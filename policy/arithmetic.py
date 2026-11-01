"""Arithmetic quiz: configuration, question draws, and the session record.

A task of type ``arithmetic`` keeps its quiz fields in ``body``. They are
checked when the policy is loaded, so a bad operand list fails the load and
the previous policy stays in force.

The session lives on the attempt's ``detail``. The server issues each
question, records when it did, and judges every answer against that moment.
The browser draws the timer, but it does not decide whether an answer was
in time. A run that sees no activity for an hour expires. The next visit
starts a new run on the same attempt with the task settings in force then.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

ARITHMETIC = "arithmetic"
CORRECT = "correct"
INCORRECT = "incorrect"
TIMEOUT = "timeout"
OUTCOMES = (CORRECT, INCORRECT, TIMEOUT)

EXPIRY = timedelta(hours=1)
NETWORK_ALLOWANCE_MS = 500
RECENT_QUESTIONS = 3
LONGEST_ANSWER = 20

_BODY_KEYS = {"operation", "max_timeout", "min_timeout", "correct_answers_required", "operands", "first"}
_REQUIRED_KEYS = ("operation", "max_timeout", "min_timeout", "correct_answers_required", "operands")
_ENTRY_KEYS = {"value", "from", "to", "weight"}
_TIMEOUT = re.compile(r"^(\d+)(ms|s|m|h)$")
_TIMEOUT_SCALE = {"ms": 1, "s": 1000, "m": 60_000, "h": 3_600_000}
_DIGITS = re.compile(r"^[0-9]+$")


@dataclass(frozen=True)
class Operation:
    """How one operation shows a question and what it expects."""

    name: str
    label: str
    text: Callable[[int, int], str]
    answer: Callable[[int, int], int]


OPERATIONS: dict[str, Operation] = {
    "addition": Operation("addition", "Addition", lambda m, n: f"{m} + {n} =", lambda m, n: m + n),
}


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


@dataclass(frozen=True)
class Settings:
    """One run's quiz settings. Timeouts are milliseconds."""

    operation: Operation
    max_timeout: int
    min_timeout: int
    required: int
    operands: WeightedList
    first: WeightedList | None = None

    @property
    def lefts(self) -> WeightedList:
        return self.operands if self.first is None else self.first

    def timeout(self, correct: int) -> int:
        """Return the time allowed after ``correct`` right answers, in milliseconds."""
        if self.required == 1:
            return self.max_timeout
        step = min(max(correct, 0), self.required - 1) / (self.required - 1)
        return round(self.max_timeout * (self.min_timeout / self.max_timeout) ** step)


def parse_settings(body: Mapping) -> Settings:
    """Check an arithmetic task body and return its settings.

    A problem raises ``ValueError`` whose message starts with the field.
    """
    if not isinstance(body, Mapping):
        raise ValueError("body must be a mapping")
    unknown = sorted(set(body) - _BODY_KEYS)
    if unknown:
        raise ValueError(f"{unknown[0]}: unknown setting")
    for key in _REQUIRED_KEYS:
        if key not in body:
            raise ValueError(f"{key}: is required")
    name = body["operation"]
    if not isinstance(name, str) or name not in OPERATIONS:
        known = ", ".join(sorted(OPERATIONS))
        raise ValueError(f"operation: {name!r} is not an operation this service has; use {known}")
    longest = _timeout(body["max_timeout"], "max_timeout")
    shortest = _timeout(body["min_timeout"], "min_timeout")
    if shortest > longest:
        raise ValueError("min_timeout: must be no longer than max_timeout")
    required = body["correct_answers_required"]
    if not _is_whole(required) or required < 1:
        raise ValueError("correct_answers_required: must be a whole number, 1 or more")
    first = None if "first" not in body else _weighted(body["first"], "first")
    return Settings(OPERATIONS[name], longest, shortest, required, _weighted(body["operands"], "operands"), first)


def draw(settings: Settings, recent: Sequence[tuple[int, int]], rng: random.Random) -> tuple[int, int]:
    """Draw ``(m, n)``, leaving out the last three questions when it can.

    ``recent`` is oldest first. The remaining questions keep their relative
    weights. When every allowed question is recent, the oldest recent one is
    let back first, and the question just asked is the last.
    """
    for keep in range(min(RECENT_QUESTIONS, len(recent)), -1, -1):
        excluded = frozenset(recent[len(recent) - keep :]) if keep else frozenset()
        pair = _draw_without(settings.lefts, settings.operands, excluded, rng)
        if pair is not None:
            return pair
    raise ValueError("an operand list has no weight")


def _draw_without(
    lefts: WeightedList,
    rights: WeightedList,
    excluded: frozenset[tuple[int, int]],
    rng: random.Random,
) -> tuple[int, int] | None:
    held_by_left: dict[int, int] = {}
    for m, n in excluded:
        if lefts.weight(m) and rights.weight(n):
            held_by_left[m] = held_by_left.get(m, 0) + rights.weight(n)
    less = {m: lefts.weight(m) * held for m, held in held_by_left.items()}
    total = lefts.total * rights.total - sum(less.values())
    if total <= 0:
        return None
    m = lefts.pick(rng.randrange(total), scale=rights.total, less=less)
    skip = {n: rights.weight(n) for left, n in excluded if left == m and rights.weight(n)}
    n = rights.pick(rng.randrange(rights.total - sum(skip.values())), less=skip)
    return m, n


@dataclass(frozen=True)
class Judged:
    """What the server decided about one answer."""

    outcome: str
    question: Mapping
    correct: int
    required: int
    finished: bool


class StaleQuestion(ValueError):
    """The answer is for a question that is no longer waiting for one."""


class Session:
    """The arithmetic record on one attempt.

    ``body`` is the task body in force now. It is used only when a run starts.
    Every method takes the household-local moment of the request, which is
    when the server received it.
    """

    def __init__(self, detail: Mapping, body: Mapping) -> None:
        self.detail: dict = _copy(detail)
        self.body = dict(body)
        self.detail.setdefault("questions", [])
        self.detail.setdefault("runs", [])

    @property
    def settings(self) -> Settings:
        return parse_settings(self.detail["settings"])

    @property
    def questions(self) -> list[dict]:
        return self.detail["questions"]

    @property
    def run(self) -> int:
        return self.detail["runs"][-1]["run"]

    @property
    def correct(self) -> int:
        return sum(1 for item in self.questions if item.get("run") == self.run and item.get("outcome") == CORRECT)

    @property
    def pending(self) -> dict | None:
        if self.questions and self.questions[-1].get("outcome") is None:
            return self.questions[-1]
        return None

    def visit(self, now: datetime) -> None:
        """Record a page load. A question left showing is a timeout."""
        self._resume(now)
        self._close_pending()
        self._touch(now)

    def settle(self, now: datetime) -> None:
        """Close a question left showing, as when he gives up."""
        if self.detail["runs"]:
            self._close_pending()
            self._touch(now)

    def issue(self, now: datetime, rng: random.Random) -> dict:
        """Issue the next question and start its time now."""
        self._resume(now)
        self._close_pending()
        settings = self.settings
        recent = [
            (item["m"], item["n"])
            for item in self.questions[-RECENT_QUESTIONS:]
            if item.get("question") == settings.operation.text(item["m"], item["n"])
        ]
        m, n = draw(settings, recent, rng)
        question = {
            "run": self.run,
            "m": m,
            "n": n,
            "question": settings.operation.text(m, n),
            "expected": settings.operation.answer(m, n),
            "answer": None,
            "outcome": None,
            "allowed_ms": settings.timeout(self.correct),
            "taken_ms": None,
            "issued": _stamp(now),
        }
        self.questions.append(question)
        self._touch(now)
        return question

    def answer(self, now: datetime, number: object, text: object, *, expired: bool) -> Judged:
        """Judge an answer the server received now.

        ``expired`` means the browser's timer ran out and it sent whatever
        was in the box. Then a right answer in time is correct and anything
        else is a timeout. An answer that arrives after the time allowed plus
        the network allowance is a timeout whatever it says, and it is still
        recorded.
        """
        self._resume(now)
        pending = self.pending
        if pending is None or number != len(self.questions) - 1:
            raise StaleQuestion("that question is no longer waiting for an answer")
        received = _received(text)
        if received is None and not expired:
            raise ValueError("an empty answer is not submitted")
        taken = max(0, round((now - datetime.fromisoformat(pending["issued"])).total_seconds() * 1000))
        value = int(received) if received is not None and _DIGITS.fullmatch(received) else None
        if taken > pending["allowed_ms"] + NETWORK_ALLOWANCE_MS:
            outcome = TIMEOUT
        elif value == pending["expected"]:
            outcome = CORRECT
        elif expired or received is None:
            outcome = TIMEOUT
        else:
            outcome = INCORRECT
        pending.update(answer=received, outcome=outcome, taken_ms=taken)
        self._touch(now)
        settings = self.settings
        correct = self.correct
        return Judged(outcome, dict(pending), correct, settings.required, correct >= settings.required)

    def _resume(self, now: datetime) -> None:
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
        self._close_pending()
        runs[-1]["expired"] = _stamp(idle_since + EXPIRY)
        self._start_run(now)

    def _start_run(self, now: datetime) -> None:
        parse_settings(self.body)
        runs = self.detail["runs"]
        runs.append({"run": len(runs) + 1, "started": _stamp(now)})
        self.detail["settings"] = dict(self.body)
        self.detail["last_activity"] = _stamp(now)

    def _valid_settings(self) -> bool:
        try:
            parse_settings(self.detail.get("settings"))
        except ValueError:
            return False
        return True

    def _close_pending(self) -> None:
        pending = self.pending
        if pending is not None:
            pending.update(answer=None, outcome=TIMEOUT, taken_ms=pending["allowed_ms"])

    def _touch(self, now: datetime) -> None:
        self.detail["last_activity"] = _stamp(now)


def _timeout(value: object, field: str) -> int:
    if not isinstance(value, str):
        raise ValueError(f"{field}: must be a duration such as 10s or 7500ms, not a bare number")
    match = _TIMEOUT.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"{field}: must be a duration such as 10s or 7500ms")
    milliseconds = int(match.group(1)) * _TIMEOUT_SCALE[match.group(2)]
    if milliseconds <= 0:
        raise ValueError(f"{field}: must be longer than zero")
    return milliseconds


def _weighted(value: object, field: str) -> WeightedList:
    if not isinstance(value, list):
        raise ValueError(f"{field}: must be a list of entries")
    if not value:
        raise ValueError(f"{field}: must have at least one entry")
    entries = [_entry(item, f"{field} entry {number}") for number, item in enumerate(value, start=1)]
    ordered = sorted(enumerate(entries, start=1), key=lambda pair: pair[1].low)
    for (left_number, left), (right_number, right) in zip(ordered, ordered[1:]):
        if right.low <= left.high:
            raise ValueError(
                f"{field}: entries {min(left_number, right_number)} and {max(left_number, right_number)} "
                "both include the value "
                f"{right.low}"
            )
    return WeightedList(tuple(entry for _number, entry in ordered))


def _entry(item: object, where: str) -> Entry:
    if not isinstance(item, Mapping):
        raise ValueError(f"{where}: must be a mapping with weight and value, or weight, from, and to")
    unknown = sorted(set(item) - _ENTRY_KEYS)
    if unknown:
        raise ValueError(f"{where}: unknown setting {unknown[0]}")
    if "weight" not in item:
        raise ValueError(f"{where}: weight is required")
    weight = item["weight"]
    if not _is_whole(weight) or weight < 1:
        raise ValueError(f"{where}: weight must be a whole number, 1 or more")
    has_value = "value" in item
    has_from = "from" in item
    has_to = "to" in item
    if has_value and (has_from or has_to):
        raise ValueError(f"{where}: give value, or from and to, not both")
    if has_value:
        value = _operand(item["value"], f"{where}: value")
        return Entry(value, value, weight)
    if not has_from and not has_to:
        raise ValueError(f"{where}: value, or from and to, is required")
    if not (has_from and has_to):
        raise ValueError(f"{where}: a range needs both from and to")
    low = _operand(item["from"], f"{where}: from")
    high = _operand(item["to"], f"{where}: to")
    if low > high:
        raise ValueError(f"{where}: from must be no larger than to")
    return Entry(low, high, weight)


def _operand(value: object, where: str) -> int:
    if not _is_whole(value) or value < 0:
        raise ValueError(f"{where} must be a whole number, 0 or more")
    return value


def _is_whole(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _received(text: object) -> str | None:
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)
    text = text.strip()[:LONGEST_ANSWER]
    return text or None


def _stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds")


def _copy(value):
    if isinstance(value, Mapping):
        return {key: _copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy(item) for item in value]
    return value
