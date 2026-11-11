"""Child-facing task pages.

Any task assigned to the child's client group opens at its own URL,
``/tasks/<type>/<name>``, whatever the task sets say, so a bookmark always works. An attempt is stored with the
set its task was in when it started, and a practice attempt counts for
nothing. ``/tasks/next`` is the picker, which opens an available task, and
``/tasks/choose`` is the selector, which lists them. Below them, the selector
lists After These and Extra Practice in sections that expand and collapse.
When nothing is available, both say so, with Extra Practice open beneath.
A quiz whose attempt doesn't count right now is shown in the practice
palette with a line that says so.

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
from policy.child_page import counting_line, head, html_tag
from policy.engine import classify_client
from policy.hierarchy import Policy
from policy.parts_of_speech import PARTS_OF_SPEECH
from policy.quiz import EXPIRY
from policy.quiz_page import Back, reload
from policy.report import PageResponse, _e, _response
from policy.selection import (
    CHOOSER_PATH,
    PICKER_PATH,
    chooser_url,
    configured_task,
    may_abandon,
    picked_task_url,
    picker_url,
    sections,
    task_key_from_path,
    task_media_from_path,
    task_page_url,
)
from policy.skip_counting import SKIP_COUNTING
from policy.sounds import SoundSets
from policy.spelling import SPELLING
from policy.tasks import ABANDONED, Attempt, AttemptStore, Task, TaskSets, household_day

NOTHING = "There is nothing to revise right now."
MUST_FINISH = "This task has to be finished before another one."
CHOOSE = "Choose a task"
AFTER_THESE = "After These"
AFTER_NOTE = "These count once the tasks above are done."
EXTRA_PRACTICE = "Extra Practice"
PRACTICE_NOTE = "Practice is just for fun. It doesn't count toward your internet time today."

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
    after a pass, for the page this computer was sent away from. A type
    and name that is not one of this group's tasks goes to the picker.
    """
    client = classify_client(policy, client_ip)
    today = household_day(now)
    if path == PICKER_PATH:
        return _pick(policy, store, client, now)
    if path == CHOOSER_PATH:
        return _choose(policy, store, client, now)
    key = task_key_from_path(path)
    action = (query or {}).get("do")
    task = None if key is None else configured_task(policy.tasks, key, client)
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
    attempt = store.open(client, task.key, now, task_set=sets.set_of(task.key), reopen_within=EXPIRY)
    return _show(policy, store, task, attempt, sets, path, now, stuck=False)


def task_media(policy: Policy, store: AttemptStore, *, path: str, client_ip: str, now: datetime) -> Path | None:
    """Return the audio file a ``/tasks/<type>/<name>/audio/<file>`` path names, or None.

    Any task assigned to this client group serves its audio.
    """
    found = task_media_from_path(path)
    if found is None:
        return None
    key, file_name = found
    task = configured_task(policy.tasks, key, classify_client(policy, client_ip))
    quiz = None if task is None else _QUIZZES.get(task.type)
    if quiz is None or not hasattr(quiz, "media"):
        return None
    return quiz.media(task, file_name)


def _pick(policy: Policy, store: AttemptStore, client: str, now: datetime) -> PageResponse:
    location = picked_task_url(policy, client, household_day(now), store)
    if location is None:
        return _nothing(policy, sections(policy, client, household_day(now), store).practice)
    return _redirect(location)


def _choose(policy: Policy, store: AttemptStore, client: str, now: datetime) -> PageResponse:
    """List the available tasks in picker order, then After These and Extra Practice.

    One available task, with nothing in the other sections, goes straight to that task.
    """
    found = sections(policy, client, household_day(now), store)
    if not found.main:
        return _nothing(policy, found.practice)
    if len(found.main) == 1 and not found.after and not found.practice:
        return _redirect(task_page_url(policy, found.main[0].key))
    body = (
        f"<h1>{_e(CHOOSE)}</h1>\n"
        f'<ul id="choices" class="choices">\n{_links(policy, found.main, "")}\n</ul>\n'
        + _section(policy, "after-these", AFTER_THESE, AFTER_NOTE, found.after, "after", expanded=False)
        + _section(policy, "extra-practice", EXTRA_PRACTICE, PRACTICE_NOTE, found.practice, "extra", expanded=False)
    )
    return _response(200, _child_document(body, sections=bool(found.after or found.practice)))


def _nothing(policy: Policy, practice: tuple[Task, ...]) -> PageResponse:
    """Say there is nothing to revise, with Extra Practice open beneath when it has a task."""
    if not practice:
        return _page(NOTHING)
    body = (
        f"<h1>Revision</h1>\n<p>{_e(NOTHING)}</p>\n"
        + _section(policy, "extra-practice", EXTRA_PRACTICE, PRACTICE_NOTE, practice, "extra", expanded=True)
    )
    return _response(200, _child_document(body, sections=True))


def _links(policy: Policy, tasks: tuple[Task, ...], kind: str) -> str:
    style = "big " + kind if kind else "big"
    return "\n".join(
        f'<li><a class="{style}" href="{_e(task_page_url(policy, task.key))}">{_e(_label(policy, task))}</a></li>'
        for task in tasks
    )


def _label(policy: Policy, task: Task) -> str:
    """Return the task's name, with its type when another task has the same name."""
    if any(other.name == task.name and other.type != task.type for other in policy.tasks):
        return f"{task.name} ({task.type.replace('_', ' ')})"
    return task.name


def _section(
    policy: Policy, key: str, heading: str, note: str, tasks: tuple[Task, ...], kind: str, *, expanded: bool
) -> str:
    """Return a section under a heading that expands and collapses, or "" when it has no tasks."""
    if not tasks:
        return ""
    state = "true" if expanded else "false"
    panel = 'class="more-panel open" data-open="true"' if expanded else 'class="more-panel" data-open="false" inert'
    return (
        f'<section class="more">\n'
        f'<h2 class="more-heading"><button type="button" class="more-toggle" aria-expanded="{state}" '
        f'aria-controls="{key}">{_CHEVRON}<span>{_e(heading)}</span></button></h2>\n'
        f'<div id="{key}" {panel}>\n<div class="more-inner">\n'
        f'<p class="more-note">{_e(note)}</p>\n'
        f'<ul class="choices">\n{_links(policy, tasks, kind)}\n</ul>\n'
        "</div>\n</div>\n</section>\n"
    )


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
    current = store.in_progress(client, task.key)
    if current is None:
        return _redirect(location)
    sets = store.task_sets(policy.tasks, client, household_day(now))
    if not may_abandon(current, task, sets):
        return _show(policy, store, task, current, sets, path, now, stuck=True, back=back)
    detail, outcome = current.detail, ABANDONED
    quiz = _QUIZZES.get(task.type)
    if quiz is not None:
        detail, outcome = quiz.settle(task, detail, now)
    store.finish(current.id, outcome, now, detail=detail)
    if quiz is not None and hasattr(quiz, "give_up_page"):
        review = quiz.give_up_page(detail, location, counting_line(current.task_set, sets))
        if review is not None:
            return review
    return _redirect(location)


def _show(
    policy: Policy,
    store: AttemptStore,
    task: Task,
    attempt: Attempt,
    sets: TaskSets,
    action: str,
    now: datetime,
    *,
    stuck: bool,
    back: Back | None = None,
) -> PageResponse:
    quiz = _QUIZZES.get(task.type)
    if quiz is not None:
        note = MUST_FINISH if stuck else ""
        line = counting_line(attempt.task_set, sets)
        return quiz.show(
            store, task, attempt, path=action, now=now, policy=policy, note=note, record=stuck, back=back, line=line
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


def _child_document(body: str, *, sections: bool = False) -> str:
    script = f"<script>\n{_SECTIONS_SCRIPT}</script>\n" if sections else ""
    return f"""<!DOCTYPE html>
{html_tag("")}
<head>
{head("Revision", _STYLE)}
</head>
<body>
{body}
{script}</body>
</html>
"""


_CHEVRON = (
    '<svg class="chevron" aria-hidden="true" viewBox="0 0 24 24" width="1em" height="1em" fill="none" '
    'stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>'
)

_STYLE = """\
body { font-family: sans-serif; background: var(--page-bg); color: var(--text); text-align: center; margin: 0; padding: 3rem 1rem; }
h1 { font-size: 3rem; margin: 0 0 2rem; }
p { font-size: 1.8rem; }
.choices { list-style: none; padding: 0.4rem 0; margin: 0; display: flex; flex-direction: column; align-items: center; gap: 1.2rem; }
.big { display: inline-block; min-width: 12em; font-size: 2rem; padding: 0.5em 1.6em; border-radius: 10px; background: var(--accent); color: var(--on-accent); text-decoration: none; }
.big.after { background: var(--choice-after); }
.big.extra { background: var(--choice-extra); }
.more { margin-top: 2.5rem; }
.more-heading { margin: 0; font-size: 2rem; }
.more-toggle { display: inline-flex; align-items: center; gap: 0.4em; font: inherit; font-weight: bold; color: var(--text);
  background: none; border: none; border-radius: 8px; padding: 0.3em 0.6em; cursor: pointer; }
.more-toggle:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
.chevron { flex: none; transition: transform var(--expand-duration) var(--expand-easing); }
.more-toggle[aria-expanded="true"] .chevron { transform: rotate(90deg); }
.more-panel { display: grid; grid-template-rows: 0fr; transition: grid-template-rows var(--expand-duration) var(--expand-easing); }
.more-panel.open { grid-template-rows: 1fr; }
.more-inner { min-height: 0; overflow: hidden; }
.more-note { font-size: 1.5rem; color: var(--muted); margin: 1rem 0 1.2rem; }
"""

# A page brought back from the browser's history starts with its sections as the server sent them.
_SECTIONS_SCRIPT = """\
(() => {
  const toggles = [...document.querySelectorAll(".more-toggle")];
  function show(toggle, open) {
    const panel = document.getElementById(toggle.getAttribute("aria-controls"));
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    panel.classList.toggle("open", open);
    panel.inert = !open;
  }
  for (const toggle of toggles) {
    toggle.addEventListener("click", () => show(toggle, toggle.getAttribute("aria-expanded") !== "true"));
  }
  window.addEventListener("pageshow", (event) => {
    if (!event.persisted) return;
    for (const toggle of toggles) {
      show(toggle, document.getElementById(toggle.getAttribute("aria-controls")).dataset.open === "true");
    }
  });
})();
"""
