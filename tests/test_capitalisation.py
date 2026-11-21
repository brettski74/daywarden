"""S040.1: capitalisation pools, the task body, and the quiz the server judges and times."""

import json
import random
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from conftest import merge_task_types  # noqa: E402
from policy import capitalisation, capitalisation_page, sentence_pools  # noqa: E402
from policy.hierarchy import ConfigError, load  # noqa: E402
from policy.sounds import load_sounds  # noqa: E402
from policy.store import PolicyStore  # noqa: E402
from policy.task_page import respond_task  # noqa: E402
from policy.tasks import AttemptStore, TaskKey  # noqa: E402

ZONE = ZoneInfo("America/Toronto")
YOUNGER = "192.0.2.40"
START = datetime(2026, 11, 2, 16, 0, tzinfo=ZONE)
KEY = TaskKey("capitalisation", "caps")
PLACES = "On Tuesday, Mia and I flew to Sydney."
NASA = "Dr Patel works at NASA in the United States."
# Words that have a capital, by position.
RIGHT = {PLACES: [0, 1, 2, 4, 7], NASA: [0, 1, 4, 7, 8]}
EXAMPLE_POOL = {
    "name": "Names and places",
    "level_of_difficulty": 1,
    "sentences": [PLACES, {"sentence": NASA, "level_of_difficulty": 1.5}],
}
POOL = "Names and places"


def _write_pool(directory: Path, pool: dict, file: str = "names.yaml") -> Path:
    import yaml

    folder = sentence_pools.pools_directory(directory, sentence_pools.CAPITALISATION_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / file
    path.write_text(yaml.safe_dump(pool, sort_keys=False), encoding="utf-8")
    return path


def _house(body: dict) -> str:
    tasks = f"  capitalisation:\n    caps:\n      group: younger\n      body: {json.dumps(body)}\n"
    return f"""\
entry: gate
timezone: America/Toronto
hostname: tasks.example
port: 443
client_groups:
  younger:
    addresses: ["{YOUNGER}"]
tasks:
{merge_task_types(tasks)}rule_sets:
  gate:
    - condition: always
      when_true: {{ action: allow }}
"""


def _load(directory: Path, body: dict | None = None):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "policy.yaml"
    path.write_text(_house(body or {"pools": [POOL]}), encoding="utf-8")
    return load(path)


def _problems(directory: Path, body: dict | None = None) -> str:
    with pytest.raises(ConfigError) as raised:
        _load(directory, body)
    return "\n".join(raised.value.problems)


# Pools and the task body


def test_the_example_pool_loads_and_the_pool_sentence_difficulty_times_the_task_timeout(tmp_path):
    _write_pool(tmp_path, EXAMPLE_POOL)
    policy = _load(tmp_path)
    assert [task.key for task in policy.tasks] == [KEY]
    token = sentence_pools.use_config_root(tmp_path)
    try:
        settings = capitalisation.check_body({"pools": [POOL]})
    finally:
        sentence_pools.reset_config_root(token)
    assert [sentence.text for sentence in settings.sentences] == [PLACES, NASA]
    assert [sentence.difficulty for sentence in settings.sentences] == [1.0, 1.5]
    assert settings.timeout == 60_000
    assert sentence_pools.allowed_ms(1.5, settings.timeout) == 90_000
    assert (settings.required, settings.minimum_questions, settings.maximum_questions) == (2, 2, 2)


@pytest.mark.parametrize(
    ("pool", "says"),
    [
        ({"name": POOL, "sentences": []}, "sentences"),
        ({"name": POOL, "sentences": [""]}, "must not be empty"),
        ({"name": POOL, "sentences": ["   "]}, "must not be empty"),
        ({"name": POOL, "sentences": ["all lower case here"]}, "no capital letter"),
        ({"name": POOL, "sentences": [PLACES, PLACES]}, "is the same as entry 1"),
        ({"name": POOL, "sentences": [PLACES, PLACES.upper().replace("TUESDAY", "tuesday")]}, "is the same as entry 1"),
        ({"name": POOL, "level_of_difficulty": 11, "sentences": [PLACES]}, "level_of_difficulty"),
        ({"name": POOL, "level_of_difficulty": 0.4, "sentences": [PLACES]}, "level_of_difficulty"),
        ({"name": POOL, "sentences": [{"sentence": PLACES, "level_of_difficulty": 10.5}]}, "level_of_difficulty"),
        ({"name": POOL, "sentences": [{"sentence": PLACES, "timeout": "5s"}]}, "timeout: unknown setting"),
    ],
)
def test_a_bad_pool_or_sentence_fails_the_load_naming_the_pool_and_where_it_is(tmp_path, pool, says):
    _write_pool(tmp_path, pool)
    problems = _problems(tmp_path)
    assert says in problems
    assert "names.yaml" in problems or POOL in problems


def test_two_pools_with_the_same_name_fail_the_load_naming_both_files(tmp_path):
    _write_pool(tmp_path, EXAMPLE_POOL, "one.yaml")
    _write_pool(tmp_path, EXAMPLE_POOL, "two.yaml")
    problems = _problems(tmp_path)
    assert "one.yaml" in problems and "two.yaml" in problems and "capitalisation pool" in problems


def test_only_the_pools_a_capitalisation_task_names_are_read(tmp_path):
    _write_pool(tmp_path, EXAMPLE_POOL)
    _write_pool(tmp_path, {"name": "Broken", "sentences": ["no capital here"]}, "broken.yaml")
    assert [task.key for task in _load(tmp_path).tasks] == [KEY]


def test_a_task_that_names_a_pool_which_is_not_there_is_refused(tmp_path):
    assert "unknown pool 'Nowhere'" in _problems(tmp_path, {"pools": ["Nowhere"]})


@pytest.mark.parametrize(
    ("extra", "says"),
    [
        ({"parts_of_speech": ["noun"]}, "parts_of_speech: unknown setting"),
        ({"sentences": [PLACES]}, "sentences: unknown setting"),
        ({"timeout": "soon"}, "timeout"),
        ({"correct_answers_required": 3}, "correct_answers_required: must be a whole number from 1 to 2"),
        ({"minimum_questions": 0}, "minimum_questions"),
        ({"maximum_questions": 3}, "maximum_questions"),
    ],
)
def test_the_task_body_checks_its_fields(tmp_path, extra, says):
    _write_pool(tmp_path, EXAMPLE_POOL)
    assert says in _problems(tmp_path, {"pools": [POOL], **extra})


def test_a_pool_of_parts_of_speech_is_not_a_capitalisation_pool(tmp_path):
    folder = sentence_pools.pools_directory(tmp_path)
    folder.mkdir(parents=True)
    (folder / "x.yaml").write_text(f"name: {POOL}\nsentences: [{PLACES!r}]\n", encoding="utf-8")
    assert "unknown pool" in _problems(tmp_path)


@pytest.mark.parametrize(
    ("word", "clicked"),
    [("NASA", "NASA"), ("Sydney.", "Sydney."), ("flew", "Flew"), ("iPhone", "iPhone"), ("McDonald's", "McDonald's"), ('"hi"', '"Hi"'), ("3", "3"), ("—", "—")],
)
def test_clicking_shows_the_pool_spelling_or_only_a_first_capital(word, clicked):
    assert capitalisation.clicked_form(word) == clicked


# The quiz


class Quiz:
    """One child working through the capitalisation task, on a clock the test sets."""

    def __init__(self, directory: Path, body: dict | None = None, pool: dict = EXAMPLE_POOL, seed: int = 1):
        self.directory = directory
        _write_pool(directory, pool)
        self.path = directory / "policy.yaml"
        self.path.write_text(_house(body or {"pools": [POOL]}), encoding="utf-8")
        self.policy = load(self.path)
        saved = PolicyStore(":memory:")
        self.store = AttemptStore(connection=saved.connection)
        _sounds = directory / "sounds"
        for outcome in ("correct", "incorrect", "timeout"):
            (_sounds / outcome).mkdir(parents=True, exist_ok=True)
            (_sounds / outcome / f"{outcome}.mp3").write_bytes(b"sound")
        self.sounds = load_sounds(_sounds, warn=lambda message: None)
        self.rng = random.Random(seed)

    def _respond(self, now, method, query=None, body=b""):
        saved = capitalisation_page._RNG
        capitalisation_page._RNG = self.rng
        token = sentence_pools.use_config_root(self.directory)
        try:
            return respond_task(
                self.policy,
                self.store,
                method=method,
                path="/tasks/capitalisation/caps",
                client_ip=YOUNGER,
                now=now,
                query=query,
                body=body,
                sounds=self.sounds,
            )
        finally:
            sentence_pools.reset_config_root(token)
            capitalisation_page._RNG = saved

    def open(self, now):
        page = self._respond(now, "GET")
        self.post(now, "visit", {})
        return page

    def give_up(self, now):
        return self._respond(now, "POST")

    def post(self, now, action, payload):
        page = self._respond(now, "POST", {"do": action}, json.dumps(payload).encode())
        return page.status, json.loads(page.body)

    def ask(self, now) -> dict:
        status, payload = self.post(now, "question", {})
        assert status == 200, payload
        return payload

    def send(self, now, question, clicks, *, expired=False) -> tuple[int, dict]:
        return self.post(now, "answer", {"id": question["id"], "clicks": clicks, "expired": expired})

    def answer(self, now, question, clicks, *, expired=False) -> dict:
        status, payload = self.send(now, question, clicks, expired=expired)
        assert status == 200, payload
        return payload

    def detail(self):
        return self.store.attempts("younger", KEY)[-1].detail

    def text(self, question: dict) -> str:
        return " ".join(word["text"] for word in question["words"])

    def right(self, question: dict) -> list[int]:
        sentence = next(text for text in RIGHT if text.lower() == self.text(question))
        return RIGHT[sentence]


def _first(directory: Path, wanted: str = PLACES, **options) -> tuple[Quiz, dict]:
    """Return a quiz and its first sentence, choosing a seed that asks ``wanted`` first."""
    for seed in range(50):
        quiz = Quiz(directory, seed=seed, **options)
        quiz.open(START)
        question = quiz.ask(START)
        if quiz.text(question) == wanted.lower():
            return quiz, question
        shutil.rmtree(directory)
    raise AssertionError("no seed asks that sentence first")


def test_the_page_sends_the_sentence_in_lower_case_and_never_which_words_need_capitals(tmp_path):
    quiz, question = _first(tmp_path)
    assert quiz.text(question) == "on tuesday, mia and i flew to sydney."
    assert [word["shown"] for word in question["words"]] == [
        "On", "Tuesday,", "Mia", "And", "I", "Flew", "To", "Sydney.",
    ]
    assert all(word["click"] for word in question["words"])
    assert question["allowed_ms"] == 60_000
    assert "capital" not in json.dumps(question) and "answer" not in question


def test_the_start_screen_and_page_have_the_instruction_and_no_drag_code(tmp_path):
    page = Quiz(tmp_path).open(START).body
    assert "Click the words that need a capital letter" in page
    assert "0 / 2 points" in page and "2 points to pass" in page
    assert 'id="submit"' in page and "Try a different task" in page
    assert "wordSort" not in page


def test_a_word_with_no_letter_cannot_be_clicked(tmp_path):
    quiz, question = _first(tmp_path, "Ben has 3 cats — Tom has 4.", pool={"name": POOL, "sentences": ["Ben has 3 cats — Tom has 4."]})
    assert [word["click"] for word in question["words"]] == [True, True, False, True, False, True, True, False]
    assert quiz.text(question) == "ben has 3 cats — tom has 4."


def test_a_harder_sentence_gets_the_task_timeout_times_its_difficulty(tmp_path):
    quiz = Quiz(tmp_path)
    quiz.open(START)
    seen = {}
    now = START
    for _ in range(2):
        question = quiz.ask(now)
        seen[quiz.text(question)] = question["allowed_ms"]
        quiz.answer(now, question, quiz.right(question))
        now += timedelta(seconds=2)
    assert seen == {PLACES.lower(): 60_000, NASA.lower(): 90_000}


def test_a_right_first_try_scores_one_point_and_shows_the_sentence_as_spelled_in_blue(tmp_path):
    quiz, question = _first(tmp_path)
    result = quiz.answer(START, question, quiz.right(question))
    assert result["outcome"] == "correct" and result["scored"] == 1 and result["sound"]
    assert [item["word"] for item in result["answer"]] == PLACES.split()
    colours = {item["word"]: item["colour"] for item in result["answer"]}
    assert colours["Mia"] == "blue" and colours["flew"] == "black"
    assert not [item for item in result["answer"] if item["colour"] == "red"]


@pytest.mark.parametrize(("tries", "scored"), [(1, 0.5), (2, 0.25)])
def test_a_later_right_try_scores_less(tmp_path, tries, scored):
    quiz, question = _first(tmp_path)
    for number in range(tries):
        result = quiz.answer(START, question, [5 + number])
        assert result["outcome"] == "wrong"
    assert quiz.answer(START, question, quiz.right(question))["scored"] == scored


@pytest.mark.parametrize(
    ("clicks", "wrong", "missed"),
    [([5, 6], 2, 5), ([0, 1, 2, 4, 7, 5], 1, 0), ([0, 1, 2], 0, 2), ([0, 1, 2, 3, 4, 7], 1, 0), ([0, 1, 4, 7, 3, 5], 2, 1)],
)
def test_a_wrong_try_counts_clicked_words_without_a_capital_and_capitals_missed(tmp_path, clicks, wrong, missed):
    quiz, question = _first(tmp_path)
    result = quiz.answer(START, question, clicks)
    assert (result["outcome"], result["wrong"], result["missed"], result["try"]) == ("wrong", wrong, missed, 1)
    assert "colour" not in json.dumps(result) and result["answer"] is None


def test_a_wrong_third_try_scores_nothing_and_shows_the_answer_with_red_marks(tmp_path):
    quiz, question = _first(tmp_path)
    quiz.answer(START, question, [5])
    quiz.answer(START, question, [5, 6])
    result = quiz.answer(START, question, [0, 2, 5])
    assert result["outcome"] == "incorrect" and result["scored"] == 0 and result["try"] == 3
    assert [(item["word"], item["colour"]) for item in result["answer"]] == [
        ("On", "blue"),
        ("Tuesday,", "red"),
        ("Mia", "blue"),
        ("and", "black"),
        ("I", "red"),
        ("flew", "red"),
        ("to", "black"),
        ("Sydney.", "red"),
    ]


def test_the_timer_running_out_scores_nothing_and_marks_the_clicks_as_they_stood(tmp_path):
    quiz, question = _first(tmp_path)
    result = quiz.answer(START + timedelta(seconds=59), question, [2, 3], expired=True)
    assert result["outcome"] == "timeout" and result["scored"] == 0 and result["try"] == 1
    colours = {item["word"]: item["colour"] for item in result["answer"]}
    assert colours["Mia"] == "blue" and colours["and"] == "red" and colours["Sydney."] == "red"
    assert colours["flew"] == "black"
    assert quiz.detail()["questions"][0]["tries"][0]["clicks"] == [2, 3]


def test_the_timer_running_out_with_nothing_clicked_is_a_timeout(tmp_path):
    quiz, question = _first(tmp_path)
    result = quiz.answer(START + timedelta(seconds=59), question, [], expired=True)
    assert result["outcome"] == "timeout"
    assert [item["colour"] for item in result["answer"]].count("red") == 5


def test_a_try_after_the_deadline_is_a_timeout_even_when_right(tmp_path):
    quiz, question = _first(tmp_path)
    result = quiz.answer(START + timedelta(seconds=61), question, quiz.right(question))
    assert result["outcome"] == "timeout" and result["scored"] == 0


@pytest.mark.parametrize("clicks", [[], [0, 0], [8], [-1], ["a"], "0", None])
def test_a_try_with_nothing_or_nonsense_is_refused_without_using_a_try(tmp_path, clicks):
    quiz, question = _first(tmp_path)
    status, payload = quiz.send(START, question, clicks)
    assert status == 400 and "error" in payload
    assert quiz.detail()["questions"][0]["tries"] == []


def test_the_clicks_of_the_last_wrong_try_are_refused_until_they_change(tmp_path):
    quiz, question = _first(tmp_path)
    quiz.answer(START, question, [5, 6])
    status, payload = quiz.send(START, question, [6, 5])
    assert status == 400 and "same" in payload["error"]
    assert len(quiz.detail()["questions"][0]["tries"]) == 1
    assert quiz.answer(START, question, [5])["try"] == 2


def test_a_try_for_a_sentence_that_is_not_open_reloads_the_page(tmp_path):
    quiz, question = _first(tmp_path)
    quiz.answer(START, question, quiz.right(question))
    status, payload = quiz.send(START, {"id": question["id"]}, [1])
    assert status == 409 and payload == {"reload": True}


def test_a_reload_brings_back_the_sentence_with_the_tries_used_the_last_clicks_and_their_hint(tmp_path):
    quiz, question = _first(tmp_path)
    quiz.answer(START, question, [5, 6])
    again = quiz.ask(START + timedelta(seconds=20))
    assert again["id"] == question["id"] and quiz.text(again) == quiz.text(question)
    assert again["try"] == 2 and again["clicks"] == [5, 6]
    assert (again["wrong"], again["missed"]) == (2, 5)
    assert again["left_ms"] == 40_000
    assert "colour" not in json.dumps(again)


def test_a_run_asks_every_sentence_once_and_passes_on_enough_points(tmp_path):
    quiz = Quiz(tmp_path)
    quiz.open(START)
    asked = []
    result = {}
    for step in range(2):
        question = quiz.ask(START + timedelta(seconds=step))
        asked.append(quiz.text(question))
        result = quiz.answer(START + timedelta(seconds=step), question, quiz.right(question))
    assert sorted(asked) == sorted(text.lower() for text in RIGHT)
    assert result["finished"] and result["result"] == "pass"
    assert sorted(quiz.detail()["runs"][-1]["asked"]) == [0, 1]


def test_a_run_fails_when_the_pass_mark_is_out_of_reach(tmp_path):
    quiz = Quiz(tmp_path)
    quiz.open(START)
    result = {}
    for step in range(2):
        question = quiz.ask(START + timedelta(seconds=step))
        for _ in range(3):
            result = quiz.answer(START + timedelta(seconds=step), question, [1] if _ == 0 else [1, 2] if _ == 1 else [3])
            if result["outcome"] != "wrong":
                break
    assert result["finished"] and result["result"] == "failure"


def test_giving_up_abandons_the_attempt_and_times_out_the_open_sentence(tmp_path):
    quiz, question = _first(tmp_path)
    quiz.give_up(START + timedelta(seconds=5))
    attempt = quiz.store.attempts("younger", KEY)[-1]
    assert attempt.outcome == "abandoned"
    assert attempt.detail["questions"][0]["outcome"] == "timeout"


def test_a_run_keeps_the_sentences_it_started_with_when_the_pool_is_edited(tmp_path):
    quiz, question = _first(tmp_path)
    _write_pool(tmp_path, {"name": POOL, "sentences": ["Only One Left"]})
    again = quiz.ask(START + timedelta(seconds=1))
    assert quiz.text(again) == quiz.text(question)


CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
HARNESS = ROOT / "tests" / "page_harness.js"


@pytest.mark.skipif(CHROMIUM is None, reason="needs Chromium to lay out the page")
def test_the_page_shades_clicks_and_toggles_words_in_a_real_browser(tmp_path):
    import html
    import re

    quiz, question = _first(tmp_path, "Ben has 3 cats — Tom has 4 NASA.", pool={"name": POOL, "sentences": ["Ben has 3 cats — Tom has 4 NASA."]})
    _status, visit = quiz.post(START, "visit", {})
    script = """\
<script>
const replies = REPLIES;
window.fetch = async (url) => {
  const reply = replies[new URL(url, location.href).searchParams.get("do")].shift();
  return { redirected: false, status: 200, ok: true, headers: { get: () => "application/json" }, json: async () => reply };
};
const wait = (ms) => new Promise((done) => setTimeout(done, ms));
addEventListener("load", async () => {
  await wait(50);
  document.getElementById("start-button").click();
  await wait(50);
  const words = [...document.querySelectorAll("#sentence .word")];
  const seen = { before: words.map((w) => w.textContent).join(" ") };
  const click = (id) => words[id].click();
  click(0); click(2); click(4);
  seen.after = words.map((w) => w.textContent + ":" + w.className.replace("word", "").trim()).join("|");
  click(0);
  seen.toggled = words[0].textContent + ":" + words[0].className;
  seen.submit = document.getElementById("submit").disabled;
  document.getElementById("out").textContent = JSON.stringify(seen);
});
</script>
"""
    page = tmp_path / "caps.html"
    body = quiz.open(START).body
    page.write_text(
        body.replace("<head>", "<head>" + script.replace("REPLIES", json.dumps({"visit": [visit], "question": [question]})))
        .replace("</body>", '<pre id="out"></pre></body>'),
        encoding="utf-8",
    )
    run = subprocess.run(
        [CHROMIUM, "--headless", "--disable-gpu", f"--user-data-dir={tmp_path / 'chromium'}", "--window-size=1280,900", "--virtual-time-budget=5000", "--dump-dom", page.as_uri()],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    seen = json.loads(html.unescape(re.search(r'<pre id="out">(.*?)</pre>', run.stdout, re.S).group(1)))
    assert seen["before"] == "ben has 3 cats — tom has 4 nasa."
    # Words 2 and 4 are "3" and the dash: clicking them does nothing, and they are never shaded.
    assert seen["after"] == "Ben:blue can|has:can|3:|cats:can|—:|tom:can|has:can|4:|nasa.:can"
    assert seen["toggled"] == "ben:word can"
    assert seen["submit"] is True  # nothing is clicked again, so Submit is off


def _rules(page):
    import re

    return re.findall(r'<p class="rule">(.*?)</p>', page)


def test_help_shows_every_point_unless_the_task_lists_some_and_shows_them_in_page_order(tmp_path):
    assert len(_rules(Quiz(tmp_path).open(START).body)) == len(capitalisation.HELP_POINTS)
    shutil.rmtree(tmp_path)
    quiz = Quiz(tmp_path, {"pools": [POOL], "help_points": ["people", "first_word", "i"]})
    rules = _rules(quiz.open(START).body)
    assert [rule.split(" start")[0].split(" is")[0] for rule in rules] == ["The first word of a sentence", "The word \u201cI\u201d", "Names of people"]


@pytest.mark.parametrize("points", [[], "people", ["people", "people"], ["people", "dogs"]])
def test_a_bad_help_points_setting_is_refused(tmp_path, points):
    with pytest.raises(ValueError, match="help_points"):
        capitalisation.parse_settings({"pools": [POOL], "help_points": points})


@pytest.mark.skipif(CHROMIUM is None, reason="needs Chromium to lay out the page")
def test_help_covers_the_sentence_keeps_the_clicks_and_closes_on_timeout_in_a_real_browser(tmp_path):
    import html
    import re

    sentence = "Ben has 3 cats."
    quiz, question = _first(tmp_path, sentence, pool={"name": POOL, "sentences": [sentence]})
    _status, visit = quiz.post(START, "visit", {})
    ended = {"outcome": "timeout", "try": 1, "wrong": None, "missed": None, "answer": [{"word": "Ben", "colour": "blue"}, {"word": "has", "colour": "red"}, {"word": "3", "colour": ""}, {"word": "cats.", "colour": ""}], "scored": 0, "points": 0, "required": 1, "number": 1, "minimum": 1, "maximum": 1, "total": 1, "finished": False, "result": None, "next": None, "practice": None, "back": None, "sound": None}
    script = """\
<script>
const replies = REPLIES;
const log = [];
window.fetch = async (url) => {
  const what = new URL(url, location.href).searchParams.get("do");
  log.push(what);
  const reply = replies[what].shift();
  return { redirected: false, status: 200, ok: true, headers: { get: () => "application/json" }, json: async () => reply };
};
const wait = (ms) => new Promise((done) => setTimeout(done, ms));
const $ = (id) => document.getElementById(id);
addEventListener("load", async () => {
  await wait(50);
  const seen = { startHelp: !$("help-button").hidden };
  $("start-button").click();
  await wait(50);
  const words = [...document.querySelectorAll("#sentence .word")];
  words[0].click();
  $("help-button").click();
  seen.open = !$("help").hidden;
  $("submit").click();
  seen.noSubmit = log.includes("answer");
  const cover = document.elementFromPoint(words[0].getBoundingClientRect().x + 2, words[0].getBoundingClientRect().y + 2);
  seen.covered = $("help").contains(cover);
  seen.backVisible = $("help-back").getBoundingClientRect().bottom <= innerHeight;
  seen.examples = [...document.querySelectorAll("#help .example")].map((e) => e.textContent);
  seen.blue = [...document.querySelectorAll("#help .example .blue")].map((e) => e.textContent).join(",");
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
  seen.closed = $("help").hidden;
  seen.kept = words.map((w) => w.className).join("|");
  $("help-button").click();
  $("help-button").click();
  seen.toggled = $("help").hidden;
  $("help-button").click();
  $("help-back").click();
  $("help-button").click();
  seen.reopen = !$("help").hidden;
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
  seen.enter = log.includes("answer");
  await wait(2500);
  seen.afterTimeout = { help: $("help").hidden, button: $("help-button").hidden, log };
  $("out").textContent = JSON.stringify(seen);
});
</script>
"""
    page = tmp_path / "help.html"
    body = quiz.open(START).body
    question = {**question, "left_ms": 1500}
    page.write_text(
        body.replace("<head>", "<head>" + script.replace("REPLIES", json.dumps({"visit": [visit], "question": [question], "answer": [ended]})))
        .replace("</body>", '<pre id="out"></pre></body>'),
        encoding="utf-8",
    )
    run = subprocess.run(
        [CHROMIUM, "--headless", "--disable-gpu", f"--user-data-dir={tmp_path / 'chromium'}", "--window-size=1280,700", "--virtual-time-budget=8000", "--dump-dom", page.as_uri()],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    seen = json.loads(html.unescape(re.search(r'<pre id="out">(.*?)</pre>', run.stdout, re.S).group(1)))
    assert seen["startHelp"] and seen["open"] and seen["covered"] and seen["backVisible"]
    assert not seen["noSubmit"] and not seen["enter"]
    assert seen["closed"] and seen["toggled"]  # a second click on Help closes it again
    kept = seen["kept"].split("|")
    assert "blue" in kept[0] and "blue" not in kept[1]  # only the word clicked before help is blue
    assert seen["reopen"]
    assert seen["examples"][6] == "My birthday is in May." and seen["examples"][8] == "We saw Dr Patel today."
    assert seen["examples"][10] == "On Tuesday, Mia and I flew to Sydney."
    assert seen["blue"].split(",")[:2] == ["The", "I"]
    assert seen["afterTimeout"]["help"] and seen["afterTimeout"]["button"]
    assert seen["afterTimeout"]["log"].count("answer") == 1


def test_the_attempt_report_can_show_a_capitalisation_attempt(tmp_path):
    from policy.review import attempt_report

    quiz, question = _first(tmp_path)
    quiz.answer(START, question, [5])
    attempt = quiz.store.attempts("younger", KEY)[-1]
    report = json.dumps(attempt_report(quiz.store, str(attempt.id), now=START))
    assert "capitalisation" in report and "clicks" in report


# The attempt in the portal and the MCP tools (S040.2)


def _report(quiz):
    from policy.review import attempt_report

    attempt = quiz.store.attempts("younger", KEY)[-1]
    return attempt_report(quiz.store, str(attempt.id), now=START + timedelta(minutes=10), timezone="America/Toronto")


def test_the_attempts_figures_are_points_against_the_pass_mark_and_questions_against_the_maximum(tmp_path):
    from policy.attempt_figures import figures

    quiz, question = _first(tmp_path)
    quiz.answer(START, question, [5])
    quiz.answer(START, question, quiz.right(question))
    second = quiz.ask(START)
    quiz.answer(START + timedelta(seconds=59), second, [], expired=True)
    found = figures("capitalisation", quiz.detail()).as_json()
    assert (found["points"], found["pass_mark"], found["questions"], found["maximum"]) == (0.5, 2, 2, 2)
    assert (found["wrong"], found["timeouts"]) == (0, 1)
    assert found["time_ms"] > 59_000


def test_the_attempt_page_shows_each_try_with_its_marked_words_points_and_timeout(tmp_path):
    quiz, question = _first(tmp_path)
    quiz.answer(START, question, [5, 0])
    quiz.answer(START + timedelta(seconds=3), question, quiz.right(question))
    second = quiz.ask(START + timedelta(seconds=4))
    quiz.answer(START + timedelta(seconds=63), second, [0], expired=True)
    shown = _report(quiz)["capitalisation"]
    assert shown["expired"] == []
    first, last = shown["last"]["sentences"]
    assert [one["points"] for one in first["tries"]] == [0, 0.5]
    wrong_try, right_try = first["tries"]
    assert {item["colour"] for item in right_try["words"]} == {"blue", "black"}
    assert [item["word"] for item in wrong_try["words"]] == PLACES.split()
    assert [item["colour"] for item in wrong_try["words"]] == ["blue", "red", "red", "black", "red", "red", "black", "red"]
    assert [item["colour"] for item in wrong_try["words"]].count("red") == 5
    assert right_try["taken_ms"] == 3000 and not wrong_try["timeout"]
    assert last["tries"][0]["timeout"] is True and last["outcome"] == "timeout"
    assert shown["last"]["figures"]["points"] == 0.5


def test_the_attempt_report_has_each_tries_clicked_words_in_its_record(tmp_path):
    quiz, question = _first(tmp_path)
    quiz.answer(START, question, [5])
    record = _report(quiz)["record"]
    assert record["questions"][0]["tries"][0]["clicks"] == [5]
