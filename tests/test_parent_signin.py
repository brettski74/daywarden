"""S007.1: parent accounts, sessions, and the pages they guard."""

import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy import accounts as accounts_module  # noqa: E402
from policy.accounts import Accounts, _DUMMY, session_limits  # noqa: E402
from policy.observations import status_for  # noqa: E402
from policy.report import respond  # noqa: E402
from policy.review import respond_attempts, respond_parent_check  # noqa: E402
from policy.store import PolicyStore  # noqa: E402

PASSWORD = "s3cret-pass"
NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
HOUSE = """
[household]
timezone = "Australia/Sydney"

[[clients]]
name = "Younger child"
address = "192.0.2.40"

[[groups]]
name = "Entertainment"
priority = 30
patterns = ["*.youtube.com"]
"""


def _accounts(store: PolicyStore, **limits) -> Accounts:
    accounts = Accounts(store.connection, **limits)
    accounts.set_password("ada", PASSWORD)
    return accounts


def _usage(store: PolicyStore, accounts: Accounts, method: str, **kwargs):
    return respond(
        store,
        accounts,
        method=method,
        query=kwargs.get("query", {}),
        cookie=kwargs.get("cookie"),
        form=kwargs.get("form", {}),
        now=kwargs.get("now", NOW),
    )


def test_a_missing_limit_uses_the_default_and_a_bad_one_stops_startup():
    assert session_limits({}) == (timedelta(minutes=15), timedelta(minutes=180))
    idle, lifetime = session_limits({"PARENT_IDLE": "1m", "PARENT_LIFETIME": "5m"})
    assert (idle, lifetime) == (timedelta(minutes=1), timedelta(minutes=5))
    with pytest.raises(SystemExit):
        session_limits({"PARENT_IDLE": "0s"})
    with pytest.raises(SystemExit):
        session_limits({"PARENT_LIFETIME": "nope"})
    with pytest.raises(SystemExit):
        session_limits({"PARENT_IDLE": "-1m"})


def test_the_password_is_an_argon2id_hash_and_the_session_stores_the_key_hash(tmp_path):
    database = tmp_path / "policy.sqlite3"
    policy = tmp_path / "policy.toml"
    policy.write_text(HOUSE, encoding="utf-8")
    before = policy.read_bytes()
    with PolicyStore(database) as store:
        accounts = Accounts(store.connection)
        accounts.set_password("ada", PASSWORD)
        accounts.set_password("ada", PASSWORD)
        hashes = [
            row[0]
            for row in store.connection.execute("SELECT password_hash FROM parent_accounts")
        ]
        assert len(hashes) == 1
        assert hashes[0].startswith("$argon2id$")
        assert "m=19456,t=2,p=1" in hashes[0]
        again = accounts_module._HASHER.hash(PASSWORD)
        assert again != hashes[0]
        key = accounts.login("ada", PASSWORD, NOW)
        assert key is not None
        (stored,) = store.connection.execute("SELECT key_hash FROM parent_sessions").fetchone()
        assert stored == hashlib.sha256(bytes.fromhex(key)).hexdigest()
        assert key not in stored
    raw = database.read_bytes()
    assert PASSWORD.encode() not in raw
    assert key.encode() not in raw
    assert policy.read_bytes() == before


def test_an_unknown_username_still_runs_a_password_check(monkeypatch):
    seen = []
    real = accounts_module._HASHER

    class Spy:
        def verify(self, stored, password):
            seen.append(stored)
            return real.verify(stored, password)

    with PolicyStore(":memory:") as store:
        accounts = _accounts(store)
        monkeypatch.setattr(accounts_module, "_HASHER", Spy())
        assert accounts.login("nobody", PASSWORD, NOW) is None
        assert accounts.login("ada", "wrong-password", NOW) is None
    assert seen[0] == _DUMMY
    assert seen[1] != _DUMMY
    assert seen[1].startswith("$argon2id$")


def test_unknown_username_and_wrong_password_look_the_same():
    with PolicyStore(":memory:") as store:
        from policy import config

        config.apply(config.parse(HOUSE), store, loaded_at=None)
        accounts = _accounts(store)
        unknown = _usage(
            store,
            accounts,
            "POST",
            query={"client": "Younger child"},
            form={"username": "nobody", "password": PASSWORD},
        )
        wrong = _usage(
            store,
            accounts,
            "POST",
            query={"client": "Younger child"},
            form={"username": "ada", "password": "wrong-password"},
        )
        assert unknown.status == wrong.status == 401
        assert unknown.body == wrong.body
        assert "That username or password is not right." in unknown.body
        assert "Younger child" not in unknown.body
        assert "set-cookie" not in dict(unknown.headers)
        assert "set-cookie" not in dict(wrong.headers)


def test_the_right_password_sets_a_secure_cookie_and_the_next_page_opens():
    with PolicyStore(":memory:") as store:
        accounts = _accounts(store)
        opened = _usage(
            store, accounts, "POST", form={"username": "ada", "password": PASSWORD}
        )
        assert opened.status == 303
        header = dict(opened.headers)["set-cookie"]
        assert header.startswith("parent_session=")
        assert "Secure" in header
        assert "HttpOnly" in header
        token = header.split(";", 1)[0].split("=", 1)[1]
        page = _usage(store, accounts, "GET", cookie=token)
        assert page.status == 200
        assert "Enter your username and password." not in page.body


def test_a_query_string_password_and_an_old_gate_cookie_do_not_sign_in():
    with PolicyStore(":memory:") as store:
        accounts = _accounts(store)
        from_query = _usage(
            store,
            accounts,
            "GET",
            query={"username": "ada", "password": PASSWORD},
        )
        assert from_query.status == 200
        assert "Enter your username and password." in from_query.body
        assert "set-cookie" not in dict(from_query.headers)
        old = hmac.new(PASSWORD.encode(), b"daywarden-parent", hashlib.sha256).hexdigest()
        forged = _usage(store, accounts, "GET", cookie=old)
        assert "Enter your username and password." in forged.body
        assert "set-cookie" not in dict(forged.headers)


def test_a_second_sign_in_leaves_the_older_key_valid():
    with PolicyStore(":memory:") as store:
        accounts = _accounts(store)
        first = accounts.login("ada", PASSWORD, NOW)
        second = accounts.login("ada", PASSWORD, NOW + timedelta(minutes=1))
        assert first is not None and second is not None and first != second
        assert accounts.accept(first, NOW + timedelta(minutes=2)) == "ada"
        assert accounts.accept(second, NOW + timedelta(minutes=2)) == "ada"


def test_replacing_the_password_ends_that_accounts_sessions():
    with PolicyStore(":memory:") as store:
        accounts = _accounts(store)
        other = Accounts(store.connection)
        other.set_password("bee", "other-password")
        kept = other.login("bee", "other-password", NOW)
        ended = accounts.login("ada", PASSWORD, NOW)
        accounts.set_password("ada", "a-new-password")
        assert accounts.accept(ended, NOW + timedelta(minutes=1)) is None
        assert accounts.login("ada", PASSWORD, NOW) is None
        assert accounts.login("ada", "a-new-password", NOW) is not None
        assert other.accept(kept, NOW + timedelta(minutes=1)) == "bee"


def test_the_idle_limit_is_inclusive_to_the_second_and_does_not_refresh_when_it_fails():
    with PolicyStore(":memory:") as store:
        accounts = _accounts(store)
        key = accounts.login("ada", PASSWORD, NOW)
        assert accounts.accept(key, NOW + timedelta(minutes=15)) == "ada"
        signed_in, last_seen = store.connection.execute(
            "SELECT signed_in_at, last_seen_at FROM parent_sessions WHERE key_hash = ?",
            (hashlib.sha256(bytes.fromhex(key)).hexdigest(),),
        ).fetchone()
        assert signed_in == NOW.isoformat()
        assert last_seen == (NOW + timedelta(minutes=15)).isoformat()

        late = accounts.login("ada", PASSWORD, NOW)
        expired = NOW + timedelta(minutes=15, seconds=1)
        assert accounts.accept(late, expired) is None
        digest = hashlib.sha256(bytes.fromhex(late)).hexdigest()
        assert (
            store.connection.execute(
                "SELECT COUNT(*) FROM parent_sessions WHERE key_hash = ?",
                (digest,),
            ).fetchone()[0]
            == 0
        )
        assert accounts.accept(late, NOW + timedelta(minutes=15)) is None
        assert accounts.accept(late, expired + timedelta(seconds=1)) is None


def test_the_lifetime_ends_the_session_even_when_it_was_not_idle():
    with PolicyStore(":memory:") as store:
        accounts = _accounts(store)
        key = accounts.login("ada", PASSWORD, NOW)
        for minute in range(0, 181, 10):
            assert accounts.accept(key, NOW + timedelta(minutes=minute)) == "ada"
        assert accounts.accept(key, NOW + timedelta(minutes=180, seconds=1)) is None
        assert accounts.accept(key, NOW + timedelta(minutes=180)) is None


def test_configured_shorter_limits_are_the_ones_that_expire_the_session():
    idle, lifetime = session_limits({"PARENT_IDLE": "1m", "PARENT_LIFETIME": "5m"})
    with PolicyStore(":memory:") as store:
        accounts = Accounts(store.connection, idle=idle, lifetime=lifetime)
        accounts.set_password("ada", PASSWORD)
        key = accounts.login("ada", PASSWORD, NOW)
        assert accounts.accept(key, NOW + timedelta(minutes=1)) == "ada"
        late = accounts.login("ada", PASSWORD, NOW)
        assert accounts.accept(late, NOW + timedelta(minutes=1, seconds=1)) is None

        fresh = accounts.login("ada", PASSWORD, NOW)
        for second in range(0, 301, 30):
            assert accounts.accept(fresh, NOW + timedelta(seconds=second)) == "ada"
        assert accounts.accept(fresh, NOW + timedelta(minutes=5)) == "ada"
        assert accounts.accept(fresh, NOW + timedelta(minutes=5, seconds=1)) is None


def test_a_parent_check_without_a_session_does_not_record_a_pass():
    with PolicyStore(":memory:") as store:
        accounts = _accounts(store)
        accounts.record_parent_check("younger", NOW)
        missing = respond_parent_check(
            accounts, cookie=None, form={"client": "older"}, now=NOW
        )
        assert "Enter your username and password." in missing.body
        assert "older" not in missing.body
        assert "younger" not in missing.body
        key = accounts.login("ada", PASSWORD, NOW)
        expired_at = NOW + timedelta(minutes=15, seconds=1)
        expired = respond_parent_check(
            accounts, cookie=key, form={"client": "older"}, now=expired_at
        )
        assert "Enter your username and password." in expired.body
        assert "older" not in expired.body
        names = [row[0] for row in store.connection.execute("SELECT client_group FROM parent_checks")]
        assert names == ["younger"]
        assert accounts.accept(key, NOW + timedelta(minutes=15)) is None

        fresh = accounts.login("ada", PASSWORD, NOW)
        recorded = respond_parent_check(
            accounts, cookie=fresh, form={"client": "older"}, now=NOW + timedelta(minutes=1)
        )
        assert "older" in recorded.body
        names = [
            row[0]
            for row in store.connection.execute(
                "SELECT client_group FROM parent_checks ORDER BY id"
            )
        ]
        assert names == ["younger", "older"]


def test_attempts_without_an_account_or_a_session_show_no_attempts():
    with PolicyStore(":memory:") as store:
        bare = Accounts(store.connection)
        closed = respond_attempts(bare, method="GET", query={}, cookie=None, form={}, now=NOW)
        assert closed.status == 403
        assert "No attempts" not in closed.body
        accounts = _accounts(store)
        accounts.record_parent_check("younger", NOW)
        unsigned = respond_attempts(accounts, method="GET", query={}, cookie=None, form={}, now=NOW)
        assert "Enter your username and password." in unsigned.body
        assert "younger" not in unsigned.body


def test_the_command_stores_a_hash_and_does_not_write_the_policy_file(tmp_path):
    database = tmp_path / "policy.sqlite3"
    policy = tmp_path / "policy.yaml"
    policy.write_text("timezone: Australia/Sydney\n", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["POLICY_DB"] = str(database)
    env["POLICY_FILE"] = str(policy)
    completed = subprocess.run(
        [sys.executable, "-m", "policy.accounts", "ada"],
        input=PASSWORD + "\n",
        text=True,
        capture_output=True,
        env=env,
        cwd=ROOT,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert policy.read_text(encoding="utf-8") == "timezone: Australia/Sydney\n"
    assert PASSWORD.encode() not in database.read_bytes()
    with PolicyStore(database) as store:
        accounts = Accounts(store.connection)
        assert accounts.login("ada", PASSWORD, NOW) is not None
        key = accounts.login("ada", PASSWORD, NOW)
    again = subprocess.run(
        [sys.executable, "-m", "policy.accounts", "ada"],
        input="a-new-password\n",
        text=True,
        capture_output=True,
        env=env,
        cwd=ROOT,
        check=False,
    )
    assert again.returncode == 0, again.stderr
    with PolicyStore(database) as store:
        accounts = Accounts(store.connection)
        assert accounts.accept(key, NOW + timedelta(minutes=1)) is None
        assert accounts.login("ada", "a-new-password", NOW) is not None


def test_the_command_help_exits_zero_without_reading_a_password(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT), "POLICY_DB": str(tmp_path / "policy.sqlite3")}
    for flag in ("--help", "-h"):
        completed = subprocess.run(
            [sys.executable, "-m", "policy.accounts", flag],
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            env=env,
            cwd=ROOT,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.startswith("usage: python -m policy.accounts USERNAME")
    assert not (tmp_path / "policy.sqlite3").exists()


def test_the_decision_and_observation_apis_do_not_record_a_pass():
    with PolicyStore(":memory:") as store:
        Accounts(store.connection)
        body = json.dumps(
            {
                "client_ip": "192.0.2.40",
                "url": "https://example.com/quiz",
                "occurred_at": "2026-10-31T12:00:00+00:00",
                "bytes": 20,
            }
        ).encode()
        assert status_for(store, body) == (204, b"")
        assert store.connection.execute("SELECT COUNT(*) FROM parent_checks").fetchone()[0] == 0


def test_parent_pages_over_http_do_not_set_a_cookie_or_record_a_pass(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    database = tmp_path / "policy.sqlite3"
    monkeypatch.setenv("POLICY_FILE", str(tmp_path / "policy.yaml"))
    monkeypatch.setenv("POLICY_DB", str(database))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    monkeypatch.setenv("DECISION_FILE", str(tmp_path / "decision.json"))
    monkeypatch.delenv("DECISION_STUB", raising=False)
    monkeypatch.delenv("PARENT_IDLE", raising=False)
    monkeypatch.delenv("PARENT_LIFETIME", raising=False)
    with PolicyStore(database) as store:
        Accounts(store.connection).set_password("ada", PASSWORD)
    app = create_app()
    assert app.state.idle == timedelta(minutes=15)
    assert app.state.lifetime == timedelta(minutes=180)

    status, body, headers = _call(app, "GET", "/quiz")
    assert status == 200
    assert "Revision" in body
    assert "set-cookie" not in headers

    status, body, headers = _call(app, "GET", "/usage")
    assert status == 403
    assert "Open this page over HTTPS." in body
    assert "Younger child" not in body
    assert "set-cookie" not in headers

    status, _body, headers = _call(
        app,
        "POST",
        "/usage",
        body=f"username=ada&password={PASSWORD}".encode(),
        content_type="application/x-www-form-urlencoded",
    )
    assert status == 403
    assert "set-cookie" not in headers

    status, body, headers = _call(
        app,
        "POST",
        "/usage",
        body=f"username=ada&password={PASSWORD}".encode(),
        content_type="application/x-www-form-urlencoded",
        scheme="https",
    )
    assert status == 303
    cookie = headers["set-cookie"][0]
    assert "Secure" in cookie and "HttpOnly" in cookie
    token = cookie.split(";", 1)[0].split("=", 1)[1]

    status, body, headers = _call(
        app,
        "POST",
        "/attempts/parent-check",
        body=b"client=younger",
        content_type="application/x-www-form-urlencoded",
        cookie=f"parent_session={token}",
    )
    assert status == 403
    assert "set-cookie" not in headers
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM parent_checks").fetchone()[0] == 0

    status, body, _headers = _call(
        app,
        "POST",
        "/attempts/parent-check",
        body=b"client=younger",
        content_type="application/x-www-form-urlencoded",
        cookie=f"parent_session={token}",
        scheme="https",
    )
    assert status == 200
    assert "younger" in body
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM parent_checks").fetchone()[0] == 1

    decision = json.dumps(
        {
            "client_ip": "192.0.2.40",
            "method": "GET",
            "url": "https://example.com/",
            "occurred_at": "2026-10-31T12:00:00+00:00",
        }
    ).encode()
    status, _body, _headers = _call(
        app, "POST", "/v1/decisions", body=decision, content_type="application/json"
    )
    assert status == 200
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM parent_checks").fetchone()[0] == 1


def test_the_service_uses_the_configured_session_limits(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    monkeypatch.setenv("POLICY_FILE", str(tmp_path / "policy.yaml"))
    monkeypatch.setenv("POLICY_DB", str(tmp_path / "policy.sqlite3"))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    monkeypatch.setenv("DECISION_FILE", str(tmp_path / "decision.json"))
    monkeypatch.setenv("PARENT_IDLE", "1m")
    monkeypatch.setenv("PARENT_LIFETIME", "5m")
    app = create_app()
    assert app.state.idle == timedelta(minutes=1)
    assert app.state.lifetime == timedelta(minutes=5)


def test_a_bad_session_limit_stops_the_service(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    monkeypatch.setenv("POLICY_FILE", str(tmp_path / "policy.yaml"))
    monkeypatch.setenv("POLICY_DB", str(tmp_path / "policy.sqlite3"))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    monkeypatch.setenv("PARENT_IDLE", "0s")
    with pytest.raises(SystemExit):
        create_app()


def _call(app, method, path, *, query="", body=b"", cookie=None, content_type=None, scheme="http"):
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
    if content_type:
        headers.append((b"content-type", content_type.encode()))
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
        "query_string": query.encode(),
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 443 if scheme == "https" else 80),
        "root_path": "",
    }
    import asyncio

    asyncio.run(app(scope, receive, send))
    start = next(item for item in messages if item["type"] == "http.response.start")
    payload = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
    found: dict[str, list[str]] = {}
    for key, value in start["headers"]:
        found.setdefault(key.decode(), []).append(value.decode())
    return start["status"], payload.decode(), found
