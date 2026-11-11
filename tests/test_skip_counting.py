"""S011: skip counting, with tries worth less each time and a pass or fail at the end."""

import asyncio
import html
import json
import random
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from conftest import merge_task_types, needs_node, run_page  # noqa: E402
from policy.hierarchy import ConfigError, load  # noqa: E402
from policy.quiz import NETWORK_ALLOWANCE_MS  # noqa: E402
from policy.review import attempt_report  # noqa: E402
from policy.skip_counting import (  # noqa: E402
    Session,
    blank_positions,
    draw_difference,
    draw_filled,
    format_points,
    parse_settings,
)
from policy.sounds import load_sounds  # noqa: E402
from policy.store import PolicyStore  # noqa: E402
from policy.task_page import MUST_FINISH, respond_task  # noqa: E402
from policy.tasks import AttemptStore, TaskKey, skip_days  # noqa: E402

ZONE = ZoneInfo("America/Toronto")
YOUNGER = "192.0.2.40"
START = datetime(2026, 11, 2, 16, 0, tzinfo=ZONE)
SAMPLES = 60_000
TOLERANCE = 0.01
TIMEOUT_MS = 180_000
CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
needs_chromium = pytest.mark.skipif(CHROMIUM is None, reason="needs Chromium to lay out the page")


def _differences(*values: int, weight: int = 1) -> list[dict]:
    return [{"value": value, "weight": weight} for value in values]


# Configuration


def test_a_body_with_no_fields_loads_with_the_defaults():
    settings = parse_settings({})
    assert settings.length == 8
    assert settings.completed == 3
    assert settings.consecutive is True
    assert settings.multiples_only is False
    assert [(entry.low, entry.weight) for entry in settings.differences.entries] == [
        (value, 1) for value in (-100, -25, -10, -5, -2, 2, 5, 10, 25, 100)
    ]
    assert (settings.minimum, settings.maximum) == (1, 999)
    assert {value: settings.range_for(value) for value in (2, 5, 10, 25, 100, -2, -5, -10, -25, -100)} == {
        2: (1, 99),
        5: (1, 199),
        10: (1, 499),
        25: (1, 999),
        100: (1, 999),
        -2: (1, 99),
        -5: (1, 199),
        -10: (1, 499),
        -25: (1, 999),
        -100: (1, 999),
    }
    assert settings.timeout == TIMEOUT_MS
    assert settings.required == 8
    assert settings.minimum_questions == 8
    assert settings.maximum_questions is None


@pytest.mark.parametrize(
    ("written", "required", "least"),
    [
        ({}, 8, 8),
        ({"maximum_questions": 5}, 5, 5),
        ({"maximum_questions": 10}, 8, 8),
        ({"minimum_questions": 15}, 12, 15),
        ({"minimum_questions": 12}, 10, 12),
        ({"minimum_questions": 5}, 8, 5),
        ({"correct_answers_required": 6}, 6, 6),
        ({"minimum_questions": 15, "maximum_questions": 20}, 12, 15),
    ],
)
def test_each_row_of_the_defaults_table(written, required, least):
    settings = parse_settings(written)
    assert (settings.required, settings.minimum_questions) == (required, least)


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"sequence_length": 3}, "sequence_length"),
        ({"sequence_length": 13}, "sequence_length"),
        ({"completed": 1}, "completed"),
        ({"completed": 8}, "completed"),
        ({"maximum_value": 1}, "maximum_value"),
        ({"maximum_value": 0}, "maximum_value"),
        ({"timeout": "0s"}, "timeout"),
        ({"timeout": 90}, "timeout"),
        ({"consecutive": "yes"}, "consecutive"),
        ({"minimum_value": 1.5}, "minimum_value"),
        ({"correct_answers_required": 0}, "correct_answers_required"),
        ({"colour": "blue"}, "colour"),
    ],
)
def test_bad_settings_fail_the_policy_load_and_keep_the_previous_policy(tmp_path, change, field):
    good = _policy(tmp_path, {})
    path = _write(tmp_path, _house({**change}))
    with pytest.raises(ConfigError) as raised:
        load(path, previous=good)
    message = str(raised.value)
    assert "'skip_counting/count'" in message
    assert f"body.{field}" in message
    assert good.task(TaskKey("skip_counting", "count")).document() == {}


@pytest.mark.parametrize(
    "difference",
    [_differences(0), [{"from": -5, "to": 5, "weight": 1}], [{"from": 0, "to": 3, "weight": 1}]],
    ids=["zero", "across-zero", "from-zero"],
)
def test_a_difference_of_zero_is_rejected(difference):
    with pytest.raises(ValueError, match="^difference entry 1: 0 is not a difference"):
        parse_settings({"difference": difference})


def test_negative_differences_and_ranges_are_accepted():
    settings = parse_settings(
        {"difference": [{"from": -5, "to": -1, "weight": 1}, {"from": 1, "to": 5, "weight": 1}, {"value": -10, "weight": 2}]}
    )
    assert settings.differences.weight(-3) == 1
    assert settings.differences.weight(-10) == 2
    assert settings.differences.weight(0) == 0


@pytest.mark.parametrize(
    "difference",
    [
        _differences(5, 5),
        [{"from": 1, "to": 5, "weight": 1}, {"from": 5, "to": 9, "weight": 1}],
        [{"value": 5, "weight": 0}],
        [{"value": 5, "from": 1, "to": 6, "weight": 1}],
        [],
    ],
    ids=["repeated", "overlap", "zero-weight", "both", "empty"],
)
def test_a_bad_difference_list_is_rejected_as_for_operands(difference):
    with pytest.raises(ValueError, match="^difference"):
        parse_settings({"difference": difference})


@pytest.mark.parametrize(
    ("written", "field"),
    [
        ({"minimum_questions": 11, "maximum_questions": 10}, "minimum_questions"),
        ({"correct_answers_required": 11, "maximum_questions": 10}, "correct_answers_required"),
    ],
)
def test_question_limits_that_cannot_work_are_rejected(written, field):
    with pytest.raises(ValueError, match=f"^{field}:"):
        parse_settings(written)


def test_counting_by_one_hundred_needs_starts_that_are_not_multiples():
    settings = parse_settings({"difference": _differences(100)})
    assert len(settings.starts(100)) == 299
    with pytest.raises(ValueError, match="counting by 100, starting on a multiple of it, allows only 2 sequences"):
        parse_settings({"difference": _differences(100), "multiples_only": True})


def test_the_default_differences_do_not_fit_twelve_numbers():
    with pytest.raises(ValueError, match="^difference entry 5: counting by 100 allows only 0 sequences"):
        parse_settings({"sequence_length": 12})


def _naive_starts(difference, length, minimum, maximum, multiples_only):
    found = []
    for start in range(minimum - 200, maximum + 201):
        sequence = [start + difference * position for position in range(length)]
        if all(minimum <= value <= maximum for value in sequence):
            if not multiples_only or start % abs(difference) == 0:
                found.append(start)
    return found


def test_a_range_of_differences_is_rejected_exactly_when_one_of_them_allows_too_few():
    rng = random.Random(21)
    for _ in range(400):
        length = rng.randint(4, 6)
        minimum = rng.randint(-30, 30)
        maximum = minimum + rng.randint(20, 90)
        multiples_only = rng.random() < 0.7
        low = rng.randint(1, 8)
        high = low + rng.randint(0, 12)
        sign = rng.choice((1, -1))
        values = range(low, high + 1)
        entry = {"from": low, "to": high, "weight": 1} if sign > 0 else {"from": -high, "to": -low, "weight": 1}
        body = {
            "sequence_length": length,
            "completed": 2,
            "minimum_value": minimum,
            "maximum_value": maximum,
            "multiples_only": multiples_only,
            "difference": [entry],
            "correct_answers_required": 1,
        }
        counts = {sign * value: len(_naive_starts(sign * value, length, minimum, maximum, multiples_only)) for value in values}
        too_few = [value for value, count in counts.items() if count < 3]
        if too_few:
            with pytest.raises(ValueError, match="^difference entry 1: counting by"):
                parse_settings(body)
        else:
            settings = parse_settings(body)
            assert {value: len(settings.starts(value)) for value in counts} == counts


def test_a_difference_may_set_its_own_range():
    body = {
        "minimum_value": 1,
        "maximum_value": 999,
        "difference": [
            {"value": 2, "weight": 1, "maximum_value": 99},
            {"from": -10, "to": -5, "weight": 1, "minimum_value": -40, "maximum_value": 60},
            {"value": 25, "weight": 1},
        ],
    }
    settings = parse_settings(body)
    assert settings.range_for(2) == (1, 99)
    assert settings.range_for(-7) == (-40, 60)
    assert settings.range_for(25) == (1, 999)
    assert settings.width == 3
    assert settings.negative is True
    questions = _issued(body, 1500)
    for question in questions:
        minimum, maximum = settings.range_for(question["difference"])
        assert all(minimum <= value <= maximum for value in question["sequence"])
    assert max(max(q["sequence"]) for q in questions if q["difference"] == 25) > 99


def test_the_default_caps_never_go_above_the_body_maximum():
    settings = parse_settings({"maximum_value": 400, "sequence_length": 4})
    assert [settings.range_for(value) for value in (2, 5, 10, 25, -10)] == [(1, 99), (1, 199), (1, 400), (1, 400), (1, 400)]
    with pytest.raises(ValueError, match="^difference entry 1: maximum_value 99 must be greater than minimum_value 120; the default list"):
        parse_settings({"minimum_value": 120})


def test_a_range_wider_than_the_body_widens_every_box():
    settings = parse_settings({"maximum_value": 99, "difference": [{"value": 10, "weight": 1, "maximum_value": 1000}, {"value": 2, "weight": 1}]})
    assert settings.width == 4


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ({"value": 2, "weight": 1, "maximum_value": 1}, "^difference entry 1: maximum_value 1 must be greater than minimum_value 1"),
        ({"value": 2, "weight": 1, "minimum_value": 2.5}, "^difference entry 1: minimum_value: must be a whole number"),
        ({"value": 10, "weight": 1, "maximum_value": 50}, "^difference entry 1: counting by 10 allows only 0 sequences of 8 numbers between 1 and 50"),
        ({"value": 2, "weight": 1, "colour": "red"}, "^difference entry 1: unknown setting colour"),
    ],
    ids=["backwards", "not-whole", "too-narrow", "unknown"],
)
def test_a_bad_range_on_a_difference_is_rejected(entry, message):
    with pytest.raises(ValueError, match=message):
        parse_settings({"difference": [entry]})


def test_the_question_count_uses_each_difference_range():
    body = {**{"sequence_length": 4, "completed": 2}, "difference": [{"value": 2, "weight": 1, "maximum_value": 20}], "maximum_questions": 15}
    with pytest.raises(ValueError, match="^maximum_questions: the differences allow only 14 distinct sequences"):
        parse_settings(body)


FOURTEEN = {"sequence_length": 4, "completed": 2, "minimum_value": 1, "maximum_value": 20, "difference": _differences(2)}


def test_the_differences_must_allow_enough_sequences_for_the_questions():
    assert len(parse_settings(FOURTEEN).starts(2)) == 14
    assert parse_settings({**FOURTEEN, "maximum_questions": 14}).maximum_questions == 14
    with pytest.raises(ValueError, match="^maximum_questions: the differences allow only 14 distinct sequences"):
        parse_settings({**FOURTEEN, "maximum_questions": 15})
    with pytest.raises(ValueError, match="^correct_answers_required: .* 14 distinct sequences"):
        parse_settings({**FOURTEEN, "correct_answers_required": 15})
    with pytest.raises(ValueError, match="^minimum_questions: .* 14 distinct sequences"):
        parse_settings({**FOURTEEN, "minimum_questions": 15})


def test_the_story_example_loads_and_needs_eight_points(tmp_path):
    body = {
        "sequence_length": 10,
        "completed": 4,
        "minimum_value": 0,
        "maximum_value": 200,
        "difference": [
            {"value": 2, "weight": 3},
            {"value": 5, "weight": 2},
            {"value": 10, "weight": 1},
            {"value": -2, "weight": 3},
            {"value": -5, "weight": 2},
            {"value": -10, "weight": 1},
        ],
        "minimum_questions": 10,
        "maximum_questions": 15,
        "timeout": "2m",
    }
    policy = _policy(tmp_path, body)
    settings = parse_settings(policy.task(TaskKey("skip_counting", "count")).document())
    assert (settings.required, settings.minimum_questions, settings.maximum_questions) == (8, 10, 15)
    assert settings.timeout == 120_000


# Drawing questions


def _issued(body: dict, count: int, seed: int = 7) -> list[dict]:
    session = Session({}, body)
    session.visit(START)
    rng = random.Random(seed)
    return [session.issue(START, rng) for _ in range(count)]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"minimum_value": -50, "maximum_value": 50, "difference": [{"from": -7, "to": -1, "weight": 1}, {"from": 1, "to": 7, "weight": 1}]},
        {"minimum_value": -300, "maximum_value": -100, "sequence_length": 12, "difference": _differences(-9, 4, 11)},
        {"multiples_only": True, "minimum_value": -40, "maximum_value": 40, "difference": _differences(-3, 2, 5)},
    ],
    ids=["defaults", "across-zero", "all-negative", "multiples"],
)
def test_every_sequence_stays_in_range_and_counts_by_its_difference(body):
    settings = parse_settings(body)
    for question in _issued(body, 2000):
        sequence = question["sequence"]
        minimum, maximum = settings.range_for(question["difference"])
        assert len(sequence) == settings.length
        assert all(minimum <= value <= maximum for value in sequence)
        assert all(right - left == question["difference"] for left, right in zip(sequence, sequence[1:]))
        assert sequence[0] == question["start"]


def test_with_the_default_minimum_counting_down_never_reaches_zero():
    body = {"difference": _differences(-2, -5, -25, -100)}
    questions = _issued(body, 2000)
    assert min(min(question["sequence"]) for question in questions) >= 1


def test_a_range_across_zero_has_sequences_crossing_zero_both_ways():
    body = {"minimum_value": -50, "maximum_value": 50, "difference": _differences(-5, -3, 3, 5)}
    questions = _issued(body, 3000)
    crossing = [question for question in questions if min(question["sequence"]) < 0 < max(question["sequence"])]
    assert any(question["difference"] > 0 for question in crossing)
    assert any(question["difference"] < 0 for question in crossing)


def test_multiples_only_starts_on_a_multiple_and_otherwise_need_not():
    body = {"difference": _differences(5, -5, 10)}
    strict = _issued({**body, "multiples_only": True}, 2000)
    assert all(value % abs(question["difference"]) == 0 for question in strict for value in question["sequence"])
    loose = _issued(body, 2000)
    assert any(question["start"] % abs(question["difference"]) for question in loose)


def _adjacent(filled) -> bool:
    return any(right - left == 1 for left, right in zip(filled, filled[1:]))


def test_by_default_only_twenty_fives_start_on_a_multiple():
    settings = parse_settings({})
    assert [settings.bounds_for(value).multiples_only for value in (2, 5, 10, 25, 100, -2, -5, -10, -25, -100)] == [
        False, False, False, True, False, False, False, False, True, False
    ]
    questions = _issued({}, 3000)
    fives = [question for question in questions if abs(question["difference"]) == 25]
    assert fives
    assert all(value % 25 == 0 for question in fives for value in question["sequence"])
    assert any(question["start"] % abs(question["difference"]) for question in questions if abs(question["difference"]) != 25)


def test_a_difference_may_set_multiples_only_either_way():
    body = {
        "multiples_only": True,
        "difference": [
            {"value": 3, "weight": 1, "multiples_only": False},
            {"value": 5, "weight": 1},
            {"value": -4, "weight": 1},
        ],
    }
    questions = _issued(body, 2000)
    assert any(question["start"] % 3 for question in questions if question["difference"] == 3)
    assert all(value % 5 == 0 for question in questions if question["difference"] == 5 for value in question["sequence"])
    assert all(value % 4 == 0 for question in questions if question["difference"] == -4 for value in question["sequence"])
    loose = _issued({"difference": [{"value": 3, "weight": 1, "multiples_only": True}, {"value": 7, "weight": 1}]}, 2000)
    assert all(value % 3 == 0 for question in loose if question["difference"] == 3 for value in question["sequence"])
    assert any(question["start"] % 7 for question in loose if question["difference"] == 7)


def test_multiples_only_on_one_difference_is_checked_for_enough_sequences():
    with pytest.raises(ValueError, match="^difference entry 2: counting by 100, starting on a multiple of it, allows only 2"):
        parse_settings({"difference": [{"value": 2, "weight": 1}, {"value": 100, "weight": 1, "multiples_only": True}]})
    with pytest.raises(ValueError, match="^difference entry 1: multiples_only: must be true or false"):
        parse_settings({"difference": [{"value": 2, "weight": 1, "multiples_only": "yes"}]})


def test_the_filled_positions_meet_the_consecutive_rule():
    together = _issued({"completed": 3}, 2000)
    assert all(len(question["filled"]) == 3 for question in together)
    assert all(_adjacent(question["filled"]) for question in together)
    apart = _issued({"completed": 3, "consecutive": False}, 2000)
    assert all(len(question["filled"]) == 3 for question in apart)
    assert any(not _adjacent(question["filled"]) for question in apart)
    assert any(_adjacent(question["filled"]) for question in apart)


def test_every_allowed_set_of_filled_positions_is_equally_likely():
    settings = parse_settings({"sequence_length": 4, "completed": 2, "difference": _differences(3)})
    rng = random.Random(5)
    counts = Counter(draw_filled(settings, rng) for _ in range(30_000))
    assert set(counts) == {(0, 1), (1, 2), (2, 3)}
    assert all(abs(count / 30_000 - 1 / 3) < TOLERANCE for count in counts.values())


def test_no_difference_follows_itself_within_two_questions():
    differences = [question["difference"] for question in _issued({}, 1000)]
    for index, difference in enumerate(differences):
        assert difference not in differences[max(0, index - 2) : index]


def test_with_the_last_two_left_out_the_rest_keep_their_weights():
    settings = parse_settings({"difference": [{"value": value, "weight": value} for value in (2, 3, 4, 5, 6)]})
    rng = random.Random(11)
    drawn = Counter(draw_difference(settings, [2, 5], rng) for _ in range(SAMPLES))
    assert set(drawn) == {3, 4, 6}
    for value in (3, 4, 6):
        assert abs(drawn[value] / SAMPLES - value / 13) < TOLERANCE


def test_two_differences_alternate_and_one_is_always_used():
    two = [question["difference"] for question in _issued({"difference": _differences(2, 5)}, 40)]
    assert all(left != right for left, right in zip(two, two[1:]))
    one = [question["difference"] for question in _issued({"difference": _differences(5)}, 10)]
    assert one == [5] * 10


def test_no_start_repeats_the_last_two_starts_for_its_difference():
    body = {**FOURTEEN, "difference": _differences(2)}
    starts = [question["start"] for question in _issued(body, 500)]
    for index, start in enumerate(starts):
        assert start not in starts[max(0, index - 2) : index]
    three = {
        "sequence_length": 4,
        "completed": 2,
        "minimum_value": 1,
        "maximum_value": 15,
        "difference": _differences(4),
        "correct_answers_required": 3,
    }
    starts = [question["start"] for question in _issued(three, 30)]
    assert starts[3:] == starts[:-3]
    assert len(set(starts[:3])) == 3


def test_the_question_sent_to_the_browser_has_only_the_filled_in_numbers(tmp_path):
    quiz = Quiz(tmp_path, {"minimum_value": -50, "maximum_value": 50, "difference": _differences(-3, 3, 7)})
    quiz.open(START)
    question = quiz.ask(START)
    stored = quiz.question()
    assert set(question) == {"id", "boxes", "width", "negative", "allowed_ms", "points", "required", "number", "maximum", "finished"}
    assert question["width"] == 3
    assert question["negative"] is True
    for position, value in enumerate(stored["sequence"]):
        assert question["boxes"][position] == (value if position in stored["filled"] else None)


# Entering and trying


def test_a_correct_first_try_scores_one_point(tmp_path):
    quiz = Quiz(tmp_path, {})
    quiz.open(START)
    question = quiz.ask(START)
    result = quiz.answer(START + timedelta(seconds=5), question["id"], quiz.right_entries())
    assert result["outcome"] == "correct"
    assert result["try"] == 1
    assert result["points"] == 1
    assert result["sound"].startswith("/static/sounds/correct/")
    assert result["sequence"] == quiz.question()["sequence"]


def test_a_wrong_first_try_says_how_many_and_a_right_second_try_scores_half(tmp_path):
    quiz = Quiz(tmp_path, {})
    quiz.open(START)
    question = quiz.ask(START)
    result = quiz.answer(START + timedelta(seconds=5), question["id"], quiz.wrong_entries(2))
    assert result["outcome"] == "wrong"
    assert result["wrong"] == 2
    assert result["right"] is None
    assert result["sequence"] is None
    assert result["sound"].startswith("/static/sounds/incorrect/")
    assert quiz.question()["outcome"] is None
    result = quiz.answer(START + timedelta(seconds=9), question["id"], quiz.right_entries())
    assert (result["outcome"], result["try"], result["points"]) == ("correct", 2, 0.5)


def test_a_wrong_second_try_says_which_boxes_were_right_and_a_right_third_scores_a_quarter(tmp_path):
    quiz = Quiz(tmp_path, {"sequence_length": 8, "completed": 3})
    quiz.open(START)
    question = quiz.ask(START)
    quiz.answer(START + timedelta(seconds=5), question["id"], quiz.wrong_entries(3))
    result = quiz.answer(START + timedelta(seconds=9), question["id"], quiz.wrong_entries(2))
    blanks = blank_positions(quiz.question())
    assert result["outcome"] == "wrong"
    assert result["wrong"] == 2
    assert result["right"] == blanks[2:]
    assert result["sound"].startswith("/static/sounds/incorrect/")
    result = quiz.answer(START + timedelta(seconds=12), question["id"], quiz.right_entries())
    assert (result["outcome"], result["try"], result["points"]) == ("correct", 3, 0.25)


def test_a_wrong_third_try_scores_nothing_and_gives_the_answer(tmp_path):
    quiz = Quiz(tmp_path, {})
    quiz.open(START)
    question = quiz.ask(START)
    for offset in (3, 6):
        quiz.answer(START + timedelta(seconds=offset), question["id"], quiz.wrong_entries(1))
    result = quiz.answer(START + timedelta(seconds=9), question["id"], quiz.wrong_entries(1))
    assert result["outcome"] == "incorrect"
    assert result["points"] == 0
    assert result["sequence"] == quiz.question()["sequence"]
    assert result["blanks"] == blank_positions(quiz.question())
    assert result["sound"].startswith("/static/sounds/incorrect/")
    assert quiz.question()["points"] == 0
    assert quiz.question()["correct_try"] is None


def test_a_fourth_try_and_a_blank_box_are_refused_without_using_a_try(tmp_path):
    quiz = Quiz(tmp_path, {})
    quiz.open(START)
    question = quiz.ask(START)
    blanked = quiz.right_entries()
    blanked[0] = "-"
    status, _payload = quiz.post(START + timedelta(seconds=1), "answer", {"id": question["id"], "entries": blanked})
    assert status == 400
    assert quiz.question()["tries"] == []
    for offset in (2, 3, 4):
        quiz.answer(START + timedelta(seconds=offset), question["id"], quiz.wrong_entries(1))
    status, _payload = quiz.post(START + timedelta(seconds=5), "answer", {"id": question["id"], "entries": quiz.right_entries()})
    assert status == 409
    assert len(quiz.question()["tries"]) == 3
    assert quiz.question()["outcome"] == "incorrect"


def test_negative_answers_are_accepted_in_the_boxes(tmp_path):
    quiz = Quiz(tmp_path, {"minimum_value": -50, "maximum_value": 50, "difference": _differences(-5, 5, 3)})
    quiz.open(START)
    now = START
    seen_negative = False
    for _ in range(12):
        question = quiz.ask(now)
        entries = quiz.right_entries()
        seen_negative = seen_negative or any(entry.startswith("-") for entry in entries)
        assert quiz.answer(now + timedelta(seconds=2), question["id"], entries)["outcome"] == "correct"
        now += timedelta(seconds=5)
        if quiz.attempt().outcome != "in_progress":
            break
    assert seen_negative


def test_a_leading_zero_is_the_same_number(tmp_path):
    quiz = Quiz(tmp_path, {"minimum_value": 10, "maximum_value": 99, "sequence_length": 4, "completed": 2, "difference": _differences(3)})
    quiz.open(START)
    question = quiz.ask(START)
    entries = ["0" + entry for entry in quiz.right_entries()]
    assert quiz.answer(START + timedelta(seconds=2), question["id"], entries)["outcome"] == "correct"


def test_the_timer_runs_through_every_try(tmp_path):
    quiz = Quiz(tmp_path, {"timeout": "30s"})
    quiz.open(START)
    question = quiz.ask(START)
    assert question["allowed_ms"] == 30_000
    quiz.answer(START + timedelta(seconds=20), question["id"], quiz.wrong_entries(1))
    late = START + timedelta(milliseconds=30_000 + NETWORK_ALLOWANCE_MS + 1)
    result = quiz.answer(late, question["id"], quiz.right_entries())
    assert result["outcome"] == "timeout"
    assert result["points"] == 0
    assert result["sound"].startswith("/static/sounds/timeout/")


# Timer and server timing


@pytest.mark.parametrize(("wrong_tries", "points"), [(0, 1), (1, 0.5), (2, 0.25)])
def test_every_box_right_when_the_timer_runs_out_scores_for_that_try(tmp_path, wrong_tries, points):
    quiz = Quiz(tmp_path, {"timeout": "30s"})
    quiz.open(START)
    question = quiz.ask(START)
    for offset in range(wrong_tries):
        quiz.answer(START + timedelta(seconds=offset + 1), question["id"], quiz.wrong_entries(1))
    result = quiz.answer(START + timedelta(seconds=30), question["id"], quiz.right_entries(), expired=True)
    assert result["outcome"] == "correct"
    assert result["try"] == wrong_tries + 1
    assert result["points"] == points
    assert result["sound"].startswith("/static/sounds/correct/")
    assert quiz.question()["tries"][-1]["expired"] is True


@pytest.mark.parametrize("kind", ["blank", "wrong"])
def test_a_blank_or_wrong_box_when_the_timer_runs_out_is_a_timeout(tmp_path, kind):
    quiz = Quiz(tmp_path, {"timeout": "30s"})
    quiz.open(START)
    question = quiz.ask(START)
    entries = quiz.wrong_entries(1)
    if kind == "blank":
        entries[0] = ""
    result = quiz.answer(START + timedelta(seconds=30), question["id"], entries, expired=True)
    assert result["outcome"] == "timeout"
    assert result["points"] == 0
    assert result["sound"].startswith("/static/sounds/timeout/")
    assert result["sequence"] == quiz.question()["sequence"]


def test_the_server_clock_decides_whether_a_try_was_in_time(tmp_path):
    quiz = Quiz(tmp_path, {"timeout": "30s"})
    quiz.open(START)
    question = quiz.ask(START)
    edge = START + timedelta(milliseconds=30_000 + NETWORK_ALLOWANCE_MS)
    assert quiz.answer(edge, question["id"], quiz.right_entries())["outcome"] == "correct"
    later = edge + timedelta(seconds=5)
    question = quiz.ask(later)
    entries = quiz.right_entries()
    late = later + timedelta(milliseconds=30_000 + NETWORK_ALLOWANCE_MS + 1)
    result = quiz.answer(late, question["id"], entries)
    assert result["outcome"] == "timeout"
    stored = quiz.question()
    assert stored["tries"] == [{"entries": entries, "wrong": 0, "expired": False, "received_ms": 30_501}]


# Finishing


def test_with_no_limits_the_answer_that_reaches_eight_points_passes(tmp_path):
    quiz = Quiz(tmp_path, {})
    quiz.open(START)
    plan = ["1", "1", "2", "3", "x", "t"] + ["1"] * 5 + ["3", "1"]
    results = quiz.play(plan)
    assert [result["finished"] for result in results] == [False] * 11 + [True]
    last = results[-1]
    assert last["points"] == 8
    assert last["result"] == "pass"
    assert last["sound"].startswith("/static/sounds/correct/")
    passed = quiz.attempt()
    assert passed.outcome == "pass"
    assert passed.finished_at == quiz.answered.replace(microsecond=0)
    assert quiz.store.passes_on("younger", START.date()) == 1


def test_a_minimum_of_ten_waits_for_the_tenth_question_whatever_it_scores(tmp_path):
    quiz = Quiz(tmp_path, {"minimum_questions": 10})
    quiz.open(START)
    results = quiz.play(["1"] * 8 + ["x", "t"])
    assert [result["finished"] for result in results] == [False] * 9 + [True]
    assert results[-1]["outcome"] == "timeout"
    assert results[-1]["result"] == "pass"
    assert quiz.attempt().outcome == "pass"


def test_reaching_the_maximum_without_the_points_is_a_failure_with_its_cooldown(tmp_path):
    quiz = Quiz(tmp_path, {"maximum_questions": 15, "correct_answers_required": 14}, failure_cooldown=2)
    quiz.open(START)
    results = quiz.play(["1"] * 13 + ["x", "x"])
    assert [result["finished"] for result in results] == [False] * 14 + [True]
    assert results[-1]["result"] == "failure"
    failed = quiz.attempt()
    assert failed.outcome == "failure"
    task = quiz.policy.task(TaskKey("skip_counting", "count"))
    assert not quiz.store.is_eligible(task, "younger", START.date() + timedelta(days=1))
    assert quiz.store.is_eligible(task, "younger", START.date() + timedelta(days=2))
    assert skip_days(TaskKey("skip_counting", "count"), "younger", quiz.store.attempts("younger")) == {START.date()}


@pytest.mark.parametrize(
    ("body", "plan", "ends_after"),
    [
        ({"minimum_questions": 10, "maximum_questions": 15}, ["1", "1", "3", "2"] + ["x"] * 6, 10),
        ({"maximum_questions": 15}, ["1", "1", "3", "2"] + ["x"] * 6, 10),
        ({"minimum_questions": 12, "maximum_questions": 15}, ["1"] + ["x"] * 11, 12),
    ],
    ids=["min-10-max-15", "max-15", "min-12-max-15"],
)
def test_the_attempt_fails_once_full_marks_cannot_reach_the_points(tmp_path, body, plan, ends_after):
    quiz = Quiz(tmp_path, body)
    quiz.open(START)
    results = quiz.play(plan)
    assert len(results) == ends_after
    assert [result["finished"] for result in results] == [False] * (ends_after - 1) + [True]
    assert results[-1]["result"] == "failure"
    assert quiz.attempt().outcome == "failure"


@pytest.mark.parametrize(
    "body",
    [{"minimum_questions": 10, "maximum_questions": 15}, {"maximum_questions": 15}],
    ids=["min-10-max-15", "max-15"],
)
def test_three_points_after_ten_questions_keeps_going(tmp_path, body):
    quiz = Quiz(tmp_path, body)
    quiz.open(START)
    results = quiz.play(["1", "1", "1"] + ["x"] * 7)
    assert results[-1]["points"] == 3
    assert results[-1]["number"] == 10
    assert results[-1]["finished"] is False
    assert quiz.attempt().outcome == "in_progress"


def test_with_only_a_maximum_eight_points_pass_well_before_it(tmp_path):
    quiz = Quiz(tmp_path, {"maximum_questions": 15})
    quiz.open(START)
    results = quiz.play(["1"] * 8)
    assert results[-1]["result"] == "pass"
    assert results[-1]["number"] == 8


def test_three_wrong_answers_to_start_do_not_end_an_attempt_of_ten(tmp_path):
    quiz = Quiz(tmp_path, {"maximum_questions": 10})
    quiz.open(START)
    results = quiz.play(["x", "x", "x", "1", "1", "1", "1", "x"])
    assert [result["finished"] for result in results] == [False] * 7 + [True]
    assert results[-1]["number"] == 8
    assert results[-1]["result"] == "failure"


def test_with_no_maximum_wrong_answers_and_timeouts_never_fail(tmp_path):
    quiz = Quiz(tmp_path, {})
    quiz.open(START)
    results = quiz.play(["x", "t"] * 15)
    assert not any(result["finished"] for result in results)
    assert quiz.attempt().outcome == "in_progress"


def test_the_progress_shows_quarter_points_and_the_question_number(tmp_path):
    assert [format_points(points) for points in (0, 5, 5.25, 5.5, 5.75)] == ["0", "5", "5.25", "5.5", "5.75"]
    quiz = Quiz(tmp_path, {"maximum_questions": 15})
    quiz.open(START)
    quiz.play(["1", "1", "1", "1", "2", "3"])
    page = quiz.open(quiz.now + timedelta(seconds=5))
    assert "4.75 / 8 points" in page.body
    assert "Question 7 of 15" in page.body
    plain = Quiz(tmp_path / "plain", {})
    assert "Question 1<" in plain.open(START).body


def test_the_end_offers_the_next_task_only_when_one_is_eligible(tmp_path):
    other = """\
  spelling:
    spelling:
      group: younger
      pass_cooldown: 0
"""
    with_other = Quiz(tmp_path / "a", {"maximum_questions": 8}, extra=other)
    with_other.open(START)
    result = with_other.play(["x"] * 8)[-1]
    assert result["result"] == "failure"
    assert result["next"] == "https://tasks.example/tasks/next"
    alone = Quiz(tmp_path / "b", {"maximum_questions": 8}, cooldown=1, failure_cooldown=1)
    alone.open(START)
    result = alone.play(["1"] * 8)[-1]
    assert result["result"] == "pass"
    assert result["next"] is None


BACK = "https://www.youtube.com/watch?v=abc123"


def test_a_pass_carries_the_page_to_go_back_to_and_a_failure_does_not(tmp_path):
    for name, entries, verdict, back in (("a", "1", "pass", BACK), ("b", "x", "failure", None)):
        quiz = Quiz(tmp_path / name, {"maximum_questions": 8})
        quiz.back = lambda: BACK
        quiz.open(START)
        result = quiz.play([entries] * 8)[-1]
        assert (result["result"], result["back"]) == (verdict, back)


@needs_node
@pytest.mark.parametrize(("verdict", "gone"), [("pass", [(5000, BACK)]), ("failure", [])])
def test_well_done_after_a_pass_counts_down_to_the_page_and_a_failure_does_not(tmp_path, verdict, gone):
    page = Quiz(tmp_path, {}).open(START).body
    ended = {"points": 8, "required": 8, "number": 8, "maximum": None, "finished": True}
    replies = {"visit": [{**ended, "result": verdict, "next": None, "back": BACK if verdict == "pass" else None}]}
    events = run_page(page, replies, steps=[{"snap": ["going-back", "back-host"]}, {"wait": 10_000}])
    snap = next(event["elements"] for event in events if event["kind"] == "snap")
    assert snap["going-back"]["hidden"] is (verdict != "pass")
    assert [(event["at"], event["what"]) for event in events if event["kind"] == "navigate"] == gone


_MEASURE = """\
<script>
const boxes = [...document.querySelectorAll(".box")].map((box) => {
  const style = getComputedStyle(box);
  const text = document.createElement("canvas").getContext("2d");
  text.font = [style.fontStyle, style.fontWeight, style.fontSize, style.fontFamily].join(" ");
  return {
    value: box.value,
    text: text.measureText(box.value).width,
    room: box.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight),
  };
});
const row = document.getElementById("row").getBoundingClientRect();
document.getElementById("out").textContent = JSON.stringify({boxes, left: row.left, right: row.right, window: innerWidth});
</script>
"""


def _installed(font: str) -> bool:
    if shutil.which("fc-list") is None:
        return False
    return bool(subprocess.run(["fc-list", f"{font}:style=Bold", "family"], capture_output=True, text=True).stdout.strip())


SANS_FONTS = [
    pytest.param(font, marks=pytest.mark.skipif(not _installed(font), reason=f"{font} is not installed"))
    for font in ("DejaVu Sans", "Liberation Sans", "Adwaita Sans", "Cantarell")
]


def _layout(tmp_path: Path, values: list[str], width: int, window: tuple[int, int], font: str) -> dict:
    """Lay out a row of boxes with the page's own styles in headless Chromium and measure it.

    The page asks only for ``sans-serif``, so the font is whatever the child's computer
    has as its default. ``font`` stands in for that default.
    """
    style = re.search(r"<style>(.*?)</style>", Quiz(tmp_path, {}).open(START).body, re.S).group(1)
    cells = "".join(f'<div class="cell"><input class="box given" value="{value}" readonly></div>' for value in values)
    page = tmp_path / "row.html"
    page.write_text(
        f"<!doctype html><html><head><style>{style}body {{ font-family: '{font}'; }}</style></head><body>"
        f'<div id="row" class="row" style="--n: {len(values)}; --w: {width}">{cells}</div>'
        f'<pre id="out"></pre>{_MEASURE}</body></html>'
    )
    run = subprocess.run(
        [
            CHROMIUM,
            "--headless",
            "--disable-gpu",
            f"--user-data-dir={tmp_path / 'chromium'}",
            f"--window-size={window[0]},{window[1]}",
            "--dump-dom",
            page.as_uri(),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(html.unescape(re.search(r'<pre id="out">(.*?)</pre>', run.stdout, re.S).group(1)))


@needs_chromium
@pytest.mark.parametrize("font", SANS_FONTS)
@pytest.mark.parametrize(("values", "width"), [(["100", "888", "-99"], 3), (["-100", "-888", "1000"], 4)])
def test_the_widest_numbers_fit_inside_their_boxes(tmp_path, values, width, font):
    measured = _layout(tmp_path, values, width, (1280, 800), font)
    for box in measured["boxes"]:
        assert box["text"] <= box["room"], box


@needs_chromium
@pytest.mark.parametrize("font", SANS_FONTS)
def test_a_long_row_of_wide_boxes_still_fits_a_narrow_window(tmp_path, font):
    measured = _layout(tmp_path, [str(-100 - 25 * n) for n in range(12)], 4, (420, 800), font)
    assert measured["left"] >= 0 and measured["right"] <= measured["window"], measured
    for box in measured["boxes"]:
        assert box["text"] <= box["room"], box


_MEASURE_HEADER = """\
<script>
const place = (id) => {
  const box = document.getElementById(id).getBoundingClientRect();
  return {left: box.left, right: box.right};
};
document.getElementById("out").textContent = JSON.stringify(
  {progress: place("progress"), number: place("number"), giveUp: place("give-up"), window: innerWidth}
);
</script>
"""


def _header(tmp_path: Path, *, asking: bool) -> dict:
    """Lay out the page's header in headless Chromium, as on the start screen or while a question is up."""
    body = Quiz(tmp_path, {}).open(START).body
    if asking:
        body = body.replace('<span id="progress" hidden>', '<span id="progress">')
        body = body.replace('<span id="number" hidden>', '<span id="number">')
    page = tmp_path / "header.html"
    page.write_text(body.replace("</body>", f'<pre id="out"></pre>{_MEASURE_HEADER}</body>'), encoding="utf-8")
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
    return json.loads(html.unescape(re.search(r'<pre id="out">(.*?)</pre>', run.stdout, re.S).group(1)))


@needs_chromium
@pytest.mark.parametrize("asking", [False, True])
def test_try_a_different_task_sits_at_the_top_right(tmp_path, asking):
    measured = _header(tmp_path, asking=asking)
    assert measured["giveUp"]["left"] > measured["window"] / 2, measured
    assert measured["window"] - measured["giveUp"]["right"] < 40, measured


@needs_chromium
def test_the_question_number_stays_midway_between_the_progress_and_try_a_different_task(tmp_path):
    measured = _header(tmp_path, asking=True)
    before = measured["number"]["left"] - measured["progress"]["right"]
    after = measured["giveUp"]["left"] - measured["number"]["right"]
    assert measured["progress"]["left"] < 40, measured
    assert abs(before - after) < 2, measured


# Resume, give-up, and record


def test_reloading_after_a_wrong_first_try_is_a_timeout(tmp_path):
    quiz = Quiz(tmp_path, {})
    quiz.open(START)
    quiz.play(["1", "2"])
    showing = quiz.ask(quiz.now)
    quiz.answer(quiz.now + timedelta(seconds=2), showing["id"], quiz.wrong_entries(1))
    page = quiz.open(quiz.now + timedelta(seconds=3))
    stored = quiz.detail()["questions"][showing["id"]]
    assert stored["outcome"] == "timeout"
    assert stored["points"] == 0
    assert len(stored["tries"]) == 1
    assert "1.5 / 8 points" in page.body
    assert "Question 4" in page.body
    following = quiz.ask(quiz.now + timedelta(seconds=4))
    assert following["id"] == showing["id"] + 1
    assert following["number"] == 3


def test_coming_back_within_an_hour_resumes_and_after_an_hour_starts_a_new_run(tmp_path):
    quiz = Quiz(tmp_path, {})
    quiz.open(START)
    quiz.play(["1", "3"])
    page = quiz.open(quiz.now + timedelta(minutes=59))
    assert "1.25 / 8 points" in page.body
    assert len(quiz.detail()["runs"]) == 1
    attempt = quiz.attempt()
    page = quiz.open(quiz.now + timedelta(minutes=59 + 62))
    assert "0 / 8 points" in page.body
    assert "Question 1<" in page.body
    detail = quiz.detail()
    assert quiz.attempt().id == attempt.id
    assert [run["run"] for run in detail["runs"]] == [1, 2]
    assert "expired" in detail["runs"][0]
    assert [item["run"] for item in detail["questions"]] == [1, 1]


def test_giving_up_an_optional_task_closes_the_question_and_abandons(tmp_path):
    quiz = Quiz(tmp_path, {})
    quiz.open(START)
    quiz.ask(START)
    page = quiz.give_up(START + timedelta(seconds=2))
    assert page.status == 302
    assert ("location", "https://tasks.example/tasks/choose") in page.headers
    abandoned = quiz.store.attempts("younger", TaskKey("skip_counting", "count"))[-1]
    assert abandoned.outcome == "abandoned"
    assert abandoned.detail["questions"][-1]["outcome"] == "timeout"


def test_the_only_required_task_keeps_its_progress_when_he_tries_to_give_up(tmp_path):
    quiz = Quiz(tmp_path, {}, due="2026-11-01")
    quiz.open(START)
    quiz.play(["2"])
    showing = quiz.ask(quiz.now)
    page = quiz.give_up(quiz.now + timedelta(seconds=2))
    assert MUST_FINISH in page.body
    assert "0.5 / 8 points" in page.body
    assert quiz.attempt().outcome == "in_progress"
    assert quiz.detail()["questions"][showing["id"]]["outcome"] == "timeout"


def test_giving_up_on_the_last_question_records_the_failure_it_decides(tmp_path):
    quiz = Quiz(tmp_path, {"maximum_questions": 8})
    quiz.open(START)
    quiz.play(["1"] * 7)
    quiz.ask(quiz.now)
    quiz.give_up(quiz.now + timedelta(seconds=2))
    assert quiz.store.attempts("younger", TaskKey("skip_counting", "count"))[-1].outcome == "failure"


def test_a_reload_that_finishes_the_minimum_passes_the_attempt(tmp_path):
    quiz = Quiz(tmp_path, {"minimum_questions": 10})
    quiz.open(START)
    quiz.play(["1"] * 9)
    quiz.ask(quiz.now)
    quiz.fetch(quiz.now + timedelta(seconds=1))
    status, payload = quiz.post(quiz.now + timedelta(seconds=1), "visit", {})
    assert status == 200
    assert payload["finished"] is True
    assert payload["result"] == "pass"
    assert quiz.attempt().outcome == "pass"


def test_each_question_is_stored_in_full_and_shown_in_the_attempt_view(tmp_path):
    quiz = Quiz(tmp_path, {"difference": _differences(5, 10, 25)})
    quiz.open(START)
    question = quiz.ask(START)
    wrong = quiz.wrong_entries(1)
    quiz.answer(START + timedelta(milliseconds=2_340), question["id"], wrong)
    right = quiz.right_entries()
    quiz.answer(START + timedelta(milliseconds=5_000), question["id"], right)
    stored = quiz.question()
    start, difference = stored["start"], stored["difference"]
    assert stored == {
        "run": 1,
        "difference": difference,
        "start": start,
        "sequence": [start + difference * position for position in range(8)],
        "filled": stored["filled"],
        "tries": [
            {"entries": wrong, "wrong": 1, "expired": False, "received_ms": 2_340},
            {"entries": right, "wrong": 0, "expired": False, "received_ms": 5_000},
        ],
        "outcome": "correct",
        "correct_try": 2,
        "points": 0.5,
        "allowed_ms": TIMEOUT_MS,
        "issued": "2026-11-02T16:00:00.000-05:00",
    }
    assert len(stored["filled"]) == 3
    page = json.dumps(attempt_report(quiz.store, str(quiz.attempt().id), now=START))
    assert "correct_try" in page
    assert "0.5" in page
    assert str(stored["sequence"][-1]) in page


def test_the_service_runs_a_skip_counting_question(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    policy_file = _write(tmp_path, _house({"difference": _differences(5)}))
    monkeypatch.setenv("POLICY_FILE", str(policy_file))
    monkeypatch.setenv("POLICY_DB", str(tmp_path / "policy.sqlite3"))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    monkeypatch.setenv("SOUND_DIR", str(_sound_dir(tmp_path / "sounds")))
    app = create_app()

    status, _headers, body = _call(app, "GET", "/tasks/skip_counting/count")
    assert status == 200
    assert b"Skip counting" in body
    assert _call(app, "POST", "/tasks/skip_counting/count", query=b"do=visit", body=b"{}")[0] == 200
    status, headers, body = _call(app, "POST", "/tasks/skip_counting/count", query=b"do=question", body=b"{}")
    assert status == 200
    assert headers["content-type"] == "application/json"
    question = json.loads(body)
    filled = [value for value in question["boxes"] if value is not None]
    first = next(position for position, value in enumerate(question["boxes"]) if value is not None)
    start = question["boxes"][first] - 5 * first
    entries = [str(start + 5 * position) for position, value in enumerate(question["boxes"]) if value is None]
    assert len(filled) == 3
    answer = json.dumps({"id": question["id"], "entries": entries, "expired": False}).encode()
    status, _headers, body = _call(app, "POST", "/tasks/skip_counting/count", query=b"do=answer", body=answer)
    result = json.loads(body)
    assert status == 200
    assert result["outcome"] == "correct"
    assert result["points"] == 1


# Helpers


def _house(
    body: dict,
    *,
    extra: str = "",
    cooldown: int = 0,
    failure_cooldown: int | None = None,
    due: str | None = None,
) -> str:
    due_line = f"      due_date: {due}\n" if due else ""
    failure_line = f"      failure_cooldown: {failure_cooldown}\n" if failure_cooldown is not None else ""
    tasks = (
        f"  skip_counting:\n    count:\n      group: younger\n      pass_cooldown: {cooldown}\n"
        f"{failure_line}{due_line}      body: {json.dumps(body)}\n{extra}"
    )
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


def _write(directory: Path, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "policy.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _policy(directory: Path, body: dict, **house):
    loaded = load(_write(directory, _house(body, **house)))
    assert loaded is not None
    return loaded


def _sound_dir(root: Path) -> Path:
    for outcome, names in {"correct": ["a.mp3"], "incorrect": ["x.m4a"], "timeout": ["bell.opus"]}.items():
        (root / outcome).mkdir(parents=True, exist_ok=True)
        for name in names:
            (root / outcome / name).write_bytes(b"sound")
    return root


class Quiz:
    """One child working through the count task, on a clock the test sets."""

    def __init__(self, directory: Path, body: dict, **house):
        self.policy = _policy(directory, body, **house)
        self.saved = PolicyStore(":memory:")
        self.store = AttemptStore(connection=self.saved.connection)
        self.sounds = load_sounds(_sound_dir(directory / "sounds"), warn=lambda message: None)
        self.back = None
        self.now = START
        self.answered = None

    def _respond(self, now, method, query=None, body=b""):
        return respond_task(
            self.policy,
            self.store,
            method=method,
            path="/tasks/skip_counting/count",
            client_ip=YOUNGER,
            now=now,
            query=query,
            body=body,
            sounds=self.sounds,
            back=self.back,
        )

    def fetch(self, now):
        return self._respond(now, "GET")

    def open(self, now):
        """Load the page in a browser tab: the GET, then the script's visit."""
        self.now = now
        page = self.fetch(now)
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

    def answer(self, now, number, entries, *, expired=False) -> dict:
        status, payload = self.post(now, "answer", {"id": number, "entries": entries, "expired": expired})
        assert status == 200, payload
        return payload

    def attempt(self):
        return self.store.attempts("younger", TaskKey("skip_counting", "count"))[-1]

    def detail(self):
        return self.attempt().detail

    def question(self) -> dict:
        return self.detail()["questions"][-1]

    def right_entries(self) -> list[str]:
        question = self.question()
        return [str(question["sequence"][position]) for position in blank_positions(question)]

    def wrong_entries(self, count: int) -> list[str]:
        """Return the answer with the first ``count`` blank boxes wrong."""
        entries = self.right_entries()
        for index in range(count):
            entries[index] = str(int(entries[index]) + 1)
        return entries

    def play(self, plan) -> list[dict]:
        """Finish one question per step and return the last response of each.

        ``1``, ``2``, and ``3`` are right on that try. ``x`` is wrong three
        times. ``t`` is the timer running out on a wrong box.
        """
        results = []
        for step in plan:
            question = self.ask(self.now)
            self.now += timedelta(seconds=2)
            if step == "t":
                result = self.answer(self.now, question["id"], self.wrong_entries(1), expired=True)
                self.answered = self.now
            else:
                tries = 3 if step == "x" else int(step)
                for attempt in range(1, tries + 1):
                    right = step != "x" and attempt == tries
                    entries = self.right_entries() if right else self.wrong_entries(1)
                    result = self.answer(self.now, question["id"], entries)
                    self.answered = self.now
                    self.now += timedelta(seconds=1)
            results.append(result)
            self.now += timedelta(seconds=3)
            if result["finished"]:
                break
        return results


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
