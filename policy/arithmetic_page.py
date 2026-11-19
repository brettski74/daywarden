"""The child-facing arithmetic page and the requests it makes.

The page is one document. Its script asks the task's own URL for each
question with ``POST ?do=question`` and sends each answer with
``POST ?do=answer``. Using the task URL means the proxy rule that lets the
page load also lets the quiz reach the server. A plain form post to the same
URL is "Try a different task", which ``policy.task_page`` handles.

Practice mode (S039) is a walk through one number's table. ``POST ?do=practice``
enters it, ``?do=practice_question`` issues each question of the walk, and
``?do=practice_answer`` judges it. A walk's answers are stored on the attempt
apart from its quiz questions and count in no figure.

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

from policy.arithmetic import PracticeOwed, Session, StaleQuestion
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
PRACTICE = "practice"
PRACTICE_QUESTION = "practice_question"
PRACTICE_ANSWER = "practice_answer"
# A right answer in a walk stays above the next question, and fades over this long once that question is shown.
ANSWER_FADE_MS = 3000
# A wrong answer or timeout in a walk shows what happened for this long before the walk starts again.
PRACTICE_WRONG_PAUSE_MS = 1000

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
        "practice": settings.can_practice,
        "owed": session.practice_owed,
        "fadeMs": ANSWER_FADE_MS,
        "practiceWrongPause": PRACTICE_WRONG_PAUSE_MS,
    }
    return _response(
        200,
        _document(settings.operation.label, session.correct, settings.required, config, note, line, settings.can_practice, session.practice_owed),
    )


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
    """Record a page load, issue a question, judge an answer, or run practice, and answer with JSON.

    A visit is the page running in a tab. A question that was showing when
    the page was left is a timeout, and a practice walk in progress ends.
    Coming back more than an hour after the last activity starts a new run.
    ``back`` names the page a pass returns to.
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
        try:
            question = session.issue(now, rng or _RNG, store.draw_figures(attempt))
        except PracticeOwed:
            return reload()
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
    if action == PRACTICE:
        return _enter_practice(store, attempt, session, now, rng or _RNG)
    if action == PRACTICE_QUESTION:
        return _practice_question(store, attempt, session, now)
    if action not in (ANSWER, PRACTICE_ANSWER):
        return json_response(404, {"error": "unknown request"})
    sent, number, refused = _answer_request(body)
    if refused is not None or sent is None or number is None:
        return refused or json_response(400, {"error": "the answer names no question"})
    if action == PRACTICE_ANSWER:
        return _practice_answer(store, attempt, session, now, sent, number, sounds)
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


def _answer_request(body: bytes) -> tuple[dict | None, int | None, PageResponse | None]:
    """Return an answer's JSON, the question it names, and the refusal to send when it is not one."""
    try:
        sent = json.loads(body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, None, json_response(400, {"error": "the answer is not JSON"})
    if not isinstance(sent, dict):
        return None, None, json_response(400, {"error": "the answer is not a JSON object"})
    number = sent.get("id")
    if isinstance(number, bool) or not isinstance(number, int):
        return None, None, json_response(400, {"error": "the answer names no question"})
    return sent, number, None


def _enter_practice(store: AttemptStore, attempt: Attempt, session: Session, now: datetime, rng: random.Random) -> PageResponse:
    """Start a walk on a new run of the same attempt, which stays in progress and is not passed or abandoned.

    A question showing is closed as a timeout and stored first, so the choice
    of ``m`` counts it, with every other answer of this attempt so far.
    """
    session.visit(now)
    if not session.settings.can_practice:
        return json_response(400, {"error": "this task does not offer practice"})
    store.save(attempt.id, session.detail)
    try:
        walk = session.begin_walk(now, rng, lambda operation: store.facts.book(attempt.client_group, operation))
    except ValueError as exc:
        return json_response(400, {"error": str(exc)})
    store.save(attempt.id, session.detail)
    return json_response(
        200,
        {"practice": {"m": walk["m"], "length": walk["length"]}, "correct": 0, "required": session.settings.required},
    )


def _practice_question(store: AttemptStore, attempt: Attempt, session: Session, now: datetime) -> PageResponse:
    try:
        question = session.practice_question(now)
    except StaleQuestion:
        store.save(attempt.id, session.detail)
        return reload()
    walk = session.walks[-1]
    store.save(attempt.id, session.detail)
    return json_response(
        200,
        {
            "id": len(walk["questions"]) - 1,
            "question": question["question"],
            "allowed_ms": question["allowed_ms"],
            "position": question["position"],
            "length": walk["length"],
        },
    )


def _practice_answer(
    store: AttemptStore,
    attempt: Attempt,
    session: Session,
    now: datetime,
    sent: Mapping,
    number: int,
    sounds: SoundSets | None,
) -> PageResponse:
    """Judge a walk's answer. Nothing here can pass the attempt, so it is only ever saved."""
    try:
        judged = session.practice_answer(now, number, sent.get("answer"), expired=sent.get("expired") is True)
    except StaleQuestion:
        store.save(attempt.id, session.detail)
        return reload()
    except ValueError as exc:
        return json_response(400, {"error": str(exc)})
    store.save(attempt.id, session.detail)
    return json_response(
        200,
        {
            "outcome": judged.outcome,
            "full": judged.full,
            "position": judged.position,
            "length": judged.length,
            "finished": judged.finished,
            "sound": (sounds or _NO_SOUNDS).choose(judged.outcome),
        },
    )


def _document(label: str, correct: int, required: int, config: Mapping, note: str, line: str, practice: bool, owed: bool = False) -> str:
    # While practice is owed (S042) Practice takes the main button's look and Start is disabled.
    start_practice = (
        '\n<p id="practice-owed"' + ("" if owed else " hidden") + ">Practise first</p>"
        '\n<p id="practice-done" hidden>Practice done. Start the quiz when you are ready.</p>\n'
        f'<button type="button" id="practice-start" class="{"big" if owed else "practice"}"{" autofocus" if owed else ""}>Practice</button>'
        if practice
        else ""
    )
    ask_practice = '\n<button type="button" id="practice-ask" class="practice">Practice</button>' if practice else ""
    confirm = (
        '<div id="practice-confirm" role="dialog" aria-label="Practice" hidden>\n'
        "<div>Start practice mode? Your current quiz progress will be reset.</div>\n"
        '<button type="button" id="practice-yes">Yes, practice</button>\n'
        '<button type="button" id="practice-no">No, keep going</button>\n'
        "</div>\n"
        if practice
        else ""
    )
    return document(
        title=label,
        config=config,
        header=f'<span id="progress" hidden>{correct} / {required}</span>\n<span></span>',
        start=(
            f"<h1>{_e(label)}</h1>\n"
            f'{note_html(note)}<p id="start-progress">{correct} / {required} correct</p>\n'
            f'<button type="button" id="start-button" class="big"{" disabled" if owed else " autofocus"}>Start</button>{start_practice}'
        ),
        ask=(
            '<div id="previous" aria-hidden="true" hidden></div>\n'
            '<div id="question" aria-live="polite"></div>\n'
            '<label for="answer" class="hidden-label">Answer</label>\n'
            '<input id="answer" type="text" inputmode="numeric" pattern="[0-9]*" autocomplete="off" maxlength="12" disabled>\n'
            f'<div id="feedback" aria-live="polite"></div>{ask_practice}'
        ),
        ends=confirm,
        style=_STYLE,
        script=_SCRIPT,
        line=line,
    )


_STYLE = """\
#question { font-size: clamp(3rem, 13vw, 9rem); font-weight: bold; margin: 0 0 2rem; white-space: nowrap; }
#previous { min-height: 3rem; margin: 0 0 0.4rem; font-size: 2.4rem; color: var(--muted); white-space: nowrap; }
#answer { font-size: 3rem; width: 5em; text-align: center; padding: 0.15em; border: 3px solid var(--field-border); border-radius: 8px; }
#practice-done { color: var(--right); }
#practice-owed { color: var(--muted); }
#start-button:disabled { opacity: 0.4; cursor: default; }
"""

_SCRIPT = """\
  const questionText = $("question"), box = $("answer"), previous = $("previous");
  const practiceBox = $("practice-confirm");
  const practiceButtons = [$("practice-start"), $("practice-ask")].filter((button) => button);
  let current = null;
  let deadline = 0;
  let expiry = null;
  let inflight = Promise.resolve();
  let nextTimer = null;
  let practicing = false;
  let entering = false;
  let attemptOver = false;
  let earlier = "";

  function counts(correct, required) {
    progress.textContent = correct + " / " + required;
  }

  function walkAt(position, length) {
    progress.textContent = "Practice: " + (position + 1) + " of " + length;
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
  inflight = visited;

  // The right answer to the last question in a walk, above the next one, fading out once that one is shown.
  function showEarlier() {
    previous.style.transition = "none";
    previous.style.opacity = "1";
    previous.textContent = earlier;
    if (earlier) {
      void previous.offsetWidth;
      previous.style.transition = "opacity " + config.fadeMs + "ms linear";
      previous.style.opacity = "0";
    }
    earlier = "";
  }

  async function ask() {
    state = "waiting";
    if (!(await visited)) return;
    inflight = post(practicing ? "practice_question" : "question");
    const next = await inflight;
    if (!next) return;
    current = next;
    if (practicing) walkAt(next.position, next.length);
    else counts(next.correct, next.required);
    startScreen.hidden = true;
    askScreen.hidden = false;
    progress.hidden = false;
    timer.hidden = false;
    questionText.textContent = next.question;
    showEarlier();
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
    inflight = post(practicing ? "practice_answer" : "answer", { id: current.id, answer: box.value, expired: expired });
    const result = await inflight;
    if (!result) return;
    state = "feedback";
    play(result.sound);
    if (practicing) {
      walked(result);
      return;
    }
    counts(result.correct, result.required);
    feedback.className = result.outcome;
    if (result.outcome === "correct") {
      feedback.textContent = "Correct!";
    } else {
      questionText.textContent = result.full;
      feedback.textContent = result.outcome === "timeout" ? "Time ran out" : "Not quite";
    }
    if (result.finished) closeOffer();
    const pause = result.outcome === "correct" ? config.correctPause : config.wrongPause;
    nextTimer = setTimeout(() => (result.finished ? finish(result, null) : ask()), pause);
  }

  // A right answer moves straight on. A miss shows what happened, never the right answer, and the walk falls back.
  function walked(result) {
    if (result.finished) {
      leavePractice();
      return;
    }
    walkAt(result.position, result.length);
    if (result.outcome === "correct") {
      earlier = result.full;
      ask();
      return;
    }
    showEarlier();
    feedback.className = result.outcome;
    feedback.textContent = result.outcome === "timeout" ? "Time ran out" : "Not quite";
    nextTimer = setTimeout(ask, config.practiceWrongPause);
  }

  function closeOffer() {
    if (!config.practice) return;
    attemptOver = true;
    practiceBox.hidden = true;
    for (const button of practiceButtons) button.disabled = true;
  }

  async function enterPractice() {
    practiceBox.hidden = true;
    if (entering || practicing || attemptOver) return;
    entering = true;
    await inflight;
    if (attemptOver) return;
    clearTimeout(nextTimer);
    clearTimeout(expiry);
    state = "waiting";
    box.disabled = true;
    const reply = await post("practice");
    entering = false;
    if (!reply) return;
    practicing = true;
    current = null;
    earlier = "";
    previous.textContent = "";
    previous.hidden = false;
    $("practice-done").hidden = true;
    for (const button of practiceButtons) button.hidden = true;
    feedback.className = "";
    feedback.textContent = "";
    counts(reply.correct, reply.required);
    ask();
  }

  // A finished walk (S042) frees Start and puts Practice back to its small place.
  function unlock() {
    if (!config.owed) return;
    config.owed = false;
    startButton.disabled = false;
    $("practice-owed").hidden = true;
    $("practice-start").className = "practice";
  }

  // The end of the walk: back to the start screen, with the quiz at zero.
  function leavePractice() {
    practicing = false;
    state = "start";
    askScreen.hidden = true;
    progress.hidden = true;
    timer.hidden = true;
    previous.hidden = true;
    previous.textContent = "";
    for (const button of practiceButtons) button.hidden = false;
    $("practice-done").hidden = false;
    unlock();
    $("start-progress").textContent = "0 / " + config.required + " correct";
    startScreen.hidden = false;
    startButton.focus();
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
    if (state === "start" && !config.owed) ask();
  });
  if (config.practice) {
    for (const button of [...practiceButtons, $("practice-yes"), $("practice-no")]) {
      button.addEventListener("mousedown", (event) => event.preventDefault());
      button.addEventListener("keydown", (event) => {
        if (event.key === "Enter") event.preventDefault();
      });
    }
    for (const button of practiceButtons) {
      button.addEventListener("click", () => {
        if (attemptOver || practicing || entering) return;
        // Practice owed (S042) has no quiz progress to lose and no quiz to keep going with, so it asks nothing.
        if (config.owed) {
          enterPractice();
          return;
        }
        confirmBox.hidden = true;
        practiceBox.hidden = false;
      });
    }
    giveUp.addEventListener("click", () => {
      practiceBox.hidden = true;
    });
    $("practice-yes").addEventListener("click", enterPractice);
    $("practice-no").addEventListener("click", () => {
      practiceBox.hidden = true;
      refocus();
    });
  }
  if (config.owed) $("practice-start").focus();
  else startButton.focus();
"""
