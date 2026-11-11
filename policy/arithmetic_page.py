"""The child-facing arithmetic page and the requests it makes.

The page is one document. Its script asks the task's own URL for each
question with ``POST ?do=question`` and sends each answer with
``POST ?do=answer``. Using the task URL means the proxy rule that lets the
page load also lets the quiz reach the server. A plain form post to the same
URL is "Try a different task", which ``policy.task_page`` handles.

A GET of the page changes nothing on the attempt. A revision redirect also
catches the browser's own background requests, such as favicons and
telemetry, and a browser that follows one of those fetches this page
without showing it. The script reports a real page load with
``POST ?do=visit``, and only that closes a question left showing.
"""

from __future__ import annotations

import json
import random
from collections.abc import Mapping
from datetime import datetime

from policy.arithmetic import Session, StaleQuestion
from policy.hierarchy import Policy
from policy.quiz_page import (
    ANSWER,
    QUESTION,
    VISIT,
    Back,
    document,
    ending,
    json_response,
    next_task_url,
    note_html,
    reload,
)
from policy.report import PageResponse, _e, _response
from policy.sounds import SoundSets
from policy.tasks import ABANDONED, PASS, Attempt, AttemptStore, Task

__all__ = ["next_task_url", "reload", "respond_api", "settle", "show"]

CORRECT_PAUSE_MS = 1000
WRONG_PAUSE_MS = 2500

_RNG = random.Random()
_NO_SOUNDS = SoundSets()


def show(
    store: AttemptStore,
    task: Task,
    attempt: Attempt,
    *,
    path: str,
    now: datetime,
    policy: Policy | None = None,
    note: str = "",
    record: bool = False,
    back: Back | None = None,
    line: str = "",
) -> PageResponse:
    """Return the start screen with the progress a visit now would show.

    Nothing is stored unless ``record`` is set, which is how a refused
    give-up closes the question that was showing. Otherwise the script's
    visit request records the page load. Closing a question never passes
    an arithmetic attempt, so ``back`` is not asked here. ``line`` says the
    attempt doesn't count right now.
    """
    session = Session(attempt.detail, task.document())
    session.visit(now)
    if record:
        store.save(attempt.id, session.detail)
    settings = session.settings
    config = {
        "action": path,
        "correct": session.correct,
        "required": settings.required,
        "correctPause": CORRECT_PAUSE_MS,
        "wrongPause": WRONG_PAUSE_MS,
    }
    return _response(200, _document(settings.operation.label, session.correct, settings.required, config, note, line))


def settle(task: Task, detail: Mapping, now: datetime) -> tuple[dict, str]:
    """Return the detail with a question left showing closed as a timeout, and how giving up ends."""
    session = Session(detail, task.document())
    session.settle(now)
    return session.detail, ABANDONED


def respond_api(
    policy: Policy,
    store: AttemptStore,
    task: Task,
    client_group: str,
    *,
    action: str,
    body: bytes,
    now: datetime,
    sounds: SoundSets | None = None,
    rng: random.Random | None = None,
    back: Back | None = None,
) -> PageResponse:
    """Record a page load, issue a question, or judge an answer, and answer with JSON.

    A visit is the page running in a tab. A question that was showing when
    the page was left is a timeout. Coming back more than an hour after the
    last activity starts a new run. ``back`` names the page a pass returns to.
    """
    attempt = store.in_progress(client_group, task.key)
    if attempt is None:
        return reload()
    session = Session(attempt.detail, task.document())
    if action == VISIT:
        session.visit(now)
        store.save(attempt.id, session.detail)
        return json_response(200, {"correct": session.correct, "required": session.settings.required})
    if action == QUESTION:
        question = session.issue(now, rng or _RNG)
        store.save(attempt.id, session.detail)
        return json_response(
            200,
            {
                "id": len(session.questions) - 1,
                "question": question["question"],
                "allowed_ms": question["allowed_ms"],
                "correct": session.correct,
                "required": session.settings.required,
            },
        )
    if action != ANSWER:
        return json_response(404, {"error": "unknown request"})
    try:
        sent = json.loads(body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return json_response(400, {"error": "the answer is not JSON"})
    if not isinstance(sent, dict):
        return json_response(400, {"error": "the answer is not a JSON object"})
    number = sent.get("id")
    if isinstance(number, bool) or not isinstance(number, int):
        return json_response(400, {"error": "the answer names no question"})
    try:
        judged = session.answer(now, number, sent.get("answer"), expired=sent.get("expired") is True)
    except StaleQuestion:
        store.save(attempt.id, session.detail)
        return reload()
    except ValueError as exc:
        return json_response(400, {"error": str(exc)})
    ended = {"next": None, "practice": None, "back": None}
    if judged.finished:
        store.finish(attempt.id, PASS, now, detail=session.detail)
        ended = ending(policy, store, client_group, now, PASS, back)
    else:
        store.save(attempt.id, session.detail)
    question = judged.question
    return json_response(
        200,
        {
            "outcome": judged.outcome,
            "full": f"{question['question']} {question['expected']}",
            "correct": judged.correct,
            "required": judged.required,
            "finished": judged.finished,
            **ended,
            "sound": (sounds or _NO_SOUNDS).choose(judged.outcome),
        },
    )


def _document(label: str, correct: int, required: int, config: Mapping, note: str, line: str) -> str:
    return document(
        title=label,
        config=config,
        header=f'<span id="progress" hidden>{correct} / {required}</span>\n<span></span>',
        start=(
            f"<h1>{_e(label)}</h1>\n"
            f'{note_html(note)}<p id="start-progress">{correct} / {required} correct</p>\n'
            '<button type="button" id="start-button" class="big" autofocus>Start</button>'
        ),
        ask=(
            '<div id="question" aria-live="polite"></div>\n'
            '<label for="answer" class="hidden-label">Answer</label>\n'
            '<input id="answer" type="text" inputmode="numeric" pattern="[0-9]*" autocomplete="off" maxlength="12" disabled>\n'
            '<div id="feedback" aria-live="polite"></div>'
        ),
        style=_STYLE,
        script=_SCRIPT,
        line=line,
    )


_STYLE = """\
#question { font-size: clamp(3rem, 13vw, 9rem); font-weight: bold; margin: 0 0 2rem; white-space: nowrap; }
#answer { font-size: 3rem; width: 5em; text-align: center; padding: 0.15em; border: 3px solid var(--field-border); border-radius: 8px; }
"""

_SCRIPT = """\
  const questionText = $("question"), box = $("answer");
  let current = null;
  let deadline = 0;
  let expiry = null;

  function counts(correct, required) {
    progress.textContent = correct + " / " + required;
  }

  function refocus() {
    if (state === "asking") box.focus();
  }

  const visited = post("visit").then((progress) => {
    if (progress) {
      $("start-progress").textContent = progress.correct + " / " + progress.required + " correct";
      counts(progress.correct, progress.required);
    }
    return progress;
  });

  async function ask() {
    state = "waiting";
    if (!(await visited)) return;
    const next = await post("question");
    if (!next) return;
    current = next;
    counts(next.correct, next.required);
    startScreen.hidden = true;
    askScreen.hidden = false;
    progress.hidden = false;
    timer.hidden = false;
    questionText.textContent = next.question;
    feedback.className = "";
    feedback.textContent = "";
    box.value = "";
    box.disabled = false;
    box.focus();
    deadline = performance.now() + next.allowed_ms;
    expiry = setTimeout(() => submit(true), next.allowed_ms);
    state = "asking";
    requestAnimationFrame(tick);
  }

  function tick() {
    if (state !== "asking") return;
    const left = Math.max(0, deadline - performance.now());
    bar.style.width = (100 * left / current.allowed_ms) + "%";
    requestAnimationFrame(tick);
  }

  async function submit(expired) {
    if (state !== "asking") return;
    state = "waiting";
    clearTimeout(expiry);
    box.disabled = true;
    if (expired) bar.style.width = "0%";
    const result = await post("answer", { id: current.id, answer: box.value, expired: expired });
    if (!result) return;
    state = "feedback";
    play(result.sound);
    counts(result.correct, result.required);
    feedback.className = result.outcome;
    if (result.outcome === "correct") {
      feedback.textContent = "Correct!";
    } else {
      questionText.textContent = result.full;
      feedback.textContent = result.outcome === "timeout" ? "Time ran out" : "Not quite";
    }
    const pause = result.outcome === "correct" ? config.correctPause : config.wrongPause;
    setTimeout(() => (result.finished ? finish(result, null) : ask()), pause);
  }

  box.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      if (box.value !== "") submit(false);
      return;
    }
    if (event.key.length === 1 && !/[0-9]/.test(event.key) && !event.ctrlKey && !event.metaKey) {
      event.preventDefault();
    }
  });
  box.addEventListener("input", () => {
    const digits = box.value.replace(/[^0-9]/g, "");
    if (digits !== box.value) box.value = digits;
  });
  startButton.addEventListener("click", () => {
    if (state === "start") ask();
  });
  startButton.focus();
"""
