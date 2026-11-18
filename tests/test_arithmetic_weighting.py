"""S037: historical arithmetic weighting. The fact ledger, the all-time figures, the weights, and the draws."""

import random
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_arithmetic import START, Quiz, _body  # noqa: E402

from policy import arithmetic_page  # noqa: E402
from policy.arithmetic import draw, parse_settings  # noqa: E402
from policy.fact_figures import ALPHA, Book, Figures, book_of  # noqa: E402
from policy.review import facts_report  # noqa: E402
from policy.tasks import AttemptStore, TaskKey  # noqa: E402

YOUNGER = "younger"
TIMES = TaskKey("arithmetic", "times")
SUMS = TaskKey("arithmetic", "sums")
NOW = datetime(2026, 11, 17, 18, 0)
TEXT = {"addition": "{m} + {n} =", "multiplication": "{m} × {n} ="}
ANSWER = {"addition": lambda m, n: m + n, "multiplication": lambda m, n: m * n}


def _question(m, n, outcome, ms=2000, operation="multiplication", run=1):
    expected = ANSWER[operation](m, n)
    return {
        "run": run,
        "m": m,
        "n": n,
        "question": TEXT[operation].format(m=m, n=n),
        "expected": expected,
        "answer": None if outcome in (None, "timeout") else str(expected if outcome == "correct" else expected + 1),
        "outcome": outcome,
        "allowed_ms": 10_000,
        "taken_ms": None if outcome is None else ms,
    }


def _detail(asked, operation="multiplication", settings_operation=None, runs=None):
    questions = [_question(*each, operation=operation) if isinstance(each, tuple) else each for each in asked]
    settings = {"operation": settings_operation or operation, "max_timeout": "10s", "min_timeout": "4s",
                "correct_answers_required": 20, "operands": [{"from": 0, "to": 12}]}
    return {"settings": settings, "runs": runs or [{"run": 1}], "questions": questions}


def _plant(store, asked, *, when=NOW, client=YOUNGER, task=TIMES, outcome="pass", **detail):
    return store.record(client, task, outcome, when + timedelta(minutes=5), started_at=when, detail=_detail(asked, **detail))


def _figures(store, m, n, operation="multiplication", client=YOUNGER) -> Figures:
    return store.facts.book(client, operation).figures(m, n)


# What is counted


def test_every_question_with_an_outcome_counts_once_in_every_kind_of_attempt():
    with AttemptStore() as store:
        runs = [{"run": 1, "expired": "2026-11-17T19:00:00"}, {"run": 2}]
        expired = [_question(7, 8, "incorrect", run=1), _question(7, 8, "correct", run=2)]
        _plant(store, expired, runs=runs)
        _plant(store, [(7, 8, "timeout")], when=NOW + timedelta(days=1), outcome="abandoned")
        open_one = store.begin(YOUNGER, SUMS, NOW + timedelta(days=2), detail=_detail([(7, 8, "correct"), (7, 8, None)]))
        assert _figures(store, 7, 8).asked == 3
        # Saving the attempt again, now with the question answered, counts only that question.
        store.save(open_one.id, _detail([(7, 8, "correct"), (7, 8, "correct")]))
        store.save(open_one.id, _detail([(7, 8, "correct"), (7, 8, "correct")]))
        assert _figures(store, 7, 8) == Figures(asked=5, right=3, run=2, smoothed_ms=2000, timed=3)


def test_giving_up_and_coming_back_to_the_attempt_counts_each_question_once():
    with AttemptStore() as store:
        attempt = store.begin(YOUNGER, TIMES, NOW, detail=_detail([(7, 8, "incorrect")]))
        store.finish(attempt.id, "abandoned", NOW + timedelta(minutes=1), detail=attempt.detail)
        back = store.open(YOUNGER, TIMES, NOW + timedelta(minutes=2), task_set="required", reopen_within=timedelta(hours=1))
        assert back.id == attempt.id
        store.save(back.id, _detail([(7, 8, "incorrect"), (7, 8, "correct")]))
        assert _figures(store, 7, 8) == Figures(asked=2, right=1, run=1, smoothed_ms=2000, timed=1)


def test_the_run_counts_right_answers_back_from_the_latest_and_a_miss_or_timeout_sets_it_to_zero():
    with AttemptStore() as store:
        _plant(store, [(7, 8, "correct"), (7, 8, "timeout"), (7, 8, "correct"), (7, 8, "correct")])
        assert (_figures(store, 7, 8).asked, _figures(store, 7, 8).run) == (4, 2)
        _plant(store, [(7, 8, "incorrect")], when=NOW + timedelta(days=1))
        assert (_figures(store, 7, 8).asked, _figures(store, 7, 8).run) == (5, 0)


def test_the_smoothed_time_moves_a_share_of_the_way_to_each_right_answer_and_ignores_misses():
    # The first right answer sets it, and misses leave it as it is.
    found = book_of([(7, 8, "correct", 8000), (7, 8, "incorrect", 500), (7, 8, "timeout", 10_000)]).figures(7, 8)
    assert found.smoothed_ms == 8000
    found = book_of([(7, 8, "correct", 8000), (7, 8, "correct", 2000)]).figures(7, 8)
    assert found.smoothed_ms == pytest.approx(8000 * (2000 / 8000) ** ALPHA)
    # After three fast answers a slow history has about a third of its pull left, on a ratio scale.
    found = book_of([(7, 8, "correct", 8000)] + [(7, 8, "correct", 2000)] * 3).figures(7, 8)
    assert found.smoothed_ms == pytest.approx(2000 * 4 ** (1 / 2.718281828), rel=1e-6)
    # One distracted answer does not swamp several quick ones.
    found = book_of([(7, 8, "correct", 2000)] * 4 + [(7, 8, "correct", 15_000)]).figures(7, 8)
    assert 3500 < found.smoothed_ms < 4000


def test_each_client_group_has_its_own_figures_and_each_operation_its_own_facts():
    with AttemptStore() as store:
        _plant(store, [(7, 8, "incorrect")], client="older")
        _plant(store, [(7, 8, "correct")])
        _plant(store, [(7, 8, "correct")], operation="addition", task=SUMS)
        assert _figures(store, 7, 8, client="older").run == 0
        assert _figures(store, 7, 8).run == 1
        assert _figures(store, 7, 8, "addition").asked == 1
        assert _figures(store, 7, 8).asked == 1


def test_a_question_goes_under_the_operation_its_sign_names_whatever_the_settings_say():
    with AttemptStore() as store:
        _plant(store, [(6, 7, "incorrect")], operation="multiplication", settings_operation="addition", task=SUMS)
        assert _figures(store, 6, 7).asked == 1
        assert _figures(store, 6, 7, "addition").asked == 0


def test_removing_attempts_leaves_the_figures_as_they_are():
    with AttemptStore() as store:
        planted = _plant(store, [(7, 8, "incorrect"), (6, 7, "correct")])
        before = store.facts.book(YOUNGER, "multiplication")
        store.remove([planted.id])
        assert store.facts.book(YOUNGER, "multiplication") == before


def test_the_first_start_builds_the_figures_from_stored_attempts_in_start_order_and_only_once(tmp_path):
    path = tmp_path / "policy.sqlite3"
    with AttemptStore(path) as store:
        # Stored out of start order, as when an older attempt has the higher id.
        _plant(store, [(7, 8, "correct", 3000)], when=NOW + timedelta(days=1))
        _plant(store, [(7, 8, "incorrect"), (7, 8, "correct", 9000)], when=NOW)
    with sqlite3.connect(path) as raw:
        for table in ("arithmetic_fact_questions", "arithmetic_fact_meta"):
            raw.execute(f"DROP TABLE {table}")
    expected = Figures(asked=3, right=2, run=2, smoothed_ms=pytest.approx(9000 * (3000 / 9000) ** ALPHA), timed=2)
    for _ in range(2):
        with AttemptStore(path) as store:
            assert _figures(store, 7, 8) == expected


# Weights


def _timed(m, n, ms, count=3):
    return [(m, n, "correct", ms)] * count


# Ten facts with three right answers each at 2 s set the median to 2 s.
MEDIAN_2S = [row for n in range(10) for row in _timed(2, n, 2000)]
TABLE = [
    ("never missed, quick", _timed(7, 1, 2000, 10), 0.091, 0, 0, 0.091),
    ("missed on its last answer", _timed(7, 2, 2000, 9) + [(7, 2, "incorrect", 2000)], 0.091, 4, 0, 4.091),
    ("missed, then right twice", _timed(7, 3, 2000, 8)[:7] + [(7, 3, "incorrect", 2000)] + _timed(7, 3, 2000, 2), 0.091, 1, 0, 1.091),
    ("missed, then right 5 times", _timed(7, 4, 2000, 4) + [(7, 4, "incorrect", 2000)] + _timed(7, 4, 2000, 5), 0.091, 0, 0, 0.091),
    ("never missed, slow", _timed(7, 5, 6000, 10), 0.091, 0, 2, 2.091),
    ("never missed, very slow", _timed(7, 6, 9000, 10), 0.091, 0, 4, 4.091),
    ("never missed, below the start", _timed(7, 7, 3900, 10), 0.091, 0, 0, 0.091),
]


def test_the_facts_page_weights_match_the_formulas_and_the_table():
    with AttemptStore() as store:
        rows = MEDIAN_2S + [row for _name, history, *_ in TABLE for row in history]
        _plant(store, [(m, n, outcome, ms) for m, n, outcome, ms in rows])
        report = facts_report(store, (YOUNGER,), "multiplication", now=NOW + timedelta(hours=1), pairs=[("client", YOUNGER)])
        shown = {(fact["m"], fact["n"]): fact["all_time"] for fact in report["facts"]["facts"]}
        for n, (name, history, base, miss, slow, weight) in enumerate(TABLE, start=1):
            found = shown[(7, n)]
            assert found["asked"] == len(history) == 10, name
            assert (round(1 / (found["asked"] + 1), 3), found["miss_boost"], found["slow_boost"], found["weight"]) == (
                base, miss, slow, weight,
            ), name
        assert report["slow"]["text"] == "Median 2.0 s. Slow from 4.0 s, full at 8.0 s."
        assert store.facts.book(YOUNGER, "multiplication").all_time(9, 9) == {
            "asked": 0, "run": 0, "smoothed_ms": None, "miss_boost": 0, "slow_boost": 0, "weight": 1,
        }


def test_a_missed_fact_keeps_its_miss_boost_until_it_is_right_five_times_or_on_every_answer():
    assert book_of([(7, 8, "incorrect", 0)]).figures(7, 8).miss_boost == 4
    one_right = book_of([(7, 8, "incorrect", 0), (7, 8, "correct", 2000)]).figures(7, 8)
    assert (one_right.asked, one_right.run, one_right.miss_boost) == (2, 1, 2)
    # Asked twice and right on both: never missed, so no boost.
    assert book_of(_timed(7, 8, 2000, 2)).figures(7, 8).miss_boost == 0


def test_the_slow_boost_waits_for_ten_timed_facts_and_for_three_right_answers_of_its_own():
    # Eight quick facts and one very slow one: nine timed facts, so no fact is slow yet.
    nine = [row for n in range(8) for row in _timed(2, n, 2000)] + _timed(7, 8, 9000)
    figures = book_of(nine)
    assert figures.slow.median_ms is None
    assert figures.slow.boost(figures.figures(7, 8)) == 0
    assert figures.slow.text == "Slow boost starts once 10 facts each have 3 right answers. 9 have so far."
    # A tenth timed fact starts it.
    figures = book_of(nine + _timed(2, 9, 2000))
    assert figures.slow.text == "Median 2.0 s. Slow from 4.0 s, full at 8.0 s."
    assert figures.slow.boost(figures.figures(7, 8)) == 4
    # A fact with only two right answers has no slow boost, however slow.
    figures = book_of(MEDIAN_2S + _timed(7, 8, 9000, 2))
    assert figures.slow.median_ms == 2000
    assert figures.slow.boost(figures.figures(7, 8)) == 0


def test_the_slow_boost_starts_at_least_two_seconds_past_the_median():
    figures = book_of([row for n in range(10) for row in _timed(2, n, 800)] + _timed(7, 8, 3600, 10))
    assert figures.slow.text == "Median 0.8 s. Slow from 2.8 s, full at 4.4 s."
    assert figures.slow.boost(figures.figures(7, 8)) == pytest.approx(2)


# Choosing questions


def _times_table(**fields):
    return parse_settings(_body(operation="multiplication", first=[{"value": 7}], operands=[{"from": 0, "to": 12}], **fields))


def _attempts(settings, rows, count, questions=20, answer=lambda fact: ("correct", 2000), seed=5):
    """Draw ``count`` attempts in turn, each with the figures of the attempts before it, and add its answers."""
    rng = random.Random(seed)
    asked_in = []
    for _ in range(count):
        figures = book_of(rows)
        asked: list[tuple[int, int]] = []
        for _ in range(questions):
            asked.append(draw(settings, asked[-3:], rng, figures))
        rows.extend((*fact, *answer(fact)) for fact in asked)
        asked_in.append(asked)
    return asked_in


def _share(settings, figures, fact, attempts=600, questions=20, seed=11):
    """The share of questions that ask ``fact`` over many attempts drawn with the same figures."""
    rng = random.Random(seed)
    hits = 0
    for _ in range(attempts):
        asked: list[tuple[int, int]] = []
        for _ in range(questions):
            asked.append(draw(settings, asked[-3:], rng, figures))
        hits += asked.count(fact)
    return hits / (attempts * questions)


def test_with_no_misses_every_fact_is_asked_about_equally_and_a_fact_added_later_catches_up():
    settings = parse_settings(_body(operation="multiplication", first=[{"value": 7}], operands=[{"from": 1, "to": 10}]))
    rows: list = []
    _attempts(settings, rows, 60, questions=10)
    counts = Counter((m, n) for m, n, *_ in rows)
    # Drawing at random alone would spread 600 questions over about 23 between the most and least asked.
    assert len(counts) == 10 and max(counts.values()) - min(counts.values()) <= 15
    wider = parse_settings(_body(operation="multiplication", first=[{"value": 7}], operands=[{"from": 1, "to": 12}]))
    new, old = ((7, 11), (7, 12)), [(7, n) for n in range(1, 11)]

    def behind() -> float:
        counts = Counter((m, n) for m, n, *_ in rows)
        return sum(counts[fact] for fact in old) / len(old) - sum(counts[fact] for fact in new) / len(new)

    gaps = [behind()]
    for block in range(4):
        asked = Counter(fact for each in _attempts(wider, rows, 15, questions=10, seed=6 + block) for fact in each)
        # While they are behind, the new facts are asked more than the old ones, and the gap closes.
        assert sum(asked[fact] for fact in new) / len(new) > sum(asked[fact] for fact in old) / len(old), asked
        gaps.append(behind())
    assert gaps == sorted(gaps, reverse=True) and gaps[-1] < 0.6 * gaps[0], gaps


def test_a_missed_fact_comes_up_about_one_question_in_six_until_he_has_it_right_five_times():
    settings = _times_table()
    rows = [row for n in range(13) for row in _timed(7, n, 2000, 10)] + [(7, 8, "incorrect", 2000)]
    figures = book_of(rows)
    # Its weight gives it 0.29 of the draws, but it is never asked within three questions of itself.
    rng = random.Random(1)
    assert sum(draw(settings, [], rng, figures) == (7, 8) for _ in range(20_000)) / 20_000 == pytest.approx(0.29, abs=0.01)
    assert _share(settings, figures, (7, 8)) == pytest.approx(0.18, abs=0.02)
    rows += _timed(7, 8, 2000, 5)
    figures = book_of(rows)
    assert figures.weight(figures.figures(7, 8)) == pytest.approx(1 / 17)
    # Its boost is gone. Asked more than the others now, it comes up a little less until they catch up.
    assert 0.04 < _share(settings, figures, (7, 8)) < 1 / 13


def test_a_slow_fact_comes_up_more_until_its_smoothed_time_falls_under_the_start():
    settings = _times_table()
    rows = [row for n in range(13) for row in _timed(7, n, 2000, 5) if n != 8] + _timed(7, 8, 7000, 5)
    figures = book_of(rows)
    assert figures.slow.boost(figures.figures(7, 8)) > 2
    assert _share(settings, figures, (7, 8)) > 2 / 13
    # Four answers in 3 seconds bring a 7 second history under the 4 second start.
    rows += _timed(7, 8, 3000, 4)
    figures = book_of(rows)
    assert figures.figures(7, 8).smoothed_ms < 4000
    assert figures.slow.boost(figures.figures(7, 8)) == 0
    assert _share(settings, figures, (7, 8)) < 1 / 13


def test_in_a_domain_larger_than_twenty_a_boosted_fact_takes_about_a_sixth_of_the_draws():
    settings = parse_settings(_body(operation="multiplication", operands=[{"from": 0, "to": 9}]))
    figures = book_of([(3, 4, "incorrect", 2000)])
    rng = random.Random(2)
    pairs = [draw(settings, [], rng, figures) for _ in range(40_000)]
    unit = (99 + 0.5) / 20
    assert pairs.count((3, 4)) / len(pairs) == pytest.approx((0.5 + 4 * unit) / (99 + 0.5 + 4 * unit), abs=0.01)
    assert abs(pairs.count((3, 4)) / len(pairs) - 1 / 6) < 0.02


def test_a_huge_domain_is_drawn_without_listing_it_and_only_its_unasked_facts_are_drawn_as_new():
    settings = parse_settings(_body(operation="addition", operands=[{"from": 0, "to": 10_000_000}]))
    rng = random.Random(3)
    figures = book_of([(5, 5, "incorrect", 2000), (2, 2, "correct", 2000)])
    pairs = [draw(settings, [], rng, figures) for _ in range(600)]
    # The missed fact takes about a sixth of the draws, and the rest are spread over ten million squared facts.
    others = [pair for pair in pairs if pair != (5, 5)]
    assert 60 < 600 - len(others) < 140
    assert len(set(others)) == len(others)
    # In a small domain where every fact but one has been asked, a draw of a new fact finds it.
    small = parse_settings(_body(operation="addition", first=[{"value": 1}], operands=[{"from": 0, "to": 3}]))
    figures = book_of([row for n in range(3) for row in _timed(1, n, 2000, 30)])
    assert Counter(draw(small, [], rng, figures) for _ in range(500)).most_common(1)[0][0] == (1, 3)


def test_the_last_three_questions_are_still_left_out_while_another_is_possible():
    settings = _times_table()
    figures = book_of([(7, 8, "incorrect", 2000)] * 3)
    rng = random.Random(4)
    asked: list[tuple[int, int]] = []
    for _ in range(300):
        asked.append(draw(settings, asked[-3:], rng, figures))
    for index, fact in enumerate(asked):
        assert fact not in asked[max(0, index - 3) : index]
    one = parse_settings(_body(first=[{"value": 3}], operands=[{"value": 4}]))
    assert [draw(one, [(3, 4)] * 3, rng, figures) for _ in range(3)] == [(3, 4)] * 3


# Through the quiz page


def _run_quiz(tmp_path, monkeypatch, answer_right: bool, plant=()):
    quiz = Quiz(tmp_path, _body(operation="multiplication", first=[{"value": 7}], operands=[{"from": 0, "to": 12}]))
    for asked in plant:
        _plant(quiz.store, asked, when=datetime(2026, 11, 1, 16, 0), task=TaskKey("arithmetic", "older"))
    monkeypatch.setattr(arithmetic_page, "_RNG", random.Random(21))
    now = START
    quiz.open(now)
    asked = []
    for _ in range(12):
        question = quiz.ask(now)
        asked.append(question["question"])
        expected = quiz.expected()
        quiz.answer(now + timedelta(seconds=2), question["id"], str(expected if answer_right else expected + 1))
        now += timedelta(seconds=5)
    return quiz, asked


def test_an_attempts_own_answers_never_change_its_own_draws(tmp_path, monkeypatch):
    earlier = [[(7, n, "correct") for n in range(13)] * 2 + [(7, 3, "incorrect"), (7, 11, "incorrect")]]
    right, asked_right = _run_quiz(tmp_path / "right", monkeypatch, True, earlier)
    wrong, asked_wrong = _run_quiz(tmp_path / "wrong", monkeypatch, False, earlier)
    assert asked_right == asked_wrong
    # The figures count the answers straight away, but the attempt's draws leave them out.
    attempt = wrong.attempt()
    missed = wrong.detail()["questions"][0]
    all_time = wrong.store.facts.book(YOUNGER, "multiplication").figures(missed["m"], missed["n"])
    for_draws = wrong.store.draw_figures(attempt)("multiplication").figures(missed["m"], missed["n"])
    assert all_time.run == 0 and all_time.asked > for_draws.asked
    assert for_draws == right.store.draw_figures(right.attempt())("multiplication").figures(missed["m"], missed["n"])
    report = facts_report(wrong.store, (YOUNGER,), "multiplication", now=START + timedelta(minutes=2), pairs=[("client", YOUNGER)])
    shown = {(fact["m"], fact["n"]): fact["all_time"] for fact in report["facts"]["facts"]}
    assert shown[(missed["m"], missed["n"])]["miss_boost"] == 4


# The facts page and its MCP tool


def test_the_all_time_figures_come_from_his_whole_record_whatever_the_period():
    with AttemptStore() as store:
        _plant(store, [(7, 8, "incorrect")], when=NOW - timedelta(days=60))
        _plant(store, [(7, 8, "correct"), (6, 7, "correct")], when=NOW - timedelta(days=2))
        report = facts_report(store, (YOUNGER,), "multiplication", now=NOW, pairs=[("client", YOUNGER), ("range", "past-week")])
        fact = next(each for each in report["facts"]["facts"] if (each["m"], each["n"]) == (7, 8))
        assert fact["asked"] == 1
        assert fact["all_time"] == {"asked": 2, "run": 1, "smoothed_ms": 2000, "miss_boost": 2, "slow_boost": 0, "weight": 2.333}
        assert report["slow"]["text"] == "Slow boost starts once 10 facts each have 3 right answers. 0 have so far."
        # With nothing asked in the period the median line is still there.
        report = facts_report(store, (YOUNGER,), "multiplication", now=NOW + timedelta(days=30), pairs=[("client", YOUNGER), ("range", "past-week")])
        assert report["facts"] is None and report["slow"]["timed_facts"] == 0
