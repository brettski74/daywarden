"""Arithmetic quiz: configuration, question draws, and the session record.

A task of type ``arithmetic`` keeps its quiz fields in ``body``. They are
checked when the policy is loaded, so a bad operand list fails the load and
the previous policy stays in force.

The session lives on the attempt's ``detail``. The server issues each
question, records when it did, and judges every answer against that moment.
The browser draws the timer, but it does not decide whether an answer was
in time. Runs, expiry, and resume are ``policy.quiz``'s.

``first`` and ``operands`` set which facts can be asked, the task's
**domain**. Which fact is asked is weighted from his record of every other
attempt, by ``policy.fact_figures``. A weight written in the lists is ignored.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from policy.fact_figures import ARITHMETIC, NO_FIGURES, UNIT_CAP, Book
from policy.problems import Collector
from policy.quiz import (
    CORRECT,
    EXPIRY,
    INCORRECT,
    NETWORK_ALLOWANCE_MS,
    OUTCOMES,
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

__all__ = [
    "ARITHMETIC",
    "CORRECT",
    "EXPIRY",
    "INCORRECT",
    "NETWORK_ALLOWANCE_MS",
    "OUTCOMES",
    "TIMEOUT",
    "Entry",
    "Judged",
    "OPERATIONS",
    "Operation",
    "Session",
    "Settings",
    "StaleQuestion",
    "WeightedList",
    "draw",
    "parse_settings",
]

RECENT_QUESTIONS = 3
LONGEST_ANSWER = 20

_BODY_KEYS = {"operation", "max_timeout", "min_timeout", "correct_answers_required", "operands", "first"}
_REQUIRED_KEYS = ("operation", "max_timeout", "min_timeout", "correct_answers_required", "operands")
_DIGITS = re.compile(r"^[0-9]+$")


@dataclass(frozen=True)
class Operation:
    """How one operation shows a question and what it expects."""

    name: str
    label: str
    text: Callable[[int, int], str]
    answer: Callable[[int, int], int]


# Subtraction and division ask the question whose answer is n, so the draws and weights work on m and n as for
# addition and multiplication. The signs are the ones on paper: − (U+2212), × (U+00D7), and ÷ (U+00F7).
OPERATIONS: dict[str, Operation] = {
    "addition": Operation("addition", "Addition", lambda m, n: f"{m} + {n} =", lambda m, n: m + n),
    "subtraction": Operation("subtraction", "Subtraction", lambda m, n: f"{m + n} \u2212 {m} =", lambda m, n: n),
    "multiplication": Operation("multiplication", "Multiplication", lambda m, n: f"{m} \u00d7 {n} =", lambda m, n: m * n),
    "division": Operation("division", "Division", lambda m, n: f"{m * n} \u00f7 {m} =", lambda m, n: n),
}
DIVISION = "division"


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

    Each field is checked, and every problem is raised together as
    ``Problems``, a ``ValueError``. Each message starts with the field.
    """
    if not isinstance(body, Mapping):
        raise ValueError("body must be a mapping")
    fields = Collector()
    for key in sorted(set(body) - _BODY_KEYS):
        fields.add(f"{key}: unknown setting")
    for key in _REQUIRED_KEYS:
        if key not in body:
            fields.add(f"{key}: is required")
    name = body.get("operation")
    if "operation" in body and (not isinstance(name, str) or name not in OPERATIONS):
        known = ", ".join(sorted(OPERATIONS))
        fields.add(f"operation: {name!r} is not an operation this service has; use {known}")
    longest = fields.take(duration, body["max_timeout"], "max_timeout") if "max_timeout" in body else None
    shortest = fields.take(duration, body["min_timeout"], "min_timeout") if "min_timeout" in body else None
    if longest is not None and shortest is not None and shortest > longest:
        fields.add("min_timeout: must be no longer than max_timeout")
    required = body.get("correct_answers_required")
    if "correct_answers_required" in body and (not is_whole(required) or required < 1):
        fields.add("correct_answers_required: must be a whole number, 1 or more")
    first = fields.take(_numbers, body["first"], "first") if "first" in body else None
    operands = fields.take(_numbers, body["operands"], "operands") if "operands" in body else None
    if name == DIVISION:
        lefts, field = (first, "first") if "first" in body else (operands, "operands")
        if lefts is not None and lefts.has(0):
            fields.add(f"{field}: division cannot divide by 0, so 0 cannot be in the list the first number is drawn from")
    fields.finish()
    return Settings(OPERATIONS[name], longest, shortest, required, operands, first)


def draw(
    settings: Settings,
    recent: Sequence[tuple[int, int]],
    rng: random.Random,
    figures: Book = NO_FIGURES,
) -> tuple[int, int]:
    """Draw ``(m, n)`` from the domain by its figures, leaving out the last three questions when it can.

    A fact's chance is in proportion to ``base + unit × boost``, where
    ``unit`` is the domain's average base over at most ``UNIT_CAP`` facts.
    A fact never asked weighs 1, so the domain is never listed. ``recent``
    is oldest first. The remaining facts keep their relative weights. When
    every fact is recent, the oldest recent one is let back first, and the
    question just asked is the last.
    """
    lefts, rights = settings.lefts, settings.operands
    size = lefts.count * rights.count
    if size == 0:
        raise ValueError("an operand list is empty")
    asked = {fact: found for fact, found in figures.facts.items() if lefts.has(fact[0]) and rights.has(fact[1])}
    unit = (size - len(asked) + sum(found.base for found in asked.values())) / min(size, UNIT_CAP)
    chances = {fact: found.base + unit * figures.boost(found) for fact, found in sorted(asked.items())}
    for keep in range(min(RECENT_QUESTIONS, len(recent)), -1, -1):
        excluded = frozenset(recent[len(recent) - keep :]) if keep else frozenset()
        pair = _draw_without(lefts, rights, chances, excluded, rng)
        if pair is not None:
            return pair
    raise ValueError("an operand list is empty")


def _draw_without(
    lefts: WeightedList,
    rights: WeightedList,
    chances: Mapping[tuple[int, int], float],
    excluded: frozenset[tuple[int, int]],
    rng: random.Random,
) -> tuple[int, int] | None:
    """Draw a fact that is not excluded: one with figures by its chance, or else one never asked, each weighing 1."""
    left_out = {fact for fact in excluded if lefts.has(fact[0]) and rights.has(fact[1])}
    known = [(fact, chance) for fact, chance in chances.items() if fact not in left_out]
    held = set(chances) | left_out
    unknown = lefts.count * rights.count - len(held)
    known_total = sum(chance for _fact, chance in known)
    if not known and unknown == 0:
        return None
    point = rng.random() * (known_total + unknown)
    if point < known_total or unknown == 0:
        for fact, chance in known:
            point -= chance
            if point < 0:
                return fact
        return known[-1][0]
    return _never_asked(lefts, rights, held, unknown, rng)


def _never_asked(
    lefts: WeightedList,
    rights: WeightedList,
    held: set[tuple[int, int]],
    unknown: int,
    rng: random.Random,
) -> tuple[int, int]:
    """Draw evenly from the domain's facts that are not ``held``, walking its ranges rather than listing them."""
    held_by_left: dict[int, int] = {}
    for m, _n in held:
        held_by_left[m] = held_by_left.get(m, 0) + 1
    m = lefts.pick(rng.randrange(unknown), scale=rights.count, less=held_by_left)
    skip = {n: 1 for left, n in held if left == m}
    n = rights.pick(rng.randrange(rights.count - len(skip)), less=skip)
    return m, n


@dataclass(frozen=True)
class Judged:
    """What the server decided about one answer."""

    outcome: str
    question: Mapping
    correct: int
    required: int
    finished: bool


class Session(QuizRecord):
    """The arithmetic record on one attempt."""

    def parse(self, body: object) -> Settings:
        return parse_settings(body)

    def time_out(self, question: dict) -> None:
        question.update(answer=None, outcome=TIMEOUT, taken_ms=question["allowed_ms"])

    @property
    def correct(self) -> int:
        return sum(1 for item in self.questions if item.get("run") == self.run and item.get("outcome") == CORRECT)

    def issue(self, now: datetime, rng: random.Random, figures: Callable[[str], Book] | None = None) -> dict:
        """Issue the next question and start its time now.

        ``figures`` returns the figures to draw with for an operation, which
        leave out this attempt's own answers. Without it every fact is drawn
        as never asked.
        """
        self.resume(now)
        self.close_pending()
        settings = self.settings
        recent = [
            (item["m"], item["n"])
            for item in self.questions[-RECENT_QUESTIONS:]
            if item.get("question") == settings.operation.text(item["m"], item["n"])
        ]
        found = NO_FIGURES if figures is None else figures(settings.operation.name)
        m, n = draw(settings, recent, rng, found)
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
            "issued": stamp(now),
        }
        self.questions.append(question)
        self.touch(now)
        return question

    def answer(self, now: datetime, number: object, text: object, *, expired: bool) -> Judged:
        """Judge an answer the server received now.

        ``expired`` means the browser's timer ran out and it sent whatever
        was in the box. Then a right answer in time is correct and anything
        else is a timeout. An answer that arrives after the time allowed plus
        the network allowance is a timeout whatever it says, and it is still
        recorded.
        """
        self.resume(now)
        pending = self.pending
        if pending is None or number != len(self.questions) - 1:
            raise StaleQuestion("that question is no longer waiting for an answer")
        received = _received(text)
        if received is None and not expired:
            raise ValueError("an empty answer is not submitted")
        taken = self.taken_ms(pending, now)
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
        self.touch(now)
        settings = self.settings
        correct = self.correct
        return Judged(outcome, dict(pending), correct, settings.required, correct >= settings.required)


def _numbers(value: object, field: str) -> WeightedList:
    """Return a ``first`` or ``operands`` list. An entry may leave out ``weight``, and a weight given is ignored."""
    return weighted(value, field, _operand, weights=False)


def _operand(value: object, where: str) -> int:
    if not is_whole(value) or value < 0:
        raise ValueError(f"{where} must be a whole number, 0 or more")
    return value


def _received(text: object) -> str | None:
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)
    text = text.strip()[:LONGEST_ANSWER]
    return text or None
