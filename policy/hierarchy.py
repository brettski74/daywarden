"""Load the hierarchical household policy from YAML.

A file may include other files, and a directory include reads the ``*.yaml``
and ``*.yml`` files in that directory, in lexicographic order, without walking
into subdirectories. A file already loaded is skipped, so an include cycle is
not an error. Names are unique inside each of the six namespaces. The same
spelling may be used in two namespaces. Tasks are the sixth. ``tasks`` maps
each task type to the tasks of that type, by name, and a task is its type and
its name together, so two tasks may share a name when their types differ.
Their bodies are opaque here, except that an ``arithmetic`` body is checked by
``policy.arithmetic``, a ``parts_of_speech`` body by
``policy.parts_of_speech``, a ``skip_counting`` body by
``policy.skip_counting``, and a ``spelling`` body and its word directories by
``policy.spelling``, so a bad quiz body fails the load. A body keeps its keys
in the order written, so a parts of speech table keeps its rows in order.
S003.1 is the catalogue that reads them.

``load`` returns a new policy only when the whole configuration is valid.
A missing root file returns the previous policy unchanged. Any other problem
raises ``ConfigError`` and leaves that previous policy untouched. Decisions
from the loaded policy are made in ``policy.engine``. This module is the loader.

The loader does not stop at the first problem. Every file is read, each item
is parsed on its own, and an item's independent fields are each checked, so
one ``ConfigError`` lists every problem it can find, sorted by file in the
order the policy includes them, then by line. An item that failed still
counts as defined, so a rule that names it gets no knock-on error. A YAML
syntax error stops only the file it is in.

The byte limit is written ``bytes``. The design names that limit in prose and
shows ``time`` for the other one. Grace is ``time_grace`` and ``volume_grace``.
"""

from __future__ import annotations

import io
import json
import re
import socket
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, time
from pathlib import Path
from urllib.parse import urlparse

import yaml

from policy import arithmetic, parts_of_speech, skip_counting, spelling
from policy.buckets import divides_day
from policy.clients import Lookup, UnresolvedAddress, normalize_ip, resolve_address
from policy.clock import named_zone
from policy.pac import SWITCHES, DirectEntries, parse_extra
from policy.problems import Collector, Problems, problems_of
from policy.tasks import Task, TaskKey

# A redirect to this location goes to the task pages on the policy server.
REVISION_TASK = "revision_task"
DEFAULT_BUCKET_SECONDS = 300
DEFAULT_TIME_GRACE = 5 * 60
DEFAULT_VOLUME_GRACE = 1024**2
# A task passed today is never offered again today, so 1 is the same as 0.
DEFAULT_PASS_COOLDOWN = 1

_STR = "tag:yaml.org,2002:str"
_INT = "tag:yaml.org,2002:int"
_FLOAT = "tag:yaml.org,2002:float"
_BOOL = "tag:yaml.org,2002:bool"
_NULL = "tag:yaml.org,2002:null"
_TIMESTAMP = "tag:yaml.org,2002:timestamp"

_DURATION = re.compile(r"^(\d+)([hms])$")
_SIZE = re.compile(r"^(\d+)([bkMGT])$")
_DECIMAL = re.compile(r"^[+-]?(?:0|[1-9][0-9]*)$")
# A problem written where it is: ``path:line:column: message``.
_PLACED = re.compile(r"(.*?:\d+:\d+): (.*)", re.DOTALL)
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_START_CLOCK = re.compile(
    r"^(?:(?P<h1>[01]\d|2[0-3]):(?P<m1>[0-5]\d)|(?P<h2>[01]\d|2[0-3])(?P<m2>[0-5]\d))$"
)
_END_CLOCK = re.compile(
    r"^(?:(?P<h1>[01]\d|2[0-3]):(?P<m1>[0-5]\d)|(?P<h2>[01]\d|2[0-3])(?P<m2>[0-5]\d))"
    r"(?:\+(?P<extra>\d+))?$"
)
_DURATION_SCALE = {"h": 3600, "m": 60, "s": 1}
_SIZE_SCALE = {"b": 1, "k": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_WEEKDAY_NAME = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_TOP_KEYS = {
    "entry",
    "timezone",
    "hostname",
    "port",
    "bucket_length",
    "time_grace",
    "volume_grace",
    "include",
    "client_groups",
    "site_groups",
    "time_windows",
    "quotas",
    "rule_sets",
    "tasks",
    "proxy_configuration",
}
_SCALARS = {"entry", "timezone", "hostname", "port", "bucket_length", "time_grace", "volume_grace"}
_PORT_TEXT = re.compile(r"[1-9][0-9]*")
_SECTIONS = {"client_groups", "site_groups", "time_windows", "quotas", "rule_sets", "tasks"}
_TASK_KEYS = {
    "group",
    "groups",
    "pass_cooldown",
    "failure_cooldown",
    "available_from",
    "due_date",
    "max_skips",
    "max_passes",
    "body",
}
_CONDITIONS = {
    "time_window",
    "site_group",
    "client_group",
    "tasks_required",
    "time_remaining",
    "volume_remaining",
    "always",
}
_NAME_LIST = {
    "time_window": ("window", "windows"),
    "site_group": ("group", "groups"),
    "client_group": ("group", "groups"),
}
_CONDITION_KEYS = {
    "time_window": {"condition", "when_true", "when_false", "window", "windows"},
    "site_group": {"condition", "when_true", "when_false", "group", "groups"},
    "client_group": {"condition", "when_true", "when_false", "group", "groups"},
    "tasks_required": {"condition", "when_true", "when_false", "required"},
    "time_remaining": {"condition", "when_true", "when_false", "quota"},
    "volume_remaining": {"condition", "when_true", "when_false", "quota"},
    "always": {"condition", "when_true", "when_false"},
}
_YAML_SUFFIXES = {".yaml", ".yml"}
_HOST_LABEL = r"[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?"
_HOST_NAME = re.compile(rf"^{_HOST_LABEL}(?:\.{_HOST_LABEL})*\.?$")
_POSITION = re.compile(r"^(\d+):(\d+)")


class ConfigError(Problems):
    """The YAML policy could not be loaded. The previous policy stays in force.

    ``problems`` holds each problem found, and ``str`` lists them one per line.
    """


@dataclass(frozen=True)
class Period:
    """One span inside a named time window.

    ``weekdays`` is None when the period may start on any day. Monday is 0,
    the same numbering as ``datetime.weekday``. ``extra_days`` is the ``+n``
    suffix, and 0 when the suffix was left off. The start clock is included
    and the end clock is excluded. ``policy.engine`` decides whether a
    household-local time falls inside.
    """

    start: time
    end: time
    extra_days: int = 0
    weekdays: frozenset[int] | None = None


@dataclass(frozen=True)
class TimeWindow:
    name: str
    periods: tuple[Period, ...]


@dataclass(frozen=True)
class SiteGroup:
    name: str
    priority: int
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class ClientGroup:
    """A named set of machines.

    ``addresses`` is what the file wrote. ``resolved`` lines up with it: each
    entry is the canonical IPs used for that address on this load. A DNS name
    that did not resolve is an empty tuple when no earlier load had resolved
    it, or the IPs from the last load that did.
    """

    name: str
    addresses: tuple[str, ...]
    resolved: tuple[tuple[str, ...], ...]

    @property
    def ips(self) -> tuple[str, ...]:
        found: list[str] = []
        for batch in self.resolved:
            for ip in batch:
                if ip not in found:
                    found.append(ip)
        return tuple(found)


@dataclass(frozen=True)
class Quota:
    name: str
    ruleset: str
    time_limit: int
    byte_limit: int
    time_grace: int
    volume_grace: int


@dataclass(frozen=True)
class Action:
    kind: str
    message: str = ""
    location: str = ""
    ruleset: str | None = None
    rules: tuple[Rule, ...] | None = None


CONTINUE = Action("continue")


@dataclass(frozen=True)
class Rule:
    condition: str
    when_true: Action = CONTINUE
    when_false: Action = CONTINUE
    windows: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    required: int | None = None
    quota: str | None = None
    # Where the rule is written, so a reference it makes can be reported there.
    where: str = field(default="", compare=False, repr=False)


@dataclass(frozen=True)
class Policy:
    entry: str
    rule_sets: tuple[tuple[str, tuple[Rule, ...]], ...]
    timezone: str | None = None
    # DNS name external clients use. None means the Compose host's hostname.
    hostname: str | None = None
    # Port external clients use. None means the published POLICY_PORT.
    port: int | None = None
    bucket_length: int = DEFAULT_BUCKET_SECONDS
    time_grace: int = DEFAULT_TIME_GRACE
    volume_grace: int = DEFAULT_VOLUME_GRACE
    client_groups: tuple[ClientGroup, ...] = ()
    site_groups: tuple[SiteGroup, ...] = ()
    time_windows: tuple[TimeWindow, ...] = ()
    quotas: tuple[Quota, ...] = ()
    tasks: tuple[Task, ...] = ()
    # Which hosts the proxy auto-config file sends direct, not to the proxy.
    proxy_configuration: DirectEntries = DirectEntries()

    def rule_set(self, name: str) -> tuple[Rule, ...] | None:
        for found, rules in self.rule_sets:
            if found == name:
                return rules
        return None

    def client_group(self, name: str) -> ClientGroup | None:
        return _named(self.client_groups, name)

    def site_group(self, name: str) -> SiteGroup | None:
        return _named(self.site_groups, name)

    def time_window(self, name: str) -> TimeWindow | None:
        return _named(self.time_windows, name)

    def quota(self, name: str) -> Quota | None:
        return _named(self.quotas, name)

    def task(self, key: TaskKey) -> Task | None:
        if not isinstance(key, tuple):
            raise TypeError("a task is named by its type and its name")
        return next((task for task in self.tasks if task.key == key), None)


def _named(items, name):
    for item in items:
        if item.name == name:
            return item
    return None


@dataclass
class _RawQuota:
    name: str
    ruleset: str
    time_limit: int
    byte_limit: int
    time_grace: int | None
    volume_grace: int | None


@dataclass
class _Build:
    scalars: dict[str, tuple[object, str]] = field(default_factory=dict)
    clients: dict[str, tuple[str, ...]] = field(default_factory=dict)
    client_where: dict[str, str] = field(default_factory=dict)
    sites: dict[str, SiteGroup] = field(default_factory=dict)
    site_where: dict[str, str] = field(default_factory=dict)
    priorities: dict[int, str] = field(default_factory=dict)
    windows: dict[str, TimeWindow] = field(default_factory=dict)
    window_where: dict[str, str] = field(default_factory=dict)
    quotas: dict[str, _RawQuota] = field(default_factory=dict)
    quota_where: dict[str, str] = field(default_factory=dict)
    tasks: dict[TaskKey, Task] = field(default_factory=dict)
    task_where: dict[TaskKey, str] = field(default_factory=dict)
    rule_sets: dict[str, tuple[Rule, ...]] = field(default_factory=dict)
    ruleset_where: dict[str, str] = field(default_factory=dict)
    proxy_configuration: DirectEntries = DirectEntries()
    proxy_where: str = ""
    task_data: bool = True
    # Text to read in place of a file on disk, by canonical path.
    overrides: Mapping[Path, str] = field(default_factory=dict)
    # Each file read, in the order the policy includes it.
    files: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def fail(self, error: ValueError | str, where: str = "") -> None:
        """Note a problem. A message from outside this module is placed at ``where``."""
        if isinstance(error, str):
            self.problems.append(error)
        elif isinstance(error, ConfigError):
            self.problems.extend(error.problems)
        else:
            self.problems.extend(f"{where}: {problem}" for problem in problems_of(error))

    def attempt(self, where: str, parse: Callable, *args) -> tuple[bool, object]:
        """Run one item's parser. Return whether it worked and what it returned."""
        try:
            return True, parse(*args)
        except ValueError as error:
            self.fail(error, where)
            return False, None

    def sorted_problems(self) -> tuple[str, ...]:
        """Return each problem once, by file in include order, then by line."""
        unique = list(dict.fromkeys(self.problems))
        return tuple(sorted(unique, key=self._place))

    def _place(self, problem: str) -> tuple[int, int, int]:
        for index, name in enumerate(self.files):
            if problem.startswith(name + ":"):
                found = _POSITION.match(problem[len(name) + 1 :])
                if found is None:
                    return index, 0, 0
                return index, int(found.group(1)), int(found.group(2))
        return len(self.files), 0, 0


class _Loader(yaml.SafeLoader):
    """PyYAML loader that rejects anchors, aliases, and keeps going otherwise."""

    def __init__(self, stream: io.StringIO, source: str) -> None:
        super().__init__(stream)
        self.source = source

    def compose_node(self, parent, index):
        if self.check_event(yaml.events.AliasEvent):
            event = self.get_event()
            raise ConfigError(
                f"{_mark(self.source, event.start_mark)}: "
                f"YAML aliases are not allowed (*{event.anchor})"
            )
        event = self.peek_event()
        anchor = getattr(event, "anchor", None)
        if anchor:
            raise ConfigError(
                f"{_mark(self.source, event.start_mark)}: "
                f"YAML anchors are not allowed (&{anchor})"
            )
        return super().compose_node(parent, index)


def absolute_http_url(value: str) -> bool:
    """True when value is an absolute http or https URL the addon will accept."""
    if any(char in value for char in "\r\n\t "):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def require_yaml(path: str | Path) -> Path:
    """Return path when it names a YAML file. Raise ``ConfigError`` otherwise."""
    root = Path(path)
    if root.suffix.lower() not in {".yaml", ".yml"}:
        raise ConfigError(f"{root}: the policy must be YAML, in a file ending in .yaml or .yml")
    return root


def load(
    path: str | Path,
    *,
    previous: Policy | None = None,
    lookup: Lookup = socket.getaddrinfo,
    warn: Callable[[str], None] = lambda message: print(message, flush=True),
    task_data: bool = True,
    overrides: Mapping[Path, str] | None = None,
) -> Policy | None:
    """Load ``path`` into a new policy.

    A root path that does not end in ``.yaml`` or ``.yml`` raises
    ``ConfigError``, whether or not the file is there. A missing root file
    returns ``previous``, including when ``previous`` is None. A present root
    that is not valid YAML policy raises ``ConfigError``.
    ``previous`` is only read, so a failed load leaves it as it was. Pass the
    last successful policy so a DNS name that fails this time can keep the
    addresses that name resolved to then.

    With ``task_data`` false, task bodies are checked without reading the
    household data directory, such as the spelling word pools. A service that
    does not mount that directory loads this way.

    ``overrides`` maps a file's canonical path to text read in its place, so
    an edit can be checked before it is written. A file not written yet, in
    an included directory, is read as though it were there, even when the
    directory is not there either.
    """
    root = require_yaml(path)
    if not root.is_file():
        return previous
    build = _Build(task_data=task_data, overrides=dict(overrides or {}))
    seen: set[Path] = set()
    _load_file(root, root.resolve(), seen, build)
    return _finish(build, previous, lookup, warn)


def task_files(path: str | Path) -> dict[TaskKey, Path]:
    """Return the file that defines each task, by type and name, following the includes.

    Nothing is checked beyond what finding the tasks needs, and the data
    directory is not read. A file that cannot be read defines nothing.
    """
    root = require_yaml(path)
    if not root.is_file():
        return {}
    build = _Build(task_data=False)
    _load_file(root, root.resolve(), set(), build)
    return {key: Path(where.rsplit(":", 2)[0]) for key, where in build.task_where.items()}


def compose(text: str, source: Path) -> yaml.Node | None:
    """Return the YAML node tree of one policy file's text, as the loader reads it."""
    return _compose(text, source)


def node_data(node: yaml.Node, where: str):
    """Return the value a node holds, as the loader reads a task body. Raises ``ConfigError``."""
    return _data(node, where)


def _load_file(path: Path, canonical: Path, seen: set[Path], build: _Build) -> None:
    if canonical in seen:
        return
    seen.add(canonical)
    build.files.append(str(canonical))
    try:
        text = build.overrides[canonical] if canonical in build.overrides else canonical.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        build.fail(f"{canonical}: {exc}")
        return
    ok, node = build.attempt(str(canonical), _compose, text, canonical)
    if not ok:
        return
    if not isinstance(node, yaml.MappingNode):
        build.fail(f"{canonical}: the file must be a mapping")
        return
    for raw, where in _absorb(node, build):
        _load_included(raw, where, path.parent, seen, build)


def _load_included(raw: str, where: str, base: Path, seen: set[Path], build: _Build) -> None:
    if Path(raw).is_absolute():
        build.fail(f"{where}: included path {raw!r} must be relative to the file that names it")
        return
    target = base / raw
    try:
        canonical = target.resolve()
    except OSError as exc:
        build.fail(f"{where}: included path {raw!r}: {exc}")
        return
    if canonical in seen:
        return
    unwritten = [
        path for path in build.overrides if path.parent == canonical and path.suffix in _YAML_SUFFIXES and not path.exists()
    ]
    if canonical.is_dir() or unwritten:
        seen.add(canonical)
        children = unwritten + [
            child
            for child in (canonical.iterdir() if canonical.is_dir() else ())
            if child.is_file() and child.suffix in _YAML_SUFFIXES
        ]
        for child in sorted(children, key=lambda item: item.name):
            _load_file(child, child.resolve(), seen, build)
        return
    if canonical.is_file():
        _load_file(target, canonical, seen, build)
        return
    build.fail(f"{where}: included path {raw!r} does not exist")


def _compose(text: str, source: Path) -> yaml.Node | None:
    stream = io.StringIO(text)
    stream.name = str(source)
    loader = _Loader(stream, str(source))
    try:
        try:
            return loader.get_single_node()
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            place = str(source) if mark is None else _mark(source, mark)
            raise ConfigError(f"{place}: {exc}") from exc
    finally:
        loader.dispose()


def _absorb(node: yaml.MappingNode, build: _Build) -> list[tuple[str, str]]:
    """Take one file's settings and sections. Return its includes and where each is written."""
    pairs = _lenient_pairs(node, build)
    for key, key_node in _key_nodes(node):
        if key == "revision_task":
            build.fail(f"{_at(pairs[key])}: revision_task is not set in the policy file")
        elif key not in _TOP_KEYS:
            build.fail(f"{_at(key_node)}: unknown setting {key}")
    for key, value in pairs.items():
        if key not in _SCALARS:
            continue
        where = _at(value)
        if key in build.scalars:
            build.fail(f"{where}: {key} is already set at {build.scalars[key][1]}")
            continue
        ok, scalar = build.attempt(where, _scalar, key, value, where)
        build.scalars[key] = (scalar if ok else _BROKEN, where)
    for key, take in _TAKERS.items():
        if key in pairs:
            take(pairs[key], build)
    if "include" not in pairs:
        return []
    return _include_list(pairs["include"], build)


# Stands in for a setting or an item that failed, so it still counts as written.
_BROKEN = object()


def _scalar(key: str, node: yaml.Node, where: str) -> object:
    if key == "entry":
        return _text(node, where)
    if key == "timezone":
        name = _text(node, where)
        try:
            named_zone(name)
        except ValueError as exc:
            raise ConfigError(f"{where}: {exc}") from exc
        return name
    if key == "hostname":
        return _hostname(node, where)
    if key == "port":
        return _port_number(node, where)
    if key == "bucket_length":
        length = _duration(node, where)
        if length < 1:
            raise ConfigError(f"{where}: bucket_length must be at least one second")
        if not divides_day(length):
            raise ConfigError(
                f"{where}: bucket_length must divide a 24-hour day "
                "with nothing left over, so the buckets meet midnight"
            )
        return length
    if key == "time_grace":
        return _non_negative(_duration(node, where), where)
    return _non_negative(_size(node, where), where)


def _take_clients(node: yaml.Node, build: _Build) -> None:
    for name, body, where in _entities(node, "client group", build):
        if not _reserve(name, where, "client group", build):
            continue
        ok, addresses = build.attempt(where, _addresses, body, where)
        _claim(build, build.clients, build.client_where, name, addresses if ok else _BROKEN, where, "client group")


def _take_sites(node: yaml.Node, build: _Build) -> None:
    for name, body, where in _entities(node, "site group", build):
        if not _reserve(name, where, "site group", build):
            continue
        ok, group = build.attempt(where, _site, name, body, where)
        if not _claim(build, build.sites, build.site_where, name, group if ok else _BROKEN, where, "site group"):
            continue
        if not ok:
            continue
        if group.priority in build.priorities:
            other = build.priorities[group.priority]
            build.fail(f"{where}: site groups {other!r} and {name!r} both have priority {group.priority}")
        else:
            build.priorities[group.priority] = name


def _take_windows(node: yaml.Node, build: _Build) -> None:
    for name, body, where in _entities(node, "time window", build):
        ok, window = build.attempt(where, _window, name, body, where)
        _claim(build, build.windows, build.window_where, name, window if ok else _BROKEN, where, "time window")


def _take_quotas(node: yaml.Node, build: _Build) -> None:
    for name, body, where in _entities(node, "quota", build):
        ok, quota = build.attempt(where, _quota, name, body, where)
        _claim(build, build.quotas, build.quota_where, name, quota if ok else _BROKEN, where, "quota")


def _take_tasks(node: yaml.Node, build: _Build) -> None:
    """Take ``tasks``, a mapping of task types to mappings of task names. A task is its type and name together."""
    for kind, names, _where in _entities(node, "task type", build):
        for name, body, where in _entities(names, "task", build, shown=lambda key, kind=kind: f"task {str(TaskKey(kind, key))!r}"):
            key = TaskKey(kind, name)
            named = f"task {str(key)!r}"
            try:
                task = _task(key, body, where, build.task_data)
            except ValueError as error:
                build.problems.extend(_about(problem, named) for problem in problems_of(error))
                task = _BROKEN
            if key in build.task_where:
                build.fail(f"{where}: {named} is already defined at {build.task_where[key]}")
                continue
            build.task_where[key] = where
            if task is not _BROKEN:
                build.tasks[key] = task


def _about(problem: str, named: str) -> str:
    """Return a problem with the task it is about named after where it is written."""
    if named in problem:
        return problem
    found = _PLACED.match(problem)
    if found is None:
        return f"{named}: {problem}"
    return f"{found.group(1)}: {named}: {found.group(2)}"


def _take_proxy_configuration(node: yaml.Node, build: _Build) -> None:
    """Take the one ``proxy_configuration`` section. Every mistake in it is noted where it is written."""
    where = _at(node)
    if build.proxy_where:
        build.fail(f"{where}: proxy_configuration is already set at {build.proxy_where}")
        return
    build.proxy_where = where
    if not isinstance(node, yaml.MappingNode):
        build.fail(f"{where}: proxy_configuration must be a mapping")
        return
    pairs = _lenient_pairs(node, build)
    for key, key_node in _key_nodes(node):
        if key != "direct":
            build.fail(f"{_at(key_node)}: unknown setting proxy_configuration.{key}")
    direct = pairs.get("direct")
    if direct is None:
        return
    if not isinstance(direct, yaml.MappingNode):
        build.fail(f"{_at(direct)}: proxy_configuration.direct must be a mapping")
        return
    entries = _lenient_pairs(direct, build)
    for key, key_node in _key_nodes(direct):
        if key not in SWITCHES and key != "extra":
            build.fail(f"{_at(key_node)}: unknown setting proxy_configuration.direct.{key}")
    switches: dict[str, bool] = {}
    for name in SWITCHES:
        value = entries.get(name)
        if value is None:
            continue
        if not isinstance(value, yaml.ScalarNode) or value.tag != _BOOL:
            build.fail(f"{_at(value)}: proxy_configuration.direct.{name} must be true or false")
            continue
        switches[name] = value.value.lower() in {"y", "yes", "true", "on"}
    extra: list = []
    if "extra" in entries:
        label = "proxy_configuration.direct.extra"
        ok, items = build.attempt(_at(entries["extra"]), _sequence, entries["extra"], f"{_at(entries['extra'])}: {label}")
        for item in items if ok else ():
            parsed, text = build.attempt(_at(item), _text, item, f"{_at(item)}: {label} item")
            if not parsed:
                continue
            try:
                found = parse_extra(text)
            except ValueError as error:
                build.fail(f"{_at(item)}: {label}: {error}")
                continue
            if found not in extra:
                extra.append(found)
    build.proxy_configuration = DirectEntries(**switches, extra=tuple(extra))


_QUIZ_BODIES: dict[str, Callable[[Mapping], object]] = {
    arithmetic.ARITHMETIC: arithmetic.parse_settings,
    parts_of_speech.PARTS_OF_SPEECH: parts_of_speech.parse_settings,
    skip_counting.SKIP_COUNTING: skip_counting.parse_settings,
    spelling.SPELLING: spelling.check_body,
}

_QUIZ_FIELDS: dict[str, Callable[[Mapping], object]] = {
    **_QUIZ_BODIES,
    spelling.SPELLING: spelling.parse_settings,
}


def _task(key: TaskKey, node: yaml.Node, where: str, task_data: bool = True) -> Task:
    pairs = _pairs(node)
    fields = Collector()
    fields.take(_reject_unknown, set(pairs), _TASK_KEYS, where)
    groups = fields.take(_task_groups, pairs, where)

    def optional(key: str, parse: Callable, *args, **kwargs):
        if key not in pairs:
            return None
        return fields.take(parse, pairs[key], f"{_at(pairs[key])}: {key}", *args, **kwargs)

    cooldown = optional("pass_cooldown", _whole, minimum=0)
    failure = optional("failure_cooldown", _whole, minimum=0)
    available = optional("available_from", _calendar_day)
    due = optional("due_date", _calendar_day)
    skips = optional("max_skips", _whole, minimum=0)
    passes = optional("max_passes", _whole, minimum=0)
    document = {} if "body" not in pairs else fields.take(_document, pairs["body"], f"{where}: body")
    parse = (_QUIZ_BODIES if task_data else _QUIZ_FIELDS).get(key.type)
    if parse is not None and document is not None:
        try:
            parse(document)
        except ValueError as exc:
            for problem in problems_of(exc):
                fields.add(f"{_body_at(pairs.get('body'), problem, where)}: task {str(key)!r}: body.{problem}")
    fields.finish(ConfigError)
    return Task(
        key.name,
        key.type,
        groups,
        DEFAULT_PASS_COOLDOWN if cooldown is None else cooldown,
        json.dumps(document, ensure_ascii=False, separators=(",", ":")),
        failure,
        available,
        due,
        skips,
        passes,
    )


def _task_groups(pairs: Mapping[str, yaml.Node], where: str) -> tuple[str, ...]:
    groups = _one_list(pairs, "group", "groups", where)
    seen: set[str] = set()
    for group in groups:
        if group in seen:
            raise ConfigError(f"{where}: client group {group!r} is listed twice")
        seen.add(group)
    return groups


def _body_at(node: yaml.Node | None, problem: str, where: str) -> str:
    """Return where the body field a task type's problem names is written, or ``where``."""
    if isinstance(node, yaml.MappingNode):
        field_name = re.split(r"[:\s.]", problem, maxsplit=1)[0]
        for key_node, _value in node.value:
            if isinstance(key_node, yaml.ScalarNode) and key_node.value == field_name:
                return _at(key_node)
    return where


def _take_rule_sets(node: yaml.Node, build: _Build) -> None:
    for name, body, where in _entities(node, "rule set", build):
        ok, bodies = build.attempt(where, _sequence, body, where)
        rules: list[Rule] = []
        for number, item in enumerate(bodies if ok else (), start=1):
            parsed, rule = build.attempt(where, _rule, item, f"{_at(item)}: rule {number}")
            if parsed:
                rules.append(rule)
        # A rule set with a bad rule keeps its good rules, so their references are still checked.
        _claim(build, build.rule_sets, build.ruleset_where, name, tuple(rules), where, "rule set")


def _entities(node: yaml.Node, label: str, build: _Build, shown: Callable[[str], str] | None = None):
    if not isinstance(node, yaml.MappingNode):
        build.fail(f"{_at(node)}: must be a mapping")
        return
    for name, body in _lenient_pairs(node, build, shown).items():
        if not name.strip():
            build.fail(f"{_at(body)}: {label} name must not be empty")
            continue
        yield name.strip(), body, _at(body)


def _claim(build: _Build, table: dict, where_table: dict, name: str, value, where: str, label: str) -> bool:
    """Record a named item. A failed item counts as defined but is not kept. False for a duplicate."""
    if name in where_table:
        build.fail(f"{where}: {label} {name!r} is already defined at {where_table[name]}")
        return False
    where_table[name] = where
    if value is not _BROKEN:
        table[name] = value
    return True


def _reserve(name: str, where: str, label: str, build: _Build) -> bool:
    if name == "default":
        build.fail(f"{where}: {label} name 'default' is reserved")
        return False
    return True


def _addresses(node: yaml.Node, where: str) -> tuple[str, ...]:
    pairs = _pairs(node)
    _reject_unknown(set(pairs), {"addresses"}, where)
    if "addresses" not in pairs:
        raise ConfigError(f"{where}: addresses is required")
    values = _string_list(pairs["addresses"], f"{where}: addresses")
    if not values:
        raise ConfigError(f"{where}: addresses must list at least one address")
    problems = Collector()
    seen: set[str] = set()
    for item, address in zip(pairs["addresses"].value, values, strict=True):
        if address in seen:
            problems.add(f"{_at(item)}: {address!r} is listed twice in this client group")
        elif not _address(address):
            problems.add(f"{_at(item)}: {address!r} is not an IP address or a host name")
        seen.add(address)
    problems.finish(ConfigError)
    return values


def _address(text: str) -> bool:
    """True for an IP address, or for text that could be a DNS host name."""
    if normalize_ip(text) is not None:
        return True
    if len(text) > 253 or _HOST_NAME.fullmatch(text) is None:
        return False
    # A name whose last label is all digits is a mistyped IPv4 address.
    return not text.rstrip(".").rsplit(".", 1)[-1].isdigit()


def _site(name: str, node: yaml.Node, where: str) -> SiteGroup:
    pairs = _pairs(node)
    fields = Collector()
    fields.take(_reject_unknown, set(pairs), {"priority", "patterns"}, where)
    for key in ("priority", "patterns"):
        if key not in pairs:
            fields.add(f"{where}: {key} is required")
    patterns = None
    if "patterns" in pairs:
        patterns = fields.take(_string_list, pairs["patterns"], f"{where}: patterns")
        if patterns == ():
            fields.add(f"{where}: patterns must list at least one pattern")
    priority = None if "priority" not in pairs else fields.take(_whole, pairs["priority"], f"{where}: priority")
    fields.finish(ConfigError)
    return SiteGroup(name, priority, patterns)


def _window(name: str, node: yaml.Node, where: str) -> TimeWindow:
    pairs = _pairs(node)
    _reject_unknown(set(pairs), {"periods"}, where)
    if "periods" not in pairs:
        raise ConfigError(f"{where}: periods is required")
    bodies = _sequence(pairs["periods"], f"{where}: periods")
    if not bodies:
        raise ConfigError(f"{where}: a time window needs at least one period")
    fields = Collector()
    periods = tuple(
        fields.take(_period, body, f"{_at(body)}: period {number}") for number, body in enumerate(bodies, start=1)
    )
    fields.finish(ConfigError)
    return TimeWindow(name, periods)


def _period(node: yaml.Node, where: str) -> Period:
    pairs = _pairs(node)
    fields = Collector()
    fields.take(_reject_unknown, set(pairs), {"start", "end", "day", "days"}, where)
    if "start" not in pairs or "end" not in pairs:
        fields.add(f"{where}: start and end are required")
    start = None if "start" not in pairs else fields.take(_clock, pairs["start"], f"{where}: start", suffix=False)
    end = None if "end" not in pairs else fields.take(_clock, pairs["end"], f"{where}: end", suffix=True)
    days = fields.take(_days, pairs, where)
    fields.finish(ConfigError)
    return Period(start[0], end[0], end[1], days)


def _days(pairs: Mapping[str, yaml.Node], where: str) -> frozenset[int] | None:
    has_day = "day" in pairs
    has_days = "days" in pairs
    if has_day and has_days:
        raise ConfigError(f"{where}: specify day or days, not both")
    if not has_day and not has_days:
        return None
    if has_day:
        return _weekday_set(pairs["day"], f"{where}: day", allow_range=False)
    return _weekday_set(pairs["days"], f"{where}: days", allow_range=True)


def _weekday_set(node: yaml.Node, where: str, *, allow_range: bool) -> frozenset[int]:
    if isinstance(node, yaml.SequenceNode):
        if not node.value:
            raise ConfigError(f"{where}: an empty day list is not allowed")
        if not allow_range:
            raise ConfigError(f"{where}: day takes one weekday name and does not accept a range")
        found: list[int] = []
        for item in node.value:
            for day in _day_token(item, where, allow_range=True):
                _add_day(found, day, where)
        return frozenset(found)
    found = []
    for day in _day_token(node, where, allow_range=allow_range):
        _add_day(found, day, where)
    return frozenset(found)


def _add_day(found: list[int], day: int, where: str) -> None:
    if day in found:
        raise ConfigError(f"{where}: {_WEEKDAY_NAME[day]} is listed twice")
    found.append(day)


def _day_token(node: yaml.Node, where: str, *, allow_range: bool) -> list[int]:
    if not isinstance(node, yaml.ScalarNode) or node.tag != _STR:
        shown = node.value if isinstance(node, yaml.ScalarNode) else node
        raise ConfigError(f"{where}: {shown!r} is not a weekday")
    text = node.value.strip().lower()
    if "-" not in text:
        return [_weekday_number(text, where)]
    if not allow_range:
        raise ConfigError(f"{where}: day does not accept a range; write the range as days")
    left, _sep, right = text.partition("-")
    if not left.strip() or not right.strip() or "-" in right:
        raise ConfigError(f"{where}: {text!r} is not a weekday range")
    start = _weekday_number(left.strip(), where)
    end = _weekday_number(right.strip(), where)
    if start == end:
        raise ConfigError(f"{where}: {text!r} starts and ends on the same day; write the day once")
    days: list[int] = []
    day = start
    while True:
        days.append(day)
        if day == end:
            break
        day = (day + 1) % 7
    return days


def _weekday_number(name: str, where: str) -> int:
    try:
        return _WEEKDAYS[name]
    except KeyError:
        raise ConfigError(f"{where}: {name!r} is not a weekday") from None


def _clock(node: yaml.Node, where: str, *, suffix: bool) -> tuple[time, int]:
    if isinstance(node, yaml.ScalarNode) and node.tag == _INT:
        raise ConfigError(f"{where}: an unquoted clock is not a time")
    if not isinstance(node, yaml.ScalarNode) or node.tag != _STR or node.style not in {"'", '"'}:
        raise ConfigError(f'{where} must be a quoted time like "07:00" or "0700"')
    text = node.value.strip()
    if re.search(r"\+\s*-", text):
        raise ConfigError(f"{where}: the +n suffix cannot be negative")
    if not suffix and "+" in text:
        raise ConfigError(f"{where}: start does not take a +n suffix")
    match = (_END_CLOCK if suffix else _START_CLOCK).fullmatch(text)
    if match is None:
        if suffix and "+" in text:
            raise ConfigError(f"{where}: the +n suffix must be a whole number of zero or more")
        raise ConfigError(f'{where} must be a quoted time like "07:00" or "0700"')
    hour = int(match.group("h1") if match.group("h1") is not None else match.group("h2"))
    minute = int(match.group("m1") if match.group("m1") is not None else match.group("m2"))
    extra = match.groupdict().get("extra")
    return time(hour, minute), 0 if not extra else int(extra)


def _quota(name: str, node: yaml.Node, where: str) -> _RawQuota:
    pairs = _pairs(node)
    fields = Collector()
    fields.take(_reject_unknown, set(pairs), {"time", "bytes", "ruleset", "time_grace", "volume_grace"}, where)
    if "ruleset" not in pairs:
        fields.add(f"{where}: ruleset is required")

    def optional(key: str, parse: Callable):
        return None if key not in pairs else fields.take(parse, pairs[key], f"{_at(pairs[key])}: {key}")

    ruleset = optional("ruleset", _text)
    time_limit = optional("time", _duration) or 0
    byte_limit = optional("bytes", _size) or 0
    time_grace = optional("time_grace", _duration)
    volume_grace = optional("volume_grace", _size)
    fields.finish(ConfigError)
    return _RawQuota(name, ruleset, time_limit, byte_limit, time_grace, volume_grace)


def _rules(node: yaml.Node, where: str) -> tuple[Rule, ...]:
    bodies = _sequence(node, where)
    return tuple(_rule(body, f"{where}: rule {number}") for number, body in enumerate(bodies, start=1))


def _rule(node: yaml.Node, where: str) -> Rule:
    pairs = _pairs(node)
    if "condition" not in pairs:
        raise ConfigError(f"{where}: condition is required")
    condition = _text(pairs["condition"], f"{where}: condition")
    if condition not in _CONDITIONS:
        raise ConfigError(f"{where}: unknown condition {condition!r}")
    _reject_unknown(set(pairs), _CONDITION_KEYS[condition], where)
    windows: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    required: int | None = None
    quota: str | None = None
    if condition in _NAME_LIST:
        singular, plural = _NAME_LIST[condition]
        names = _one_list(pairs, singular, plural, where)
        if condition == "time_window":
            windows = names
        else:
            groups = names
    elif condition == "tasks_required":
        if "required" not in pairs:
            raise ConfigError(f"{where}: required is required")
        required = _whole(pairs["required"], f"{where}: required", minimum=0)
    elif condition in {"time_remaining", "volume_remaining"}:
        if "quota" not in pairs:
            raise ConfigError(f"{where}: quota is required")
        quota = _text(pairs["quota"], f"{where}: quota")
    when_true = _action(pairs["when_true"], f"{where}: when_true") if "when_true" in pairs else CONTINUE
    when_false = _action(pairs["when_false"], f"{where}: when_false") if "when_false" in pairs else CONTINUE
    return Rule(condition, when_true, when_false, windows, groups, required, quota, where)


def _one_list(pairs: Mapping[str, yaml.Node], singular: str, plural: str, where: str) -> tuple[str, ...]:
    has_one = singular in pairs
    has_many = plural in pairs
    if has_one and has_many:
        raise ConfigError(f"{where}: specify {singular} or {plural}, not both")
    if not has_one and not has_many:
        raise ConfigError(f"{where}: {singular} or {plural} is required")
    if has_one:
        return (_text(pairs[singular], f"{where}: {singular}"),)
    names = _string_list(pairs[plural], f"{where}: {plural}")
    if not names:
        raise ConfigError(f"{where}: {plural} must name at least one")
    return names


def _action(node: yaml.Node, where: str) -> Action:
    pairs = _pairs(node)
    if "action" not in pairs:
        raise ConfigError(f"{where}: action is required")
    kind = _text(pairs["action"], f"{where}: action")
    if kind in {"continue", "allow"}:
        _reject_unknown(set(pairs), {"action"}, where)
        return Action(kind)
    if kind == "deny":
        _reject_unknown(set(pairs), {"action", "message"}, where)
        if "message" not in pairs:
            raise ConfigError(f"{where}: deny needs a message")
        return Action("deny", message=_text(pairs["message"], f"{where}: message"))
    if kind == "redirect":
        _reject_unknown(set(pairs), {"action", "location"}, where)
        if "location" not in pairs:
            raise ConfigError(f"{where}: redirect needs a location")
        location = _text(pairs["location"], f"{where}: location")
        if location != REVISION_TASK and not absolute_http_url(location):
            raise ConfigError(
                f"{where}: location must be an absolute http or https URL, or revision_task"
            )
        return Action("redirect", location=location)
    if kind == "evaluate":
        _reject_unknown(set(pairs), {"action", "ruleset", "rules"}, where)
        has_set = "ruleset" in pairs
        has_rules = "rules" in pairs
        if has_set and has_rules:
            raise ConfigError(f"{where}: evaluate takes a ruleset or an inline rules list, not both")
        if not has_set and not has_rules:
            raise ConfigError(f"{where}: evaluate needs a ruleset or an inline rules list")
        if has_set:
            return Action("evaluate", ruleset=_text(pairs["ruleset"], f"{where}: ruleset"))
        return Action("evaluate", rules=_rules(pairs["rules"], f"{where}: rules"))
    raise ConfigError(f"{where}: unknown action {kind!r}")


def _include_list(node: yaml.Node, build: _Build) -> list[tuple[str, str]]:
    where = _at(node)
    ok, items = build.attempt(where, _sequence, node, f"{where}: include")
    found: list[tuple[str, str]] = []
    for item in items if ok else ():
        parsed, raw = build.attempt(where, _text, item, f"{_at(item)}: include")
        if parsed:
            found.append((raw, _at(item)))
    return found


_TAKERS: dict[str, Callable[[yaml.Node, _Build], None]] = {
    "client_groups": _take_clients,
    "site_groups": _take_sites,
    "time_windows": _take_windows,
    "quotas": _take_quotas,
    "rule_sets": _take_rule_sets,
    "tasks": _take_tasks,
    "proxy_configuration": _take_proxy_configuration,
}


def _finish(
    build: _Build,
    previous: Policy | None,
    lookup: Lookup,
    warn: Callable[[str], None],
) -> Policy:
    root = build.files[0]
    if "entry" not in build.scalars:
        build.fail(f"{root}: entry is required")
    _check_references(build)
    _check_cycles(build)
    clients = _resolve_clients(build, previous, lookup, warn)
    if build.problems:
        raise ConfigError(*build.sorted_problems())
    entry = str(build.scalars["entry"][0])
    timezone = build.scalars["timezone"][0] if "timezone" in build.scalars else None
    hostname = build.scalars["hostname"][0] if "hostname" in build.scalars else None
    port = build.scalars["port"][0] if "port" in build.scalars else None
    bucket_length = (
        int(build.scalars["bucket_length"][0])
        if "bucket_length" in build.scalars
        else DEFAULT_BUCKET_SECONDS
    )
    time_grace = (
        int(build.scalars["time_grace"][0]) if "time_grace" in build.scalars else DEFAULT_TIME_GRACE
    )
    volume_grace = (
        int(build.scalars["volume_grace"][0]) if "volume_grace" in build.scalars else DEFAULT_VOLUME_GRACE
    )
    quotas = tuple(
        Quota(
            raw.name,
            raw.ruleset,
            raw.time_limit,
            raw.byte_limit,
            time_grace if raw.time_grace is None else raw.time_grace,
            volume_grace if raw.volume_grace is None else raw.volume_grace,
        )
        for raw in build.quotas.values()
    )
    return Policy(
        entry,
        tuple(build.rule_sets.items()),
        None if timezone is None else str(timezone),
        None if hostname is None else str(hostname),
        None if port is None else int(port),
        bucket_length,
        time_grace,
        volume_grace,
        clients,
        tuple(build.sites.values()),
        tuple(build.windows.values()),
        quotas,
        tuple(build.tasks.values()),
        build.proxy_configuration,
    )


def _check_references(build: _Build) -> None:
    """Note every name that names nothing. An item that failed to parse still counts as defined."""
    entry, where = build.scalars.get("entry", (_BROKEN, ""))
    if entry is not _BROKEN and entry not in build.ruleset_where:
        build.fail(f"{where}: entry {entry!r} does not name a rule set")
    known = {
        "site group": set(build.site_where) | {"default"},
        "client group": set(build.client_where) | {"default"},
        "time window": set(build.window_where),
        "quota": set(build.quota_where),
        "rule set": set(build.ruleset_where),
    }
    for key, task in build.tasks.items():
        for group in task.groups:
            if group not in known["client group"]:
                build.fail(f"{build.task_where[key]}: task {str(key)!r}: unknown client group {group!r}")
    for name, raw in build.quotas.items():
        if raw.ruleset not in known["rule set"]:
            build.fail(f"{build.quota_where[name]}: quota {name!r}: unknown rule set {raw.ruleset!r}")
    for rules in build.rule_sets.values():
        _check_rules(rules, known, build)


def _check_rules(rules: tuple[Rule, ...], known: Mapping[str, set[str]], build: _Build) -> None:
    for rule in rules:
        if rule.condition == "time_window":
            _known(rule.windows, known, "time window", rule.where, build)
        elif rule.condition in {"site_group", "client_group"}:
            _known(rule.groups, known, rule.condition.replace("_", " "), rule.where, build)
        elif rule.condition in {"time_remaining", "volume_remaining"}:
            _known((rule.quota,), known, "quota", rule.where, build)
        for branch, action in (("when_true", rule.when_true), ("when_false", rule.when_false)):
            if action.kind != "evaluate":
                continue
            if action.ruleset is not None:
                _known((action.ruleset,), known, "rule set", f"{rule.where}: {branch}", build)
            elif action.rules is not None:
                _check_rules(action.rules, known, build)


def _known(names: tuple[str, ...], known: Mapping[str, set[str]], label: str, where: str, build: _Build) -> None:
    for name in names:
        if name not in known[label]:
            build.fail(f"{where}: unknown {label} {name!r}")


def _check_cycles(build: _Build) -> None:
    """Note each evaluate cycle once, at the rule set it was first reached from."""
    rule_sets = build.rule_sets
    done: set[int] = set()

    def walk(rules: tuple[Rule, ...], label: str, labels: tuple[str, ...], ids: tuple[int, ...], where: str) -> None:
        node = id(rules)
        if node in ids:
            start = ids.index(node)
            cycle = " -> ".join(labels[start:] + (label,))
            build.fail(f"{where}: evaluate cycle: {cycle}")
            return
        if node in done:
            return
        labels = labels + (label,)
        ids = ids + (node,)
        for index, rule in enumerate(rules, start=1):
            for branch, action in (("when_true", rule.when_true), ("when_false", rule.when_false)):
                if action.kind != "evaluate":
                    continue
                if action.ruleset is not None:
                    if action.ruleset in rule_sets:
                        walk(rule_sets[action.ruleset], action.ruleset, labels, ids, where)
                elif action.rules is not None:
                    walk(action.rules, f"{label} rule {index} {branch}", labels, ids, where)
        done.add(node)

    for name, rules in rule_sets.items():
        walk(rules, name, (), (), build.ruleset_where[name])


def _resolve_clients(
    build: _Build,
    previous: Policy | None,
    lookup: Lookup,
    warn: Callable[[str], None],
) -> tuple[ClientGroup, ...]:
    """Resolve each client group. Note every address that is listed twice."""
    groups: list[ClientGroup] = []
    owners: dict[str, str] = {}
    for name, addresses in build.clients.items():
        where = build.client_where[name]
        resolved: list[tuple[str, ...]] = []
        seen_here: dict[str, str] = {}
        for address in addresses:
            ips = _resolve_one(name, address, previous, lookup, warn)
            for ip in ips:
                if ip in seen_here:
                    build.fail(
                        f"{where}: {ip} is listed twice in client group {name!r}, "
                        f"from {seen_here[ip]!r} and {address!r}"
                    )
                elif ip in owners:
                    build.fail(f"{where}: {ip} belongs to client groups {owners[ip]!r} and {name!r}")
                else:
                    seen_here[ip] = address
                    owners[ip] = name
            resolved.append(ips)
        groups.append(ClientGroup(name, addresses, tuple(resolved)))
    return tuple(groups)


def _resolve_one(
    group: str,
    address: str,
    previous: Policy | None,
    lookup: Lookup,
    warn: Callable[[str], None],
) -> tuple[str, ...]:
    try:
        return resolve_address(address, lookup)
    except UnresolvedAddress as exc:
        kept = _previous_ips(previous, group, address)
        if kept:
            warn(f"client group {group}: {exc}; keeping {', '.join(kept)}")
            return kept
        warn(f"client group {group}: {exc}; it has no IP until the name resolves")
        return ()


def _previous_ips(previous: Policy | None, group: str, address: str) -> tuple[str, ...]:
    if previous is None:
        return ()
    found = previous.client_group(group)
    if found is None:
        return ()
    for written, ips in zip(found.addresses, found.resolved, strict=True):
        if written == address and ips:
            return ips
    return ()


def _pairs(node: yaml.Node) -> dict[str, yaml.Node]:
    if not isinstance(node, yaml.MappingNode):
        raise ConfigError(f"{_at(node)}: must be a mapping")
    found: dict[str, yaml.Node] = {}
    for key_node, value_node in node.value:
        if not isinstance(key_node, yaml.ScalarNode) or key_node.tag != _STR:
            shown = key_node.value if isinstance(key_node, yaml.ScalarNode) else key_node.id
            raise ConfigError(f"{_at(key_node)}: mapping keys must be strings, not {shown!r}")
        key = key_node.value
        if key in found:
            raise ConfigError(f"{_at(key_node)}: duplicate key {key!r}")
        found[key] = value_node
    return found


def _lenient_pairs(
    node: yaml.Node, build: _Build, shown: Callable[[str], str] | None = None
) -> dict[str, yaml.Node]:
    """Like ``_pairs``, but a bad or repeated key is noted and skipped, and the rest are kept.

    ``shown`` says what a repeated key names, such as ``task 'spelling/week-1'``.
    """
    if not isinstance(node, yaml.MappingNode):
        build.fail(f"{_at(node)}: must be a mapping")
        return {}
    found: dict[str, yaml.Node] = {}
    first: dict[str, yaml.Node] = {}
    for key_node, value_node in node.value:
        if not isinstance(key_node, yaml.ScalarNode) or key_node.tag != _STR:
            shown = key_node.value if isinstance(key_node, yaml.ScalarNode) else key_node.id
            build.fail(f"{_at(key_node)}: mapping keys must be strings, not {shown!r}")
        elif key_node.value in found:
            if shown is None:
                build.fail(f"{_at(key_node)}: duplicate key {key_node.value!r}, already at {_at(first[key_node.value])}")
            else:
                build.fail(f"{_at(key_node)}: {shown(key_node.value)} is already defined at {_at(first[key_node.value])}")
        else:
            found[key_node.value] = value_node
            first[key_node.value] = key_node
    return found


def _key_nodes(node: yaml.MappingNode) -> list[tuple[str, yaml.Node]]:
    """Return each string key of a mapping with its own node, for where it is written."""
    return [
        (key_node.value, key_node)
        for key_node, _value in node.value
        if isinstance(key_node, yaml.ScalarNode) and key_node.tag == _STR
    ]


def _sequence(node: yaml.Node, where: str) -> list[yaml.Node]:
    if not isinstance(node, yaml.SequenceNode):
        raise ConfigError(f"{where} must be a list")
    return list(node.value)


def _string_list(node: yaml.Node, where: str) -> tuple[str, ...]:
    return tuple(_text(item, where) for item in _sequence(node, where))


def _calendar_day(node: yaml.Node, where: str) -> date:
    if not isinstance(node, yaml.ScalarNode) or node.tag not in {_STR, _TIMESTAMP}:
        raise ConfigError(f"{where} must be a date like 2026-10-31")
    text = node.value.strip()
    if not _DAY.fullmatch(text):
        raise ConfigError(f"{where} must be a date like 2026-10-31")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ConfigError(f"{where} must be a date like 2026-10-31") from exc


def _document(node: yaml.Node, where: str) -> dict:
    if not isinstance(node, yaml.MappingNode):
        raise ConfigError(f"{where} must be a mapping")
    return {key: _data(value, f"{where}.{key}") for key, value in _pair_items(node)}


def _pair_items(node: yaml.MappingNode) -> list[tuple[str, yaml.Node]]:
    found: list[tuple[str, yaml.Node]] = []
    seen: set[str] = set()
    for key_node, value_node in node.value:
        key = _text(key_node, _at(key_node))
        if key in seen:
            raise ConfigError(f"{_at(key_node)}: duplicate key {key!r}")
        seen.add(key)
        found.append((key, value_node))
    return found


def _data(node: yaml.Node, where: str):
    if isinstance(node, yaml.MappingNode):
        return {key: _data(value, f"{where}.{key}") for key, value in _pair_items(node)}
    if isinstance(node, yaml.SequenceNode):
        return [_data(item, where) for item in node.value]
    if not isinstance(node, yaml.ScalarNode):
        raise ConfigError(f"{where} must be a JSON value")
    if node.tag == _NULL:
        return None
    if node.tag == _BOOL:
        return node.value.lower() in {"y", "yes", "true", "on"}
    if node.tag == _INT:
        return _whole(node, where)
    if node.tag == _FLOAT:
        try:
            value = float(node.value)
        except ValueError as exc:
            raise ConfigError(f"{where} must be a finite number") from exc
        if value != value or value in {float("inf"), float("-inf")}:
            raise ConfigError(f"{where} must be a finite number")
        return value
    if node.tag in {_STR, _TIMESTAMP}:
        return node.value
    raise ConfigError(f"{where} must be a JSON value")


def _hostname(node: yaml.Node, where: str) -> str:
    """Return a host name. A scheme, port, path, space, or empty value is refused."""
    message = f"{where}: hostname must be a host name, without a scheme, port, path, or space"
    if not isinstance(node, yaml.ScalarNode) or node.tag != _STR:
        raise ConfigError(message)
    text = node.value
    if not text.strip():
        raise ConfigError(f"{where}: hostname must not be empty")
    if any(char.isspace() for char in text) or any(char in text for char in ":/\\?#"):
        raise ConfigError(message)
    return text


def _port_number(node: yaml.Node, where: str) -> int:
    """Return a TCP port from 1 to 65535."""
    message = f"{where}: port must be a whole number from 1 to 65535"
    if not isinstance(node, yaml.ScalarNode) or node.tag not in {_INT, _STR}:
        raise ConfigError(message)
    if node.tag == _INT:
        text = node.value.replace("_", "")
        if not _DECIMAL.fullmatch(text):
            raise ConfigError(message)
        value = int(text)
    else:
        if _PORT_TEXT.fullmatch(node.value) is None:
            raise ConfigError(message)
        value = int(node.value)
    if not 1 <= value <= 65535:
        raise ConfigError(message)
    return value


def _text(node: yaml.Node, where: str) -> str:
    if not isinstance(node, yaml.ScalarNode) or node.tag != _STR:
        raise ConfigError(f"{where} must be a string")
    text = node.value.strip()
    if not text:
        raise ConfigError(f"{where} must not be empty")
    return text


def _whole(node: yaml.Node, where: str, *, minimum: int | None = None) -> int:
    if not isinstance(node, yaml.ScalarNode) or node.tag != _INT:
        raise ConfigError(f"{where} must be a whole number")
    text = node.value.replace("_", "")
    if not _DECIMAL.fullmatch(text):
        raise ConfigError(f"{where} must be a whole number")
    value = int(text)
    if minimum is not None and value < minimum:
        raise ConfigError(f"{where} must be a whole number, zero or more")
    return value


def _duration(node: yaml.Node, where: str) -> int:
    if isinstance(node, yaml.ScalarNode) and node.tag == _INT:
        value = _whole(node, where)
        if value < 0:
            raise ConfigError(f"{where} cannot be negative")
        raise ConfigError(f"{where} must be a duration like 2h, 120m, or 7200s, not a bare number")
    text = _text(node, where)
    if text.startswith("-"):
        raise ConfigError(f"{where} cannot be negative")
    match = _DURATION.fullmatch(text)
    if match is None:
        raise ConfigError(f"{where} must be a duration like 2h, 120m, or 7200s, not a bare number")
    return int(match.group(1)) * _DURATION_SCALE[match.group(2)]


def _size(node: yaml.Node, where: str) -> int:
    if isinstance(node, yaml.ScalarNode) and node.tag == _INT:
        value = _whole(node, where)
        if value < 0:
            raise ConfigError(f"{where} cannot be negative")
        raise ConfigError(f"{where} must be a size like 720b, 720k, 720M, 720G, or 720T, not a bare number")
    text = _text(node, where)
    if text.startswith("-"):
        raise ConfigError(f"{where} cannot be negative")
    match = _SIZE.fullmatch(text)
    if match is None:
        raise ConfigError(f"{where} must be a size like 720b, 720k, 720M, 720G, or 720T, not a bare number")
    return int(match.group(1)) * _SIZE_SCALE[match.group(2)]


def _non_negative(value: int, where: str) -> int:
    if value < 0:
        raise ConfigError(f"{where} cannot be negative")
    return value


def _reject_unknown(keys: set[str], allowed: set[str], where: str) -> None:
    unknown = sorted(keys - allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown setting {', '.join(unknown)}")


def _at(node: yaml.Node) -> str:
    return _mark(node.start_mark.name, node.start_mark)


def _mark(path: Path | str, mark) -> str:
    return f"{path}:{mark.line + 1}:{mark.column + 1}"
