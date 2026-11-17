"""Spelling word figures: how often each word has been asked, right, and wrong.

The household database keeps one ledger row for each word in each attempt
that asked it, whatever the attempt's task. A row says whether the word was
missed at least once in that attempt. The figures are worked out from the
ledger, so recording an attempt again changes nothing, and a row is not
removed when its attempt is, so ``rm-attempts`` leaves the figures alone.

Words are identified by their entry key folded to lower case, such as
``rope`` or ``read.1``, within a client group. The weights that choose
revision words are fixed here, not in the policy file.
"""

from __future__ import annotations

import json
import random
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from policy.quiz import CORRECT, OUTCOMES

SPELLING = "spelling"
# A word right on this many of its last tasks, or on all of them when it has fewer, has no boost.
SETTLED_RUN = 5
BOOST = 4.0

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS spelling_word_tasks (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        client_group TEXT NOT NULL,
        word TEXT NOT NULL,
        attempt_id INTEGER NOT NULL,
        started_at TEXT NOT NULL,
        missed INTEGER NOT NULL CHECK (missed IN (0, 1)),
        UNIQUE (client_group, word, attempt_id, started_at)
    )
    """,
    "CREATE INDEX IF NOT EXISTS spelling_word_tasks_by_word ON spelling_word_tasks (client_group, word, seq)",
    "CREATE TABLE IF NOT EXISTS spelling_word_meta (name TEXT PRIMARY KEY)",
)
_REBUILT = "rebuilt"


@dataclass(frozen=True)
class Figures:
    """One word's figures for one client group. ``run`` is the correct tasks in a row, latest first."""

    attempts: int = 0
    correct: int = 0
    incorrect: int = 0
    run: int = 0

    @property
    def weight(self) -> float:
        return weight(self.attempts, self.run)


def weight(attempts: int, run: int) -> float:
    """Return a revision word's chance of being picked, relative to the other revision words.

    ``1 / (attempts + 1)`` favours a word asked fewer times. A word that is
    not right on its last ``min(5, attempts)`` tasks adds ``4 * 0.5 ** run``,
    which halves with each correct task and does not shrink as attempts grow.
    """
    base = 1 / (attempts + 1)
    if run >= min(SETTLED_RUN, attempts):
        return base
    return base + BOOST * 0.5**run


def weighted_sample(rng: random.Random, items: Sequence, weights: Sequence[float], count: int) -> list:
    """Return ``count`` items picked without repeats, each draw in proportion to the weights left."""
    pool = list(zip(items, weights))
    chosen = []
    for _ in range(count):
        point = rng.random() * sum(each for _item, each in pool)
        index = len(pool) - 1
        for position, (_item, each) in enumerate(pool):
            point -= each
            if point < 0:
                index = position
                break
        chosen.append(pool.pop(index)[0])
    return chosen


FigureLookup = Callable[[Sequence[str]], Mapping[str, Figures]]


def ensure_words(connection: sqlite3.Connection) -> None:
    """Create the ledger, and on the first start build it from every stored spelling attempt.

    The attempts are counted in the order they started. A marker stored in
    the same step stops a later start counting them again.
    """
    with connection:
        for statement in SCHEMA:
            connection.execute(statement)
        marked = connection.execute("INSERT OR IGNORE INTO spelling_word_meta (name) VALUES (?)", (_REBUILT,))
        if marked.rowcount != 1:
            return
        rows = connection.execute(
            "SELECT id, client_group, started_at, detail FROM attempts WHERE task_type = ? ORDER BY started_at, id",
            (SPELLING,),
        ).fetchall()
        for attempt_id, client_group, started_at, detail in rows:
            try:
                loaded = json.loads(detail)
            except ValueError:
                continue
            _tally(connection, attempt_id, client_group, started_at, loaded)


def tally(connection: sqlite3.Connection, attempt_id: int, client_group: str, started_at: str, detail: Mapping) -> None:
    """Record the words an attempt asked, in one step. See ``_tally``."""
    with connection:
        _tally(connection, attempt_id, client_group, started_at, detail)


def _tally(connection: sqlite3.Connection, attempt_id: int, client_group: str, started_at: str, detail: Mapping) -> None:
    """Record each word the attempt's answered questions asked. Doing it again changes nothing new.

    A word is missed in the attempt when any of its questions was wrong or
    timed out. A word first missed after it was recorded right is changed to
    missed.
    """
    missed: dict[str, bool] = {}
    questions = detail.get("questions") if isinstance(detail, Mapping) else None
    for item in questions if isinstance(questions, list) else ():
        if not isinstance(item, Mapping) or not isinstance(item.get("key"), str) or item.get("outcome") not in OUTCOMES:
            continue
        word = item["key"].lower()
        missed[word] = missed.get(word, False) or item["outcome"] != CORRECT
    if not missed:
        return
    where = "client_group = ? AND attempt_id = ? AND started_at = ?"
    known = dict(
        connection.execute(
            f"SELECT word, missed FROM spelling_word_tasks WHERE {where}", (client_group, attempt_id, started_at)
        ).fetchall()
    )
    for word, was_missed in missed.items():
        if word not in known:
            connection.execute(
                "INSERT INTO spelling_word_tasks (client_group, word, attempt_id, started_at, missed) "
                "VALUES (?, ?, ?, ?, ?)",
                (client_group, word, attempt_id, started_at, int(was_missed)),
            )
        elif was_missed and not known[word]:
            connection.execute(
                f"UPDATE spelling_word_tasks SET missed = 1 WHERE {where} AND word = ?",
                (client_group, attempt_id, started_at, word),
            )


class WordStats:
    """Read the figures from the ledger on a connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def figures(self, client_group: str, words: Sequence[str] | None = None) -> dict[str, Figures]:
        """Return the figures of each word of this client group that has any, by folded key.

        ``words`` limits them to those keys. A word with no ledger rows is
        left out.
        """
        wanted = None if words is None else {word.lower() for word in words}
        rows = self.connection.execute(
            "SELECT word, missed FROM spelling_word_tasks WHERE client_group = ? ORDER BY seq", (client_group,)
        )
        tasks: dict[str, list[bool]] = {}
        for word, missed in rows:
            if wanted is None or word in wanted:
                tasks.setdefault(word, []).append(bool(missed))
        return {word: _figures(history) for word, history in tasks.items()}

    def all_figures(self) -> dict[tuple[str, str], Figures]:
        """Return every client group's figures, by client group and folded key."""
        found: dict[tuple[str, str], Figures] = {}
        for (group,) in self.connection.execute("SELECT DISTINCT client_group FROM spelling_word_tasks ORDER BY 1"):
            for word, figures in self.figures(group).items():
                found[(group, word)] = figures
        return found


def _figures(history: Sequence[bool]) -> Figures:
    missed = sum(history)
    run = 0
    for was_missed in reversed(history):
        if was_missed:
            break
        run += 1
    return Figures(len(history), len(history) - missed, missed, run)
