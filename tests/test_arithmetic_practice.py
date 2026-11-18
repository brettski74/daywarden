"""S039: arithmetic practice mode. The walk, the choice of m, entering and leaving, the page script, and the record."""

import random
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_arithmetic import START, Quiz, _body  # noqa: E402
from test_arithmetic_weighting import SUMS, _plant  # noqa: E402

from conftest import needs_node, run_page  # noqa: E402
from policy.arithmetic import parse_settings  # noqa: E402
from policy.arithmetic_practice import choose_m, index_at, length, restart  # noqa: E402
from policy.fact_figures import NO_FIGURES, book_of  # noqa: E402
from policy.quiz import weighted  # noqa: E402
from policy.review import attempt_report, facts_report  # noqa: E402
from policy.task_page import MUST_FINISH  # noqa: E402

# 7 + n for n from 1 to 10, as the story lists it.
STORY_WALK = [1, 2, 1, 2, 3, 2, 3, 4, 3, 4, 5, 4, 5, 6, 5, 6, 7, 6, 7, 8, 7, 8, 9, 8, 9, 10, 9, 10]
WRONG = "99999"


def _times(**fields) -> dict:
    """The seven times table with `n` from 1 to 10, as an addition task."""
    return _body(first=[{"value": 7}], operands=[{"from": 1, "to": 10}], **fields)


def _values(*entries) -> object:
    return weighted(list(entries), "operands", lambda value, where: value, weights=False)


# The walk: its order, and where a miss starts it again


def test_the_walk_over_ten_values_is_the_story_s_twenty_eight_questions():
    assert length(10) == 28
    assert [index_at(position, 10) + 1 for position in range(length(10))] == STORY_WALK


@pytest.mark.parametrize("count", [5, 6, 13])
def test_the_first_and_last_values_are_asked_twice_and_every_other_three_times(count):
    asked = Counter(index_at(position, count) for position in range(length(count)))
    assert length(count) == 3 * count - 2
    assert [asked[index] for index in range(count)] == [2, *[3] * (count - 2), 2]


@pytest.mark.parametrize(
    ("missed", "fallback", "again"),
    [(2, 3, 0), (7, 3, 4), (3, 3, 0), (9, 3, 6), (7, 1, 6), (7, 20, 0), (0, 3, 0)],
)
def test_a_miss_starts_again_that_many_values_below_or_from_the_first(missed, fallback, again):
    assert restart(missed, fallback) == 3 * again
    assert index_at(restart(missed, fallback), 10) == again


def test_a_range_is_counted_and_looked_up_without_being_listed():
    values = _values({"value": 1}, {"from": 5, "to": 10**12}, {"value": 10**13})
    assert values.count == 10**12 - 2
    assert [values.nth(index) for index in range(4)] == [1, 5, 6, 7]
    assert (values.nth(10**12 - 4), values.nth(10**12 - 3)) == (10**12, 10**13)
    assert values.index_of(10**13) == values.count - 1
    assert values.index_of(5) == 1
    with pytest.raises(ValueError):
        values.index_of(3)


def _walk_ns(quiz):
    return [item["n"] for item in quiz.detail()["practice"][-1]["questions"]]


def _enter(quiz, now):
    status, reply = quiz.post(now, "practice", {})
    assert status == 200, reply
    return reply


def _next(quiz, now):
    status, question = quiz.post(now, "practice_question", {})
    assert status == 200, question
    return question


def _reply(quiz, now, question, text, *, expired=False):
    status, result = quiz.post(now, "practice_answer", {"id": question["id"], "answer": text, "expired": expired})
    assert status == 200, result
    return result


def _play(quiz, script=(), *, start=None, limit=400):
    """Walk until it ends, answering `script` in turn (True is right, False is wrong) and then right. Return the walk."""
    now = start or quiz.now
    for step in range(limit):
        now += timedelta(seconds=1)
        question = _next(quiz, now)
        expected = quiz.detail()["practice"][-1]["questions"][-1]["expected"]
        now += timedelta(seconds=1)
        right = script[step] if step < len(script) else True
        result = _reply(quiz, now, question, str(expected) if right else WRONG)
        if result["finished"]:
            quiz.now = now
            return quiz.detail()["practice"][-1]
    raise AssertionError("the walk did not end")


def _quiz(tmp_path, body=None, **options):
    quiz = Quiz(tmp_path, body or _times(), **options)
    quiz.now = START
    quiz.open(START)
    return quiz


def test_a_walk_with_every_answer_right_asks_the_story_s_questions_and_ends(tmp_path):
    quiz = _quiz(tmp_path)
    assert _enter(quiz, START) == {"practice": {"m": 7, "length": 28}, "correct": 0, "required": 20}
    walk = _play(quiz)
    assert [item["n"] for item in walk["questions"]] == STORY_WALK
    assert [item["question"] for item in walk["questions"][:6]] == [f"7 + {n} =" for n in (1, 2, 1, 2, 3, 2)]
    assert [item["question"] for item in walk["questions"][-5:]] == [f"7 + {n} =" for n in (8, 9, 10, 9, 10)]
    assert [item["position"] for item in walk["questions"]] == list(range(28))
    assert walk["ended"] == "finished" and {item["outcome"] for item in walk["questions"]} == {"correct"}


def test_with_gaps_in_operands_the_walk_steps_through_the_values_in_order(tmp_path):
    quiz = _quiz(tmp_path, _body(first=[{"value": 7}], operands=[{"value": 1}, {"value": 2}, {"value": 5}, {"from": 10, "to": 11}]))
    _enter(quiz, START)
    _play(quiz)
    assert _walk_ns(quiz) == [1, 2, 1, 2, 5, 2, 5, 10, 5, 10, 11, 10, 11]


@pytest.mark.parametrize(
    ("operation", "asked"),
    [
        ("subtraction", ["8 − 7 =", "9 − 7 =", "8 − 7 ="]),
        ("division", ["7 ÷ 7 =", "14 ÷ 7 =", "7 ÷ 7 ="]),
        ("multiplication", ["7 × 1 =", "7 × 2 =", "7 × 1 ="]),
    ],
)
def test_every_operation_walks_n_with_m_fixed(tmp_path, operation, asked):
    quiz = _quiz(tmp_path, _times(operation=operation))
    _enter(quiz, START)
    _play(quiz)
    questions = quiz.detail()["practice"][-1]["questions"]
    assert [item["question"] for item in questions[:3]] == asked
    assert {item["m"] for item in questions} == {7}


def test_a_miss_falls_back_three_values_and_keeps_going_to_the_end(tmp_path):
    quiz = _quiz(tmp_path)
    _enter(quiz, START)
    _play(quiz, [True] * 19 + [False])
    ns = _walk_ns(quiz)
    assert ns[:20] == STORY_WALK[:20]
    assert ns[19] == 8 and ns[20:28] == [5, 6, 5, 6, 7, 6, 7, 8]
    assert ns[-1] == 10 and ns[-2] == 9


def test_missing_seven_plus_three_starts_again_at_seven_plus_one(tmp_path):
    quiz = _quiz(tmp_path)
    _enter(quiz, START)
    _play(quiz, [True, True, True, True, False])
    assert _walk_ns(quiz)[:8] == [1, 2, 1, 2, 3, 1, 2, 1]


def test_a_timeout_falls_back_like_a_wrong_answer_and_there_is_no_limit_on_falling_back(tmp_path):
    quiz = _quiz(tmp_path)
    _enter(quiz, START)
    now = START
    for _ in range(4):
        now += timedelta(seconds=1)
        question = _next(quiz, now)
        result = _reply(quiz, now + timedelta(seconds=10), question, "", expired=True)
        assert result["outcome"] == "timeout" and result["full"] is None and result["position"] == 0
        now += timedelta(seconds=10)
    assert _walk_ns(quiz) == [1, 1, 1, 1]
    walk = quiz.detail()["practice"][-1]
    assert {item["outcome"] for item in walk["questions"]} == {"timeout"}


def test_falling_back_counts_values_of_n_so_three_back_from_eleven_is_two(tmp_path):
    quiz = _quiz(tmp_path, _body(first=[{"value": 7}], operands=[{"value": 1}, {"value": 2}, {"value": 5}, {"from": 10, "to": 11}]))
    _enter(quiz, START)
    _play(quiz, [True] * 12 + [False])
    assert _walk_ns(quiz)[:15] == [1, 2, 1, 2, 5, 2, 5, 10, 5, 10, 11, 10, 11, 2, 5]


@pytest.mark.parametrize(("fallback", "again"), [(1, [7, 8, 7]), (2, [6, 7, 6]), (5, [3, 4, 3])])
def test_practice_fallback_sets_how_many_values_it_falls_back(tmp_path, fallback, again):
    quiz = _quiz(tmp_path, _times(practice_fallback=fallback))
    _enter(quiz, START)
    _play(quiz, [True] * 19 + [False])
    assert _walk_ns(quiz)[20:23] == again


def test_a_wrong_answer_reports_the_position_it_fell_back_to_and_never_the_right_answer(tmp_path):
    quiz = _quiz(tmp_path)
    _enter(quiz, START)
    now = START
    for _ in range(19):
        now += timedelta(seconds=1)
        question = _next(quiz, now)
        _reply(quiz, now, question, str(quiz.detail()["practice"][-1]["questions"][-1]["expected"]))
    question = _next(quiz, now + timedelta(seconds=1))
    assert (question["position"], question["length"]) == (19, 28)
    result = _reply(quiz, now + timedelta(seconds=2), question, WRONG)
    assert result["outcome"] == "incorrect" and result["full"] is None and (result["position"], result["length"]) == (12, 28)
    assert _next(quiz, now + timedelta(seconds=3))["question"] == "7 + 5 ="


def test_every_question_allows_the_max_timeout_however_many_are_right(tmp_path):
    quiz = _quiz(tmp_path, _times(correct_answers_required=5))
    _enter(quiz, START)
    walk = _play(quiz)
    assert {item["allowed_ms"] for item in walk["questions"]} == {10_000}


def test_the_server_judges_a_practice_answer_by_its_own_clock(tmp_path):
    quiz = _quiz(tmp_path)
    _enter(quiz, START)
    question = _next(quiz, START)
    expected = quiz.detail()["practice"][-1]["questions"][-1]["expected"]
    late = _reply(quiz, START + timedelta(seconds=11), question, str(expected))
    assert late["outcome"] == "timeout" and late["full"] is None
    question = _next(quiz, START + timedelta(seconds=12))
    right = _reply(quiz, START + timedelta(seconds=22), question, str(expected), expired=True)
    assert right["outcome"] == "correct" and right["full"] == "7 + 1 = 8" and right["sound"].startswith("/static/sounds/correct/")


def test_a_wrong_answer_plays_the_incorrect_sound(tmp_path):
    quiz = _quiz(tmp_path)
    _enter(quiz, START)
    result = _reply(quiz, START, _next(quiz, START), WRONG)
    assert result["sound"].startswith("/static/sounds/incorrect/")


# Offering practice, entering it, and leaving it


@pytest.mark.parametrize(
    ("operands", "offered"),
    [
        ([{"from": 1, "to": 5}], True),
        ([{"from": 1, "to": 4}], False),
        ([{"value": 1}, {"value": 2}, {"value": 3}, {"value": 4}], False),
        ([{"from": 1, "to": 4}, {"value": 10}], True),
    ],
)
def test_practice_is_offered_with_five_or_more_values_in_operands_and_not_fewer(tmp_path, operands, offered):
    quiz = Quiz(tmp_path, _body(first=[{"value": 7}], operands=operands))
    page = quiz.open(START).body
    assert ('id="practice-start"' in page and 'id="practice-ask"' in page) is offered
    assert ('id="practice-confirm"' in page) is offered
    status, _reply_body = quiz.post(START, "practice", {})
    assert (status == 200) is offered
    if not offered:
        assert status == 400 and "practice" not in quiz.detail() and len(quiz.detail()["runs"]) == 1


def test_entering_practice_closes_the_question_showing_and_keeps_the_attempt_going_on_a_new_run(tmp_path):
    quiz = _quiz(tmp_path, _times(correct_answers_required=3), due="2026-11-01")
    question = quiz.ask(START)
    quiz.answer(START, question["id"], str(quiz.expected()))
    quiz.ask(START + timedelta(seconds=1))
    reply = _enter(quiz, START + timedelta(seconds=2))
    assert reply == {"practice": {"m": 7, "length": 28}, "correct": 0, "required": 3}
    [attempt] = quiz.store.attempts("younger", quiz.attempt().key)
    assert attempt.outcome == "in_progress"
    assert [(item["run"], item["outcome"]) for item in attempt.detail["questions"]] == [(1, "correct"), (1, "timeout")]
    assert len(attempt.detail["runs"]) == 2 and attempt.detail["practice"][0]["run"] == 2
    assert quiz.store.passes_on("younger", START.date()) == 0
    assert "0 / 3 correct" in quiz.open(START + timedelta(minutes=1)).body


def test_practice_never_passes_the_attempt_and_scores_nothing(tmp_path):
    quiz = _quiz(tmp_path, _times(correct_answers_required=1))
    _enter(quiz, START)
    _play(quiz)
    assert quiz.attempt().outcome == "in_progress"
    assert quiz.detail()["questions"] == []
    assert quiz.store.passes_on("younger", START.date()) == 0
    question = quiz.ask(quiz.now + timedelta(seconds=1))
    result = quiz.answer(quiz.now + timedelta(seconds=2), question["id"], str(quiz.expected()))
    assert result["finished"] is True and quiz.attempt().outcome == "pass"


def test_after_the_walk_ends_the_quiz_starts_from_zero_on_the_same_attempt(tmp_path):
    quiz = _quiz(tmp_path, _times(correct_answers_required=3))
    first = quiz.ask(START)
    quiz.answer(START, first["id"], str(quiz.expected()))
    _enter(quiz, START + timedelta(seconds=1))
    _play(quiz, start=START + timedelta(seconds=1))
    status, visit = quiz.post(quiz.now + timedelta(seconds=1), "visit", {})
    assert (status, visit) == (200, {"correct": 0, "required": 3})
    asked = quiz.ask(quiz.now + timedelta(seconds=2))
    assert asked["correct"] == 0 and quiz.detail()["questions"][-1]["run"] == 2
    assert [item["run"] for item in quiz.detail()["questions"]] == [1, 2]
    assert len(quiz.store.attempts("younger", quiz.attempt().key)) == 1


def test_leaving_by_reloading_ends_the_walk_and_lands_on_the_start_screen_at_zero(tmp_path):
    quiz = _quiz(tmp_path)
    question = quiz.ask(START)
    quiz.answer(START, question["id"], str(quiz.expected()))
    _enter(quiz, START + timedelta(seconds=1))
    shown = _next(quiz, START + timedelta(seconds=2))
    page = quiz.open(START + timedelta(seconds=5))
    assert "0 / 20 correct" in page.body
    walk = quiz.detail()["practice"][-1]
    assert walk["ended"] == "left"
    assert walk["questions"][shown["id"]]["outcome"] == "timeout"
    status, payload = quiz.post(START + timedelta(seconds=6), "practice_question", {})
    assert (status, payload) == (409, {"reload": True})
    status, payload = quiz.post(
        START + timedelta(seconds=6), "practice_answer", {"id": shown["id"], "answer": "8", "expired": False}
    )
    assert (status, payload) == (409, {"reload": True})
    assert quiz.ask(START + timedelta(seconds=7))["correct"] == 0


def test_giving_up_during_a_walk_follows_the_quiz_rules(tmp_path):
    quiz = _quiz(tmp_path)
    _enter(quiz, START)
    _next(quiz, START)
    page = quiz.give_up(START + timedelta(seconds=2))
    assert page.status == 302
    gone = quiz.attempt()
    assert gone.outcome == "abandoned"
    assert gone.detail["practice"][-1]["ended"] == "left"
    assert gone.detail["practice"][-1]["questions"][-1]["outcome"] == "timeout"


def test_practice_is_allowed_on_the_only_required_task_and_giving_up_there_keeps_the_attempt(tmp_path):
    quiz = _quiz(tmp_path, due="2026-11-01")
    _enter(quiz, START)
    _next(quiz, START)
    page = quiz.give_up(START + timedelta(seconds=2))
    assert page.status == 200 and MUST_FINISH in page.body
    assert quiz.attempt().outcome == "in_progress"
    assert quiz.attempt().detail["practice"][-1]["ended"] == "left"


def test_a_second_walk_is_a_new_walk_and_the_first_stays_in_the_record(tmp_path):
    quiz = _quiz(tmp_path)
    _enter(quiz, START)
    _next(quiz, START)
    reply = _enter(quiz, START + timedelta(seconds=5))
    assert reply["practice"]["length"] == 28
    walks = quiz.detail()["practice"]
    assert [walk.get("ended") for walk in walks] == ["left", None]
    assert [walk["run"] for walk in walks] == [2, 3]
    assert walks[0]["questions"][0]["outcome"] == "timeout"


def test_practice_with_no_attempt_in_progress_asks_the_page_to_reload(tmp_path):
    quiz = _quiz(tmp_path, _times(correct_answers_required=1), cooldown=1)
    question = quiz.ask(START)
    quiz.answer(START, question["id"], str(quiz.expected()))
    for action in ("practice", "practice_question", "practice_answer"):
        status, payload = quiz.post(START + timedelta(seconds=1), action, {"id": 0, "answer": "1"})
        assert (status, payload) == (409, {"reload": True})


def test_a_practice_question_or_answer_with_no_walk_is_refused(tmp_path):
    quiz = _quiz(tmp_path)
    assert quiz.post(START, "practice_question", {}) == (409, {"reload": True})
    assert quiz.post(START, "practice_answer", {"id": 0, "answer": "8"}) == (409, {"reload": True})
    _enter(quiz, START)
    question = _next(quiz, START)
    status, payload = quiz.post(START, "practice_answer", {"id": question["id"] + 1, "answer": "8"})
    assert (status, payload) == (409, {"reload": True})
    status, payload = quiz.post(START, "practice_answer", {"id": question["id"], "answer": ""})
    assert status == 400 and "empty" in payload["error"]
    status, payload = quiz.post(START, "practice_answer", {"answer": "8"})
    assert status == 400


# Which number is practised


def _book(*rows):
    return book_of(list(rows))


def _missed(m, *ns):
    return [(m, n, "incorrect", 2000) for n in ns]


def _right(m, ns, times=5):
    return [(m, n, "correct", 2000) for _ in range(times) for n in ns]


SIX_TO_EIGHT = _values({"from": 6, "to": 8})
ONE_TO_TEN = _values({"from": 1, "to": 10})


def test_the_number_whose_facts_weigh_most_is_practised():
    asked = [*_right(6, range(1, 11)), *_right(8, range(1, 11)), *_missed(7, 1, 2, 3, 4, 5, 6), *_right(7, range(7, 11))]
    assert {choose_m(SIX_TO_EIGHT, ONE_TO_TEN, _book(*asked), random.Random(seed)) for seed in range(20)} == {7}


def test_a_never_asked_fact_weighs_one_so_an_unseen_number_beats_numbers_asked_often():
    asked = [*_right(6, range(1, 11)), *_right(8, range(1, 11))]
    assert {choose_m(SIX_TO_EIGHT, ONE_TO_TEN, _book(*asked), random.Random(seed)) for seed in range(20)} == {7}


def test_with_no_figures_every_number_ties_and_the_choice_is_random():
    rng = random.Random(3)
    counts = Counter(choose_m(SIX_TO_EIGHT, ONE_TO_TEN, NO_FIGURES, rng) for _ in range(600))
    assert set(counts) == {6, 7, 8}
    assert all(count > 140 for count in counts.values())


def test_equal_totals_tie_even_when_the_facts_are_summed_in_a_different_order():
    asked = [*_right(7, range(1, 11)), *_missed(6, 1, 2, 3), *_right(8, range(1, 8)), *_missed(8, 10, 9, 8), *_right(6, range(4, 11))]
    book = _book(*asked)
    rng = random.Random(5)
    counts = Counter(choose_m(SIX_TO_EIGHT, ONE_TO_TEN, book, rng) for _ in range(200))
    assert set(counts) == {6, 8} and min(counts.values()) > 50


def test_only_facts_with_the_tasks_own_n_values_count():
    asked = [*_missed(6, 11, 12, 13), *_missed(7, 1)]
    assert {choose_m(SIX_TO_EIGHT, ONE_TO_TEN, _book(*asked), random.Random(seed)) for seed in range(20)} == {7}


def test_a_huge_list_is_never_listed():
    huge = _values({"from": 0, "to": 10**12})
    assert 0 <= choose_m(huge, ONE_TO_TEN, NO_FIGURES, random.Random(1)) <= 10**12
    book = _book(*_missed(123_456_789, 1, 2))
    assert choose_m(huge, ONE_TO_TEN, book, random.Random(1)) == 123_456_789


def test_a_task_with_no_first_practises_a_number_from_operands():
    settings = parse_settings(_body(operands=[{"from": 1, "to": 6}], first=None))
    asked = [row for m in (1, 2, 3, 4, 6) for row in _right(m, range(1, 7))]
    assert choose_m(settings.lefts, settings.operands, _book(*asked), random.Random()) == 5


def test_through_the_page_a_task_whose_sevens_were_missed_practises_the_sevens(tmp_path):
    quiz = Quiz(tmp_path, _body(first=[{"from": 6, "to": 8}], operands=[{"from": 1, "to": 10}]))
    quiz.now = START
    for m, outcome in ((6, "correct"), (8, "correct"), (7, "incorrect")):
        asked = [(m, n, outcome) for n in range(1, 11) for _ in range(5 if outcome == "correct" else 1)]
        _plant(quiz.store, asked, operation="addition", task=SUMS, when=START - timedelta(days=3))
    quiz.open(START)
    assert _enter(quiz, START)["practice"]["m"] == 7
    assert {item["m"] for item in _next_walk(quiz)} == {7}


def _next_walk(quiz):
    _next(quiz, quiz.now + timedelta(seconds=1))
    return quiz.detail()["practice"][-1]["questions"]


def test_the_choice_counts_this_attempts_answers_including_the_question_closed_on_entering(tmp_path):
    quiz = Quiz(tmp_path, _body(first=[{"from": 6, "to": 8}], operands=[{"from": 1, "to": 10}]))
    quiz.open(START)
    shown = quiz.ask(START)
    asked = quiz.detail()["questions"][shown["id"]]
    assert _enter(quiz, START + timedelta(seconds=2))["practice"]["m"] == asked["m"]
    assert quiz.detail()["questions"][shown["id"]]["outcome"] == "timeout"


def test_the_choice_ignores_other_operations_and_other_client_groups(tmp_path):
    quiz = Quiz(tmp_path, _body(first=[{"from": 6, "to": 8}], operands=[{"from": 1, "to": 10}]))
    quiz.now = START
    for m in (6, 8):
        asked = [(m, n, "correct") for n in range(1, 11) for _ in range(5)]
        _plant(quiz.store, asked, operation="addition", task=SUMS, when=START - timedelta(days=3))
    misses = [(6, n, "incorrect") for n in range(1, 11)]
    _plant(quiz.store, misses, operation="addition", task=SUMS, client="older", when=START - timedelta(days=3))
    _plant(quiz.store, misses, operation="multiplication", task=SUMS, when=START - timedelta(days=3))
    quiz.open(START)
    assert _enter(quiz, START)["practice"]["m"] == 7


# The record: practice counts in no figure, and the attempt page lists each walk


def test_practice_answers_count_in_no_figure(tmp_path):
    quiz = _quiz(tmp_path)
    question = quiz.ask(START)
    quiz.answer(START, question["id"], str(quiz.expected()))
    before = quiz.store.facts.book("younger", "addition").facts
    asked = quiz.detail()["questions"]
    figures = attempt_report(quiz.store, str(quiz.attempt().id), now=START)["arithmetic"]["last"]["figures"]
    assert figures["questions"] == 1
    _enter(quiz, START + timedelta(seconds=1))
    _play(quiz, [True, False, True, True, False], start=START + timedelta(seconds=1))
    assert quiz.store.facts.book("younger", "addition").facts == before
    assert quiz.detail()["questions"] == asked
    report = attempt_report(quiz.store, str(quiz.attempt().id), now=START)["arithmetic"]
    assert report["last"]["figures"]["questions"] == 0 and report["last"]["questions"] == []
    assert report["expired"][0]["figures"]["questions"] == 1
    found = facts_report(quiz.store, ("younger",), "addition", now=quiz.now, pairs=[("client", "younger")])
    assert sum(fact["asked"] for fact in found["facts"]["facts"]) == 1


def test_the_attempt_page_lists_each_walk_with_its_m_and_every_question(tmp_path):
    quiz = _quiz(tmp_path, _times(correct_answers_required=3))
    _enter(quiz, START)
    _play(quiz, [True, True, False], start=START)
    _enter(quiz, quiz.now + timedelta(seconds=1))
    _next(quiz, quiz.now + timedelta(seconds=2))
    quiz.open(quiz.now + timedelta(seconds=10))
    report = attempt_report(quiz.store, str(quiz.attempt().id), now=quiz.now)["arithmetic"]
    first, second = report["practice"]
    assert (first["walk"], first["m"], first["operation"], first["ended"], first["length"]) == (1, 7, "addition", "finished", 28)
    rows = first["questions"]
    assert [row["text"] for row in rows[:4]] == ["7 + 1 = 8", "7 + 2 = 9", "7 + 1 = 8", "7 + 1 = 8"]
    assert [row["outcome"] for row in rows[:4]] == ["correct", "correct", "incorrect", "correct"]
    assert rows[2]["answer"] == WRONG and rows[0]["answer"] == "8"
    assert [row["step"] for row in rows[:4]] == ["1 of 28", "2 of 28", "3 of 28", "1 of 28"]
    assert all(row["taken_ms"] == 1000 for row in rows)
    assert (second["walk"], second["ended"], second["m"]) == (2, "left", 7)
    assert second["questions"][0]["outcome"] == "timeout" and second["questions"][0]["taken_ms"] == 10_000


def test_an_attempt_that_never_practised_lists_no_walks(tmp_path):
    quiz = _quiz(tmp_path)
    quiz.ask(START)
    assert attempt_report(quiz.store, str(quiz.attempt().id), now=START)["arithmetic"]["practice"] == []


# The practice_fallback setting


def test_practice_fallback_defaults_to_three_and_takes_a_whole_number_of_one_or_more():
    assert parse_settings(_body()).practice_fallback == 3
    assert parse_settings(_body(practice_fallback=1)).practice_fallback == 1
    assert parse_settings(_body(practice_fallback=40)).practice_fallback == 40


@pytest.mark.parametrize("value", [0, -2, 2.5, "3", True, None, [3]])
def test_any_other_practice_fallback_is_refused_naming_the_field(value):
    body = _body()
    body["practice_fallback"] = value
    with pytest.raises(ValueError, match="practice_fallback: must be a whole number, 1 or more"):
        parse_settings(body)


# The page script


def _page(tmp_path, **fields):
    return Quiz(tmp_path, _times(**fields)).open(START).body


def _question(number, n, *, position, length_=28):
    return {"id": number, "question": f"7 + {n} =", "allowed_ms": 10_000, "position": position, "length": length_}


WATCH = ["start", "ask", "question", "previous", "feedback", "progress", "timer", "answer", "practice-confirm", "practice-start",
         "practice-ask", "practice-done", "start-progress", "start-button"]


def _snaps(events):
    return {event["what"]: event["elements"] for event in events if event["kind"] == "snap"}


def _posts(events):
    return [event["what"] for event in events if event["kind"] == "post"]


@needs_node
def test_the_walk_on_screen_shows_progress_the_last_right_answer_fading_and_never_a_wrong_one(tmp_path):
    replies = {
        "visit": [{"correct": 0, "required": 20}],
        "practice": [{"practice": {"m": 7, "length": 28}, "correct": 0, "required": 20}],
        "practice_question": [_question(0, 1, position=0), _question(1, 2, position=1), _question(2, 1, position=0)],
        "practice_answer": [
            {"outcome": "correct", "full": "7 + 1 = 8", "position": 1, "length": 28, "finished": False, "sound": None},
            {"outcome": "incorrect", "full": None, "position": 0, "length": 28, "finished": False, "sound": None},
        ],
    }
    steps = [
        {"click": "practice-start"},
        {"snap": WATCH, "label": "asking to confirm"},
        {"click": "practice-yes"},
        {"snap": WATCH, "label": "first question"},
        {"type": ["answer", "8"]},
        {"key": ["answer", "Enter"]},
        {"snap": WATCH, "label": "second question"},
        {"wait": 4000},
        {"snap": WATCH, "label": "four seconds on"},
        {"type": ["answer", "5"]},
        {"key": ["answer", "Enter"]},
        {"snap": WATCH, "label": "after a miss"},
        {"wait": 1000},
        {"snap": WATCH, "label": "walk again"},
    ]
    events = run_page(_page(tmp_path), replies, steps=steps, bodies=True)
    snaps = _snaps(events)
    assert _posts(events) == ["visit", "practice", "practice_question", "practice_answer", "practice_question",
                              "practice_answer", "practice_question"]
    assert snaps["asking to confirm"]["practice-confirm"]["hidden"] is False
    first = snaps["first question"]
    assert first["practice-confirm"]["hidden"] is True and first["start"]["hidden"] is True and first["ask"]["hidden"] is False
    assert (first["question"]["text"], first["progress"]["text"], first["previous"]["text"]) == ("7 + 1 =", "Practice: 1 of 28", "")
    assert first["practice-ask"]["hidden"] is True and first["previous"]["hidden"] is False
    second = snaps["second question"]
    assert second["question"]["text"] == "7 + 2 =" and second["progress"]["text"] == "Practice: 2 of 28"
    assert second["previous"]["text"] == "7 + 1 = 8"
    assert second["previous"]["style"]["transition"] == "opacity 3000ms linear" and second["previous"]["style"]["opacity"] == "0"
    answers = [event["body"] for event in events if event["kind"] == "post" and event["what"] == "practice_answer"]
    assert answers == [{"id": 0, "answer": "8", "expired": False}, {"id": 1, "answer": "5", "expired": False}]
    missed = snaps["after a miss"]
    assert missed["feedback"]["text"] == "Not quite" and missed["question"]["text"] == "7 + 2 ="
    assert missed["progress"]["text"] == "Practice: 1 of 28" and missed["previous"]["text"] == ""
    again = snaps["walk again"]
    assert again["question"]["text"] == "7 + 1 =" and again["previous"]["text"] == "" and again["feedback"]["text"] == ""
    assert again["progress"]["text"] == "Practice: 1 of 28"


@needs_node
def test_a_timeout_in_a_walk_says_so_and_falls_back_without_showing_the_answer(tmp_path):
    replies = {
        "visit": [{"correct": 0, "required": 20}],
        "practice": [{"practice": {"m": 7, "length": 28}, "correct": 0, "required": 20}],
        "practice_question": [_question(0, 1, position=0), _question(1, 1, position=0)],
        "practice_answer": [{"outcome": "timeout", "full": None, "position": 0, "length": 28, "finished": False, "sound": None}],
    }
    steps = [
        {"click": "practice-start"},
        {"click": "practice-yes"},
        {"wait": 10_000},
        {"snap": WATCH, "label": "timed out"},
    ]
    events = run_page(_page(tmp_path), replies, steps=steps, bodies=True)
    out = _snaps(events)["timed out"]
    assert out["feedback"]["text"] == "Time ran out" and out["question"]["text"] == "7 + 1 =" and out["previous"]["text"] == ""
    assert [event["body"] for event in events if event["what"] == "practice_answer"] == [{"id": 0, "answer": "", "expired": True}]


@needs_node
def test_the_end_of_the_walk_returns_to_the_start_screen_at_zero_and_the_quiz_waits_for_start(tmp_path):
    replies = {
        "visit": [{"correct": 0, "required": 20}],
        "practice": [{"practice": {"m": 7, "length": 28}, "correct": 0, "required": 20}],
        "practice_question": [_question(0, 10, position=27)],
        "practice_answer": [{"outcome": "correct", "full": "7 + 10 = 17", "position": 27, "length": 28, "finished": True, "sound": None}],
        "question": [{"id": 0, "question": "7 + 4 =", "allowed_ms": 10_000, "correct": 0, "required": 20}],
    }
    steps = [
        {"click": "practice-start"},
        {"click": "practice-yes"},
        {"type": ["answer", "17"]},
        {"key": ["answer", "Enter"]},
        {"snap": WATCH, "label": "walk over"},
        {"wait": 6000},
        {"click": "start-button"},
        {"snap": WATCH, "label": "quiz"},
    ]
    events = run_page(_page(tmp_path), replies, steps=steps)
    over = _snaps(events)["walk over"]
    assert over["start"]["hidden"] is False and over["ask"]["hidden"] is True and over["timer"]["hidden"] is True
    assert over["start-progress"]["text"] == "0 / 20 correct" and over["start-button"]["focused"] is True
    assert over["practice-done"]["hidden"] is False and over["practice-start"]["hidden"] is False
    assert _posts(events) == ["visit", "practice", "practice_question", "practice_answer", "question"]
    quiz = _snaps(events)["quiz"]
    assert quiz["question"]["text"] == "7 + 4 =" and quiz["progress"]["text"] == "0 / 20" and quiz["previous"]["hidden"] is True


@needs_node
def test_the_confirmation_leaves_the_timer_running_and_confirming_stops_the_old_question(tmp_path):
    replies = {
        "visit": [{"correct": 0, "required": 20}],
        "question": [{"id": 0, "question": "7 + 4 =", "allowed_ms": 10_000, "correct": 0, "required": 20}],
        "practice": [{"practice": {"m": 7, "length": 28}, "correct": 0, "required": 20}],
        "practice_question": [_question(1, 1, position=0)],
    }
    steps = [
        {"click": "start-button"},
        {"click": "practice-ask"},
        {"wait": 9000},
        {"snap": WATCH, "label": "still open"},
        {"click": "practice-yes"},
        {"wait": 5000},
        {"snap": WATCH, "label": "in the walk"},
    ]
    events = run_page(_page(tmp_path), replies, steps=steps)
    assert _snaps(events)["still open"]["practice-confirm"]["hidden"] is False
    assert _snaps(events)["still open"]["question"]["text"] == "7 + 4 ="
    assert _posts(events) == ["visit", "question", "practice", "practice_question"]
    assert _snaps(events)["in the walk"]["question"]["text"] == "7 + 1 ="


@needs_node
def test_answering_no_keeps_the_question_and_enter_never_opens_the_confirmation(tmp_path):
    replies = {
        "visit": [{"correct": 0, "required": 20}],
        "question": [{"id": 0, "question": "7 + 4 =", "allowed_ms": 10_000, "correct": 0, "required": 20}],
    }
    steps = [
        {"click": "start-button"},
        {"key": ["practice-ask", "Enter"]},
        {"snap": WATCH, "label": "enter"},
        {"click": "practice-ask"},
        {"click": "practice-no"},
        {"snap": WATCH, "label": "no"},
    ]
    events = run_page(_page(tmp_path), replies, steps=steps)
    snaps = _snaps(events)
    assert snaps["enter"]["practice-confirm"]["hidden"] is True
    assert snaps["no"]["practice-confirm"]["hidden"] is True and snaps["no"]["answer"]["focused"] is True
    assert _posts(events) == ["visit", "question"]
