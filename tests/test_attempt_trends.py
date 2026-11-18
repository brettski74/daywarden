"""S035.1: each attempt's figures, the attempts overview over a period, and a task's trend."""

import json
import random
from datetime import datetime, timedelta

import pytest

from asgi import call, session_cookie
from policy.accounts import Accounts
from policy.arithmetic import Session as ArithmeticSession
from policy.attempt_figures import figures
from policy.review import attempts_report, trend_report
from policy.store import PolicyStore
from policy.tasks import AttemptStore, Task, TaskKey

NOW = datetime(2026, 11, 17, 18, 0)
CLIENTS = ("younger", "older")
PASSWORD = "s3cret-pass"
SUMS = TaskKey("arithmetic", "sums")
WORDS = TaskKey("spelling", "week-3")
SENTENCES = TaskKey("parts_of_speech", "nouns")
COUNTING = TaskKey("skip_counting", "by-fives")
OPERANDS = [{"from": 2, "to": 9, "weight": 1}]


def _arithmetic_body(required: int) -> dict:
    return {
        "operation": "addition",
        "max_timeout": "10s",
        "min_timeout": "4s",
        "correct_answers_required": required,
        "operands": OPERANDS,
    }


def _sum(outcome: str, ms: int, run: int = 1, allowed: int = 10_000) -> dict:
    return {"run": run, "outcome": outcome, "taken_ms": ms, "allowed_ms": allowed}


def _arithmetic(right: int, wrong: int = 0, timeouts: int = 0, required: int = 20) -> dict:
    questions = [_sum("correct", 3000)] * right + [_sum("incorrect", 3000)] * wrong + [_sum("timeout", 10_000)] * timeouts
    return {"settings": _arithmetic_body(required), "runs": [{"run": 1}], "questions": questions}


def _plant(store: AttemptStore, key: TaskKey, days_ago: float, outcome: str = "pass", detail: dict | None = None, **extra):
    started = NOW - timedelta(days=days_ago)
    return store.record("younger", key, outcome, started + timedelta(minutes=5), started_at=started, detail=detail or {}, **extra)


def _report(store: AttemptStore, query: str = "", tasks=()) -> dict:
    pairs = [("client", "younger")] + [tuple(pair.split("=", 1)) for pair in query.split("&") if pair]
    return attempts_report(store, CLIENTS, "younger", now=NOW, tasks=tasks, pairs=pairs)


def _trend(store: AttemptStore, key: TaskKey, query: str = "") -> dict:
    pairs = [("client", "younger")] + [tuple(pair.split("=", 1)) for pair in query.split("&") if pair]
    return trend_report(store, CLIENTS, key, now=NOW, pairs=pairs)


# Figures


def test_arithmetic_counts_right_wrong_and_timeouts_from_the_quiz_record():
    session = ArithmeticSession({}, _arithmetic_body(20))
    rng = random.Random(4)
    moment = NOW
    for kind in ["right"] * 20 + ["wrong"] * 3 + ["late"] + ["reload"]:
        question = session.issue(moment, rng)
        number = len(session.questions) - 1
        if kind == "reload":
            moment += timedelta(seconds=2)
            session.visit(moment)
            continue
        moment += timedelta(seconds=30 if kind == "late" else 2)
        answer = question["expected"] if kind == "right" else question["expected"] + 1
        session.answer(moment, number, str(answer), expired=False)
    found = figures("arithmetic", session.detail)
    assert (found.points, found.pass_mark, found.questions, found.wrong, found.timeouts, found.maximum) == (20, 20, 25, 3, 2, None)
    assert found.average_ms == 2000


def test_only_the_last_run_counts_and_its_pass_mark_is_the_one_it_started_with():
    session = ArithmeticSession({}, _arithmetic_body(10))
    rng = random.Random(1)
    moment = NOW
    for _ in range(12):
        question = session.issue(moment, rng)
        moment += timedelta(seconds=2)
        session.answer(moment, len(session.questions) - 1, str(question["expected"] + 1), expired=False)
    # An hour and more with nothing done expires the run. The next one starts with the settings in force then.
    session.body = _arithmetic_body(20)
    moment += timedelta(hours=2)
    for kind in ["right"] * 20 + ["wrong"] * 2:
        question = session.issue(moment, rng)
        moment += timedelta(seconds=2)
        answer = question["expected"] if kind == "right" else question["expected"] + 1
        session.answer(moment, len(session.questions) - 1, str(answer), expired=False)
    assert len(session.detail["runs"]) == 2
    found = figures("arithmetic", session.detail)
    assert (found.questions, found.points, found.pass_mark, found.wrong) == (22, 20, 20, 2)


def test_time_answering_adds_the_time_allowed_for_a_timeout_and_averages_only_the_right_answers():
    detail = {
        "settings": _arithmetic_body(2),
        "runs": [{"run": 1}],
        "questions": [_sum("correct", 2500), _sum("correct", 3500), _sum("timeout", 9000, allowed=4000)],
    }
    found = figures("arithmetic", detail)
    assert (found.time_ms, found.average_ms) == (10_000, 3000)


def _sentence(outcome: str, points: float, *received: int, run: int = 1) -> dict:
    return {
        "run": run,
        "outcome": outcome,
        "points": points,
        "allowed_ms": 30_000,
        "tries": [{"received_ms": ms} for ms in received],
    }


def test_parts_of_speech_points_come_from_the_tries_and_the_maximum_is_always_there():
    detail = {
        "settings": {"correct_answers_required": 7, "minimum_questions": 7, "maximum_questions": 10, "sentences": []},
        "runs": [{"run": 1}],
        "questions": [_sentence("correct", 1, 4000)] * 5
        + [_sentence("correct", 0.5, 4000, 6000), _sentence("correct", 0.25, 1000, 2000, 3000)]
        + [_sentence("incorrect", 0, 1000, 2000, 3000), _sentence("timeout", 0, 1000)]
        + [{"run": 1, "outcome": None, "points": None, "tries": []}],
    }
    found = figures("parts_of_speech", detail)
    assert (found.points, found.pass_mark, found.maximum) == (5.75, 7, 10)
    assert (found.questions, found.wrong, found.timeouts) == (9, 1, 1)
    # The second-try sentence is neither wrong nor a timeout, and its time is to its last try.
    assert found.time_ms == 5 * 4000 + 6000 + 3000 + 3000 + 30_000


def test_capitalisation_figures_and_trend_are_points_with_a_maximum():
    detail = {
        "settings": {"correct_answers_required": 2, "minimum_questions": 2, "maximum_questions": 4, "sentences": []},
        "runs": [{"run": 1}],
        "questions": [_sentence("correct", 1, 4000), _sentence("correct", 0.25, 1000, 2000, 3000), _sentence("incorrect", 0, 1000, 2000, 3000), _sentence("timeout", 0, 1000)],
    }
    found = figures("capitalisation", detail)
    assert (found.points, found.pass_mark, found.maximum, found.questions, found.wrong, found.timeouts) == (1.25, 2, 4, 4, 1, 1)
    key = TaskKey("capitalisation", "caps")
    with AttemptStore(":memory:") as store:
        _plant(store, key, 1, detail=detail)
        shown = _trend(store, key)["trend"]
        assert shown["kind"] == "points" and shown["has_maximum"] is True


def test_skip_counting_has_a_maximum_only_when_one_is_set_and_works_out_an_omitted_pass_mark():
    question = {"run": 1, "outcome": "correct", "points": 1, "allowed_ms": 180_000, "tries": [{"received_ms": 9000}]}
    detail = {"settings": {"correct_answers_required": 6}, "runs": [{"run": 1}], "questions": [question]}
    found = figures("skip_counting", detail)
    assert (found.points, found.pass_mark, found.maximum) == (1, 6, None)
    capped = figures("skip_counting", {**detail, "settings": {"maximum_questions": 8}})
    assert capped.maximum == 8
    assert capped.pass_mark is not None and capped.pass_mark <= 8


def _word(pool: str, outcome: str, run: int, ms: int | None = 4000) -> dict:
    return {"run": run, "pool": pool, "outcome": outcome, "allowed_ms": 12_000, "received_ms": None if outcome == "timeout" else ms}


def test_spelling_has_current_and_revision_points_from_the_run_after_practice():
    detail = {
        "settings": {"timeout": "10s"},
        "runs": [
            {"run": 1, "current_required": 8, "revision_required": 4},
            {"run": 2, "current_required": 8, "revision_required": 4, "practice": []},
        ],
        "questions": [_word("current", "correct", 1)] * 5
        + [_word("current", "correct", 2)] * 8
        + [_word("revision", "correct", 2)] * 3
        + [_word("revision", "incorrect", 2), _word("revision", "timeout", 2)],
    }
    found = figures("spelling", detail)
    assert (found.current_points, found.current_required, found.revision_points, found.revision_required) == (8, 8, 3, 4)
    assert (found.points, found.pass_mark, found.questions, found.wrong, found.timeouts) == (11, 12, 13, 1, 1)
    assert found.time_ms == 12 * 4000 + 12_000


def test_a_type_without_figures_has_none():
    assert figures("worksheet", {"answers": []}) is None
    assert figures("parent_check", {"recorded_by": "parent"}) is None
    assert figures("arithmetic", {"answers": []}) is None


# The overview and the list


def test_the_period_decides_what_is_listed_and_counted():
    with AttemptStore(":memory:") as store:
        _plant(store, SUMS, 10, detail=_arithmetic(20))
        _plant(store, SUMS, 2, detail=_arithmetic(20))
        month = _report(store)
        assert month["view"]["range"] == "past-month"
        assert [row["attempts"] for row in month["overview"]] == [2]
        assert len(month["attempts"]) == 2
        week = _report(store, "range=past-week")
        assert [row["attempts"] for row in week["overview"]] == [1]
        assert len(week["attempts"]) == 1


def test_the_overview_counts_outcomes_and_works_out_accuracy():
    with AttemptStore(":memory:") as store:
        for days, wrong in ((5, 1), (4, 5), (3, 30)):
            _plant(store, SUMS, days, detail=_arithmetic(20, wrong=wrong))
        _plant(store, SUMS, 2, "abandoned", detail=_arithmetic(0))
        store.begin("younger", SUMS, NOW - timedelta(days=1), detail=_arithmetic(0))
        row = _report(store)["overview"][0]
        assert (row["label"], row["attempts"], row["passes"], row["failures"], row["abandoned"], row["unfinished"]) == (
            "arithmetic/sums",
            5,
            3,
            0,
            1,
            1,
        )
        # 60 points in 96 questions.
        assert row["accuracy"] == 63
        assert row["spark"][:3] == [{"points": 20, "pass_mark": 20}] * 3
        assert row["spark_label"] == "5 attempts, latest 0 of 20"


def test_rows_are_ordered_by_type_then_name_and_one_gone_from_the_policy_is_marked():
    with AttemptStore(":memory:") as store:
        _plant(store, WORDS, 1)
        _plant(store, TaskKey("arithmetic", "times"), 1)
        _plant(store, SUMS, 1)
        rows = _report(store, tasks=(Task("sums", "arithmetic", ("younger",), 0),))["overview"]
        assert [row["label"] for row in rows] == ["arithmetic/sums", "arithmetic/times", "spelling/week-3"]
        assert [row["in_policy"] for row in rows] == [True, False, False]


def test_a_renamed_task_is_one_row_under_its_new_name():
    with AttemptStore(":memory:") as store:
        _plant(store, SUMS, 3)
        store.rename(SUMS, TaskKey("arithmetic", "adding"))
        _plant(store, TaskKey("arithmetic", "adding"), 1)
        rows = _report(store)["overview"]
        assert [(row["label"], row["attempts"]) for row in rows] == [("arithmetic/adding", 2)]


def test_filters_leave_out_practice_and_outcomes_but_parent_checks_stay_in_the_list():
    with AttemptStore(":memory:") as store:
        _plant(store, SUMS, 3, detail=_arithmetic(20))
        _plant(store, SUMS, 2, "failure", detail=_arithmetic(5), task_set="practice")
        _plant(store, TaskKey("parent_check", "check"), 1, task_set="parent_check")
        everything = _report(store)
        assert [row["attempts"] for row in everything["overview"]] == [2]
        assert len(everything["attempts"]) == 3
        no_practice = _report(store, "set=required&set=potential")
        assert [row["attempts"] for row in no_practice["overview"]] == [1]
        assert [row["task"] for row in no_practice["attempts"]] == ["check", "sums"]
        failures = _report(store, "outcome=failure")
        assert [row["failures"] for row in failures["overview"]] == [1]
        nothing = _report(store, "set=none")
        assert nothing["view"]["set"] == []
        assert nothing["overview"] == []
        assert [row["task"] for row in nothing["attempts"]] == ["check"]


def test_a_period_that_is_not_real_days_shows_the_summary_and_says_why():
    with AttemptStore(":memory:") as store:
        _plant(store, SUMS, 1)
        report = _report(store, "range=custom&from=2026-11-10&to=2026-11-01")
        assert report["summary"] is not None
        assert (report["overview"], report["attempts"]) == (None, None)
        assert "To is before From." in report["notes"]
        custom = _report(store, "range=custom&from=2026-11-15&to=2026-11-16")
        assert len(custom["attempts"]) == 1
        assert custom["days"] == {"from": "2026-11-15", "to": "2026-11-16"}


# The trend


def test_a_trend_has_each_attempt_oldest_first_at_its_start_with_its_figures():
    with AttemptStore(":memory:") as store:
        first = _plant(store, SUMS, 20, detail=_arithmetic(20, required=10))
        second = _plant(store, SUMS, 5, "abandoned", detail=_arithmetic(4))
        _plant(store, WORDS, 4)
        report = _trend(store, SUMS)
        trend = report["trend"]
        assert report["task"] == {"type": "arithmetic", "name": "sums", "label": "arithmetic/sums", "in_policy": False}
        assert [point["id"] for point in trend["points"]] == [first.id, second.id]
        assert [point["figures"]["pass_mark"] for point in trend["points"]] == [10, 20]
        assert trend["points"][1]["outcome_label"] == "Abandoned"
        assert trend["kind"] == "points" and trend["has_maximum"] is False
        assert trend["points"][0]["at"] < trend["points"][1]["at"] <= trend["length"]
        assert trend["ticks"]
        assert [row["id"] for row in trend["attempts"]] == [second.id, first.id]


def test_a_practice_attempt_is_marked_and_the_filters_apply_to_the_trend():
    with AttemptStore(":memory:") as store:
        _plant(store, SUMS, 3, detail=_arithmetic(20))
        _plant(store, SUMS, 2, detail=_arithmetic(20), task_set="practice")
        assert [point["practice"] for point in _trend(store, SUMS)["trend"]["points"]] == [False, True]
        assert len(_trend(store, SUMS, "set=required")["trend"]["points"]) == 1


def test_a_trend_with_nothing_to_show_says_so():
    with AttemptStore(":memory:") as store:
        _plant(store, SUMS, 40)
        assert _trend(store, SUMS)["message"] == "No attempts at arithmetic/sums for younger in this period."
        missing = _trend(store, TaskKey("arithmetic", "nothing"))
        assert (missing["message"], missing["trend"]) == ("No attempts at arithmetic/nothing for younger in this period.", None)


def test_a_spelling_trend_is_spelling_and_a_parts_of_speech_trend_has_a_maximum():
    with AttemptStore(":memory:") as store:
        _plant(store, WORDS, 1, detail={"runs": [{"run": 1, "current_required": 2, "revision_required": 1}], "questions": []})
        _plant(
            store,
            SENTENCES,
            1,
            detail={"settings": {"correct_answers_required": 7, "maximum_questions": 10}, "runs": [{"run": 1}], "questions": []},
        )
        assert _trend(store, WORDS)["trend"]["kind"] == "spelling"
        assert _trend(store, SENTENCES)["trend"]["has_maximum"] is True


# The endpoint


@pytest.fixture
def service(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    database = tmp_path / "policy.sqlite3"
    monkeypatch.setenv("POLICY_FILE", str(tmp_path / "missing.yaml"))
    monkeypatch.setenv("POLICY_DB", str(database))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    recent = datetime.now() - timedelta(hours=1)
    with PolicyStore(database) as saved:
        Accounts(saved.connection).set_password("ada", PASSWORD)
        AttemptStore(connection=saved.connection).record("younger", SUMS, "pass", recent, detail=_arithmetic(20))
    app = create_app()
    app.state.database = database
    return app


def test_a_trend_is_sent_only_with_a_session(service):
    path = "/parent/api/attempts/tasks/arithmetic/sums"
    status, body, _headers = call(service, "GET", path, query="client=younger")
    assert status == 401
    assert "sums" not in body
    _status, _body, headers = call(service, "POST", "/parent/api/login", json_body={"username": "ada", "password": PASSWORD})
    status, body, _headers = call(service, "GET", path, query="client=younger&range=past-week", cookie=session_cookie(headers))
    assert status == 200
    trend = json.loads(body)["trend"]
    assert trend["points"][0]["figures"]["points"] == 20
