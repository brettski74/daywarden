"""Read and rewrite one task in a policy file, leaving the rest of the file as it was.

The parent pages change a task's fields in place. Only the text of the
fields that change is rewritten: every other line, comment, quote, and
space in the file stays exactly as it was written, including the rest of
that task. A round-trip YAML library would re-space flow mappings and drop
trailing spaces across the whole file, so this edits the text at the
positions the loader's own YAML parser reports.

A changed scalar keeps its place and any comment after it. A cleared field
loses its line. A new field goes after the last field of its mapping, at
the same indent. A flow mapping, such as ``body: { timeout: 30s }``, is
written again as a flow mapping, with its untouched entries copied as they
were.

A list, such as a parts of speech task's ``sentences``, is changed with a
``ListEdit``. Each item kept unchanged keeps its text exactly. A changed
item is written again in its place as a block entry, a removed item loses
its lines, and a new item goes after the last one. A list written in flow
style, or inside a flow mapping, is written again as a block list as a
whole, and a flow body around it becomes a block mapping.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from policy.hierarchy import ConfigError, compose, node_data

_PLAIN = re.compile(r"-?[A-Za-z0-9][A-Za-z0-9._+-]*")
_SIMPLE_STYLES = (None, "", "'", '"')


class EditError(ValueError):
    """The task cannot be edited from the parent pages, and the reason why."""


@dataclass(frozen=True)
class WrittenTask:
    """A task as its file writes it: each field's text, the client groups, and the body's scalar fields.

    ``group_key`` is ``group`` or ``groups``, whichever the file uses.
    ``body_data`` is the body's value as the loader reads it, or empty when
    it cannot be read.
    """

    fields: dict[str, str]
    groups: tuple[str, ...]
    body: dict[str, str]
    group_key: str | None = None
    body_data: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ListItem:
    """One item of a list being written again.

    ``origin`` is its place in the list as the file writes it, or None for a
    new item. ``data`` is what to write when the item is written again: a
    mapping of scalars, lists of scalars, and mappings.
    """

    origin: int | None
    data: object
    changed: bool


@dataclass(frozen=True)
class ListEdit:
    """A list's new items in order. Items kept from the file keep their order."""

    items: tuple[ListItem, ...]


def scalar(text: str, *, name: bool = False) -> str:
    """Return the YAML for a value the parent typed.

    A simple value, such as ``3``, ``2026-11-30``, or ``30s``, is written
    bare, so the loader reads it as the number, date, or text it looks
    like. Anything else is written as a quoted string, so it cannot change
    the shape of the file, and the loader refuses it naming the field. A
    name, such as a client group, is quoted when it would read as anything
    other than text.
    """
    value = text.strip()
    if _PLAIN.fullmatch(value) and (not name or isinstance(yaml.safe_load(value), str)):
        return value
    return json.dumps(value, ensure_ascii=False)


def name_list(names: tuple[str, ...] | list[str]) -> str:
    return "[" + ", ".join(scalar(name, name=True) for name in names) + "]"


def read_task(text: str, source: Path, name: str) -> WrittenTask:
    """Return how the file writes the task ``name``."""
    node = _task_node(text, source, name)
    if not isinstance(node, yaml.MappingNode):
        raise EditError(f"{name} is not written as a mapping in {source}")
    fields: dict[str, str] = {}
    groups: tuple[str, ...] = ()
    group_key = None
    body: dict[str, str] = {}
    body_data: dict[str, object] = {}
    for key, _key_node, value in _entries(node):
        if key == "body":
            if isinstance(value, yaml.MappingNode):
                body = {inner: _shown(text, item) for inner, _node, item in _entries(value)}
                try:
                    body_data = node_data(value, "body")
                except ConfigError:
                    body_data = {}
        elif key == "group" and isinstance(value, yaml.ScalarNode):
            groups, group_key = (value.value.strip(),), key
        elif key == "groups" and isinstance(value, yaml.SequenceNode):
            groups = tuple(item.value.strip() for item in value.value if isinstance(item, yaml.ScalarNode))
            group_key = key
        else:
            fields[key] = _shown(text, value)
    return WrittenTask(fields, groups, body, group_key, body_data)


def rewrite_task(text: str, source: Path, name: str, changes: Mapping[str, object]) -> str:
    """Return ``text`` with the task ``name`` changed.

    ``changes`` maps a field to its new YAML text, or to None to remove it.
    ``body`` maps to a mapping of the body's own changes in the same form,
    where a list may be changed with a ``ListEdit``.
    """
    node = _task_node(text, source, name)
    if not isinstance(node, yaml.MappingNode):
        raise EditError(f"{name} is not written as a mapping in {source}")
    step = max(2, _indent(node) - _name_column(text, source, name)) if not node.flow_style else 2
    return _apply(text, _edit_mapping(text, node, changes, step))


def _task_node(text: str, source: Path, name: str) -> yaml.Node:
    try:
        root = compose(text, source)
    except ConfigError as error:
        raise EditError(str(error)) from error
    if not isinstance(root, yaml.MappingNode):
        raise EditError(f"{source}: the file must be a mapping")
    for key, _key_node, value in _entries(root):
        if key != "tasks" or not isinstance(value, yaml.MappingNode):
            continue
        for task, _task_key, body in _entries(value):
            if task.strip() == name:
                return body
    raise EditError(f"{source} does not define the task {name}")


def _name_column(text: str, source: Path, name: str) -> int:
    root = compose(text, source)
    for key, _key_node, value in _entries(root):
        if key == "tasks" and isinstance(value, yaml.MappingNode):
            for task, task_key, _body in _entries(value):
                if task.strip() == name:
                    return task_key.start_mark.column
    return 0


def _entries(node: yaml.MappingNode) -> list[tuple[str, yaml.Node, yaml.Node]]:
    return [(key.value, key, value) for key, value in node.value if isinstance(key, yaml.ScalarNode)]


def _shown(text: str, node: yaml.Node) -> str:
    if isinstance(node, yaml.ScalarNode):
        return node.value
    return text[node.start_mark.index : _last_end(text, node)]


def _last_end(text: str, node: yaml.Node) -> int:
    """Return where a node's own text ends, before any comment or blank line after it."""
    if isinstance(node, (yaml.MappingNode, yaml.SequenceNode)) and not node.flow_style and node.value:
        last = node.value[-1]
        return _last_end(text, last[1] if isinstance(last, tuple) else last)
    end = node.end_mark.index
    start = node.start_mark.index
    while end > start and text[end - 1] in " \t\r\n":
        end -= 1
    return end


def _indent(node: yaml.MappingNode) -> int:
    return node.value[0][0].start_mark.column if node.value else 0


def _line_start(text: str, index: int) -> int:
    return text.rfind("\n", 0, index) + 1


def _line_end(text: str, index: int) -> int:
    found = text.find("\n", index)
    return len(text) if found < 0 else found + 1


# The span to replace, the text to put there, and how deeply nested the mapping is.
Edit = tuple[int, int, str, int]


def _apply(text: str, edits: list[Edit]) -> str:
    # A nested mapping's new lines go before its parent's new lines at the same place.
    for start, end, replacement, _depth in sorted(edits, key=lambda edit: (edit[0], edit[1], -edit[3]), reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


def _edit_mapping(text: str, node: yaml.MappingNode, changes: Mapping[str, object], step: int, depth: int = 0) -> list[Edit]:
    if node.flow_style:
        return [(node.start_mark.index, node.end_mark.index, _flow_text(text, node, changes), depth)]
    edits: list[Edit] = []
    present = {key: (key_node, value) for key, key_node, value in _entries(node)}
    indent = " " * _indent(node)
    added: list[str] = []
    for key, change in changes.items():
        if key not in present:
            if change is None or (isinstance(change, Mapping) and not _sets_anything(change)):
                continue
            added.append(_block_entry(key, change, indent, step))
            continue
        key_node, value = present[key]
        if isinstance(change, ListEdit):
            if isinstance(value, yaml.SequenceNode) and not value.flow_style and value.value:
                edits += _edit_sequence(text, value, change, step, depth + 1)
            else:
                start, end = _entry_span(text, key_node, value)
                edits.append((start, end, _list_entry(key, change, indent, step), depth))
            continue
        if isinstance(change, Mapping):
            if isinstance(value, yaml.MappingNode):
                if value.flow_style and _holds_list_edit(change):
                    start, end = _entry_span(text, key_node, value)
                    edits.append((start, end, _block_from_flow(text, key, value, change, indent, step), depth))
                elif not value.flow_style and _empties(value, change):
                    edits.append((*_entry_span(text, key_node, value), "", depth))
                else:
                    edits += _edit_mapping(text, value, change, step, depth + 1)
                continue
            if not _sets_anything(change):
                continue
            start, end = _entry_span(text, key_node, value)
            edits.append((start, end, _block_entry(key, change, indent, step), depth))
            continue
        if change is None:
            edits.append((*_entry_span(text, key_node, value), "", depth))
        elif _replaceable(value):
            edits.append((value.start_mark.index, value.end_mark.index, str(change), depth))
        else:
            start, end = _entry_span(text, key_node, value)
            edits.append((start, end, f"{indent}{key}: {change}\n", depth))
    if added:
        at = _line_end(text, _last_end(text, node))
        prefix = "" if at == 0 or text[at - 1] == "\n" else "\n"
        edits.append((at, at, prefix + "".join(added), depth))
    return edits


def _sets_anything(changes: Mapping[str, object]) -> bool:
    return any(value is not None for value in changes.values())


def _empties(node: yaml.MappingNode, changes: Mapping[str, object]) -> bool:
    """True when the changes remove every field of a mapping and add none."""
    keys = {key for key, _key_node, _value in _entries(node)}
    removed = {key for key, value in changes.items() if value is None}
    added = {key for key, value in changes.items() if value is not None and key not in keys}
    return keys <= removed and not added


def _replaceable(node: yaml.Node) -> bool:
    """True for a one-line scalar whose text can be swapped where it stands."""
    if not isinstance(node, yaml.ScalarNode) or node.style not in _SIMPLE_STYLES:
        return False
    if node.style in (None, "") and node.value == "":
        return False
    return node.start_mark.line == node.end_mark.line


def _entry_span(text: str, key_node: yaml.Node, value: yaml.Node) -> tuple[int, int]:
    """Return the lines that hold one block mapping entry, to be removed."""
    start = _line_start(text, key_node.start_mark.index)
    if text[start : key_node.start_mark.index].strip():
        raise EditError(f"line {key_node.start_mark.line + 1} is laid out in a way the parent pages cannot edit; edit it by hand")
    return start, _line_end(text, max(_last_end(text, value), key_node.end_mark.index))


def _block_entry(key: str, change: object, indent: str, step: int) -> str:
    if isinstance(change, ListEdit):
        return _list_entry(key, change, indent, step)
    if not isinstance(change, Mapping):
        return f"{indent}{key}: {change}\n"
    inner = indent + " " * step
    lines = "".join(_block_entry(field, value, inner, step) for field, value in change.items() if value is not None)
    return f"{indent}{key}:\n{lines}"


def _holds_list_edit(changes: Mapping[str, object]) -> bool:
    return any(isinstance(value, ListEdit) for value in changes.values())


def _edit_sequence(text: str, node: yaml.SequenceNode, edit: ListEdit, step: int, depth: int) -> list[Edit]:
    """Return the edits that make a block list hold ``edit``'s items, keeping each unchanged item's text."""
    origins = [item.origin for item in edit.items if item.origin is not None]
    if origins != sorted(set(origins)) or any(not 0 <= origin < len(node.value) for origin in origins):
        raise EditError("the list's items must keep their order")
    by_origin = {item.origin: item for item in edit.items if item.origin is not None}
    edits: list[Edit] = []
    indent = ""
    for index, value in enumerate(node.value):
        dash = _dash(text, value)
        start = _line_start(text, dash)
        indent = text[start:dash]
        end = _line_end(text, _last_end(text, value))
        item = by_origin.get(index)
        if item is None:
            edits.append((start, end, "", depth))
        elif item.changed:
            edits.append((start, end, _list_item(item.data, indent, step), depth))
    added = "".join(_list_item(item.data, indent, step) for item in edit.items if item.origin is None)
    if added:
        at = _line_end(text, _last_end(text, node.value[-1]))
        prefix = "" if at == 0 or text[at - 1] == "\n" else "\n"
        edits.append((at, at, prefix + added, depth))
    return edits


def _dash(text: str, item: yaml.Node) -> int:
    """Return where the ``-`` of a block list item is, which may be on a line of its own."""
    at = item.start_mark.index - 1
    while at >= 0 and text[at] in " \t\r\n":
        at -= 1
    if at < 0 or text[at] != "-" or text[_line_start(text, at) : at].strip():
        raise EditError(f"line {item.start_mark.line + 1} is laid out in a way the parent pages cannot edit; edit it by hand")
    return at


def _list_entry(key: str, edit: ListEdit, indent: str, step: int) -> str:
    """Return a whole list as a block entry, every item written from its data."""
    if not edit.items:
        return f"{indent}{key}: []\n"
    inner = indent + " " * step
    return f"{indent}{key}:\n" + "".join(_list_item(item.data, inner, step) for item in edit.items)


def _list_item(data: object, indent: str, step: int) -> str:
    """Return one block list item, its dash at ``indent``."""
    if not isinstance(data, Mapping) or not data:
        return f"{indent}- {_value(data)}\n"
    inner = indent + "  "
    lines = "".join(_data_entry(key, value, inner, step) for key, value in data.items())
    return indent + "- " + lines[len(inner) :]


def _data_entry(key: object, value: object, indent: str, step: int) -> str:
    if isinstance(value, Mapping) and value:
        inner = indent + " " * step
        return f"{indent}{_key(key)}:\n" + "".join(_data_entry(name, item, inner, step) for name, item in value.items())
    return f"{indent}{_key(key)}: {_value(value)}\n"


def _value(value: object) -> str:
    """Return a value as flow YAML that reads back as the same value, quoting text only where it must."""
    if isinstance(value, Mapping):
        return "{ " + ", ".join(f"{_key(key)}: {_value(item)}" for key, item in value.items()) + " }" if value else "{}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_flow_item(item) for item in value) + "]"
    if isinstance(value, str):
        return value if _reads_back(f"k: {value}", {"k": value}) else json.dumps(value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)


def _flow_item(value: object) -> str:
    if isinstance(value, str):
        return value if _reads_back(f"[{value}]", [value]) else json.dumps(value, ensure_ascii=False)
    return _value(value)


def _key(key: object) -> str:
    if isinstance(key, str) and _reads_back(f"{key}: 0", {key: 0}):
        return key
    return json.dumps(key if isinstance(key, str) else str(key), ensure_ascii=False)


def _reads_back(written: str, expected: object) -> bool:
    if "\n" in written or "\r" in written or written != written.strip():
        return False
    try:
        return yaml.safe_load(written) == expected
    except yaml.YAMLError:
        return False


def _block_from_flow(text: str, key: str, node: yaml.MappingNode, changes: Mapping[str, object], indent: str, step: int) -> str:
    """Return a flow mapping as a block entry with the changes made, copying each untouched scalar as written."""
    inner = indent + " " * step
    lines: list[str] = []
    seen: set[str] = set()
    for name, key_node, value in _entries(node):
        seen.add(name)
        change = changes.get(name, _KEEP)
        written = text[key_node.start_mark.index : key_node.end_mark.index]
        if change is _KEEP:
            if isinstance(value, yaml.ScalarNode):
                lines.append(f"{inner}{written}: {text[value.start_mark.index : value.end_mark.index]}\n")
            else:
                try:
                    lines.append(f"{inner}{written}: {json.dumps(node_data(value, name), ensure_ascii=False)}\n")
                except ConfigError as error:
                    raise EditError(str(error)) from error
        elif isinstance(change, Mapping):
            raise EditError(f"{key} is written in a way the parent pages cannot edit; edit it by hand")
        elif change is not None:
            lines.append(_block_entry(name, change, inner, step))
    for name, change in changes.items():
        if name not in seen and change is not None:
            lines.append(_block_entry(name, change, inner, step))
    return f"{indent}{key}:\n" + "".join(lines) if lines else f"{indent}{key}: {{}}\n"


def _flow_text(text: str, node: yaml.MappingNode, changes: Mapping[str, object]) -> str:
    if _holds_list_edit(changes) or any(isinstance(value, Mapping) and _holds_list_edit(value) for value in changes.values()):
        raise EditError(
            f"line {node.start_mark.line + 1} writes the task in flow style, which the parent pages cannot rewrite "
            "with a list; edit it by hand"
        )
    parts: list[str] = []
    seen: set[str] = set()
    for key, key_node, value in _entries(node):
        seen.add(key)
        change = changes.get(key, _KEEP)
        if change is _KEEP:
            parts.append(text[key_node.start_mark.index : value.end_mark.index])
        elif isinstance(change, Mapping) and isinstance(value, yaml.MappingNode):
            inner = _apply(text, _edit_mapping(text, value, change, 2))
            shift = len(inner) - len(text)
            parts.append(f"{key}: {inner[value.start_mark.index : value.end_mark.index + shift]}")
        elif isinstance(change, Mapping):
            parts.append(f"{key}: {_flow_mapping(change)}")
        elif change is not None:
            parts.append(f"{key}: {change}")
    for key, change in changes.items():
        if key in seen or change is None:
            continue
        if isinstance(change, Mapping):
            if _sets_anything(change):
                parts.append(f"{key}: {_flow_mapping(change)}")
        else:
            parts.append(f"{key}: {change}")
    return "{ " + ", ".join(parts) + " }" if parts else "{}"


def _flow_mapping(changes: Mapping[str, object]) -> str:
    parts = [f"{key}: {value}" for key, value in changes.items() if value is not None]
    return "{ " + ", ".join(parts) + " }" if parts else "{}"


_KEEP = object()
