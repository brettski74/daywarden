"""Child-facing task pages.

The page resumes an in-progress attempt instead of opening a second one.
Giving up abandons that attempt when the selection rules allow it, and
otherwise leaves the attempt in progress and says this task has to be
finished. ``parent_check`` is not a page the child can open, and nothing
on these pages records a pass except a quiz that reaches its target.
An ``arithmetic`` task is the quiz in ``policy.arithmetic_page``, a
``parts_of_speech`` task is the one in ``policy.parts_of_speech_page``, a
``skip_counting`` task is the one in ``policy.skip_counting_page``, and a
``spelling`` task is the one in ``policy.spelling_page``. A quiz's page
load, questions, and answers are posts to the task's own URL with ``?do=``.
A quiz with its own audio serves it under ``<task URL>/audio/``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote

from policy import arithmetic_page, parts_of_speech_page, skip_counting_page, spelling_page
from policy.arithmetic import ARITHMETIC
from policy.engine import classify_client
from policy.hierarchy import Policy
from policy.parts_of_speech import PARTS_OF_SPEECH
from policy.quiz_page import Back, reload
from policy.report import PageResponse, _document, _e, _response
from policy.selection import (
    PICKER_PATH,
    chosen_task_url,
    may_abandon,
    may_open,
    task_media_from_path,
    task_name_from_path,
    task_page_url,
)
from policy.skip_counting import SKIP_COUNTING
from policy.sounds import SoundSets
from policy.spelling import SPELLING
from policy.tasks import ABANDONED, Attempt, AttemptStore, Task, household_day

NOTHING = "There is nothing to revise right now."
NOTHING_ELSE = "There is nothing else available right now."
MUST_FINISH = "This task has to be finished before another one."
VISIT_COOKIE = "task_visit"

_QUIZZES = {
    ARITHMETIC: arithmetic_page,
    PARTS_OF_SPEECH: parts_of_speech_page,
    SKIP_COUNTING: skip_counting_page,
    SPELLING: spelling_page,
}


def respond_task(
    policy: Policy,
    store: AttemptStore,
    *,
    method: str,
    path: str,
    client_ip: str,
    cookie: str | None,
    now: datetime,
    query: Mapping[str, str] | None = None,
    body: bytes = b"",
    sounds: SoundSets | None = None,
    back: Back | None = None,
) -> PageResponse:
    """Open a task, give it up, or say there is nothing to revise.

    A post with ``do`` in the query is a quiz request, answered with JSON.
    Any other post is "Try a different task". ``back`` is asked, after a
    pass, for the page this computer was sent away from.
    """
    client = classify_client(policy, client_ip)
    today = household_day(now)
    name = task_name_from_path(path, PICKER_PATH)
    action = (query or {}).get("do")
    if name is None:
        return _send_to_choice(policy, store, client, today)
    task = policy.task(name)
    rows = store.attempts(client)
    if task is None or not may_open(policy.tasks, name, client, today, rows):
        if method.upper() == "POST" and action is not None:
            return reload()
        page = _send_to_choice(policy, store, client, today)
        if task is not None and page.status == 302:
            target = task_page_url(policy, task.name)
            if _location(page) == target:
                return _page(NOTHING)
        return page
    quiz = _QUIZZES.get(task.type)
    if method.upper() == "POST":
        if action is not None and quiz is not None:
            return quiz.respond_api(
                policy, store, task, client, action=action, body=body, now=now, sounds=sounds, back=back
            )
        return _give_up(policy, store, task, client, today, cookie, now, path, back)
    attempt = store.begin(client, task.name, now)
    return _show(policy, store, task, attempt, path, now, stuck=False)


def task_media(policy: Policy, store: AttemptStore, *, path: str, client_ip: str, now: datetime) -> Path | None:
    """Return the audio file a ``/tasks/<name>/audio/<file>`` path names, or None.

    Only a task this client group may open now serves its audio.
    """
    found = task_media_from_path(path)
    if found is None:
        return None
    name, file_name = found
    task = policy.task(name)
    quiz = None if task is None else _QUIZZES.get(task.type)
    if quiz is None or not hasattr(quiz, "media"):
        return None
    client = classify_client(policy, client_ip)
    if not may_open(policy.tasks, name, client, household_day(now), store.attempts(client)):
        return None
    return quiz.media(task, file_name)


def _send_to_choice(policy, store, client, today) -> PageResponse:
    location = chosen_task_url(policy, client, today, store)
    if location is None:
        return _page(NOTHING)
    return _redirect(location)


def _give_up(policy, store, task, client, today, cookie, now, path: str, back: Back | None) -> PageResponse:
    rows = store.attempts(client)
    if not may_abandon(task, policy.tasks, client, today, rows):
        current = store.begin(client, task.name, now)
        return _show(policy, store, task, current, path, now, stuck=True, back=back)
    current = store.in_progress(client, task.name)
    if current is None:
        current = store.begin(client, task.name, now)
    detail, outcome = current.detail, ABANDONED
    quiz = _QUIZZES.get(task.type)
    if quiz is not None:
        detail, outcome = quiz.settle(task, detail, now)
    store.finish(current.id, outcome, now, detail=detail)
    visit = _read_visit(cookie) | {task.name}
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
    if quiz is not None and hasattr(quiz, "give_up_page"):
        review = quiz.give_up_page(detail, location, NOTHING_ELSE)
        if review is not None:
            return PageResponse(review.status, review.body, (*review.headers, ("set-cookie", header)))
    if location is None:
        return _page(NOTHING_ELSE, extra=(("set-cookie", header),))
    return _redirect(location, extra=(("set-cookie", header),))


def _show(
    policy: Policy,
    store: AttemptStore,
    task: Task,
    attempt: Attempt,
    action: str,
    now: datetime,
    *,
    stuck: bool,
    back: Back | None = None,
) -> PageResponse:
    quiz = _QUIZZES.get(task.type)
    if quiz is not None:
        note = MUST_FINISH if stuck else ""
        return quiz.show(
            store, task, attempt, path=action, now=now, policy=policy, note=note, record=stuck, back=back
        )
    note = f"<p>{_e(MUST_FINISH)}</p>\n" if stuck else ""
    form = (
        f'<form method="post" action="{_e(action)}">\n'
        '<button type="submit">Try a different task</button>\n'
        "</form>"
    )
    return _page(f"<h1>{_e(task.name)}</h1>\n<p>This is a revision task.</p>\n{note}{form}")


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
