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
from policy.report import PageResponse, _e, _response
from policy.selection import choose_task, picker_url
from policy.sounds import SoundSets
from policy.tasks import PASS, Attempt, AttemptStore, Task, household_day

CORRECT_PAUSE_MS = 1000
WRONG_PAUSE_MS = 2500
VISIT = "visit"
QUESTION = "question"
ANSWER = "answer"

_RNG = random.Random()
_NO_SOUNDS = SoundSets()


def show(
    store: AttemptStore,
    task: Task,
    attempt: Attempt,
    *,
    path: str,
    now: datetime,
    note: str = "",
    record: bool = False,
) -> PageResponse:
    """Return the start screen with the progress a visit now would show.

    Nothing is stored unless ``record`` is set, which is how a refused
    give-up closes the question that was showing. Otherwise the script's
    visit request records the page load.
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
    return _response(200, _document(settings.operation.label, session.correct, settings.required, config, note))


def settle(task: Task, detail: Mapping, now: datetime) -> dict:
    """Return the detail with a question left showing closed as a timeout."""
    session = Session(detail, task.document())
    session.settle(now)
    return session.detail


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
) -> PageResponse:
    """Record a page load, issue a question, or judge an answer, and answer with JSON.

    A visit is the page running in a tab. A question that was showing when
    the page was left is a timeout. Coming back more than an hour after the
    last activity starts a new run.
    """
    attempt = store.in_progress(client_group, task.name)
    if attempt is None:
        return reload()
    session = Session(attempt.detail, task.document())
    if action == VISIT:
        session.visit(now)
        store.save(attempt.id, session.detail)
        return _json(200, {"correct": session.correct, "required": session.settings.required})
    if action == QUESTION:
        question = session.issue(now, rng or _RNG)
        store.save(attempt.id, session.detail)
        return _json(
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
        return _json(404, {"error": "unknown request"})
    try:
        sent = json.loads(body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _json(400, {"error": "the answer is not JSON"})
    if not isinstance(sent, dict):
        return _json(400, {"error": "the answer is not a JSON object"})
    number = sent.get("id")
    if isinstance(number, bool) or not isinstance(number, int):
        return _json(400, {"error": "the answer names no question"})
    try:
        judged = session.answer(now, number, sent.get("answer"), expired=sent.get("expired") is True)
    except StaleQuestion:
        store.save(attempt.id, session.detail)
        return reload()
    except ValueError as exc:
        return _json(400, {"error": str(exc)})
    following = None
    if judged.finished:
        store.finish(attempt.id, PASS, now, detail=session.detail)
        following = next_task_url(policy, store, client_group, now)
    else:
        store.save(attempt.id, session.detail)
    question = judged.question
    return _json(
        200,
        {
            "outcome": judged.outcome,
            "full": f"{question['question']} {question['expected']}",
            "correct": judged.correct,
            "required": judged.required,
            "finished": judged.finished,
            "next": following,
            "sound": (sounds or _NO_SOUNDS).choose(judged.outcome),
        },
    )


def next_task_url(policy: Policy, store: AttemptStore, client_group: str, now: datetime) -> str | None:
    """Return the picker when another task is eligible, or None when there is nothing."""
    chosen, _ties = choose_task(policy.tasks, client_group, household_day(now), store.attempts(client_group))
    if chosen is None:
        return None
    return picker_url(policy)


def reload() -> PageResponse:
    """Tell the page to load again, because the question it holds is gone."""
    return _json(409, {"reload": True})


def _json(status: int, payload: Mapping) -> PageResponse:
    return _response(status, json.dumps(payload), (("content-type", "application/json"),))


def _document(label: str, correct: int, required: int, config: Mapping, note: str) -> str:
    data = json.dumps(config).replace("</", "<\\/")
    notice = f'<p class="note">{_e(note)}</p>\n' if note else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>{_e(label)}</title>
<style>
html, body {{ height: 100%; margin: 0; }}
body {{ display: flex; flex-direction: column; font-family: sans-serif; background: #fbfbf7; color: #222; }}
header {{ display: flex; justify-content: space-between; align-items: center; padding: 0.6rem 1rem; min-height: 2rem; }}
#progress {{ font-size: 1.1rem; color: #555; }}
#give-up {{ font-size: 0.85rem; padding: 0.3rem 0.7rem; background: none; border: 1px solid #aaa; border-radius: 4px; color: #555; cursor: pointer; }}
main {{ flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; padding: 1rem; }}
.screen h1 {{ font-size: 4rem; margin: 0 0 1rem; }}
.screen p {{ font-size: 1.8rem; margin: 0 0 2rem; }}
.note {{ color: #b42318; }}
.big {{ font-size: 2rem; padding: 0.5em 1.6em; border: none; border-radius: 10px; background: #2f6fd6; color: #fff; cursor: pointer; text-decoration: none; }}
#question {{ font-size: clamp(3rem, 13vw, 9rem); font-weight: bold; margin: 0 0 2rem; white-space: nowrap; }}
#answer {{ font-size: 3rem; width: 5em; text-align: center; padding: 0.15em; border: 3px solid #888; border-radius: 8px; }}
#feedback {{ min-height: 3rem; font-size: 2.2rem; margin-top: 1.5rem; font-weight: bold; }}
#feedback.correct {{ color: #1a7f37; }}
#feedback.incorrect, #feedback.timeout {{ color: #b42318; }}
#timer {{ height: 2rem; background: #e4e4e4; }}
#bar {{ height: 100%; width: 100%; background: #2f6fd6; }}
#confirm {{ position: fixed; top: 3rem; right: 1rem; background: #fff; border: 1px solid #aaa; border-radius: 6px; padding: 0.8rem 1rem; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2); }}
#confirm button {{ margin: 0.5rem 0.3rem 0 0; font-size: 1rem; }}
.hidden-label {{ position: absolute; left: -10000px; }}
[hidden] {{ display: none !important; }}
</style>
</head>
<body>
<header>
<span id="progress" hidden>{correct} / {required}</span>
<span></span>
<button type="button" id="give-up">Try a different task</button>
</header>
<div id="confirm" role="dialog" aria-label="Try a different task" hidden>
<div>Are you sure?</div>
<button type="button" id="confirm-yes">Yes, try a different task</button>
<button type="button" id="confirm-no">No, keep going</button>
</div>
<form id="give-up-form" method="post" action="{_e(str(config["action"]))}" hidden></form>
<main>
<section id="start" class="screen">
<h1>{_e(label)}</h1>
{notice}<p id="start-progress">{correct} / {required} correct</p>
<button type="button" id="start-button" class="big" autofocus>Start</button>
</section>
<section id="ask" hidden>
<div id="question" aria-live="polite"></div>
<label for="answer" class="hidden-label">Answer</label>
<input id="answer" type="text" inputmode="numeric" pattern="[0-9]*" autocomplete="off" maxlength="12" disabled>
<div id="feedback" aria-live="polite"></div>
</section>
<section id="done" class="screen" hidden>
<h1>Well done</h1>
<p id="all-done" hidden>All done for now</p>
<a id="next-task" class="big" href="#" hidden>Next task</a>
</section>
</main>
<div id="timer" hidden><div id="bar"></div></div>
<script type="application/json" id="quiz-config">{data}</script>
<script>
{_SCRIPT}
</script>
</body>
</html>
"""


_SCRIPT = """\
(() => {
  const config = JSON.parse(document.getElementById("quiz-config").textContent);
  const $ = (id) => document.getElementById(id);
  const startScreen = $("start"), askScreen = $("ask"), doneScreen = $("done");
  const startButton = $("start-button"), questionText = $("question"), box = $("answer");
  const feedback = $("feedback"), progress = $("progress"), timer = $("timer"), bar = $("bar");
  const giveUp = $("give-up"), confirmBox = $("confirm"), form = $("give-up-form");
  const player = new Audio();
  let state = "start";
  let current = null;
  let deadline = 0;
  let expiry = null;

  function counts(correct, required) {
    progress.textContent = correct + " / " + required;
  }

  function play(url) {
    player.pause();
    if (!url) return;
    player.src = url;
    const started = player.play();
    if (started) started.catch(() => {});
  }

  function trouble() {
    feedback.className = "timeout";
    feedback.textContent = "Lost touch with the server. Starting again...";
    setTimeout(() => window.location.reload(), 2500);
  }

  async function post(action, payload) {
    let response;
    try {
      response = await fetch(config.action + "?do=" + action, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload || {}),
        cache: "no-store",
      });
    } catch (error) {
      trouble();
      return null;
    }
    const type = response.headers.get("content-type") || "";
    if (response.redirected || response.status === 409 || !type.startsWith("application/json")) {
      window.location.reload();
      return null;
    }
    if (!response.ok) {
      trouble();
      return null;
    }
    return response.json();
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
    setTimeout(() => (result.finished ? finish(result.next) : ask()), pause);
  }

  function finish(next) {
    state = "done";
    startScreen.hidden = true;
    askScreen.hidden = true;
    timer.hidden = true;
    giveUp.hidden = true;
    confirmBox.hidden = true;
    doneScreen.hidden = false;
    if (next) {
      const link = $("next-task");
      link.href = next;
      link.hidden = false;
      link.focus();
    } else {
      $("all-done").hidden = false;
    }
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
  for (const button of [giveUp, $("confirm-yes"), $("confirm-no")]) {
    button.addEventListener("mousedown", (event) => event.preventDefault());
    button.addEventListener("keydown", (event) => {
      if (event.key === "Enter") event.preventDefault();
    });
  }
  giveUp.addEventListener("click", () => {
    confirmBox.hidden = false;
  });
  $("confirm-yes").addEventListener("click", () => form.submit());
  $("confirm-no").addEventListener("click", () => {
    confirmBox.hidden = true;
    if (state === "asking") box.focus();
  });
  startButton.focus();
})();
"""
