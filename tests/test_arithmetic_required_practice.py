"""S042: an arithmetic task that requires a finished practice walk before the quiz."""

import sys
from datetime import timedelta
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_arithmetic import START, Quiz  # noqa: E402
from test_arithmetic import _body as _task_body  # noqa: E402
from test_arithmetic_admin import TEXT, _body  # noqa: E402
from test_arithmetic_admin import house as admin_house  # noqa: E402,F401
from test_arithmetic_practice import STORY_WALK, WATCH, _enter, _next, _play, _posts, _question, _reply, _snaps, _times  # noqa: E402
from test_mcp_writes import TIMES_6  # noqa: E402
from test_mcp_writes import house as mcp_house  # noqa: E402,F401

from conftest import needs_node, run_page  # noqa: E402
from policy.arithmetic import parse_settings  # noqa: E402


def _required(**fields) -> dict:
    return _times(practice_required=True, **fields)


def _quiz(tmp_path, body=None, **options):
    quiz = Quiz(tmp_path, body or _required(), **options)
    quiz.now = START
    quiz.open(START)
    return quiz


def _locked(page: str) -> bool:
    """Whether the start screen says to practise first and has Start disabled."""
    return '<p id="practice-owed">' in page and 'id="start-button" class="big" disabled' in page


def _refused(quiz, now):
    status, payload = quiz.post(now, "question", {})
    assert (status, payload) == (409, {"reload": True})
    assert quiz.detail().get("questions", []) == []


# The setting


def test_practice_required_is_off_unless_the_task_sets_it_true():
    assert parse_settings(_times()).practice_required is False
    assert parse_settings(_times(practice_required=False)).practice_required is False
    assert parse_settings(_required()).practice_required is True


@pytest.mark.parametrize("value", ["true", 1, 0, "yes", None, [True]])
def test_a_practice_required_that_is_not_true_or_false_is_refused_naming_the_field(value):
    body = _times()
    body["practice_required"] = value
    with pytest.raises(ValueError, match="practice_required: must be true or false"):
        parse_settings(body)


def test_practice_required_with_fewer_than_five_operand_values_is_refused_naming_the_field():
    body = _task_body(first=[{"value": 7}], operands=[{"from": 1, "to": 4}], practice_required=True)
    with pytest.raises(ValueError, match="practice_required: needs 5 or more values in operands"):
        parse_settings(body)
    assert parse_settings({**body, "practice_required": False}).practice_required is False
    body["operands"] = [{"from": 1, "to": 5}]
    assert parse_settings(body).practice_required is True


# Before practice


def test_the_start_screen_is_locked_and_no_question_is_asked_until_a_walk_is_finished(tmp_path):
    quiz = _quiz(tmp_path)
    assert _locked(quiz.fetch(START).body)
    _refused(quiz, START)
    _refused(quiz, START + timedelta(minutes=1))
    assert _locked(quiz.fetch(START + timedelta(minutes=2)).body)


def test_a_task_that_does_not_require_practice_asks_its_first_question_at_once(tmp_path):
    quiz = _quiz(tmp_path, _times())
    assert quiz.ask(START)["question"]
    assert _locked(quiz.fetch(START).body) is False


def test_entering_practice_does_not_unlock_and_a_walk_left_early_keeps_the_quiz_locked(tmp_path):
    quiz = _quiz(tmp_path)
    _enter(quiz, START)
    _next(quiz, START + timedelta(seconds=1))
    quiz.open(START + timedelta(seconds=5))
    assert quiz.detail()["practice"][-1]["ended"] == "left"
    _refused(quiz, START + timedelta(seconds=6))
    assert _locked(quiz.fetch(START + timedelta(seconds=7)).body)


def test_giving_up_is_not_blocked_by_the_requirement(tmp_path):
    quiz = _quiz(tmp_path, due="2026-11-01")
    _enter(quiz, START)
    page = quiz.give_up(START + timedelta(seconds=1))
    assert page.status == 200
    assert quiz.attempt().outcome == "in_progress"


# After practice


def test_a_finished_walk_unlocks_the_quiz_and_stays_unlocked_after_a_reload(tmp_path):
    quiz = _quiz(tmp_path)
    _enter(quiz, START)
    walk = _play(quiz)
    assert walk["ended"] == "finished" and [item["n"] for item in walk["questions"]] == STORY_WALK
    later = quiz.now + timedelta(seconds=30)
    assert quiz.ask(later)["question"]
    assert _locked(quiz.open(later + timedelta(seconds=1)).body) is False
    assert quiz.ask(later + timedelta(seconds=2))["question"]


def test_a_walk_left_early_and_then_a_walk_finished_unlocks_the_quiz(tmp_path):
    quiz = _quiz(tmp_path)
    _enter(quiz, START)
    _next(quiz, START + timedelta(seconds=1))
    quiz.open(START + timedelta(seconds=5))
    _enter(quiz, START + timedelta(seconds=6))
    _play(quiz, start=START + timedelta(seconds=7))
    assert quiz.ask(quiz.now + timedelta(seconds=1))["question"]


def test_a_walk_with_misses_still_unlocks_when_it_reaches_its_end(tmp_path):
    quiz = _quiz(tmp_path)
    _enter(quiz, START)
    _play(quiz, [False, True, False])
    assert quiz.ask(quiz.now + timedelta(seconds=1))["question"]


def test_a_new_attempt_of_the_same_task_is_locked_again(tmp_path):
    quiz = _quiz(tmp_path, _required(correct_answers_required=1))
    _enter(quiz, START)
    _play(quiz)
    question = quiz.ask(quiz.now + timedelta(seconds=1))
    result = quiz.answer(quiz.now + timedelta(seconds=2), question["id"], str(quiz.expected()))
    assert result["finished"] is True
    later = quiz.now + timedelta(days=1)
    quiz.fetch(later)
    quiz.open(later)
    _refused(quiz, later)


def test_practising_again_after_unlocking_is_optional_and_changes_nothing(tmp_path):
    quiz = _quiz(tmp_path)
    _enter(quiz, START)
    _play(quiz)
    _enter(quiz, quiz.now + timedelta(seconds=1))
    _next(quiz, quiz.now + timedelta(seconds=2))
    quiz.open(quiz.now + timedelta(seconds=10))
    assert quiz.ask(quiz.now + timedelta(seconds=20))["question"]


# The page script


@needs_node
def test_start_is_locked_until_the_walk_ends_and_then_starts_the_quiz(tmp_path):
    page = Quiz(tmp_path, _required()).open(START).body
    replies = {
        "visit": [{"correct": 0, "required": 20}],
        "practice": [{"practice": {"m": 7, "length": 28}, "correct": 0, "required": 20}],
        "practice_question": [_question(0, 10, position=27)],
        "practice_answer": [{"outcome": "correct", "full": "7 + 10 = 17", "position": 27, "length": 28, "finished": True, "sound": None}],
        "question": [{"id": 0, "question": "7 + 4 =", "allowed_ms": 10_000, "correct": 0, "required": 20}],
    }
    steps = [
        {"snap": WATCH, "label": "locked"},
        {"click": "start-button"},
        {"click": "practice-start"},
        {"wait": 1},
        {"snap": WATCH, "label": "entered"},
        {"type": ["answer", "17"]},
        {"key": ["answer", "Enter"]},
        {"snap": WATCH, "label": "unlocked"},
        {"wait": 6000},
        {"click": "start-button"},
    ]
    events = run_page(page, replies, steps=steps)
    locked = _snaps(events)["locked"]
    assert locked["start-button"]["disabled"] is True and locked["practice-start"]["focused"] is True
    assert _snaps(events)["entered"]["practice-confirm"]["hidden"] is True
    unlocked = _snaps(events)["unlocked"]
    assert unlocked["start-button"]["disabled"] is False and unlocked["start-button"]["focused"] is True
    assert unlocked["practice-done"]["hidden"] is False
    assert _posts(events) == ["visit", "practice", "practice_question", "practice_answer", "question"]


# Editing


def test_the_portal_saves_and_clears_practice_required(admin_house):  # noqa: F811
    house = admin_house
    status, body = house.save("arithmetic/times", settings={"practice_required": "true"})
    assert status == 200, body
    assert _body(house)["practice_required"] is True
    assert house.page("arithmetic/times")["arithmetic"]["settings"]["practice_required"] == "true"
    status, body = house.save("arithmetic/times", settings={"practice_required": ""})
    assert status == 200, body
    assert house.policy.read_text(encoding="utf-8") == TEXT


def test_the_portal_refuses_practice_required_with_too_few_operand_values(admin_house):  # noqa: F811
    house = admin_house
    lists = {"operands": [{"from": "1", "to": "4"}]}
    status, body = house.save("arithmetic/times", settings={"practice_required": "true"}, lists=lists)
    assert status == 400
    assert any("practice_required: needs 5 or more values in operands" in problem for problem in body["errors"]), body
    assert house.policy.read_text(encoding="utf-8") == TEXT


def test_the_mcp_tools_set_practice_required_and_null_clears_it(mcp_house):  # noqa: F811
    house = mcp_house
    house.ok("update_task", {**TIMES_6, "settings": {"practice_required": True}})
    body = yaml.safe_load(house.text("tasks.d/times-6.yaml"))["tasks"]["arithmetic"]["times-6"]["body"]
    assert body["practice_required"] is True
    house.ok("update_task", {**TIMES_6, "settings": {"practice_required": None}})
    assert "practice_required" not in house.text("tasks.d/times-6.yaml")
