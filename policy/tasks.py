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

Each attempt is stored with the task set the task was in when it started:
required, potential, practice, or parent check. A practice attempt is kept
for the parent to see, and counts for nothing: no cooldown, skip day, pass
cap, due date, or score. An attempt left in progress past the household day
it started is a skip day for that day, and is closed as unfinished when the
task is next opened.

``parent_check`` is never required. ``available_from``, ``due_date``,
``max_skips``, and ``max_passes`` do not apply to it. Assignment and cooldown
still do.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

PARENT_CHECK = "parent_check"
IN_PROGRESS = "in_progress"
PASS = "pass"
FAILURE = "failure"
ABANDONED = "abandoned"
UNFINISHED = "unfinished"
FINISHED = (PASS, FAILURE, ABANDONED)
SKIPPED = (FAILURE, ABANDONED)

REQUIRED = "required"
POTENTIAL = "potential"
PRACTICE = "practice"
TASK_SETS = (REQUIRED, POTENTIAL, PRACTICE, PARENT_CHECK)

SCHEMA = """
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY,
    client_group TEXT NOT NULL,
    task_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT NOT NULL CHECK (
        outcome IN ('in_progress', 'pass', 'failure', 'abandoned', 'unfinished')
    ),
    detail TEXT NOT NULL,
    task_set TEXT NOT NULL DEFAULT 'required' CHECK (
        task_set IN ('required', 'potential', 'practice', 'parent_check')
    ),
    reopened TEXT NOT NULL DEFAULT '[]',
    CHECK (
        (outcome IN ('in_progress', 'unfinished') AND finished_at IS NULL)
        OR (outcome NOT IN ('in_progress', 'unfinished') AND finished_at IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS attempts_by_group
    ON attempts (client_group, task_name, id);
CREATE UNIQUE INDEX IF NOT EXISTS attempts_one_in_progress
    ON attempts (client_group, task_name)
    WHERE outcome = 'in_progress';
"""

# Attempts stored before task sets existed keep their rows and become required.
_UPGRADE = (
    SCHEMA.replace("CREATE TABLE IF NOT EXISTS attempts (", "CREATE TABLE attempts_upgraded (", 1).split(
        "CREATE INDEX", 1
    )[0],
    "INSERT INTO attempts_upgraded "
    "(id, client_group, task_name, started_at, finished_at, outcome, detail, task_set, reopened) "
    "SELECT id, client_group, task_name, started_at, finished_at, outcome, detail, 'required', '[]' "
    "FROM attempts",
    "DROP TABLE attempts",
    "ALTER TABLE attempts_upgraded RENAME TO attempts",
)

_COLUMNS = (
    "id, client_group, task_name, started_at, finished_at, outcome, detail, task_set, reopened"
)
# The same row without the quiz detail, for reading a whole history quickly.
_HISTORY = (
    "id, client_group, task_name, started_at, finished_at, outcome, '{}', task_set, reopened"
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
    """Create the attempt table on this connection, or upgrade one stored before task sets."""
    if _needs_upgrade(connection):
        _upgrade(connection)
    connection.executescript(SCHEMA)


def _needs_upgrade(connection: sqlite3.Connection) -> bool:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(attempts)")}
    return bool(columns) and "task_set" not in columns


def _upgrade(connection: sqlite3.Connection) -> None:
    # The decisions and observations services share the file, so the check is
    # repeated once the write lock is held.
    if connection.in_transaction:
        connection.commit()
    connection.execute("BEGIN IMMEDIATE")
    try:
        if _needs_upgrade(connection):
            for statement in _UPGRADE:
                connection.execute(statement)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def pass_count(
    connection: sqlite3.Connection,
    client_group: str,
    day: date,
    tasks: Sequence[Task] = (),
) -> int:
    """Return this client group's score on this household day.

    ``tasks`` is the policy's task list, which says whether any task is
    still required, and so whether potential passes count yet.
    """
    day = _as_date(day)
    ensure_attempts(connection)
    rows = connection.execute(
        f"SELECT {_HISTORY} FROM attempts WHERE client_group = ? ORDER BY id",
        (client_group,),
    ).fetchall()
    return day_score(tasks, client_group, day, tuple(_attempt(row) for row in rows)).points


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
    An in-progress or unfinished attempt has no finish time. ``task_set`` is
    the set the task was in when the attempt started. ``reopened`` holds a
    ``gave_up`` and a ``came_back`` time for each time a given-up attempt
    was carried on.
    """

    id: int
    client_group: str
    task: str
    started_at: datetime
    finished_at: datetime | None
    outcome: str
    detail: Mapping
    task_set: str = REQUIRED
    reopened: tuple[Mapping, ...] = ()

    @property
    def counted(self) -> bool:
        """Return whether this attempt counts for cooldowns, skip days, passes, and due dates."""
        return self.task_set != PRACTICE

    def left_open(self, today: date) -> bool:
        """Return whether this attempt was left unfinished on a household day before today."""
        if self.outcome == UNFINISHED:
            return True
        return self.outcome == IN_PROGRESS and household_day(self.started_at) < today


@dataclass(frozen=True)
class TaskSets:
    """The tasks one client group is offered on one household day.

    ``configured`` is every task assigned to the group, other than
    ``parent_check``. ``required`` and ``potential`` are in the policy's
    task order. ``available`` is the required tasks while there are any,
    and otherwise the potential tasks.
    """

    configured: tuple[Task, ...]
    required: tuple[Task, ...]
    potential: tuple[Task, ...]

    @property
    def available(self) -> tuple[Task, ...]:
        return self.required or self.potential

    def set_of(self, name: str) -> str:
        """Return the set an attempt of this task would start in now."""
        if any(task.name == name for task in self.required):
            return REQUIRED
        if any(task.name == name for task in self.potential):
            return POTENTIAL
        return PRACTICE


@dataclass(frozen=True)
class Score:
    """Today's score, and what the parent page shows about it.

    ``waiting`` names the potential passes that score nothing until no
    task is required.
    """

    points: int
    sets: TaskSets
    waiting: tuple[str, ...] = field(default=())


def task_sets(
    tasks: Sequence[Task],
    client_group: str,
    today: date,
    attempts: Sequence[Attempt],
) -> TaskSets:
    """Return the configured, required, and potential tasks for this group today."""
    today = _as_date(today)
    configured = tuple(task for task in tasks if task.type != PARENT_CHECK and client_group in task.groups)
    required = tuple(task for task in configured if is_required(task, client_group, today, attempts))
    potential = tuple(
        task
        for task in configured
        if task not in required and is_eligible(task, client_group, today, attempts)
    )
    return TaskSets(configured, required, potential)


def day_score(
    tasks: Sequence[Task],
    client_group: str,
    day: date,
    attempts: Sequence[Attempt],
) -> Score:
    """Return this group's score on this household day.

    A required pass scores one point. A potential pass scores one point only
    while no task is required. No task scores twice in a day, and a practice
    pass scores nothing. Each parent check scores one point.
    """
    day = _as_date(day)
    sets = task_sets(tasks, client_group, day, attempts)
    passes = [
        attempt
        for attempt in attempts
        if attempt.client_group == client_group
        and attempt.outcome == PASS
        and attempt.finished_at is not None
        and household_day(attempt.finished_at) == day
    ]
    points = sum(1 for attempt in passes if attempt.task_set == PARENT_CHECK)
    scored: set[str] = set()
    for attempt in passes:
        if attempt.task_set == REQUIRED and attempt.task not in scored:
            scored.add(attempt.task)
            points += 1
    waiting: list[str] = []
    for attempt in passes:
        if attempt.task_set != POTENTIAL or attempt.task in scored or attempt.task in waiting:
            continue
        if sets.required:
            waiting.append(attempt.task)
        else:
            scored.add(attempt.task)
            points += 1
    return Score(points, sets, tuple(waiting))


def is_eligible(
    task: Task,
    client_group: str,
    today: date,
    attempts: Sequence[Attempt],
) -> bool:
    """Return whether this client group may be offered the task on this day.

    Assigned, available, under the pass cap, out of cooldown, and not passed
    already today. A task at ``max_passes`` is not eligible, so a due date
    or a skip limit cannot make it required. ``parent_check`` ignores
    availability, the pass cap, and today's pass. Practice attempts are
    left out of every one of these.
    """
    today = _as_date(today)
    if client_group not in task.groups:
        return False
    if task.type != PARENT_CHECK:
        if task.available_from is not None and today < task.available_from:
            return False
        if task.max_passes is not None and stored_passes(task.name, client_group, attempts) >= task.max_passes:
            return False
        last = _last_pass(task.name, client_group, attempts)
        if last is not None and last.finished_at is not None and household_day(last.finished_at) == today:
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
    """Return how many counted pass rows this client group has stored for this task."""
    return sum(
        1
        for attempt in attempts
        if attempt.task == task_name
        and attempt.client_group == client_group
        and attempt.outcome == PASS
        and attempt.counted
    )


def skip_days(
    task_name: str,
    client_group: str,
    attempts: Sequence[Attempt],
    *,
    before: date | None = None,
) -> frozenset[date]:
    """Return the household days this group failed, abandoned, or left this task unfinished.

    The count starts again after the group's last pass. A day with several
    failures, several abandonments, or one of each is still one day. An
    attempt left in progress counts for the day it started, once that day
    has ended. ``before`` leaves out that day and every later one, which is
    how "skip days before today" is read. Practice attempts are not skips.
    """
    if before is not None:
        before = _as_date(before)
    last_pass = _last_pass(task_name, client_group, attempts)
    ended = None if last_pass is None else last_pass.finished_at
    found: set[date] = set()
    for attempt in attempts:
        if attempt.task != task_name or attempt.client_group != client_group or not attempt.counted:
            continue
        if attempt.outcome in SKIPPED and attempt.finished_at is not None:
            moment = attempt.finished_at
        elif attempt.outcome in (UNFINISHED, IN_PROGRESS):
            moment = attempt.started_at
            if attempt.outcome == IN_PROGRESS and (before is None or household_day(moment) >= before):
                continue
        else:
            continue
        if ended is not None and moment <= ended:
            continue
        day = household_day(moment)
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

    def history(self, client_group: str) -> tuple[Attempt, ...]:
        """Return this group's attempts, oldest id first, without their quiz detail.

        This is what the task sets and the score read on every decision.
        """
        _label(client_group, "a client group")
        rows = self.connection.execute(
            f"SELECT {_HISTORY} FROM attempts WHERE client_group = ? ORDER BY id",
            (client_group,),
        ).fetchall()
        return tuple(_attempt(row) for row in rows)

    def begin(
        self,
        client_group: str,
        task: str,
        started_at: datetime,
        *,
        detail: Mapping | None = None,
        task_set: str = REQUIRED,
    ) -> Attempt:
        """Start an attempt, or return the one already in progress.

        Coming back does not open a second parallel attempt for the same
        client group and task. Another group, and another task, are separate.
        """
        _label(client_group, "a client group")
        _label(task, "a task name")
        _task_set(task_set)
        existing = self.in_progress(client_group, task)
        if existing is not None:
            return existing
        stamp = _stamp(started_at)
        payload = _payload(detail)
        with self.connection:
            try:
                cursor = self.connection.execute(
                    "INSERT INTO attempts "
                    "(client_group, task_name, started_at, finished_at, outcome, detail, task_set) "
                    "VALUES (?, ?, ?, NULL, ?, ?, ?)",
                    (client_group, task, stamp, IN_PROGRESS, payload, task_set),
                )
            except sqlite3.IntegrityError:
                raced = self.in_progress(client_group, task)
                if raced is not None:
                    return raced
                raise
        return self._by_id(int(cursor.lastrowid))

    def open(
        self,
        client_group: str,
        task: str,
        now: datetime,
        *,
        task_set: str,
        reopen_within: timedelta,
    ) -> Attempt:
        """Return the attempt a task page opened now works on.

        An attempt in progress since earlier today carries on. One started
        on an earlier household day is closed as unfinished. A given-up
        attempt carries on when it is this task's newest attempt, it started
        today, and it was given up no more than ``reopen_within`` ago.
        Otherwise a new attempt starts in ``task_set``.
        """
        today = household_day(now)
        current = self.in_progress(client_group, task)
        if current is not None:
            if household_day(current.started_at) == today:
                return current
            self._close_unfinished(current.id)
        else:
            newest = self._newest(client_group, task)
            if (
                newest is not None
                and newest.outcome == ABANDONED
                and newest.finished_at is not None
                and household_day(newest.started_at) == today
                and now - newest.finished_at <= reopen_within
            ):
                reopened = self._reopen(newest, now)
                if reopened is not None:
                    return reopened
        return self.begin(client_group, task, now, task_set=task_set)

    def _newest(self, client_group: str, task: str) -> Attempt | None:
        row = self.connection.execute(
            f"SELECT {_COLUMNS} FROM attempts WHERE client_group = ? AND task_name = ? "
            "ORDER BY started_at DESC, id DESC LIMIT 1",
            (client_group, task),
        ).fetchone()
        return None if row is None else _attempt(row)

    def _reopen(self, attempt: Attempt, now: datetime) -> Attempt | None:
        assert attempt.finished_at is not None
        events = [*attempt.reopened, {"gave_up": _stamp(attempt.finished_at), "came_back": _stamp(now)}]
        try:
            with self.connection:
                cursor = self.connection.execute(
                    "UPDATE attempts SET outcome = ?, finished_at = NULL, reopened = ? "
                    "WHERE id = ? AND outcome = ?",
                    (IN_PROGRESS, json.dumps(events, separators=(",", ":")), attempt.id, ABANDONED),
                )
        except sqlite3.IntegrityError:
            return self.in_progress(attempt.client_group, attempt.task)
        if cursor.rowcount != 1:
            return self.in_progress(attempt.client_group, attempt.task)
        return self._by_id(attempt.id)

    def _close_unfinished(self, attempt_id: int) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE attempts SET outcome = ? WHERE id = ? AND outcome = ?",
                (UNFINISHED, attempt_id, IN_PROGRESS),
            )

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
        task_set: str = REQUIRED,
    ) -> Attempt:
        """Store a finished attempt in one step.

        This is how a parent check is recorded, and how a test plants history.
        It does not consult eligibility. The caller decides whether the task
        was eligible and which set it was in. An open attempt for the same
        task is left open.
        """
        if outcome not in FINISHED:
            raise ValueError("a finished attempt is a pass, a failure, or abandoned")
        _label(client_group, "a client group")
        _label(task, "a task name")
        _task_set(task_set)
        finished = _stamp(finished_at)
        started = finished if started_at is None else _stamp(started_at)
        payload = _payload(detail)
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO attempts "
                "(client_group, task_name, started_at, finished_at, outcome, detail, task_set) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (client_group, task, started, finished, outcome, payload, task_set),
            )
        return self._by_id(int(cursor.lastrowid))

    def is_eligible(self, task: Task, client_group: str, today: date) -> bool:
        return is_eligible(task, client_group, today, self.attempts(client_group, task.name))

    def is_required(self, task: Task, client_group: str, today: date) -> bool:
        return is_required(task, client_group, today, self.attempts(client_group, task.name))

    def task_sets(self, tasks: Sequence[Task], client_group: str, today: date) -> TaskSets:
        return task_sets(tasks, client_group, today, self.history(client_group))

    def score(self, tasks: Sequence[Task], client_group: str, day: date) -> Score:
        return day_score(tasks, client_group, day, self.history(client_group))

    def passes_on(self, client_group: str, day: date, tasks: Sequence[Task] = ()) -> int:
        """Return the revision points this client group scored on this day."""
        return pass_count(self.connection, client_group, day, tasks)

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
        and attempt.counted
        and attempt.outcome in FINISHED
        and attempt.finished_at is not None
    ]
    if not finished:
        return None
    return max(finished, key=lambda attempt: (attempt.finished_at, attempt.id))


def last_pass(task_name: str, client_group: str, attempts: Sequence[Attempt]) -> Attempt | None:
    """Return this group's latest counted pass of this task, or None."""
    return _last_pass(task_name, client_group, attempts)


def _last_pass(task_name: str, client_group: str, attempts: Sequence[Attempt]) -> Attempt | None:
    passes = [
        attempt
        for attempt in attempts
        if attempt.task == task_name
        and attempt.client_group == client_group
        and attempt.counted
        and attempt.outcome == PASS
        and attempt.finished_at is not None
    ]
    if not passes:
        return None
    return max(passes, key=lambda attempt: (attempt.finished_at, attempt.id))


def _attempt(row: tuple) -> Attempt:
    attempt_id, client_group, task_name, started_at, finished_at, outcome, detail, task_set, reopened = row
    loaded = json.loads(detail)
    if not isinstance(loaded, dict):
        raise ValueError("attempt detail is a JSON object")
    events = json.loads(reopened)
    return Attempt(
        int(attempt_id),
        client_group,
        task_name,
        datetime.fromisoformat(started_at),
        None if finished_at is None else datetime.fromisoformat(finished_at),
        outcome,
        loaded,
        task_set,
        tuple(event for event in events if isinstance(event, dict)) if isinstance(events, list) else (),
    )


def _task_set(value: object) -> str:
    if value not in TASK_SETS:
        raise ValueError("an attempt's task set is required, potential, practice, or parent_check")
    return value


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
