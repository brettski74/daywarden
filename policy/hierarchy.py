"""Load the hierarchical household policy from YAML.

A file may include other files, and a directory include reads the ``*.yaml``
and ``*.yml`` files in that directory, in lexicographic order, without walking
into subdirectories. A file already loaded is skipped, so an include cycle is
not an error. Names are unique inside each of the six namespaces. The same
spelling may be used in two namespaces. Tasks are the sixth. Their bodies
are opaque here. S003.1 is the catalogue that reads them.

``load`` returns a new policy only when the whole configuration is valid.
A missing root file returns the previous policy unchanged. Any other problem
raises ``ConfigError`` and leaves that previous policy untouched. Decisions
from the loaded policy are made in ``policy.engine``. This module is the loader.

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

import yaml

from policy.buckets import divides_day
from policy.clients import Lookup, UnresolvedAddress, resolve_address
from policy.clock import named_zone
from policy.rules import REVISION_TASK, absolute_http_url
from policy.store import DEFAULT_BUCKET_SECONDS
from policy.tasks import Task

DEFAULT_TIME_GRACE = 5 * 60
DEFAULT_VOLUME_GRACE = 1024**2

_STR = "tag:yaml.org,2002:str"
_INT = "tag:yaml.org,2002:int"
_FLOAT = "tag:yaml.org,2002:float"
_BOOL = "tag:yaml.org,2002:bool"
_NULL = "tag:yaml.org,2002:null"
_TIMESTAMP = "tag:yaml.org,2002:timestamp"

_DURATION = re.compile(r"^(\d+)([hms])$")
_SIZE = re.compile(r"^(\d+)([bkMGT])$")
_DECIMAL = re.compile(r"^[+-]?(?:0|[1-9][0-9]*)$")
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
    "revision_task",
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
}
_SCALARS = {"entry", "timezone", "revision_task", "bucket_length", "time_grace", "volume_grace"}
_SECTIONS = {"client_groups", "site_groups", "time_windows", "quotas", "rule_sets", "tasks"}
_TASK_KEYS = {
    "type",
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


class ConfigError(ValueError):
    """The YAML policy could not be loaded. The previous policy stays in force."""


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


@dataclass(frozen=True)
class Policy:
    entry: str
    rule_sets: tuple[tuple[str, tuple[Rule, ...]], ...]
    timezone: str | None = None
    revision_task: str | None = None
    bucket_length: int = DEFAULT_BUCKET_SECONDS
    time_grace: int = DEFAULT_TIME_GRACE
    volume_grace: int = DEFAULT_VOLUME_GRACE
    client_groups: tuple[ClientGroup, ...] = ()
    site_groups: tuple[SiteGroup, ...] = ()
    time_windows: tuple[TimeWindow, ...] = ()
    quotas: tuple[Quota, ...] = ()
    tasks: tuple[Task, ...] = ()

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

    def task(self, name: str) -> Task | None:
        return _named(self.tasks, name)


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
    tasks: dict[str, Task] = field(default_factory=dict)
    task_where: dict[str, str] = field(default_factory=dict)
    rule_sets: dict[str, tuple[Rule, ...]] = field(default_factory=dict)
    ruleset_where: dict[str, str] = field(default_factory=dict)


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


def load(
    path: str | Path,
    *,
    previous: Policy | None = None,
    lookup: Lookup = socket.getaddrinfo,
    warn: Callable[[str], None] = lambda message: print(message, flush=True),
) -> Policy | None:
    """Load ``path`` into a new policy.

    A missing root file returns ``previous``, including when ``previous`` is
    None. A present root that is not valid YAML policy raises ``ConfigError``.
    ``previous`` is only read, so a failed load leaves it as it was. Pass the
    last successful policy so a DNS name that fails this time can keep the
    addresses that name resolved to then.
    """
    root = Path(path)
    if not root.is_file():
        return previous
    build = _Build()
    seen: set[Path] = set()
    _load_file(root, root.resolve(), seen, build)
    return _finish(build, previous, lookup, warn)


def _load_file(path: Path, canonical: Path, seen: set[Path], build: _Build) -> None:
    if canonical in seen:
        return
    if not canonical.is_file():
        raise ConfigError(f"{path}: included path does not exist")
    seen.add(canonical)
    try:
        text = canonical.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{canonical}: {exc}") from exc
    node = _compose(text, canonical)
    if not isinstance(node, yaml.MappingNode):
        raise ConfigError(f"{canonical}: the file must be a mapping")
    includes = _absorb(node, build)
    for raw in includes:
        _load_included(raw, path.parent, canonical, seen, build)


def _load_included(raw: str, base: Path, origin: Path, seen: set[Path], build: _Build) -> None:
    if Path(raw).is_absolute():
        raise ConfigError(f"{origin}: included path {raw!r} must be relative to the file that names it")
    target = base / raw
    try:
        canonical = target.resolve()
    except OSError as exc:
        raise ConfigError(f"{origin}: included path {raw!r}: {exc}") from exc
    if canonical in seen:
        return
    if not target.exists():
        raise ConfigError(f"{origin}: included path {raw!r} does not exist")
    if canonical.is_dir():
        seen.add(canonical)
        children = [
            child
            for child in canonical.iterdir()
            if child.is_file() and child.suffix in _YAML_SUFFIXES
        ]
        for child in sorted(children, key=lambda item: item.name):
            _load_file(child, child.resolve(), seen, build)
        return
    if canonical.is_file():
        _load_file(target, canonical, seen, build)
        return
    raise ConfigError(f"{origin}: included path {raw!r} does not exist")


def _compose(text: str, source: Path) -> yaml.Node | None:
    stream = io.StringIO(text)
    stream.name = str(source)
    loader = _Loader(stream, str(source))
    try:
        try:
            return loader.get_single_node()
        except yaml.YAMLError as exc:
            raise ConfigError(f"{source}: {exc}") from exc
    finally:
        loader.dispose()


def _absorb(node: yaml.MappingNode, build: _Build) -> tuple[str, ...]:
    pairs = _pairs(node)
    _reject_unknown(set(pairs), _TOP_KEYS, _at(node))
    for key in _SCALARS:
        if key not in pairs:
            continue
        where = _at(pairs[key])
        if key in build.scalars:
            raise ConfigError(f"{where}: {key} is already set at {build.scalars[key][1]}")
        build.scalars[key] = (_scalar(key, pairs[key], where), where)
    if "client_groups" in pairs:
        _take_clients(pairs["client_groups"], build)
    if "site_groups" in pairs:
        _take_sites(pairs["site_groups"], build)
    if "time_windows" in pairs:
        _take_windows(pairs["time_windows"], build)
    if "quotas" in pairs:
        _take_quotas(pairs["quotas"], build)
    if "rule_sets" in pairs:
        _take_rule_sets(pairs["rule_sets"], build)
    if "tasks" in pairs:
        _take_tasks(pairs["tasks"], build)
    if "include" not in pairs:
        return ()
    return _include_list(pairs["include"], _at(pairs["include"]))


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
    if key == "revision_task":
        url = _text(node, where)
        if not absolute_http_url(url):
            raise ConfigError(f"{where}: revision_task must be an absolute http or https URL")
        return url
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
    for name, body, where in _entities(node, "client group"):
        _reserve(name, where, "client group")
        _claim(build.clients, build.client_where, name, _addresses(body, where), where, "client group")


def _take_sites(node: yaml.Node, build: _Build) -> None:
    for name, body, where in _entities(node, "site group"):
        _reserve(name, where, "site group")
        if name in build.sites:
            raise ConfigError(f"{where}: site group {name!r} is already defined at {build.site_where[name]}")
        group = _site(name, body, where)
        if group.priority in build.priorities:
            other = build.priorities[group.priority]
            raise ConfigError(
                f"{where}: site groups {other!r} and {name!r} both have priority {group.priority}"
            )
        _claim(build.sites, build.site_where, name, group, where, "site group")
        build.priorities[group.priority] = name


def _take_windows(node: yaml.Node, build: _Build) -> None:
    for name, body, where in _entities(node, "time window"):
        window = _window(name, body, where)
        _claim(build.windows, build.window_where, name, window, where, "time window")


def _take_quotas(node: yaml.Node, build: _Build) -> None:
    for name, body, where in _entities(node, "quota"):
        quota = _quota(name, body, where)
        _claim(build.quotas, build.quota_where, name, quota, where, "quota")


def _take_tasks(node: yaml.Node, build: _Build) -> None:
    for name, body, where in _entities(node, "task"):
        task = _task(name, body, where)
        _claim(build.tasks, build.task_where, name, task, where, "task")


def _task(name: str, node: yaml.Node, where: str) -> Task:
    pairs = _pairs(node)
    _reject_unknown(set(pairs), _TASK_KEYS, where)
    if "type" not in pairs:
        raise ConfigError(f"{where}: type is required")
    if "pass_cooldown" not in pairs:
        raise ConfigError(f"{where}: pass_cooldown is required")
    groups = _one_list(pairs, "group", "groups", where)
    seen: set[str] = set()
    for group in groups:
        if group in seen:
            raise ConfigError(f"{where}: client group {group!r} is listed twice")
        seen.add(group)
    failure = None
    if "failure_cooldown" in pairs:
        failure = _whole(pairs["failure_cooldown"], f"{where}: failure_cooldown", minimum=0)
    available = None
    if "available_from" in pairs:
        available = _calendar_day(pairs["available_from"], f"{where}: available_from")
    due = None
    if "due_date" in pairs:
        due = _calendar_day(pairs["due_date"], f"{where}: due_date")
    skips = None
    if "max_skips" in pairs:
        skips = _whole(pairs["max_skips"], f"{where}: max_skips", minimum=0)
    passes = None
    if "max_passes" in pairs:
        passes = _whole(pairs["max_passes"], f"{where}: max_passes", minimum=0)
    document = {} if "body" not in pairs else _document(pairs["body"], f"{where}: body")
    if not isinstance(document, dict):
        raise ConfigError(f"{where}: body must be a mapping")
    return Task(
        name,
        _text(pairs["type"], f"{where}: type"),
        groups,
        _whole(pairs["pass_cooldown"], f"{where}: pass_cooldown", minimum=0),
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        failure,
        available,
        due,
        skips,
        passes,
    )


def _take_rule_sets(node: yaml.Node, build: _Build) -> None:
    for name, body, where in _entities(node, "rule set"):
        rules = _rules(body, where)
        _claim(build.rule_sets, build.ruleset_where, name, rules, where, "rule set")


def _entities(node: yaml.Node, label: str):
    pairs = _pairs(node)
    for name, body in pairs.items():
        if not name.strip():
            raise ConfigError(f"{_at(body)}: {label} name must not be empty")
        yield name.strip(), body, _at(body)


def _claim(table: dict, where_table: dict, name: str, value, where: str, label: str) -> None:
    if name in table:
        raise ConfigError(f"{where}: {label} {name!r} is already defined at {where_table[name]}")
    table[name] = value
    where_table[name] = where


def _reserve(name: str, where: str, label: str) -> None:
    if name == "default":
        raise ConfigError(f"{where}: {label} name 'default' is reserved")


def _addresses(node: yaml.Node, where: str) -> tuple[str, ...]:
    pairs = _pairs(node)
    _reject_unknown(set(pairs), {"addresses"}, where)
    if "addresses" not in pairs:
        raise ConfigError(f"{where}: addresses is required")
    values = _string_list(pairs["addresses"], f"{where}: addresses")
    if not values:
        raise ConfigError(f"{where}: addresses must list at least one address")
    seen: set[str] = set()
    for address in values:
        if address in seen:
            raise ConfigError(f"{where}: {address!r} is listed twice in this client group")
        seen.add(address)
    return values


def _site(name: str, node: yaml.Node, where: str) -> SiteGroup:
    pairs = _pairs(node)
    _reject_unknown(set(pairs), {"priority", "patterns"}, where)
    if "priority" not in pairs:
        raise ConfigError(f"{where}: priority is required")
    if "patterns" not in pairs:
        raise ConfigError(f"{where}: patterns is required")
    patterns = _string_list(pairs["patterns"], f"{where}: patterns")
    if not patterns:
        raise ConfigError(f"{where}: patterns must list at least one pattern")
    return SiteGroup(name, _whole(pairs["priority"], f"{where}: priority"), patterns)


def _window(name: str, node: yaml.Node, where: str) -> TimeWindow:
    pairs = _pairs(node)
    _reject_unknown(set(pairs), {"periods"}, where)
    if "periods" not in pairs:
        raise ConfigError(f"{where}: periods is required")
    bodies = _sequence(pairs["periods"], f"{where}: periods")
    if not bodies:
        raise ConfigError(f"{where}: a time window needs at least one period")
    periods = tuple(_period(body, f"{where}: period {number}") for number, body in enumerate(bodies, start=1))
    return TimeWindow(name, periods)


def _period(node: yaml.Node, where: str) -> Period:
    pairs = _pairs(node)
    _reject_unknown(set(pairs), {"start", "end", "day", "days"}, where)
    if "start" not in pairs or "end" not in pairs:
        raise ConfigError(f"{where}: start and end are required")
    start, _suffix = _clock(pairs["start"], f"{where}: start", suffix=False)
    end, extra = _clock(pairs["end"], f"{where}: end", suffix=True)
    return Period(start, end, extra, _days(pairs, where))


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
    _reject_unknown(set(pairs), {"time", "bytes", "ruleset", "time_grace", "volume_grace"}, where)
    if "ruleset" not in pairs:
        raise ConfigError(f"{where}: ruleset is required")
    time_limit = _duration(pairs["time"], f"{where}: time") if "time" in pairs else 0
    byte_limit = _size(pairs["bytes"], f"{where}: bytes") if "bytes" in pairs else 0
    time_grace = (
        _non_negative(_duration(pairs["time_grace"], f"{where}: time_grace"), f"{where}: time_grace")
        if "time_grace" in pairs
        else None
    )
    volume_grace = (
        _non_negative(_size(pairs["volume_grace"], f"{where}: volume_grace"), f"{where}: volume_grace")
        if "volume_grace" in pairs
        else None
    )
    return _RawQuota(name, _text(pairs["ruleset"], f"{where}: ruleset"), time_limit, byte_limit, time_grace, volume_grace)


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
    return Rule(condition, when_true, when_false, windows, groups, required, quota)


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


def _include_list(node: yaml.Node, where: str) -> tuple[str, ...]:
    return _string_list(node, where)


def _finish(
    build: _Build,
    previous: Policy | None,
    lookup: Lookup,
    warn: Callable[[str], None],
) -> Policy:
    if "entry" not in build.scalars:
        raise ConfigError("entry is required")
    entry = str(build.scalars["entry"][0])
    timezone = build.scalars["timezone"][0] if "timezone" in build.scalars else None
    revision_task = build.scalars["revision_task"][0] if "revision_task" in build.scalars else None
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
    _check_references(entry, build)
    _check_cycles(build.rule_sets)
    clients = _resolve_clients(build.clients, previous, lookup, warn)
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
        None if revision_task is None else str(revision_task),
        bucket_length,
        time_grace,
        volume_grace,
        clients,
        tuple(build.sites.values()),
        tuple(build.windows.values()),
        quotas,
        tuple(build.tasks.values()),
    )


def _check_references(entry: str, build: _Build) -> None:
    if entry not in build.rule_sets:
        raise ConfigError(f"entry {entry!r} does not name a rule set")
    sites = set(build.sites) | {"default"}
    clients = set(build.clients) | {"default"}
    windows = set(build.windows)
    quotas = set(build.quotas)
    rulesets = set(build.rule_sets)
    for name, task in build.tasks.items():
        for group in task.groups:
            if group not in clients:
                raise ConfigError(f"task {name!r}: unknown client group {group!r}")
    for name, raw in build.quotas.items():
        if raw.ruleset not in rulesets:
            raise ConfigError(f"quota {name!r}: unknown rule set {raw.ruleset!r}")
    for name, rules in build.rule_sets.items():
        _check_rules(rules, f"rule set {name}", sites, clients, windows, quotas, rulesets)


def _check_rules(
    rules: tuple[Rule, ...],
    where: str,
    sites: set[str],
    clients: set[str],
    windows: set[str],
    quotas: set[str],
    rulesets: set[str],
) -> None:
    for index, rule in enumerate(rules, start=1):
        place = f"{where} rule {index}"
        if rule.condition == "time_window":
            _known(rule.windows, windows, place, "time window")
        elif rule.condition == "site_group":
            _known(rule.groups, sites, place, "site group")
        elif rule.condition == "client_group":
            _known(rule.groups, clients, place, "client group")
        elif rule.condition in {"time_remaining", "volume_remaining"} and rule.quota not in quotas:
            raise ConfigError(f"{place}: unknown quota {rule.quota!r}")
        for branch, action in (("when_true", rule.when_true), ("when_false", rule.when_false)):
            if action.kind != "evaluate":
                continue
            if action.ruleset is not None:
                if action.ruleset not in rulesets:
                    raise ConfigError(f"{place} {branch}: unknown rule set {action.ruleset!r}")
            elif action.rules is not None:
                _check_rules(
                    action.rules,
                    f"{place} {branch} inline",
                    sites,
                    clients,
                    windows,
                    quotas,
                    rulesets,
                )


def _known(names: tuple[str, ...], have: set[str], where: str, label: str) -> None:
    for name in names:
        if name not in have:
            raise ConfigError(f"{where}: unknown {label} {name!r}")


def _check_cycles(rule_sets: Mapping[str, tuple[Rule, ...]]) -> None:
    done: set[int] = set()

    def walk(rules: tuple[Rule, ...], label: str, labels: tuple[str, ...], ids: tuple[int, ...]) -> None:
        node = id(rules)
        if node in ids:
            start = ids.index(node)
            cycle = " -> ".join(labels[start:] + (label,))
            raise ConfigError(f"evaluate cycle: {cycle}")
        if node in done:
            return
        labels = labels + (label,)
        ids = ids + (node,)
        for index, rule in enumerate(rules, start=1):
            for branch, action in (("when_true", rule.when_true), ("when_false", rule.when_false)):
                if action.kind != "evaluate":
                    continue
                if action.ruleset is not None:
                    walk(rule_sets[action.ruleset], action.ruleset, labels, ids)
                elif action.rules is not None:
                    walk(action.rules, f"{label} rule {index} {branch}", labels, ids)
        done.add(node)

    for name, rules in rule_sets.items():
        walk(rules, name, (), ())


def _resolve_clients(
    clients: Mapping[str, tuple[str, ...]],
    previous: Policy | None,
    lookup: Lookup,
    warn: Callable[[str], None],
) -> tuple[ClientGroup, ...]:
    groups: list[ClientGroup] = []
    owners: dict[str, str] = {}
    for name, addresses in clients.items():
        resolved: list[tuple[str, ...]] = []
        seen_here: dict[str, str] = {}
        for address in addresses:
            ips = _resolve_one(name, address, previous, lookup, warn)
            for ip in ips:
                if ip in seen_here:
                    raise ConfigError(
                        f"{ip} is listed twice in client group {name!r}, "
                        f"from {seen_here[ip]!r} and {address!r}"
                    )
                if ip in owners:
                    raise ConfigError(f"{ip} belongs to client groups {owners[ip]!r} and {name!r}")
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
