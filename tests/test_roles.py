"""S043: admin and reviewer roles, on the accounts, the command, the portal's data addresses, and the MCP server."""

import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from asgi import call, session_cookie  # noqa: E402
from policy.accounts import ADMIN, REVIEWER, AccountError, Accounts, _HASHER  # noqa: E402
from policy.portal import REVIEWER_ADDRESSES  # noqa: E402
from policy.store import PolicyStore  # noqa: E402
from test_mcp_server import (  # noqa: E402,F401 - service is the fixture
    PASSWORD,
    activity,
    authorize,
    call_tool,
    connect,
    consent,
    decide,
    page,
    register,
    save,
    service,
    tool_answer,
    tool_names,
)

NOW = datetime(2026, 11, 19, 9, 0, tzinfo=timezone.utc)
REVIEWER_TOOLS = ["list_attempts", "get_task_trend", "get_arithmetic_facts", "get_spelling_words", "get_attempt", "get_usage", "list_requests"]


def add(app, username: str, role: str | None = None) -> None:
    with PolicyStore(app.state.database) as store:
        Accounts(store.connection).set_password(username, PASSWORD, role)


def set_role(app, username: str, role: str) -> None:
    with PolicyStore(app.state.database) as store:
        Accounts(store.connection).update(username, role=role)


def sign_in_as(app, username: str) -> str:
    status, body, headers = call(app, "POST", "/parent/api/login", json_body={"username": username, "password": PASSWORD})
    assert status == 200, body
    return session_cookie(headers)


# Accounts


def test_accounts_from_before_roles_become_admins_and_keep_their_sessions(tmp_path):
    database = tmp_path / "policy.sqlite3"
    key = os.urandom(32)
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE parent_accounts (id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL);
            CREATE TABLE parent_sessions (
                id INTEGER PRIMARY KEY,
                account_id INTEGER NOT NULL REFERENCES parent_accounts(id) ON DELETE CASCADE,
                key_hash TEXT NOT NULL UNIQUE, signed_in_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
            );
            """
        )
        connection.execute("INSERT INTO parent_accounts (username, password_hash) VALUES ('bee', ?)", (_HASHER.hash(PASSWORD),))
        connection.execute("INSERT INTO parent_accounts (username, password_hash) VALUES ('ada', ?)", (_HASHER.hash(PASSWORD),))
        moment = NOW.isoformat()
        connection.execute(
            "INSERT INTO parent_sessions (account_id, key_hash, signed_in_at, last_seen_at) VALUES (2, ?, ?, ?)",
            (hashlib.sha256(key).hexdigest(), moment, moment),
        )
    with PolicyStore(database) as store:
        accounts = Accounts(store.connection)
        assert accounts.accounts() == [("ada", ADMIN), ("bee", ADMIN)]
        assert accounts.accept(key.hex(), NOW + timedelta(minutes=1)) == ("ada", ADMIN)
        assert accounts.login("bee", PASSWORD, NOW) is not None
    # Opening it again does not upgrade it twice.
    with PolicyStore(database) as store:
        assert Accounts(store.connection).accounts() == [("ada", ADMIN), ("bee", ADMIN)]


def test_changing_a_role_ends_the_accounts_sessions_and_only_that_accounts():
    with PolicyStore(":memory:") as store:
        accounts = Accounts(store.connection)
        accounts.set_password("ada", PASSWORD)
        accounts.set_password("bee", PASSWORD)
        ada = accounts.login("ada", PASSWORD, NOW)
        bee = accounts.login("bee", PASSWORD, NOW)
        accounts.update("bee", role=REVIEWER)
        assert accounts.accept(bee, NOW) is None
        assert accounts.accept(ada, NOW) == ("ada", ADMIN)
        assert accounts.accept(accounts.login("bee", PASSWORD, NOW), NOW) == ("bee", REVIEWER)


@pytest.mark.parametrize(
    ("username", "role", "problem"),
    [
        ("ada", REVIEWER, "ada is the only admin. Add another admin first."),
        ("zed", REVIEWER, "There is no parent account zed. Nothing was changed. Add it with dw-account add."),
        ("ada", "owner", "owner is not a role. The roles are admin and reviewer. Nothing was changed."),
    ],
)
def test_a_refused_role_change_changes_nothing(username, role, problem):
    with PolicyStore(":memory:") as store:
        accounts = Accounts(store.connection)
        accounts.set_password("ada", PASSWORD)
        accounts.set_password("nana", PASSWORD, REVIEWER)
        key = accounts.login("ada", PASSWORD, NOW)
        with pytest.raises(AccountError) as refused:
            accounts.update(username, role=role)
        assert str(refused.value) == problem
        assert accounts.accounts() == [("ada", ADMIN), ("nana", REVIEWER)]
        assert accounts.accept(key, NOW) == ("ada", ADMIN)


# The portal's data addresses


def _addresses(app):
    """Every data address under /parent/api/, as (method, route template, address with its parts filled in)."""
    from fastapi.routing import APIRoute

    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/parent/api/") or "{rest:path}" in route.path:
            continue
        # Signing in and out needs no session, so it is the same for every account.
        if route.path in ("/parent/api/login", "/parent/api/logout"):
            continue
        filled = re.sub(r"\{file_name\}", "x.opus", route.path)
        filled = re.sub(r"\{[a-z_]+\}", "x1", filled)
        for method in sorted(route.methods - {"HEAD"}):
            yield method, route.path, filled


def _send(app, method: str, address: str, cookie: str):
    if method == "GET":
        return call(app, "GET", address, cookie=cookie)
    if address == "/parent/api/recordings":
        return call(app, "POST", address, body=b"", content_type="audio/webm", cookie=cookie)
    return call(app, "POST", address, json_body={}, cookie=cookie)


def test_a_reviewer_is_refused_every_data_address_not_on_the_reviewer_list(service):
    add(service, "nana", REVIEWER)
    cookie = sign_in_as(service, "nana")
    refused = []
    for method, template, address in _addresses(service):
        if (method, template) in REVIEWER_ADDRESSES:
            continue
        status, body, headers = _send(service, method, address, cookie)
        assert status == 403, (method, address, body)
        assert json.loads(body) == {
            "error": "This address is for admins. You are signed in as nana, a reviewer.",
            "admins_only": True,
        }
        assert headers["cache-control"] == ["no-store"]
        refused.append(address)
    # Tasks, new task, pools, policy, recordings, weeks, audio, presets, and the MCP page.
    assert len(refused) > 40
    # The session is still good afterwards.
    assert call(service, "GET", "/parent/api/session", cookie=cookie)[0] == 200


def test_an_admin_is_refused_no_data_address(service):
    cookie = sign_in_as(service, "ada")
    for method, _template, address in _addresses(service):
        _status, body, _headers = _send(service, method, address, cookie)
        assert "admins_only" not in body, (method, address)


def test_a_reviewer_reads_attempts_and_usage_and_records_a_parent_check(service):
    add(service, "nana", REVIEWER)
    cookie = sign_in_as(service, "nana")
    status, body, _headers = call(service, "GET", "/parent/api/session", cookie=cookie)
    assert (status, json.loads(body)) == (200, {"username": "nana", "role": "reviewer"})
    for address, query in (
        ("/parent/api/attempts", "client=younger"),
        ("/parent/api/attempts/tasks/worksheet/worksheet-1", "client=younger"),
        ("/parent/api/attempts/facts/times", "client=younger"),
        ("/parent/api/attempts/words", "client=younger"),
        ("/parent/api/usage/minutes", ""),
        ("/parent/api/usage/bytes", "preset=Default"),
        ("/parent/api/usage/requests", "page=1"),
    ):
        status, body, _headers = call(service, "GET", address, query=query, cookie=cookie)
        assert status == 200, (address, body)
    status, body, _headers = call(service, "POST", "/parent/api/parent-check", json_body={"client": "younger"}, cookie=cookie)
    assert status == 200, body
    status, body, _headers = call(service, "GET", "/parent/api/attempts", query="client=younger", cookie=cookie)
    (recorded,) = json.loads(body)["attempts"]
    assert (recorded["type"], recorded["outcome"]) == ("parent_check", "pass")
    status, body, _headers = call(service, "GET", f"/parent/api/attempts/{recorded['id']}", cookie=cookie)
    assert status == 200, body


def test_unknown_data_addresses_are_still_404_for_a_reviewer(service):
    add(service, "nana", REVIEWER)
    cookie = sign_in_as(service, "nana")
    status, body, _headers = call(service, "GET", "/parent/api/no-such-thing", cookie=cookie)
    assert (status, json.loads(body)) == (404, {"error": "Not found."})


def test_changing_a_role_signs_the_account_out_and_the_new_role_applies_at_once(service):
    add(service, "bee")
    cookie = sign_in_as(service, "bee")
    assert call(service, "GET", "/parent/api/tasks", cookie=cookie)[0] == 200
    set_role(service, "bee", REVIEWER)
    assert call(service, "GET", "/parent/api/attempts", cookie=cookie)[0] == 401
    cookie = sign_in_as(service, "bee")
    assert call(service, "GET", "/parent/api/tasks", cookie=cookie)[0] == 403
    set_role(service, "bee", ADMIN)
    cookie = sign_in_as(service, "bee")
    assert call(service, "GET", "/parent/api/tasks", cookie=cookie)[0] == 200


# The MCP server


def test_a_reviewers_agent_lists_and_calls_only_attempts_and_usage_reads(service):
    add(service, "nana", REVIEWER)
    nana = sign_in_as(service, "nana")
    shown = consent(service, nana, authorize(service, register(service)))
    assert shown["reviewer"] is True
    assert shown["permissions"] == [{"name": "attempts", "permissions": ["read"]}, {"name": "usage", "permissions": ["read"]}]

    _client, tokens = connect(service, nana)
    access = tokens["access_token"]
    assert sorted(tool_names(service, access)) == sorted(REVIEWER_TOOLS)
    assert tool_answer(service, access, "list_attempts", {"client": "younger"})["attempts"] == []
    for name, arguments in (("update_task", {"type": "worksheet", "name": "worksheet-1"}), ("get_household", {}), ("list_tasks", {})):
        result = call_tool(service, access, name, arguments)
        assert result["isError"] is True
        assert result["content"][0]["text"] == "This needs an admin's approval."
    entry = activity(service, sign_in_as(service, "ada"))[0]
    assert (entry["agent"], entry["parent"], entry["tool"], entry["outcome"], entry["reasons"]) == (
        "Claude Code", "nana", "list_tasks", "refused", ["This needs an admin's approval."],
    )
    (listed,) = page(service, sign_in_as(service, "ada"))["connections"]
    assert (listed["parent"], listed["role"]) == ("nana", "reviewer")


def test_an_admins_consent_page_lists_every_grant(service):
    shown = consent(service, sign_in_as(service, "ada"), authorize(service, register(service)))
    assert shown["reviewer"] is False
    assert [grant["name"] for grant in shown["permissions"]] == ["tasks", "attempts", "usage"]


def test_a_reviewers_agent_follows_its_approvers_role_at_each_call(service):
    add(service, "bee")
    _client, tokens = connect(service, sign_in_as(service, "ada"))
    access = tokens["access_token"]
    assert "list_tasks" in tool_names(service, access)
    set_role(service, "ada", REVIEWER)
    assert sorted(tool_names(service, access)) == sorted(REVIEWER_TOOLS)
    assert call_tool(service, access, "list_tasks")["content"][0]["text"] == "This needs an admin's approval."
    set_role(service, "ada", ADMIN)
    assert "list_tasks" in tool_names(service, access)
    assert tool_answer(service, access, "list_tasks") == {"tasks": [{"type": "worksheet", "name": "worksheet-1"}]}


def test_a_reviewer_cannot_approve_an_agent_with_nothing_to_use_but_can_deny(service):
    ada = sign_in_as(service, "ada")
    permissions = page(service, ada)["settings"]["permissions"]
    permissions["attempts"] = []
    permissions["usage"] = []
    assert save(service, ada, permissions=permissions)[0] == 200
    add(service, "nana", REVIEWER)
    nana = sign_in_as(service, "nana")
    location = authorize(service, register(service))
    shown = consent(service, nana, location)
    assert (shown["reviewer"], shown["permissions"]) == (True, [])
    status, answer = decide(service, nana, location, "approve")
    assert status == 400
    assert "nothing a reviewer's agent could use" in answer["error"]
    status, answer = decide(service, nana, location, "deny")
    assert status == 200
    assert "error=access_denied" in answer["location"]


def test_a_reviewers_agent_gets_no_reads_mcp_yaml_does_not_grant(service):
    ada = sign_in_as(service, "ada")
    permissions = page(service, ada)["settings"]["permissions"]
    permissions["usage"] = []
    assert save(service, ada, permissions=permissions)[0] == 200
    add(service, "nana", REVIEWER)
    _client, tokens = connect(service, sign_in_as(service, "nana"))
    access = tokens["access_token"]
    assert sorted(tool_names(service, access)) == sorted(["list_attempts", "get_task_trend", "get_arithmetic_facts", "get_spelling_words", "get_attempt"])
    assert call_tool(service, access, "get_usage")["content"][0]["text"] == "This needs usage: read."
