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

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from policy.accounts import Accounts
from policy.arithmetic import ARITHMETIC, OPERATIONS
from policy.arithmetic_facts import attempt_runs, facts, no_questions
from policy.attempt_trends import listed, no_attempts, overview, period_json, period_of, read_view, trend
from policy.capitalisation_attempt import capitalisation_runs
from policy.child_page import FAVICON_PATH
from policy.fact_figures import operation_of as question_operation
from policy.report import format_day, format_duration, timezone_note
from policy.spelling import data_root
from policy.spelling_report import no_words, offered_tasks, pools_now, read_choices, spelling_runs, this_week_day, words
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
    pairs: Sequence[tuple[str, str]] | None = None,
) -> dict:
    """Return one client group's day so far, its overview, and its attempts over the period, newest first.

    ``pairs`` is the page address's query string, which names the period and
    the filters. Without it, only ``client`` is chosen, over the past month.
    With no group chosen, or one that is not in the household, ``message``
    says so and there is no summary, overview, or list. A Custom period that
    is not real days has the summary but no overview or list, and ``notes``
    says why.
    """
    view, notes = read_view([("client", client if isinstance(client, str) else "")] if pairs is None else pairs)
    chosen = view.client
    period, problems = period_of(view, now)
    notes.extend(problems)
    report: dict = {
        "clients": list(clients),
        "client": chosen,
        "view": view.as_json(),
        "notes": notes,
        "times": timezone_note(timezone),
        **period_json(period, now),
        "message": None,
        "summary": None,
        "overview": None,
        "attempts": None,
    }
    if not chosen:
        report["message"] = "Choose a client group."
    elif clients and chosen not in clients:
        report["message"] = NOT_IN_HOUSEHOLD
    else:
        today = household_day(now)
        report["summary"] = _summary(attempts.score(tasks, chosen, today))
        if period is not None:
            stored = attempts.recent(chosen)
            known = {task.key for task in tasks}
            report["overview"] = overview(stored, view, period, today, known)
            report["attempts"] = [_attempt_row(attempt, today) for attempt in listed(stored, view, period, today)]
    return report


def trend_report(
    attempts: AttemptStore,
    clients: Sequence[str],
    key: TaskKey,
    *,
    now: datetime,
    tasks: Sequence[Task] = (),
    timezone: str | None = None,
    pairs: Sequence[tuple[str, str]] = (),
) -> dict:
    """Return one task's trend for one client group over the period, with the same choices as the attempts page.

    ``message`` says why there is nothing to draw: no group chosen, a group
    not in the household, a Custom period that is not real days, or no
    attempts that pass the filters. A type and name that is not a task, with
    no attempts, is the last of these.
    """
    view, notes = read_view(pairs)
    chosen = view.client
    period, problems = period_of(view, now)
    notes.extend(problems)
    report: dict = {
        "clients": list(clients),
        "client": chosen,
        "view": view.as_json(),
        "notes": notes,
        "times": timezone_note(timezone),
        **period_json(period, now),
        "task": {"type": key.type, "name": key.name, "label": str(key), "in_policy": key in {task.key for task in tasks}},
        "facts": None,
        "message": None,
        "trend": None,
    }
    if not chosen:
        report["message"] = "Choose a client group."
    elif clients and chosen not in clients:
        report["message"] = NOT_IN_HOUSEHOLD
    elif period is None:
        report["message"] = "Fix the period to show the trend."
    else:
        today = household_day(now)
        stored = attempts.attempts(chosen, key)
        found = trend(stored, key, view, period, today, lambda attempt: _attempt_row(attempt, today))
        if key.type == ARITHMETIC:
            report["facts"] = _task_operation(stored, key, tasks)
        if found["points"]:
            report["trend"] = found
        else:
            report["message"] = no_attempts(key, chosen)
    return report


def facts_report(
    attempts: AttemptStore,
    clients: Sequence[str],
    operation: str,
    *,
    now: datetime,
    timezone: str | None = None,
    pairs: Sequence[tuple[str, str]] = (),
) -> dict:
    """Return one operation's arithmetic facts for one client group over the period, with the attempts page's choices.

    ``message`` says why there is nothing to show: no group chosen, a group
    not in the household, an operation the service does not have, a Custom
    period that is not real days, or no questions of that operation. Each
    fact's ``all_time`` figures, and ``slow``, the operation's median
    smoothed time and where the slow boost starts and is full, come from his
    whole record whatever the period and filters.
    """
    view, notes = read_view(pairs)
    chosen = view.client
    period, problems = period_of(view, now)
    notes.extend(problems)
    known = operation in OPERATIONS
    report: dict = {
        "clients": list(clients),
        "client": chosen,
        "view": view.as_json(),
        "notes": notes,
        "times": timezone_note(timezone),
        **period_json(period, now),
        "operation": {"name": operation, "label": OPERATIONS[operation].label if known else operation},
        "operations": [{"name": name, "label": each.label} for name, each in OPERATIONS.items()],
        "message": None,
        "slow": None,
        "facts": None,
    }
    if not known:
        report["message"] = f"{operation} is not an arithmetic operation."
        return report
    if not chosen:
        report["message"] = "Choose a client group."
        return report
    if clients and chosen not in clients:
        report["message"] = NOT_IN_HOUSEHOLD
        return report
    all_time = attempts.facts.book(chosen, operation)
    report["slow"] = all_time.slow.as_json()
    if period is None:
        report["message"] = "Fix the period to show the facts."
        return report
    found = facts(
        attempts.attempts(chosen),
        operation,
        view,
        period,
        household_day(now),
        lambda attempt: _local(attempt.started_at),
        all_time,
    )
    if found["facts"]:
        report["facts"] = found
    else:
        report["message"] = no_questions(operation, chosen)
    return report


def words_report(
    attempts: AttemptStore,
    clients: Sequence[str],
    *,
    now: datetime,
    tasks: Sequence[Task] = (),
    timezone: str | None = None,
    pairs: Sequence[tuple[str, str]] = (),
    root: Path | None = None,
) -> dict:
    """Return one client group's spelling words over the period, with the attempts page's choices and the Task and Pool filters.

    ``tasks_offered`` is the Task filter's choices, and ``choices`` the
    chosen tasks and pools. ``this_week`` is the Custom period that This
    week's words chooses. ``message`` says why there is nothing to show: no
    group chosen, a group not in the household, a Custom period that is not
    real days, or no words. Each word's Run and Weight are all-time, from
    ``bin/word-stats``'s figures, whatever the period and filters. ``root`` is
    the data directory the pools are read from.
    """
    view, notes = read_view(pairs)
    choices, more = read_choices(pairs)
    notes.extend(more)
    chosen = view.client
    period, problems = period_of(view, now)
    notes.extend(problems)
    report: dict = {
        "clients": list(clients),
        "client": chosen,
        "view": view.as_json(),
        "notes": notes,
        "times": timezone_note(timezone),
        **period_json(period, now),
        "tasks_offered": [],
        "choices": choices.as_json([]),
        "this_week": None,
        "message": None,
        "words": None,
    }
    if not chosen:
        report["message"] = "Choose a client group."
        return report
    if clients and chosen not in clients:
        report["message"] = NOT_IN_HOUSEHOLD
        return report
    today = household_day(now)
    stored = attempts.attempts(chosen)
    # Without a real period, only the policy's tasks are offered.
    offered = offered_tasks(tasks, chosen, stored if period is not None else (), view, period, today)
    names = [each["name"] for each in offered]
    if choices.tasks is not None:
        unknown = [name for name in choices.tasks if name not in names]
        notes.extend(f"{name} is not a spelling task here, so it is left out." for name in unknown)
        picked = [name for name in names if name in choices.tasks]
    else:
        picked = names
    report["tasks_offered"] = offered
    report["choices"] = {"task": picked, "pool": list(choices.pools)}
    held = pools_now(tasks, picked, root or data_root())
    report["this_week"] = {"from": this_week_day(stored, picked, held, today).isoformat(), "to": today.isoformat()}
    if period is None:
        report["message"] = "Fix the period to show the words."
        return report
    found = words(
        stored, view, period, today, picked, held, choices.pools, attempts.words.figures(chosen), lambda attempt: _local(attempt.started_at)
    )
    if found["words"]:
        report["words"] = found
    else:
        report["message"] = no_words(chosen)
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
        "arithmetic": attempt_runs(found, _event_time),
        "capitalisation": capitalisation_runs(found, _event_time),
        "spelling": spelling_runs(found, _event_time),
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


def _task_operation(stored: Sequence[Attempt], key: TaskKey, tasks: Sequence[Task]) -> str | None:
    """Return the operation an arithmetic task asks: its latest attempt's, or else the policy's."""
    for attempt in reversed(stored):
        detail = attempt.detail if isinstance(attempt.detail, Mapping) else {}
        named = question_operation({}, detail.get("settings"))
        if named is not None:
            return named
    for task in tasks:
        if task.key == key:
            try:
                body = json.loads(task.body)
            except ValueError:
                return None
            named = body.get("operation") if isinstance(body, Mapping) else None
            return named if named in OPERATIONS else None
    return None


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
