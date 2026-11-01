"""S003.3: a parent reviews attempts and records a parent check."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from policy.accounts import Accounts
from policy.review import respond_attempt, respond_attempts, respond_parent_check
from policy.store import PolicyStore
from policy.tasks import PARENT_CHECK, AttemptStore, Task

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
        "private-task",
        "failure",
        datetime(2026, 10, 31, 18, 0),
        started_at=datetime(2026, 10, 31, 17, 30),
        detail={"answers": ["platypus"]},
    )
    store.begin("younger", "open-task", datetime(2026, 10, 31, 17, 0))
    store.record(
        "younger",
        "later",
        "pass",
        datetime(2026, 10, 31, 16, 12, 30),
        started_at=datetime(2026, 10, 31, 16, 0),
        detail={"answers": ["wombat", "kangaroo"], "result": "pass"},
    )
    store.record(
        "younger",
        "middle",
        "failure",
        datetime(2026, 10, 31, 15, 5),
        started_at=datetime(2026, 10, 31, 15, 0),
        detail={"answers": [{"prompt": "2 + 2", "answer": "5", "correct": False}]},
    )
    store.record(
        "younger",
        "early",
        "abandoned",
        datetime(2026, 10, 31, 14, 10, 45),
        started_at=datetime(2026, 10, 31, 14, 10),
        detail={"answers": []},
    )


def test_a_pass_a_failure_and_an_abandonment_show_outcome_and_local_times():
    with PolicyStore(":memory:") as saved:
        accounts = _accounts(saved)
        store = AttemptStore(connection=saved.connection)
        _plant(store)
        key = accounts.login("ada", PASSWORD, NOW)
        page = respond_attempts(
            accounts,
            method="GET",
            query={"client": "younger"},
            cookie=key,
            form={},
            now=NOW,
            attempts=store,
            clients=CLIENTS,
        )
        body = page.body
        assert page.status == 200
        assert body.index("open-task") < body.index("later") < body.index("middle") < body.index("early")
        assert "private-task" not in body
        assert "platypus" not in body
        assert ">in_progress<" in body
        assert ">pass<" in body
        assert ">failure<" in body
        assert ">abandoned<" in body
        assert "Saturday 31 October 2026, 17:00" in body
        assert "Saturday 31 October 2026, 16:00" in body
        assert "Saturday 31 October 2026, 16:12:30" in body
        assert "Saturday 31 October 2026, 15:00" in body
        assert "Saturday 31 October 2026, 15:05" in body
        assert "Saturday 31 October 2026, 14:10" in body
        assert "Saturday 31 October 2026, 14:10:45" in body
        assert "still going" in body
        assert "12m 30s" in body
        assert "5m" in body
        assert "45s" in body


def test_an_attempt_shows_each_answer_and_a_parent_check_shows_its_record():
    with PolicyStore(":memory:") as saved:
        accounts = _accounts(saved)
        store = AttemptStore(connection=saved.connection)
        _plant(store)
        key = accounts.login("ada", PASSWORD, NOW)
        passed = next(row for row in store.recent("younger") if row.task == "later")
        page = respond_attempt(
            accounts,
            attempt_id=str(passed.id),
            method="GET",
            query={},
            cookie=key,
            form={},
            now=NOW,
            attempts=store,
        )
        assert page.status == 200
        assert ">pass<" in page.body
        assert page.body.index("wombat") < page.body.index("kangaroo")
        failed = next(row for row in store.recent("younger") if row.task == "middle")
        detail = respond_attempt(
            accounts,
            attempt_id=str(failed.id),
            method="GET",
            query={},
            cookie=key,
            form={},
            now=NOW,
            attempts=store,
        )
        assert ">failure<" in detail.body
        assert "2 + 2" in detail.body
        assert ">5<" in detail.body
        assert ">false<" in detail.body
        recorded = respond_parent_check(
            accounts,
            cookie=key,
            form={"client": "younger"},
            now=NOW,
            tasks=(CREDIT,),
            attempts=store,
            clients=CLIENTS,
        )
        assert ">pass<" in recorded.body
        assert "credit" in recorded.body
        credit = next(row for row in store.recent("younger") if row.task == "credit")
        opened = respond_attempt(
            accounts,
            attempt_id=str(credit.id),
            method="GET",
            query={},
            cookie=key,
            form={},
            now=NOW,
            attempts=store,
        )
        assert "recorded_by" in opened.body
        assert "parent" in opened.body
        assert store.passes_on("younger", NOW.date()) == 2


def test_a_missing_idle_or_expired_session_shows_the_form_and_no_attempts():
    with PolicyStore(":memory:") as saved:
        bare = Accounts(saved.connection)
        store = AttemptStore(connection=saved.connection)
        _plant(store)
        closed = respond_attempts(
            bare, method="GET", query={"client": "younger"}, cookie=None, form={}, now=NOW, attempts=store
        )
        assert closed.status == 403
        assert "No attempts" not in closed.body
        assert "wombat" not in closed.body
        assert "later" not in closed.body

        accounts = _accounts(saved)
        missing = respond_attempt(
            accounts,
            attempt_id="1",
            method="GET",
            query={},
            cookie=None,
            form={},
            now=NOW,
            attempts=store,
        )
        assert "Enter your username and password." in missing.body
        assert "wombat" not in missing.body
        assert "later" not in missing.body
        listed = respond_attempts(
            accounts,
            method="GET",
            query={"client": "younger"},
            cookie=None,
            form={},
            now=NOW,
            attempts=store,
            clients=CLIENTS,
        )
        assert "Enter your username and password." in listed.body
        assert "wombat" not in listed.body
        assert "later" not in listed.body

        idle = accounts.login("ada", PASSWORD, NOW)
        expired_at = NOW + timedelta(minutes=15, seconds=1)
        idle_page = respond_attempts(
            accounts,
            method="GET",
            query={"client": "younger"},
            cookie=idle,
            form={},
            now=expired_at,
            attempts=store,
            clients=CLIENTS,
        )
        assert "Enter your username and password." in idle_page.body
        assert "later" not in idle_page.body
        assert "wombat" not in idle_page.body
        assert accounts.accept(idle, NOW + timedelta(minutes=15)) is None

        kept = accounts.login("ada", PASSWORD, NOW)
        still = respond_attempt(
            accounts,
            attempt_id=str(next(row.id for row in store.recent("younger") if row.task == "later")),
            method="GET",
            query={},
            cookie=kept,
            form={},
            now=NOW + timedelta(minutes=15),
            attempts=store,
        )
        assert "wombat" in still.body

        lifetime = accounts.login("ada", PASSWORD, NOW)
        for minute in range(0, 181, 10):
            page = respond_attempts(
                accounts,
                method="GET",
                query={"client": "younger"},
                cookie=lifetime,
                form={},
                now=NOW + timedelta(minutes=minute),
                attempts=store,
                clients=CLIENTS,
            )
            assert "later" in page.body
        ended = respond_attempt(
            accounts,
            attempt_id="1",
            method="GET",
            query={},
            cookie=lifetime,
            form={},
            now=NOW + timedelta(minutes=180, seconds=1),
            attempts=store,
        )
        assert "Enter your username and password." in ended.body
        assert "wombat" not in ended.body
        assert "later" not in ended.body
        assert "platypus" not in ended.body


def test_a_parent_records_a_parent_check_and_a_stranger_group_does_not():
    with PolicyStore(":memory:") as saved:
        accounts = _accounts(saved)
        store = AttemptStore(connection=saved.connection)
        key = accounts.login("ada", PASSWORD, NOW)
        unsigned = respond_parent_check(
            accounts,
            cookie=None,
            form={"client": "younger"},
            now=NOW,
            tasks=(CREDIT,),
            attempts=store,
            clients=CLIENTS,
        )
        assert "Enter your username and password." in unsigned.body
        assert store.attempts("younger") == ()
        stranger = respond_parent_check(
            accounts,
            cookie=key,
            form={"client": "stranger"},
            now=NOW,
            tasks=(CREDIT,),
            attempts=store,
            clients=CLIENTS,
        )
        assert "That client group is not in the household." in stranger.body
        assert store.attempts("younger") == ()
        recorded = respond_parent_check(
            accounts,
            cookie=key,
            form={"client": "younger"},
            now=NOW,
            tasks=(CREDIT,),
            attempts=store,
            clients=CLIENTS,
        )
        assert "credit" in recorded.body
        assert ">pass<" in recorded.body
        assert "Saturday 31 October 2026, 12:00" in recorded.body
        assert store.passes_on("younger", NOW.date()) == 1
        assert [row.outcome for row in store.attempts("younger")] == ["pass"]


def test_plain_http_does_not_show_an_attempt(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    database = tmp_path / "policy.sqlite3"
    monkeypatch.setenv("POLICY_FILE", str(tmp_path / "missing.yaml"))
    monkeypatch.setenv("POLICY_DB", str(database))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    monkeypatch.setenv("DECISION_FILE", str(tmp_path / "decision.json"))
    with PolicyStore(database) as saved:
        accounts = Accounts(saved.connection)
        accounts.set_password("ada", PASSWORD)
        AttemptStore(connection=saved.connection).record(
            "younger",
            "later",
            "pass",
            NOW,
            detail={"answers": ["wombat"]},
        )
        key = accounts.login("ada", PASSWORD, datetime.now(timezone.utc))
    app = create_app()

    status, body, headers = _call(app, "GET", "/attempts/1")
    assert status == 403
    assert "Open this page over HTTPS." in body
    assert "wombat" not in body
    assert "set-cookie" not in headers

    status, body, _headers = _call(
        app,
        "GET",
        "/attempts/1",
        cookie=f"parent_session={key}",
        scheme="https",
    )
    assert status == 200
    assert "wombat" in body
    status, body, _headers = _call(app, "GET", "/attempts", query=b"client=younger", scheme="https")
    assert "Enter your username and password." in body
    assert "wombat" not in body
    assert "later" not in body


def _call(app, method, path, *, body=b"", cookie=None, scheme="http", query=b""):
    messages = []
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    headers = []
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": scheme,
        "path": path,
        "raw_path": path.encode(),
        "query_string": query,
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8443),
        "root_path": "",
    }
    asyncio.run(app(scope, receive, send))
    start = next(item for item in messages if item["type"] == "http.response.start")
    payload = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
    found: dict[str, list[str]] = {}
    for name, value in start["headers"]:
        found.setdefault(name.decode(), []).append(value.decode())
    return start["status"], payload.decode(), found
