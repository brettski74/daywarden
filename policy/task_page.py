"""Child-facing task pages.

Any task assigned to the child's client group opens at its own URL, whatever
the task sets say, so a bookmark always works. An attempt is stored with the
set its task was in when it started, and a practice attempt counts for
nothing. ``/tasks/next`` is the picker, which opens an available task, and
``/tasks/choose`` is the selector, which lists them.

Opening a task carries on an attempt started earlier the same household day,
or one given up within the quiz's idle limit. An attempt left from an earlier
day is closed as unfinished, and a new one starts. Giving up abandons the
attempt, unless it is a required attempt on the only required task, and then
goes to the selector. ``parent_check`` is not a page the child can open, and
nothing on these pages records a pass except a quiz that reaches its target.
An ``arithmetic`` task is the quiz in ``policy.arithmetic_page``, a
``parts_of_speech`` task is the one in ``policy.parts_of_speech_page``, a
``skip_counting`` task is the one in ``policy.skip_counting_page``, and a
``spelling`` task is the one in ``policy.spelling_page``. A quiz's page
load, questions, and answers are posts to the task's own URL with ``?do=``.
A quiz with its own audio serves it under ``<task URL>/audio/``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from policy import arithmetic_page, parts_of_speech_page, skip_counting_page, spelling_page
from policy.arithmetic import ARITHMETIC
from policy.engine import classify_client
from policy.hierarchy import Policy
from policy.parts_of_speech import PARTS_OF_SPEECH
from policy.quiz import EXPIRY
from policy.quiz_page import Back, reload
from policy.report import PageResponse, _e, _response
from policy.selection import (
    CHOOSER_PATH,
    PICKER_PATH,
    choices,
    chooser_url,
    configured_task,
    may_abandon,
    picked_task_url,
    picker_url,
    task_media_from_path,
    task_name_from_path,
    task_page_url,
)
from policy.skip_counting import SKIP_COUNTING
from policy.sounds import SoundSets
from policy.spelling import SPELLING
from policy.tasks import ABANDONED, Attempt, AttemptStore, Task, household_day

NOTHING = "There is nothing to revise right now."
MUST_FINISH = "This task has to be finished before another one."
CHOOSE = "Choose a task"

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
    now: datetime,
    query: Mapping[str, str] | None = None,
    body: bytes = b"",
    sounds: SoundSets | None = None,
    back: Back | None = None,
) -> PageResponse:
    """Open a task, give it up, pick one, or list the ones to choose from.

    A post with ``do`` in the query is a quiz request, answered with JSON.
    Any other post to a task is "Try a different task". ``back`` is asked,
    after a pass, for the page this computer was sent away from. A task
    name that is not one of this group's tasks goes to the picker.
    """
    client = classify_client(policy, client_ip)
    today = household_day(now)
    if path == PICKER_PATH:
        return _pick(policy, store, client, now)
    if path == CHOOSER_PATH:
        return _choose(policy, store, client, now)
    name = task_name_from_path(path)
    action = (query or {}).get("do")
    task = None if name is None else configured_task(policy.tasks, name, client)
    if task is None:
        if method.upper() == "POST" and action is not None:
            return reload()
        return _redirect(picker_url(policy))
    quiz = _QUIZZES.get(task.type)
    if method.upper() == "POST":
        if action is not None and quiz is not None:
            return quiz.respond_api(
                policy, store, task, client, action=action, body=body, now=now, sounds=sounds, back=back
            )
        return _give_up(policy, store, task, client, now, path, back)
    sets = store.task_sets(policy.tasks, client, today)
    attempt = store.open(client, task.name, now, task_set=sets.set_of(task.name), reopen_within=EXPIRY)
    return _show(policy, store, task, attempt, path, now, stuck=False)


def task_media(policy: Policy, store: AttemptStore, *, path: str, client_ip: str, now: datetime) -> Path | None:
    """Return the audio file a ``/tasks/<name>/audio/<file>`` path names, or None.

    Any task assigned to this client group serves its audio.
    """
    found = task_media_from_path(path)
    if found is None:
        return None
    name, file_name = found
    task = configured_task(policy.tasks, name, classify_client(policy, client_ip))
    quiz = None if task is None else _QUIZZES.get(task.type)
    if quiz is None or not hasattr(quiz, "media"):
        return None
    return quiz.media(task, file_name)


def _pick(policy: Policy, store: AttemptStore, client: str, now: datetime) -> PageResponse:
    location = picked_task_url(policy, client, household_day(now), store)
    if location is None:
        return _page(NOTHING)
    return _redirect(location)


def _choose(policy: Policy, store: AttemptStore, client: str, now: datetime) -> PageResponse:
    """List the available tasks in picker order. One goes straight to that task."""
    offered = choices(policy, client, household_day(now), store)
    if not offered:
        return _page(NOTHING)
    if len(offered) == 1:
        return _redirect(task_page_url(policy, offered[0].name))
    links = "\n".join(
        f'<li><a class="big" href="{_e(task_page_url(policy, task.name))}">{_e(task.name)}</a></li>'
        for task in offered
    )
    return _page(f'<h1>{_e(CHOOSE)}</h1>\n<ul id="choices">\n{links}\n</ul>')


def _give_up(
    policy: Policy,
    store: AttemptStore,
    task: Task,
    client: str,
    now: datetime,
    path: str,
    back: Back | None,
) -> PageResponse:
    location = chooser_url(policy)
    current = store.in_progress(client, task.name)
    if current is None:
        return _redirect(location)
    sets = store.task_sets(policy.tasks, client, household_day(now))
    if not may_abandon(current, task, sets):
        return _show(policy, store, task, current, path, now, stuck=True, back=back)
    detail, outcome = current.detail, ABANDONED
    quiz = _QUIZZES.get(task.type)
    if quiz is not None:
        detail, outcome = quiz.settle(task, detail, now)
    store.finish(current.id, outcome, now, detail=detail)
    if quiz is not None and hasattr(quiz, "give_up_page"):
        review = quiz.give_up_page(detail, location)
        if review is not None:
            return review
    return _redirect(location)


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


def _page(body: str) -> PageResponse:
    if body in {NOTHING, MUST_FINISH}:
        body = f"<h1>Revision</h1>\n<p>{_e(body)}</p>"
    return _response(200, _child_document(body))


def _redirect(location: str) -> PageResponse:
    return _response(302, "", (("location", location),))


def _child_document(body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>Revision</title>
<style>
body {{ font-family: sans-serif; background: #fbfbf7; color: #222; text-align: center; margin: 0; padding: 3rem 1rem; }}
h1 {{ font-size: 3rem; margin: 0 0 2rem; }}
p {{ font-size: 1.8rem; }}
#choices {{ list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; align-items: center; gap: 1.2rem; }}
.big {{ display: inline-block; min-width: 12em; font-size: 2rem; padding: 0.5em 1.6em; border-radius: 10px; background: #2f6fd6; color: #fff; text-decoration: none; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""
