"""The child-facing skip counting page and the requests it makes.

The page is the quiz shell from ``policy.quiz_page`` with a row of boxes in
place of one question and one answer. Its script reports a page load with
``POST ?do=visit``, asks for each question with ``POST ?do=question``, and
sends each try with ``POST ?do=answer``. A plain form post to the same URL
is "Try a different task", which ``policy.task_page`` handles.

Closing a question left showing finishes it, so a reload or a give-up can
be what passes or fails the attempt. Every request that closes one checks.
"""

from __future__ import annotations

import json
import random
from collections.abc import Mapping
from datetime import datetime

from policy.hierarchy import Policy
from policy.quiz import StaleQuestion
from policy.quiz_page import (
    ANSWER,
    QUESTION,
    VISIT,
    Back,
    document,
    end_links,
    ending,
    json_response,
    note_html,
    reload,
)
from policy.report import PageResponse, _e, _response
from policy.skip_counting import LABEL, WRONG, Session, blank_positions, format_points
from policy.sounds import SoundSets
from policy.tasks import ABANDONED, Attempt, AttemptStore, Task

__all__ = ["reload", "respond_api", "settle", "show"]

CORRECT_PAUSE_MS = 1000
REVEAL_MS = 10_000
REVEAL_SKIP_MS = 3000

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
) -> PageResponse:
    """Return the start screen with the progress a visit now would show.

    Nothing is stored unless ``record`` is set, which is how a refused
    give-up closes the question that was showing. When that decides the
    attempt, the page opens on its end screen.
    """
    session = Session(attempt.detail, task.document())
    session.visit(now)
    ended = None
    if record:
        verdict = session.verdict()
        if verdict is None:
            store.save(attempt.id, session.detail)
        else:
            ended = _conclude(policy, store, attempt, session, verdict, now, back)
    config = {
        "action": path,
        **_progress(session),
        "correctPause": CORRECT_PAUSE_MS,
        "revealMs": REVEAL_MS,
        "revealSkipMs": REVEAL_SKIP_MS,
        "ended": ended,
    }
    return _response(200, _document(session, config, note))


def settle(task: Task, detail: Mapping, now: datetime) -> tuple[dict, str]:
    """Return the detail with a question left showing closed as a timeout, and how giving up ends.

    Giving up is an abandonment, unless closing that question is what
    passes or fails the attempt.
    """
    session = Session(detail, task.document())
    session.settle(now)
    verdict = session.verdict() if session.detail["runs"] else None
    return session.detail, verdict or ABANDONED


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
    """Record a page load, issue a question, or judge a try, and answer with JSON."""
    attempt = store.in_progress(client_group, task.name)
    if attempt is None:
        return reload()
    session = Session(attempt.detail, task.document())
    if action in (VISIT, QUESTION):
        session.visit(now)
        verdict = session.verdict()
        if verdict is not None:
            ended = _conclude(policy, store, attempt, session, verdict, now, back)
            return json_response(200, {**_progress(session), "finished": True, **ended})
        if action == VISIT:
            store.save(attempt.id, session.detail)
            return json_response(200, {**_progress(session), "finished": False})
        question = session.issue(now, rng or _RNG)
        store.save(attempt.id, session.detail)
        settings = session.settings
        filled = set(question["filled"])
        boxes = [value if position in filled else None for position, value in enumerate(question["sequence"])]
        return json_response(
            200,
            {
                "id": len(session.questions) - 1,
                "boxes": boxes,
                "width": settings.width,
                "negative": settings.negative,
                "allowed_ms": question["allowed_ms"],
                **_progress(session),
                "finished": False,
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
        judged = session.answer(now, number, sent.get("entries"), expired=sent.get("expired") is True)
    except StaleQuestion:
        store.save(attempt.id, session.detail)
        return reload()
    except ValueError as exc:
        return json_response(400, {"error": str(exc)})
    ended = {"result": None, "next": None, "back": None}
    if judged.verdict is None:
        store.save(attempt.id, session.detail)
    else:
        ended = _conclude(policy, store, attempt, session, judged.verdict, now, back)
    question = judged.question
    sound = "incorrect" if judged.outcome == WRONG else judged.outcome
    return json_response(
        200,
        {
            "outcome": judged.outcome,
            "try": judged.attempt,
            "wrong": judged.wrong,
            "right": None if judged.right is None else list(judged.right),
            "sequence": None if judged.outcome == WRONG else question["sequence"],
            "blanks": None if judged.outcome == WRONG else blank_positions(question),
            **_progress(session),
            "finished": judged.verdict is not None,
            **ended,
            "sound": (sounds or _NO_SOUNDS).choose(sound),
        },
    )


def _conclude(
    policy, store: AttemptStore, attempt: Attempt, session: Session, verdict: str, now: datetime, back: Back | None
) -> dict:
    store.finish(attempt.id, verdict, now, detail=session.detail)
    return {"result": verdict, **ending(policy, store, attempt.client_group, now, verdict, back)}


def _progress(session: Session) -> dict:
    settings = session.settings
    return {
        "points": session.points,
        "required": settings.required,
        "number": session.number,
        "maximum": settings.maximum_questions,
    }


def _document(session: Session, config: Mapping, note: str) -> str:
    settings = session.settings
    points = f"{format_points(session.points)} / {settings.required} points"
    upcoming = f"Question {session.number + 1}" + (
        f" of {settings.maximum_questions}" if settings.maximum_questions else ""
    )
    return document(
        title=LABEL,
        config=config,
        header=f'<span id="progress" hidden>{_e(points)}</span>\n<span id="number" hidden>{_e(upcoming)}</span>',
        start=(
            f"<h1>{_e(LABEL)}</h1>\n"
            f'{note_html(note)}<p id="start-progress">{_e(points)}</p>\n'
            f'<p id="start-number">{_e(upcoming)}</p>\n'
            '<button type="button" id="start-button" class="big" autofocus>Start</button>'
        ),
        ask=(
            '<h1 class="title">Skip Counting</h1>\n'
            '<p class="instruction">Fill in the missing numbers</p>\n'
            '<div id="row" class="row" role="group" aria-label="Sequence"></div>\n'
            '<div id="feedback" aria-live="polite"></div>'
        ),
        ends=(
            '<section id="failed" class="screen end" hidden>\n'
            "<h1>The questions are finished</h1>\n"
            f'<p id="failed-points">{_e(points)}</p>\n'
            f"{end_links()}\n"
            "</section>\n"
        ),
        style=_STYLE,
        script=_SCRIPT,
    )


_STYLE = """\
#number { margin-left: auto; font-size: 1.1rem; color: #555; }
#ask .title { font-size: 3rem; margin: 0 0 0.4rem; }
#ask .instruction { font-size: 1.8rem; color: #555; margin: 0 0 2.5rem; }
#start-number { font-size: 1.4rem; color: #555; }
.row { display: flex; flex-wrap: nowrap; justify-content: center; align-items: flex-start; gap: 0.35em; margin: 0 0 1rem;
  font-size: min(3.2rem, calc(92vw / (var(--n) * (var(--w) * 0.75 + 1.25)))); }
.cell { display: flex; flex-direction: column; align-items: center; }
.box { box-sizing: content-box; width: calc(var(--w) * 0.75em); height: 1.25em; line-height: 1.25em; font: inherit; font-weight: bold;
  font-variant-numeric: tabular-nums; text-align: center; padding: 0.15em 0.25em; border: 3px solid #888; border-radius: 8px; background: #fff; }
.box.given { color: #000; background: #f1f1ea; border-color: #bbb; }
.box.entry { color: #4169E1; }
.box.entry.wrong { color: #b42318; border-color: #b42318; }
.box.missed { color: #1a7f37; border: 7px solid #1a7f37; padding: calc(0.15em - 4px) calc(0.25em - 4px); }
.was { font-size: 0.6em; color: #555; margin-top: 0.2em; }
"""

_SCRIPT = """\
  const row = $("row"), number = $("number");
  let current = null;
  let inputs = [];
  let entries = [];
  let locked = new Set();
  let deadline = 0;
  let expiry = null;
  let timing = false;
  let lateExpiry = false;
  let last = null;
  let revealTimer = null;
  let revealAt = 0;
  let ending = null;

  function pointsText(points, required) {
    return points + " / " + required + " points";
  }

  function numberText(count, maximum) {
    return "Question " + count + (maximum ? " of " + maximum : "");
  }

  function counts(progressNow) {
    progress.textContent = pointsText(progressNow.points, progressNow.required);
  }

  function isBlank(input) {
    return input.value === "" || input.value === "-";
  }

  function editable() {
    return entries.filter((input) => !locked.has(input));
  }

  function refocus() {
    if (state !== "asking") return;
    if (last && !locked.has(last)) last.focus();
    else if (editable().length) editable()[0].focus();
  }

  function end(result) {
    if (result.result === "pass") {
      finish(result.next, null, result.back);
      return;
    }
    $("failed-points").textContent = pointsText(result.points, result.required);
    finish(result.next, $("failed"));
  }

  const visited = config.ended
    ? Promise.resolve(null)
    : post("visit").then((now) => {
        if (!now) return null;
        if (now.finished) {
          end(now);
          return null;
        }
        $("start-progress").textContent = pointsText(now.points, now.required);
        $("start-number").textContent = numberText(now.number + 1, now.maximum);
        counts(now);
        return now;
      });

  function box(value) {
    const element = document.createElement("div");
    element.className = "box given";
    element.textContent = String(value);
    return element;
  }

  function build(question) {
    row.textContent = "";
    row.style.setProperty("--n", question.boxes.length);
    row.style.setProperty("--w", question.width);
    inputs = [];
    entries = [];
    locked = new Set();
    last = null;
    question.boxes.forEach((value, position) => {
      const cell = document.createElement("div");
      cell.className = "cell";
      const input = document.createElement("input");
      input.type = "text";
      input.autocomplete = "off";
      input.setAttribute("aria-label", "Number " + (position + 1));
      if (value === null) {
        input.className = "box entry";
        input.inputMode = question.negative ? "text" : "numeric";
        input.maxLength = question.width;
        input.addEventListener("keydown", key);
        input.addEventListener("input", typed);
        input.addEventListener("focus", () => (last = input));
        entries.push(input);
      } else {
        input.className = "box given";
        input.value = String(value);
        input.readOnly = true;
        input.tabIndex = -1;
      }
      cell.appendChild(input);
      row.appendChild(cell);
      inputs.push(input);
    });
  }

  async function ask() {
    state = "waiting";
    if (!(await visited)) return;
    const next = await post("question");
    if (!next) return;
    if (next.finished) {
      end(next);
      return;
    }
    current = next;
    counts(next);
    number.textContent = numberText(next.number + 1, next.maximum);
    build(next);
    startScreen.hidden = true;
    askScreen.hidden = false;
    progress.hidden = false;
    number.hidden = false;
    timer.hidden = false;
    feedback.className = "";
    feedback.textContent = "";
    deadline = performance.now() + next.allowed_ms;
    lateExpiry = false;
    timing = true;
    expiry = setTimeout(expire, next.allowed_ms);
    state = "asking";
    entries[0].focus();
    requestAnimationFrame(tick);
  }

  function tick() {
    if (!timing) return;
    const left = Math.max(0, deadline - performance.now());
    bar.style.width = (100 * left / current.allowed_ms) + "%";
    requestAnimationFrame(tick);
  }

  function expire() {
    if (state === "asking") submit(true);
    else if (state === "waiting") lateExpiry = true;
  }

  function enter(input) {
    if (state !== "asking") return;
    const blanks = editable().filter(isBlank);
    if (blanks.length === 0) {
      submit(false);
      return;
    }
    const others = blanks.filter((other) => other !== input);
    if (others.length === 0) return;
    const here = inputs.indexOf(input);
    const after = others.find((other) => inputs.indexOf(other) > here);
    land(after || others[0]);
  }

  function key(event) {
    const input = event.target;
    if (event.key === "Enter") {
      event.preventDefault();
      if (!event.repeat) enter(input);
      return;
    }
    if (event.key.length !== 1 || event.ctrlKey || event.metaKey || event.altKey) return;
    if (/[0-9]/.test(event.key)) return;
    if (event.key === "-" && input.selectionStart === 0 && !input.value.slice(input.selectionEnd).startsWith("-")) return;
    event.preventDefault();
  }

  function typed(event) {
    const input = event.target;
    const sign = input.value.startsWith("-") ? "-" : "";
    const clean = sign + input.value.replace(/[^0-9]/g, "");
    if (clean !== input.value) input.value = clean;
    input.classList.remove("wrong");
  }

  function wrongText(count) {
    return (count === 1 ? "1 box is wrong." : count + " boxes are wrong.") + " Try again.";
  }

  function stop() {
    timing = false;
    clearTimeout(expiry);
    for (const input of inputs) input.readOnly = true;
  }

  async function submit(expired) {
    if (state !== "asking") return;
    state = "waiting";
    if (expired) bar.style.width = "0%";
    const sent = entries.map((input) => input.value);
    const result = await post("answer", { id: current.id, entries: sent, expired: expired });
    if (!result) return;
    play(result.sound);
    counts(result);
    if (result.outcome === "wrong") {
      feedback.className = "incorrect";
      feedback.textContent = wrongText(result.wrong);
      if (result.right) {
        const right = new Set(result.right);
        current.boxes.forEach((value, position) => {
          const input = inputs[position];
          if (value !== null || locked.has(input)) return;
          if (right.has(position)) {
            locked.add(input);
            input.readOnly = true;
            input.tabIndex = -1;
            input.className = "box given";
          } else {
            input.classList.add("wrong");
          }
        });
      }
      state = "asking";
      if (lateExpiry || performance.now() >= deadline) {
        submit(true);
        return;
      }
      land(editable()[0]);
      return;
    }
    stop();
    ending = result;
    if (result.outcome === "correct") {
      state = "feedback";
      feedback.className = "correct";
      feedback.textContent = "Correct!";
      setTimeout(onward, config.correctPause);
      return;
    }
    reveal(result, sent);
  }

  function reveal(result, sent) {
    state = "reveal";
    timer.hidden = true;
    feedback.className = result.outcome;
    feedback.textContent = result.outcome === "timeout" ? "Time ran out. Here are the answers." : "Here are the answers.";
    const typedAt = new Map(result.blanks.map((position, index) => [position, sent[index]]));
    row.textContent = "";
    result.sequence.forEach((value, position) => {
      const cell = document.createElement("div");
      cell.className = "cell";
      const shown = box(value);
      cell.appendChild(shown);
      if (typedAt.has(position)) {
        const entered = typedAt.get(position);
        const blank = entered === "" || entered === "-";
        if (blank || !/^-?[0-9]+$/.test(entered) || Number(entered) !== value) {
          shown.className = "box missed";
          if (!blank) {
            const was = document.createElement("s");
            was.className = "was";
            was.textContent = entered;
            was.setAttribute("aria-label", "you wrote " + entered);
            cell.appendChild(was);
          }
        }
      }
      row.appendChild(cell);
    });
    if (document.activeElement) document.activeElement.blur();
    revealAt = performance.now();
    revealTimer = setTimeout(onward, config.revealMs);
  }

  function onward() {
    clearTimeout(revealTimer);
    if (state !== "feedback" && state !== "reveal") return;
    const result = ending;
    ending = null;
    if (result.finished) end(result);
    else ask();
  }

  row.addEventListener("mousedown", (event) => {
    if (event.target.readOnly) event.preventDefault();
  });
  document.addEventListener("keydown", (event) => {
    if (state !== "reveal" && state !== "feedback") return;
    if (event.target === giveUp || confirmBox.contains(event.target)) return;
    event.preventDefault();
    if (state === "reveal" && event.key === "Enter" && !event.repeat && performance.now() - revealAt >= config.revealSkipMs) {
      onward();
    }
  });
  startButton.addEventListener("click", () => {
    if (state === "start") ask();
  });
  if (config.ended) end({ ...config.ended, points: config.points, required: config.required });
  else startButton.focus();
"""
