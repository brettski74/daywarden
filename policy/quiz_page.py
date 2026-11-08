"""What the timed quiz pages share: the page shell, its script, and JSON replies.

Each quiz page is one document with a start screen, a question screen, a
"Well done" screen, a timer bar, and "Try a different task" with an in-page
confirmation. A browser ``confirm()`` would freeze the timer. The shared
script reads the page's config, posts ``?do=`` requests to the task URL,
plays one sound at a time, and shows an end screen with "Next task" or "All
done for now". When a pass comes with the page he was sent away from, the
"Well done" screen says it is going back there, and opens it after
``BACK_DELAY_MS``, or at once on "Go now" or Enter. "Next task" stops that.
Tab and Shift+Tab cycle through the page's own visible, usable controls and wrap round, instead of leaving for the browser's
toolbar. Landing in a text box selects what is in it, so typing replaces it. The quiz's own script defines ``refocus()``, which is called
when the confirmation is cancelled.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime

from policy.hierarchy import Policy
from policy.report import PageResponse, _e, _response
from policy.selection import picker_url
from policy.tasks import PASS, AttemptStore, household_day

VISIT = "visit"
QUESTION = "question"
ANSWER = "answer"
BACK_DELAY_MS = 5000

Back = Callable[[], str | None]


def next_task_url(policy: Policy, store: AttemptStore, client_group: str, now: datetime) -> str | None:
    """Return the picker when a task is available, or None when there is nothing."""
    if not store.task_sets(policy.tasks, client_group, household_day(now)).available:
        return None
    return picker_url(policy)


def ending(
    policy: Policy | None,
    store: AttemptStore,
    client_group: str,
    now: datetime,
    verdict: str,
    back: Back | None,
) -> dict:
    """Return where the end screen leads: ``next`` is the next task, ``back`` the page he was sent away from.

    ``back`` is only asked after a pass, once the pass is stored.
    """
    return {
        "next": None if policy is None else next_task_url(policy, store, client_group, now),
        "back": back() if verdict == PASS and back is not None else None,
    }


def reload() -> PageResponse:
    """Tell the page to load again, because the question it holds is gone."""
    return json_response(409, {"reload": True})


def json_response(status: int, payload: Mapping) -> PageResponse:
    return _response(status, json.dumps(payload), (("content-type", "application/json"),))


def end_links() -> str:
    """Return the "All done for now" line and the "Next task" link an end screen holds."""
    return '<p class="all-done" hidden>All done for now</p>\n<a class="big next-task" href="#" hidden>Next task</a>'


def document(
    *,
    title: str,
    config: Mapping,
    header: str,
    start: str,
    ask: str,
    script: str,
    style: str = "",
    ends: str = "",
) -> str:
    """Return a quiz page.

    ``header`` sits between the progress line and "Try a different task".
    ``start`` and ``ask`` are the insides of the start and question screens.
    ``ends`` is any end screen besides "Well done". ``script`` runs after
    the shared script, inside the same function.
    """
    data = json.dumps(config).replace("</", "<\\/")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>{_e(title)}</title>
<style>
{SHELL_STYLE}{style}</style>
</head>
<body>
<header>
{header}
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
{start}
</section>
<section id="ask" hidden>
{ask}
</section>
<section id="done" class="screen end" hidden>
<h1>Well done</h1>
<p id="going-back" hidden>Going back to <span id="back-host"></span></p>
<button type="button" id="go-now" class="big" hidden>Go now</button>
<p class="all-done" hidden>All done for now</p>
<a class="big next-task" id="next-task" href="#" hidden>Next task</a>
</section>
{ends}</main>
<div id="timer" hidden><div id="bar"></div></div>
<script type="application/json" id="quiz-config">{data}</script>
<script>
(() => {{
{SHELL_SCRIPT}{script}}})();
</script>
</body>
</html>
"""


def note_html(note: str) -> str:
    return f'<p class="note">{_e(note)}</p>\n' if note else ""


SHELL_STYLE = """\
html, body { height: 100%; margin: 0; }
body { display: flex; flex-direction: column; font-family: sans-serif; background: #fbfbf7; color: #222; }
header { display: flex; justify-content: space-between; align-items: center; padding: 0.6rem 1rem; min-height: 2rem; }
#progress { font-size: 1.1rem; color: #555; }
#give-up { margin-left: auto; font-size: 0.85rem; padding: 0.3rem 0.7rem; background: none; border: 1px solid #aaa; border-radius: 4px; color: #555; cursor: pointer; }
main { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; padding: 1rem; }
.screen h1 { font-size: 4rem; margin: 0 0 1rem; }
.screen p { font-size: 1.8rem; margin: 0 0 2rem; }
.note { color: #b42318; }
.big { font-size: 2rem; padding: 0.5em 1.6em; border: none; border-radius: 10px; background: #2f6fd6; color: #fff; cursor: pointer; text-decoration: none; }
#go-now { margin-right: 0.6rem; }
#feedback { min-height: 3rem; font-size: 2.2rem; margin-top: 1.5rem; font-weight: bold; }
#feedback.correct { color: #1a7f37; }
#feedback.incorrect, #feedback.timeout { color: #b42318; }
#timer { height: 2rem; background: #e4e4e4; }
#bar { height: 100%; width: 100%; background: #2f6fd6; }
#confirm { position: fixed; top: 3rem; right: 1rem; background: #fff; border: 1px solid #aaa; border-radius: 6px; padding: 0.8rem 1rem; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2); }
#confirm button { margin: 0.5rem 0.3rem 0 0; font-size: 1rem; }
.hidden-label { position: absolute; left: -10000px; }
[hidden] { display: none !important; }
"""

SHELL_SCRIPT = f"""\
  const BACK_DELAY = {BACK_DELAY_MS};
""" + """\
  const config = JSON.parse(document.getElementById("quiz-config").textContent);
  const $ = (id) => document.getElementById(id);
  const startScreen = $("start"), askScreen = $("ask"), doneScreen = $("done");
  const startButton = $("start-button");
  const feedback = $("feedback"), progress = $("progress"), timer = $("timer"), bar = $("bar");
  const giveUp = $("give-up"), confirmBox = $("confirm"), form = $("give-up-form");
  const player = new Audio();
  let state = "start";

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

  const goNow = $("go-now"), nextTask = $("next-task");
  let backTo = null;
  let backTimer = null;

  function goBack() {
    if (!backTo) return;
    const target = backTo;
    backTo = null;
    clearTimeout(backTimer);
    window.location.assign(target);
  }

  function stayHere() {
    backTo = null;
    clearTimeout(backTimer);
  }

  function finish(next, screen, back) {
    state = "done";
    screen = screen || doneScreen;
    const returning = Boolean(back) && screen === doneScreen;
    for (const section of document.querySelectorAll("main > section")) section.hidden = section !== screen;
    timer.hidden = true;
    giveUp.hidden = true;
    confirmBox.hidden = true;
    const link = screen.querySelector(".next-task");
    if (next) {
      link.href = next;
      link.hidden = false;
      link.focus();
    } else if (!returning) {
      screen.querySelector(".all-done").hidden = false;
    }
    if (returning) {
      backTo = back;
      $("back-host").textContent = new URL(back).host;
      $("going-back").hidden = false;
      goNow.hidden = false;
      goNow.focus();
      backTimer = setTimeout(goBack, BACK_DELAY);
    }
  }

  goNow.addEventListener("click", goBack);
  nextTask.addEventListener("click", stayHere);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || !backTo || event.repeat || document.activeElement === nextTask) return;
    event.preventDefault();
    goBack();
  });

  function land(element) {
    element.focus();
    if (element.tagName === "INPUT") element.select();
  }

  function tabStops() {
    return [...document.querySelectorAll("button, input, a[href]")].filter(
      (element) => !element.disabled && !element.readOnly && element.tabIndex >= 0 && element.getClientRects().length > 0
    );
  }

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Tab" || event.ctrlKey || event.altKey || event.metaKey) return;
    event.preventDefault();
    const stops = tabStops();
    if (!stops.length) return;
    const step = event.shiftKey ? -1 : 1;
    const here = stops.indexOf(document.activeElement);
    const next = here === -1 ? (step > 0 ? 0 : stops.length - 1) : (here + step + stops.length) % stops.length;
    land(stops[next]);
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
    refocus();
  });

"""
