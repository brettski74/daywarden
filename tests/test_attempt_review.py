"""S003.3 and S007.4: a parent reviews attempts and records a parent check."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from asgi import call, session_cookie
from policy.accounts import Accounts
from policy.review import attempt_report, attempts_report, record_parent_check
from policy.store import PolicyStore
from policy.tasks import PARENT_CHECK, AttemptStore, Task, TaskKey

PASSWORD = "s3cret-pass"
NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
CLIENTS = ("younger", "older")
CREDIT = Task("credit", PARENT_CHECK, ("younger",), 0)


def _accounts(store: PolicyStore, **limits) -> Accounts:
    accounts = Accounts(store.connection, **limits)
    accounts.set_password("ada", PASSWORD)
    return accounts


def _plant(store: AttemptStore) -> None:
    store.record(
        "older",
        TaskKey("worksheet", "private-task"),
        "failure",
        datetime(2026, 10, 31, 18, 0),
        started_at=datetime(2026, 10, 31, 17, 30),
        detail={"answers": ["platypus"]},
    )
    store.begin("younger", TaskKey("worksheet", "open-task"), datetime(2026, 10, 31, 17, 0))
    store.record(
        "younger",
        TaskKey("arithmetic", "later"),
        "pass",
        datetime(2026, 10, 31, 16, 12, 30),
        started_at=datetime(2026, 10, 31, 16, 0),
        detail={"answers": ["wombat", "kangaroo"], "result": "pass"},
    )
    store.record(
        "younger",
        TaskKey("worksheet", "middle"),
        "failure",
        datetime(2026, 10, 31, 15, 5),
        started_at=datetime(2026, 10, 31, 15, 0),
        detail={"answers": [{"prompt": "2 + 2", "answer": "5", "correct": False}]},
    )
    store.record(
        "younger",
        TaskKey("worksheet", "early"),
        "abandoned",
        datetime(2026, 10, 31, 14, 10, 45),
        started_at=datetime(2026, 10, 31, 14, 10),
        detail={"answers": []},
    )


def _row(report: dict, task: str) -> dict:
    return next(row for row in report["attempts"] if row["task"] == task)


def test_a_pass_a_failure_and_an_abandonment_show_outcome_and_local_times():
    with AttemptStore(":memory:") as store:
        _plant(store)
        report = attempts_report(store, CLIENTS, "younger", now=NOW, timezone="Australia/Sydney")
        assert report["client"] == "younger"
        assert report["clients"] == ["younger", "older"]
        assert report["times"] == "Times are Australia/Sydney."
        assert [row["task"] for row in report["attempts"]] == ["open-task", "later", "middle", "early"]
        assert "private-task" not in json.dumps(report)
        assert "platypus" not in json.dumps(report)
        assert _row(report, "open-task") | {"id": 0} == {
            "id": 0,
            "task": "open-task",
            "type": "worksheet",
            "set": "Required",
            "started": "Saturday 31 October 2026, 17:00",
            "finished": "still going",
            "outcome": "in_progress",
            "duration": "still going",
        }
        later = _row(report, "later")
        assert later["type"] == "arithmetic"
        assert (later["started"], later["finished"], later["outcome"], later["duration"]) == (
            "Saturday 31 October 2026, 16:00",
            "Saturday 31 October 2026, 16:12:30",
            "pass",
            "12m 30s",
        )
        middle = _row(report, "middle")
        assert (middle["finished"], middle["outcome"], middle["duration"]) == (
            "Saturday 31 October 2026, 15:05",
            "failure",
            "5m",
        )
        early = _row(report, "early")
        assert (early["started"], early["finished"], early["outcome"], early["duration"]) == (
            "Saturday 31 October 2026, 14:10",
            "Saturday 31 October 2026, 14:10:45",
            "abandoned",
            "45s",
        )
        assert [item["label"] for item in report["summary"]] == [
            "Today's score",
            "Required tasks outstanding",
            "Potential tasks available",
            "Potential passes waiting on required tasks",
        ]


def test_no_group_or_a_stranger_group_lists_nothing():
    with AttemptStore(":memory:") as store:
        _plant(store)
        waiting = attempts_report(store, CLIENTS, "", now=NOW)
        assert (waiting["message"], waiting["summary"], waiting["attempts"]) == ("Choose a client group.", None, None)
        assert waiting["times"] == "Times are the timezone of this machine."
        stranger = attempts_report(store, CLIENTS, "stranger", now=NOW)
        assert stranger["message"] == "That client group is not in the household."
        assert stranger["attempts"] is None
        quiet = attempts_report(AttemptStore(":memory:"), CLIENTS, "older", now=NOW)
        assert quiet["attempts"] == []


def test_an_attempt_shows_each_answer_and_a_parent_check_shows_its_record():
    with PolicyStore(":memory:") as saved:
        accounts = _accounts(saved)
        store = AttemptStore(connection=saved.connection)
        _plant(store)
        passed = next(row for row in store.recent("younger") if row.task == "later")
        page = attempt_report(store, str(passed.id), now=NOW)
        assert (page["task"], page["type"]) == ("later", "arithmetic")
        assert {"label": "Type", "value": "arithmetic"} in page["summary"]
        assert page["client"] == "younger"
        assert {"label": "Outcome", "value": "pass"} in page["summary"]
        assert page["answers"] == ["wombat", "kangaroo"]
        assert page["record"] == {"result": "pass"}
        failed = next(row for row in store.recent("younger") if row.task == "middle")
        detail = attempt_report(store, str(failed.id), now=NOW)
        assert {"label": "Outcome", "value": "failure"} in detail["summary"]
        assert detail["answers"] == [{"prompt": "2 + 2", "answer": "5", "correct": False}]
        assert detail["record"] is None
        abandoned = next(row for row in store.recent("younger") if row.task == "early")
        assert attempt_report(store, str(abandoned.id), now=NOW)["answers"] == []

        assert record_parent_check(accounts, store, "younger", now=NOW, tasks=(CREDIT,), clients=CLIENTS) is None
        credit = next(row for row in store.recent("younger") if row.task == "credit")
        opened = attempt_report(store, str(credit.id), now=NOW)
        assert opened["record"] == {"recorded_by": "parent"}
        assert {"label": "Set", "value": "Parent check"} in opened["summary"]
        assert {"label": "Type", "value": "parent_check"} in opened["summary"]
        assert store.passes_on("younger", NOW.date()) == 2


def test_an_attempt_number_that_is_not_stored_is_none():
    with AttemptStore(":memory:") as store:
        _plant(store)
        for asked in ("999999", "0", "-1", "01", "abc", ""):
            assert attempt_report(store, asked, now=NOW) is None


def test_a_parent_records_a_parent_check_and_a_stranger_group_does_not():
    with PolicyStore(":memory:") as saved:
        accounts = _accounts(saved)
        store = AttemptStore(connection=saved.connection)
        assert record_parent_check(accounts, store, "stranger", now=NOW, tasks=(CREDIT,), clients=CLIENTS) == (
            "That client group is not in the household."
        )
        assert record_parent_check(accounts, store, "  ", now=NOW, clients=CLIENTS) == "Choose a client group."
        assert record_parent_check(accounts, store, None, now=NOW, clients=CLIENTS) == "Choose a client group."
        assert store.attempts("younger") == ()
        assert record_parent_check(accounts, store, "younger", now=NOW, tasks=(CREDIT,), clients=CLIENTS) is None
        report = attempts_report(store, CLIENTS, "younger", now=NOW, tasks=(CREDIT,))
        top = report["attempts"][0]
        assert (top["task"], top["type"], top["set"], top["outcome"], top["started"]) == (
            "credit",
            "parent_check",
            "Parent check",
            "pass",
            "Saturday 31 October 2026, 12:00",
        )
        assert store.passes_on("younger", NOW.date()) == 1
        assert [row.outcome for row in store.attempts("younger")] == ["pass"]
        assert accounts.parent_checks()[0][0] == "younger"
        assert record_parent_check(accounts, store, "older", now=NOW, tasks=(CREDIT,), clients=CLIENTS) is None
        assert store.attempts("older")[0].key == TaskKey("parent_check", "parent_check")


@pytest.fixture
def service(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    database = tmp_path / "policy.sqlite3"
    monkeypatch.setenv("POLICY_FILE", str(tmp_path / "missing.yaml"))
    monkeypatch.setenv("POLICY_DB", str(database))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    monkeypatch.setenv("PARENT_IDLE", "1m")
    with PolicyStore(database) as saved:
        Accounts(saved.connection).set_password("ada", PASSWORD)
        AttemptStore(connection=saved.connection).record("younger", TaskKey("worksheet", "later"), "pass", NOW, detail={"answers": ["wombat"]})
    app = create_app()
    app.state.database = database
    return app


def test_an_attempt_is_shown_only_over_https_with_a_session(service):
    status, body, headers = call(service, "GET", "/parent/api/attempts/1", scheme="http")
    assert status == 403
    assert "wombat" not in body
    assert "set-cookie" not in headers
    status, body, _headers = call(service, "GET", "/parent/api/attempts/1")
    assert status == 401
    assert "wombat" not in body

    _status, _body, headers = call(service, "POST", "/parent/api/login", json_body={"username": "ada", "password": PASSWORD})
    cookie = session_cookie(headers)
    status, body, _headers = call(service, "GET", "/parent/api/attempts/1", cookie=cookie)
    assert status == 200
    assert json.loads(body)["answers"] == ["wombat"]
    status, body, _headers = call(service, "GET", "/parent/api/attempts", query="client=younger", cookie=cookie)
    assert [row["task"] for row in json.loads(body)["attempts"]] == ["later"]


def test_an_idle_session_shows_no_attempts_and_cannot_be_used_again(service):
    import sqlite3

    _status, _body, headers = call(service, "POST", "/parent/api/login", json_body={"username": "ada", "password": PASSWORD})
    cookie = session_cookie(headers)
    idle = (datetime.now(timezone.utc) - timedelta(minutes=1, seconds=5)).replace(microsecond=0).isoformat()
    with sqlite3.connect(service.state.database) as connection:
        connection.execute("UPDATE parent_sessions SET last_seen_at = ?", (idle,))
    status, body, _headers = call(service, "GET", "/parent/api/attempts", query="client=younger", cookie=cookie)
    assert status == 401
    assert "wombat" not in body and "later" not in body
    status, _body, _headers = call(service, "GET", "/parent/api/attempts/1", cookie=cookie)
    assert status == 401
