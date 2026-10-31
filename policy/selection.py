"""Pick the revision task a client group faces, and the URL it is sent to.

The pool is whatever S003.1 calls eligible, except ``parent_check``, which
the child never sees. When any of those tasks is required, the pool is only
the required ones. Inside the pool, a task that has never been passed comes
before one that has, and the oldest pass comes next. Equal candidates are
ordered by name and then rotated, so the order of requests does not leave
one of them at the back forever.

Giving up is allowed on a task that is not required. It is allowed on a
required task only when another required task is eligible. The next page
leaves out tasks already abandoned in this visit. When that would leave no
required task, and a required task is still eligible, he is sent back to a
required task other than the one he just left.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from urllib.parse import quote, unquote, urlsplit

from policy.hierarchy import Policy
from policy.tasks import (
    PARENT_CHECK,
    PASS,
    Attempt,
    AttemptStore,
    Task,
    household_day,
    is_eligible,
    is_required,
)

_TURNS = """
CREATE TABLE IF NOT EXISTS task_turns (
    client_group TEXT PRIMARY KEY,
    turn INTEGER NOT NULL
);
"""


def task_origin(revision_task: str) -> str:
    """Return ``scheme://host`` for the household task site."""
    parts = urlsplit(revision_task)
    return f"{parts.scheme}://{parts.netloc}"


def entry_path(revision_task: str) -> str:
    """Return the path of the household ``revision_task`` URL."""
    path = urlsplit(revision_task).path
    return path if path else "/"


def task_page_path(revision_task: str, name: str) -> str:
    """Return the path of one task on the task site.

    The household entry path is reserved for the picker. A task whose
    ordinary path would be that entry is served under ``/tasks/work/``.
    """
    path = "/tasks/" + quote(name, safe="")
    if path == entry_path(revision_task):
        return "/tasks/work/" + quote(name, safe="")
    return path


def task_page_url(revision_task: str, name: str) -> str:
    """Return the absolute URL of one task on the task site."""
    return task_origin(revision_task) + task_page_path(revision_task, name)


def same_task_site(url: str, revision_task: str) -> bool:
    """Return whether url is on the host named by ``revision_task``."""
    left = urlsplit(url)
    right = urlsplit(revision_task)
    if left.scheme.lower() not in {"http", "https"}:
        return False
    return (
        left.scheme.lower() == right.scheme.lower()
        and (left.hostname or "").lower() == (right.hostname or "").lower()
        and left.port == right.port
    )


def task_name_from_path(path: str, entry: str) -> str | None:
    """Return the task name in a task-site path, or None for the picker entry."""
    if path == entry:
        return None
    for prefix in ("/tasks/work/", "/tasks/"):
        if path.startswith(prefix):
            name = unquote(path[len(prefix) :])
            if name and "/" not in name:
                return name
            return None
    return None


def may_open(
    tasks: Sequence[Task],
    name: str,
    client_group: str,
    today: date,
    attempts: Sequence[Attempt],
) -> bool:
    """Return whether this client group may be shown this task today.

    ``parent_check`` is never shown. A task that is not eligible is not
    shown. While any required task is eligible, an optional task is not shown.
    """
    task = next((item for item in tasks if item.name == name), None)
    if task is None or task.type == PARENT_CHECK:
        return False
    if not is_eligible(task, client_group, today, attempts):
        return False
    if _any_required(tasks, client_group, today, attempts):
        return is_required(task, client_group, today, attempts)
    return True


def may_abandon(
    task: Task,
    tasks: Sequence[Task],
    client_group: str,
    today: date,
    attempts: Sequence[Attempt],
) -> bool:
    """Return whether this attempt may be marked abandoned.

    A task that is not required may be put down. A required task may be put
    down only when another required task is eligible. ``parent_check`` is not
    a child task, so it is not abandoned from a child page. Spelling practice
    uses this same answer before it leaves a scored attempt.
    """
    if task.type == PARENT_CHECK:
        return False
    if not is_required(task, client_group, today, attempts):
        return True
    return any(
        other.name != task.name and is_required(other, client_group, today, attempts)
        for other in tasks
        if other.type != PARENT_CHECK
    )


def choose_task(
    tasks: Sequence[Task],
    client_group: str,
    today: date,
    attempts: Sequence[Attempt],
    *,
    exclude: frozenset[str] = frozenset(),
    turn: int = 0,
    reopen_required: bool = False,
    leaving: str | None = None,
) -> tuple[Task | None, int]:
    """Return the task to open, and how many candidates tied for it.

    ``exclude`` holds tasks already abandoned in this visit. When that leaves
    nothing, and ``reopen_required`` is set while a required task remains,
    the next task is a required one other than ``leaving`` when one exists.
    The tie count is zero when nothing is chosen. A tie of one does not rotate.
    """
    eligible = [
        task
        for task in tasks
        if task.type != PARENT_CHECK and is_eligible(task, client_group, today, attempts)
    ]
    required = [task for task in eligible if is_required(task, client_group, today, attempts)]
    base = required if required else eligible
    narrowed = [task for task in base if task.name not in exclude]
    if narrowed:
        pool = narrowed
    elif reopen_required and required:
        others = [task for task in required if task.name != leaving]
        pool = others or list(required)
    else:
        return None, 0
    ranked = sorted(pool, key=lambda task: (_rank(task, client_group, attempts), task.name))
    best = _rank(ranked[0], client_group, attempts)
    tied = [task for task in ranked if _rank(task, client_group, attempts) == best]
    if turn < 0:
        turn = 0
    return tied[turn % len(tied)], len(tied)


def chosen_task_url(
    policy: Policy,
    client_group: str,
    today: date,
    store: AttemptStore,
    *,
    exclude: frozenset[str] = frozenset(),
    reopen_required: bool = False,
    leaving: str | None = None,
) -> str | None:
    """Return the task URL to open, advancing the rotation when the pick was tied.

    None means nothing in the pool is eligible. The caller then shows the
    plain-language page instead of redirecting.
    """
    if not policy.revision_task:
        return None
    task, ties = choose_task(
        policy.tasks,
        client_group,
        today,
        store.attempts(client_group),
        exclude=exclude,
        turn=read_turn(store, client_group),
        reopen_required=reopen_required,
        leaving=leaving,
    )
    if task is None:
        return None
    if ties > 1:
        advance_turn(store, client_group)
    return task_page_url(policy.revision_task, task.name)


def apply_task_selection(
    decision: dict,
    policy: Policy,
    url: str,
    client_group: str,
    at: datetime,
    store: AttemptStore,
) -> dict:
    """Point a revision redirect at the chosen task, and keep him off the wrong one.

    A task he may open is allowed through, including when the rule said
    ``revision_task``, so the follow-up request does not redirect in a circle.
    An allow for the picker entry, or for a task he may not open, becomes a
    redirect. When nothing is eligible, a request that is already the
    household ``revision_task`` URL is allowed so that page can say so.
    """
    revision = policy.revision_task
    if not revision:
        return decision
    action = decision.get("action")
    today = household_day(at)
    on_site = same_task_site(url, revision)
    entry = entry_path(revision)
    path = urlsplit(url).path or "/"
    name = task_name_from_path(path, entry) if on_site else None
    if name is not None and may_open(policy.tasks, name, client_group, today, store.attempts(client_group)):
        if action == "allow" or (action == "redirect" and decision.get("location") == revision):
            return {"action": "allow"} if action == "redirect" else decision
        return decision
    if action == "redirect" and decision.get("location") == revision:
        picked, ties = _preview(policy, client_group, today, store)
        if picked is None:
            if on_site and path == entry:
                return {"action": "allow"}
            return decision
        if on_site and path == urlsplit(picked).path:
            return {"action": "allow"}
        _use_turn(store, client_group, ties)
        return {**decision, "location": picked}
    if action != "allow" or not on_site or (name is None and path != entry):
        return decision
    picked, ties = _preview(policy, client_group, today, store)
    if picked is None:
        if name is None:
            return decision
        return {"action": "redirect", "status": 302, "location": revision}
    if name is not None and picked == task_page_url(revision, name):
        return decision
    _use_turn(store, client_group, ties)
    return {"action": "redirect", "status": 302, "location": picked}


def _preview(
    policy: Policy,
    client_group: str,
    today: date,
    store: AttemptStore,
) -> tuple[str | None, int]:
    if not policy.revision_task:
        return None, 0
    task, ties = choose_task(
        policy.tasks,
        client_group,
        today,
        store.attempts(client_group),
        turn=read_turn(store, client_group),
    )
    if task is None:
        return None, 0
    return task_page_url(policy.revision_task, task.name), ties


def _use_turn(store: AttemptStore, client_group: str, ties: int) -> None:
    if ties > 1:
        advance_turn(store, client_group)


def read_turn(store: AttemptStore, client_group: str) -> int:
    """Return how many tied picks this client group has already taken."""
    _ensure_turns(store.connection)
    row = store.connection.execute(
        "SELECT turn FROM task_turns WHERE client_group = ?",
        (client_group,),
    ).fetchone()
    return 0 if row is None else int(row[0])


def advance_turn(store: AttemptStore, client_group: str) -> None:
    """Record that a tied pick was used, so the next tie moves on."""
    _ensure_turns(store.connection)
    with store.connection:
        row = store.connection.execute(
            "SELECT turn FROM task_turns WHERE client_group = ?",
            (client_group,),
        ).fetchone()
        nxt = 1 if row is None else int(row[0]) + 1
        store.connection.execute(
            "INSERT INTO task_turns (client_group, turn) VALUES (?, ?) "
            "ON CONFLICT(client_group) DO UPDATE SET turn = excluded.turn",
            (client_group, nxt),
        )


def _any_required(
    tasks: Sequence[Task],
    client_group: str,
    today: date,
    attempts: Sequence[Attempt],
) -> bool:
    return any(
        task.type != PARENT_CHECK and is_required(task, client_group, today, attempts) for task in tasks
    )


def _rank(task: Task, client_group: str, attempts: Sequence[Attempt]) -> tuple[int, str]:
    """Sort never-passed tasks first, then the oldest pass."""
    finished = _last_pass_finished(task.name, client_group, attempts)
    if finished is None:
        return (0, "")
    return (1, finished.isoformat())


def _last_pass_finished(
    task_name: str,
    client_group: str,
    attempts: Sequence[Attempt],
) -> datetime | None:
    found: Attempt | None = None
    for attempt in attempts:
        if attempt.task != task_name or attempt.client_group != client_group:
            continue
        if attempt.outcome != PASS or attempt.finished_at is None:
            continue
        if found is None or (attempt.finished_at, attempt.id) > (found.finished_at, found.id):
            found = attempt
    return None if found is None else found.finished_at


def _ensure_turns(connection) -> None:
    connection.executescript(_TURNS)
