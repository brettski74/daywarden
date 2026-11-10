"""The child-facing parts of speech page and the requests it makes.

The page is the quiz shell from ``policy.quiz_page`` with a sentence whose
words he drags into a table of parts of speech. Its script reports a page
load with ``POST ?do=visit``, asks for each sentence with ``POST
?do=question``, and sends each try with ``POST ?do=answer``. A plain form
post to the same URL is "Try a different task", which ``policy.task_page``
handles.

A page load does not close the open sentence. ``?do=question`` brings it
back with the time left on its deadline, the tries used, and his last
submitted table. Only its deadline, an expired run, or a give-up closes it.
A give-up that is allowed is always an abandonment.
"""

from __future__ import annotations

import json
import random
from collections.abc import Mapping
from datetime import datetime

from policy.hierarchy import Policy
from policy.parts_of_speech import LABEL, WRONG, Session, format_points, segments
from policy.quiz import CORRECT, INCORRECT, TIMEOUT, StaleQuestion
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
from policy.sounds import SoundSets
from policy.tasks import ABANDONED, Attempt, AttemptStore, Task

__all__ = ["reload", "respond_api", "settle", "show"]

CORRECT_PAUSE_MS = 1000
FLIGHT_MS = 600
NEXT_GUARD_MS = 3000
NEXT_WAIT_MS = 15_000
RED_MARKS_TRY = 2

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

    ``line`` says the attempt doesn't count right now.

    Nothing is stored unless ``record`` is set, which is how a refused
    give-up is recorded. It leaves the open sentence open, unless its
    deadline has passed. When closing a sentence past its deadline finishes
    the run, the page opens on its end screen.
    """
    session = Session(attempt.detail, task.document(), _RNG)
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
        "flightMs": FLIGHT_MS,
        "nextGuardMs": NEXT_GUARD_MS,
        "nextWaitMs": NEXT_WAIT_MS,
        "ended": ended,
    }
    return _response(200, _document(session, config, note, line))


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
    attempt = store.in_progress(client_group, task.name)
    if attempt is None:
        return reload()
    session = Session(attempt.detail, task.document(), rng or _RNG)
    if action in (VISIT, QUESTION):
        session.visit(now)
        verdict = session.verdict()
        if verdict is not None:
            ended = _conclude(policy, store, attempt, session, verdict, now, back)
            return json_response(200, {**_progress(session), "finished": True, **ended})
        if action == VISIT:
            store.save(attempt.id, session.detail)
            return json_response(200, {**_progress(session), "finished": False})
        question = session.issue(now)
        store.save(attempt.id, session.detail)
        tries = question["tries"]
        last = tries[-1] if tries else None
        return json_response(
            200,
            {
                "id": len(session.questions) - 1,
                "segments": segments(question["sentence"]),
                "parts": question["parts"],
                "try": len(tries) + 1,
                "allowed_ms": question["allowed_ms"],
                "left_ms": session.left_ms(question, now),
                "table": None if last is None else last["placements"],
                "wrong": None if last is None else last["wrong"],
                "missed": None if last is None else last["missed"],
                **_marks(last if len(tries) == RED_MARKS_TRY else None),
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
        return json_response(400, {"error": "the answer names no sentence"})
    try:
        judged = session.answer(now, number, sent.get("parts"), expired=sent.get("expired") is True)
    except StaleQuestion:
        store.save(attempt.id, session.detail)
        return reload()
    except ValueError as exc:
        return json_response(400, {"error": str(exc)})
    ended = {"result": None, "next": None, "practice": None, "back": None}
    if judged.verdict is None:
        store.save(attempt.id, session.detail)
    else:
        ended = _conclude(policy, store, attempt, session, judged.verdict, now, back)
    sound = CORRECT if judged.outcome == CORRECT else "timeout" if judged.outcome == "timeout" else "incorrect"
    last = judged.question["tries"][-1]
    shown = judged.outcome == WRONG and judged.attempt == RED_MARKS_TRY
    return json_response(
        200,
        {
            "outcome": judged.outcome,
            "try": judged.attempt,
            "wrong": judged.wrong if judged.outcome == WRONG else None,
            "missed": judged.missed if judged.outcome == WRONG else None,
            **_marks(last if shown else None),
            "answer": answer(judged.question) if judged.outcome in (INCORRECT, TIMEOUT) else None,
            "scored": judged.question["points"],
            **_progress(session),
            "finished": judged.verdict is not None,
            **ended,
            "sound": (sounds or _NO_SOUNDS).choose(sound),
        },
    )


def answer(question: Mapping) -> list[dict]:
    """Return, for every word of a finished sentence, the part it belongs in, where he had it, and how that compares.

    ``had`` is ``right``, ``other`` (another row), or ``missed`` for a word
    the task lists, ``extra`` for a word he sorted that belongs in no row,
    and None for a word in no row that he left alone. His table is the last
    try's, or empty when the sentence closed without one.
    """
    tries = question["tries"]
    table = tries[-1]["placements"] if tries else {}
    placed = {position: name for name, numbers in table.items() for position in numbers}
    shown = []
    for position, word in enumerate(question["words"]):
        part, there = word["part"], placed.get(position)
        if part is None:
            had = None if there is None else "extra"
        elif there is None:
            had = "missed"
        else:
            had = "right" if there == part else "other"
        shown.append({"part": part, "placed": there, "had": had})
    return shown


def _marks(last: Mapping | None) -> dict:
    """Return which words to show red: wrong words where he put them, and missed words in the sentence."""
    if last is None:
        return {"wrong_words": None, "missed_words": None}
    return {"wrong_words": list(last["wrong_words"]), "missed_words": list(last["missed_words"])}


def _conclude(
    policy, store: AttemptStore, attempt: Attempt, session: Session, verdict: str, now: datetime, back: Back | None
) -> dict:
    store.finish(attempt.id, verdict, now, detail=session.detail)
    return {"result": verdict, **ending(policy, store, attempt.client_group, now, verdict, back)}


def _progress(session: Session) -> dict:
    return {
        "points": session.points,
        "required": session.settings.required,
        "number": session.number,
        "total": session.total,
    }


def _document(session: Session, config: Mapping, note: str, line: str) -> str:
    progress = _progress(session)
    points = f"{format_points(progress['points'])} / {progress['total']} points"
    upcoming = f"Sentence {min(progress['number'] + 1, progress['total'])} of {progress['total']}"
    return document(
        title=LABEL,
        config=config,
        header='<span id="progress" hidden></span>\n<span></span>',
        start=(
            f"<h1>{_e(LABEL)}</h1>\n"
            f'{note_html(note)}<p id="start-points">{_e(points)}</p>\n'
            f'<p id="start-required" class="minor">{_e(str(progress["required"]))} points to pass</p>\n'
            f'<p id="start-number" class="minor">{_e(upcoming)}</p>\n'
            '<button type="button" id="start-button" class="big" autofocus>Start</button>'
        ),
        ask=(
            '<h1 class="title">Sort the words into the table</h1>\n'
            '<p id="sentence" class="sentence"></p>\n'
            '<table id="table" class="parts"><tbody id="rows"></tbody></table>\n'
            '<div id="feedback" aria-live="polite"></div>\n'
            '<button type="button" id="submit" class="big" disabled>Submit</button>\n'
            '<button type="button" id="next" class="big" disabled hidden>Next Question</button>'
        ),
        ends=(
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


_STYLE = """\
.minor { font-size: 1.4rem !important; color: var(--muted); }
#ask { width: min(100%, 72rem); display: flex; flex-direction: column; align-items: center; }
#ask .title { font-size: 2.2rem; margin: 0 0 1.2rem; }
#ask, .ghost { user-select: none; -webkit-user-select: none; }
.sentence { font-size: 2.5rem; line-height: 1.5; margin: 0 0 1.5rem; white-space: pre-wrap; overflow-wrap: anywhere; max-width: 100%; }
.word, .placed { border-radius: 6px; padding: 0 0.06em; touch-action: none; }
.word.can, #ask:not(.locked) .placed { cursor: grab; }
.word.can:hover, .word.held, .word.lit, .placed.lit, .placed.held { background: var(--highlight); }
body.dragging .word.can:not(.held):hover { background: none; }
body.dragging, body.dragging * { cursor: grabbing !important; }
.parts { width: 100%; border-collapse: collapse; font-size: 2rem; }
.parts th, .parts td { border: 2px solid var(--given-border); padding: 0.2rem 0.6rem; }
.parts th { width: 1%; white-space: nowrap; text-align: left; font-weight: normal; color: var(--soft-text); background: var(--given-bg); }
.parts td { height: 3.75rem; text-align: left; overflow-wrap: anywhere; }
.parts tr.over th, .parts tr.over td { background: var(--accent-soft); }
.ghost { position: fixed; z-index: 10; pointer-events: none; background: transparent; white-space: pre; margin: 0; }
.ghost.flying { transition: left var(--flight) ease-out, top var(--flight) ease-out; }
.red { color: var(--mark); }
.blue { color: var(--entry); }
.answer { color: var(--strong-text); border-radius: 6px; padding: 0 0.15em; }
.answer.right { background: var(--right-soft); }
.answer.other, .answer.extra { background: var(--wrong-soft); }
.answer.missed { background: var(--missed-soft); }
.answer.extra { text-decoration: line-through; }
#submit, #next { margin-top: 1rem; }
#submit:disabled, #next:disabled { background: var(--accent-disabled); cursor: default; }
"""

_MODEL = """\
  const model = {
    empty(parts) {
      const cells = {};
      for (const part of parts) cells[part] = [];
      return cells;
    },
    partOf(cells, id) {
      for (const part of Object.keys(cells)) if (cells[part].includes(id)) return part;
      return null;
    },
    place(cells, id, part) {
      if (model.partOf(cells, id) === part) return cells;
      const next = model.remove(cells, id);
      next[part] = [...next[part], id];
      return next;
    },
    remove(cells, id) {
      const next = {};
      for (const part of Object.keys(cells)) next[part] = cells[part].filter((other) => other !== id);
      return next;
    },
    count(cells) {
      return Object.values(cells).reduce((sum, ids) => sum + ids.length, 0);
    },
    same(left, right) {
      if (!left || !right || model.count(left) !== model.count(right)) return false;
      return Object.keys(left).every((part) => left[part].every((id) => model.partOf(right, id) === part));
    },
    canSubmit(view) {
      return view.phase === "asking" && !view.dragging && !view.flying && !view.confirming
        && model.count(view.cells) > 0 && !model.same(view.cells, view.lastWrong);
    },
    marks(cells, wrong, missed) {
      const found = {};
      for (const id of wrong) found[id] = model.partOf(cells, id);
      for (const id of missed) found[id] = null;
      return found;
    },
    colour(marks, cells, id) {
      if (!Object.prototype.hasOwnProperty.call(marks, id)) return "black";
      return model.partOf(cells, id) === marks[id] ? "red" : "blue";
    },
    answerRow(answer, part) {
      const listed = [], extra = [];
      answer.forEach((item, id) => {
        if (item.part === part) listed.push({ id, had: item.had });
        else if (item.part === null && item.placed === part) extra.push({ id, had: "extra" });
      });
      return [...listed, ...extra];
    },
    drop(origin, target) {
      if (target === null) return origin === null ? "back" : "unsort";
      return target === origin ? "stay" : "place";
    },
    wrongText(wrong, missed) {
      const parts = [];
      if (wrong) parts.push(wrong === 1 ? "1 word is in the wrong row." : wrong + " words are in the wrong row.");
      if (missed) parts.push(missed === 1 ? "You missed 1 word." : "You missed " + missed + " words.");
      parts.push("Try again.");
      return parts.join(" ");
    },
    pointsText(points, total) {
      return points + " / " + total + " points";
    },
    progressText(now) {
      return model.pointsText(now.points, now.total) + " \\u00b7 " + now.required + " to pass \\u00b7 Sentence "
        + Math.min(now.number + 1, now.total) + " of " + now.total;
    },
  };
  if (typeof window !== "undefined") window.partsOfSpeech = model;
"""

_SCRIPT = """\
  const sentence = $("sentence"), rows = $("rows"), submitButton = $("submit"), nextButton = $("next");
  let current = null;
  let phase = "start";
  let cells = {};
  let lastWrong = null;
  let marks = {};
  let shownAnswer = null;
  let words = [];
  let deadline = 0;
  let expiry = null;
  let timing = false;
  let lateExpiry = false;
  let press = null;
  let drag = null;
  let flight = null;
  let ending = null;
  let guardTimer = null;
  let waitTimer = null;
  document.documentElement.style.setProperty("--flight", config.flightMs + "ms");

  function view() {
    return {
      phase, cells, lastWrong, dragging: drag !== null, flying: flight !== null, confirming: !confirmBox.hidden,
    };
  }

  function refresh() {
    submitButton.disabled = !model.canSubmit(view());
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
    timing = false;
    clearTimeout(expiry);
    if (result.result === "pass") {
      finish(result, null);
      return;
    }
    $("failed-points").textContent =
      model.pointsText(result.points, result.total) + ". You needed " + result.required + " to pass.";
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
        $("start-points").textContent = model.pointsText(now.points, now.total);
        $("start-required").textContent = now.required + " points to pass";
        $("start-number").textContent = "Sentence " + (now.number + 1) + " of " + now.total;
        counts(now);
        return now;
      });

  function sentenceWord(id) {
    return words[id];
  }

  function cellWord(id) {
    return rows.querySelector('.placed[data-word="' + id + '"]');
  }

  function build(question) {
    sentence.textContent = "";
    words = [];
    for (const piece of question.segments) {
      if (piece.word === undefined) {
        sentence.appendChild(document.createTextNode(piece.text));
        continue;
      }
      const span = document.createElement("span");
      span.className = "word";
      span.dataset.word = String(piece.word);
      span.textContent = piece.text;
      words[piece.word] = span;
      sentence.appendChild(span);
    }
    rows.textContent = "";
    for (const part of question.parts) {
      const row = document.createElement("tr");
      row.dataset.part = part;
      const label = document.createElement("th");
      label.textContent = part;
      const cell = document.createElement("td");
      row.appendChild(label);
      row.appendChild(cell);
      rows.appendChild(row);
    }
    cells = model.empty(question.parts);
    lastWrong = null;
    marks = {};
    shownAnswer = null;
    if (question.table) {
      for (const part of question.parts) for (const id of question.table[part] || []) cells = model.place(cells, id, part);
      lastWrong = cells;
    }
    if (question.wrong_words) marks = model.marks(cells, question.wrong_words, question.missed_words);
  }

  function paint(span, id) {
    span.classList.remove("red", "blue");
    const colour = model.colour(marks, cells, id);
    if (colour !== "black") span.classList.add(colour);
  }

  function render() {
    askScreen.classList.toggle("locked", phase !== "asking");
    words.forEach((span, id) => {
      span.classList.toggle("can", phase === "asking" && model.partOf(cells, id) === null);
      span.classList.remove("red", "blue");
      if (model.partOf(cells, id) === null) paint(span, id);
    });
    for (const row of rows.querySelectorAll("tr")) {
      const cell = row.querySelector("td");
      cell.textContent = "";
      if (shownAnswer) {
        model.answerRow(shownAnswer, row.dataset.part).forEach((item, index) => {
          if (index) cell.appendChild(document.createTextNode(", "));
          const span = document.createElement("span");
          span.className = "answer " + item.had;
          span.textContent = sentenceWord(item.id).textContent;
          cell.appendChild(span);
        });
        continue;
      }
      cells[row.dataset.part].forEach((id, index) => {
        if (index) cell.appendChild(document.createTextNode(", "));
        const span = document.createElement("span");
        span.className = "placed";
        span.dataset.word = String(id);
        span.textContent = sentenceWord(id).textContent;
        paint(span, id);
        cell.appendChild(span);
      });
    }
    refresh();
  }

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
    feedback.className = next.table ? "incorrect" : "";
    feedback.textContent = next.table ? model.wrongText(next.wrong, next.missed) : "";
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
    if (phase === "asking") {
      cancelDrag();
      arrive();
      submit(true);
    } else if (phase === "waiting") {
      lateExpiry = true;
    }
  }

  async function submit(expired) {
    if (phase !== "asking") return;
    if (!expired && !model.canSubmit(view())) return;
    phase = "waiting";
    render();
    if (expired) bar.style.width = "0%";
    const sent = cells;
    const result = await post("answer", { id: current.id, parts: sent, expired: expired });
    if (!result) return;
    play(result.sound);
    counts(result);
    if (result.outcome === "wrong") {
      feedback.className = "incorrect";
      feedback.textContent = model.wrongText(result.wrong, result.missed);
      lastWrong = sent;
      if (result.wrong_words) marks = model.marks(sent, result.wrong_words, result.missed_words);
      phase = "asking";
      render();
      if (lateExpiry || performance.now() >= deadline) submit(true);
      return;
    }
    timing = false;
    clearTimeout(expiry);
    ending = result;
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
    marks = {};
    shownAnswer = result.answer || null;
    render();
    timer.hidden = true;
    feedback.className = result.outcome;
    feedback.textContent = (result.outcome === "timeout" ? "Time ran out." : "Not quite.")
      + (shownAnswer ? " Here is the answer." : "");
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

  function lit(id, on) {
    const twin = sentenceWord(id);
    const placed = cellWord(id);
    if (twin) twin.classList.toggle("lit", on);
    if (placed) placed.classList.toggle("lit", on);
  }

  function rowAt(x, y) {
    if (x < 0 || y < 0 || x >= window.innerWidth || y >= window.innerHeight) return null;
    const found = document.elementFromPoint(x, y);
    return found ? found.closest("#rows tr") : null;
  }

  function hover(row) {
    for (const other of rows.querySelectorAll("tr.over")) if (other !== row) other.classList.remove("over");
    if (row) row.classList.add("over");
  }

  function pressed(event) {
    if (phase !== "asking" || drag || flight || event.button !== 0) return;
    const target = event.target.closest(".word.can, .placed");
    if (!target) return;
    event.preventDefault();
    press = { id: Number(target.dataset.word), source: target, x: event.clientX, y: event.clientY, pointer: event.pointerId };
  }

  function begin(event) {
    const source = press.source;
    const box = source.getBoundingClientRect();
    const ghost = document.createElement("span");
    ghost.className = "ghost " + (source.classList.contains("placed") ? "placed" : "word");
    for (const colour of ["red", "blue"]) if (source.classList.contains(colour)) ghost.classList.add(colour);
    ghost.textContent = source.textContent;
    const style = getComputedStyle(source);
    ghost.style.font = style.font;
    ghost.style.padding = style.padding;
    ghost.style.left = box.left + "px";
    ghost.style.top = box.top + "px";
    document.body.appendChild(ghost);
    const origin = source.classList.contains("placed") ? model.partOf(cells, press.id) : null;
    drag = { id: press.id, origin, ghost, dx: press.x - box.left, dy: press.y - box.top };
    try {
      source.setPointerCapture(event.pointerId);
    } catch (error) {}
    sentenceWord(drag.id).classList.add("held");
    if (origin !== null) source.classList.add("held");
    document.body.classList.add("dragging");
    press = null;
    refresh();
  }

  function moved(event) {
    if (press && !drag) {
      if (Math.abs(event.clientX - press.x) + Math.abs(event.clientY - press.y) < 4) return;
      begin(event);
    }
    if (!drag) return;
    drag.ghost.style.left = event.clientX - drag.dx + "px";
    drag.ghost.style.top = event.clientY - drag.dy + "px";
    hover(rowAt(event.clientX, event.clientY));
  }

  function released(event, outside) {
    press = null;
    if (!drag) return;
    const row = outside ? null : rowAt(event.clientX, event.clientY);
    const { id, origin, ghost } = drag;
    drag = null;
    hover(null);
    document.body.classList.remove("dragging");
    const target = row ? row.dataset.part : null;
    const action = model.drop(origin, target);
    if (action === "place") {
      ghost.remove();
      cells = model.place(cells, id, target);
      clearShading(id);
      render();
      return;
    }
    if (action === "stay") {
      clearShading(id);
      fly(ghost, cellWord(id), id);
      return;
    }
    if (action === "unsort") {
      clearShading(id);
      cells = model.remove(cells, id);
      render();
    }
    fly(ghost, sentenceWord(id), id);
  }

  function clearShading(id) {
    lit(id, false);
    sentenceWord(id).classList.remove("held");
    const placed = cellWord(id);
    if (placed) placed.classList.remove("held");
  }

  function fly(ghost, home, id) {
    const box = home.getBoundingClientRect();
    flight = { ghost, id, timer: setTimeout(arrive, config.flightMs) };
    ghost.getBoundingClientRect();
    ghost.classList.add("flying");
    ghost.style.left = box.left + "px";
    ghost.style.top = box.top + "px";
    refresh();
  }

  function arrive() {
    if (!flight) return;
    clearTimeout(flight.timer);
    flight.ghost.remove();
    sentenceWord(flight.id).classList.remove("held");
    flight = null;
    render();
  }

  function cancelDrag() {
    press = null;
    if (!drag) return;
    drag.ghost.remove();
    clearShading(drag.id);
    hover(null);
    document.body.classList.remove("dragging");
    drag = null;
  }

  function over(event) {
    if (drag || flight) return;
    const target = event.target.closest(".placed");
    if (target) lit(Number(target.dataset.word), phase === "asking");
  }

  function out(event) {
    if (drag) return;
    const target = event.target.closest(".placed");
    if (target && !target.contains(event.relatedTarget)) lit(Number(target.dataset.word), false);
  }

  sentence.addEventListener("pointerdown", pressed);
  rows.addEventListener("pointerdown", pressed);
  rows.addEventListener("pointerover", over);
  rows.addEventListener("pointerout", out);
  document.addEventListener("pointermove", moved);
  document.addEventListener("pointerup", (event) => released(event, false));
  document.addEventListener("pointercancel", (event) => released(event, true));
  document.addEventListener("dragstart", (event) => event.preventDefault());
  document.addEventListener("selectstart", (event) => {
    if (askScreen.contains(event.target)) event.preventDefault();
  });

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

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || phase === "start" || phase === "done") return;
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
  else startButton.focus();
"""
