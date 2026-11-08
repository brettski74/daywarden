"""S006.2: the parts of speech quiz, judged and timed by the server."""

import html
import json
import random
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy import parts_of_speech_page  # noqa: E402
from policy.accounts import Accounts  # noqa: E402
from policy.hierarchy import load  # noqa: E402
from policy.review import respond_attempt  # noqa: E402
from policy.sounds import load_sounds  # noqa: E402
from policy.store import PolicyStore  # noqa: E402
from policy.task_page import MUST_FINISH, respond_task  # noqa: E402
from policy.tasks import AttemptStore, household_day, skip_days  # noqa: E402

ZONE = ZoneInfo("America/Toronto")
YOUNGER = "192.0.2.40"
START = datetime(2026, 11, 2, 16, 0, tzinfo=ZONE)
FOX = "The quick, brown fox jumped over the lazy dog."
DRY = "Dry the dishes with a dry towel."
FOX_RIGHT = {"noun": [3, 8], "verb": [4], "adjective": [1, 2, 7]}
DRY_RIGHT = {"verb": [0], "noun": [2, 6], "adjective": [5]}
RIGHT = {FOX: FOX_RIGHT, DRY: DRY_RIGHT}
EXAMPLE = {
    "timeout": "45s",
    "sentences": [
        {"sentence": FOX, "parts": {"noun": ["fox", "dog"], "verb": ["jumped"], "adjective": ["quick", "brown", "lazy"]}},
        {
            "sentence": DRY,
            "timeout": "60s",
            "parts": {"verb": ["dry[1]"], "noun": ["dishes", "towel"], "adjective": ["dry[2]"]},
        },
    ],
}


def _ten(required: int | None = None) -> dict:
    body: dict = {
        "sentences": [{"sentence": f"The cat number {number} sat.", "parts": {"noun": ["cat"]}} for number in range(10)]
    }
    if required is not None:
        body["correct_answers_required"] = required
    return body


def _house(body: dict, *, due: str | None = None, failure_cooldown: int = 0, extra: str = "") -> str:
    due_line = f"    due_date: {due}\n" if due else ""
    return f"""\
entry: gate
timezone: America/Toronto
hostname: tasks.example
port: 443
client_groups:
  younger:
    addresses: ["{YOUNGER}"]
tasks:
  words:
    type: parts_of_speech
    group: younger
    pass_cooldown: 7
    failure_cooldown: {failure_cooldown}
{due_line}    body: {json.dumps(body)}
{extra}rule_sets:
  gate:
    - condition: always
      when_true: {{ action: allow }}
"""


def _sound_dir(root: Path) -> Path:
    for outcome in ("correct", "incorrect", "timeout"):
        (root / outcome).mkdir(parents=True, exist_ok=True)
        (root / outcome / f"{outcome}.mp3").write_bytes(b"sound")
    return root


class Quiz:
    """One child working through the words task, on a clock the test sets."""

    def __init__(self, directory: Path, body: dict = EXAMPLE, *, seed: int = 1, **house):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "policy.yaml"
        path.write_text(_house(body, **house), encoding="utf-8")
        self.policy = load(path)
        self.saved = PolicyStore(":memory:")
        self.store = AttemptStore(connection=self.saved.connection)
        self.sounds = load_sounds(_sound_dir(directory / "sounds"), warn=lambda message: None)
        self.back = None
        self.rng = random.Random(seed)
        self.now = START

    def _respond(self, now, method, query=None, body=b""):
        saved = parts_of_speech_page._RNG
        parts_of_speech_page._RNG = self.rng
        try:
            return respond_task(
                self.policy,
                self.store,
                method=method,
                path="/tasks/words",
                client_ip=YOUNGER,
                now=now,
                query=query,
                body=body,
                sounds=self.sounds,
                back=self.back,
            )
        finally:
            parts_of_speech_page._RNG = saved

    def open(self, now):
        """Load the page in a browser tab: the GET, then the script's visit."""
        page = self._respond(now, "GET")
        status, payload = self.post(now, "visit", {})
        assert status == 200, payload
        return page

    def give_up(self, now):
        return self._respond(now, "POST")

    def post(self, now, action, payload):
        page = self._respond(now, "POST", {"do": action}, json.dumps(payload).encode())
        assert ("content-type", "application/json") in page.headers
        return page.status, json.loads(page.body)

    def ask(self, now) -> dict:
        status, payload = self.post(now, "question", {})
        assert status == 200, payload
        return payload

    def answer(self, now, number, parts, *, expired=False) -> dict:
        status, payload = self.post(now, "answer", {"id": number, "parts": parts, "expired": expired})
        assert status == 200, payload
        return payload

    def attempt(self):
        return self.store.attempts("younger", "words")[-1]

    def detail(self):
        return self.attempt().detail

    def text(self, question: dict) -> str:
        return "".join(piece["text"] for piece in question["segments"])

    def right(self, question: dict) -> dict:
        return RIGHT[self.text(question)]

    def wrong(self, question: dict) -> dict:
        """Return the answer with the first noun moved to verb."""
        table = {part: list(ids) for part, ids in self.right(question).items()}
        table["verb"] = table["verb"] + [table["noun"].pop(0)]
        return table


def _fox_first(directory: Path, **house) -> tuple[Quiz, dict]:
    """Return a quiz and its first sentence, choosing a seed that asks the fox sentence first."""
    for seed in range(50):
        quiz = Quiz(directory, seed=seed, **house)
        quiz.open(START)
        question = quiz.ask(START)
        if quiz.text(question) == FOX:
            return quiz, question
    raise AssertionError("no seed asks the fox sentence first")


# Start screen and what the page is told


def test_the_start_screen_shows_points_out_of_the_sentences_and_the_pass_mark(tmp_path):
    quiz = Quiz(tmp_path, _ten(7))
    page = quiz.open(START)
    assert "<h1>Parts of speech</h1>" in page.body
    assert "0 / 10 points" in page.body
    assert "7 points to pass" in page.body
    assert "Sentence 1 of 10" in page.body
    assert "Sort the words into the table" in page.body


CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")

_MEASURE_GIVE_UP = """\
<script>
const box = document.getElementById("give-up").getBoundingClientRect();
document.getElementById("out").textContent = JSON.stringify({left: box.left, right: box.right, window: innerWidth});
</script>
"""


@pytest.mark.skipif(CHROMIUM is None, reason="needs Chromium to lay out the page")
def test_try_a_different_task_sits_at_the_top_right_of_the_start_screen(tmp_path):
    body = Quiz(tmp_path).open(START).body
    page = tmp_path / "start.html"
    page.write_text(body.replace("</body>", f'<pre id="out"></pre>{_MEASURE_GIVE_UP}</body>'), encoding="utf-8")
    run = subprocess.run(
        [
            CHROMIUM,
            "--headless",
            "--disable-gpu",
            f"--user-data-dir={tmp_path / 'chromium'}",
            "--window-size=1280,800",
            "--dump-dom",
            page.as_uri(),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    box = json.loads(html.unescape(re.search(r'<pre id="out">(.*?)</pre>', run.stdout, re.S).group(1)))
    assert box["left"] > box["window"] / 2, box
    assert box["window"] - box["right"] < 40, box


def test_the_question_has_words_punctuation_and_parts_but_never_the_answer(tmp_path):
    quiz, question = _fox_first(tmp_path)
    assert [piece["text"] for piece in question["segments"]] == [
        "The", " ", "quick", ", ", "brown", " ", "fox", " ", "jumped", " ", "over", " ", "the", " ", "lazy", " ", "dog", ".",
    ]
    assert [piece.get("word") for piece in question["segments"] if "word" in piece] == list(range(9))
    assert question["parts"] == ["noun", "verb", "adjective"]
    assert question["try"] == 1
    assert (question["allowed_ms"], question["left_ms"]) == (45_000, 45_000)
    assert (question["points"], question["required"], question["number"], question["total"]) == (0, 2, 0, 2)
    assert question["table"] is None
    hidden = json.dumps(question)
    assert '"part"' not in hidden and "expected" not in hidden and "jumped\", \"verb" not in hidden
    wrong = quiz.answer(START + timedelta(seconds=5), question["id"], quiz.wrong(question))
    assert set(wrong) >= {"outcome", "try", "wrong", "missed", "points", "finished", "sound"}
    assert not any(key in wrong for key in ("words", "parts", "table"))
    assert (wrong["wrong_words"], wrong["missed_words"], wrong["answer"]) == (None, None, None)


def test_part_names_keep_their_written_order_for_every_sentence_of_the_run(tmp_path):
    body = {
        "sentences": [
            {"sentence": "A cat ran.", "parts": {"verb": ["ran"], "noun": ["cat"], "article": ["a"]}},
            {"sentence": "A dog sat.", "parts": {"Doing words": ["sat"], "adjective": [], "noun": ["dog"]}},
        ]
    }
    quiz = Quiz(tmp_path, body)
    quiz.open(START)
    seen = {}
    for _ in range(2):
        question = quiz.ask(quiz.now)
        seen[quiz.text(question)] = question["parts"]
        table = {"A cat ran.": {"verb": [2], "noun": [1], "article": [0]}, "A dog sat.": {"Doing words": [2], "noun": [1]}}
        assert quiz.answer(quiz.now, question["id"], table[quiz.text(question)])["outcome"] == "correct"
        quiz.now += timedelta(seconds=3)
    assert seen == {"A cat ran.": ["verb", "noun", "article"], "A dog sat.": ["Doing words", "adjective", "noun"]}


# Judging and scoring


def test_a_correct_first_try_scores_one_point_with_the_correct_sound(tmp_path):
    quiz, question = _fox_first(tmp_path)
    result = quiz.answer(START + timedelta(seconds=5), question["id"], FOX_RIGHT)
    assert result["outcome"] == "correct"
    assert result["scored"] == 1
    assert result["points"] == 1
    assert result["sound"].startswith("/static/sounds/correct/")
    assert result["finished"] is False


@pytest.mark.parametrize(
    ("table", "wrong", "missed"),
    [
        ({**FOX_RIGHT, "noun": [3, 8, 0]}, 1, 0),
        ({"noun": [8], "verb": [4, 3], "adjective": [1, 2, 7]}, 1, 0),
        ({"noun": [], "verb": [4, 3], "adjective": [1, 2, 7]}, 1, 1),
        ({"verb": [4]}, 0, 5),
    ],
    ids=["the-as-noun", "fox-as-verb", "fox-as-verb-dog-missed", "only-the-verb"],
)
def test_a_wrong_try_says_how_many_words_are_wrong_and_missed(tmp_path, table, wrong, missed):
    quiz, question = _fox_first(tmp_path)
    result = quiz.answer(START + timedelta(seconds=5), question["id"], table)
    assert (result["outcome"], result["wrong"], result["missed"]) == ("wrong", wrong, missed)
    assert result["sound"].startswith("/static/sounds/incorrect/")
    assert result["points"] == 0


def test_the_two_dry_words_are_judged_separately(tmp_path):
    quiz = Quiz(tmp_path, {"sentences": [EXAMPLE["sentences"][1]]})
    quiz.open(START)
    question = quiz.ask(START)
    swapped = {"verb": [5], "noun": [2, 6], "adjective": [0]}
    result = quiz.answer(START + timedelta(seconds=5), question["id"], swapped)
    assert (result["wrong"], result["missed"]) == (2, 0)
    result = quiz.answer(START + timedelta(seconds=9), question["id"], DRY_RIGHT)
    assert result["outcome"] == "correct"
    assert result["scored"] == 0.5


@pytest.mark.parametrize(("tries", "scored"), [(2, 0.5), (3, 0.25)])
def test_a_later_correct_try_scores_less(tmp_path, tries, scored):
    quiz, question = _fox_first(tmp_path)
    for number in range(1, tries):
        wrong = {"noun": [3, 8], "verb": [4], "adjective": [1, 2, 7][:number]}
        assert quiz.answer(START + timedelta(seconds=number), question["id"], wrong)["outcome"] == "wrong"
    result = quiz.answer(START + timedelta(seconds=tries), question["id"], FOX_RIGHT)
    assert (result["outcome"], result["try"], result["scored"], result["points"]) == ("correct", tries, scored, scored)


def test_a_wrong_third_try_scores_nothing_and_finishes_the_sentence(tmp_path):
    quiz, question = _fox_first(tmp_path)
    for number in (1, 2):
        quiz.answer(START + timedelta(seconds=number), question["id"], {"verb": [4], "noun": [number]})
    result = quiz.answer(START + timedelta(seconds=3), question["id"], {"verb": [4]})
    assert (result["outcome"], result["scored"], result["points"]) == ("incorrect", 0, 0)
    assert result["sound"].startswith("/static/sounds/incorrect/")
    assert result["wrong"] is None and result["missed"] is None
    status, _payload = quiz.post(START + timedelta(seconds=4), "answer", {"id": question["id"], "parts": {"verb": [4]}})
    assert status == 409


@pytest.mark.parametrize(
    ("parts", "says"),
    [
        ({}, "at least one word"),
        ({"noun": [], "verb": []}, "at least one word"),
        ({"noun": [3], "verb": [12]}, "not in the sentence"),
        ({"noun": [3], "verb": [-1]}, "not in the sentence"),
        ({"noun": [3], "verb": ["4"]}, "not in the sentence"),
        ({"noun": [3], "pronoun": [0]}, "not a part"),
        ({"noun": [3], "verb": [3]}, "more than once"),
        ({"noun": [3, 3]}, "more than once"),
        (["noun", 3], "maps part names"),
    ],
)
def test_a_refused_submission_uses_no_try(tmp_path, parts, says):
    quiz, question = _fox_first(tmp_path)
    status, payload = quiz.post(START + timedelta(seconds=5), "answer", {"id": question["id"], "parts": parts})
    assert status == 400
    assert says in payload["error"]
    assert quiz.detail()["questions"][-1]["tries"] == []
    assert quiz.answer(START + timedelta(seconds=6), question["id"], FOX_RIGHT)["scored"] == 1


def test_the_table_of_the_last_wrong_try_is_refused_until_it_changes(tmp_path):
    quiz, question = _fox_first(tmp_path)
    first = {"noun": [8, 3], "verb": [4], "adjective": [1, 2]}
    assert quiz.answer(START + timedelta(seconds=2), question["id"], first)["outcome"] == "wrong"
    reordered = {"adjective": [2, 1], "verb": [4], "noun": [3, 8]}
    status, payload = quiz.post(START + timedelta(seconds=3), "answer", {"id": question["id"], "parts": reordered})
    assert status == 400
    assert "same as the last try" in payload["error"]
    assert len(quiz.detail()["questions"][-1]["tries"]) == 1
    assert quiz.answer(START + timedelta(seconds=4), question["id"], FOX_RIGHT)["scored"] == 0.5


def test_a_try_for_a_sentence_that_is_not_open_reloads_the_page(tmp_path):
    quiz, question = _fox_first(tmp_path)
    status, payload = quiz.post(START, "answer", {"id": question["id"] + 1, "parts": FOX_RIGHT})
    assert (status, payload) == (409, {"reload": True})


# Timer


@pytest.mark.parametrize(("tries", "scored"), [(1, 1), (2, 0.5), (3, 0.25)])
def test_the_timer_running_out_on_a_correct_table_scores_the_try_he_is_on(tmp_path, tries, scored):
    quiz, question = _fox_first(tmp_path)
    for number in range(1, tries):
        quiz.answer(START + timedelta(seconds=number), question["id"], {"verb": [4], "noun": [number]})
    result = quiz.answer(START + timedelta(seconds=45), question["id"], FOX_RIGHT, expired=True)
    assert (result["outcome"], result["scored"]) == ("correct", scored)


@pytest.mark.parametrize(
    "table", [{"noun": [3], "verb": [4]}, {}, {"noun": [3, 8], "verb": [4], "adjective": [1, 2]}], ids=["wrong", "empty", "missed"]
)
def test_the_timer_running_out_on_anything_else_is_a_timeout(tmp_path, table):
    quiz, question = _fox_first(tmp_path)
    result = quiz.answer(START + timedelta(seconds=45), question["id"], table, expired=True)
    assert (result["outcome"], result["scored"]) == ("timeout", 0)
    assert result["sound"].startswith("/static/sounds/timeout/")
    assert quiz.detail()["questions"][-1]["tries"][-1]["expired"] is True


def test_the_timer_may_resend_the_table_of_the_last_wrong_try(tmp_path):
    quiz, question = _fox_first(tmp_path)
    wrong = {"noun": [3], "verb": [4]}
    quiz.answer(START + timedelta(seconds=2), question["id"], wrong)
    result = quiz.answer(START + timedelta(seconds=45), question["id"], wrong, expired=True)
    assert result["outcome"] == "timeout"


def test_a_try_after_the_deadline_is_a_timeout_and_is_still_recorded(tmp_path):
    quiz, question = _fox_first(tmp_path)
    just_in = quiz.answer(START + timedelta(milliseconds=45_500), question["id"], FOX_RIGHT)
    assert just_in["outcome"] == "correct"
    quiz2, question2 = _fox_first(tmp_path / "late")
    late = quiz2.answer(START + timedelta(milliseconds=45_501), question2["id"], FOX_RIGHT)
    assert (late["outcome"], late["scored"]) == ("timeout", 0)
    stored = quiz2.detail()["questions"][-1]["tries"]
    assert stored[-1]["placements"] == FOX_RIGHT
    assert stored[-1]["received_ms"] == 45_501


def test_a_sentence_with_its_own_timeout_gets_it_and_a_wrong_try_does_not_refill_it(tmp_path):
    quiz = Quiz(tmp_path, {"timeout": "30s", "sentences": EXAMPLE["sentences"]})
    quiz.open(START)
    allowed = {}
    for _ in range(2):
        question = quiz.ask(quiz.now)
        allowed[quiz.text(question)] = question["allowed_ms"]
        quiz.answer(quiz.now + timedelta(seconds=10), question["id"], quiz.wrong(question))
        again = quiz.ask(quiz.now + timedelta(seconds=11))
        assert again["left_ms"] == question["allowed_ms"] - 11_000
        quiz.answer(quiz.now + timedelta(seconds=12), question["id"], quiz.right(question))
        quiz.now += timedelta(seconds=15)
    assert allowed == {FOX: 30_000, DRY: 60_000}


# Reload, leaving, give-up


def test_a_reload_before_the_deadline_brings_back_the_same_sentence(tmp_path):
    quiz, question = _fox_first(tmp_path)
    wrong = {"noun": [3], "verb": [4, 8]}
    quiz.answer(START + timedelta(seconds=5), question["id"], wrong)
    for seconds in (8, 20):
        page = quiz.open(START + timedelta(seconds=seconds))
        assert "Sentence 1 of 2" in page.body
        again = quiz.ask(START + timedelta(seconds=seconds))
        assert again["id"] == question["id"]
        assert again["try"] == 2
        assert again["table"] == wrong
        assert (again["wrong"], again["missed"]) == (1, 3)
        assert again["left_ms"] == 45_000 - seconds * 1000
    assert quiz.detail()["questions"][-1]["outcome"] is None


def test_coming_back_after_the_deadline_closes_the_sentence_and_asks_the_next(tmp_path):
    quiz, question = _fox_first(tmp_path)
    quiz.open(START + timedelta(minutes=5))
    stored = quiz.detail()["questions"][0]
    assert (stored["outcome"], stored["points"]) == ("timeout", 0)
    following = quiz.ask(START + timedelta(minutes=5))
    assert quiz.text(following) == DRY
    assert following["number"] == 1


def test_a_last_sentence_closed_by_its_deadline_finishes_the_run(tmp_path):
    quiz, question = _fox_first(tmp_path)
    quiz.answer(START + timedelta(seconds=5), question["id"], FOX_RIGHT)
    quiz.ask(START + timedelta(seconds=8))
    status, payload = quiz.post(START + timedelta(minutes=5), "visit", {})
    assert status == 200
    assert (payload["finished"], payload["result"]) == (True, "failure")
    assert quiz.attempt().outcome == "failure"


def test_coming_back_after_an_hour_starts_a_new_run_in_a_new_order(tmp_path):
    quiz = Quiz(tmp_path, _ten())
    quiz.open(START)
    first = quiz.ask(START)
    quiz.answer(START + timedelta(seconds=2), first["id"], {"noun": [1]})
    quiz.ask(START + timedelta(seconds=5))
    later = START + timedelta(hours=2)
    page = quiz.open(later)
    assert "0 / 10 points" in page.body and "Sentence 1 of 10" in page.body
    runs = quiz.detail()["runs"]
    assert [run["run"] for run in runs] == [1, 2]
    assert sorted(runs[1]["order"]) == list(range(10)) and runs[1]["order"] != runs[0]["order"]
    assert [item["run"] for item in quiz.detail()["questions"]] == [1, 1]
    assert quiz.detail()["questions"][1]["outcome"] == "timeout"
    assert "expired" in runs[0]


def test_every_sentence_is_asked_once_per_run_in_the_shuffled_order(tmp_path):
    quiz = Quiz(tmp_path, _ten())
    quiz.open(START)
    asked = []
    for _ in range(10):
        question = quiz.ask(quiz.now)
        asked.append(quiz.text(question))
        quiz.answer(quiz.now, question["id"], {"noun": [1]})
        quiz.now += timedelta(seconds=2)
    order = quiz.detail()["runs"][0]["order"]
    assert asked == [f"The cat number {index} sat." for index in order]
    assert sorted(order) == list(range(10)) and order != list(range(10))


def test_giving_up_an_optional_task_abandons_and_closes_the_open_sentence(tmp_path):
    quiz, question = _fox_first(tmp_path)
    page = quiz.give_up(START + timedelta(seconds=2))
    assert page.status in (200, 302)
    assert quiz.attempt().outcome == "abandoned"
    assert quiz.detail()["questions"][0]["outcome"] == "timeout"


def test_giving_up_on_the_last_sentence_with_enough_points_is_still_abandoned(tmp_path):
    quiz, question = _fox_first(tmp_path)
    quiz.answer(START + timedelta(seconds=2), question["id"], FOX_RIGHT)
    quiz.ask(START + timedelta(seconds=5))
    quiz.give_up(START + timedelta(seconds=6))
    assert quiz.attempt().outcome == "abandoned"
    assert quiz.store.passes_on("younger", household_day(START)) == 0


def test_a_refused_give_up_leaves_the_open_sentence_alone(tmp_path):
    quiz, question = _fox_first(tmp_path, due="2026-11-01")
    quiz.answer(START + timedelta(seconds=2), question["id"], FOX_RIGHT)
    last = quiz.ask(START + timedelta(seconds=5))
    wrong = {"noun": [2], "verb": [0]}
    quiz.answer(START + timedelta(seconds=7), last["id"], wrong)
    page = quiz.give_up(START + timedelta(seconds=9))
    assert MUST_FINISH in page.body
    assert quiz.attempt().outcome == "in_progress"
    assert quiz.detail()["questions"][-1]["outcome"] is None
    again = quiz.ask(START + timedelta(seconds=12))
    assert (again["id"], again["try"], again["table"]) == (last["id"], 2, wrong)
    assert again["left_ms"] == 60_000 - 7_000


# Finishing


def _play(quiz: Quiz, plan: list[str]) -> list[dict]:
    """Finish one ten-cat sentence per step: right on try ``1``, ``2``, or ``3``, or ``x`` for wrong three times."""
    wrongs = [{"noun": [0]}, {"noun": [2]}, {"noun": [4]}]
    results = []
    for step in plan:
        question = quiz.ask(quiz.now)
        tries = 3 if step == "x" else int(step)
        for number in range(1, tries + 1):
            right = step != "x" and number == tries
            result = quiz.answer(quiz.now, question["id"], {"noun": [1]} if right else wrongs[number - 1])
            quiz.now += timedelta(seconds=1)
        results.append(result)
        quiz.now += timedelta(seconds=3)
    return results


@pytest.mark.parametrize(
    ("plan", "points"),
    [(["x"] * 4 + ["1"] * 6, 6), (["x"] * 2 + ["1"] * 6 + ["2", "3"], 6.75)],
    ids=["nothing-after-four", "six-and-three-quarters"],
)
def test_every_sentence_is_asked_and_too_few_points_fail(tmp_path, plan, points):
    quiz = Quiz(tmp_path, _ten(7), failure_cooldown=2)
    quiz.open(START)
    results = _play(quiz, plan)
    assert [result["finished"] for result in results] == [False] * 9 + [True]
    final = results[-1]
    assert (final["points"], final["required"], final["total"], final["result"]) == (points, 7, 10, "failure")
    assert quiz.attempt().outcome == "failure"
    assert len(skip_days("words", "younger", quiz.store.attempts("younger"))) == 1
    task = quiz.policy.task("words")
    assert not quiz.store.is_eligible(task, "younger", household_day(START) + timedelta(days=1))
    assert quiz.store.is_eligible(task, "younger", household_day(START) + timedelta(days=2))
    assert quiz.store.passes_on("younger", household_day(START)) == 0


def test_finishing_with_the_pass_mark_passes_and_counts_toward_today(tmp_path):
    quiz = Quiz(tmp_path, _ten(7))
    quiz.open(START)
    final = _play(quiz, ["1"] * 7 + ["x"] * 3)[-1]
    assert (final["finished"], final["result"], final["points"]) == (True, "pass", 7)
    assert quiz.attempt().outcome == "pass"
    assert quiz.store.passes_on("younger", household_day(START)) == 1


BACK = "https://www.youtube.com/watch?v=abc123"


def test_a_pass_carries_the_page_to_go_back_to_and_a_failure_does_not(tmp_path):
    for name, plan, verdict, back in (("a", ["1"] * 10, "pass", BACK), ("b", ["x"] * 10, "failure", None)):
        quiz = Quiz(tmp_path / name, _ten(7))
        quiz.back = lambda: BACK
        quiz.open(START)
        final = _play(quiz, plan)[-1]
        assert (final["result"], final["back"]) == (verdict, back)


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to run the page script")
@pytest.mark.parametrize(("verdict", "gone"), [("pass", [(5000, BACK)]), ("failure", [])])
def test_well_done_after_a_pass_counts_down_to_the_page_and_a_failure_does_not(tmp_path, verdict, gone):
    quiz = Quiz(tmp_path, _ten(7))
    page = quiz.open(START).body
    ended = {"points": 7, "total": 10, "required": 7, "number": 10, "finished": True}
    replies = {"visit": [{**ended, "result": verdict, "next": None, "back": BACK if verdict == "pass" else None}]}
    events = _harness(page, replies, steps=[{"snap": ["going-back", "back-host"]}, {"wait": 10_000}])
    snap = next(event["elements"] for event in events if event["kind"] == "snap")
    assert snap["going-back"]["hidden"] is (verdict != "pass")
    assert [(event["at"], event["what"]) for event in events if event["kind"] == "navigate"] == gone


# Record


def test_each_sentence_is_stored_in_full_and_shown_in_the_attempt_view(tmp_path):
    quiz, question = _fox_first(tmp_path)
    wrong = {"noun": [3, 0], "verb": [4]}
    quiz.answer(START + timedelta(milliseconds=2_340), question["id"], wrong)
    quiz.answer(START + timedelta(milliseconds=5_000), question["id"], FOX_RIGHT)
    stored = quiz.detail()["questions"][0]
    assert stored == {
        "run": 1,
        "index": 0,
        "sentence": FOX,
        "parts": ["noun", "verb", "adjective"],
        "words": [
            {"word": "The", "part": None},
            {"word": "quick", "part": "adjective"},
            {"word": "brown", "part": "adjective"},
            {"word": "fox", "part": "noun"},
            {"word": "jumped", "part": "verb"},
            {"word": "over", "part": None},
            {"word": "the", "part": None},
            {"word": "lazy", "part": "adjective"},
            {"word": "dog", "part": "noun"},
        ],
        "tries": [
            {
                "placements": wrong,
                "wrong": 1,
                "missed": 4,
                "wrong_words": [0],
                "missed_words": [1, 2, 7, 8],
                "expired": False,
                "received_ms": 2_340,
            },
            {
                "placements": FOX_RIGHT,
                "wrong": 0,
                "missed": 0,
                "wrong_words": [],
                "missed_words": [],
                "expired": False,
                "received_ms": 5_000,
            },
        ],
        "outcome": "correct",
        "correct_try": 2,
        "points": 0.5,
        "allowed_ms": 45_000,
        "issued": "2026-11-02T16:00:00.000-05:00",
    }
    accounts = Accounts(quiz.store.connection)
    accounts.set_password("ada", "s3cret-pass")
    key = accounts.login("ada", "s3cret-pass", START)
    page = respond_attempt(
        accounts,
        attempt_id=str(quiz.attempt().id),
        method="GET",
        query={},
        cookie=key,
        form={},
        now=START,
        attempts=quiz.store,
    )
    assert "missed_words" in page.body
    assert "jumped" in page.body


# The page script, run in tests/page_harness.js

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node to run the page script")
WATCHED = ["submit", "next", "feedback", "progress", "ask", "timer"]


def _harness(page: str, replies: dict, **options) -> list[dict]:
    run = subprocess.run(
        ["node", str(ROOT / "tests" / "page_harness.js")],
        input=json.dumps({"html": page, "replies": replies, "clip_ms": 0, **options}),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(run.stdout)


def _snaps(events: list[dict]) -> dict[str, dict]:
    return {event["what"]: event["elements"] for event in events if event["kind"] == "snap"}


def _posts(events: list[dict]) -> list[dict]:
    return [event for event in events if event["kind"] == "post"]


def _ended(outcome: str, *, finished: bool = False) -> dict:
    return {
        "outcome": outcome,
        "try": 1,
        "wrong": None,
        "missed": None,
        "scored": 1 if outcome == "correct" else 0,
        "points": 1 if outcome == "correct" else 0,
        "required": 2,
        "number": 1,
        "total": 2,
        "finished": finished,
        "result": None,
        "next": None,
        "sound": f"/static/sounds/{outcome}/{outcome}.mp3",
    }


@needs_node
def test_the_table_functions_place_move_and_compare_words(tmp_path):
    quiz = Quiz(tmp_path)
    page = quiz.open(START).body
    empty = {"noun": [], "verb": [], "adjective": []}
    placed = {"noun": [3, 8], "verb": [], "adjective": []}
    moved = {"noun": [8], "verb": [3], "adjective": []}
    calls = [
        ["empty", ["noun", "verb", "adjective"]],
        ["place", {"noun": [3], "verb": [], "adjective": []}, 8, "noun"],
        ["place", placed, 3, "verb"],
        ["place", placed, 3, "noun"],
        ["remove", placed, 3],
        ["same", placed, {"noun": [8, 3], "verb": [], "adjective": []}],
        ["same", placed, moved],
        ["same", placed, None],
        ["canSubmit", {"phase": "asking", "cells": empty, "lastWrong": None}],
        ["canSubmit", {"phase": "asking", "cells": placed, "lastWrong": None}],
        ["canSubmit", {"phase": "asking", "cells": placed, "lastWrong": {"noun": [8, 3], "verb": [], "adjective": []}}],
        ["canSubmit", {"phase": "asking", "cells": moved, "lastWrong": placed}],
        ["canSubmit", {"phase": "asking", "cells": placed, "lastWrong": None, "dragging": True}],
        ["canSubmit", {"phase": "asking", "cells": placed, "lastWrong": None, "flying": True}],
        ["canSubmit", {"phase": "asking", "cells": placed, "lastWrong": None, "confirming": True}],
        ["canSubmit", {"phase": "waiting", "cells": placed, "lastWrong": None}],
        ["canSubmit", {"phase": "feedback", "cells": placed, "lastWrong": None}],
        ["canSubmit", {"phase": "reveal", "cells": placed, "lastWrong": None}],
        ["drop", None, "noun"],
        ["drop", None, None],
        ["drop", "noun", "verb"],
        ["drop", "noun", "noun"],
        ["drop", "noun", None],
        ["wrongText", 2, 1],
        ["wrongText", 0, 2],
        ["wrongText", 1, 0],
        ["progressText", {"points": 2.5, "total": 10, "required": 7, "number": 3}],
    ]
    events = _harness(page, {}, calls=calls, steps=[])
    results = [event["result"] for event in events if event["kind"] == "call"]
    assert results == [
        empty,
        placed,
        moved,
        placed,
        {"noun": [8], "verb": [], "adjective": []},
        True,
        False,
        False,
        False,
        True,
        False,
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        "place",
        "back",
        "place",
        "stay",
        "unsort",
        "2 words are in the wrong row. You missed 1 word. Try again.",
        "You missed 2 words. Try again.",
        "1 word is in the wrong row. Try again.",
        "2.5 / 10 points \u00b7 7 to pass \u00b7 Sentence 4 of 10",
    ]


@needs_node
def test_an_empty_table_cannot_be_submitted_and_the_timer_sends_it_anyway(tmp_path):
    quiz, question = _fox_first(tmp_path)
    page = quiz.open(START).body
    _status, visit = quiz.post(START, "visit", {})
    replies = {"visit": [visit], "question": [question, question], "answer": [_ended("timeout")]}
    steps = [
        {"click": "start-button"},
        {"snap": WATCHED, "label": "asking"},
        {"key": ["submit", "Enter"]},
        {"click": "submit"},
        {"wait": 45_000},
        {"wait": 100},
        {"snap": WATCHED, "label": "reveal"},
        {"key": ["next", "Enter"]},
        {"wait": 2_900},
        {"snap": WATCHED, "label": "guarded"},
        {"key": ["next", "Enter"]},
        {"wait": 100},
    ]
    events = _harness(page, replies, steps=steps, bodies=True)
    snaps = _snaps(events)
    assert snaps["asking"]["submit"]["disabled"] is True
    assert snaps["asking"]["progress"]["text"] == "0 / 2 points \u00b7 2 to pass \u00b7 Sentence 1 of 2"
    posts = _posts(events)
    answers = [post for post in posts if post["what"] == "answer"]
    assert len(answers) == 1
    assert answers[0]["at"] == 45_000
    assert answers[0]["body"] == {"id": question["id"], "parts": {"noun": [], "verb": [], "adjective": []}, "expired": True}
    assert snaps["reveal"]["feedback"]["text"] == "Time ran out."
    assert snaps["reveal"]["timer"]["hidden"] is True
    assert snaps["reveal"]["submit"]["hidden"] is True
    assert (snaps["reveal"]["next"]["hidden"], snaps["reveal"]["next"]["disabled"]) == (False, True)
    assert (snaps["guarded"]["next"]["disabled"], snaps["guarded"]["next"]["focused"]) == (False, True)
    assert [post["at"] for post in posts if post["what"] == "question"] == [0, 48_000]
    assert [event["what"] for event in events if event["kind"] == "play"] == ["/static/sounds/timeout/timeout.mp3"]


@needs_node
def test_next_question_moves_on_by_itself_after_fifteen_seconds(tmp_path):
    quiz, question = _fox_first(tmp_path)
    page = quiz.open(START).body
    _status, visit = quiz.post(START, "visit", {})
    replies = {"visit": [visit], "question": [question], "answer": [{**_ended("incorrect"), "try": 3}]}
    events = _harness(page, replies, steps=[{"click": "start-button"}, {"wait": 45_000}, {"wait": 16_000}])
    posts = [(post["at"], post["what"]) for post in _posts(events)]
    assert posts == [(0, "visit"), (0, "question"), (45_000, "answer"), (60_000, "question")]


@needs_node
def test_a_correct_try_shows_correct_and_asks_the_next_sentence_after_a_second(tmp_path):
    quiz, question = _fox_first(tmp_path)
    page = quiz.open(START).body
    _status, visit = quiz.post(START, "visit", {})
    replies = {"visit": [visit], "question": [question], "answer": [_ended("correct")]}
    steps = [{"click": "start-button"}, {"wait": 45_000}, {"snap": WATCHED, "label": "correct"}, {"wait": 1_500}]
    events = _harness(page, replies, steps=steps)
    snaps = _snaps(events)
    assert snaps["correct"]["feedback"]["text"] == "Correct!"
    assert snaps["correct"]["submit"]["disabled"] is True
    assert [post["at"] for post in _posts(events) if post["what"] == "question"] == [0, 46_000]


@needs_node
def test_a_resumed_sentence_shows_the_last_message_and_cannot_resend_the_same_table(tmp_path):
    quiz, question = _fox_first(tmp_path)
    quiz.answer(START + timedelta(seconds=5), question["id"], {"noun": [3], "verb": [4, 8]})
    page = quiz.open(START + timedelta(seconds=20)).body
    _status, visit = quiz.post(START + timedelta(seconds=20), "visit", {})
    again = quiz.ask(START + timedelta(seconds=20))
    replies = {"visit": [visit], "question": [again]}
    steps = [{"click": "start-button"}, {"snap": WATCHED, "label": "resumed"}, {"key": ["submit", "Enter"]}, {"wait": 26_000}]
    events = _harness(page, replies, steps=steps, bodies=True)
    snaps = _snaps(events)
    assert snaps["resumed"]["feedback"]["text"] == "1 word is in the wrong row. You missed 3 words. Try again."
    assert snaps["resumed"]["submit"]["disabled"] is True
    answers = [post for post in _posts(events) if post["what"] == "answer"]
    assert [(post["at"], post["body"]["expired"]) for post in answers] == [(25_000, True)]
    assert answers[0]["body"]["parts"] == {"noun": [3], "verb": [4, 8], "adjective": []}


def test_no_quiz_script_replaces_a_function_of_the_shared_shell():
    """A function declared again in the same scope silently replaces the shell's, as ``land`` once broke Tab."""
    import re

    from policy import arithmetic_page, skip_counting_page, spelling_page
    from policy.quiz_page import SHELL_SCRIPT

    declared = re.compile(r"^\s*(?:async\s+)?function\s+(\w+)\s*\(", re.MULTILINE)
    shell = set(declared.findall(SHELL_SCRIPT))
    for module in (arithmetic_page, parts_of_speech_page, skip_counting_page, spelling_page):
        script = "".join(value for name, value in vars(module).items() if name.startswith("_") and name.isupper() and isinstance(value, str))
        assert shell.isdisjoint(declared.findall(script)), module.__name__


# S006.3: red marks after a wrong second try, and the answer after a finished wrong sentence

FOX_IN_VERB = {"noun": [], "verb": [4, 3], "adjective": [1, 2, 7]}
FOX_WRONG_THIRD = {"noun": [6], "verb": [4, 3], "adjective": [1, 2, 7]}
FOX_ANSWER = [
    {"part": None, "placed": None, "had": None},
    {"part": "adjective", "placed": "adjective", "had": "right"},
    {"part": "adjective", "placed": "adjective", "had": "right"},
    {"part": "noun", "placed": "verb", "had": "other"},
    {"part": "verb", "placed": "verb", "had": "right"},
    {"part": None, "placed": None, "had": None},
    {"part": None, "placed": "noun", "had": "extra"},
    {"part": "adjective", "placed": "adjective", "had": "right"},
    {"part": "noun", "placed": None, "had": "missed"},
]


def test_only_a_wrong_second_try_says_which_words_are_wrong_and_missed(tmp_path):
    quiz, question = _fox_first(tmp_path)
    first = quiz.answer(START + timedelta(seconds=2), question["id"], {"noun": [3], "verb": [4]})
    assert (first["wrong_words"], first["missed_words"], first["answer"]) == (None, None, None)
    again = quiz.ask(START + timedelta(seconds=3))
    assert (again["wrong_words"], again["missed_words"]) == (None, None)
    second = quiz.answer(START + timedelta(seconds=5), question["id"], FOX_IN_VERB)
    assert (second["outcome"], second["wrong"], second["missed"]) == ("wrong", 1, 1)
    assert (second["wrong_words"], second["missed_words"], second["answer"]) == ([3], [8], None)


def test_a_reload_after_a_wrong_second_try_brings_back_the_red_marks(tmp_path):
    quiz, question = _fox_first(tmp_path)
    quiz.answer(START + timedelta(seconds=2), question["id"], {"noun": [3], "verb": [4]})
    quiz.answer(START + timedelta(seconds=5), question["id"], FOX_IN_VERB)
    quiz.open(START + timedelta(seconds=9))
    again = quiz.ask(START + timedelta(seconds=9))
    assert (again["try"], again["table"]) == (3, FOX_IN_VERB)
    assert (again["wrong_words"], again["missed_words"]) == ([3], [8])


def test_a_wrong_third_try_gives_the_answer_and_where_he_had_each_word(tmp_path):
    quiz, question = _fox_first(tmp_path)
    quiz.answer(START + timedelta(seconds=2), question["id"], {"noun": [3], "verb": [4]})
    quiz.answer(START + timedelta(seconds=5), question["id"], FOX_IN_VERB)
    third = quiz.answer(START + timedelta(seconds=8), question["id"], FOX_WRONG_THIRD)
    assert third["outcome"] == "incorrect"
    assert third["answer"] == FOX_ANSWER
    assert (third["wrong_words"], third["missed_words"]) == (None, None)


def test_a_timeout_gives_the_answer_and_a_correct_try_does_not(tmp_path):
    quiz, question = _fox_first(tmp_path)
    timed_out = quiz.answer(START + timedelta(seconds=45), question["id"], FOX_WRONG_THIRD, expired=True)
    assert timed_out["outcome"] == "timeout"
    assert timed_out["answer"] == FOX_ANSWER
    following = quiz.ask(START + timedelta(seconds=50))
    assert "answer" not in following
    right = quiz.answer(START + timedelta(seconds=52), following["id"], quiz.right(following))
    assert (right["outcome"], right["answer"]) == ("correct", None)


@needs_node
def test_red_marks_turn_blue_when_moved_and_red_again_when_put_back(tmp_path):
    quiz = Quiz(tmp_path)
    page = quiz.open(START).body
    second = {"noun": [], "verb": [4, 3], "adjective": [1, 2, 7]}
    fox_back_in_noun = {"noun": [3], "verb": [4], "adjective": [1, 2, 7]}
    fox_out = {"noun": [], "verb": [4], "adjective": [1, 2, 7]}
    dog_in_noun = {"noun": [8], "verb": [4, 3], "adjective": [1, 2, 7]}
    marks = {"3": "verb", "8": None}
    calls = [
        ["marks", second, [3], [8]],
        ["colour", marks, second, 3],
        ["colour", marks, second, 8],
        ["colour", marks, second, 4],
        ["colour", marks, fox_back_in_noun, 3],
        ["colour", marks, fox_out, 3],
        ["colour", marks, dog_in_noun, 8],
        ["colour", marks, dog_in_noun, 3],
        ["colour", marks, {"noun": [4], "verb": [3], "adjective": [1, 2, 7]}, 4],
        ["answerRow", FOX_ANSWER, "noun"],
        ["answerRow", FOX_ANSWER, "verb"],
        ["answerRow", FOX_ANSWER, "adjective"],
    ]
    events = _harness(page, {}, calls=calls, steps=[])
    assert [event["result"] for event in events if event["kind"] == "call"] == [
        {"3": "verb", "8": None},
        "red",
        "red",
        "black",
        "blue",
        "blue",
        "blue",
        "red",
        "black",
        [{"id": 3, "had": "other"}, {"id": 8, "had": "missed"}, {"id": 6, "had": "extra"}],
        [{"id": 4, "had": "right"}],
        [{"id": 1, "had": "right"}, {"id": 2, "had": "right"}, {"id": 7, "had": "right"}],
    ]


@needs_node
@pytest.mark.parametrize(("outcome", "message"), [("incorrect", "Not quite. Here is the answer."), ("timeout", "Time ran out. Here is the answer.")])
def test_a_finished_wrong_sentence_says_here_is_the_answer(tmp_path, outcome, message):
    quiz, question = _fox_first(tmp_path)
    page = quiz.open(START).body
    _status, visit = quiz.post(START, "visit", {})
    replies = {"visit": [visit], "question": [question], "answer": [{**_ended(outcome), "answer": FOX_ANSWER}]}
    steps = [{"click": "start-button"}, {"wait": 45_000}, {"snap": WATCHED, "label": "shown"}, {"wait": 14_000}, {"snap": WATCHED, "label": "still"}]
    snaps = _snaps(_harness(page, replies, steps=steps))
    assert snaps["shown"]["feedback"]["text"] == message
    assert snaps["still"]["feedback"]["text"] == message
