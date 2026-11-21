"""The child-facing capitalisation page and the requests it makes.

The page is the quiz shell from ``policy.quiz_page`` with a sentence shown in
lower case, whose words he clicks when they need a capital letter. Its script
reports a page load with ``POST ?do=visit``, asks for each sentence with
``POST ?do=question``, and sends each try with ``POST ?do=answer``. A plain
form post to the same URL is "Try a different task", which
``policy.task_page`` handles.

The requests, the open sentence, the resume, and the ending are the parts of
speech page's, in ``policy.parts_of_speech_page``; this module says what a
question, a try, and an answer look like for capitalisation.

What clicking a word shows is sent with the question as each word's ``shown``
text, so the server never says which words have a capital until the answer.
"""

from __future__ import annotations

import json
import random
from collections.abc import Mapping
from datetime import datetime

from policy.capitalisation import HELP_POINTS, LABEL, Session, answer, help_points, sentence_words
from policy.hierarchy import Policy
from policy.parts_of_speech import WRONG, format_points
from policy.parts_of_speech_page import (
    CORRECT_PAUSE_MS,
    NEXT_GUARD_MS,
    NEXT_WAIT_MS,
    conclude,
    progress,
    questions_label,
)
from policy.quiz import CORRECT, INCORRECT, TIMEOUT, StaleQuestion
from policy.quiz_page import (
    ANSWER,
    QUESTION,
    VISIT,
    Back,
    document,
    end_links,
    json_response,
    note_html,
    reload,
)
from policy.report import PageResponse, _e, _response
from policy.sounds import SoundSets
from policy.tasks import ABANDONED, Attempt, AttemptStore, Task

__all__ = ["reload", "respond_api", "settle", "show"]

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
    """Return the start screen with the progress a visit now would show, as the parts of speech page does."""
    session = Session(attempt.detail, task.document(), _RNG)
    session.visit(now)
    ended = None
    if record:
        verdict = session.verdict()
        if verdict is None:
            store.save(attempt.id, session.detail)
        else:
            ended = conclude(policy, store, attempt, session, verdict, now, back)
    config = {
        "action": path,
        **progress(session),
        "correctPause": CORRECT_PAUSE_MS,
        "nextGuardMs": NEXT_GUARD_MS,
        "nextWaitMs": NEXT_WAIT_MS,
        "ended": ended,
    }
    return _response(200, _document(session, config, note, line, task.document()))


def settle(task: Task, detail: Mapping, now: datetime) -> tuple[dict, str]:
    """Return the detail with the open sentence closed as a timeout. Giving up is always an abandonment."""
    session = Session(detail, task.document(), _RNG)
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
    """Record a page load, issue or bring back a sentence, or judge a try, and answer with JSON."""
    attempt = store.in_progress(client_group, task.key)
    if attempt is None:
        return reload()
    session = Session(attempt.detail, task.document(), rng or _RNG)
    if action in (VISIT, QUESTION):
        session.visit(now)
        verdict = session.verdict()
        if verdict is not None:
            ended = conclude(policy, store, attempt, session, verdict, now, back)
            return json_response(200, {**progress(session), "finished": True, **ended})
        if action == VISIT:
            store.save(attempt.id, session.detail)
            return json_response(200, {**progress(session), "finished": False})
        question = session.issue(now)
        store.save(attempt.id, session.detail)
        tries = question["tries"]
        last = tries[-1] if tries else None
        return json_response(
            200,
            {
                "id": len(session.questions) - 1,
                "words": sentence_words(question),
                "try": len(tries) + 1,
                "allowed_ms": question["allowed_ms"],
                "left_ms": session.left_ms(question, now),
                "clicks": None if last is None else last["clicks"],
                "wrong": None if last is None else last["wrong"],
                "missed": None if last is None else last["missed"],
                **progress(session),
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
        return json_response(400, {"error": "the answer names no sentence"})
    try:
        judged = session.answer(now, number, sent.get("clicks"), expired=sent.get("expired") is True)
    except StaleQuestion:
        store.save(attempt.id, session.detail)
        return reload()
    except ValueError as exc:
        return json_response(400, {"error": str(exc)})
    ended = {"result": None, "next": None, "practice": None, "back": None}
    if judged.verdict is None:
        store.save(attempt.id, session.detail)
    else:
        ended = conclude(policy, store, attempt, session, judged.verdict, now, back)
    sound = CORRECT if judged.outcome == CORRECT else "timeout" if judged.outcome == "timeout" else "incorrect"
    return json_response(
        200,
        {
            "outcome": judged.outcome,
            "try": judged.attempt,
            "wrong": judged.wrong if judged.outcome == WRONG else None,
            "missed": judged.missed if judged.outcome == WRONG else None,
            "answer": answer(judged.question) if judged.outcome in (CORRECT, INCORRECT, TIMEOUT) else None,
            "scored": judged.question["points"],
            **progress(session),
            "finished": judged.verdict is not None,
            **ended,
            "sound": (sounds or _NO_SOUNDS).choose(sound),
        },
    )


def _document(session: Session, config: Mapping, note: str, line: str, body: Mapping) -> str:
    now = progress(session)
    points = f"{format_points(now['points'])} / {now['required']} points"
    upcoming = questions_label(now["number"], now["minimum"], now["maximum"])
    return document(
        title=LABEL,
        config=config,
        header='<span id="progress" hidden></span>\n<span></span>',
        start=(
            f"<h1>{_e(LABEL)}</h1>\n"
            f'{note_html(note)}<p id="start-points">{_e(points)}</p>\n'
            f'<p id="start-required" class="minor">{_e(str(now["required"]))} points to pass</p>\n'
            f'<p id="start-number" class="minor">{_e(upcoming)}</p>\n'
            '<button type="button" id="start-button" class="big" autofocus>Start</button>'
        ),
        ask=(
            '<h1 class="title">Click the words that need a capital letter</h1>\n'
            '<p id="sentence" class="sentence"></p>\n'
            '<div id="feedback" aria-live="polite"></div>\n'
            '<button type="button" id="submit" class="big" disabled>Submit</button>\n'
            '<button type="button" id="next" class="big" disabled hidden>Next Question</button>'
        ),
        ends=_help_html(help_points(body))
        + (
            '<section id="failed" class="screen end" hidden>\n'
            "<h1>The sentences are finished</h1>\n"
            '<p id="failed-points"></p>\n'
            f"{end_links()}\n"
            "</section>\n"
        ),
        style=_STYLE,
        script=_MODEL + _SCRIPT,
        line=line,
    )


_HELP_POINTS = (
    ("first_word", "The first word of a sentence starts with a capital letter.", (("The", True), ("dog ran home.", False))),
    ("i", "The word \u201cI\u201d is always a capital letter.", (("Can", False), ("I", True), ("have a snack?", False))),
    ("people", "Names of people start with a capital letter.", (("We saw", False), ("Mia", True), ("at the park.", False))),
    ("pets", "Names of pets start with a capital letter.", (("Our dog is called", False), ("Rex", True), (".", None))),
    (
        "places",
        "Names of places, like towns, countries, and streets, start with a capital letter.",
        (("We drove to", False), ("Sydney", True), ("today.", False)),
    ),
    (
        "days",
        "Days of the week start with a capital letter.",
        (("We are going to the zoo on", False), ("Tuesday", True), (".", None)),
    ),
    ("months", "Months of the year start with a capital letter.", (("My birthday is in", False), ("May", True), (".", None))),
    ("holidays", "Holidays start with a capital letter.", (("We eat cake at", False), ("Christmas", True), (".", None))),
    (
        "titles",
        "A title used with a name, like Dr or Mr, starts with a capital letter.",
        (("We saw", False), ("Dr", True), ("Patel today.", False)),
    ),
    (
        "capitals",
        "Short names made of capital letters, like NASA, are all capitals.",
        (("My uncle works for", False), ("NASA", True), (".", None)),
    ),
    (
        "many_rules",
        "Many of these rules can be in one sentence.",
        (("On", True), ("Tuesday", True), (",", None), ("Mia", True), ("and", False), ("I", True), ("flew to", False), ("Sydney", True), (".", None)),
    ),
)


def _example(parts: tuple) -> str:
    """Return an example sentence with the word that shows the point in blue. A part with None joins the word before it."""
    out = []
    for text, blue in parts:
        if blue is None:
            out[-1] += _e(text)
            continue
        out.append(f'<span class="blue">{_e(text)}</span>' if blue else _e(text))
    return " ".join(out)


def _help_html(points: tuple[str, ...] = HELP_POINTS) -> str:
    """Return the Help button and page with the points a task shows, in page order."""
    items = "\n".join(
        f'<li><p class="rule">{_e(rule)}</p><p class="example">{_example(parts)}</p></li>'
        for point, rule, parts in _HELP_POINTS
        if point in points
    )
    return (
        '<button type="button" id="help-button" class="practice" hidden>Help</button>\n'
        '<div id="help" role="dialog" aria-label="Capital letters help" hidden>\n'
        '<div id="help-body">\n<h1>Where do capital letters go?</h1>\n'
        f"<ol>\n{items}\n</ol>\n</div>\n"
        '<div id="help-footer"><button type="button" id="help-back" class="big">Back to my sentence</button></div>\n'
        "</div>\n"
    )


_STYLE = """\
#help { position: fixed; top: 0; left: 0; right: 0; bottom: 2rem; z-index: 5; background: var(--page-bg); display: flex; flex-direction: column; }
#help-body { flex: 1; overflow-y: auto; padding: 1rem 8rem 1rem 1.5rem; text-align: left; }
#help-body h1 { font-size: 2.2rem; margin: 0 0 1rem; }
#help-body ol { margin: 0; padding-left: 1.6rem; }
#help-body li { margin-bottom: 1rem; }
#help .rule { font-size: 1.6rem; margin: 0; }
#help .example { font-size: 1.8rem; margin: 0.2rem 0 0; color: var(--strong-text); }
#help .example .blue { color: var(--entry); }
#help-footer { padding: 0.6rem; text-align: center; border-top: 1px solid var(--control-border); }
#help-button { z-index: 6; }
.minor { font-size: 1.4rem !important; color: var(--muted); }
#ask { width: min(100%, 72rem); display: flex; flex-direction: column; align-items: center; }
#ask .title { font-size: 2.2rem; margin: 0 0 1.2rem; }
#ask { user-select: none; -webkit-user-select: none; }
.sentence { font-size: 3rem; line-height: 1.6; margin: 0 0 1.5rem; overflow-wrap: anywhere; max-width: 100%; color: var(--strong-text); }
.word { border-radius: 6px; padding: 0 0.06em; }
#ask:not(.locked) .word.can { cursor: pointer; }
#ask:not(.locked) .word.can:hover { background: var(--highlight); }
.word.blue { color: var(--entry); }
.word.red { color: var(--mark); }
#submit, #next { margin-top: 1rem; }
#submit:disabled, #next:disabled { background: var(--accent-disabled); cursor: default; }
"""

_MODEL = """\
  const model = {
    key(clicked) {
      return [...clicked].sort((left, right) => left - right).join(",");
    },
    canSubmit(view) {
      return view.phase === "asking" && !view.confirming && view.clicked.size > 0
        && model.key(view.clicked) !== view.lastWrong;
    },
    wrongText(wrong, missed) {
      const parts = [];
      if (wrong) parts.push(wrong === 1 ? "1 word shouldn't have a capital." : wrong + " words shouldn't have capitals.");
      if (missed) parts.push(missed === 1 ? "You missed 1 capital." : "You missed " + missed + " capitals.");
      parts.push("Try again.");
      return parts.join(" ");
    },
    pointsText(points, required) {
      return points + " / " + required + " points";
    },
    questionsText(number, minimum, maximum) {
      const next = Math.min(number + 1, maximum);
      if (minimum === maximum) return "Question " + next + " of " + maximum;
      return "Question " + next + " · " + minimum + " minimum · " + maximum + " maximum";
    },
    progressText(now) {
      return model.pointsText(now.points, now.required) + " \\u00b7 " + now.required + " to pass \\u00b7 "
        + model.questionsText(now.number, now.minimum, now.maximum);
    },
  };
  if (typeof window !== "undefined") window.capitalisation = model;
"""

_SCRIPT = """\
  const sentence = $("sentence"), submitButton = $("submit"), nextButton = $("next");
  let current = null;
  let phase = "start";
  let clicked = new Set();
  let lastWrong = null;
  let spans = [];
  let shownAnswer = null;
  let deadline = 0;
  let expiry = null;
  let timing = false;
  let lateExpiry = false;
  let ending = null;
  let guardTimer = null;
  let waitTimer = null;

  function view() {
    return { phase, clicked, lastWrong, confirming: !confirmBox.hidden };
  }

  const helpBox = $("help"), helpButton = $("help-button"), helpBack = $("help-back");

  function refresh() {
    submitButton.disabled = !model.canSubmit(view());
    helpButton.hidden = !(phase === "start" || phase === "waiting" || phase === "asking");
    if (helpButton.hidden) closeHelp();
  }

  function openHelp() {
    helpBox.hidden = false;
    helpBack.focus();
  }

  function closeHelp() {
    if (helpBox.hidden) return;
    helpBox.hidden = true;
    if (!helpButton.hidden) helpButton.blur();
  }

  function refocus() {
    refresh();
    if (phase === "reveal" && !nextButton.disabled) nextButton.focus();
  }

  function counts(now) {
    progress.textContent = model.progressText(now);
  }

  function end(result) {
    phase = "done";
    refresh();
    timing = false;
    clearTimeout(expiry);
    if (result.result === "pass") {
      finish(result, null);
      return;
    }
    $("failed-points").textContent =
      model.pointsText(result.points, result.required) + ". You needed " + result.required + " to pass.";
    finish(result, $("failed"));
  }

  const visited = config.ended
    ? Promise.resolve(null)
    : post("visit").then((now) => {
        if (!now) return null;
        if (now.finished) {
          end(now);
          return null;
        }
        $("start-points").textContent = model.pointsText(now.points, now.required);
        $("start-required").textContent = now.required + " points to pass";
        $("start-number").textContent = model.questionsText(now.number, now.minimum, now.maximum);
        counts(now);
        return now;
      });

  function build(question) {
    sentence.textContent = "";
    spans = [];
    question.words.forEach((word, id) => {
      if (id) sentence.appendChild(document.createTextNode(" "));
      const span = document.createElement("span");
      span.className = "word";
      span.dataset.word = String(id);
      span.textContent = word.text;
      spans.push(span);
      sentence.appendChild(span);
    });
    clicked = new Set(question.clicks || []);
    lastWrong = question.clicks ? model.key(clicked) : null;
    shownAnswer = null;
  }

  function render() {
    askScreen.classList.toggle("locked", phase !== "asking");
    spans.forEach((span, id) => {
      const word = current.words[id];
      if (shownAnswer) {
        const item = shownAnswer[id];
        span.textContent = item.word;
        span.className = "word " + item.colour;
        return;
      }
      const on = clicked.has(id);
      span.textContent = on ? word.shown : word.text;
      span.className = "word" + (on ? " blue" : "") + (phase === "asking" && word.click ? " can" : "");
    });
    refresh();
  }

  sentence.addEventListener("click", (event) => {
    if (phase !== "asking") return;
    const span = event.target.closest(".word");
    if (!span || !sentence.contains(span)) return;
    const id = Number(span.dataset.word);
    if (!current.words[id].click) return;
    if (clicked.has(id)) clicked.delete(id);
    else clicked.add(id);
    render();
  });

  async function ask() {
    phase = "waiting";
    if (!(await visited)) return;
    const next = await post("question");
    if (!next) return;
    if (next.finished) {
      end(next);
      return;
    }
    current = next;
    counts(next);
    build(next);
    startScreen.hidden = true;
    askScreen.hidden = false;
    progress.hidden = false;
    timer.hidden = false;
    submitButton.hidden = false;
    nextButton.hidden = true;
    nextButton.disabled = true;
    feedback.className = next.clicks ? "incorrect" : "";
    feedback.textContent = next.clicks ? model.wrongText(next.wrong, next.missed) : "";
    deadline = performance.now() + next.left_ms;
    lateExpiry = false;
    timing = true;
    clearTimeout(expiry);
    expiry = setTimeout(expire, next.left_ms);
    phase = "asking";
    render();
    if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
    requestAnimationFrame(tick);
  }

  function tick() {
    if (!timing) return;
    const left = Math.max(0, deadline - performance.now());
    bar.style.width = (100 * left / current.allowed_ms) + "%";
    requestAnimationFrame(tick);
  }

  function expire() {
    if (phase === "asking") submit(true);
    else if (phase === "waiting") lateExpiry = true;
  }

  async function submit(expired) {
    if (phase !== "asking") return;
    if (!expired && (!helpBox.hidden || !model.canSubmit(view()))) return;
    phase = "waiting";
    if (expired) closeHelp();
    render();
    if (expired) bar.style.width = "0%";
    const sent = new Set(clicked);
    const result = await post("answer", { id: current.id, clicks: [...sent].sort((a, b) => a - b), expired: expired });
    if (!result) return;
    play(result.sound);
    counts(result);
    if (result.outcome === "wrong") {
      feedback.className = "incorrect";
      feedback.textContent = model.wrongText(result.wrong, result.missed);
      lastWrong = model.key(sent);
      phase = "asking";
      render();
      if (lateExpiry || performance.now() >= deadline) submit(true);
      return;
    }
    timing = false;
    clearTimeout(expiry);
    ending = result;
    shownAnswer = result.answer || null;
    if (result.outcome === "correct") {
      phase = "feedback";
      render();
      feedback.className = "correct";
      feedback.textContent = "Correct!";
      setTimeout(onward, config.correctPause);
      return;
    }
    reveal(result);
  }

  function reveal(result) {
    phase = "reveal";
    render();
    timer.hidden = true;
    feedback.className = result.outcome;
    feedback.textContent = (result.outcome === "timeout" ? "Time ran out." : "Not quite.") + " Here is the answer.";
    submitButton.hidden = true;
    nextButton.hidden = false;
    nextButton.disabled = true;
    if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
    guardTimer = setTimeout(() => {
      if (phase !== "reveal") return;
      nextButton.disabled = false;
      if (confirmBox.hidden) nextButton.focus();
    }, config.nextGuardMs);
    waitTimer = setTimeout(onward, config.nextWaitMs);
  }

  function onward() {
    clearTimeout(guardTimer);
    clearTimeout(waitTimer);
    if (phase !== "feedback" && phase !== "reveal") return;
    const result = ending;
    ending = null;
    nextButton.disabled = true;
    if (result.finished) end(result);
    else ask();
  }

  for (const button of [submitButton, nextButton]) {
    button.addEventListener("keydown", (event) => {
      if (event.key === "Enter") event.preventDefault();
    });
  }
  submitButton.addEventListener("click", () => submit(false));
  nextButton.addEventListener("click", () => {
    if (phase === "reveal" && !nextButton.disabled) onward();
  });
  giveUp.addEventListener("click", refresh);

  helpButton.addEventListener("click", () => (helpBox.hidden ? openHelp() : closeHelp()));
  helpBack.addEventListener("click", closeHelp);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeHelp();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || phase === "start" || phase === "done") return;
    if (!helpBox.hidden) return;
    if (event.target === giveUp || confirmBox.contains(event.target)) return;
    if (event.target && event.target.classList && event.target.classList.contains("next-task")) return;
    event.preventDefault();
    if (event.repeat || !confirmBox.hidden) return;
    if (phase === "asking") submit(false);
    else if (phase === "reveal" && !nextButton.disabled) onward();
  });
  document.addEventListener("keydown", (event) => {
    if (phase !== "reveal" && phase !== "feedback") return;
    if (event.key === "Tab" || event.target === giveUp || confirmBox.contains(event.target)) return;
    if (event.target === nextButton && event.key === " ") return;
    event.preventDefault();
  });
  startButton.addEventListener("click", () => {
    if (phase === "start") ask();
  });
  if (config.ended) end({ ...config.ended, points: config.points, required: config.required, total: config.total });
  else {
    startButton.focus();
    refresh();
  }
"""
