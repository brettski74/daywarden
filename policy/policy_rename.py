"""Renaming a named item in the text of a policy file, and every reference to it.

``renamed_text`` changes only the scalars that hold the name: the item's own
key, and each place the policy names it. The rest of the file, comments and
layout included, is left as written. A name keeps the style it was written in
(plain, ``"double"``, or ``'single'``) when the new name can be written that
way.

What names each kind of item:

* A client group: ``group`` or ``groups`` of a ``client_group`` rule, and of
  each task in ``tasks``.
* A site group: ``group`` or ``groups`` of a ``site_group`` rule.
* A time window: ``window`` or ``windows`` of a ``time_window`` rule.
* A quota: ``quota`` of a ``time_remaining`` or ``volume_remaining`` rule.
* A rule set: ``entry``, a quota's ``ruleset``, and the ``ruleset`` of an
  ``evaluate`` action.

Rules are found in every rule set, and in the inline ``rules`` of an
``evaluate`` action at any depth.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from policy.task_edit import _entries, _key, _root, scalar

# What a rule's condition is, for the sections a rule's condition names, and the fields that hold the names.
_CONDITION = {
    "client_groups": ("client_group", ("group", "groups")),
    "site_groups": ("site_group", ("group", "groups")),
    "time_windows": ("time_window", ("window", "windows")),
}
_QUOTA_CONDITIONS = frozenset({"time_remaining", "volume_remaining"})
_BRANCHES = ("when_true", "when_false")


def renamed_text(text: str, source: Path, section: str, old: str, new: str) -> str:
    """Return ``text`` with the item ``old`` of ``section`` called ``new`` wherever this file writes it.

    Raises ``EditError`` when the file cannot be read as a policy file.
    """
    root = _root(text, source)
    if root is None:
        return text
    spans: list[tuple[int, int, str]] = []

    def swap(node: yaml.Node | None, *, key: bool = False) -> None:
        if isinstance(node, yaml.ScalarNode) and node.value.strip() == old:
            spans.append((node.start_mark.index, node.end_mark.index, _spelled(node, new, key=key)))

    def swap_all(node: yaml.Node | None) -> None:
        if isinstance(node, yaml.SequenceNode):
            for item in node.value:
                swap(item)
        else:
            swap(node)

    def rules(node: yaml.Node | None) -> None:
        if not isinstance(node, yaml.SequenceNode):
            return
        for rule in node.value:
            if not isinstance(rule, yaml.MappingNode):
                continue
            fields = {name: value for name, _key_node, value in _entries(rule)}
            condition = fields.get("condition")
            kind = condition.value.strip() if isinstance(condition, yaml.ScalarNode) else ""
            if section in _CONDITION and kind == _CONDITION[section][0]:
                for field in _CONDITION[section][1]:
                    swap_all(fields.get(field))
            elif section == "quotas" and kind in _QUOTA_CONDITIONS:
                swap(fields.get("quota"))
            for branch in _BRANCHES:
                action = fields.get(branch)
                if not isinstance(action, yaml.MappingNode):
                    continue
                inside = {name: value for name, _key_node, value in _entries(action)}
                if section == "rule_sets":
                    swap(inside.get("ruleset"))
                rules(inside.get("rules"))

    for name, key_node, value in _entries(root):
        if name == "entry" and section == "rule_sets":
            swap(value)
        elif name == section and isinstance(value, yaml.MappingNode):
            for item, item_key, _body in _entries(value):
                if item.strip() == old:
                    swap(item_key, key=True)
        if name == "quotas" and section == "rule_sets" and isinstance(value, yaml.MappingNode):
            for _item, _item_key, body in _entries(value):
                if isinstance(body, yaml.MappingNode):
                    swap(next((field for field_name, _k, field in _entries(body) if field_name == "ruleset"), None))
        elif name == "rule_sets" and isinstance(value, yaml.MappingNode):
            for _item, _item_key, body in _entries(value):
                rules(body)
        elif name == "tasks" and section == "client_groups" and isinstance(value, yaml.MappingNode):
            for _kind, _kind_key, names in _entries(value):
                if not isinstance(names, yaml.MappingNode):
                    continue
                for _task, _task_key, body in _entries(names):
                    if isinstance(body, yaml.MappingNode):
                        for field_name, _k, field in _entries(body):
                            if field_name in ("group", "groups"):
                                swap_all(field)
    for start, end, replacement in sorted(spans, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


def _spelled(node: yaml.ScalarNode, name: str, *, key: bool) -> str:
    """Return ``name`` written the way ``node`` writes its text, quoted when the name cannot be plain."""
    if node.style == '"':
        return json.dumps(name, ensure_ascii=False)
    if node.style == "'":
        return "'" + name.replace("'", "''") + "'"
    return _key(name) if key else scalar(name, name=True)
