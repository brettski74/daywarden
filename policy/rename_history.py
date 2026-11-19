"""The stored rows that a rename of a client group, a site group, or a quota moves to the new name.

Usage, attempts, and the figures read from them are filed under the names of
the client group, the site group, and the quota they belong to. A rename
moves every such row in one transaction, so the history carries on under the
new name. ``usage_presets`` names them too, inside each preset's settings.
The decision log keeps the old names as it wrote them, and time windows and
rule sets have no stored history.

A table that the database does not have yet is skipped, because each module
makes its own tables the first time it is used.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence

# Each section a rename moves history for, and the table and column that file rows under its name.
COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "client_groups": (
        ("attempts", "client_group"),
        ("parent_checks", "client_group"),
        ("task_turns", "client_group"),
        ("spelling_word_tasks", "client_group"),
        ("arithmetic_fact_questions", "client_group"),
        ("group_buckets", "client_group"),
        ("quota_buckets", "client_group"),
        ("host_buckets", "client_group"),
        ("host_quota_buckets", "client_group"),
        ("requests", "client_group"),
        ("transfers", "client_group"),
    ),
    "site_groups": (
        ("group_buckets", "site_group"),
        ("host_buckets", "site_group"),
        ("requests", "site_group"),
        ("transfers", "site_group"),
    ),
    "quotas": (
        ("quota_buckets", "quota"),
        ("host_quota_buckets", "quota"),
        ("request_quotas", "quota"),
    ),
}
# The key of each section's names in a usage preset's settings.
_PRESET_KEY = {"client_groups": "client", "site_groups": "site", "quotas": "quota"}


def has_history(section: str) -> bool:
    """Whether stored rows are filed under the names of this section's items."""
    return section in COLUMNS


def stored_names(connection: sqlite3.Connection, section: str) -> set[str]:
    """Return every name that rows of this section's items are stored under, whether or not the policy still has it.

    A usage preset that names an item is not history, so it is not counted.
    """
    found: set[str] = set()
    present = _tables(connection)
    for table, column in COLUMNS.get(section, ()):
        if table in present:
            found.update(name for (name,) in connection.execute(f"SELECT DISTINCT {column} FROM {table}"))
    if section == "quotas" and "transfers" in present:
        for (raw,) in connection.execute("SELECT ceilings FROM transfers"):
            found.update(name for name, _level in _ceilings(raw))
    return found


def move(connection: sqlite3.Connection, section: str, old: str, new: str) -> int:
    """Move every row filed under ``old`` to ``new`` in one transaction, and return how many rows moved.

    A quota's name is also inside each open transfer's ceilings, and every
    section's names are inside the settings of the usage presets that chose
    them. Moving again is harmless: it finds nothing under ``old`` and moves
    only what has been filed there since.
    """
    if section not in COLUMNS:
        return 0
    moved = 0
    present = _tables(connection)
    with connection:
        for table, column in COLUMNS[section]:
            if table in present:
                moved += connection.execute(f"UPDATE {table} SET {column} = ? WHERE {column} = ?", (new, old)).rowcount
        if section == "quotas" and "transfers" in present:
            moved += _move_ceilings(connection, old, new)
        moved += _move_presets(connection, present, section, old, new)
    return moved


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {name for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _ceilings(raw: str) -> Sequence[tuple[str, int]]:
    try:
        parsed = json.loads(raw)
        return [(str(name), int(level)) for name, level in parsed]
    except (ValueError, TypeError):
        return []


def _move_ceilings(connection: sqlite3.Connection, old: str, new: str) -> int:
    moved = 0
    rows = connection.execute("SELECT flow_id, ceilings FROM transfers").fetchall()
    for flow_id, raw in rows:
        ceilings = _ceilings(raw)
        if not any(name == old for name, _level in ceilings):
            continue
        renamed = [[new if name == old else name, level] for name, level in ceilings]
        connection.execute(
            "UPDATE transfers SET ceilings = ? WHERE flow_id = ?", (json.dumps(renamed, separators=(",", ":")), flow_id)
        )
        moved += 1
    return moved


def _presets(connection: sqlite3.Connection, present: set[str]) -> dict[str, dict]:
    if "usage_presets" not in present:
        return {}
    found: dict[str, dict] = {}
    for name, raw in connection.execute("SELECT name, settings FROM usage_presets"):
        try:
            settings = json.loads(raw)
        except ValueError:
            continue
        if isinstance(settings, dict):
            found[name] = settings
    return found


def _move_presets(connection: sqlite3.Connection, present: set[str], section: str, old: str, new: str) -> int:
    key = _PRESET_KEY[section]
    moved = 0
    for name, settings in _presets(connection, present).items():
        names = settings.get(key)
        if not isinstance(names, list) or old not in names:
            continue
        renamed: list = []
        for each in names:
            each = new if each == old else each
            if each not in renamed:
                renamed.append(each)
        settings[key] = renamed
        connection.execute(
            "UPDATE usage_presets SET settings = ? WHERE name = ?", (json.dumps(settings, separators=(",", ":")), name)
        )
        moved += 1
    return moved
