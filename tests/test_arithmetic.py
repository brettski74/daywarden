"""S004.1: the arithmetic session shell, built and tested with addition."""

import asyncio
import json
import random
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from conftest import needs_node, run_page  # noqa: E402
from policy.accounts import Accounts  # noqa: E402
from policy.arithmetic import (  # noqa: E402
    NETWORK_ALLOWANCE_MS,
    Session,
    draw,
    parse_settings,
)
from policy.engine import decide  # noqa: E402
from policy.hierarchy import ConfigError, load  # noqa: E402
from policy.review import respond_attempt  # noqa: E402
from policy.sounds import load_sounds  # noqa: E402
from policy.store import PolicyStore  # noqa: E402
from policy.task_page import MUST_FINISH, respond_task  # noqa: E402
from policy.tasks import AttemptStore  # noqa: E402

ZONE = ZoneInfo("America/Toronto")
YOUNGER = "192.0.2.40"
START = datetime(2026, 11, 2, 16, 0, tzinfo=ZONE)
SAMPLES = 60_000
TOLERANCE = 0.01

EXAMPLE = [
    {"value": 1, "weight": 5},
    {"value": 2, "weight": 7},
    {"from": 3, "to": 9, "weight": 10},
    {"value": 10, "weight": 5},
]
EXAMPLE_SHARE = {1: 5 / 87, 2: 7 / 87, **{value: 10 / 87 for value in range(3, 10)}, 10: 5 / 87}


def _body(**fields) -> dict:
    body = {
        "operation": "addition",
        "max_timeout": "10s",
        "min_timeout": "4s",
        "correct_answers_required": 20,
        "operands": EXAMPLE,
    }
    body.update(fields)
    return {key: value for key, value in body.items() if value is not None}


def _shares(values) -> dict[int, float]:
    counts = Counter(values)
    total = sum(counts.values())
    return {value: count / total for value, count in counts.items()}


def _close(found: dict[int, float], expected: dict[int, float]) -> None:
    assert set(found) == set(expected)
    for value, share in expected.items():
        assert abs(found[value] - share) < TOLERANCE, (value, found[value], share)


def _sample(settings, recent=(), count=SAMPLES, seed=4):
    rng = random.Random(seed)
    return [draw(settings, list(recent), rng) for _ in range(count)]


# Configuration and draws


def test_a_large_sample_follows_the_example_weights():
    pairs = _sample(parse_settings(_body()))
    _close(_shares(m for m, _n in pairs), EXAMPLE_SHARE)
    _close(_shares(n for _m, n in pairs), EXAMPLE_SHARE)


def test_a_range_gives_every_value_the_full_weight_like_separate_values():
    ranged = parse_settings(_body(operands=[{"from": 3, "to": 9, "weight": 10}]))
    listed = parse_settings(_body(operands=[{"value": value, "weight": 10} for value in range(3, 10)]))
    assert [ranged.operands.weight(value) for value in range(3, 10)] == [10] * 7
    assert ranged.operands.total == listed.operands.total == 70
    assert _sample(ranged, count=500) == _sample(listed, count=500)


def test_first_draws_the_left_number_and_operands_still_draw_the_right():
    settings = parse_settings(
        _body(
            first=[{"value": 7, "weight": 1}],
            operands=[
                {"value": 1, "weight": 2},
                {"from": 2, "to": 9, "weight": 5},
                {"value": 10, "weight": 2},
                {"from": 11, "to": 12, "weight": 5},
            ],
        )
    )
    pairs = _sample(settings)
    assert {m for m, _n in pairs} == {7}
    total = 2 + 8 * 5 + 2 + 2 * 5
    expected = {1: 2 / total, 10: 2 / total, **{v: 5 / total for v in (*range(2, 10), 11, 12)}}
    _close(_shares(n for _m, n in pairs), expected)


def test_first_with_two_weights_splits_the_left_number_one_to_three():
    settings = parse_settings(_body(first=[{"value": 2, "weight": 1}, {"value": 3, "weight": 3}]))
    pairs = _sample(settings)
    _close(_shares(m for m, _n in pairs), {2: 0.25, 3: 0.75})
    _close(_shares(n for _m, n in pairs), EXAMPLE_SHARE)


def test_a_value_may_be_in_first_and_operands_with_different_weights():
    settings = parse_settings(_body(first=[{"value": 3, "weight": 2}], operands=[{"value": 3, "weight": 9}]))
    assert settings.lefts.weight(3) == 2
    assert settings.operands.weight(3) == 9


@pytest.mark.parametrize(
    "first",
    [
        [],
        [{"value": 4, "weight": 1}, {"value": 4, "weight": 2}],
        [{"value": 4, "weight": 0}],
    ],
    ids=["empty", "repeated", "zero-weight"],
)
def test_first_follows_the_same_rules_as_operands(first):
    with pytest.raises(ValueError, match="^first"):
        parse_settings(_body(first=first))


@pytest.mark.parametrize("weight", [0, -1, 1.5, "3", True])
def test_a_weight_must_be_a_whole_number_of_one_or_more(weight):
    with pytest.raises(ValueError, match="weight"):
        parse_settings(_body(operands=[{"value": 1, "weight": weight}]))


def test_a_positive_weight_and_an_operand_of_zero_are_accepted():
    settings = parse_settings(_body(operands=[{"value": 0, "weight": 1}, {"from": 1, "to": 2, "weight": 3}]))
    assert settings.operands.weight(0) == 1


@pytest.mark.parametrize(
    "entry",
    [{"value": -1, "weight": 1}, {"from": -2, "to": 3, "weight": 1}, {"from": 1, "to": -1, "weight": 1}],
    ids=["value", "from", "to"],
)
def test_a_negative_operand_is_rejected(entry):
    with pytest.raises(ValueError, match="0 or more"):
        parse_settings(_body(operands=[entry]))


@pytest.mark.parametrize(
    "operands",
    [
        [{"value": 4, "weight": 1}, {"value": 4, "weight": 1}],
        [{"from": 1, "to": 5, "weight": 1}, {"from": 5, "to": 9, "weight": 1}],
        [{"from": 1, "to": 5, "weight": 1}, {"value": 3, "weight": 1}],
        [{"from": 6, "to": 5, "weight": 1}],
        [{"value": 4, "from": 1, "to": 5, "weight": 1}],
        [{"from": 1, "weight": 1}],
        [{"weight": 1}],
        [{"value": 4, "weight": 1, "step": 2}],
    ],
    ids=["repeated", "overlap", "value-in-range", "backwards", "both", "half-range", "neither", "unknown"],
)
def test_a_bad_operand_list_is_rejected(operands):
    with pytest.raises(ValueError, match="^operands"):
        parse_settings(_body(operands=operands))


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"max_timeout": None}, "max_timeout"),
        ({"min_timeout": None}, "min_timeout"),
        ({"correct_answers_required": None}, "correct_answers_required"),
        ({"operands": None}, "operands"),
        ({"min_timeout": "11s"}, "min_timeout"),
        ({"max_timeout": "0s"}, "max_timeout"),
        ({"max_timeout": 10}, "max_timeout"),
        ({"correct_answers_required": 0}, "correct_answers_required"),
        ({"operation": "exponent"}, "operation"),
        ({"colour": "blue"}, "colour"),
    ],
)
def test_bad_arithmetic_settings_fail_the_policy_load_and_keep_the_previous_policy(tmp_path, change, field):
    good = _policy(tmp_path, _body())
    path = _write(tmp_path, _house(_body(**change)))
    with pytest.raises(ConfigError) as raised:
        load(path, previous=good)
    message = str(raised.value)
    assert "'sums'" in message
    assert f"body.{field}" in message
    assert good.task("sums").document()["correct_answers_required"] == 20


def test_a_timeout_takes_milliseconds_or_seconds():
    assert parse_settings(_body(max_timeout="7500ms")).max_timeout == 7500
    assert parse_settings(_body(max_timeout="10s")).max_timeout == 10_000
    assert parse_settings(_body(max_timeout="1m", min_timeout="1m")).min_timeout == 60_000


def test_an_operand_above_ten_can_appear():
    settings = parse_settings(_body(operands=[{"from": 1, "to": 12, "weight": 1}]))
    assert 12 in {n for _m, n in _sample(settings, count=2000)}


def test_a_long_run_never_repeats_the_last_three_but_can_repeat_the_fourth():
    session = _session(_body(operands=[{"from": 1, "to": 3, "weight": 1}]))
    rng = random.Random(9)
    issued = []
    now = START
    for _ in range(400):
        question = session.issue(now, rng)
        session.answer(now, len(session.questions) - 1, str(question["expected"]), expired=False)
        issued.append((question["m"], question["n"]))
        now += timedelta(seconds=2)
    for index, pair in enumerate(issued):
        assert pair not in issued[max(0, index - 3) : index]
    assert any(pair == issued[index - 4] for index, pair in enumerate(issued) if index >= 4)


def test_with_three_questions_left_out_the_rest_keep_their_relative_weights():
    settings = parse_settings(
        _body(first=[{"value": 1, "weight": 1}], operands=[{"value": v, "weight": v} for v in range(1, 7)])
    )
    recent = [(1, 1), (1, 3), (1, 6)]
    pairs = _sample(settings, recent=recent)
    left = {2: 2, 4: 4, 5: 5}
    _close(_shares(n for _m, n in pairs), {n: weight / sum(left.values()) for n, weight in left.items()})


def test_six_plus_seven_may_follow_seven_plus_six():
    settings = parse_settings(_body(operands=[{"value": 6, "weight": 1}, {"value": 7, "weight": 1}]))
    pairs = _sample(settings, recent=[(7, 6)], count=400)
    assert (6, 7) in pairs
    assert (7, 6) not in pairs


def test_two_questions_alternate_and_one_question_still_comes_every_time():
    rng = random.Random(3)
    two = parse_settings(_body(first=[{"from": 1, "to": 2, "weight": 1}], operands=[{"value": 5, "weight": 1}]))
    recent: list[tuple[int, int]] = []
    for _ in range(12):
        recent.append(draw(two, recent, rng))
    assert all(left != right for left, right in zip(recent, recent[1:]))
    one = parse_settings(_body(first=[{"value": 3, "weight": 1}], operands=[{"value": 4, "weight": 1}]))
    recent = []
    for _ in range(6):
        recent.append(draw(one, recent, rng))
    assert recent == [(3, 4)] * 6


# Session flow on the server


def test_opening_the_task_shows_the_start_screen_and_issues_no_question(tmp_path):
    quiz = Quiz(tmp_path, _body())
    page = quiz.open(START)
    assert page.status == 200
    assert "<h1>Addition</h1>" in page.body
    assert "0 / 20 correct" in page.body
    assert "Start" in page.body
    assert quiz.detail()["questions"] == []


def test_a_right_answer_scores_and_plays_a_correct_sound(tmp_path):
    quiz = Quiz(tmp_path, _body(first=[{"value": 6, "weight": 1}], operands=[{"value": 7, "weight": 1}]))
    quiz.open(START)
    question = quiz.ask(START)
    assert question["question"] == "6 + 7 ="
    result = quiz.answer(START + timedelta(seconds=2), question["id"], "013")
    assert result["outcome"] == "correct"
    assert result["correct"] == 1
    assert result["required"] == 20
    assert result["sound"].startswith("/static/sounds/correct/")
    assert "1 / 20 correct" in quiz.open(START + timedelta(seconds=3)).body


def test_a_wrong_answer_shows_the_full_question_and_plays_an_incorrect_sound(tmp_path):
    quiz = Quiz(tmp_path, _body(first=[{"value": 6, "weight": 1}], operands=[{"value": 7, "weight": 1}]))
    quiz.open(START)
    question = quiz.ask(START)
    result = quiz.answer(START + timedelta(seconds=2), question["id"], "12")
    assert result["outcome"] == "incorrect"
    assert result["correct"] == 0
    assert result["full"] == "6 + 7 = 13"
    assert result["sound"].startswith("/static/sounds/incorrect/")


def test_the_right_answer_in_the_box_when_the_timer_ends_is_correct(tmp_path):
    quiz = Quiz(tmp_path, _body())
    quiz.open(START)
    question = quiz.ask(START)
    expected = quiz.detail()["questions"][-1]["expected"]
    result = quiz.answer(START + timedelta(seconds=10), question["id"], str(expected), expired=True)
    assert result["outcome"] == "correct"
    assert result["sound"].startswith("/static/sounds/correct/")


@pytest.mark.parametrize("box", ["", "999"])
def test_an_empty_or_wrong_box_when_the_timer_ends_is_a_timeout(tmp_path, box):
    quiz = Quiz(tmp_path, _body())
    quiz.open(START)
    question = quiz.ask(START)
    result = quiz.answer(START + timedelta(seconds=10), question["id"], box, expired=True)
    assert result["outcome"] == "timeout"
    assert result["correct"] == 0
    assert result["sound"].startswith("/static/sounds/timeout/")
    assert quiz.detail()["questions"][-1]["outcome"] == "timeout"


def test_enter_on_an_empty_box_is_not_an_answer(tmp_path):
    quiz = Quiz(tmp_path, _body())
    quiz.open(START)
    question = quiz.ask(START)
    status, _payload = quiz.post(START + timedelta(seconds=1), "answer", {"id": question["id"], "answer": ""})
    assert status == 400
    assert quiz.detail()["questions"][-1]["outcome"] is None


def test_the_timeout_shrinks_with_correct_answers_and_not_with_wrong_ones(tmp_path):
    quiz = Quiz(tmp_path, _body(correct_answers_required=5))
    quiz.open(START)
    allowed = []
    for right in (True, False, True, True, True, True):
        question = quiz.ask(START)
        allowed.append(question["allowed_ms"])
        quiz.answer(START, question["id"], str(quiz.expected() + (0 if right else 1)))
    formula = [round(10_000 * (4_000 / 10_000) ** (k / 4)) for k in range(5)]
    assert allowed == [formula[0], formula[1], formula[1], formula[2], formula[3], formula[4]]
    assert formula[0] == 10_000
    assert formula[4] == 4_000
    assert formula[0] > formula[1] > formula[2] > formula[3] > formula[4]


def test_one_required_answer_always_gets_the_longest_time():
    settings = parse_settings(_body(correct_answers_required=1))
    assert settings.timeout(0) == 10_000


# Server timing and resume


def test_the_question_sent_to_the_browser_has_no_expected_answer(tmp_path):
    quiz = Quiz(tmp_path, _body(first=[{"value": 6, "weight": 1}], operands=[{"value": 7, "weight": 1}]))
    quiz.open(START)
    question = quiz.ask(START)
    assert set(question) == {"id", "question", "allowed_ms", "correct", "required"}
    assert "13" not in json.dumps(question)


def test_the_server_clock_decides_whether_an_answer_was_in_time(tmp_path):
    quiz = Quiz(tmp_path, _body())
    quiz.open(START)
    edge = timedelta(milliseconds=10_000 + NETWORK_ALLOWANCE_MS)
    question = quiz.ask(START)
    expected = quiz.detail()["questions"][-1]["expected"]
    assert quiz.answer(START + edge, question["id"], str(expected))["outcome"] == "correct"
    later = START + timedelta(seconds=20)
    question = quiz.ask(later)
    assert question["allowed_ms"] < 10_000
    late = later + timedelta(milliseconds=question["allowed_ms"] + NETWORK_ALLOWANCE_MS + 1)
    expected = quiz.detail()["questions"][-1]["expected"]
    result = quiz.answer(late, question["id"], str(expected))
    assert result["outcome"] == "timeout"
    stored = quiz.detail()["questions"][-1]
    assert stored["answer"] == str(expected)
    assert stored["taken_ms"] == question["allowed_ms"] + NETWORK_ALLOWANCE_MS + 1


def test_reloading_during_a_question_records_it_as_a_timeout(tmp_path):
    quiz = Quiz(tmp_path, _body())
    quiz.open(START)
    first = quiz.ask(START)
    quiz.answer(START, first["id"], str(quiz.detail()["questions"][-1]["expected"]))
    showing = quiz.ask(START + timedelta(seconds=1))
    page = quiz.open(START + timedelta(seconds=2))
    stored = quiz.detail()["questions"][showing["id"]]
    assert stored["outcome"] == "timeout"
    assert stored["answer"] is None
    assert stored["taken_ms"] == stored["allowed_ms"]
    assert "1 / 20 correct" in page.body
    following = quiz.ask(START + timedelta(seconds=3))
    assert following["id"] == showing["id"] + 1
    status, _payload = quiz.post(START + timedelta(seconds=4), "answer", {"id": showing["id"], "answer": "1"})
    assert status == 409


def test_a_background_fetch_of_the_page_does_not_close_the_question_on_screen(tmp_path):
    quiz = Quiz(tmp_path, _body())
    quiz.open(START)
    question = quiz.ask(START)
    before = quiz.detail()
    for offset in (1, 2, 3):
        fetched = quiz.fetch(START + timedelta(seconds=offset))
        assert fetched.status == 200
    assert quiz.detail() == before
    result = quiz.answer(START + timedelta(seconds=4), question["id"], str(quiz.expected()))
    assert result["outcome"] == "correct"
    assert result["correct"] == 1


def test_coming_back_after_fifty_nine_minutes_resumes(tmp_path):
    quiz = Quiz(tmp_path, _body())
    quiz.open(START)
    question = quiz.ask(START)
    quiz.answer(START + timedelta(seconds=1), question["id"], str(quiz.detail()["questions"][-1]["expected"]))
    page = quiz.open(START + timedelta(seconds=1, minutes=59))
    assert "1 / 20 correct" in page.body
    assert len(quiz.detail()["runs"]) == 1


def test_coming_back_after_sixty_one_minutes_starts_the_same_attempt_again(tmp_path):
    quiz = Quiz(tmp_path, _body())
    quiz.open(START)
    question = quiz.ask(START)
    quiz.answer(START + timedelta(seconds=1), question["id"], str(quiz.detail()["questions"][-1]["expected"]))
    left = quiz.ask(START + timedelta(seconds=2))
    attempt = quiz.attempt()
    back = START + timedelta(seconds=2, minutes=61)
    page = quiz.open(back)
    assert "0 / 20 correct" in page.body
    assert quiz.attempt().id == attempt.id
    assert quiz.attempt().outcome == "in_progress"
    detail = quiz.detail()
    assert [run["run"] for run in detail["runs"]] == [1, 2]
    assert detail["runs"][0]["expired"] == (START + timedelta(seconds=2, hours=1)).isoformat(timespec="milliseconds")
    assert [item["run"] for item in detail["questions"]] == [1, 1]
    assert detail["questions"][left["id"]]["outcome"] == "timeout"
    assert [row.outcome for row in quiz.store.attempts("younger")] == ["in_progress"]


def test_a_long_session_does_not_expire_while_he_keeps_answering(tmp_path):
    quiz = Quiz(tmp_path, _body(correct_answers_required=500))
    quiz.open(START)
    now = START
    while now < START + timedelta(hours=3):
        question = quiz.ask(now)
        now += timedelta(seconds=30)
        quiz.answer(now, question["id"], "0")
        now += timedelta(seconds=30)
    assert len(quiz.detail()["runs"]) == 1


def test_a_policy_edit_waits_for_the_next_run(tmp_path):
    quiz = Quiz(tmp_path, _body(correct_answers_required=20))
    quiz.open(START)
    quiz.use(_body(correct_answers_required=3))
    question = quiz.ask(START + timedelta(seconds=1))
    assert question["required"] == 20
    assert "0 / 20 correct" in quiz.open(START + timedelta(minutes=30)).body
    page = quiz.open(START + timedelta(minutes=95))
    assert "0 / 3 correct" in page.body
    assert quiz.detail()["settings"]["correct_answers_required"] == 3


# Finishing and giving up


def test_reaching_the_target_is_a_pass_at_that_answer_and_counts_today(tmp_path):
    quiz = Quiz(tmp_path, _body(correct_answers_required=2))
    quiz.open(START)
    now = START
    for _ in range(2):
        question = quiz.ask(now)
        assert quiz.answer(now, question["id"], "999")["finished"] is False
        question = quiz.ask(now)
        assert quiz.answer(now + timedelta(seconds=12), question["id"], "", expired=True)["outcome"] == "timeout"
        question = quiz.ask(now)
        answered = now + timedelta(seconds=1, milliseconds=250)
        result = quiz.answer(answered, question["id"], str(quiz.expected()))
        now += timedelta(seconds=30)
    assert result["finished"] is True
    assert result["sound"].startswith("/static/sounds/correct/")
    passed = quiz.attempt()
    assert passed.outcome == "pass"
    assert passed.finished_at == answered.replace(microsecond=0)
    assert quiz.store.passes_on("younger", START.date()) == 1
    assert "failure" not in {row.outcome for row in quiz.store.attempts("younger")}


def test_well_done_offers_the_next_task_only_when_one_is_eligible(tmp_path):
    other = """\
  spelling:
    type: spelling
    group: younger
    pass_cooldown: 0
"""
    with_other = Quiz(tmp_path / "a", _body(correct_answers_required=1), extra=other)
    with_other.open(START)
    question = with_other.ask(START)
    result = with_other.answer(START, question["id"], str(with_other.expected()))
    assert result["next"] == "https://tasks.example/tasks/next"
    alone = Quiz(tmp_path / "b", _body(correct_answers_required=1), cooldown=1)
    alone.open(START)
    question = alone.ask(START)
    result = alone.answer(START, question["id"], str(alone.expected()))
    assert result["finished"] is True
    assert result["next"] is None


# Back to the page he was sent away from (S015)

BACK = "https://www.youtube.com/watch?v=abc123"
GOING_BACK = ["going-back", "back-host", "go-now"]


def test_only_the_answer_that_passes_carries_the_page_to_go_back_to(tmp_path):
    quiz = Quiz(tmp_path, _body(correct_answers_required=2))
    asked = []
    quiz.back = lambda: asked.append(True) or BACK
    quiz.open(START)
    question = quiz.ask(START)
    first = quiz.answer(START, question["id"], str(quiz.expected()))
    assert (first["finished"], first["back"]) == (False, None)
    assert asked == []
    question = quiz.ask(START)
    final = quiz.answer(START, question["id"], str(quiz.expected()))
    assert (final["finished"], final["back"]) == (True, BACK)
    assert len(asked) == 1


def _well_done(tmp_path, *, back, next_task=None, leave=()):
    """Pass the one-question quiz in the page script, then do what ``leave`` lists on "Well done"."""
    sums = _body(correct_answers_required=1, first=[{"value": 6, "weight": 1}], operands=[{"value": 7, "weight": 1}])
    page = Quiz(tmp_path, sums).open(START).body
    replies = {
        "visit": [{"correct": 0, "required": 1}],
        "question": [{"id": 0, "question": "6 + 7 =", "allowed_ms": 10_000, "correct": 0, "required": 1}],
        "answer": [
            {
                "outcome": "correct",
                "full": "6 + 7 = 13",
                "correct": 1,
                "required": 1,
                "finished": True,
                "next": next_task,
                "back": back,
                "sound": None,
            }
        ],
    }
    steps = [
        {"click": "start-button"},
        {"type": ["answer", "13"]},
        {"key": ["answer", "Enter"]},
        {"wait": 1000},
        {"snap": GOING_BACK, "label": "well done"},
        *leave,
    ]
    events = run_page(page, replies, steps=steps)
    snaps = {event["what"]: event["elements"] for event in events if event["kind"] == "snap"}
    gone = [(event["at"], event["what"]) for event in events if event["kind"] == "navigate"]
    return snaps["well done"], gone


@needs_node
def test_well_done_says_where_he_is_going_and_opens_it_five_seconds_later(tmp_path):
    shown, gone = _well_done(tmp_path, back=BACK, leave=[{"wait": 4999}, {"wait": 1}])
    assert shown["going-back"]["hidden"] is False
    assert shown["back-host"]["text"] == "www.youtube.com"
    assert shown["go-now"]["hidden"] is False
    assert shown["go-now"]["focused"] is True
    assert gone == [(6000, BACK)]


@needs_node
@pytest.mark.parametrize(
    "leave",
    [[{"click": "go-now"}], [{"key": ["go-now", "Enter"]}]],
    ids=["go now", "enter"],
)
def test_go_now_and_enter_open_the_page_straight_away(tmp_path, leave):
    _shown, gone = _well_done(tmp_path, back=BACK, leave=[*leave, {"wait": 10_000}])
    assert gone == [(1000, BACK)]


@needs_node
def test_choosing_next_task_stops_the_countdown(tmp_path):
    shown, gone = _well_done(
        tmp_path,
        back=BACK,
        next_task="https://tasks.example/tasks/next",
        leave=[{"wait": 2000}, {"click": "next-task"}, {"wait": 10_000}],
    )
    assert shown["going-back"]["hidden"] is False
    assert gone == []


@needs_node
def test_without_a_page_to_go_back_to_well_done_is_unchanged(tmp_path):
    shown, gone = _well_done(tmp_path, back=None, leave=[{"key": ["answer", "Enter"]}, {"wait": 10_000}])
    assert shown["going-back"]["hidden"] is True
    assert shown["go-now"]["hidden"] is True
    assert gone == []


def test_the_only_required_task_keeps_its_progress_when_he_tries_to_give_up(tmp_path):
    quiz = Quiz(tmp_path, _body(), due="2026-11-01")
    quiz.open(START)
    question = quiz.ask(START)
    quiz.answer(START, question["id"], str(quiz.expected()))
    showing = quiz.ask(START + timedelta(seconds=1))
    page = quiz.give_up(START + timedelta(seconds=2))
    assert page.status == 200
    assert MUST_FINISH in page.body
    assert "1 / 20 correct" in page.body
    assert quiz.attempt().outcome == "in_progress"
    assert quiz.detail()["questions"][showing["id"]]["outcome"] == "timeout"


def test_giving_up_an_optional_task_closes_the_question_and_abandons(tmp_path):
    quiz = Quiz(tmp_path, _body())
    quiz.open(START)
    quiz.ask(START)
    page = quiz.give_up(START + timedelta(seconds=2))
    assert page.status == 200
    abandoned = quiz.store.attempts("younger", "sums")[-1]
    assert abandoned.outcome == "abandoned"
    assert abandoned.detail["questions"][-1]["outcome"] == "timeout"


def test_a_quiz_request_for_a_task_he_may_not_open_asks_the_page_to_reload(tmp_path):
    quiz = Quiz(tmp_path, _body(correct_answers_required=1), cooldown=1)
    quiz.open(START)
    question = quiz.ask(START)
    quiz.answer(START, question["id"], str(quiz.expected()))
    status, payload = quiz.post(START + timedelta(seconds=1), "question", {})
    assert status == 409
    assert payload == {"reload": True}


# Sounds


def _sound_dir(root: Path) -> Path:
    for outcome, names in {
        "correct": ["a.mp3", "b.wav", "c.ogg", "ATTRIBUTION.md"],
        "incorrect": ["x.m4a"],
        "timeout": ["bell.opus"],
    }.items():
        (root / outcome).mkdir(parents=True)
        for name in names:
            (root / outcome / name).write_bytes(b"sound")
    return root


def test_each_file_in_a_set_is_equally_likely_and_nothing_else_is_chosen(tmp_path):
    sounds = load_sounds(_sound_dir(tmp_path / "sounds"), warn=lambda message: None)
    rng = random.Random(5)
    picks = [sounds.choose("correct", rng) for _ in range(30_000)]
    prefix = "/static/sounds/correct/"
    _close(_shares(picks), {prefix + "a.mp3": 1 / 3, prefix + "b.wav": 1 / 3, prefix + "c.ogg": 1 / 3})
    assert prefix + "ATTRIBUTION.md" not in picks


def test_a_fourth_audio_file_becomes_a_choice_without_any_other_change(tmp_path):
    root = _sound_dir(tmp_path / "sounds")
    (root / "correct" / "d.opus").write_bytes(b"sound")
    sounds = load_sounds(root, warn=lambda message: None)
    assert sounds.files["correct"] == ("a.mp3", "b.wav", "c.ogg", "d.opus")


def test_an_empty_set_plays_nothing_and_warns_at_start_up(tmp_path):
    root = _sound_dir(tmp_path / "sounds")
    (root / "timeout" / "bell.opus").unlink()
    (root / "timeout" / "README.txt").write_text("credits")
    warnings: list[str] = []
    sounds = load_sounds(root, warn=warnings.append)
    assert len(warnings) == 1
    assert "timeout" in warnings[0]
    quiz = Quiz(tmp_path / "quiz", _body(), sounds=sounds)
    quiz.open(START)
    question = quiz.ask(START)
    result = quiz.answer(START + timedelta(seconds=10), question["id"], "", expired=True)
    assert result["outcome"] == "timeout"
    assert result["sound"] is None
    assert quiz.ask(START + timedelta(seconds=13))["id"] == question["id"] + 1


def test_the_shipped_sets_have_audio_for_every_outcome():
    sounds = load_sounds(warn=lambda message: pytest.fail(message))
    assert all(sounds.files[outcome] for outcome in ("correct", "incorrect", "timeout"))


@pytest.mark.parametrize(
    ("rules", "expected"),
    [
        (
            """\
  gate:
    - condition: site_group
      group: tasks
      when_true: { action: allow }
      when_false: { action: deny, message: "Closed." }
""",
            {"action": "allow"},
        ),
        (
            """\
  gate:
    - condition: always
      when_true: { action: redirect, location: revision_task }
""",
            {"action": "allow"},
        ),
        (
            """\
  gate:
    - condition: always
      when_true: { action: deny, message: "Closed." }
""",
            {"action": "deny", "status": 403, "message": "Closed."},
        ),
    ],
    ids=["allowed-site", "revision-redirect", "denied"],
)
def test_sound_files_follow_the_rule_that_lets_the_task_page_load(tmp_path, rules, expected):
    sites = """\
site_groups:
  tasks:
    priority: 10
    patterns: ["tasks.example"]
"""
    policy = _policy(tmp_path, _body(), rules=rules, sites=sites)
    with AttemptStore(":memory:") as store:
        sound = decide(
            policy,
            client_ip=YOUNGER,
            url="https://tasks.example/static/sounds/correct/cha-ching.mp3",
            at=START,
            attempts=store,
        )
        page = decide(policy, client_ip=YOUNGER, url="https://tasks.example/tasks/sums", at=START, attempts=store)
    assert sound.decision == expected
    assert page.decision["action"] == expected["action"]


def test_the_service_serves_the_sounds_and_runs_a_question(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    body = _body(first=[{"value": 6, "weight": 1}], operands=[{"value": 7, "weight": 1}])
    policy_file = _write(tmp_path, _house(body))
    monkeypatch.setenv("POLICY_FILE", str(policy_file))
    monkeypatch.setenv("POLICY_DB", str(tmp_path / "policy.sqlite3"))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    monkeypatch.setenv("SOUND_DIR", str(_sound_dir(tmp_path / "sounds")))
    monkeypatch.delenv("DECISION_STUB", raising=False)
    app = create_app()

    status, headers, body = _call(app, "GET", "/static/sounds/timeout/bell.opus")
    assert status == 200
    assert headers["content-type"].startswith("audio/ogg")
    assert body == b"sound"
    assert _call(app, "GET", "/static/sounds/correct/ATTRIBUTION.md")[0] == 404
    assert _call(app, "GET", "/static/sounds/correct/..%2F..%2Fpolicy.yaml")[0] == 404

    status, _headers, body = _call(app, "GET", "/tasks/sums")
    assert status == 200
    assert b"Addition" in body
    status, headers, body = _call(app, "POST", "/tasks/sums", query=b"do=question", body=b"{}")
    assert status == 200
    assert headers["content-type"] == "application/json"
    question = json.loads(body)
    assert question["question"] == "6 + 7 ="
    answer = json.dumps({"id": question["id"], "answer": "13", "expired": False}).encode()
    status, _headers, body = _call(app, "POST", "/tasks/sums", query=b"do=answer", body=answer)
    result = json.loads(body)
    assert status == 200
    assert result["outcome"] == "correct"
    assert result["sound"].startswith("/static/sounds/correct/")


# Record


def test_each_question_is_stored_in_full_and_shown_in_the_attempt_view(tmp_path):
    quiz = Quiz(tmp_path, _body(first=[{"value": 6, "weight": 1}], operands=[{"value": 7, "weight": 1}]))
    quiz.open(START)
    question = quiz.ask(START)
    quiz.answer(START + timedelta(milliseconds=2_340), question["id"], "13")
    stored = quiz.detail()["questions"][0]
    assert stored == {
        "run": 1,
        "m": 6,
        "n": 7,
        "question": "6 + 7 =",
        "expected": 13,
        "answer": "13",
        "outcome": "correct",
        "allowed_ms": 10_000,
        "taken_ms": 2_340,
        "issued": "2026-11-02T16:00:00.000-05:00",
    }
    assert quiz.detail()["settings"]["operation"] == "addition"
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
    assert "6 + 7 =" in page.body
    assert "correct" in page.body


# Helpers


def _house(
    body: dict,
    *,
    rules: str | None = None,
    sites: str = "",
    extra: str = "",
    cooldown: int = 0,
    due: str | None = None,
) -> str:
    rules = rules or """\
  gate:
    - condition: always
      when_true: { action: allow }
"""
    due_line = f"    due_date: {due}\n" if due else ""
    return f"""\
entry: gate
timezone: America/Toronto
hostname: tasks.example
port: 443
client_groups:
  younger:
    addresses: ["{YOUNGER}"]
{sites}tasks:
  sums:
    type: arithmetic
    group: younger
    pass_cooldown: {cooldown}
{due_line}    body: {json.dumps(body)}
{extra}rule_sets:
{rules}"""


def _write(directory: Path, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "policy.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _policy(directory: Path, body: dict, **house):
    loaded = load(_write(directory, _house(body, **house)))
    assert loaded is not None
    return loaded


def _session(body: dict) -> Session:
    session = Session({}, body)
    session.visit(START)
    return session


class Quiz:
    """One child working through the sums task, on a clock the test sets."""

    def __init__(self, directory: Path, body: dict, *, sounds=None, extra: str = "", cooldown: int = 0, due=None):
        self.directory = directory
        self.house = {"extra": extra, "cooldown": cooldown, "due": due}
        self.policy = _policy(directory, body, **self.house)
        self.saved = PolicyStore(":memory:")
        self.store = AttemptStore(connection=self.saved.connection)
        self.sounds = sounds or load_sounds(_sound_dir(directory / "sounds"), warn=lambda message: None)
        self.back = None

    def use(self, body: dict) -> None:
        self.policy = _policy(self.directory, body, **self.house)

    def _respond(self, now, method, query=None, body=b""):
        return respond_task(
            self.policy,
            self.store,
            method=method,
            path="/tasks/sums",
            client_ip=YOUNGER,
            cookie=None,
            now=now,
            query=query,
            body=body,
            sounds=self.sounds,
            back=self.back,
        )

    def fetch(self, now):
        """GET the page without running its script, as a redirected favicon request does."""
        return self._respond(now, "GET")

    def open(self, now):
        """Load the page in a browser tab: the GET, then the script's visit."""
        page = self.fetch(now)
        status, payload = self.post(now, "visit", {})
        assert status == 200, payload
        assert f"{payload['correct']} / {payload['required']} correct" in page.body
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

    def answer(self, now, number, text, *, expired=False) -> dict:
        status, payload = self.post(now, "answer", {"id": number, "answer": text, "expired": expired})
        assert status == 200, payload
        return payload

    def attempt(self):
        return self.store.attempts("younger", "sums")[-1]

    def detail(self):
        return self.attempt().detail

    def expected(self) -> int:
        return self.detail()["questions"][-1]["expected"]


def _call(app, method, path, *, query=b"", body=b""):
    messages = []
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            await asyncio.Future()
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query,
        "headers": [(b"x-daywarden-client", YOUNGER.encode()), (b"content-type", b"application/json")],
        "client": ("172.17.0.2", 12345),
        "server": ("127.0.0.1", 80),
        "root_path": "",
    }
    asyncio.run(app(scope, receive, send))
    start = next(item for item in messages if item["type"] == "http.response.start")
    payload = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
    headers = {key.decode(): value.decode() for key, value in start["headers"]}
    return start["status"], headers, payload
