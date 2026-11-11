"""The child-facing spelling page and the requests it makes.

The page is the quiz shell from ``policy.quiz_page`` with two audio buttons
and one large text box. Its script reports a page load with
``POST ?do=visit``, asks for each word with ``POST ?do=question``, reports
each "Repeat word" or "Use in a sentence" with ``POST ?do=replay``, sends
each spelling with ``POST ?do=answer``, and starts practice mode with
``POST ?do=practice``. The word audio is served from
``<task URL>/audio/<token>.<ext>``, so the rule that lets the page load also
lets the audio through, and the URL says nothing about the word. Letter
clips for practice are ``<task URL>/audio/alphabet.<file>``.

Closing a question left showing finishes it, so a reload or a give-up can
be what passes the attempt. Every request that closes one checks.
"""

from __future__ import annotations

import json
import random
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from policy.child_page import head, html_tag, line_html
from policy.hierarchy import Policy
from policy.quiz import StaleQuestion
from policy.quiz_page import (
    ANSWER,
    QUESTION,
    VISIT,
    Back,
    document,
    ending,
    json_response,
    note_html,
    reload,
)
from policy.report import PageResponse, _e, _response
from policy.selection import task_media_path
from policy.sounds import SoundSets
from policy.spelling import (
    ALPHABET_MEDIA,
    LABEL,
    WORD_CLIP,
    Clip,
    Session,
    alphabet_media_name,
    character_name,
    find_alphabet_clip,
    find_clip,
    media_name,
    missed_words,
    parse_settings,
    practice_plan,
    read_media_name,
)
from policy.tasks import ABANDONED, Attempt, AttemptStore, Task

__all__ = ["PRACTICE", "REPLAY", "give_up_page", "media", "reload", "respond_api", "settle", "show"]

REPLAY = "replay"
PRACTICE = "practice"
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
    back: Back | None = None,
    line: str = "",
) -> PageResponse:
    """Return the start screen with the progress a visit now would show.

    Nothing is stored unless ``record`` is set, which is how a refused
    give-up closes the question that was showing. When that passes the
    attempt, the page opens on its end screen. ``line`` says the attempt
    doesn't count right now.
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
        **session.progress(),
        "feedbackPause": FEEDBACK_PAUSE_MS,
        "audioGrace": AUDIO_GRACE_MS,
        "ended": ended,
    }
    return _response(200, _document(session, config, note, line))


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
    back: Back | None = None,
) -> PageResponse:
    """Record a page load, issue a word, record a replay, or judge a spelling, and answer with JSON."""
    attempt = store.in_progress(client_group, task.key)
    if attempt is None:
        return reload()
    rng = rng or _RNG
    session = Session(attempt.detail, task.document(), rng)
    if action in (VISIT, QUESTION):
        session.visit(now)
        verdict = session.verdict()
        if verdict is not None:
            ended = _conclude(policy, store, attempt, session, verdict, now, back)
            return json_response(200, {**session.progress(), "finished": True, **ended})
        if action == VISIT:
            store.save(attempt.id, session.detail)
            return json_response(200, {**session.progress(), "finished": False})
        question = session.issue(now)
        store.save(attempt.id, session.detail)
        return json_response(200, {**_question(session, task, question, rng), "finished": False})
    if action == PRACTICE:
        chosen, alphabet = session.practice(now)
        store.save(attempt.id, session.detail)
        words = [_practice_word(session, task, pool, key, alphabet, rng) for pool, key in chosen]
        return json_response(200, {"practice": words, **session.progress(), "finished": False})
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
    ended = {"result": None, "next": None, "practice": None, "back": None, "missed": []}
    if judged.verdict is None:
        store.save(attempt.id, session.detail)
    else:
        ended = _conclude(policy, store, attempt, session, judged.verdict, now, back)
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
    """Return the audio file an ``audio/<token>...`` or ``audio/alphabet.<file>`` URL of this task names, or None."""
    try:
        settings = parse_settings(task.document())
    except ValueError:
        return None
    if name.startswith(ALPHABET_MEDIA):
        return find_alphabet_clip(settings, name)
    found = read_media_name(name)
    if found is None:
        return None
    pool, key, sentence, extension = found
    return find_clip(settings, pool, key, sentence=sentence, extension=extension)


def give_up_page(detail: Mapping, location: str, line: str = "") -> PageResponse | None:
    """Return the missed-words screen shown after giving up, or None when he missed nothing.

    "Continue" goes on to ``location``, the task selector. ``line`` says the
    attempt given up didn't count right now.
    """
    words = missed_words(detail)
    if not words:
        return None
    target = json.dumps(location).replace("</", "<\\/")
    return _response(
        200,
        f"""<!DOCTYPE html>
{html_tag(line)}
<head>
{head(LABEL, _REVIEW_STYLE)}
</head>
<body>
{line_html(line)}<section id="review">
<h1>Words to practise</h1>
{_missed_list(words)}
<button type="button" id="continue" class="big" autofocus>Continue</button>
</section>
<script>
(() => {{
  const next = {target};
  const button = document.getElementById("continue");
  let gone = false;
  function onward() {{
    if (gone) return;
    gone = true;
    window.location.href = next;
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
    base = task_media_path(task.key)
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


def _practice_word(
    session: Session, task: Task, pool: str, key: str, alphabet: Mapping[str, Clip], rng: random.Random
) -> dict:
    """Return one practice word and each clip to play for it, with the pause before each in milliseconds."""
    word = session.word(pool, key)
    base = task_media_path(task.key)
    spoken = base + media_name(key, pool, Clip(word["clip"], word["clip_ms"]), sentence=False, rng=rng)
    clips = {WORD_CLIP: (spoken, word["clip_ms"])}
    for character in word["word"]:
        letter = alphabet[character_name(character)]
        clips[character_name(character)] = (base + alphabet_media_name(letter), letter.ms)
    settings = session.settings
    plan = practice_plan(word["word"], settings.letter_pause, settings.word_pause)
    steps = [{"url": clips[clip][0], "ms": clips[clip][1], "pause": pause} for clip, pause in plan]
    return {"word": word["word"], "steps": steps}


def _conclude(
    policy, store: AttemptStore, attempt: Attempt, session: Session, verdict: str, now: datetime, back: Back | None
) -> dict:
    store.finish(attempt.id, verdict, now, detail=session.detail)
    return {
        "result": verdict,
        **ending(policy, store, attempt.client_group, now, verdict, back),
        "missed": missed_words(session.detail),
    }


def progress_text(progress: Mapping) -> str:
    return (
        f"Current: {progress['current']} / {progress['current_required']} \u00b7 "
        f"Revision: {progress['revision']} / {progress['revision_required']}"
    )


def _document(session: Session, config: Mapping, note: str, line: str) -> str:
    shown = _e(progress_text(session.progress()))
    return document(
        title=LABEL,
        config=config,
        header=f'<span id="progress" hidden>{shown}</span>\n<span></span>',
        start=(
            f"<h1>{_e(LABEL)}</h1>\n"
            f'{note_html(note)}<p id="start-progress">{shown}</p>\n'
            '<button type="button" id="start-button" class="big" autofocus>Start</button>\n'
            '<button type="button" id="practice-start" class="practice">Practice</button>'
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
            "</div>\n"
            '<button type="button" id="practice-ask" class="practice">Practice</button>'
        ),
        ends=(
            '<section id="practise" hidden>\n'
            '<div id="practice-word"></div>\n'
            '<div class="prompt-line"><p id="practice-prompt" hidden>Say and spell the word until you know it.</p></div>\n'
            '<button type="button" id="practice-next" class="clip" disabled>Next</button>\n'
            "</section>\n"
            '<section id="missed" class="screen end" hidden>\n'
            "<h1>Words to practise</h1>\n"
            '<ul id="missed-words"></ul>\n'
            '<button type="button" id="missed-continue" class="big">Continue</button>\n'
            "</section>\n"
            '<div id="practice-confirm" role="dialog" aria-label="Practice" hidden>\n'
            "<div>Start practice mode? Your current quiz progress will be reset.</div>\n"
            '<button type="button" id="practice-yes">Yes, practice</button>\n'
            '<button type="button" id="practice-no">No, keep going</button>\n'
            "</div>\n"
        ),
        style=_STYLE,
        script=_SCRIPT,
        line=line,
    )


_REVIEW_STYLE = """\
body { font-family: sans-serif; background: var(--page-bg); color: var(--text); text-align: center; margin: 0; padding: 0 1rem 3rem; }
#review { padding-top: 3rem; }
h1 { font-size: 3rem; margin: 0 0 2rem; }
.big { display: inline-block; font-size: 2rem; padding: 0.5em 1.6em; border: none; border-radius: 10px; background: var(--accent); color: var(--on-accent); cursor: pointer; text-decoration: none; }
[hidden] { display: none !important; }
"""

_MISSED_STYLE = """\
#missed-words { display: grid; grid-template-columns: repeat(var(--columns, 3), minmax(4em, max-content)); justify-content: center;
  gap: 0.5em 1.6em; list-style: none; padding: 0; margin: 0 0 2.5rem; font-size: min(2.6rem, 3.2vw); font-weight: bold; text-align: left; }
"""

_STYLE = (
    """\
#ask:not([hidden]) { align-self: stretch; flex: 1; display: flex; flex-direction: column; }
.clips { display: flex; justify-content: space-between; gap: 1rem; }
.clip { font-size: 1.8rem; font-weight: bold; padding: 0.6em 1.2em; border-radius: 12px; color: var(--accent-strong); background: var(--accent-soft);
  border: 3px solid var(--accent-edge); cursor: pointer; }
.clip:hover:not(:disabled) { border-color: var(--accent-hover); }
.clip:disabled { color: var(--disabled-text); background: var(--disabled-bg); border-color: var(--disabled-edge); cursor: default; }
.entry { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; }
#answer { box-sizing: content-box; width: 18ch; font: bold min(3.5rem, 5vw) ui-monospace, "DejaVu Sans Mono", Menlo, Consolas, monospace;
  padding: 0.2em 0.4em; text-align: center; border: 3px solid var(--field-border); border-radius: 10px; background: var(--surface); color: var(--text); }
#answer:disabled { background: var(--given-bg); }
#reveal { min-height: 3.6rem; font-size: 3rem; font-weight: bold; color: var(--right); margin-top: 1.2rem; }
.practice { position: fixed; right: 1rem; bottom: 2.8rem; font-size: 1.1rem; padding: 0.35rem 1rem; background: var(--surface);
  border: 1px solid var(--control-border); border-radius: 6px; color: var(--soft-text); cursor: pointer; }
.practice:disabled { color: var(--control-border); cursor: default; }
#practice-confirm { position: fixed; right: 1rem; bottom: 5.6rem; max-width: 22rem; background: var(--surface); border: 1px solid var(--control-border);
  border-radius: 6px; padding: 0.8rem 1rem; box-shadow: 0 2px 8px var(--shadow); text-align: left; }
#practice-confirm button { margin: 0.5rem 0.3rem 0 0; font-size: 1rem; }
#practise:not([hidden]) { display: flex; flex-direction: column; align-items: center; }
#practice-word { font-size: min(9rem, 9vw); font-weight: bold; line-height: 1.2; overflow-wrap: anywhere; }
.prompt-line { min-height: 4rem; margin: 1.5rem 0; }
#practice-prompt { font-size: 2rem; margin: 0; }
#practice-next { font-size: 2.2rem; min-width: 8em; }
"""
    + _MISSED_STYLE
)

_SCRIPT = """\
  const box = $("answer"), repeatButton = $("repeat"), sentenceButton = $("say-sentence"), reveal = $("reveal");
  const missedScreen = $("missed"), missedList = $("missed-words"), missedContinue = $("missed-continue");
  const practiceScreen = $("practise"), practiceWord = $("practice-word"), practicePrompt = $("practice-prompt");
  const practiceNext = $("practice-next"), practiceBox = $("practice-confirm");
  const practiceButtons = [$("practice-start"), $("practice-ask")];
  const voice = new Audio();
  let current = null;
  let plays = { word: 0, sentence: 0 };
  let left = 0;
  let since = null;
  let expiry = null;
  let listening = 0;
  let afterMissed = null;
  let inflight = Promise.resolve();
  let attemptOver = false;
  let entering = false;
  let nextTimer = null;
  let practiceWords = [];
  let practiceAt = 0;
  let sequenceTurn = 0;

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
    attemptOver = true;
    practiceBox.hidden = true;
    const missed = result.missed || [];
    if (!missed.length) {
      finish(result, null);
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
    afterMissed = result;
    missedContinue.focus();
  }

  function onward() {
    if (state === "missed") finish(afterMissed, null);
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
  inflight = visited;

  async function ask() {
    state = "waiting";
    practiceNext.disabled = true;
    if (!(await visited)) return;
    inflight = post("question");
    const next = await inflight;
    if (!next) return;
    if (next.finished) {
      end(next);
      return;
    }
    current = next;
    plays = { word: 0, sentence: 0 };
    counts(next);
    startScreen.hidden = true;
    practiceScreen.hidden = true;
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
    inflight = post("replay", { id: current.id, clip: kind });
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
    inflight = post("answer", { id: current.id, answer: box.value, expired: expired });
    const result = await inflight;
    if (!result) return;
    state = "feedback";
    if (result.finished) {
      attemptOver = true;
      practiceBox.hidden = true;
      for (const button of practiceButtons) button.disabled = true;
    }
    play(result.sound);
    counts(result);
    feedback.className = result.outcome;
    if (result.outcome === "correct") {
      feedback.textContent = "Correct!";
    } else {
      feedback.textContent = result.outcome === "timeout" ? "Time ran out" : "Not quite";
      if (result.word) reveal.textContent = result.word;
    }
    nextTimer = setTimeout(() => (result.finished ? end(result) : ask()), config.feedbackPause);
  }

  function sequence(steps, done) {
    const turn = ++sequenceTurn;
    let index = 0;
    const step = () => {
      if (turn !== sequenceTurn) return;
      if (index >= steps.length) {
        done();
        return;
      }
      const clip = steps[index++];
      setTimeout(() => {
        if (turn === sequenceTurn) listen(clip.url, clip.ms, step);
      }, clip.pause);
    };
    step();
  }

  function showPracticeWord() {
    const item = practiceWords[practiceAt];
    state = "practice";
    progress.textContent = "Practice: " + (practiceAt + 1) + " of " + practiceWords.length;
    practiceWord.textContent = item.word;
    practicePrompt.hidden = true;
    practiceNext.textContent = practiceAt === practiceWords.length - 1 ? "Start quiz" : "Next";
    practiceNext.disabled = true;
    sequence(item.steps, () => {
      state = "practised";
      practicePrompt.hidden = false;
      practiceNext.disabled = false;
      practiceNext.focus();
    });
  }

  async function enterPractice() {
    practiceBox.hidden = true;
    if (entering || state === "practice" || state === "practised") return;
    entering = true;
    await inflight;
    if (attemptOver) return;
    clearTimeout(nextTimer);
    pauseTimer();
    listening += 1;
    voice.pause();
    controls(false);
    state = "practice";
    const reply = await post("practice");
    entering = false;
    if (!reply) return;
    current = null;
    practiceWords = reply.practice;
    practiceAt = 0;
    startScreen.hidden = true;
    askScreen.hidden = true;
    timer.hidden = true;
    feedback.className = "";
    feedback.textContent = "";
    reveal.textContent = "";
    if (!practiceWords.length) {
      ask();
      return;
    }
    practiceScreen.hidden = false;
    progress.hidden = false;
    showPracticeWord();
  }

  function advance() {
    if (state !== "practised") return;
    practiceAt += 1;
    if (practiceAt < practiceWords.length) showPracticeWord();
    else ask();
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
  for (const button of [...practiceButtons, $("practice-yes"), $("practice-no")]) {
    button.addEventListener("mousedown", (event) => event.preventDefault());
    button.addEventListener("keydown", (event) => {
      if (event.key === "Enter") event.preventDefault();
    });
  }
  for (const button of practiceButtons) {
    button.addEventListener("click", () => {
      if (attemptOver) return;
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
  practiceNext.addEventListener("click", advance);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || (state !== "missed" && state !== "practice" && state !== "practised")) return;
    event.preventDefault();
    if (event.repeat) return;
    if (state === "missed") onward();
    else advance();
  });
  startButton.addEventListener("click", () => {
    if (state === "start") ask();
  });
  if (config.ended) end(config.ended);
  else startButton.focus();
"""
