"""Task catalogue, cooldowns, and attempt history.

A task is named configuration: a type, an opaque body, the client groups it
is assigned to, and the day rules from S003.1. Attempts are rows. Eligibility,
skip days, and the pass cap are read from those rows each time, so a restart
does not forget them and a later edit of ``max_skips`` still sees the days
already stored.

The household day is the local date of a household-local moment. S009 is the
story that moves the boundary off midnight. Cooldowns, ``available_from``,
``due_date``, skip days, and the ``tasks_required`` count all ask
``household_day`` which day a moment belongs to.

A cooldown of N days elapses on the household day N day-boundaries after the
finish day. Zero is the same day. One is the next day. The last finished
attempt is the one that counts. A pass uses the pass cooldown, a failure uses
the failure cooldown, and an abandonment does not start one. An omitted
failure cooldown is no wait.

``parent_check`` is never required. ``available_from``, ``due_date``,
``max_skips``, and ``max_passes`` do not apply to it. Assignment and cooldown
still do.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

PARENT_CHECK = "parent_check"
IN_PROGRESS = "in_progress"
PASS = "pass"
FAILURE = "failure"
ABANDONED = "abandoned"
FINISHED = (PASS, FAILURE, ABANDONED)
SKIPPED = (FAILURE, ABANDONED)

SCHEMA = """
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY,
    client_group TEXT NOT NULL,
    task_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT NOT NULL CHECK (
        outcome IN ('in_progress', 'pass', 'failure', 'abandoned')
    ),
    detail TEXT NOT NULL,
    CHECK (
        (outcome = 'in_progress' AND finished_at IS NULL)
        OR (outcome != 'in_progress' AND finished_at IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS attempts_by_group
    ON attempts (client_group, task_name, id);
CREATE UNIQUE INDEX IF NOT EXISTS attempts_one_in_progress
    ON attempts (client_group, task_name)
    WHERE outcome = 'in_progress';
"""

_COLUMNS = (
    "id, client_group, task_name, started_at, finished_at, outcome, detail"
)


def household_day(moment: datetime) -> date:
    """Return the household day of a household-local moment.

    The day starts at local midnight until S009 configures another boundary.
    ``moment`` is already in the household zone. A naive value is taken to be
    that local clock already. The date is not converted from another zone.
    """
    if not isinstance(moment, datetime):
        raise ValueError("a household moment is a datetime")
    return moment.date()


def ensure_attempts(connection: sqlite3.Connection) -> None:
    """Create the attempt table on this connection if it is not there yet."""
    connection.executescript(SCHEMA)


def pass_count(connection: sqlite3.Connection, client_group: str, day: date) -> int:
    """Return how many pass attempts this client group finished on this day.

    One stored pass scores one point. Failure, abandonment, and another
    group's passes do not count. The day is the household day of the finish.
    """
    day = _as_date(day)
    ensure_attempts(connection)
    rows = connection.execute(
        "SELECT finished_at FROM attempts WHERE client_group = ? AND outcome = ?",
        (client_group, PASS),
    )
    return sum(
        1
        for (finished_at,) in rows
        if finished_at is not None and household_day(datetime.fromisoformat(finished_at)) == day
    )


@dataclass(frozen=True)
class Task:
    """One named task.

    ``body`` is a JSON object with its keys in the order the policy file
    wrote them. Quiz stories define its fields.
    This layer does not read them. ``groups`` is the client groups it is
    assigned to. Each keeps its own attempt history. ``failure_cooldown`` is
    None when the file left it out, which means a failure does not make the
    task wait.
    """

    name: str
    type: str
    groups: tuple[str, ...]
    pass_cooldown: int
    body: str = "{}"
    failure_cooldown: int | None = None
    available_from: date | None = None
    due_date: date | None = None
    max_skips: int | None = None
    max_passes: int | None = None

    def __post_init__(self) -> None:
        _label(self.name, "a task name")
        _label(self.type, "a task type")
        if not self.groups or any(not isinstance(group, str) or not group.strip() for group in self.groups):
            raise ValueError("a task is assigned to one or more client groups")
        _days(self.pass_cooldown, "pass cooldown")
        if self.failure_cooldown is not None:
            _days(self.failure_cooldown, "failure cooldown")
        _optional_days(self.max_skips, "max_skips")
        _optional_days(self.max_passes, "max_passes")
        _optional_date(self.available_from, "available_from")
        _optional_date(self.due_date, "due_date")
        loaded = json.loads(self.body)
        if not isinstance(loaded, dict):
            raise ValueError("a task body is a JSON object")

    def document(self) -> dict:
        """Return a copy of the type-specific body."""
        loaded = json.loads(self.body)
        if not isinstance(loaded, dict):
            raise ValueError("a task body is a JSON object")
        return loaded


@dataclass(frozen=True)
class Attempt:
    """One try by one client group.

    ``started_at`` and ``finished_at`` are household-local. ``detail`` is the
    JSON object the quiz fills with what was asked and what was answered.
    An in-progress attempt has no finish time.
    """

    id: int
    client_group: str
    task: str
    started_at: datetime
    finished_at: datetime | None
    outcome: str
    detail: Mapping


def is_eligible(
    task: Task,
    client_group: str,
    today: date,
    attempts: Sequence[Attempt],
) -> bool:
    """Return whether this client group may be offered the task on this day.

    Assigned, available, under the pass cap, and out of cooldown. A task at
    ``max_passes`` is not eligible, so a due date or a skip limit cannot make
    it required. ``parent_check`` ignores availability and the pass cap.
    """
    today = _as_date(today)
    if client_group not in task.groups:
        return False
    if task.type != PARENT_CHECK:
        if task.available_from is not None and today < task.available_from:
            return False
        if task.max_passes is not None and stored_passes(task.name, client_group, attempts) >= task.max_passes:
            return False
    return _cooldown_elapsed(task, client_group, today, attempts)


def is_required(
    task: Task,
    client_group: str,
    today: date,
    attempts: Sequence[Attempt],
) -> bool:
    """Return whether an eligible task is required for this client group today.

    A due date requires it once today is on or after that date and this group
    has never passed it. Skip days before today require it once they reach
    ``max_skips``. A skip recorded today does not. Either condition is enough.
    A task that is not eligible is not required. ``parent_check`` is never
    required.
    """
    today = _as_date(today)
    if task.type == PARENT_CHECK:
        return False
    if not is_eligible(task, client_group, today, attempts):
        return False
    if task.due_date is not None and today >= task.due_date:
        if stored_passes(task.name, client_group, attempts) == 0:
            return True
    if task.max_skips is not None and len(skip_days(task.name, client_group, attempts, before=today)) >= task.max_skips:
        return True
    return False


def stored_passes(task_name: str, client_group: str, attempts: Sequence[Attempt]) -> int:
    """Return how many pass rows this client group has stored for this task."""
    return sum(
        1
        for attempt in attempts
        if attempt.task == task_name and attempt.client_group == client_group and attempt.outcome == PASS
    )


def skip_days(
    task_name: str,
    client_group: str,
    attempts: Sequence[Attempt],
    *,
    before: date | None = None,
) -> frozenset[date]:
    """Return the household days this group failed or abandoned this task.

    The count starts again after the group's last pass. A day with several
    failures, several abandonments, or one of each is still one day. ``before``
    leaves out that day and every later one, which is how "skip days before
    today" is read.
    """
    if before is not None:
        before = _as_date(before)
    last_pass = _last_pass(task_name, client_group, attempts)
    found: set[date] = set()
    for attempt in attempts:
        if attempt.task != task_name or attempt.client_group != client_group:
            continue
        if attempt.outcome not in SKIPPED or attempt.finished_at is None:
            continue
        if last_pass is not None and last_pass.finished_at is not None:
            if attempt.finished_at <= last_pass.finished_at:
                continue
        day = household_day(attempt.finished_at)
        if before is not None and day >= before:
            continue
        found.add(day)
    return frozenset(found)


class AttemptStore:
    """Attempt rows for every client group.

    The connection may be one the decisions service already opened. A store
    constructed from a path owns its connection and closes it. Rows survive
    a restart. Skip days are not stored on their own. They are derived from
    these rows.
    """

    def __init__(
        self,
        path: str | Path = ":memory:",
        *,
        connection: sqlite3.Connection | None = None,
        check_same_thread: bool = True,
    ) -> None:
        if connection is not None:
            self.connection = connection
            self._owns = False
        else:
            self.connection = sqlite3.connect(path, check_same_thread=check_same_thread)
            self._owns = True
            self.connection.execute("PRAGMA busy_timeout = 5000")
            if str(path) != ":memory:":
                self.connection.execute("PRAGMA journal_mode = WAL").fetchone()
        ensure_attempts(self.connection)

    def __enter__(self) -> AttemptStore:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        if self._owns:
            self.connection.close()

    def get(self, attempt_id: int) -> Attempt | None:
        """Return one attempt, or None when that id is not stored."""
        if isinstance(attempt_id, bool) or not isinstance(attempt_id, int) or attempt_id < 1:
            raise ValueError("an attempt id is a whole number")
        row = self.connection.execute(
            f"SELECT {_COLUMNS} FROM attempts WHERE id = ?",
            (attempt_id,),
        ).fetchone()
        return None if row is None else _attempt(row)

    def recent(self, client_group: str) -> tuple[Attempt, ...]:
        """Return this group's attempts, newest start first.

        The same start time is ordered by the newer id. Another client
        group's rows are never included.
        """
        _label(client_group, "a client group")
        rows = self.connection.execute(
            f"SELECT {_COLUMNS} FROM attempts WHERE client_group = ? "
            "ORDER BY started_at DESC, id DESC",
            (client_group,),
        ).fetchall()
        return tuple(_attempt(row) for row in rows)

    def attempts(self, client_group: str, task: str | None = None) -> tuple[Attempt, ...]:
        """Return this group's attempts, oldest id first.

        Pass a task name to keep the other tasks out. Another client group's
        rows are never included.
        """
        _label(client_group, "a client group")
        if task is None:
            rows = self.connection.execute(
                f"SELECT {_COLUMNS} FROM attempts WHERE client_group = ? ORDER BY id",
                (client_group,),
            ).fetchall()
        else:
            _label(task, "a task name")
            rows = self.connection.execute(
                f"SELECT {_COLUMNS} FROM attempts WHERE client_group = ? AND task_name = ? ORDER BY id",
                (client_group, task),
            ).fetchall()
        return tuple(_attempt(row) for row in rows)

    def everything(self) -> tuple[Attempt, ...]:
        """Return every client group's attempts, oldest id first. Maintenance reads this."""
        rows = self.connection.execute(f"SELECT {_COLUMNS} FROM attempts ORDER BY id").fetchall()
        return tuple(_attempt(row) for row in rows)

    def remove(self, attempt_ids: Sequence[int]) -> int:
        """Delete these attempts and return how many were stored.

        Skip days, cooldowns, and pass counts are read from the rows, so they
        forget a removed attempt straight away.
        """
        ids = list(attempt_ids)
        if any(isinstance(item, bool) or not isinstance(item, int) for item in ids):
            raise ValueError("an attempt id is a whole number")
        removed = 0
        with self.connection:
            for attempt_id in ids:
                removed += self.connection.execute("DELETE FROM attempts WHERE id = ?", (attempt_id,)).rowcount
        return removed

    def in_progress(self, client_group: str, task: str) -> Attempt | None:
        """Return the open attempt for this group and task, if there is one."""
        _label(client_group, "a client group")
        _label(task, "a task name")
        row = self.connection.execute(
            f"SELECT {_COLUMNS} FROM attempts "
            "WHERE client_group = ? AND task_name = ? AND outcome = ?",
            (client_group, task, IN_PROGRESS),
        ).fetchone()
        return None if row is None else _attempt(row)

    def begin(
        self,
        client_group: str,
        task: str,
        started_at: datetime,
        *,
        detail: Mapping | None = None,
    ) -> Attempt:
        """Start an attempt, or return the one already in progress.

        Coming back does not open a second parallel attempt for the same
        client group and task. Another group, and another task, are separate.
        """
        _label(client_group, "a client group")
        _label(task, "a task name")
        existing = self.in_progress(client_group, task)
        if existing is not None:
            return existing
        stamp = _stamp(started_at)
        payload = _payload(detail)
        with self.connection:
            try:
                cursor = self.connection.execute(
                    "INSERT INTO attempts "
                    "(client_group, task_name, started_at, finished_at, outcome, detail) "
                    "VALUES (?, ?, ?, NULL, ?, ?)",
                    (client_group, task, stamp, IN_PROGRESS, payload),
                )
            except sqlite3.IntegrityError:
                raced = self.in_progress(client_group, task)
                if raced is not None:
                    return raced
                raise
        return self._by_id(int(cursor.lastrowid))

    def finish(
        self,
        attempt_id: int,
        outcome: str,
        finished_at: datetime,
        detail: Mapping | None = None,
    ) -> Attempt:
        """Finish an in-progress attempt and store the outcome.

        A pass is stored even when the task is no longer eligible, including
        when ``max_passes`` was lowered while this attempt was open. The
        detail replaces whatever the attempt was holding.
        """
        if outcome not in FINISHED:
            raise ValueError("a finished attempt is a pass, a failure, or abandoned")
        current = self._by_id(attempt_id)
        if current.outcome != IN_PROGRESS:
            raise ValueError("this attempt is already finished")
        stamp = _stamp(finished_at)
        payload = _payload(detail)
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE attempts SET finished_at = ?, outcome = ?, detail = ? "
                "WHERE id = ? AND outcome = ?",
                (stamp, outcome, payload, attempt_id, IN_PROGRESS),
            )
            if cursor.rowcount != 1:
                raise ValueError("this attempt is already finished")
        return self._by_id(attempt_id)

    def save(self, attempt_id: int, detail: Mapping) -> Attempt:
        """Replace the detail of an in-progress attempt, so a reload keeps it.

        A finished attempt is not changed.
        """
        payload = _payload(detail)
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE attempts SET detail = ? WHERE id = ? AND outcome = ?",
                (payload, attempt_id, IN_PROGRESS),
            )
            if cursor.rowcount != 1:
                raise ValueError("only an attempt in progress can be saved")
        return self._by_id(attempt_id)

    def record(
        self,
        client_group: str,
        task: str,
        outcome: str,
        finished_at: datetime,
        *,
        started_at: datetime | None = None,
        detail: Mapping | None = None,
    ) -> Attempt:
        """Store a finished attempt in one step.

        This is how a parent check is recorded, and how a test plants history.
        It does not consult eligibility. The caller decides whether the task
        was eligible. An open attempt for the same task is left open.
        """
        if outcome not in FINISHED:
            raise ValueError("a finished attempt is a pass, a failure, or abandoned")
        _label(client_group, "a client group")
        _label(task, "a task name")
        finished = _stamp(finished_at)
        started = finished if started_at is None else _stamp(started_at)
        payload = _payload(detail)
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO attempts "
                "(client_group, task_name, started_at, finished_at, outcome, detail) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (client_group, task, started, finished, outcome, payload),
            )
        return self._by_id(int(cursor.lastrowid))

    def is_eligible(self, task: Task, client_group: str, today: date) -> bool:
        return is_eligible(task, client_group, today, self.attempts(client_group, task.name))

    def is_required(self, task: Task, client_group: str, today: date) -> bool:
        return is_required(task, client_group, today, self.attempts(client_group, task.name))

    def passes_on(self, client_group: str, day: date) -> int:
        """Return the revision points this client group scored on this day."""
        return pass_count(self.connection, client_group, day)

    def _by_id(self, attempt_id: int) -> Attempt:
        row = self.connection.execute(
            f"SELECT {_COLUMNS} FROM attempts WHERE id = ?",
            (attempt_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"attempt {attempt_id} is not stored")
        return _attempt(row)


def _cooldown_elapsed(
    task: Task,
    client_group: str,
    today: date,
    attempts: Sequence[Attempt],
) -> bool:
    last = _last_finished(task.name, client_group, attempts)
    if last is None or last.finished_at is None or last.outcome == ABANDONED:
        return True
    if last.outcome == PASS:
        wait = task.pass_cooldown
    elif last.outcome == FAILURE:
        wait = 0 if task.failure_cooldown is None else task.failure_cooldown
    else:
        return True
    return (today - household_day(last.finished_at)).days >= wait


def _last_finished(task_name: str, client_group: str, attempts: Sequence[Attempt]) -> Attempt | None:
    finished = [
        attempt
        for attempt in attempts
        if attempt.task == task_name
        and attempt.client_group == client_group
        and attempt.outcome in FINISHED
        and attempt.finished_at is not None
    ]
    if not finished:
        return None
    return max(finished, key=lambda attempt: (attempt.finished_at, attempt.id))


def _last_pass(task_name: str, client_group: str, attempts: Sequence[Attempt]) -> Attempt | None:
    passes = [
        attempt
        for attempt in attempts
        if attempt.task == task_name
        and attempt.client_group == client_group
        and attempt.outcome == PASS
        and attempt.finished_at is not None
    ]
    if not passes:
        return None
    return max(passes, key=lambda attempt: (attempt.finished_at, attempt.id))


def _attempt(row: tuple) -> Attempt:
    attempt_id, client_group, task_name, started_at, finished_at, outcome, detail = row
    loaded = json.loads(detail)
    if not isinstance(loaded, dict):
        raise ValueError("attempt detail is a JSON object")
    return Attempt(
        int(attempt_id),
        client_group,
        task_name,
        datetime.fromisoformat(started_at),
        None if finished_at is None else datetime.fromisoformat(finished_at),
        outcome,
        loaded,
    )


def _payload(detail: Mapping | None) -> str:
    if detail is None:
        detail = {}
    if not isinstance(detail, Mapping):
        raise ValueError("attempt detail is a JSON object")
    try:
        return json.dumps(dict(detail), ensure_ascii=False, separators=(",", ":"))
    except TypeError as exc:
        raise ValueError("attempt detail is a JSON object") from exc


def _stamp(moment: datetime) -> str:
    if not isinstance(moment, datetime):
        raise ValueError("time must be a datetime")
    return moment.replace(microsecond=0).isoformat(timespec="seconds")


def _as_date(value: object) -> date:
    if type(value) is not date:
        raise ValueError("a household day is a date")
    return value


def _label(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value


def _days(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} is a whole number of household days, zero or more")
    return value


def _optional_days(value: object, name: str) -> None:
    if value is not None:
        _days(value, name)


def _optional_date(value: object, name: str) -> None:
    if value is not None and type(value) is not date:
        raise ValueError(f"{name} is a household date")
