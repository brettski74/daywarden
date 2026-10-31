"""Child-facing task pages.

The page resumes an in-progress attempt instead of opening a second one.
Giving up abandons that attempt when the selection rules allow it, and
otherwise leaves the attempt in progress and says this task has to be
finished. ``parent_check`` is not a page the child can open, and nothing
on these pages records a pass.
"""

from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import quote, unquote

from policy.engine import classify_client
from policy.hierarchy import Policy
from policy.report import PageResponse, _document, _e, _response
from policy.selection import (
    chosen_task_url,
    entry_path,
    may_abandon,
    may_open,
    task_name_from_path,
    task_page_url,
)
from policy.tasks import ABANDONED, AttemptStore, household_day

NOTHING = "There is nothing to revise right now."
NOTHING_ELSE = "There is nothing else available right now."
MUST_FINISH = "This task has to be finished before another one."
VISIT_COOKIE = "task_visit"


def respond_task(
    policy: Policy,
    store: AttemptStore,
    *,
    method: str,
    path: str,
    client_ip: str,
    cookie: str | None,
    now: datetime,
) -> PageResponse:
    """Open a task, give it up, or say there is nothing to revise."""
    client = classify_client(policy, client_ip)
    today = household_day(now)
    revision = policy.revision_task
    entry = "/tasks/next" if not revision else entry_path(revision)
    name = task_name_from_path(path, entry)
    if name is None:
        return _send_to_choice(policy, store, client, today)
    task = policy.task(name)
    rows = store.attempts(client)
    if task is None or not may_open(policy.tasks, name, client, today, rows):
        page = _send_to_choice(policy, store, client, today)
        if task is not None and revision and page.status == 302:
            target = task_page_url(revision, task.name)
            if _location(page) == target:
                return _page(NOTHING)
        return page
    if method.upper() == "POST":
        return _give_up(policy, store, task, client, today, cookie, now, path)
    store.begin(client, task.name, now)
    return _show(task.name, path, stuck=False)


def _send_to_choice(policy, store, client, today) -> PageResponse:
    if not policy.revision_task:
        return _page(NOTHING)
    location = chosen_task_url(policy, client, today, store)
    if location is None:
        return _page(NOTHING)
    return _redirect(location)


def _give_up(policy, store, task, client, today, cookie, now, path: str) -> PageResponse:
    rows = store.attempts(client)
    if not may_abandon(task, policy.tasks, client, today, rows):
        current = store.begin(client, task.name, now)
        return _show(task.name, path, stuck=True)
    current = store.in_progress(client, task.name)
    if current is None:
        current = store.begin(client, task.name, now)
    store.finish(current.id, ABANDONED, now, detail=current.detail)
    visit = _read_visit(cookie) | {task.name}
    location = None
    if policy.revision_task:
        location = chosen_task_url(
            policy,
            client,
            today,
            store,
            exclude=frozenset(visit),
            reopen_required=True,
            leaving=task.name,
        )
    header = _visit_cookie(visit)
    if location is None:
        return _page(NOTHING_ELSE, extra=(("set-cookie", header),))
    return _redirect(location, extra=(("set-cookie", header),))


def _show(name: str, action: str, *, stuck: bool) -> PageResponse:
    note = f"<p>{_e(MUST_FINISH)}</p>\n" if stuck else ""
    form = (
        f'<form method="post" action="{_e(action)}">\n'
        '<button type="submit">Try a different task</button>\n'
        "</form>"
    )
    return _page(f"<h1>{_e(name)}</h1>\n<p>This is a revision task.</p>\n{note}{form}")


def _page(body: str, extra: tuple[tuple[str, str], ...] = ()) -> PageResponse:
    if body in {NOTHING, NOTHING_ELSE, MUST_FINISH}:
        body = f"<h1>Revision</h1>\n<p>{_e(body)}</p>"
    return _response(200, _document(body, "Revision"), extra)


def _redirect(location: str, extra: tuple[tuple[str, str], ...] = ()) -> PageResponse:
    return _response(302, "", (("location", location), *extra))


def _location(page: PageResponse) -> str | None:
    for name, value in page.headers:
        if name == "location":
            return value
    return None


def _read_visit(cookie: str | None) -> frozenset[str]:
    if not cookie:
        return frozenset()
    raw = None
    for part in cookie.split(";"):
        text = part.strip()
        if text.startswith(VISIT_COOKIE + "="):
            raw = text.split("=", 1)[1]
            break
    if not raw:
        return frozenset()
    try:
        loaded = json.loads(unquote(raw))
    except (ValueError, json.JSONDecodeError):
        return frozenset()
    if not isinstance(loaded, list):
        return frozenset()
    return frozenset(item for item in loaded if isinstance(item, str) and item.strip())


def _visit_cookie(names: frozenset[str]) -> str:
    payload = quote(json.dumps(sorted(names), separators=(",", ":")), safe="")
    return f"{VISIT_COOKIE}={payload}; HttpOnly; SameSite=Lax; Path=/"
