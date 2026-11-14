"""S007.1 and S007.4: parent accounts, sessions, and the portal data they guard."""

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

from asgi import call, session_cookie  # noqa: E402
from policy import accounts as accounts_module  # noqa: E402
from policy.accounts import Accounts, _DUMMY, session_limits  # noqa: E402
from policy.observations import status_for  # noqa: E402
from policy.store import PolicyStore  # noqa: E402
from policy.tasks import AttemptStore, TaskKey  # noqa: E402
from policy.usage import UsageStore  # noqa: E402

PASSWORD = "s3cret-pass"
NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
HOUSE = """\
timezone: Australia/Sydney
entry: entry
client_groups:
  younger:
    addresses: ["192.0.2.40"]
site_groups:
  entertainment:
    priority: 30
    patterns: ["*.youtube.com"]
rule_sets:
  entry:
    - condition: always
      when_true: { action: allow }
"""


def _accounts(store: PolicyStore, **limits) -> Accounts:
    accounts = Accounts(store.connection, **limits)
    accounts.set_password("ada", PASSWORD)
    return accounts


@pytest.fixture
def service(tmp_path, monkeypatch):
    """The decisions app on a fresh database with the household policy and no account yet."""
    pytest.importorskip("fastapi")
    from policy.app import create_app

    policy = tmp_path / "policy.yaml"
    policy.write_text(HOUSE, encoding="utf-8")
    database = tmp_path / "policy.sqlite3"
    monkeypatch.setenv("POLICY_FILE", str(policy))
    monkeypatch.setenv("POLICY_DB", str(database))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    monkeypatch.delenv("PARENT_IDLE", raising=False)
    monkeypatch.delenv("PARENT_LIFETIME", raising=False)

    class Service:
        def __init__(self):
            self.database = database

        def app(self, *, account=True):
            if account:
                with PolicyStore(database) as store:
                    Accounts(store.connection).set_password("ada", PASSWORD)
            return create_app()

        def count(self, table):
            with sqlite3.connect(database) as connection:
                return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    return Service()


def _sign_in(app, password=PASSWORD, username="ada", **kwargs):
    return call(app, "POST", "/parent/api/login", json_body={"username": username, "password": password}, **kwargs)


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
    policy = tmp_path / "policy.yaml"
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


def test_unknown_username_and_wrong_password_look_the_same(service):
    app = service.app()
    unknown = _sign_in(app, username="nobody")
    wrong = _sign_in(app, password="wrong-password")
    assert unknown[0] == wrong[0] == 401
    assert unknown[1] == wrong[1]
    assert json.loads(unknown[1]) == {"error": "Username or password incorrect."}
    assert "set-cookie" not in unknown[2]
    assert "set-cookie" not in wrong[2]
    assert service.count("parent_sessions") == 0


def test_the_right_password_sets_a_secure_cookie_and_the_data_opens(service):
    app = service.app()
    status, body, headers = _sign_in(app)
    assert status == 200
    header = headers["set-cookie"][0]
    assert header.startswith("parent_session=")
    for part in ("Secure", "HttpOnly", "SameSite=Lax", "Path=/"):
        assert part in header
    assert headers["cache-control"] == ["no-store"]
    cookie = session_cookie(headers)
    status, body, _headers = call(app, "GET", "/parent/api/session", cookie=cookie)
    assert (status, json.loads(body)) == (200, {"username": "ada"})
    status, body, _headers = call(app, "GET", "/parent/api/attempts", query="client=younger", cookie=cookie)
    assert status == 200
    assert json.loads(body)["client"] == "younger"


def test_a_query_string_password_a_form_post_and_an_old_gate_cookie_do_not_sign_in(service):
    app = service.app()
    status, _body, headers = call(app, "POST", "/parent/api/login", query=f"username=ada&password={PASSWORD}")
    assert status == 415
    assert "set-cookie" not in headers
    status, _body, headers = call(
        app,
        "POST",
        "/parent/api/login",
        query=f"username=ada&password={PASSWORD}",
        json_body={},
    )
    assert status == 401
    assert "set-cookie" not in headers
    status, _body, headers = call(
        app,
        "POST",
        "/parent/api/login",
        body=f"username=ada&password={PASSWORD}".encode(),
        content_type="application/x-www-form-urlencoded",
    )
    assert status == 415
    assert "set-cookie" not in headers
    old = hmac.new(PASSWORD.encode(), b"daywarden-parent", hashlib.sha256).hexdigest()
    status, _body, headers = call(app, "GET", "/parent/api/session", cookie=f"parent_session={old}")
    assert status == 401
    assert "set-cookie" not in headers
    assert service.count("parent_sessions") == 0


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


def test_a_parent_check_without_a_session_or_a_json_body_does_not_record_a_pass(service):
    app = service.app()
    check = {"client": "younger"}
    status, body, _headers = call(app, "POST", "/parent/api/parent-check", json_body=check)
    assert status == 401
    assert "younger" not in body
    cookie = session_cookie(_sign_in(app)[2])
    with sqlite3.connect(service.database) as connection:
        connection.execute("UPDATE parent_sessions SET last_seen_at = '2000-01-01T00:00:00+00:00'")
    status, _body, _headers = call(app, "POST", "/parent/api/parent-check", json_body=check, cookie=cookie)
    assert status == 401
    assert service.count("parent_checks") == 0
    assert service.count("parent_sessions") == 0

    cookie = session_cookie(_sign_in(app)[2])
    for content_type in ("application/x-www-form-urlencoded", "text/plain", "multipart/form-data; boundary=x"):
        status, _body, _headers = call(
            app,
            "POST",
            "/parent/api/parent-check",
            body=b"client=younger",
            content_type=content_type,
            cookie=cookie,
        )
        assert status == 415
    status, body, _headers = call(app, "POST", "/parent/api/parent-check", json_body={"client": "stranger"}, cookie=cookie)
    assert (status, json.loads(body)) == (400, {"error": "That client group is not in the household."})
    assert service.count("parent_checks") == 0

    status, body, _headers = call(app, "POST", "/parent/api/parent-check", json_body=check, cookie=cookie)
    assert (status, json.loads(body)) == (200, {"message": "Recorded a parent check for younger."})
    assert service.count("parent_checks") == 1
    with PolicyStore(service.database) as store:
        assert [row.task_set for row in AttemptStore(connection=store.connection).attempts("younger")] == ["parent_check"]


def test_without_an_account_or_a_session_the_data_endpoints_show_nothing(service):
    closed = service.app(account=False)
    with PolicyStore(service.database) as store:
        AttemptStore(connection=store.connection).record("younger", TaskKey("spelling", "words"), "pass", NOW, detail={"answers": ["wombat"]})
    for path, query in (("/parent/api/attempts", "client=younger"), ("/parent/api/attempts/1", ""), ("/parent/api/usage/minutes", "client=younger"), ("/parent/api/session", "")):
        status, body, _headers = call(closed, "GET", path, query=query)
        assert status == 403, path
        assert json.loads(body) == {"error": "The parent portal is closed until a parent account is added.", "closed": True}
    status, _body, headers = _sign_in(closed)
    assert status == 403
    assert "set-cookie" not in headers

    app = service.app()
    for path, query in (("/parent/api/attempts", "client=younger"), ("/parent/api/attempts/1", ""), ("/parent/api/usage/minutes", "client=younger")):
        status, body, headers = call(app, "GET", path, query=query)
        assert status == 401, path
        assert "wombat" not in body and "words" not in body and "younger" not in body
        assert "location" not in headers
        assert headers["cache-control"] == ["no-store"]


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
        assert status_for(None, UsageStore(connection=store.connection), body) == (204, b"")
        assert store.connection.execute("SELECT COUNT(*) FROM parent_checks").fetchone()[0] == 0


def test_plain_http_does_not_sign_in_show_data_or_record_a_pass(service):
    app = service.app()
    assert app.state.idle == timedelta(minutes=15)
    assert app.state.lifetime == timedelta(minutes=180)

    status, body, headers = call(app, "GET", "/quiz", scheme="http")
    assert status == 200
    assert "Revision" in body
    assert "set-cookie" not in headers

    status, _body, headers = _sign_in(app, scheme="http")
    assert status == 403
    assert "set-cookie" not in headers
    assert service.count("parent_sessions") == 0

    cookie = session_cookie(_sign_in(app)[2])
    for path in ("/parent/api/session", "/parent/api/attempts", "/parent/api/usage/minutes", "/parent/", "/parent/attempts", "/usage", "/attempts/1"):
        status, body, headers = call(app, "GET", path, query="client=younger", cookie=cookie, scheme="http")
        assert status == 403, path
        assert "Open this page over HTTPS." in body
        assert "younger" not in body
        assert "set-cookie" not in headers
        assert "location" not in headers

    status, _body, headers = call(app, "POST", "/parent/api/parent-check", json_body={"client": "younger"}, cookie=cookie, scheme="http")
    assert status == 403
    assert "set-cookie" not in headers
    assert service.count("parent_checks") == 0

    decision = json.dumps(
        {
            "client_ip": "192.0.2.40",
            "method": "GET",
            "url": "https://example.com/",
            "occurred_at": "2026-10-31T12:00:00+00:00",
        }
    ).encode()
    status, _body, _headers = call(app, "POST", "/v1/decisions", body=decision, content_type="application/json", scheme="http")
    assert status == 200
    assert service.count("parent_checks") == 0


def test_the_service_uses_the_configured_session_limits(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    monkeypatch.setenv("POLICY_FILE", str(tmp_path / "policy.yaml"))
    monkeypatch.setenv("POLICY_DB", str(tmp_path / "policy.sqlite3"))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
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

