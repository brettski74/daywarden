"""Arithmetic fact figures: each fact's all-time record, and the weights that choose questions (S037).

A fact is a question as it is asked, ``(operation, m, n)``, so ``6 × 7`` and
``7 × 6`` are two facts. Its operation is read from the sign in the
question's stored text, as the facts page does.

The household database keeps one ledger row for each question that has an
outcome, whatever the attempt's task: its client group, operation, ``m`` and
``n``, outcome, and time taken. A row is identified by its attempt and its
place in the attempt's questions, so recording an attempt again adds nothing,
and a row is not removed when its attempt is, so ``rm-attempts`` leaves the
figures alone. The figures are worked out from the rows in the order they
were recorded.

The weights are fixed here, not in the policy file.
"""

from __future__ import annotations

import json
import math
import sqlite3
import statistics
from collections.abc import Mapping
from dataclasses import dataclass, field

from policy.quiz import CORRECT, OUTCOMES

ARITHMETIC = "arithmetic"
# The sign each operation writes between its numbers, as ``policy.arithmetic.OPERATIONS`` shows them.
SIGNS = {"addition": "+", "subtraction": "−", "multiplication": "×", "division": "÷"}
_BY_SIGN = {sign: name for name, sign in SIGNS.items()}

# A fact right on this many of its last answers, or on all of them when it has fewer, has no miss boost.
SETTLED_RUN = 5
MISS_BOOST = 4.0
# Each right answer moves the smoothed time this far towards it, on a ratio scale.
ALPHA = 1 - math.exp(-1 / 3)
# A fact is timed once it has this many right answers, and the median counts once this many facts are timed.
TIMED_ANSWERS = 3
TIMED_FACTS = 10
# The slow boost starts at the larger of SLOW_RATIO × M and M + SLOW_MARGIN_MS, and is full SLOW_SPAN × M later.
SLOW_RATIO = 1.5
SLOW_MARGIN_MS = 2000
SLOW_SPAN = 2
SLOW_BOOST = 4.0
# The boosts are scaled to the average base of this many facts at most.
UNIT_CAP = 20

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS arithmetic_fact_questions (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        client_group TEXT NOT NULL,
        operation TEXT NOT NULL,
        m INTEGER NOT NULL,
        n INTEGER NOT NULL,
        attempt_id INTEGER NOT NULL,
        started_at TEXT NOT NULL,
        position INTEGER NOT NULL,
        outcome TEXT NOT NULL,
        taken_ms INTEGER,
        UNIQUE (attempt_id, started_at, position)
    )
    """,
    "CREATE INDEX IF NOT EXISTS arithmetic_fact_questions_by_operation "
    "ON arithmetic_fact_questions (client_group, operation, seq)",
    "CREATE TABLE IF NOT EXISTS arithmetic_fact_meta (name TEXT PRIMARY KEY)",
)
_REBUILT = "rebuilt"


def operation_of(question: Mapping, settings: Mapping | None = None) -> str | None:
    """Return the operation a stored question asked, from the sign in its text, or else the stored settings."""
    text = question.get("question")
    if isinstance(text, str):
        for part in text.split():
            if part in _BY_SIGN:
                return _BY_SIGN[part]
    named = settings.get("operation") if isinstance(settings, Mapping) else None
    return named if named in SIGNS else None


def seconds(ms: float) -> str:
    """A time as the facts page writes it, such as ``2.0 s``."""
    return f"{ms / 1000:.1f} s"


@dataclass(frozen=True)
class Figures:
    """One fact's all-time figures for one client group.

    ``run`` is the right answers in a row, counting back from the latest.
    ``smoothed_ms`` is built from right answers only, and ``timed`` is how
    many right answers it was built from.
    """

    asked: int = 0
    right: int = 0
    run: int = 0
    smoothed_ms: float | None = None
    timed: int = 0

    @property
    def base(self) -> float:
        return 1 / (self.asked + 1)

    @property
    def miss_boost(self) -> float:
        if self.run >= min(SETTLED_RUN, self.asked):
            return 0.0
        return MISS_BOOST * 0.5**self.run


NEVER_ASKED = Figures()


@dataclass(frozen=True)
class Slow:
    """Where one operation's slow boost starts and is full, from the median smoothed time of its timed facts.

    ``timed_facts`` is how many facts have at least ``TIMED_ANSWERS`` right
    answers. ``median_ms`` is None until there are ``TIMED_FACTS`` of them,
    and then no fact has a slow boost.
    """

    timed_facts: int = 0
    median_ms: float | None = None

    @property
    def start_ms(self) -> float | None:
        if self.median_ms is None:
            return None
        return max(SLOW_RATIO * self.median_ms, self.median_ms + SLOW_MARGIN_MS)

    @property
    def full_ms(self) -> float | None:
        start = self.start_ms
        return None if start is None or self.median_ms is None else start + SLOW_SPAN * self.median_ms

    def boost(self, figures: Figures) -> float:
        start, median = self.start_ms, self.median_ms
        if start is None or median is None or figures.timed < TIMED_ANSWERS or figures.smoothed_ms is None:
            return 0.0
        if figures.smoothed_ms <= start:
            return 0.0
        return min(SLOW_BOOST, SLOW_BOOST * (figures.smoothed_ms - start) / (SLOW_SPAN * median))

    @property
    def text(self) -> str:
        if self.median_ms is None:
            have = "has" if self.timed_facts == 1 else "have"
            return (
                f"Slow boost starts once {TIMED_FACTS} facts each have {TIMED_ANSWERS} right answers. "
                f"{self.timed_facts} {have} so far."
            )
        return f"Median {seconds(self.median_ms)}. Slow from {seconds(self.start_ms)}, full at {seconds(self.full_ms)}."

    def as_json(self) -> dict:
        def whole(value: float | None) -> int | None:
            return None if value is None else round(value)

        return {
            "median_ms": whole(self.median_ms),
            "start_ms": whole(self.start_ms),
            "full_ms": whole(self.full_ms),
            "timed_facts": self.timed_facts,
            "facts_needed": TIMED_FACTS,
            "answers_needed": TIMED_ANSWERS,
            "text": self.text,
        }


@dataclass(frozen=True)
class Book:
    """One client group's figures for one operation: each fact asked, and where the slow boost starts."""

    facts: Mapping[tuple[int, int], Figures] = field(default_factory=dict)
    slow: Slow = Slow()

    def figures(self, m: int, n: int) -> Figures:
        return self.facts.get((m, n), NEVER_ASKED)

    def boost(self, figures: Figures) -> float:
        """Return a fact's miss boost and slow boost together."""
        return figures.miss_boost + self.slow.boost(figures)

    def weight(self, figures: Figures) -> float:
        return figures.base + self.boost(figures)

    def all_time(self, m: int, n: int) -> dict:
        """Return a fact's all-time figures and weight, as the facts page shows them."""
        found = self.figures(m, n)
        return {
            "asked": found.asked,
            "run": found.run,
            "smoothed_ms": None if found.smoothed_ms is None else round(found.smoothed_ms),
            "miss_boost": round(found.miss_boost, 3),
            "slow_boost": round(self.slow.boost(found), 3),
            "weight": round(self.weight(found), 3),
        }


NO_FIGURES = Book()


def book_of(rows: list[tuple[int, int, str, int | None]]) -> Book:
    """Return the figures of one operation's ledger rows, ``(m, n, outcome, taken_ms)`` in the order recorded."""
    counts: dict[tuple[int, int], list] = {}
    for m, n, outcome, taken in rows:
        # asked, right, run, smoothed, timed
        fact = counts.setdefault((m, n), [0, 0, 0, None, 0])
        fact[0] += 1
        if outcome != CORRECT:
            fact[2] = 0
            continue
        fact[1] += 1
        fact[2] += 1
        if taken is None:
            continue
        time = max(1, taken)
        fact[3] = time if fact[3] is None else fact[3] * (time / fact[3]) ** ALPHA
        fact[4] += 1
    facts = {key: Figures(*values) for key, values in counts.items()}
    timed = [each.smoothed_ms for each in facts.values() if each.timed >= TIMED_ANSWERS and each.smoothed_ms is not None]
    median = statistics.median(timed) if len(timed) >= TIMED_FACTS else None
    return Book(facts, Slow(len(timed), median))


def ensure_facts(connection: sqlite3.Connection) -> None:
    """Create the ledger, and on the first start build it from every stored arithmetic attempt.

    The attempts are counted in the order they started. A marker stored in
    the same step stops a later start counting them again.
    """
    with connection:
        for statement in SCHEMA:
            connection.execute(statement)
        marked = connection.execute("INSERT OR IGNORE INTO arithmetic_fact_meta (name) VALUES (?)", (_REBUILT,))
        if marked.rowcount != 1:
            return
        rows = connection.execute(
            "SELECT id, client_group, started_at, detail FROM attempts WHERE task_type = ? ORDER BY started_at, id",
            (ARITHMETIC,),
        ).fetchall()
        for attempt_id, client_group, started_at, detail in rows:
            try:
                loaded = json.loads(detail)
            except (TypeError, ValueError):
                continue
            _tally(connection, attempt_id, client_group, started_at, loaded)


def tally(connection: sqlite3.Connection, attempt_id: int, client_group: str, started_at: str, detail: Mapping) -> None:
    """Record the questions an attempt has answered so far, in one step. See ``_tally``."""
    with connection:
        _tally(connection, attempt_id, client_group, started_at, detail)


def _tally(connection: sqlite3.Connection, attempt_id: int, client_group: str, started_at: str, detail: Mapping) -> None:
    """Record each question of the attempt that has an outcome and is not recorded yet.

    A question still showing has no outcome and waits until it has one.
    """
    questions = detail.get("questions") if isinstance(detail, Mapping) else None
    if not isinstance(questions, list):
        return
    settings = detail.get("settings")
    recorded = {
        position
        for (position,) in connection.execute(
            "SELECT position FROM arithmetic_fact_questions WHERE attempt_id = ? AND started_at = ?",
            (attempt_id, started_at),
        )
    }
    for position, item in enumerate(questions):
        if position in recorded or not isinstance(item, Mapping) or item.get("outcome") not in OUTCOMES:
            continue
        m, n = _whole(item.get("m")), _whole(item.get("n"))
        operation = operation_of(item, settings if isinstance(settings, Mapping) else None)
        if m is None or n is None or operation is None:
            continue
        taken = item.get("taken_ms")
        connection.execute(
            "INSERT INTO arithmetic_fact_questions "
            "(client_group, operation, m, n, attempt_id, started_at, position, outcome, taken_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                client_group,
                operation,
                m,
                n,
                attempt_id,
                started_at,
                position,
                item["outcome"],
                max(0, round(taken)) if isinstance(taken, (int, float)) and not isinstance(taken, bool) else None,
            ),
        )


class FactStats:
    """Read the figures from the ledger on a connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def book(self, client_group: str, operation: str, *, leave_out: tuple[int, str] | None = None) -> Book:
        """Return one client group's figures for one operation.

        ``leave_out`` names an attempt, by id and start, whose questions are
        not counted, so an attempt's own answers never change its draws.
        """
        query = "SELECT m, n, outcome, taken_ms FROM arithmetic_fact_questions WHERE client_group = ? AND operation = ?"
        values: tuple = (client_group, operation)
        if leave_out is not None:
            query += " AND NOT (attempt_id = ? AND started_at = ?)"
            values += tuple(leave_out)
        return book_of(self.connection.execute(query + " ORDER BY seq", values).fetchall())


def _whole(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
