"""S035.2: arithmetic facts across attempts, and an arithmetic attempt's page."""

import json
import random
from datetime import datetime, timedelta

import pytest

from asgi import call, session_cookie
from policy.accounts import Accounts
from policy.arithmetic import Session as ArithmeticSession
from policy.review import attempt_report, facts_report, trend_report
from policy.store import PolicyStore
from policy.tasks import AttemptStore, Task, TaskKey

NOW = datetime(2026, 11, 17, 18, 0)
CLIENTS = ("younger", "older")
PASSWORD = "s3cret-pass"
TIMES = TaskKey("arithmetic", "times")
SUMS = TaskKey("arithmetic", "sums")
SIGNS = {"addition": "+", "subtraction": "−", "multiplication": "×", "division": "÷"}


def _settings(operation: str = "multiplication", required: int = 20) -> dict:
    return {
        "operation": operation,
        "max_timeout": "10s",
        "min_timeout": "4s",
        "correct_answers_required": required,
        "operands": [{"from": 2, "to": 9, "weight": 1}],
    }


def _ask(m: int, n: int, outcome: str | None, answer: str | None = None, ms: int = 3000, run: int = 1, operation="multiplication", issued=None):
    if operation == "multiplication":
        text, expected = f"{m} × {n} =", m * n
    elif operation == "addition":
        text, expected = f"{m} + {n} =", m + n
    elif operation == "subtraction":
        text, expected = f"{m + n} − {m} =", n
    else:
        text, expected = f"{m * n} ÷ {m} =", n
    if answer is None and outcome == "correct":
        answer = str(expected)
    question = {
        "run": run,
        "m": m,
        "n": n,
        "question": text,
        "expected": expected,
        "answer": answer,
        "outcome": outcome,
        "allowed_ms": 10_000,
        "taken_ms": ms if outcome is not None else None,
    }
    if issued is not None:
        question["issued"] = issued.isoformat(timespec="milliseconds")
    return question


def _detail(*questions, operation="multiplication", runs=None) -> dict:
    return {"settings": _settings(operation), "runs": runs or [{"run": 1}], "questions": list(questions)}


def _plant(store: AttemptStore, key: TaskKey, days_ago: float, detail: dict, outcome: str = "pass", **extra):
    started = NOW - timedelta(days=days_ago)
    return store.record("younger", key, outcome, started + timedelta(minutes=5), started_at=started, detail=detail, **extra)


def _facts(store: AttemptStore, operation: str = "multiplication", query: str = "") -> dict:
    pairs = [("client", "younger")] + [tuple(pair.split("=", 1)) for pair in query.split("&") if pair]
    return facts_report(store, CLIENTS, operation, now=NOW, pairs=pairs)


def _by_fact(report: dict) -> dict:
    return {(fact["m"], fact["n"]): fact for fact in report["facts"]["facts"]}


# The facts page


def test_each_fact_counts_its_asks_rights_wrongs_and_timeouts_across_attempts_and_tasks():
    with AttemptStore(":memory:") as store:
        _plant(store, TIMES, 3, _detail(_ask(7, 8, "correct", ms=2000), _ask(7, 8, "incorrect", "54"), _ask(8, 7, "correct", ms=4000)))
        _plant(store, TaskKey("arithmetic", "other"), 1, _detail(_ask(7, 8, "timeout", ms=10_000), _ask(7, 8, "correct", ms=3000)))
        facts = _by_fact(_facts(store))
    seven_eight = facts[(7, 8)]
    assert (seven_eight["asked"], seven_eight["right"], seven_eight["wrong"], seven_eight["timeouts"]) == (4, 2, 1, 1)
    assert (seven_eight["missed"], seven_eight["missed_percent"]) == (2, 50)
    assert seven_eight["median_ms"] == 2500
    assert (seven_eight["text"], seven_eight["cell"]) == ("7 × 8 = 56", "7 × 8")
    # 6 + 7 and 7 + 6 are two facts.
    assert facts[(8, 7)]["asked"] == 1
    assert facts[(8, 7)]["last_missed"] is None


def test_the_grid_has_a_row_for_each_left_number_and_a_column_for_each_right_number_asked():
    with AttemptStore(":memory:") as store:
        _plant(store, TIMES, 1, _detail(_ask(6, 7, "correct"), _ask(6, 9, "correct"), _ask(3, 7, "correct")))
        report = _facts(store)
    assert (report["facts"]["rows"], report["facts"]["columns"]) == ([3, 6], [7, 9])


def test_every_question_counts_in_expired_runs_and_unfinished_attempts_but_not_one_still_showing():
    with AttemptStore(":memory:") as store:
        expired = _detail(
            _ask(7, 8, "incorrect", "54", run=1),
            _ask(7, 8, "correct", run=2),
            runs=[{"run": 1, "expired": "2026-11-16T17:00:00.000"}, {"run": 2}],
        )
        _plant(store, TIMES, 1, expired)
        store.begin("younger", TIMES, NOW - timedelta(hours=2), detail=_detail(_ask(7, 8, "incorrect", "55"), _ask(7, 8, None)))
        _plant(store, TIMES, 2, _detail(_ask(7, 8, "timeout", ms=10_000)), outcome="abandoned")
        fact = _by_fact(_facts(store))[(7, 8)]
    assert (fact["asked"], fact["wrong"], fact["timeouts"]) == (4, 2, 1)


def test_the_period_and_filters_choose_the_attempts_and_parent_checks_and_other_types_are_left_out():
    with AttemptStore(":memory:") as store:
        _plant(store, TIMES, 40, _detail(_ask(2, 2, "correct")))
        _plant(store, TIMES, 10, _detail(_ask(3, 3, "correct")))
        _plant(store, TIMES, 1, _detail(_ask(4, 4, "correct")), task_set="practice")
        _plant(store, TaskKey("spelling", "week"), 1, {"questions": [{"m": 5, "n": 5, "outcome": "correct", "question": "5 × 5 ="}]})
        assert set(_by_fact(_facts(store))) == {(3, 3), (4, 4)}
        assert set(_by_fact(_facts(store, query="range=past-week"))) == {(4, 4)}
        assert set(_by_fact(_facts(store, query="set=required&set=potential"))) == {(3, 3)}
        assert _facts(store, query="outcome=failure")["facts"] is None


def test_each_question_goes_under_the_operation_its_sign_names():
    with AttemptStore(":memory:") as store:
        changed = _detail(_ask(6, 7, "correct", operation="addition"), _ask(6, 7, "correct", operation="subtraction"), operation="subtraction")
        _plant(store, SUMS, 1, changed)
        _plant(store, TIMES, 1, _detail(_ask(6, 7, "correct", operation="division")))
        assert _by_fact(_facts(store, "addition"))[(6, 7)]["text"] == "6 + 7 = 13"
        assert _by_fact(_facts(store, "subtraction"))[(6, 7)]["text"] == "13 − 6 = 7"
        assert _by_fact(_facts(store, "division"))[(6, 7)]["text"] == "42 ÷ 6 = 7"
        assert _facts(store, "multiplication")["message"] == "No multiplication questions for younger in this period."


def test_a_fact_lists_the_attempts_that_asked_it_newest_first_with_each_answer_and_the_day_last_missed():
    with AttemptStore(":memory:") as store:
        older = _plant(store, TIMES, 5, _detail(_ask(7, 8, "incorrect", "54", issued=NOW - timedelta(days=5)), _ask(7, 8, "incorrect", "54"), _ask(7, 8, "correct")))
        newer = _plant(store, TIMES, 2, _detail(_ask(7, 8, "timeout", issued=NOW - timedelta(days=2)), _ask(7, 8, "correct")))
        report = _facts(store)
    fact = _by_fact(report)[(7, 8)]
    assert fact["attempts"] == [{"id": newer.id, "answers": ["timeout", "56"]}, {"id": older.id, "answers": ["54", "54", "56"]}]
    assert (fact["last_missed"], fact["last_missed_day"]) == ("Sunday 15 November 2026", "2026-11-15")
    assert report["facts"]["attempts"][str(older.id)] == {"started": "Thursday 12 November 2026, 18:00", "task": "times"}


def test_the_facts_page_says_why_it_has_nothing_to_show():
    with AttemptStore(":memory:") as store:
        assert _facts(store, "powers")["message"] == "powers is not an arithmetic operation."
        assert facts_report(store, CLIENTS, "addition", now=NOW, pairs=[])["message"] == "Choose a client group."
        assert facts_report(store, CLIENTS, "addition", now=NOW, pairs=[("client", "cousin")])["facts"] is None
        report = _facts(store, "addition")
    assert report["message"] == "No addition questions for younger in this period."
    assert [each["name"] for each in report["operations"]] == ["addition", "subtraction", "multiplication", "division"]


def test_an_arithmetic_trend_names_its_operation_for_the_facts_link():
    with AttemptStore(":memory:") as store:
        _plant(store, TIMES, 1, _detail(_ask(6, 7, "correct")))
        assert trend_report(store, CLIENTS, TIMES, now=NOW, pairs=[("client", "younger")])["facts"] == "multiplication"
        task = Task("division", "arithmetic", ("younger",), 1, body=json.dumps(_settings("division")))
        idle = trend_report(store, CLIENTS, task.key, now=NOW, tasks=[task], pairs=[("client", "younger")])
        assert idle["facts"] == "division"
        assert trend_report(store, CLIENTS, TaskKey("spelling", "week"), now=NOW, pairs=[("client", "younger")])["facts"] is None


# The attempt page


def test_an_attempt_page_has_its_last_run_with_its_figures_and_each_expired_run_after_it():
    session = ArithmeticSession({}, _settings("addition", required=3))
    rng = random.Random(2)
    moment = NOW
    for _ in range(2):
        question = session.issue(moment, rng)
        moment += timedelta(seconds=2)
        session.answer(moment, len(session.questions) - 1, str(question["expected"] + 1), expired=False)
    moment += timedelta(hours=2)
    for kind in ("right", "wrong", "right", "reload", "right"):
        question = session.issue(moment, rng)
        if kind == "reload":
            moment += timedelta(seconds=1)
            session.visit(moment)
            continue
        moment += timedelta(seconds=3)
        answer = question["expected"] if kind == "right" else question["expected"] + 1
        session.answer(moment, len(session.questions) - 1, str(answer), expired=False)
    with AttemptStore(":memory:") as store:
        attempt = _plant(store, SUMS, 0.5, session.detail)
        page = attempt_report(store, str(attempt.id), now=NOW)
    runs = page["arithmetic"]
    last = runs["last"]
    assert (last["operation"], last["operation_label"]) == ("addition", "Addition")
    figures = last["figures"]
    assert (figures["points"], figures["pass_mark"], figures["questions"], figures["wrong"], figures["timeouts"]) == (3, 3, 5, 1, 1)
    assert [row["outcome_label"] for row in last["questions"]] == ["Right", "Wrong", "Right", "Timeout", "Right"]
    reload = last["questions"][3]
    assert (reload["answer"], reload["taken_ms"], reload["allowed_ms"]) == ("", reload["allowed_ms"], reload["allowed_ms"])
    first = last["questions"][0]
    assert first["text"].endswith(f" = {first['answer']}") and first["text"].startswith(f"{first['m']} + {first['n']}")
    assert len(runs["expired"]) == 1
    expired = runs["expired"][0]
    assert expired["expired"].startswith("Tuesday 17 November 2026, 19:00")
    assert (expired["figures"]["questions"], expired["figures"]["wrong"], expired["figures"]["points"]) == (2, 2, 0)
    # The stored record is still sent whole.
    assert page["record"]["questions"] == session.detail["questions"]


def test_an_attempt_in_progress_shows_the_question_still_waiting_and_other_types_have_no_runs():
    with AttemptStore(":memory:") as store:
        going = store.begin("younger", TIMES, NOW - timedelta(hours=2), detail=_detail(_ask(6, 7, "correct"), _ask(6, 8, None)))
        page = attempt_report(store, str(going.id), now=NOW)
        rows = page["arithmetic"]["last"]["questions"]
        assert [(row["outcome"], row["outcome_label"]) for row in rows] == [("correct", "Right"), (None, "Not answered yet")]
        assert page["arithmetic"]["last"]["figures"]["questions"] == 1
        other = store.record("younger", TaskKey("worksheet", "w"), "pass", NOW, detail={"answers": ["x"]})
        assert attempt_report(store, str(other.id), now=NOW)["arithmetic"] is None


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
        AttemptStore(connection=saved.connection).record("younger", TIMES, "pass", recent, detail=_detail(_ask(7, 8, "incorrect", "54")))
    app = create_app()
    app.state.database = database
    return app


def test_facts_are_sent_only_with_a_session(service):
    path = "/parent/api/attempts/facts/multiplication"
    status, body, _headers = call(service, "GET", path, query="client=younger")
    assert status == 401
    assert "54" not in body
    _status, _body, headers = call(service, "POST", "/parent/api/login", json_body={"username": "ada", "password": PASSWORD})
    status, body, _headers = call(service, "GET", path, query="client=younger&range=past-week&m=7&n=8", cookie=session_cookie(headers))
    assert status == 200
    fact = json.loads(body)["facts"]["facts"][0]
    assert (fact["text"], fact["attempts"][0]["answers"]) == ("7 × 8 = 56", ["54"])
