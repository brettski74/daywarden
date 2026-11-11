"""Parent review of revision attempts.

The review lists one client group's attempts, newest first, and opens one
attempt to show the answers and results that were stored. Each attempt says
its task's type and name, as stored with it, and which task set it started
in. A task named in the summary is written ``type/name``. Above the list is where the household day
stands: today's score, the required tasks still outstanding, the potential
tasks still available, and the potential passes waiting on the required
ones. A parent records a ``parent_check`` pass from the portal. The child has
no request that does that.

These functions assemble the review as plain data for the parent portal.
Times and durations are already formatted. An attempt's answers and stored
record are sent as stored, and the portal page lays them out. The portal
decides who may see them.

Quiz stories add type-specific detail later.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from policy.accounts import Accounts
from policy.child_page import FAVICON_PATH
from policy.report import format_day, format_duration, timezone_note
from policy.tasks import (
    PARENT_CHECK,
    PASS,
    POTENTIAL,
    PRACTICE,
    REQUIRED,
    Attempt,
    AttemptStore,
    Score,
    Task,
    TaskKey,
    household_day,
)

QUIZ_PAGE = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<link rel="icon" type="image/png" href="{FAVICON_PATH}">
<title>Revision</title>
</head>
<body>
<h1>Revision</h1>
<p>This is a revision task.</p>
</body>
</html>
"""

NOT_STORED = "That attempt is not stored."
NOT_IN_HOUSEHOLD = "That client group is not in the household."
_SET_LABELS = {
    REQUIRED: "Required",
    POTENTIAL: "Potential",
    PRACTICE: "Practice",
    PARENT_CHECK: "Parent check",
}
UNFINISHED_LABEL = "Unfinished"


def attempts_report(
    attempts: AttemptStore,
    clients: Sequence[str],
    client: str,
    *,
    now: datetime,
    tasks: Sequence[Task] = (),
    timezone: str | None = None,
) -> dict:
    """Return one client group's day so far and its attempts, newest first.

    With no group chosen, or one that is not in the household, ``message``
    says so and there is no summary or list.
    """
    chosen = client.strip() if isinstance(client, str) else ""
    report: dict = {
        "clients": list(clients),
        "client": chosen,
        "times": timezone_note(timezone),
        "message": None,
        "summary": None,
        "attempts": None,
    }
    if not chosen:
        report["message"] = "Choose a client group."
    elif clients and chosen not in clients:
        report["message"] = NOT_IN_HOUSEHOLD
    else:
        today = household_day(now)
        report["summary"] = _summary(attempts.score(tasks, chosen, today))
        report["attempts"] = [_attempt_row(attempt, today) for attempt in attempts.recent(chosen)]
    return report


def attempt_report(
    attempts: AttemptStore,
    attempt_id: str,
    *,
    now: datetime,
    timezone: str | None = None,
) -> dict | None:
    """Return one stored attempt, or None when that number is not stored."""
    found = _stored(attempts, attempt_id)
    if found is None:
        return None
    today = household_day(now)
    return {
        "id": found.id,
        "task": found.task,
        "type": found.task_type,
        "client": found.client_group,
        "times": timezone_note(timezone),
        "summary": [
            {"label": "Client group", "value": found.client_group},
            {"label": "Type", "value": found.task_type},
            {"label": "Set", "value": set_label(found)},
            {"label": "Started", "value": _local(found.started_at)},
            {"label": "Finished", "value": _finished(found, today)},
            {"label": "Outcome", "value": outcome_label(found, today)},
            {"label": "Duration", "value": _duration(found, today)},
        ],
        "reopened": _reopened(found),
        "answers": _answers(found.detail),
        "record": _record(found.detail),
    }


def record_parent_check(
    accounts: Accounts,
    attempts: AttemptStore,
    client: object,
    *,
    now: datetime,
    tasks: Sequence[Task] = (),
    clients: Sequence[str] = (),
) -> str | None:
    """Record a parent_check pass and return None, or return why it was refused.

    The caller has already accepted the parent session. The pass is an attempt
    row, so it counts toward the client group's revision total for the
    household day and appears in that group's list. The child has no page
    that calls this.
    """
    group = client.strip() if isinstance(client, str) else ""
    if not group:
        return "Choose a client group."
    if clients and group not in clients:
        return NOT_IN_HOUSEHOLD
    attempts.record(
        group,
        _parent_task(tasks, group),
        PASS,
        now,
        detail={"recorded_by": "parent"},
        task_set=PARENT_CHECK,
    )
    accounts.record_parent_check(group, now)
    return None


def set_label(attempt: Attempt) -> str:
    """Return Required, Potential, Practice, or Parent check."""
    return _SET_LABELS.get(attempt.task_set, attempt.task_set)


def outcome_label(attempt: Attempt, today) -> str:
    """Return the stored outcome, or Unfinished for an attempt left open on an earlier household day."""
    if attempt.left_open(today):
        return UNFINISHED_LABEL
    return attempt.outcome


def _parent_task(tasks: Sequence[Task], client_group: str) -> TaskKey:
    """Return a parent_check task assigned to this group, or one named for the type."""
    for task in tasks:
        if task.type == PARENT_CHECK and client_group in task.groups:
            return task.key
    return TaskKey(PARENT_CHECK, PARENT_CHECK)


def _summary(score: Score) -> list[dict]:
    """Return where today stands: the score and the tasks behind it."""
    return [
        {"label": "Today's score", "value": str(score.points)},
        {"label": "Required tasks outstanding", "value": _names(str(task.key) for task in score.sets.required)},
        {"label": "Potential tasks available", "value": _names(str(task.key) for task in score.sets.potential)},
        {"label": "Potential passes waiting on required tasks", "value": _names(map(str, score.waiting))},
    ]


def _names(names) -> str:
    listed = list(names)
    return ", ".join(listed) if listed else "none"


def _attempt_row(attempt: Attempt, today) -> dict:
    return {
        "id": attempt.id,
        "task": attempt.task,
        "type": attempt.task_type,
        "set": set_label(attempt),
        "started": _local(attempt.started_at),
        "finished": _finished(attempt, today),
        "outcome": outcome_label(attempt, today),
        "duration": _duration(attempt, today),
    }


def _reopened(attempt: Attempt) -> list[dict]:
    """Return each time he gave this attempt up and came back to it."""
    return [
        {"gave_up": _event_time(event.get("gave_up")), "came_back": _event_time(event.get("came_back"))}
        for event in attempt.reopened
    ]


def _event_time(value: object) -> str:
    if not isinstance(value, str):
        return ""
    try:
        return _local(datetime.fromisoformat(value))
    except ValueError:
        return value


def _answers(detail: Mapping) -> list | None:
    answers = detail.get("answers")
    return answers if isinstance(answers, list) else None


def _record(detail: Mapping) -> dict | None:
    shown = {key: value for key, value in detail.items() if not (key == "answers" and isinstance(value, list))}
    return shown or None


def _stored(attempts: AttemptStore, attempt_id: str) -> Attempt | None:
    try:
        number = int(attempt_id)
    except (TypeError, ValueError):
        return None
    if str(number) != attempt_id or number < 1:
        return None
    return attempts.get(number)


def _local(moment: datetime) -> str:
    """Return a household-local clock time. The offset is dropped, not converted."""
    if moment.tzinfo is not None:
        moment = moment.replace(tzinfo=None)
    moment = moment.replace(microsecond=0)
    clock = moment.strftime("%H:%M:%S") if moment.second else moment.strftime("%H:%M")
    return f"{format_day(moment.date())}, {clock}"


def _finished(attempt: Attempt, today) -> str:
    if attempt.left_open(today):
        return "never finished"
    if attempt.finished_at is None:
        return "still going"
    return _local(attempt.finished_at)


def _duration(attempt: Attempt, today) -> str:
    if attempt.left_open(today):
        return ""
    if attempt.finished_at is None:
        return "still going"
    started = attempt.started_at
    finished = attempt.finished_at
    if started.tzinfo is not None:
        started = started.replace(tzinfo=None)
    if finished.tzinfo is not None:
        finished = finished.replace(tzinfo=None)
    seconds = int((finished - started).total_seconds())
    if seconds < 0:
        seconds = 0
    return format_duration(seconds)
