"""Changing the policy's named items and household settings, as one checked change each.

The named items are client groups, site groups, time windows, quotas, and
rule sets. Each can be created, updated, and deleted, one at a time or
several together as one change, which is how a policy page saves. The
household settings ``entry``, ``timezone``, ``bucket_length``,
``time_grace``, ``volume_grace``, ``host_retention``, ``request_retention``,
and ``proxy_configuration`` can be changed. ``page`` reads a policy page's
items and settings as the files write them.

A change is written in the file that already defines the item or setting,
following the includes, so an item in an included file is changed there and
the rest of ``policy.yaml`` is left as it was. A new item goes in the file
that defines the first item of its section, or in ``policy.yaml`` when the
section has none yet. Only the text of the changed entry is rewritten, with
``policy.task_edit``, so comments and layout elsewhere survive.

Every change passes through ``TaskAdmin.change``, as a task page's save
does: the whole policy is checked as ``dw check`` checks it, and a policy
that would not load is refused with the loader's reasons. A change that
passes is written, every service reloads it, and it is committed in the
config history. An agent's dry run stops after the checks.

A value is written as the text it would be typed as, and the loader is the
one judge of whether it is right. A clock given as text is always written
quoted, as the loader requires. One given as a number is written bare, so
the loader refuses it with ``dw check``'s reason.

``rename`` changes an item's name and every reference to it, and moves the
rows stored under it (``policy.rename_history``), as one change. It is a
portal action only: an agent's new name is still a delete and a create.
``config/bypass.txt`` is never written.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import yaml

from policy.check import household_zone, machine_localtime, size, span
from policy.hierarchy import (
    DEFAULT_BUCKET_SECONDS,
    DEFAULT_HOST_RETENTION_DAYS,
    DEFAULT_REQUEST_RETENTION_DAYS,
    DEFAULT_TIME_GRACE,
    DEFAULT_VOLUME_GRACE,
    ConfigError,
    Written,
    _days,
    _pairs,
    node_data,
    written,
)
from policy import rename_history
from policy.pac import SWITCHES
from policy.policy_rename import renamed_text
from policy.task_admin import STALE, Answer, Step, TaskAdmin, replace_text
from policy.task_edit import (
    EditError,
    Flow,
    ListEdit,
    ListItem,
    Quoted,
    _entries,
    _key,
    _root,
    _value,
    add_root_entry_after,
    has_entries,
    rewrite_root,
    scalar,
)


@dataclass(frozen=True)
class Section:
    """One section of named items: what one item is called, and the fields it takes."""

    label: str
    fields: tuple[str, ...]


SECTIONS: dict[str, Section] = {
    "client_groups": Section("client group", ("addresses",)),
    "site_groups": Section("site group", ("priority", "patterns")),
    "time_windows": Section("time window", ("periods",)),
    "quotas": Section("quota", ("time", "bytes", "time_grace", "volume_grace", "ruleset")),
    "rule_sets": Section("rule set", ("rules",)),
}
_PROXY = "proxy_configuration"
HOUSEHOLD = (
    "entry", "timezone", "bucket_length", "time_grace", "volume_grace", "host_retention", "request_retention", _PROXY,
)
# The policy pages: each one's section and the name its commit and message give it.
PAGES: dict[str, tuple[str | None, str]] = {
    "client-groups": ("client_groups", "client groups"),
    "site-groups": ("site_groups", "site groups"),
    "time-windows": ("time_windows", "time windows"),
    "quotas": ("quotas", "quotas"),
    "rule-sets": ("rule_sets", "rule sets"),
    "household": (None, "household"),
}
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
# A rule set is written as its list of rules, not as a mapping of fields.
_LISTED = "rule_sets"
# Sections with an implicit ``default`` item that the policy never writes.
_IMPLICIT = frozenset({"client_groups", "site_groups"})
_NAMES = frozenset({"ruleset", "entry"})
_SCALAR_LISTS = frozenset({"addresses", "patterns"})


def reserved(label: str) -> str:
    return f"The {label} default is implicit: it holds everything no other {label} holds, and cannot be created, changed, or deleted."


class PolicyChanges:
    def __init__(self, tasks: TaskAdmin) -> None:
        self.tasks = tasks

    @property
    def root(self) -> Path:
        return self.tasks.policy_file.resolve()

    def create(self, section: str, name: object, fields: Mapping, username: str) -> Answer:
        """Add a new item, checked and applied as a save is. A name already in use is refused."""
        refused = _section_and_name(section, name) or _unknown_fields(section, fields)
        if refused is not None:
            return refused
        label = SECTIONS[section].label
        path = self._create_path(section)
        return self.change(
            section, {str(name): fields}, {}, [], username,
            done=f"Created the {label} {name} in {path}.", commit=f"created {label} {name}",
        )

    def update(self, section: str, name: object, fields: Mapping, username: str) -> Answer:
        """Change only the fields named. A list named replaces the whole list."""
        refused = _section_and_name(section, name, existing=True) or _unknown_fields(section, fields)
        if refused is not None:
            return refused
        label = SECTIONS[section].label
        if not fields:
            return Answer(400, {"error": f"Name at least one field to change: {', '.join(SECTIONS[section].fields)}."})
        return self.change(
            section, {}, {str(name): fields}, [], username, done=f"Saved the {label} {name}.", commit=f"saved {label} {name}"
        )

    def delete(self, section: str, name: object, username: str) -> Answer:
        """Take an item out of the policy. Refused, naming each user, while anything still names it."""
        refused = _section_and_name(section, name, existing=True)
        if refused is not None:
            return refused
        label = SECTIONS[section].label
        return self.change(
            section, {}, {}, [str(name)], username, done=f"Deleted the {label} {name}.", commit=f"deleted {label} {name}"
        )

    def rename(self, section: str, old: object, new: object, username: str) -> Answer:
        """Rename an item, every reference to it in every policy file, and the history stored under it, as one change.

        Refused when the new name is taken in the section (case aside, so a
        change of case alone is allowed), is ``default`` for a client group or
        a site group, would not load, or is one that history is still stored
        under from an item no longer in the policy. The rows move, the
        services reload, and the rows move once more for anything filed under
        the old name in between. Any failure puts every file and row back.
        """
        refused = _section_and_name(section, old, existing=True)
        if refused is not None:
            return refused
        label = SECTIONS[section].label
        if not isinstance(new, str) or not new.strip():
            return Answer(400, {"error": f"Give the {label}'s new name."})
        if section in _IMPLICIT and new.strip() == DEFAULT:
            return Answer(400, {"error": reserved(label)})
        refused = _section_and_name(section, new)
        if refused is not None:
            return refused
        old, new = str(old), str(new)
        places = self._written().places[section]
        if old not in places:
            return Answer(404, {"error": f"There is no {label} named {old}."})
        if new == old:
            return Answer(200, {"message": "The name has not changed, so nothing was saved.", "warnings": [], "name": new})
        for other in places:
            if other != old and other.casefold() == new.casefold():
                return Answer(400, {"error": f"A {label} named {other} already exists, in {places[other]}."})
        connection = self.tasks.attempts.connection
        if rename_history.has_history(section):
            try:
                left = sorted(name for name in rename_history.stored_names(connection, section) if name != old and name.casefold() == new.casefold())
            except sqlite3.Error as error:
                return Answer(500, {"error": f"The stored history could not be read, so nothing was renamed: {error}"})
            if left:
                return Answer(
                    400,
                    {"error": f"History is still stored under {left[0]}, from a {label} no longer in the policy. Choose another name."},
                )

        def editor(path: Path):
            return lambda text: renamed_text(text, path, section, old, new)

        found = self._written()
        paths = [self.root, *found.files]
        edits = {path: editor(path) for path in dict.fromkeys(path.resolve() for path in paths)}
        steps: list[Step] = []
        after = None
        if rename_history.has_history(section):
            steps.append(
                Step(
                    lambda: rename_history.move(connection, section, old, new),
                    lambda: rename_history.move(connection, section, new, old),
                    "The stored history could not be moved, so nothing was renamed",
                )
            )
            after = lambda: rename_history.move(connection, section, old, new)  # noqa: E731
        return self._write(
            edits, username, done=f"Renamed the {label} {old} to {new}.", commit=f"renamed {label} {old} to {new}",
            steps=steps, after_reload=after, extra={"name": new},
        )

    def change(
        self,
        section: str,
        creates: Mapping[str, Mapping],
        updates: Mapping[str, Mapping],
        deletes: Sequence[str],
        username: str,
        *,
        done: str,
        commit: str,
    ) -> Answer:
        """Make any number of creates, updates, and deletes of one section's items as one change.

        ``creates`` and ``updates`` map a name to the fields to write, and
        ``deletes`` names the items to take out. Each item is changed in the
        file that defines it, and the new items go where ``create`` puts
        one. The whole change is one check, one reload, and one commit. An
        item still in use is not deleted: the change is refused naming each
        user of each item.
        """
        if section not in SECTIONS:
            return _section_and_name(section, "x") or Answer(400, {"error": f"{section} is not a section."})
        label = SECTIONS[section].label
        for name in [*creates, *updates, *deletes]:
            refused = _section_and_name(section, name, existing=name not in creates)
            if refused is not None:
                return refused
        for fields in [*creates.values(), *updates.values()]:
            refused = _unknown_fields(section, fields)
            if refused is not None:
                return refused
        names = [*creates, *updates, *deletes]
        if len(set(names)) != len(names):
            twice = sorted({name for name in names if names.count(name) > 1})
            return Answer(400, {"error": f"The {label} {', '.join(twice)} is named more than once in the one change."})
        found = self._written()
        places = found.places[section]
        for name in creates:
            if name in places:
                return Answer(400, {"error": f"A {label} named {name} already exists, in {places[name]}."})
        for name in [*updates, *deletes]:
            if name not in places:
                return Answer(404, {"error": f"There is no {label} named {name}."})
        in_use = [(name, found.users(section, name)) for name in deletes]
        in_use = [(name, users) for name, users in in_use if users]
        if in_use:
            reasons = [f"{label.capitalize()} {name} is used by {user}." for name, users in in_use for user in users]
            one = f"The {label} {in_use[0][0]} is still in use, so it was not deleted."
            many = f"These {label}s are still in use, so nothing was saved."
            return Answer(400, {"error": one if len(deletes) == 1 else many, "errors": reasons})
        by_file: dict[Path, dict[str, dict[str, object]]] = {}
        for name in updates:
            by_file.setdefault(places[name], {}).setdefault("update", {})[name] = updates[name]
        for name in deletes:
            by_file.setdefault(places[name], {}).setdefault("delete", {})[name] = {}
        if creates:
            by_file.setdefault(self._create_path(section), {})["create"] = dict(creates)

        def editor(path: Path, work: Mapping[str, Mapping[str, object]]):
            def edit(text: str) -> str:
                items: dict[str, object] = {}
                for name, fields in work.get("update", {}).items():
                    node = _entry_node(text, path, section, name)
                    change = _item_change(section, fields, node, new=False)
                    # A rule set that already holds these rules is left as the file writes it.
                    if change is not _KEEP:
                        items[name] = change
                for name, fields in work.get("create", {}).items():
                    items[name] = _item_change(section, fields, None, new=True)
                for name in work.get("delete", {}):
                    items[name] = None
                if not items:
                    return text
                new_text = rewrite_root(text, path, {section: items})
                # A file left holding nothing is still a mapping, with its comments kept.
                if work.get("delete") and not has_entries(new_text, path):
                    return new_text.rstrip("\n") + ("\n" if new_text.strip() else "") + "{}\n"
                return new_text
            return edit

        return self._write({path: editor(path, work) for path, work in by_file.items()}, username, done=done, commit=commit)

    def household(self, fields: Mapping, username: str, *, commit: str = "saved household settings") -> Answer:
        """Change the household's settings. None takes a setting out, back to its default."""
        unknown = sorted(str(field) for field in fields if field not in HOUSEHOLD)
        if unknown:
            return Answer(400, {"error": f"{', '.join(unknown)}: the household settings changed here are {', '.join(HOUSEHOLD)}."})
        if not fields:
            return Answer(400, {"error": f"Name at least one setting to change: {', '.join(HOUSEHOLD)}."})
        places = self._written().scalars
        by_file: dict[Path, dict[str, object]] = {}
        try:
            for field in HOUSEHOLD:
                if field in fields:
                    by_file.setdefault(places.get(field, self.root), {})[field] = (
                        fields[field] if field == _PROXY else _scalar_text(fields[field], field)
                    )
        except EditError as error:
            return Answer(400, {"error": str(error)})

        def editor(path: Path, changes: Mapping[str, object]):
            def edit(text: str) -> str:
                root = _root(text, path)
                present = {} if root is None else {key: value for key, _node, value in _entries(root)}
                for key, value in changes.items():
                    node = present.get(key)
                    if key == _PROXY:
                        value = _proxy_change(node, value)
                    elif isinstance(node, yaml.ScalarNode) and value is not None and _same_text(node, fields[key]):
                        continue
                    if key in present or value is None:
                        text = rewrite_root(text, path, {key: value})
                    else:
                        text = add_root_entry_after(text, path, "entry", key, value)
                return text
            return edit

        return self._write(
            {path: editor(path, changes) for path, changes in by_file.items()},
            username, done="Saved the household settings.", commit=commit,
        )

    # The policy pages

    def page(self, page: str) -> Answer:
        """Return a policy page's items, or the household's settings, as the policy files write them."""
        if page not in PAGES:
            return Answer(404, {"error": f"{page} is not a policy page. The pages are {', '.join(PAGES)}."})
        found = self._written()
        texts = self._texts(found)
        body: dict[str, object] = {"version": _version(texts), "file": str(self.root)}
        section = PAGES[page][0]
        if section is None:
            body.update(self._household_page(found, texts))
            return Answer(200, body)
        items = [self._item_page(section, name, path, texts[path]) for name, path in found.places[section].items()]
        if section == "site_groups":
            items.sort(key=lambda item: (_priority(item["priority"]), item["name"]))
        body["items"] = items
        if section == "rule_sets":
            for item in items:
                item["users"] = [_user(text) for text in found.users("rule_sets", item["name"])]
            body["choices"] = {
                "time_window": list(found.places["time_windows"]),
                "site_group": [*found.places["site_groups"], DEFAULT],
                "client_group": [*found.places["client_groups"], DEFAULT],
                "quota": list(found.places["quotas"]),
            }
        if section == "quotas":
            body["rule_sets"] = list(found.places["rule_sets"])
            body["defaults"] = self._grace_defaults()
        return Answer(200, body)

    def save_page(self, page: str, request: Mapping, username: str) -> Answer:
        """Save every change a policy page made as one change. A page open on files that have changed since is refused."""
        if page not in PAGES:
            return Answer(404, {"error": f"{page} is not a policy page. The pages are {', '.join(PAGES)}."})
        found = self._written()
        if request.get("version") != _version(self._texts(found)):
            return Answer(409, {"error": STALE, "stale": True})
        section, name = PAGES[page]
        if section is None:
            fields = request.get("fields")
            if not isinstance(fields, Mapping):
                return Answer(400, {"error": "Send the household's changed settings as fields."})
            return self.household(fields, username, commit=f"saved {name}")
        items, deleted = request.get("items", []), request.get("deleted", [])
        if not isinstance(items, list) or not all(isinstance(item, Mapping) and isinstance(item.get("fields"), Mapping) for item in items):
            return Answer(400, {"error": "Send each changed item as a name and its fields."})
        if not isinstance(deleted, list):
            return Answer(400, {"error": "Send the items to delete as a list of names."})
        creates = {item.get("name"): item["fields"] for item in items if item.get("new")}
        updates = {item.get("name"): item["fields"] for item in items if not item.get("new")}
        for each in [*creates, *updates, *deleted]:
            if not isinstance(each, str):
                return Answer(400, {"error": "Every item has a name."})
        done, commit = f"Saved the {name}.", f"saved {name}"
        if section == _LISTED:
            done, commit = _rule_set_words(list(creates), list(updates), deleted)
        return self.change(section, creates, updates, deleted, username, done=done, commit=commit)

    def rename_page(self, page: str, request: Mapping, username: str) -> Answer:
        """Rename an item from its policy page. A page open on files that have changed since is refused."""
        section = PAGES.get(page, (None, ""))[0]
        if section is None:
            return Answer(404, {"error": f"{page} is not a policy page with items to rename."})
        if request.get("version") != _version(self._texts(self._written())):
            return Answer(409, {"error": STALE, "stale": True})
        return self.rename(section, request.get("name"), request.get("to"), username)

    def _texts(self, found: Written) -> dict[Path, str]:
        """Return the text of the root file and of every file that holds an item or a setting."""
        paths = {self.root, *found.scalars.values()}
        for places in found.places.values():
            paths.update(places.values())
        texts: dict[Path, str] = {}
        for path in sorted(paths):
            try:
                texts[path] = path.read_bytes().decode("utf-8")
            except (OSError, UnicodeDecodeError):
                texts[path] = ""
        return texts

    def _shown_file(self, path: Path) -> str | None:
        """Return the file that holds an item when it is not ``policy.yaml``, relative to the config directory."""
        if path == self.root:
            return None
        try:
            return str(path.relative_to(self.root.parent))
        except ValueError:
            return str(path)

    def _create_path(self, section: str) -> Path:
        return next(iter(self._written().places[section].values()), self.root)

    def _item_page(self, section: str, name: str, path: Path, text: str) -> dict:
        node = _entry_node(text, path, section, name)
        data = _data_or_none(node) if node is not None else None
        data = data if isinstance(data, Mapping) else {}
        item: dict[str, object] = {"name": name, "file": self._shown_file(path)}
        if section == _LISTED:
            rules = _data_or_none(node) if node is not None else None
            item["rules"] = rules if isinstance(rules, list) else []
            return item
        if section in _SCALAR_LISTS_OF:
            item[_SCALAR_LISTS_OF[section]] = _texts_of(data.get(_SCALAR_LISTS_OF[section]))
        if section == "site_groups":
            item["priority"] = _text_of(data.get("priority"))
        elif section == "time_windows":
            item["periods"] = _periods_page(node)
        elif section == "quotas":
            for field in SECTIONS[section].fields:
                item[field] = _text_of(data.get(field))
        return item

    def _grace_defaults(self) -> dict[str, str]:
        policy = self.tasks.policy()
        if policy is None:
            return {"time_grace": span(DEFAULT_TIME_GRACE), "volume_grace": size(DEFAULT_VOLUME_GRACE)}
        return {"time_grace": span(policy.time_grace), "volume_grace": size(policy.volume_grace)}

    def _household_page(self, found: Written, texts: Mapping[Path, str]) -> dict:
        fields: dict[str, str] = {}
        proxy: object = None
        for key in HOUSEHOLD:
            path = found.scalars.get(key)
            node = None
            if path is not None:
                root = _root(texts[path], path)
                node = next((value for name, _key_node, value in _entries(root) if name == key), None) if root is not None else None
            if key == _PROXY:
                proxy = _proxy_page(node)
            else:
                fields[key] = _text_of(_data_or_none(node)) if node is not None else ""
        try:
            zone = str(household_zone(None, machine_localtime())[0])
        except Exception:  # noqa: BLE001 - a machine with no usable zone just has no default to show
            zone = "the machine's timezone"
        return {
            "fields": fields,
            "proxy": proxy,
            "rule_sets": list(found.places["rule_sets"]),
            "switches": list(SWITCHES),
            "defaults": {
                "timezone": zone,
                "bucket_length": span(DEFAULT_BUCKET_SECONDS),
                "time_grace": span(DEFAULT_TIME_GRACE),
                "volume_grace": size(DEFAULT_VOLUME_GRACE),
                "host_retention": f"{DEFAULT_HOST_RETENTION_DAYS}d",
                "request_retention": f"{DEFAULT_REQUEST_RETENTION_DAYS}d",
            },
        }

    def _written(self) -> Written:
        try:
            return written(self.tasks.policy_file)
        except ConfigError:
            return written_nothing()

    def _write(
        self,
        edits: Mapping[Path, object],
        username: str,
        *,
        done: str,
        commit: str,
        steps: Sequence[Step] = (),
        after_reload: object = None,
        extra: Mapping[str, object] | None = None,
    ) -> Answer:
        """Make each file's edit as one change, checked, applied, and committed as a task save is.

        ``steps`` are made after the files are written, and taken back with them. ``after_reload`` runs once
        the services have reloaded. ``extra`` is added to an answer that succeeded.
        """
        before: dict[Path, str] = {}
        after: dict[Path, str] = {}
        try:
            for path, edit in edits.items():
                text = path.read_bytes().decode("utf-8")
                before[path] = text
                after[path] = edit(text)
        except (OSError, UnicodeDecodeError, EditError) as error:
            return Answer(400, {"error": str(error)})
        changed = [path for path in after if after[path] != before[path]]
        if not changed:
            return Answer(200, {"message": "That is already how the policy reads, so nothing was saved.", "warnings": []})
        written_steps = [
            Step(
                lambda path=path: replace_text(path, after[path]),
                lambda path=path: replace_text(path, before[path]),
                f"{path} could not be written, so nothing was saved",
            )
            for path in changed
        ]
        answer = self.tasks.change(
            None, {path: after[path] for path in changed}, [], [*written_steps, *steps], username,
            confirmed=True, moved=None, failed="", done=done, commit=commit, paths=changed, after_reload=after_reload,
        )
        if extra and answer.status == 200:
            answer.body.update(extra)
        return answer


DEFAULT = "default"


def _rule_set_words(created: list[str], saved: list[str], deleted: list) -> tuple[str, str]:
    """Return the message and the commit for a rule set page's save: each rule set saved, created, or deleted, named."""
    parts = [
        *(("saved", name) for name in saved),
        *(("created", name) for name in created),
        *(("deleted", name) for name in deleted),
    ]
    commit = ", ".join(f"{verb} rule set {name}" for verb, name in parts)
    if len(parts) == 1:
        verb, name = parts[0]
        return f"{verb.capitalize()} the rule set {name}.", commit
    return "Saved the rule sets.", commit


def _user(text: str) -> dict[str, str]:
    """Return what names a rule set as a link to give it: ``{"kind", "name", "text"}``, from ``Written.users``."""
    if text.startswith("quota "):
        return {"kind": "quota", "name": text[len("quota "):], "text": text}
    if text.startswith("rule set "):
        return {"kind": "rule_set", "name": text[len("rule set "):].partition(", ")[0], "text": text}
    return {"kind": "entry", "name": "", "text": text}


def _version(texts: Mapping[Path, str]) -> str:
    """Return a version of the files a policy page reads, which changes when any of them does."""
    digest = hashlib.sha256()
    for path in sorted(texts):
        digest.update(str(path).encode("utf-8") + b"\0" + texts[path].encode("utf-8") + b"\0")
    return digest.hexdigest()


_SCALAR_LISTS_OF = {"client_groups": "addresses", "site_groups": "patterns"}


def _text_of(value: object) -> str:
    return "" if value is None or isinstance(value, (Mapping, list)) else str(value).strip()


def _texts_of(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [_text_of(item) for item in value] if isinstance(value, list) else []


def _priority(text: object) -> int:
    try:
        return int(str(text))
    except ValueError:
        return 1 << 62


def _split_end(raw: str) -> tuple[str, str]:
    """Return a period's end clock and its extra days, as written: ``21:00+2`` is ``21:00`` and ``2``."""
    clock, plus, extra = raw.partition("+")
    return clock.strip(), extra.strip() if plus else "0"


def _weekdays_of(node: yaml.Node) -> frozenset[int]:
    try:
        return _days(_pairs(node), "") or frozenset()
    except ConfigError:
        return frozenset()


def _periods_page(node: yaml.Node | None) -> list[dict]:
    """Return a time window's periods as the page edits them: clocks and extra days as written, and the weekdays on."""
    present = {key: value for key, _key_node, value in _entries(node)} if isinstance(node, yaml.MappingNode) else {}
    periods = present.get("periods")
    if not isinstance(periods, yaml.SequenceNode):
        return []
    found = []
    for index, item in enumerate(periods.value):
        data = _data_or_none(item)
        data = data if isinstance(data, Mapping) else {}
        clock, extra = _split_end(_text_of(data.get("end")))
        found.append(
            {
                "origin": index,
                "start": _text_of(data.get("start")),
                "end": clock,
                "extra": extra,
                "weekdays": sorted(_weekdays_of(item)),
            }
        )
    return found


def _proxy_page(node: yaml.Node | None) -> dict:
    """Return ``proxy_configuration`` as the page edits it: each switch, on when not written, and ``extra``."""
    data = _data_or_none(node) if node is not None else None
    direct = data.get("direct") if isinstance(data, Mapping) else None
    direct = direct if isinstance(direct, Mapping) else {}
    found: dict[str, object] = {name: direct.get(name) is not False for name in SWITCHES}
    found["extra"] = _texts_of(direct.get("extra"))
    return found


def _same_text(node: yaml.ScalarNode, value: object) -> bool:
    return value is not None and str(value).strip() == node.value.strip() and node.tag != "tag:yaml.org,2002:null"


def written_nothing() -> Written:
    return Written({section: {} for section in SECTIONS}, {}, None, {}, {}, {})


# Checking the request


def _section_and_name(section: str, name: object, *, existing: bool = False) -> Answer | None:
    if section not in SECTIONS:
        return Answer(400, {"error": f"{section} is not a section. The sections are {', '.join(SECTIONS)}."})
    label = SECTIONS[section].label
    if not isinstance(name, str) or not name.strip():
        return Answer(400, {"error": f"Give the {label}'s name."})
    if existing and section in _IMPLICIT and name.strip() == "default":
        return Answer(400, {"error": reserved(label)})
    if name != name.strip() or _key(name) != name:
        return Answer(400, {"error": f"{name!r} cannot be a {label}'s name. A name is plain text, such as weekend-bedtime."})
    return None


def _unknown_fields(section: str, fields: Mapping) -> Answer | None:
    allowed = SECTIONS[section].fields
    unknown = sorted(str(field) for field in fields if field not in allowed)
    if not unknown:
        return None
    label = SECTIONS[section].label
    named = "is not a field" if len(unknown) == 1 else "are not fields"
    return Answer(400, {"error": f"{', '.join(unknown)} {named} of a {label}. Its fields are {', '.join(allowed)}."})


# Writing the change


def _entry_node(text: str, source: Path, section: str, name: str) -> yaml.Node | None:
    """Return the node of one named item as the file writes it, or None."""
    root = _root(text, source)
    for key, _key_node, value in [] if root is None else _entries(root):
        if key == section and isinstance(value, yaml.MappingNode):
            for item, _item_node, body in _entries(value):
                if item.strip() == name:
                    return body
    return None


def _item_change(section: str, fields: Mapping, node: yaml.Node | None, *, new: bool) -> object:
    """Return the change ``rewrite_root`` makes to one item for ``fields``."""
    if section == _LISTED:
        rules = fields.get("rules", [] if new else None)
        return _list_change([_rule_data(rule) for rule in rules] if isinstance(rules, list) else rules, node)
    present = {} if not isinstance(node, yaml.MappingNode) else {key: value for key, _key_node, value in _entries(node)}
    changes: dict[str, object] = {}
    for field in SECTIONS[section].fields:
        if field not in fields:
            continue
        value = fields[field]
        if value is None:
            changes[field] = None
        elif field in _SCALAR_LISTS or field == "periods":
            change = _list_change(value, present.get(field)) if field in _SCALAR_LISTS else _periods_change(value, present.get(field))
            if change is not _KEEP:
                changes[field] = change
        else:
            text = _scalar_text(value, field)
            old = present.get(field)
            # A value that is already what the file has is left as the file writes it.
            if not new and isinstance(old, yaml.ScalarNode) and text is not None and _same_text(old, value):
                continue
            changes[field] = text
    if new and not any(value is not None for value in changes.values()):
        return "{}"
    if not new and not isinstance(node, yaml.MappingNode):
        raise EditError(f"the {SECTIONS[section].label} is not written as a mapping; edit it by hand")
    return changes


def _scalar_text(value: object, field: str) -> str | None:
    """Return a setting as the text it would be typed as. Anything not text or a number is written as YAML, for the loader to judge."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        typed = scalar(value, name=field in _NAMES)
        # Text such as America/Toronto reads back as itself unquoted, so it is written as a parent would type it.
        return _value(value.strip()) if typed.startswith('"') else typed
    return _value(value)


def _list_change(items: object, node: yaml.Node | None) -> object:
    """Return the change that makes a list hold ``items``, keeping the text of each item that stays the same in its place.

    A block list is changed item by item, so a comment on an item that stays
    is kept. A list of plain values that is new, or written in flow style, is
    written as one flow list, such as ``patterns: ["*.youtube.com"]``. A list
    of mappings is written as a block list.
    """
    if not isinstance(items, list):
        return _value(items)
    if isinstance(node, yaml.SequenceNode) and _keys([_data_or_none(item) for item in node.value]) == _keys(items):
        return _KEEP
    if not items:
        return "[]"
    if isinstance(node, yaml.SequenceNode) and not node.flow_style and node.value:
        return ListEdit(_list_items(items, [_data_or_none(item) for item in node.value]))
    if not any(isinstance(item, (Mapping, list)) for item in items):
        return _value(items)
    return ListEdit(tuple(ListItem(None, item, True) for item in items))


# What ``_list_change`` returns for a list that already holds exactly these items, so its text is left alone.
_KEEP = object()


def _keys(values: list) -> list[str]:
    return [json.dumps(value, sort_keys=True, default=str) for value in values]


def _list_items(items: list, old: list) -> tuple[ListItem, ...]:
    """Match the new items to the old ones, so an item that is left alone, or taken out, does not rewrite the ones after it.

    A changed item is written again in the place of the one it replaces. New
    items can only go after the last one, so a list with a new item in the
    middle is matched by position instead.
    """
    found: list[ListItem | None] = [None] * len(items)
    for tag, old_from, old_to, new_from, new_to in SequenceMatcher(None, _keys(old), _keys(items), autojunk=False).get_opcodes():
        if tag == "equal":
            for step in range(old_to - old_from):
                found[new_from + step] = ListItem(old_from + step, items[new_from + step], False)
        elif tag == "replace":
            for step in range(min(old_to - old_from, new_to - new_from)):
                found[new_from + step] = ListItem(old_from + step, items[new_from + step], True)
    matched = [item or ListItem(None, items[index], True) for index, item in enumerate(found)]
    after_new = False
    for item in matched:
        if item.origin is None:
            after_new = True
        elif after_new:
            return tuple(
                ListItem(index, item, item != old[index]) if index < len(old) else ListItem(None, item, True)
                for index, item in enumerate(items)
            )
    return tuple(matched)


def _data_or_none(node: yaml.Node) -> object:
    try:
        return node_data(node, "item")
    except ConfigError:
        return None


def _periods_change(periods: object, node: yaml.Node | None) -> object:
    """Return the change that makes a time window hold ``periods``.

    A period may be written as the loader reads it, ``start``, ``end``, and
    ``day`` or ``days``, or as a policy page edits it, with ``extra`` days,
    ``weekdays``, and the ``origin`` it was read from. A page's period keeps
    the text of every clock and of the days that it did not change.
    """
    if not isinstance(periods, list):
        return _value(periods)
    old = list(node.value) if isinstance(node, yaml.SequenceNode) else []
    items = []
    for period in periods:
        if isinstance(period, Mapping) and ("weekdays" in period or "extra" in period):
            origin = period.get("origin")
            was = old[origin] if isinstance(origin, int) and not isinstance(origin, bool) and 0 <= origin < len(old) else None
            items.append(_page_period(period, was))
        else:
            items.append(_period_data(period))
    return _list_change(items, node)


def _page_period(period: Mapping, was: yaml.Node | None) -> dict:
    data = _data_or_none(was) if was is not None else None
    data = data if isinstance(data, Mapping) else {}
    extra = _extra_days(period.get("extra"))
    clock = str(period.get("end", "")).strip()
    old_clock, old_extra = _split_end(_text_of(data.get("end")))
    unchanged_end = was is not None and clock == old_clock and old_extra.isdigit() and int(old_extra) == extra
    end = _text_of(data.get("end")) if unchanged_end else clock + (f"+{extra}" if extra else "")
    found: dict[str, object] = {"start": Quoted(str(period.get("start", "")).strip()), "end": Quoted(end)}
    days = period.get("weekdays") or []
    if not isinstance(days, list) or not all(isinstance(day, int) and not isinstance(day, bool) and 0 <= day <= 6 for day in days):
        raise EditError("weekdays is a list of numbers, Monday 0 to Sunday 6.")
    if was is not None and frozenset(days) == _weekdays_of(was):
        found.update({key: data[key] for key in ("day", "days") if key in data})
    else:
        found.update(_weekday_fields(frozenset(days)))
    return found


def _extra_days(value: object) -> int:
    if value is None or value == "":
        return 0
    number = value if isinstance(value, int) and not isinstance(value, bool) else (int(value) if isinstance(value, str) and value.strip().isdigit() else -1)
    if number < 0:
        raise EditError("Extra days is a whole number, 0 or more.")
    return number


def _weekday_fields(days: frozenset[int]) -> dict[str, object]:
    """Return how a set of weekdays is written: none, a day, a run such as ``friday-tuesday``, or a list."""
    if not days:
        return {}
    if len(days) == 1:
        return {"day": _WEEKDAYS[next(iter(days))]}
    if len(days) == 7:
        return {"days": f"{_WEEKDAYS[0]}-{_WEEKDAYS[6]}"}
    for first in days:
        if (first - 1) % 7 not in days and all((first + step) % 7 in days for step in range(len(days))):
            return {"days": f"{_WEEKDAYS[first]}-{_WEEKDAYS[(first + len(days) - 1) % 7]}"}
    return {"days": [_WEEKDAYS[day] for day in sorted(days)]}


def _proxy_change(node: yaml.Node | None, value: object) -> object:
    """Return the change that makes ``proxy_configuration`` hold ``value``, a ``direct`` mapping of switches and ``extra``.

    A switch is on when it is not written, so only an off switch is written.
    When every switch is on and ``extra`` is empty, the section is taken out.
    """
    if value is None:
        return None
    if not isinstance(value, Mapping):
        return _value(value)
    others = sorted(str(key) for key in value if key != "direct")
    if others:
        raise EditError(f"{', '.join(others)}: proxy_configuration holds only direct.")
    direct = value.get("direct") or {}
    if not isinstance(direct, Mapping):
        raise EditError("proxy_configuration.direct is a mapping of the switches and extra.")
    others = sorted(str(key) for key in direct if key not in SWITCHES and key != "extra")
    if others:
        raise EditError(f"{', '.join(others)}: direct holds {', '.join(SWITCHES)}, and extra.")
    wanted = {}
    for name in SWITCHES:
        switch = direct.get(name)
        if switch is not None and not isinstance(switch, bool):
            raise EditError(f"{name} must be true or false.")
        wanted[name] = switch is not False
    extra = direct.get("extra") or []
    if not isinstance(extra, list) or not all(isinstance(item, str) for item in extra):
        raise EditError("extra is a list of hosts, domains, addresses, and subnets.")
    if all(wanted.values()) and not extra:
        return None
    section = {key: body for key, _key_node, body in _entries(node)} if isinstance(node, yaml.MappingNode) else {}
    direct_node = section.get("direct")
    old = {key: body for key, _key_node, body in _entries(direct_node)} if isinstance(direct_node, yaml.MappingNode) else {}
    changes: dict[str, object] = {}
    for name in SWITCHES:
        had = _data_or_none(old[name]) if name in old else None
        if wanted[name]:
            if had is False:
                changes[name] = None
        elif had is not False:
            changes[name] = "false"
    if extra:
        change = _list_change(extra, old.get("extra"))
        if change is not _KEEP:
            changes["extra"] = change
    elif "extra" in old:
        changes["extra"] = None
    return {"direct": changes}


def _period_data(period: object) -> object:
    """Return a period with its clocks given as text written quoted. A clock given as a number is left for the loader to refuse."""
    if not isinstance(period, Mapping):
        return period
    return {
        str(key): Quoted(value) if key in ("start", "end") and isinstance(value, str) else value
        for key, value in period.items()
    }


def _rule_data(rule: object) -> object:
    """Return a rule with each action written on one line, such as ``when_true: { action: allow }``."""
    if not isinstance(rule, Mapping):
        return rule
    found = {}
    for key, value in rule.items():
        if key in ("when_true", "when_false") and isinstance(value, Mapping):
            inner = value.get("rules")
            if isinstance(inner, list):
                value = {**value, "rules": [_rule_data(item) for item in inner]}
            else:
                value = Flow(value)
        found[str(key)] = value
    return found
