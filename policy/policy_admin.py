"""Changing the policy's named items and household settings, as one checked change each.

The named items are client groups, site groups, time windows, quotas, and
rule sets. Each can be created, updated, and deleted. The household
settings ``entry``, ``timezone``, and ``bucket_length`` can be changed.

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

Nothing is renamed: a new name is a delete and a create. ``config/bypass.txt``
is never written.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from policy.hierarchy import ConfigError, Written, node_data, written
from policy.task_admin import Answer, Step, TaskAdmin, replace_text
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
HOUSEHOLD = ("entry", "timezone", "bucket_length")
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
        found = self._written()
        places = found.places[section]
        if name in places:
            return Answer(400, {"error": f"A {label} named {name} already exists, in {places[name]}."})
        path = next(iter(places.values()), self.root)
        def edit(text: str) -> str:
            node = _entry_node(text, path, section, str(name))
            return rewrite_root(text, path, {section: {str(name): _item_change(section, fields, node, new=True)}})
        return self._write(
            {path: edit}, username, done=f"Created the {label} {name} in {path}.", commit=f"created {label} {name}"
        )

    def update(self, section: str, name: object, fields: Mapping, username: str) -> Answer:
        """Change only the fields named. A list named replaces the whole list."""
        refused = _section_and_name(section, name, existing=True) or _unknown_fields(section, fields)
        if refused is not None:
            return refused
        label = SECTIONS[section].label
        if not fields:
            return Answer(400, {"error": f"Name at least one field to change: {', '.join(SECTIONS[section].fields)}."})
        path = self._written().places[section].get(str(name))
        if path is None:
            return Answer(404, {"error": f"There is no {label} named {name}."})
        def edit(text: str) -> str:
            node = _entry_node(text, path, section, str(name))
            return rewrite_root(text, path, {section: {str(name): _item_change(section, fields, node, new=False)}})
        return self._write({path: edit}, username, done=f"Saved the {label} {name}.", commit=f"saved {label} {name}")

    def delete(self, section: str, name: object, username: str) -> Answer:
        """Take an item out of the policy. Refused, naming each user, while anything still names it."""
        refused = _section_and_name(section, name, existing=True)
        if refused is not None:
            return refused
        label = SECTIONS[section].label
        found = self._written()
        path = found.places[section].get(str(name))
        if path is None:
            return Answer(404, {"error": f"There is no {label} named {name}."})
        users = found.users(section, str(name))
        if users:
            return Answer(
                400,
                {
                    "error": f"The {label} {name} is still in use, so it was not deleted.",
                    "errors": [f"{label.capitalize()} {name} is used by {user}." for user in users],
                },
            )
        def edit(text: str) -> str:
            new_text = rewrite_root(text, path, {section: {str(name): None}})
            # A file left holding nothing is still a mapping, with its comments kept.
            return new_text if has_entries(new_text, path) else new_text.rstrip("\n") + ("\n" if new_text.strip() else "") + "{}\n"
        return self._write({path: edit}, username, done=f"Deleted the {label} {name}.", commit=f"deleted {label} {name}")

    def household(self, fields: Mapping, username: str) -> Answer:
        """Change the household's entry, timezone, or bucket length. None takes a setting out, back to its default."""
        unknown = sorted(str(field) for field in fields if field not in HOUSEHOLD)
        if unknown:
            return Answer(400, {"error": f"{', '.join(unknown)}: the household settings changed here are {', '.join(HOUSEHOLD)}."})
        if not fields:
            return Answer(400, {"error": f"Name at least one setting to change: {', '.join(HOUSEHOLD)}."})
        places = self._written().scalars
        by_file: dict[Path, dict[str, str | None]] = {}
        for field in HOUSEHOLD:
            if field in fields:
                by_file.setdefault(places.get(field, self.root), {})[field] = _scalar_text(fields[field], field)

        def editor(path: Path, changes: Mapping[str, str | None]):
            def edit(text: str) -> str:
                root = _root(text, path)
                present = set() if root is None else {key for key, _node, _value in _entries(root)}
                for key, value in changes.items():
                    if key in present or value is None:
                        text = rewrite_root(text, path, {key: value})
                    else:
                        text = add_root_entry_after(text, path, "entry", key, value)
                return text
            return edit

        return self._write(
            {path: editor(path, changes) for path, changes in by_file.items()},
            username, done="Saved the household settings.", commit="saved household settings",
        )

    def _written(self) -> Written:
        try:
            return written(self.tasks.policy_file)
        except ConfigError:
            return written_nothing()

    def _write(self, edits: Mapping[Path, object], username: str, *, done: str, commit: str) -> Answer:
        """Make each file's edit as one change, checked, applied, and committed as a task save is."""
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
        steps = [
            Step(
                lambda path=path: replace_text(path, after[path]),
                lambda path=path: replace_text(path, before[path]),
                f"{path} could not be written, so nothing was saved",
            )
            for path in changed
        ]
        return self.tasks.change(
            None, {path: after[path] for path in changed}, [], steps, username,
            confirmed=True, moved=None, failed="", done=done, commit=commit, paths=changed,
        )


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
        elif field in _SCALAR_LISTS:
            changes[field] = _list_change(value, present.get(field))
        elif field == "periods":
            changes[field] = _list_change([_period_data(period) for period in value] if isinstance(value, list) else value, present.get(field))
        else:
            changes[field] = _scalar_text(value, field)
    if new and not any(value is not None for value in changes.values()):
        return "{}"
    if not new and not isinstance(node, yaml.MappingNode):
        raise EditError(f"the {SECTIONS[section].label} is not written as a mapping; edit it by hand")
    return changes


def _scalar_text(value: object, field: str) -> str | None:
    """Return a setting as the text it would be typed as. Anything not text or a number is written as YAML, for the loader to judge."""
    if value is None:
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

    A block list is changed item by item. A list of plain values that is new,
    or written in flow style, is written as one flow list, such as
    ``patterns: ["*.youtube.com"]``. A list of mappings is written as a block list.
    """
    if not isinstance(items, list):
        return _value(items)
    if not items:
        return "[]"
    if isinstance(node, yaml.SequenceNode) and not node.flow_style and node.value:
        old = [_data_or_none(item) for item in node.value]
        return ListEdit(
            tuple(
                ListItem(index, item, item != old[index]) if index < len(old) else ListItem(None, item, True)
                for index, item in enumerate(items)
            )
        )
    if not any(isinstance(item, (Mapping, list)) for item in items):
        return _value(items)
    return ListEdit(tuple(ListItem(None, item, True) for item in items))


def _data_or_none(node: yaml.Node) -> object:
    try:
        return node_data(node, "item")
    except ConfigError:
        return None


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
