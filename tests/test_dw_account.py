"""S044.1: dw-account, accounts with no password or an email address, removing accounts, and the sign-in limits."""

import hashlib
import json
import os
import signal
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
from policy.accounts import ADMIN, REVIEWER, AccountError, Accounts, _DUMMY, _HASHER  # noqa: E402
from policy.store import PolicyStore  # noqa: E402
from test_mcp_server import PASSWORD, activity, connect, mcp, service  # noqa: E402,F401 - service is the fixture

NOW = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)


def dw_account(database: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    """Run the command without a terminal. stdin None gives it an empty standard input."""
    env = {**os.environ, "PYTHONPATH": str(ROOT), "POLICY_DB": str(database)}
    return subprocess.run(
        [sys.executable, "-m", "policy.accounts", *args],
        input=stdin,
        stdin=subprocess.DEVNULL if stdin is None else None,
        text=True,
        capture_output=True,
        env=env,
        cwd=ROOT,
        check=False,
        timeout=60,
    )


def listing(database: Path) -> list[str]:
    done = dw_account(database, "list")
    assert done.returncode == 0, done.stderr
    return [" ".join(line.split()) for line in done.stdout.splitlines()]


@pytest.fixture
def database(tmp_path):
    """A database with Ada, the first admin."""
    path = tmp_path / "policy.sqlite3"
    added = dw_account(path, "add", "--role", "admin", "--password", "ada", stdin=PASSWORD + "\n")
    assert added.returncode == 0, added.stderr
    return path


def signs_in(database: Path, username: str, password: str) -> bool:
    with PolicyStore(database) as store:
        return Accounts(store.connection).login(username, password, NOW) is not None


# Upgrading


def _old_database(path: Path, *, roles: bool) -> bytes:
    """Write the accounts table as it was before S044.1, or before S043, with two accounts and a session for ada."""
    key = os.urandom(32)
    role = ", role TEXT NOT NULL DEFAULT 'admin'" if roles else ""
    with sqlite3.connect(path) as connection:
        connection.executescript(
            f"""
            CREATE TABLE parent_accounts (id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL{role});
            CREATE TABLE parent_sessions (
                id INTEGER PRIMARY KEY,
                account_id INTEGER NOT NULL REFERENCES parent_accounts(id) ON DELETE CASCADE,
                key_hash TEXT NOT NULL UNIQUE, signed_in_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
            );
            """
        )
        connection.execute("INSERT INTO parent_accounts (id, username, password_hash) VALUES (3, 'bee', ?)", (_HASHER.hash("bee-pass"),))
        connection.execute("INSERT INTO parent_accounts (id, username, password_hash) VALUES (7, 'ada', ?)", (_HASHER.hash(PASSWORD),))
        if roles:
            connection.execute("UPDATE parent_accounts SET role = 'reviewer' WHERE username = 'bee'")
        connection.execute(
            "INSERT INTO parent_sessions (account_id, key_hash, signed_in_at, last_seen_at) VALUES (7, ?, ?, ?)",
            (hashlib.sha256(key).hexdigest(), NOW.isoformat(), NOW.isoformat()),
        )
    return key


@pytest.mark.parametrize("roles", [True, False])
def test_an_upgrade_keeps_every_account_its_role_password_and_sessions(tmp_path, roles):
    path = tmp_path / "policy.sqlite3"
    key = _old_database(path, roles=roles)
    assert listing(path) == ["ada admin no email", f"bee {'reviewer' if roles else 'admin'} no email"]
    with PolicyStore(path) as store:
        accounts = Accounts(store.connection)
        assert accounts.accept(key.hex(), NOW + timedelta(minutes=1)) == ("ada", ADMIN)
        assert accounts.account_id("ada") == 7
        assert accounts.login("bee", "bee-pass", NOW) is not None
        # The rebuilt table takes accounts with no password.
        accounts.add("nana", email="nana@example.net")
    # Opening it again does not rebuild it again.
    with PolicyStore(path) as store:
        assert Accounts(store.connection).accept(key.hex(), NOW + timedelta(minutes=2)) == ("ada", ADMIN)
    assert listing(path)[-1] == "nana reviewer nana@example.net no password"


def test_a_removed_accounts_id_is_never_used_again(tmp_path):
    path = tmp_path / "policy.sqlite3"
    _old_database(path, roles=True)
    with PolicyStore(path) as store:
        accounts = Accounts(store.connection)
        accounts.add("cara", ADMIN, password=PASSWORD)
        cara = accounts.account_id("cara")
        accounts.remove("cara")
        accounts.add("cara", ADMIN, password=PASSWORD)
        assert accounts.account_id("cara") > cara


# add


def test_add_with_an_email_and_no_password_asks_for_none(database):
    added = dw_account(database, "add", "--email", "nana@example.net", "nana")
    assert added.returncode == 0, added.stderr
    assert "nana is added, as a reviewer, with the email address nana@example.net." in added.stdout
    assert "nana has no password yet. dw-account update --password nana sets one." in added.stdout
    assert "Password" not in added.stdout + added.stderr
    assert listing(database) == ["ada admin no email", "nana reviewer nana@example.net no password"]


def test_add_with_a_password_and_a_role(database):
    added = dw_account(database, "add", "--role", "admin", "--password", "bee", stdin="bee-pass\n")
    assert added.returncode == 0, added.stderr
    assert "bee is added, as an admin, with no email address." in added.stdout
    assert "no password" not in added.stdout
    assert listing(database) == ["ada admin no email", "bee admin no email"]
    assert signs_in(database, "bee", "bee-pass")


@pytest.mark.parametrize(
    ("args", "problem"),
    [
        (("add", "nana"), "nana would have no email address and no password, so there would be no way to set a password."),
        (("add", "--role", "admin", "--email", "x@example.net", "ada"), "ada already exists, so nothing was added. Change it with dw-account update."),
        (("add", "--email", "nana", "nana"), "nana is not an email address."),
        (("add", "--email", "nana@", "nana"), "nana@ is not an email address."),
    ],
)
def test_a_refused_add_adds_nothing(database, args, problem):
    refused = dw_account(database, *args)
    assert refused.returncode == 1
    assert problem in refused.stderr
    assert listing(database) == ["ada admin no email"]


def test_the_first_account_must_be_an_admin(tmp_path):
    path = tmp_path / "policy.sqlite3"
    for args in (("add", "--email", "nana@example.net", "nana"), ("add", "--role", "reviewer", "--password", "nana")):
        refused = dw_account(path, *args, stdin="nana-pass\n")
        assert refused.returncode == 1
        assert refused.stderr.strip() == "There is no admin yet. Add the first account with --role admin."
    assert listing(path) == ["There are no parent accounts. Add the first with dw-account add --role admin --password USERNAME."]


# update


def test_update_sets_and_removes_an_email_without_asking_for_a_password(database):
    key = None
    with PolicyStore(database) as store:
        key = Accounts(store.connection).login("ada", PASSWORD, NOW)
    done = dw_account(database, "update", "--email", "ada@example.net", "ada")
    assert done.returncode == 0, done.stderr
    assert "ada's email address is now ada@example.net." in done.stdout
    assert listing(database) == ["ada admin ada@example.net"]
    done = dw_account(database, "update", "ada", "--no-email")
    assert done.returncode == 0, done.stderr
    assert "ada has no email address now." in done.stdout
    assert listing(database) == ["ada admin no email"]
    with PolicyStore(database) as store:
        # An address change keeps her signed in.
        assert Accounts(store.connection).accept(key, NOW) == ("ada", ADMIN)


def test_update_password_gives_an_account_with_none_its_first(database):
    assert dw_account(database, "add", "--email", "nana@example.net", "nana").returncode == 0
    assert not signs_in(database, "nana", "")
    done = dw_account(database, "update", "--password", "nana", stdin="nana-pass\n")
    assert done.returncode == 0, done.stderr
    assert "nana's password is set." in done.stdout
    assert signs_in(database, "nana", "nana-pass")
    assert listing(database)[-1] == "nana reviewer nana@example.net"


def test_update_password_ends_the_sessions(database):
    with PolicyStore(database) as store:
        key = Accounts(store.connection).login("ada", PASSWORD, NOW)
    assert dw_account(database, "update", "--password", "ada", stdin="a-new-password\n").returncode == 0
    with PolicyStore(database) as store:
        accounts = Accounts(store.connection)
        assert accounts.accept(key, NOW) is None
        assert accounts.login("ada", "a-new-password", NOW) is not None
    assert PASSWORD.encode() not in database.read_bytes()


def test_several_switches_are_all_applied(database):
    assert dw_account(database, "add", "--email", "nana@example.net", "nana").returncode == 0
    done = dw_account(database, "update", "--role", "admin", "--email", "nana@example.org", "--password", "nana", stdin="nana-pass\n")
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == [
        "nana is now an admin. Its sessions have ended.",
        "nana's email address is now nana@example.org.",
        "nana's password is set. Its sessions and the MCP connections it approved have ended.",
    ]
    assert listing(database) == ["ada admin no email", "nana admin nana@example.org"]


@pytest.mark.parametrize(
    ("args", "stdin", "problem"),
    [
        (("update", "--role", "reviewer", "--email", "ada@example.net", "ada"), None, "ada is the only admin. Add another admin first."),
        (("update", "--email", "ada@", "--password", "ada"), "new-pass\n", "ada@ is not an email address."),
        (("update", "--email", "ada@example.net", "--password", "ada"), "\n", "The password is empty. Nothing was changed."),
        (("update", "--email", "ada@example.net", "--password", "ada"), "x" * 201 + "\n", "longer than 200 characters"),
        (("update", "--email", "zed@example.net", "zed"), None, "There is no parent account zed. Nothing was changed. Add it with dw-account add."),
        (("remove", "--yes", "zed"), None, "There is no parent account zed. Nothing was removed. Add it with dw-account add."),
    ],
)
def test_one_refused_switch_changes_nothing(database, args, stdin, problem):
    refused = dw_account(database, *args, stdin=stdin)
    assert refused.returncode == 1
    assert problem in refused.stderr
    assert listing(database) == ["ada admin no email"]
    assert signs_in(database, "ada", PASSWORD)


def test_a_password_of_200_characters_is_accepted(database):
    long = "é" * 200
    assert dw_account(database, "update", "--password", "ada", stdin=long + "\n").returncode == 0
    assert signs_in(database, "ada", long)


@pytest.mark.parametrize(
    "args",
    [
        ("update", "ada"),
        ("update", "--email", "a@example.net", "--no-email", "ada"),
        ("list", "--role", "admin"),
        ("remove", "--password", "ada"),
        ("add", "--role", "owner", "--email", "x@example.net", "nana"),
        ("add", "--email", "x@example.net"),
        ("update", "--role", "admin"),
        ("remove",),
    ],
)
def test_a_command_line_that_does_not_fit_shows_the_subcommands_usage_and_changes_nothing(database, args):
    refused = dw_account(database, *args, stdin="x\n")
    assert refused.returncode == 2
    assert refused.stderr.startswith(f"usage: dw-account {args[0]} ")
    assert listing(database) == ["ada admin no email"]


@pytest.mark.parametrize("args", [(), ("rename", "ada"), ("--role", "admin", "ada")])
def test_no_or_an_unknown_subcommand_shows_the_usage(database, args):
    refused = dw_account(database, *args)
    assert refused.returncode == 2
    assert refused.stderr.startswith("usage: dw-account SUBCOMMAND")


def test_help_describes_every_subcommand_and_switch(tmp_path):
    path = tmp_path / "policy.sqlite3"
    for args in (("help",), ("--help",)):
        shown = dw_account(path, *args)
        assert shown.returncode == 0
        for word in ("add", "update", "remove", "list", "--role", "--email", "--no-email", "--password", "--yes", "must not exist", "existing account"):
            assert word in shown.stdout
    for name, switches in {"add": ["--role", "--email", "--password"], "update": ["--role", "--email", "--no-email", "--password"], "remove": ["--yes"]}.items():
        shown = dw_account(path, name, "--help")
        assert shown.returncode == 0
        assert all(switch in shown.stdout for switch in switches)
    assert not path.exists()


# remove


def test_remove_without_a_terminal_needs_yes(database):
    assert dw_account(database, "add", "--email", "nana@example.net", "nana").returncode == 0
    refused = dw_account(database, "remove", "nana")
    assert refused.returncode == 1
    assert "Give --yes" in refused.stderr
    assert len(listing(database)) == 2
    done = dw_account(database, "remove", "--yes", "nana")
    assert done.returncode == 0, done.stderr
    assert "nana is removed." in done.stdout
    assert listing(database) == ["ada admin no email"]


def test_the_only_admin_cannot_be_removed(database):
    refused = dw_account(database, "remove", "--yes", "ada")
    assert refused.returncode == 1
    assert refused.stderr.strip() == "ada is the only admin. Add another admin first."
    assert listing(database) == ["ada admin no email"]


def test_removing_an_account_ends_its_sessions_and_connections_and_a_new_one_gets_none_back(service):
    database = service.state.database
    with PolicyStore(database) as store:
        Accounts(store.connection).add("bee", ADMIN, password="bee-pass")
    _status, _body, headers = call(service, "POST", "/parent/api/login", json_body={"username": "bee", "password": "bee-pass"})
    bee = session_cookie(headers)
    _client, tokens = connect(service, bee)
    with PolicyStore(database) as store:
        connection = store.connection
        (codes,) = connection.execute("SELECT COUNT(*) FROM mcp_codes").fetchone()
        assert codes == 1
    assert dw_account(database, "remove", "--yes", "bee").returncode == 0

    assert call(service, "GET", "/parent/api/session", cookie=bee)[0] == 401
    assert mcp(service, tokens["access_token"], "tools/list")[0] == 401
    status, body, _headers = call(service, "POST", "/parent/api/login", json_body={"username": "bee", "password": "bee-pass"})
    assert (status, json.loads(body)) == (401, {"error": "Username or password incorrect."})
    with PolicyStore(database) as store:
        assert store.connection.execute("SELECT COUNT(*) FROM mcp_codes").fetchone() == (0,)
    _status, _body, headers = call(service, "POST", "/parent/api/login", json_body={"username": "ada", "password": PASSWORD})
    entries = activity(service, session_cookie(headers))
    assert entries[0]["parent"] == "bee"
    assert "the parent's account was removed" in json.dumps(entries[0])
    assert any(entry["outcome"] == "approved" and entry["parent"] == "bee" for entry in entries)

    # A new bee is a new account.
    with PolicyStore(database) as store:
        Accounts(store.connection).add("bee", ADMIN, password="bee-pass")
    assert call(service, "GET", "/parent/api/session", cookie=bee)[0] == 401
    assert mcp(service, tokens["access_token"], "tools/list")[0] == 401
    status, _body, _headers = call(
        service, "POST", "/oauth/token", body=f"grant_type=refresh_token&refresh_token={tokens['refresh_token']}".encode(),
        content_type="application/x-www-form-urlencoded",
    )
    assert status == 400


# Signing in


@pytest.mark.parametrize("password", ["", "anything", None])
def test_an_account_with_no_password_refuses_every_sign_in_like_a_wrong_password(service, password, monkeypatch):
    with PolicyStore(service.state.database) as store:
        Accounts(store.connection).add("nana", email="nana@example.net")
    seen = []
    real = accounts_module._HASHER

    class Spy:
        def verify(self, stored, given):
            seen.append(stored)
            return real.verify(stored, given)

    monkeypatch.setattr(accounts_module, "_HASHER", Spy())
    body = {"username": "nana"} if password is None else {"username": "nana", "password": password}
    status, text, headers = call(service, "POST", "/parent/api/login", json_body=body)
    wrong = call(service, "POST", "/parent/api/login", json_body={"username": "ada", "password": "wrong"})
    assert status == wrong[0] == 401
    assert text == wrong[1]
    assert "set-cookie" not in headers
    # The same work as a wrong password: one Argon2 check, against the dummy hash.
    assert seen[0] == _DUMMY and len(seen) == 2


def test_a_password_over_200_characters_is_refused_without_hashing_it(service, monkeypatch):
    seen = []
    real = accounts_module._HASHER

    class Spy:
        def verify(self, stored, given):
            seen.append(given)
            return real.verify(stored, given)

    monkeypatch.setattr(accounts_module, "_HASHER", Spy())
    long = "x" * 201
    status, text, headers = call(service, "POST", "/parent/api/login", json_body={"username": "ada", "password": long})
    assert status == 401
    assert json.loads(text) == {"error": "Username or password incorrect."}
    assert "set-cookie" not in headers
    assert seen and long not in seen


def test_a_sign_in_body_over_4_kb_is_refused_with_413(service):
    big = json.dumps({"username": "ada", "password": PASSWORD, "next": "x" * 4096}).encode()
    status, _text, headers = call(service, "POST", "/parent/api/login", body=big, content_type="application/json")
    assert status == 413
    assert "set-cookie" not in headers


# The prompt


def test_the_prompt_restores_echo_when_a_signal_ends_it(tmp_path, database):
    """Run update --password under a pseudo-terminal, send each signal while it waits, and check the echo."""
    pty = pytest.importorskip("pty")
    import termios

    env = {**os.environ, "PYTHONPATH": str(ROOT), "POLICY_DB": str(database)}
    for signum in (signal.SIGINT, signal.SIGQUIT, signal.SIGTERM, signal.SIGHUP):
        primary, secondary = pty.openpty()
        process = subprocess.Popen(
            [sys.executable, "-m", "policy.accounts", "update", "--password", "ada"],
            stdin=secondary, stdout=secondary, stderr=secondary, env=env, cwd=ROOT, start_new_session=True,
        )
        os.close(secondary)
        seen = b""
        while b"Password: " not in seen:
            seen += os.read(primary, 1024)
        assert not termios.tcgetattr(primary)[3] & termios.ECHO
        process.send_signal(signum)
        assert process.wait(timeout=10) == 130
        assert termios.tcgetattr(primary)[3] & termios.ECHO
        output = b""
        try:
            while True:
                output += os.read(primary, 1024)
        except OSError:
            pass
        os.close(primary)
        assert b"Nothing was changed." in output
    assert signs_in(database, "ada", PASSWORD)


def test_model_add_refuses_an_existing_username():
    with PolicyStore(":memory:") as store:
        accounts = Accounts(store.connection)
        accounts.add("ada", ADMIN, password=PASSWORD)
        with pytest.raises(AccountError, match="already exists"):
            accounts.add("ada", REVIEWER, email="ada@example.net")
