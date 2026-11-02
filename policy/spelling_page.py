"""The child-facing spelling page and the requests it makes.

The page is the quiz shell from ``policy.quiz_page`` with two audio buttons
and one large text box. Its script reports a page load with
``POST ?do=visit``, asks for each word with ``POST ?do=question``, reports
each "Repeat word" or "Use in a sentence" with ``POST ?do=replay``, and
sends each spelling with ``POST ?do=answer``. The word audio is served from
``<task URL>/audio/<token>.<ext>``, so the rule that lets the page load also
lets the audio through, and the URL says nothing about the word.

Closing a question left showing finishes it, so a reload or a give-up can
be what passes the attempt. Every request that closes one checks.
"""

from __future__ import annotations

import json
import random
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from policy.hierarchy import Policy
from policy.quiz import StaleQuestion
from policy.quiz_page import (
    ANSWER,
    QUESTION,
    VISIT,
    document,
    json_response,
    next_task_url,
    note_html,
    reload,
)
from policy.report import PageResponse, _e, _response
from policy.selection import task_media_path
from policy.sounds import SoundSets
from policy.spelling import (
    LABEL,
    Clip,
    Session,
    find_clip,
    media_name,
    missed_words,
    parse_settings,
    read_media_name,
)
from policy.tasks import ABANDONED, Attempt, AttemptStore, Task

__all__ = ["REPLAY", "give_up_page", "media", "reload", "respond_api", "settle", "show"]

REPLAY = "replay"
FEEDBACK_PAUSE_MS = 4000
AUDIO_GRACE_MS = 5000
MISSED_COLUMNS = 3

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
) -> PageResponse:
    """Return the start screen with the progress a visit now would show.

    Nothing is stored unless ``record`` is set, which is how a refused
    give-up closes the question that was showing. When that passes the
    attempt, the page opens on its end screen.
    """
    session = Session(attempt.detail, task.document(), _RNG)
    session.visit(now)
    ended = None
    if record:
        verdict = session.verdict()
        if verdict is None:
            store.save(attempt.id, session.detail)
        else:
            ended = _conclude(policy, store, attempt, session, verdict, now)
    config = {
        "action": path,
        **session.progress(),
        "feedbackPause": FEEDBACK_PAUSE_MS,
        "audioGrace": AUDIO_GRACE_MS,
        "ended": ended,
    }
    return _response(200, _document(session, config, note))


def settle(task: Task, detail: Mapping, now: datetime) -> tuple[dict, str]:
    """Return the detail with a question left showing closed as a timeout, and how giving up ends.

    Giving up is an abandonment, unless closing that question is what
    passes the attempt.
    """
    session = Session(detail, task.document(), _RNG)
    session.settle(now)
    verdict = session.verdict()
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
) -> PageResponse:
    """Record a page load, issue a word, record a replay, or judge a spelling, and answer with JSON."""
    attempt = store.in_progress(client_group, task.name)
    if attempt is None:
        return reload()
    rng = rng or _RNG
    session = Session(attempt.detail, task.document(), rng)
    if action in (VISIT, QUESTION):
        session.visit(now)
        verdict = session.verdict()
        if verdict is not None:
            ended = _conclude(policy, store, attempt, session, verdict, now)
            return json_response(200, {**session.progress(), "finished": True, **ended})
        if action == VISIT:
            store.save(attempt.id, session.detail)
            return json_response(200, {**session.progress(), "finished": False})
        question = session.issue(now)
        store.save(attempt.id, session.detail)
        return json_response(200, {**_question(session, task, question, rng), "finished": False})
    if action not in (ANSWER, REPLAY):
        return json_response(404, {"error": "unknown request"})
    try:
        sent = json.loads(body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return json_response(400, {"error": "the request is not JSON"})
    if not isinstance(sent, dict):
        return json_response(400, {"error": "the request is not a JSON object"})
    number = sent.get("id")
    if isinstance(number, bool) or not isinstance(number, int):
        return json_response(400, {"error": "the request names no question"})
    try:
        if action == REPLAY:
            played = session.replay(now, number, sent.get("clip"))
        else:
            judged = session.answer(now, number, sent.get("answer"), expired=sent.get("expired") is True)
    except StaleQuestion:
        store.save(attempt.id, session.detail)
        return reload()
    except ValueError as exc:
        return json_response(400, {"error": str(exc)})
    if action == REPLAY:
        store.save(attempt.id, session.detail)
        return json_response(
            200, {"word_replays": played["word_replays"], "sentence_plays": played["sentence_plays"]}
        )
    ended = {"result": None, "next": None, "missed": []}
    if judged.verdict is None:
        store.save(attempt.id, session.detail)
    else:
        ended = _conclude(policy, store, attempt, session, judged.verdict, now)
    return json_response(
        200,
        {
            "outcome": judged.outcome,
            "word": judged.word,
            **session.progress(),
            "finished": judged.verdict is not None,
            **ended,
            "sound": (sounds or _NO_SOUNDS).choose(judged.outcome),
        },
    )


def media(task: Task, name: str) -> Path | None:
    """Return the audio file an ``audio/<token>...`` URL of this task names, or None."""
    found = read_media_name(name)
    if found is None:
        return None
    pool, key, sentence, extension = found
    try:
        settings = parse_settings(task.document())
    except ValueError:
        return None
    return find_clip(settings, pool, key, sentence=sentence, extension=extension)


def give_up_page(detail: Mapping, location: str | None, nothing: str) -> PageResponse | None:
    """Return the missed-words screen shown after giving up, or None when he missed nothing.

    "Continue" goes on to ``location``, or says ``nothing`` when no other
    task is available.
    """
    words = missed_words(detail)
    if not words:
        return None
    target = json.dumps(location).replace("</", "<\\/")
    return _response(
        200,
        f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>{_e(LABEL)}</title>
<style>
body {{ font-family: sans-serif; background: #fbfbf7; color: #222; text-align: center; margin: 0; padding: 3rem 1rem; }}
h1 {{ font-size: 3rem; margin: 0 0 2rem; }}
p {{ font-size: 1.8rem; }}
.big {{ display: inline-block; font-size: 2rem; padding: 0.5em 1.6em; border: none; border-radius: 10px; background: #2f6fd6; color: #fff; cursor: pointer; text-decoration: none; }}
{_MISSED_STYLE}[hidden] {{ display: none !important; }}
</style>
</head>
<body>
<section id="review">
<h1>Words to practise</h1>
{_missed_list(words)}
<button type="button" id="continue" class="big" autofocus>Continue</button>
</section>
<p id="nothing" hidden>{_e(nothing)}</p>
<script>
(() => {{
  const next = {target};
  const button = document.getElementById("continue");
  let gone = false;
  function onward() {{
    if (gone) return;
    gone = true;
    if (next) {{
      window.location.href = next;
      return;
    }}
    document.getElementById("review").hidden = true;
    document.getElementById("nothing").hidden = false;
  }}
  button.addEventListener("click", onward);
  document.addEventListener("keydown", (event) => {{
    if (event.key !== "Enter") return;
    event.preventDefault();
    if (!event.repeat) onward();
  }});
  button.focus();
}})();
</script>
</body>
</html>
""",
    )


def _missed_list(words: list[str]) -> str:
    items = "".join(f"<li>{_e(word)}</li>" for word in words)
    return f'<ul id="missed-words" style="--columns: {min(MISSED_COLUMNS, len(words))}">{items}</ul>'


def _question(session: Session, task: Task, question: Mapping, rng: random.Random) -> dict:
    """Return what the page needs to ask a word, without the word or its length."""
    settings = session.settings
    pool, key = question["pool"], question["key"]
    word = session.word(pool, key)
    base = task_media_path(task.name)
    sentence = None
    if word["sentence"] is not None:
        sentence = base + media_name(key, pool, Clip(word["sentence"], word["sentence_ms"]), sentence=True, rng=rng)
    return {
        "id": len(session.questions) - 1,
        "word_url": base + media_name(key, pool, Clip(word["clip"], word["clip_ms"]), sentence=False, rng=rng),
        "word_ms": word["clip_ms"],
        "sentence_url": sentence,
        "sentence_ms": word["sentence_ms"],
        "timeout_ms": question["timeout_ms"],
        "maximum_replays": settings.maximum_replays,
        "maximum_sentence_plays": settings.maximum_sentence_plays,
        **session.progress(),
    }


def _conclude(policy, store: AttemptStore, attempt: Attempt, session: Session, verdict: str, now: datetime) -> dict:
    store.finish(attempt.id, verdict, now, detail=session.detail)
    following = None if policy is None else next_task_url(policy, store, attempt.client_group, now)
    return {"result": verdict, "next": following, "missed": missed_words(session.detail)}


def progress_text(progress: Mapping) -> str:
    return (
        f"Current: {progress['current']} / {progress['current_required']} \u00b7 "
        f"Revision: {progress['revision']} / {progress['revision_required']}"
    )


def _document(session: Session, config: Mapping, note: str) -> str:
    shown = _e(progress_text(session.progress()))
    return document(
        title=LABEL,
        config=config,
        header=f'<span id="progress" hidden>{shown}</span>\n<span></span>',
        start=(
            f"<h1>{_e(LABEL)}</h1>\n"
            f'{note_html(note)}<p id="start-progress">{shown}</p>\n'
            '<button type="button" id="start-button" class="big" autofocus>Start</button>'
        ),
        ask=(
            '<div class="clips">\n'
            '<button type="button" id="repeat" class="clip" disabled>Repeat word</button>\n'
            '<button type="button" id="say-sentence" class="clip" disabled>Use in a sentence</button>\n'
            "</div>\n"
            '<div class="entry">\n'
            '<label for="answer" class="hidden-label">Spelling</label>\n'
            '<input id="answer" type="text" autocomplete="off" autocapitalize="none" autocorrect="off" '
            'spellcheck="false" maxlength="40" disabled>\n'
            '<div id="reveal" aria-live="polite"></div>\n'
            '<div id="feedback" aria-live="polite"></div>\n'
            "</div>"
        ),
        ends=(
            '<section id="missed" class="screen end" hidden>\n'
            "<h1>Words to practise</h1>\n"
            '<ul id="missed-words"></ul>\n'
            '<button type="button" id="missed-continue" class="big">Continue</button>\n'
            "</section>\n"
        ),
        style=_STYLE,
        script=_SCRIPT,
    )


_MISSED_STYLE = """\
#missed-words { display: grid; grid-template-columns: repeat(var(--columns, 3), minmax(4em, max-content)); justify-content: center;
  gap: 0.5em 1.6em; list-style: none; padding: 0; margin: 0 0 2.5rem; font-size: min(2.6rem, 3.2vw); font-weight: bold; text-align: left; }
"""

_STYLE = (
    """\
#ask:not([hidden]) { align-self: stretch; flex: 1; display: flex; flex-direction: column; }
.clips { display: flex; justify-content: space-between; gap: 1rem; }
.clip { font-size: 1.8rem; font-weight: bold; padding: 0.6em 1.2em; border-radius: 12px; color: #1d4ed8; background: #dbeafe;
  border: 3px solid #93c5fd; cursor: pointer; }
.clip:hover:not(:disabled) { border-color: #2563eb; }
.clip:disabled { color: #9ca3af; background: #e5e7eb; border-color: #d1d5db; cursor: default; }
.entry { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; }
#answer { box-sizing: content-box; width: 18ch; font: bold min(3.5rem, 5vw) ui-monospace, "DejaVu Sans Mono", Menlo, Consolas, monospace;
  padding: 0.2em 0.4em; text-align: center; border: 3px solid #888; border-radius: 10px; background: #fff; color: #222; }
#answer:disabled { background: #f1f1ea; }
#reveal { min-height: 3.6rem; font-size: 3rem; font-weight: bold; color: #1a7f37; margin-top: 1.2rem; }
"""
    + _MISSED_STYLE
)

_SCRIPT = """\
  const box = $("answer"), repeatButton = $("repeat"), sentenceButton = $("say-sentence"), reveal = $("reveal");
  const missedScreen = $("missed"), missedList = $("missed-words"), missedContinue = $("missed-continue");
  const voice = new Audio();
  let current = null;
  let plays = { word: 0, sentence: 0 };
  let left = 0;
  let since = null;
  let expiry = null;
  let listening = 0;
  let afterMissed = null;

  function progressText(now) {
    return "Current: " + now.current + " / " + now.current_required +
      " \\u00b7 Revision: " + now.revision + " / " + now.revision_required;
  }

  function counts(now) {
    progress.textContent = progressText(now);
  }

  function remaining() {
    return since === null ? left : Math.max(0, left - (performance.now() - since));
  }

  function runTimer() {
    since = performance.now();
    expiry = setTimeout(expire, left);
    requestAnimationFrame(tick);
  }

  function pauseTimer() {
    left = remaining();
    since = null;
    clearTimeout(expiry);
  }

  function tick() {
    if (!current) return;
    bar.style.width = (100 * remaining() / current.timeout_ms) + "%";
    if (since !== null) requestAnimationFrame(tick);
  }

  function usable(kind) {
    if (kind === "word") return plays.word < current.maximum_replays;
    return current.sentence_url !== null && plays.sentence < current.maximum_sentence_plays;
  }

  function controls(on) {
    box.disabled = !on;
    repeatButton.disabled = !(on && usable("word"));
    sentenceButton.disabled = !(on && usable("sentence"));
  }

  function typeHere() {
    box.focus();
    const end = box.value.length;
    box.setSelectionRange(end, end);
  }

  function refocus() {
    if (state === "asking") typeHere();
  }

  function listen(url, ms, done) {
    const turn = ++listening;
    let over = false;
    const heard = () => {
      if (over || turn !== listening) return;
      over = true;
      clearTimeout(guard);
      done();
    };
    const guard = setTimeout(heard, ms + config.audioGrace);
    voice.onended = heard;
    voice.onerror = heard;
    voice.src = url;
    const started = voice.play();
    if (started) started.catch(heard);
  }

  function resume() {
    if (state !== "listening") return;
    state = "asking";
    controls(true);
    typeHere();
    runTimer();
  }

  function end(result) {
    const missed = result.missed || [];
    if (!missed.length) {
      finish(result.next);
      return;
    }
    state = "missed";
    for (const section of document.querySelectorAll("main > section")) section.hidden = section !== missedScreen;
    timer.hidden = true;
    giveUp.hidden = true;
    confirmBox.hidden = true;
    missedList.textContent = "";
    missedList.style.setProperty("--columns", Math.min(3, missed.length));
    for (const word of missed) {
      const item = document.createElement("li");
      item.textContent = word;
      missedList.appendChild(item);
    }
    afterMissed = result.next;
    missedContinue.focus();
  }

  function onward() {
    if (state === "missed") finish(afterMissed);
  }

  const visited = config.ended
    ? Promise.resolve(null)
    : post("visit").then((now) => {
        if (!now) return null;
        if (now.finished) {
          end(now);
          return null;
        }
        $("start-progress").textContent = progressText(now);
        counts(now);
        return now;
      });

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
    plays = { word: 0, sentence: 0 };
    counts(next);
    startScreen.hidden = true;
    askScreen.hidden = false;
    progress.hidden = false;
    timer.hidden = false;
    feedback.className = "";
    feedback.textContent = "";
    reveal.textContent = "";
    box.value = "";
    controls(false);
    left = next.timeout_ms;
    since = null;
    bar.style.width = "100%";
    state = "listening";
    listen(next.word_url, next.word_ms, resume);
  }

  function replay(kind) {
    if (state !== "asking" || !usable(kind)) return;
    plays[kind] += 1;
    pauseTimer();
    state = "listening";
    controls(false);
    post("replay", { id: current.id, clip: kind });
    if (kind === "word") listen(current.word_url, current.word_ms, resume);
    else listen(current.sentence_url, current.sentence_ms, resume);
  }

  function expire() {
    if (state === "asking") submit(true);
  }

  async function submit(expired) {
    if (state !== "asking") return;
    state = "waiting";
    pauseTimer();
    controls(false);
    if (expired) bar.style.width = "0%";
    const result = await post("answer", { id: current.id, answer: box.value, expired: expired });
    if (!result) return;
    state = "feedback";
    play(result.sound);
    counts(result);
    feedback.className = result.outcome;
    if (result.outcome === "correct") {
      feedback.textContent = "Correct!";
    } else {
      feedback.textContent = result.outcome === "timeout" ? "Time ran out" : "Not quite";
      if (result.word) reveal.textContent = result.word;
    }
    setTimeout(() => (result.finished ? end(result) : ask()), config.feedbackPause);
  }

  box.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      if (!event.repeat && box.value.trim() !== "") submit(false);
      return;
    }
    if (event.key.length !== 1 || event.ctrlKey || event.metaKey || event.altKey) return;
    if (!/[A-Za-z'\\u2019-]/.test(event.key)) event.preventDefault();
  });
  box.addEventListener("input", () => {
    const clean = box.value.replace(/\\u2019/g, "'").replace(/[^A-Za-z'-]/g, "");
    if (clean !== box.value) box.value = clean;
  });
  repeatButton.addEventListener("click", () => replay("word"));
  sentenceButton.addEventListener("click", () => replay("sentence"));
  missedContinue.addEventListener("click", onward);
  document.addEventListener("keydown", (event) => {
    if (state !== "missed" || event.key !== "Enter") return;
    event.preventDefault();
    if (!event.repeat) onward();
  });
  startButton.addEventListener("click", () => {
    if (state === "start") ask();
  });
  if (config.ended) end(config.ended);
  else startButton.focus();
"""
