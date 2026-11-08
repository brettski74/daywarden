"""Parent review of revision attempts.

The page lists one client group's attempts, newest first, and opens one
attempt to show the answers and results that were stored. Each attempt says
which task set it started in. Above the list is where the household day
stands: today's score, the required tasks still outstanding, the potential
tasks still available, and the potential passes waiting on the required
ones. A parent records a ``parent_check`` pass from this page. The child has
no request that does that, and the page itself is the parent session from
S007.1.

Quiz stories add type-specific detail later. This page shows the stored
record, and a list of answers when the record has one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from policy.accounts import Accounts
from policy.report import (
    PageResponse,
    _closed_page,
    _document,
    _e,
    _option,
    _response,
    _sign_in_page,
    format_day,
    format_duration,
    open_parent,
)
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
    household_day,
)

QUIZ_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Revision</title>
</head>
<body>
<h1>Revision</h1>
<p>This is a revision task.</p>
</body>
</html>
"""

_LIST_KEYS = ("client",)
_SET_LABELS = {
    REQUIRED: "Required",
    POTENTIAL: "Potential",
    PRACTICE: "Practice",
    PARENT_CHECK: "Parent check",
}
UNFINISHED_LABEL = "Unfinished"


def respond_attempts(
    accounts: Accounts,
    *,
    method: str,
    query: Mapping[str, str],
    cookie: str | None,
    form: Mapping[str, str],
    now: datetime,
    attempts: AttemptStore | None = None,
    clients: Sequence[str] = (),
    tasks: Sequence[Task] = (),
) -> PageResponse:
    """Return the attempt list, the sign-in form, or the closed page."""
    denied = open_parent(
        accounts,
        method=method,
        query=query,
        cookie=cookie,
        form=form,
        now=now,
        keys=_LIST_KEYS,
        title="Attempts",
        home="/attempts",
    )
    if denied is not None:
        return denied
    store = attempts if attempts is not None else AttemptStore(connection=accounts.connection)
    return _response(200, _attempts_body(store, clients, query.get("client", ""), now=now, tasks=tasks))


def respond_attempt(
    accounts: Accounts,
    *,
    attempt_id: str,
    method: str,
    query: Mapping[str, str],
    cookie: str | None,
    form: Mapping[str, str],
    now: datetime,
    attempts: AttemptStore | None = None,
) -> PageResponse:
    """Return one attempt, the sign-in form, or the closed page.

    A missing session, an idle session, and a session past its lifetime all
    return the sign-in form and none of the stored answers.
    """
    home = "/attempts/" + attempt_id
    denied = open_parent(
        accounts,
        method=method,
        query=query,
        cookie=cookie,
        form=form,
        now=now,
        keys=(),
        title="Attempt",
        home=home,
    )
    if denied is not None:
        return denied
    store = attempts if attempts is not None else AttemptStore(connection=accounts.connection)
    found = _stored(store, attempt_id)
    if found is None:
        body = _document(
            "<h1>Attempt</h1>\n<p>That attempt is not stored.</p>\n<p><a href=\"/attempts\">Attempts</a></p>",
            "Attempt",
        )
        return _response(404, body)
    return _response(200, _attempt_body(found, household_day(now)))


def respond_parent_check(
    accounts: Accounts,
    *,
    cookie: str | None,
    form: Mapping[str, str],
    now: datetime,
    tasks: tuple[Task, ...] = (),
    attempts: AttemptStore | None = None,
    clients: Sequence[str] = (),
) -> PageResponse:
    """Record a parent_check pass when the session is valid.

    A missing or expired session returns the sign-in form and writes nothing.
    The pass is an attempt row, so it counts toward the client group's
    revision total for the household day and appears in that group's list.
    The child has no page that calls this.
    """
    if accounts.count() == 0:
        return _response(403, _closed_page("Attempts"))
    if accounts.accept(cookie, now) is None:
        return _response(
            200,
            _sign_in_page({}, rejected=False, keys=(), title="Attempts", home="/attempts"),
        )
    store = attempts if attempts is not None else AttemptStore(connection=accounts.connection)
    client = form.get("client", "")
    group = client.strip() if isinstance(client, str) else ""
    notice = ""
    if group:
        if clients and group not in clients:
            notice = "<p>That client group is not in the household.</p>\n"
            group = ""
        else:
            store.record(
                group,
                _parent_task(tasks, group),
                PASS,
                now,
                detail={"recorded_by": "parent"},
                task_set=PARENT_CHECK,
            )
            accounts.record_parent_check(group, now)
    return _response(200, _attempts_body(store, clients, group, notice=notice, now=now, tasks=tasks))


def https_only_page() -> str:
    """Return the refusal for a parent page that did not arrive over HTTPS."""
    return _document(
        "<h1>Parent pages</h1>\n<p>Open this page over HTTPS.</p>",
        "Parent pages",
    )


def _parent_task(tasks: tuple[Task, ...], client_group: str) -> str:
    """Return a parent_check task assigned to this group, or the type name."""
    for task in tasks:
        if task.type == PARENT_CHECK and client_group in task.groups:
            return task.name
    return PARENT_CHECK


def _attempts_body(
    attempts: AttemptStore,
    clients: Sequence[str],
    client: str,
    *,
    now: datetime,
    tasks: Sequence[Task] = (),
    notice: str = "",
) -> str:
    parts = ["<h1>Attempts</h1>", _client_form(clients, client), notice]
    chosen = client.strip()
    if not chosen:
        parts.append("<p>Choose a client group.</p>")
    elif clients and chosen not in clients:
        parts.append("<p>That client group is not in the household.</p>")
    else:
        today = household_day(now)
        rows = attempts.recent(chosen)
        parts.append(f"<h2>{_e(chosen)}</h2>")
        parts.append(_summary(attempts.score(tasks, chosen, today)))
        parts.append(_attempt_table(rows, today))
    parts.append("<h2>Record a parent check</h2>")
    parts.append(_check_form(clients))
    return _document("\n".join(part for part in parts if part), "Attempts")


def _summary(score: Score) -> str:
    """Return where today stands: the score and the tasks behind it."""
    rows = [
        ("Today's score", str(score.points)),
        ("Required tasks outstanding", _names(task.name for task in score.sets.required)),
        ("Potential tasks available", _names(task.name for task in score.sets.potential)),
        ("Potential passes waiting on required tasks", _names(score.waiting)),
    ]
    items = "\n".join(f"<dt>{_e(label)}</dt><dd>{_e(value)}</dd>" for label, value in rows)
    return f'<dl id="today">\n{items}\n</dl>'


def _names(names) -> str:
    listed = list(names)
    return ", ".join(listed) if listed else "none"


def _attempt_table(rows: Sequence[Attempt], today) -> str:
    if not rows:
        return "<p>No attempts yet.</p>"
    body = "\n".join(_attempt_row(attempt, today) for attempt in rows)
    return (
        "<table>\n"
        "<thead>\n"
        "<tr><th>Task</th><th>Set</th><th>Started</th><th>Finished</th><th>Outcome</th><th>Duration</th></tr>\n"
        "</thead>\n"
        f"<tbody>\n{body}\n</tbody>\n"
        "</table>"
    )


def _attempt_row(attempt: Attempt, today) -> str:
    name = _e(attempt.task)
    return (
        "<tr>"
        f'<td><a href="/attempts/{attempt.id}">{name}</a></td>'
        f"<td>{_e(set_label(attempt))}</td>"
        f"<td>{_e(_local(attempt.started_at))}</td>"
        f"<td>{_e(_finished(attempt, today))}</td>"
        f"<td>{_e(outcome_label(attempt, today))}</td>"
        f"<td>{_e(_duration(attempt, today))}</td>"
        "</tr>"
    )


def set_label(attempt: Attempt) -> str:
    """Return Required, Potential, Practice, or Parent check."""
    return _SET_LABELS.get(attempt.task_set, attempt.task_set)


def outcome_label(attempt: Attempt, today) -> str:
    """Return the stored outcome, or Unfinished for an attempt left open on an earlier household day."""
    if attempt.left_open(today):
        return UNFINISHED_LABEL
    return attempt.outcome


def _attempt_body(attempt: Attempt, today) -> str:
    finished = _finished(attempt, today)
    back = f"/attempts?client={_e(attempt.client_group)}"
    parts = [
        f"<h1>{_e(attempt.task)}</h1>",
        f"<p><a href=\"{back}\">Attempts</a></p>",
        "<dl>",
        f"<dt>Client group</dt><dd>{_e(attempt.client_group)}</dd>",
        f"<dt>Set</dt><dd>{_e(set_label(attempt))}</dd>",
        f"<dt>Started</dt><dd>{_e(_local(attempt.started_at))}</dd>",
        f"<dt>Finished</dt><dd>{_e(finished)}</dd>",
        f"<dt>Outcome</dt><dd>{_e(outcome_label(attempt, today))}</dd>",
        f"<dt>Duration</dt><dd>{_e(_duration(attempt, today))}</dd>",
        "</dl>",
        _reopened(attempt),
        _answers(attempt.detail),
        _record(attempt.detail),
    ]
    return _document("\n".join(part for part in parts if part), "Attempt")


def _reopened(attempt: Attempt) -> str:
    """Return each time he gave this attempt up and came back to it."""
    if not attempt.reopened:
        return ""
    rows = []
    for event in attempt.reopened:
        gave_up = _event_time(event.get("gave_up"))
        came_back = _event_time(event.get("came_back"))
        rows.append(f"<tr><td>{_e(gave_up)}</td><td>{_e(came_back)}</td></tr>")
    body = "\n".join(rows)
    return (
        "<h2>Given up and carried on</h2>\n"
        "<table>\n<thead>\n<tr><th>Gave up</th><th>Came back</th></tr>\n</thead>\n"
        f"<tbody>\n{body}\n</tbody>\n</table>"
    )


def _event_time(value: object) -> str:
    if not isinstance(value, str):
        return ""
    try:
        return _local(datetime.fromisoformat(value))
    except ValueError:
        return value


def _answers(detail: Mapping) -> str:
    answers = detail.get("answers")
    if not isinstance(answers, list):
        return ""
    if not answers:
        return "<h2>Answers</h2>\n<p>No answers were stored.</p>"
    items = "\n".join(f"<li>{_value(answer)}</li>" for answer in answers)
    return f"<h2>Answers</h2>\n<ol>\n{items}\n</ol>"


def _record(detail: Mapping) -> str:
    shown = {key: value for key, value in detail.items() if not (key == "answers" and isinstance(value, list))}
    if not shown:
        return ""
    return "<h2>Record</h2>\n" + _fields(shown)


def _fields(detail: Mapping) -> str:
    rows = "\n".join(f"<dt>{_e(str(key))}</dt><dd>{_value(value)}</dd>" for key, value in detail.items())
    return f"<dl>\n{rows}\n</dl>"


def _value(value: object) -> str:
    if isinstance(value, str):
        return _e(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _e(str(value))
    if value is None:
        return ""
    if isinstance(value, Mapping):
        return _fields(value)
    if isinstance(value, list):
        if not value:
            return ""
        items = "\n".join(f"<li>{_value(item)}</li>" for item in value)
        return f"<ol>\n{items}\n</ol>"
    return _e(str(value))


def _client_form(clients: Sequence[str], chosen: str) -> str:
    control = _client_control(clients, chosen, "show-client", include_blank=True)
    return (
        '<form method="get" action="/attempts">\n'
        '<label for="show-client">Client group</label>\n'
        f"{control}\n"
        '<button type="submit">Show</button>\n'
        "</form>"
    )


def _check_form(clients: Sequence[str]) -> str:
    control = _client_control(clients, "", "client", include_blank=False)
    return (
        '<form method="post" action="/attempts/parent-check">\n'
        '<label for="client">Client group</label>\n'
        f"{control}\n"
        '<button type="submit">Record a pass</button>\n'
        "</form>"
    )


def _client_control(clients: Sequence[str], chosen: str, control_id: str, *, include_blank: bool) -> str:
    if not clients:
        value = f' value="{_e(chosen)}"' if chosen else ""
        return f'<input id="{control_id}" name="client"{value}>'
    blank = _option("", chosen, "Choose") if include_blank else ""
    options = "\n".join(part for part in (blank, *(_option(name, chosen) for name in clients)) if part)
    return f'<select id="{control_id}" name="client">\n{options}\n</select>'


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
