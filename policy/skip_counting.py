"""Skip counting quiz: configuration, sequence draws, tries, and points.

A task of type ``skip_counting`` keeps its fields in ``body``. Every field
is optional. They are checked when the policy is loaded, so a difference
that leaves too few sequences fails the load and the previous policy stays
in force.

A question is an arithmetic progression of ``sequence_length`` whole
numbers between ``minimum_value`` and ``maximum_value``. ``completed`` of
them are filled in and the rest are blank boxes. He has three tries, worth
1, 0.5, and 0.25 points. The server times the whole question from when it
issued it, counts the tries, and judges every box. Runs, expiry, and resume
are ``policy.quiz``'s.
"""

from __future__ import annotations

import random
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations

from policy.problems import Collector
from policy.quiz import (
    CORRECT,
    INCORRECT,
    NETWORK_ALLOWANCE_MS,
    TIMEOUT,
    Entry,
    QuizRecord,
    StaleQuestion,
    WeightedList,
    duration,
    is_whole,
    stamp,
    weighted,
)
from policy.tasks import FAILURE, PASS

SKIP_COUNTING = "skip_counting"
LABEL = "Skip counting"
WRONG = "wrong"
TRIES = 3
POINTS = (1, 0.5, 0.25)
RECENT_DIFFERENCES = 2
RECENT_STARTS = 2
MINIMUM_SEQUENCES = 3
LONGEST_ENTRY = 24

_BODY_KEYS = {
    "sequence_length",
    "completed",
    "consecutive",
    "multiples_only",
    "difference",
    "minimum_value",
    "maximum_value",
    "timeout",
    "correct_answers_required",
    "minimum_questions",
    "maximum_questions",
}
_ENTRY_KEYS = frozenset({"minimum_value", "maximum_value", "multiples_only"})
_DEFAULT_CAPS = {2: 99, 5: 199, 10: 499, 25: None, 100: None}
_DEFAULT_MULTIPLES = frozenset({25})
_DEFAULT_DIFFERENCES = (*_DEFAULT_CAPS, *(-value for value in _DEFAULT_CAPS))
_DEFAULT_REQUIRED = 8
_NUMBER = re.compile(r"^-?[0-9]+$")


@dataclass(frozen=True)
class Bounds:
    """The numbers allowed for the differences from ``low`` to ``high``, and whether they start on a multiple."""

    low: int
    high: int
    minimum: int
    maximum: int
    multiples_only: bool = False


@dataclass(frozen=True)
class Settings:
    """One run's skip counting settings. The timeout is milliseconds.

    ``minimum``, ``maximum``, and ``multiples_only`` are the body's.
    ``bounds`` holds the range and ``multiples_only`` each difference entry
    uses, which are the body's unless the entry sets its own.
    """

    length: int
    completed: int
    consecutive: bool
    multiples_only: bool
    differences: WeightedList
    minimum: int
    maximum: int
    timeout: int
    required: int
    minimum_questions: int
    maximum_questions: int | None
    bounds: tuple[Bounds, ...] = ()

    @property
    def width(self) -> int:
        """Return the characters in the longest number any box can hold."""
        return max(len(str(value)) for bound in self.bounds for value in (bound.minimum, bound.maximum))

    @property
    def negative(self) -> bool:
        return any(bound.minimum < 0 for bound in self.bounds)

    def bounds_for(self, difference: int) -> Bounds:
        """Return the range and ``multiples_only`` used when counting by ``difference``."""
        for bound in self.bounds:
            if bound.low <= difference <= bound.high:
                return bound
        return Bounds(difference, difference, self.minimum, self.maximum, self.multiples_only)

    def range_for(self, difference: int) -> tuple[int, int]:
        """Return the lowest and highest number allowed when counting by ``difference``."""
        bound = self.bounds_for(difference)
        return bound.minimum, bound.maximum

    def starts(self, difference: int) -> range:
        """Return every start that keeps a sequence with this difference in range."""
        bound = self.bounds_for(difference)
        return starts(difference, self.length, bound.minimum, bound.maximum, bound.multiples_only)


def starts(difference: int, length: int, minimum: int, maximum: int, multiples_only: bool) -> range:
    """Return the starts of every sequence of ``length`` numbers counting by ``difference``.

    Every number is between ``minimum`` and ``maximum``. With
    ``multiples_only``, the start is a multiple of the difference's size, so
    every number is one too.
    """
    span = abs(difference) * (length - 1)
    low, high = (minimum, maximum - span) if difference > 0 else (minimum + span, maximum)
    if not multiples_only:
        return range(low, high + 1)
    size = abs(difference)
    return range(-(-low // size) * size, high + 1, size)


def parse_settings(body: Mapping) -> Settings:
    """Check a skip counting task body and return its settings.

    Each field is checked, and every problem is raised together as
    ``Problems``, a ``ValueError``. Each message starts with the field. The
    checks that compare fields, and the difference list, run once the fields
    they read are good.
    """
    if not isinstance(body, Mapping):
        raise ValueError("body must be a mapping")
    fields = Collector()
    for key in sorted(set(body) - _BODY_KEYS):
        fields.add(f"{key}: unknown setting")
    length = fields.take(_whole, body.get("sequence_length", 8), "sequence_length", 4, 12)
    if length is not None:
        fields.take(_whole, body.get("completed", 3), "completed", 2, length - 1)
    fields.take(_flag, body.get("consecutive", True), "consecutive")
    fields.take(_flag, body.get("multiples_only", False), "multiples_only")
    minimum = fields.take(_whole, body.get("minimum_value", 1), "minimum_value")
    maximum = fields.take(_whole, body.get("maximum_value", 999), "maximum_value")
    if minimum is not None and maximum is not None and maximum <= minimum:
        fields.add("maximum_value: must be greater than minimum_value")
    fields.take(duration, body.get("timeout", "3m"), "timeout")
    for field in ("maximum_questions", "minimum_questions", "correct_answers_required"):
        fields.take(_count, body, field)
    fields.finish()
    return _settings(body)


def _settings(body: Mapping) -> Settings:
    """Check what ties the fields together, once each field on its own is good."""
    length = _whole(body.get("sequence_length", 8), "sequence_length", 4, 12)
    completed = _whole(body.get("completed", 3), "completed", 2, length - 1)
    consecutive = _flag(body.get("consecutive", True), "consecutive")
    multiples_only = _flag(body.get("multiples_only", False), "multiples_only")
    minimum = _whole(body.get("minimum_value", 1), "minimum_value")
    maximum = _whole(body.get("maximum_value", 999), "maximum_value")
    timeout = duration(body.get("timeout", "3m"), "timeout")
    most = _count(body, "maximum_questions")
    least = _count(body, "minimum_questions")
    required = _count(body, "correct_answers_required")
    if required is None:
        required = _DEFAULT_REQUIRED if least is None else max(_DEFAULT_REQUIRED, -(-4 * least // 5))
        if most is not None:
            required = min(required, most)
    if least is None:
        least = required
    if most is not None:
        if required > most:
            raise ValueError("correct_answers_required: must be no more than maximum_questions, or he could never pass")
        if least > most:
            raise ValueError("minimum_questions: must be no more than maximum_questions")

    bounds: list[Bounds] = []

    def enough(entry: Entry, where: str, item: Mapping) -> None:
        if entry.low <= 0 <= entry.high:
            raise ValueError(
                f"{where}: 0 is not a difference, because every number would be the same; "
                "write one range below zero and another above it"
            )
        low = _whole(item.get("minimum_value", minimum), f"{where}: minimum_value")
        high = _whole(item.get("maximum_value", maximum), f"{where}: maximum_value")
        if high <= low:
            hint = (
                ""
                if "difference" in body
                else f"; the default list counts by {entry.low} only up to {high}, so write a difference list"
            )
            raise ValueError(f"{where}: maximum_value {high} must be greater than minimum_value {low}{hint}")
        multiples = _flag(item.get("multiples_only", multiples_only), f"{where}: multiples_only")
        for difference in _to_check(entry, length, low, high, multiples):
            found = len(starts(difference, length, low, high, multiples))
            if found < MINIMUM_SEQUENCES:
                starting = ", starting on a multiple of it," if multiples else ""
                raise ValueError(
                    f"{where}: counting by {difference}{starting} allows only {found} "
                    f"sequence{'' if found == 1 else 's'} of {length} numbers between {low} and {high}; "
                    f"each difference needs at least {MINIMUM_SEQUENCES}"
                )
        bounds.append(Bounds(entry.low, entry.high, low, high, multiples))

    if "difference" in body:
        differences = weighted(body["difference"], "difference", _difference, enough, _ENTRY_KEYS)
    else:
        differences = weighted(_default_differences(maximum), "difference", _difference, enough, _ENTRY_KEYS)
    needed, field = (most, "maximum_questions") if most is not None else _larger(required, least, body)
    total = _sequences_up_to(bounds, needed, length)
    if total < needed:
        raise ValueError(
            f"{field}: the differences allow only {total} distinct sequences, and {needed} are needed"
        )
    return Settings(
        length,
        completed,
        consecutive,
        multiples_only,
        differences,
        minimum,
        maximum,
        timeout,
        required,
        least,
        most,
        tuple(sorted(bounds, key=lambda bound: bound.low)),
    )


def _default_differences(maximum: int) -> list[dict]:
    """Return the default difference list.

    Each is capped at its default maximum or the body's, whichever is lower.
    25 and -25 always start on a multiple of 25.
    """
    written = []
    for value in _DEFAULT_DIFFERENCES:
        entry: dict = {"value": value, "weight": 1}
        cap = _DEFAULT_CAPS[abs(value)]
        if cap is not None:
            entry["maximum_value"] = min(cap, maximum)
        if abs(value) in _DEFAULT_MULTIPLES:
            entry["multiples_only"] = True
        written.append(entry)
    return written


def draw_difference(settings: Settings, recent: Sequence[int], rng: random.Random) -> int:
    """Draw a difference, leaving out the last two used.

    ``recent`` is the differences of earlier questions, oldest first. The
    others keep their relative weights. With fewer than three differences,
    only as many are left out as still leaves one, so two alternate.
    """
    differences = settings.differences
    for keep in range(min(RECENT_DIFFERENCES, len(recent)), -1, -1):
        excluded = set(recent[len(recent) - keep :]) if keep else set()
        less = {value: differences.weight(value) for value in excluded if differences.weight(value)}
        total = differences.total - sum(less.values())
        if total > 0:
            return differences.pick(rng.randrange(total), less=less)
    raise ValueError("the difference list has no weight")


def draw_start(settings: Settings, difference: int, recent: Sequence[int], rng: random.Random) -> int:
    """Draw a start evenly from every start allowed, leaving out ``recent``."""
    allowed = settings.starts(difference)
    skipped = sorted({allowed.index(start) for start in recent if start in allowed})
    if len(skipped) >= len(allowed):
        skipped = []
    position = rng.randrange(len(allowed) - len(skipped))
    for index in skipped:
        if index <= position:
            position += 1
    return allowed[position]


def draw_filled(settings: Settings, rng: random.Random) -> tuple[int, ...]:
    """Draw the filled-in positions. Every set that meets the ``consecutive`` rule is equally likely."""
    choices = [
        chosen
        for chosen in combinations(range(settings.length), settings.completed)
        if not settings.consecutive or _adjacent(chosen)
    ]
    return rng.choice(choices)


@dataclass(frozen=True)
class Judged:
    """What the server decided about one try.

    ``outcome`` is ``wrong`` while the question is still waiting for another
    try. ``right`` is the blank positions he got right, given after a wrong
    second try. ``verdict`` is ``pass`` or ``failure`` when this try ends the
    attempt.
    """

    outcome: str
    attempt: int
    wrong: int
    right: tuple[int, ...] | None
    question: Mapping
    verdict: str | None


class Session(QuizRecord):
    """The skip counting record on one attempt."""

    def parse(self, body: object) -> Settings:
        return parse_settings(body)

    def time_out(self, question: dict) -> None:
        question.update(outcome=TIMEOUT, correct_try=None, points=0)

    def finished(self) -> list[dict]:
        """Return the finished questions of the current run."""
        return [item for item in self.in_run() if item.get("outcome") is not None]

    @property
    def points(self) -> float:
        return sum(item.get("points") or 0 for item in self.finished())

    @property
    def number(self) -> int:
        """Return how many questions of the current run are finished."""
        return len(self.finished())

    def verdict(self) -> str | None:
        """Return ``pass`` or ``failure`` once the current run has decided the attempt."""
        settings = self.settings
        done = self.number
        points = self.points
        if points >= settings.required and done >= settings.minimum_questions:
            return PASS
        most = settings.maximum_questions
        if most is not None:
            if done >= most:
                return FAILURE
            if done >= settings.minimum_questions and points + (most - done) < settings.required:
                return FAILURE
        return None

    def issue(self, now: datetime, rng: random.Random) -> dict:
        """Issue the next question and start its time now."""
        self.resume(now)
        self.close_pending()
        settings = self.settings
        last = [item["difference"] for item in self.questions[-RECENT_DIFFERENCES:]]
        difference = draw_difference(settings, last, rng)
        start = draw_start(settings, difference, self._recent_starts(difference), rng)
        question = {
            "run": self.run,
            "difference": difference,
            "start": start,
            "sequence": [start + difference * position for position in range(settings.length)],
            "filled": list(draw_filled(settings, rng)),
            "tries": [],
            "outcome": None,
            "correct_try": None,
            "points": None,
            "allowed_ms": settings.timeout,
            "issued": stamp(now),
        }
        self.questions.append(question)
        self.touch(now)
        return question

    def _recent_starts(self, difference: int) -> list[int]:
        found: list[int] = []
        for item in reversed(self.questions):
            if len(found) == RECENT_STARTS:
                break
            if item["difference"] == difference:
                found.append(item["start"])
        return found

    def answer(self, now: datetime, number: object, entries: object, *, expired: bool) -> Judged:
        """Judge a try the server received now.

        ``entries`` is what is in each blank box, left to right. ``expired``
        means the browser's timer ran out and it sent whatever was in the
        boxes. Then every box right is correct on the try he was on, and
        anything else is a timeout. A try that arrives after the time allowed
        plus the network allowance is a timeout whatever it says, and it is
        still recorded. A try with a blank box that is not from the timer is
        refused and does not use a try.
        """
        self.resume(now)
        pending = self.pending
        if pending is None or number != len(self.questions) - 1:
            raise StaleQuestion("that question is no longer waiting for an answer")
        blanks = blank_positions(pending)
        if not isinstance(entries, list) or len(entries) != len(blanks):
            raise ValueError(f"an answer has {len(blanks)} entries, one for each blank box")
        texts = [_received(item) for item in entries]
        taken = self.taken_ms(pending, now)
        late = taken > pending["allowed_ms"] + NETWORK_ALLOWANCE_MS
        if not late and not expired and None in texts:
            raise ValueError("every blank box needs a number before the answer is sent")
        right = tuple(
            position for position, text in zip(blanks, texts) if _value(text) == pending["sequence"][position]
        )
        wrong = len(blanks) - len(right)
        attempt = len(pending["tries"]) + 1
        pending["tries"].append({"entries": texts, "wrong": wrong, "expired": expired, "received_ms": taken})
        if late:
            outcome = TIMEOUT
        elif wrong == 0:
            outcome = CORRECT
        elif expired:
            outcome = TIMEOUT
        elif attempt >= TRIES:
            outcome = INCORRECT
        else:
            outcome = WRONG
        if outcome != WRONG:
            pending.update(
                outcome=outcome,
                correct_try=attempt if outcome == CORRECT else None,
                points=POINTS[attempt - 1] if outcome == CORRECT else 0,
            )
        self.touch(now)
        verdict = None if outcome == WRONG else self.verdict()
        shown = right if outcome == WRONG and attempt == TRIES - 1 else None
        return Judged(outcome, attempt, wrong, shown, dict(pending), verdict)


def blank_positions(question: Mapping) -> list[int]:
    filled = set(question["filled"])
    return [position for position in range(len(question["sequence"])) if position not in filled]


def format_points(points: float) -> str:
    """Return points as the page shows them: 5, 5.25, 5.5, or 5.75."""
    return f"{points:g}"


def _adjacent(chosen: Sequence[int]) -> bool:
    return any(right - left == 1 for left, right in zip(chosen, chosen[1:]))


def _to_check(entry: Entry, length: int, minimum: int, maximum: int, multiples_only: bool):
    """Yield the entry's differences that might allow too few sequences, largest size first.

    Without ``multiples_only`` a larger difference never allows more
    sequences, so the largest is the only one to check. With it the count is
    uneven, but any size up to ``(maximum - minimum + 1) // (length + 2)``
    always leaves at least three, so the walk stops there.
    """
    largest = entry.high if entry.high > 0 else entry.low
    step = -1 if largest > 0 else 1
    if not multiples_only:
        yield largest
        return
    safe = (maximum - minimum + 1) // (length + 2)
    for difference in range(largest, entry.low - 1 if step < 0 else entry.high + 1, step):
        if abs(difference) <= safe:
            return
        yield difference


def _sequences_up_to(bounds: Sequence[Bounds], needed: int, length: int) -> int:
    """Count distinct sequences, stopping once there are ``needed``."""
    total = 0
    for bound in bounds:
        for difference in range(bound.low, bound.high + 1):
            total += len(starts(difference, length, bound.minimum, bound.maximum, bound.multiples_only))
            if total >= needed:
                return total
    return total


def _larger(required: int, least: int, body: Mapping) -> tuple[int, str]:
    if least > required or (least == required and "minimum_questions" in body):
        return least, "minimum_questions"
    return required, "correct_answers_required"


def _whole(value: object, field: str, low: int | None = None, high: int | None = None) -> int:
    if not is_whole(value):
        raise ValueError(f"{field}: must be a whole number")
    if low is not None and high is not None and not low <= value <= high:
        raise ValueError(f"{field}: must be a whole number from {low} to {high}")
    return value


def _count(body: Mapping, field: str) -> int | None:
    if field not in body:
        return None
    value = body[field]
    if not is_whole(value) or value < 1:
        raise ValueError(f"{field}: must be a whole number, 1 or more")
    return value


def _flag(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field}: must be true or false")
    return value


def _difference(value: object, where: str) -> int:
    if not is_whole(value):
        raise ValueError(f"{where} must be a whole number")
    return value


def _received(item: object) -> str | None:
    if item is None:
        return None
    text = (item if isinstance(item, str) else str(item)).strip()[:LONGEST_ENTRY]
    return None if text in ("", "-") else text


def _value(text: str | None) -> int | None:
    return int(text) if text is not None and _NUMBER.fullmatch(text) else None
