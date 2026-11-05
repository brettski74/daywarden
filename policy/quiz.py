"""What the timed quizzes share: weighted lists, durations, and runs.

Each quiz keeps its record on the attempt's ``detail``: ``settings``,
``runs``, ``questions``, and ``last_activity``. The server issues each
question and records when it did. A run that sees no activity for an hour
expires, and the next visit starts a new run on the same attempt with the
task settings in force then. A question left showing when the page is
reloaded, or when he gives up, is a timeout.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

CORRECT = "correct"
INCORRECT = "incorrect"
TIMEOUT = "timeout"
OUTCOMES = (CORRECT, INCORRECT, TIMEOUT)

EXPIRY = timedelta(hours=1)
NETWORK_ALLOWANCE_MS = 500

_ENTRY_KEYS = {"value", "from", "to", "weight"}
_DURATION = re.compile(r"^(\d+)(ms|s|m|h)$")
_DURATION_SCALE = {"ms": 1, "s": 1000, "m": 60_000, "h": 3_600_000}


@dataclass(frozen=True)
class Entry:
    """Every whole number from ``low`` to ``high``, each with the full weight."""

    low: int
    high: int
    weight: int

    @property
    def total(self) -> int:
        return (self.high - self.low + 1) * self.weight


@dataclass(frozen=True)
class WeightedList:
    """Values and their weights. A range is never expanded into its values."""

    entries: tuple[Entry, ...]

    @property
    def total(self) -> int:
        return sum(entry.total for entry in self.entries)

    @property
    def count(self) -> int:
        """Return how many distinct values the list holds."""
        return sum(entry.high - entry.low + 1 for entry in self.entries)

    def weight(self, value: int) -> int:
        for entry in self.entries:
            if entry.low <= value <= entry.high:
                return entry.weight
        return 0

    def pick(self, offset: int, *, scale: int = 1, less: Mapping[int, int] | None = None) -> int:
        """Return the value at ``offset`` when value v weighs ``weight(v) * scale - less[v]``.

        ``offset`` is below the total of those weights. ``less`` holds the few
        values whose weight is reduced, so a long range is walked in pieces.
        """
        less = less or {}
        for entry in self.entries:
            unit = entry.weight * scale
            start = entry.low
            for special in sorted(value for value in less if entry.low <= value <= entry.high):
                plain = (special - start) * unit
                if offset < plain:
                    return start + offset // unit
                offset -= plain
                here = unit - less[special]
                if offset < here:
                    return special
                offset -= here
                start = special + 1
            plain = (entry.high - start + 1) * unit
            if offset < plain:
                return start + offset // unit
            offset -= plain
        raise ValueError("the offset is past the end of the weighted list")


class StaleQuestion(ValueError):
    """The answer is for a question that is no longer waiting for one."""


class QuizRecord:
    """Runs, expiry, and the question left showing, on one attempt.

    ``body`` is the task body in force now. It is used only when a run starts.
    Every method takes the household-local moment of the request, which is
    when the server received it. A subclass parses its settings and says how
    a question left showing is closed.
    """

    def __init__(self, detail: Mapping, body: Mapping) -> None:
        self.detail: dict = copy(detail)
        self.body = dict(body)
        self.detail.setdefault("questions", [])
        self.detail.setdefault("runs", [])

    def parse(self, body: object):
        raise NotImplementedError

    def time_out(self, question: dict) -> None:
        """Close a question that was left showing."""
        raise NotImplementedError

    @property
    def settings(self):
        return self.parse(self.detail["settings"])

    @property
    def questions(self) -> list[dict]:
        return self.detail["questions"]

    @property
    def run(self) -> int:
        return self.detail["runs"][-1]["run"]

    @property
    def pending(self) -> dict | None:
        if self.questions and self.questions[-1].get("outcome") is None:
            return self.questions[-1]
        return None

    def in_run(self) -> list[dict]:
        """Return the questions of the current run, oldest first."""
        return [item for item in self.questions if item.get("run") == self.run]

    def visit(self, now: datetime) -> None:
        """Record a page load. A question left showing is a timeout."""
        self.resume(now)
        self.close_pending()
        self.touch(now)

    def settle(self, now: datetime) -> None:
        """Close a question left showing, as when he gives up."""
        if self.detail["runs"]:
            self.close_pending()
            self.touch(now)

    def resume(self, now: datetime) -> None:
        runs = self.detail["runs"]
        if not runs or not self._valid_settings():
            self._start_run(now)
            return
        last = self.detail.get("last_activity")
        if last is None:
            return
        idle_since = datetime.fromisoformat(last)
        if now - idle_since <= EXPIRY:
            return
        self.close_pending()
        runs[-1]["expired"] = stamp(idle_since + EXPIRY)
        self._start_run(now)

    def close_pending(self) -> None:
        pending = self.pending
        if pending is not None:
            self.time_out(pending)

    def touch(self, now: datetime) -> None:
        self.detail["last_activity"] = stamp(now)

    def taken_ms(self, question: Mapping, now: datetime) -> int:
        return max(0, round((now - datetime.fromisoformat(question["issued"])).total_seconds() * 1000))

    def _start_run(self, now: datetime) -> None:
        self.parse(self.body)
        runs = self.detail["runs"]
        runs.append({"run": len(runs) + 1, "started": stamp(now)})
        self.detail["settings"] = dict(self.body)
        self.detail["last_activity"] = stamp(now)

    def _valid_settings(self) -> bool:
        try:
            self.parse(self.detail.get("settings"))
        except ValueError:
            return False
        return True


def duration(value: object, field: str, *, zero: bool = False) -> int:
    """Return a duration such as ``10s`` or ``7500ms`` in milliseconds. ``zero`` allows ``0ms``."""
    if not isinstance(value, str):
        raise ValueError(f"{field}: must be a duration such as 10s or 7500ms, not a bare number")
    match = _DURATION.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"{field}: must be a duration such as 10s or 7500ms")
    milliseconds = int(match.group(1)) * _DURATION_SCALE[match.group(2)]
    if milliseconds <= 0 and not zero:
        raise ValueError(f"{field}: must be longer than zero")
    return milliseconds


def weighted(
    value: object,
    field: str,
    number: Callable[[object, str], int],
    check: Callable[[Entry, str, Mapping], None] | None = None,
    extra: frozenset[str] = frozenset(),
) -> WeightedList:
    """Return a weighted list of entries.

    ``number`` checks each ``value``, ``from``, and ``to``. ``extra`` names
    any other keys an entry may have. ``check`` looks at each finished entry
    and the mapping it was written as. Both raise ``ValueError`` naming the
    entry.
    """
    if not isinstance(value, list):
        raise ValueError(f"{field}: must be a list of entries")
    if not value:
        raise ValueError(f"{field}: must have at least one entry")
    entries = []
    for position, item in enumerate(value, start=1):
        where = f"{field} entry {position}"
        entry = _entry(item, where, number, extra)
        if check is not None:
            check(entry, where, item)
        entries.append(entry)
    ordered = sorted(enumerate(entries, start=1), key=lambda pair: pair[1].low)
    for (left_number, left), (right_number, right) in zip(ordered, ordered[1:]):
        if right.low <= left.high:
            raise ValueError(
                f"{field}: entries {min(left_number, right_number)} and {max(left_number, right_number)} "
                "both include the value "
                f"{right.low}"
            )
    return WeightedList(tuple(entry for _number, entry in ordered))


def _entry(item: object, where: str, number: Callable[[object, str], int], extra: frozenset[str]) -> Entry:
    if not isinstance(item, Mapping):
        raise ValueError(f"{where}: must be a mapping with weight and value, or weight, from, and to")
    unknown = sorted(set(item) - _ENTRY_KEYS - extra)
    if unknown:
        raise ValueError(f"{where}: unknown setting {unknown[0]}")
    if "weight" not in item:
        raise ValueError(f"{where}: weight is required")
    weight = item["weight"]
    if not is_whole(weight) or weight < 1:
        raise ValueError(f"{where}: weight must be a whole number, 1 or more")
    has_value = "value" in item
    has_from = "from" in item
    has_to = "to" in item
    if has_value and (has_from or has_to):
        raise ValueError(f"{where}: give value, or from and to, not both")
    if has_value:
        value = number(item["value"], f"{where}: value")
        return Entry(value, value, weight)
    if not has_from and not has_to:
        raise ValueError(f"{where}: value, or from and to, is required")
    if not (has_from and has_to):
        raise ValueError(f"{where}: a range needs both from and to")
    low = number(item["from"], f"{where}: from")
    high = number(item["to"], f"{where}: to")
    if low > high:
        raise ValueError(f"{where}: from must be no larger than to")
    return Entry(low, high, weight)


def is_whole(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds")


def copy(value):
    if isinstance(value, Mapping):
        return {key: copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [copy(item) for item in value]
    return value
