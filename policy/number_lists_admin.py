"""The weighted number tables of a task page: a skip counting task's differences and an arithmetic task's numbers.

Each entry of a weighted list is one row of text: From, To, and Weight, and
for a skip counting difference its own Min, Max, and Multiples Only. A
``value`` entry shows its number in From with To empty. A ``from``/``to``
range shows both.

A save sends each changed list back as rows. A list whose rows hold the same
numbers as the file's keeps its text exactly. Any other list is written again
whole, one flow mapping per row in table order, with its keys in the order
``value`` or ``from`` and ``to``, then ``weight``, ``minimum_value``,
``maximum_value``, and ``multiples_only``. A row whose To is empty or equal
to From is written with ``value``, and an empty Weight as ``weight: 1``.

The page's own checks only catch typing mistakes on the row where they
happen. The policy check stays the one judge of a save.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from policy.arithmetic import OPERATIONS
from policy.skip_counting import default_differences
from policy.task_edit import ListEdit, ListItem, WrittenTask

SKIP_COUNTING_SETTINGS = (
    "sequence_length",
    "completed",
    "minimum_value",
    "maximum_value",
    "consecutive",
    "multiples_only",
    "timeout",
    "correct_answers_required",
    "minimum_questions",
    "maximum_questions",
)
# The checkbox settings and the value each has when the file leaves it out.
FLAGS = {"consecutive": True, "multiples_only": False}
ARITHMETIC_SETTINGS = ("operation", "max_timeout", "min_timeout", "correct_answers_required")
# A skip counting save sends this in place of rows to go back to the default list.
DEFAULT = "default"

_RANGE_KEYS = ("from", "to", "weight")
_BOUND_KEYS = ("minimum_value", "maximum_value", "multiples_only")
_NUMBER = re.compile(r"-?[0-9]+")


@dataclass(frozen=True)
class Table:
    """One weighted list a page shows as a table.

    ``bounds`` gives each row its own minimum, maximum, and multiples only.
    ``default`` lets a save go back to the default list by removing the
    field. ``optional`` removes the field when the table has no rows.
    """

    field: str
    bounds: bool = False
    default: bool = False
    optional: bool = False

    @property
    def keys(self) -> tuple[str, ...]:
        return _RANGE_KEYS + (_BOUND_KEYS if self.bounds else ())


DIFFERENCE = Table("difference", bounds=True, default=True)
FIRST = Table("first", optional=True)
OPERANDS = Table("operands")
SKIP_COUNTING_TABLES = (DIFFERENCE,)
ARITHMETIC_TABLES = (FIRST, OPERANDS)


def skip_counting_page(written: WrittenTask) -> dict:
    """Return the skip counting area of a task page.

    ``difference`` is None when the task uses the default list. ``default``
    is that list with each difference's own cap, which the page lowers to
    the Maximum Value it shows.
    """
    body = written.body_data
    rows, problems = _rows(body["difference"], DIFFERENCE) if "difference" in body else (None, [])
    return {
        "settings": {key: written.body.get(key, "") for key in SKIP_COUNTING_SETTINGS},
        "flags": {key: body[key] if isinstance(body.get(key), bool) else default for key, default in FLAGS.items()},
        "difference": rows,
        "default": _rows(default_differences(), DIFFERENCE)[0],
        "problems": problems,
    }


def arithmetic_page(written: WrittenTask) -> dict:
    """Return the arithmetic area of a task page. A task with no ``first`` shows it with no rows."""
    body = written.body_data
    first, first_problems = _rows(body["first"], FIRST) if "first" in body else ([], [])
    operands, operand_problems = _rows(body["operands"], OPERANDS) if "operands" in body else ([], [])
    return {
        "settings": {key: written.body.get(key, "") for key in ARITHMETIC_SETTINGS},
        "operations": [{"name": operation.name, "label": operation.label} for operation in OPERATIONS.values()],
        "first": first,
        "operands": operands,
        "problems": first_problems + operand_problems,
    }


def list_changes(written: WrittenTask, tables: tuple[Table, ...], asked: object) -> dict[str, object]:
    """Return the body changes for the lists a save sends, leaving out each list that is as written.

    A list maps to a ``ListEdit``, or to None to remove the field. Raises
    ``ValueError`` for a request the page would never send.
    """
    if asked is None:
        return {}
    if not isinstance(asked, Mapping):
        raise ValueError("lists must map each list to its rows")
    known = {table.field: table for table in tables}
    changes: dict[str, object] = {}
    for field, sent in asked.items():
        table = known.get(field)
        if table is None:
            raise ValueError(f"{field} cannot be changed from the parent pages")
        present = field in written.body_data
        if (sent == DEFAULT and table.default) or (sent == [] and table.optional):
            if present:
                changes[field] = None
            continue
        if not isinstance(sent, list):
            raise ValueError(f"{field} must be a list of rows")
        entries = [_entry(row, f"{field} row {number}", table) for number, row in enumerate(sent, 1)]
        if present and entries == _written_entries(written.body_data[field], table):
            continue
        changes[field] = ListEdit(tuple(ListItem(None, entry, True) for entry in entries), flow=True)
    return changes


def _rows(listed: object, table: Table) -> tuple[list[dict], list[str]]:
    """Return each entry of a list as the page shows it, and why any entry could not be shown."""
    if not isinstance(listed, list):
        return [], [f"{table.field}: must be a list of entries"]
    rows: list[dict] = []
    problems: list[str] = []
    for number, item in enumerate(listed, 1):
        where = f"{table.field} entry {number}"
        if not isinstance(item, Mapping):
            problems.append(f"{where}: must be a mapping with weight and value, or weight, from, and to")
            continue
        unknown = sorted(str(key) for key in set(item) - set(table.keys) - {"value"})
        if unknown:
            problems.append(f"{where}: unknown setting {unknown[0]}, which saving from this page leaves out")
        row = {
            "from": _text(item.get("value", item.get("from"))),
            "to": "" if "value" in item else _text(item.get("to")),
            "weight": _text(item.get("weight")),
        }
        if table.bounds:
            row["minimum_value"] = _text(item.get("minimum_value"))
            row["maximum_value"] = _text(item.get("maximum_value"))
            flag = item.get("multiples_only")
            row["multiples_only"] = flag if isinstance(flag, bool) else None
        rows.append(row)
    return rows, problems


def _written_entries(listed: object, table: Table) -> list[dict] | None:
    """Return the file's list as a save would write it, or None when it holds anything a save would not keep."""
    rows, problems = _rows(listed, table)
    if problems:
        return None
    try:
        return [_entry(row, "", table) for row in rows]
    except ValueError:
        return None


def _entry(row: object, where: str, table: Table) -> dict:
    """Return the entry a row is written as."""
    if not isinstance(row, Mapping):
        raise ValueError(f"{where} must be a mapping")
    unknown = sorted(str(key) for key in set(row) - set(table.keys))
    if unknown:
        raise ValueError(f"{where}: {unknown[0]} is not a column of this table")
    low = _number(row.get("from"), f"{where}: from")
    if low is None:
        raise ValueError(f"{where}: from is needed")
    high = _number(row.get("to"), f"{where}: to")
    weight = _number(row.get("weight"), f"{where}: weight")
    entry: dict = {"value": low} if high is None or high == low else {"from": low, "to": high}
    entry["weight"] = 1 if weight is None else weight
    if table.bounds:
        for key in ("minimum_value", "maximum_value"):
            bound = _number(row.get(key), f"{where}: {key}")
            if bound is not None:
                entry[key] = bound
        flag = row.get("multiples_only")
        if flag is not None and not isinstance(flag, bool):
            raise ValueError(f"{where}: multiples_only must be true, false, or left to the task")
        if flag is not None:
            entry["multiples_only"] = flag
    return entry


def _number(value: object, where: str) -> int | None:
    """Return a box's whole number, or None when it is empty."""
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    text = value.strip() if isinstance(value, str) else None
    if text == "":
        return None
    if text is None or not _NUMBER.fullmatch(text):
        raise ValueError(f"{where} must be a whole number")
    return int(text)


def _text(value: object) -> str:
    return "" if value is None else str(value)
