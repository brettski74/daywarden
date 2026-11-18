"""S036.1: the MCP server, its OAuth sign-in, the MCP page's data, and the read tools."""

import base64
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from asgi import call, session_cookie  # noqa: E402
from policy.accounts import Accounts  # noqa: E402
from policy.store import PolicyStore  # noqa: E402

PASSWORD = "s3cret-pass"
ZONE = ZoneInfo("Australia/Sydney")
ORIGIN = "https://garden:8084"
ENDPOINT = ORIGIN + "/mcp"
REDIRECT = "http://localhost:43123/callback"
VERIFIER = "v" * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")
HOUSE = """\
timezone: Australia/Sydney
entry: entry
bucket_length: 3m
client_groups:
  younger:
    addresses: ["192.0.2.40"]
site_groups:
  school:
    priority: 10
    patterns: ["*.school.example"]
time_windows:
  bedtime:
    periods:
      - start: "20:00"
        end: "07:00+1"
        days: monday-friday
quotas:
  fun:
    time: 45m
    ruleset: entry
tasks:
  worksheet:
    worksheet-1:
      group: younger
      pass_cooldown: 0
rule_sets:
  entry:
    - condition: always
      when_true: { action: allow }
"""
MCP_FILE = """\
# Agents for the household.
enabled: true   # on
access_token: 1h
permissions:
  tasks: [read]  # tasks only
  attempts: [read]
  usage: [read]
"""


@pytest.fixture
def service(tmp_path, monkeypatch):
    """The decisions app, a parent account, a policy, and an MCP server that is on."""
    pytest.importorskip("mcp")
    from policy.app import create_app

    built = tmp_path / "dist"
    built.mkdir()
    (built / "index.html").write_text("<!DOCTYPE html><title>Daywarden</title>", encoding="utf-8")
    config = tmp_path / "config"
    config.mkdir()
    (config / "policy.yaml").write_text(HOUSE, encoding="utf-8")
    (config / "mcp.yaml").write_text(MCP_FILE, encoding="utf-8")
    database = tmp_path / "policy.sqlite3"
    monkeypatch.setenv("POLICY_FILE", str(config / "policy.yaml"))
    monkeypatch.setenv("POLICY_DB", str(database))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    monkeypatch.setenv("PORTAL_DIR", str(built))
    monkeypatch.setenv("PARENT_NAMES", "garden,localhost")
    monkeypatch.setenv("POLICY_PORT", "8084")
    monkeypatch.delenv("MCP_FILE", raising=False)
    with PolicyStore(database) as store:
        Accounts(store.connection).set_password("ada", PASSWORD)
    holder = {}

    def make():
        app = create_app()
        app.state.config = config
        app.state.database = database
        holder["app"] = app
        return app

    app = make()
    app.state.remake = make
    return app


def at(app, moment: datetime) -> None:
    """Set the household clock to moment."""
    from policy.app import Loaded
    from policy.clock import HouseholdClock

    now = app.state.holder.loaded
    app.state.holder.loaded = Loaded(now.policy, HouseholdClock(ZONE, now=lambda: moment), now.source)


def sign_in(app) -> str:
    _status, _body, headers = call(app, "POST", "/parent/api/login", json_body={"username": "ada", "password": PASSWORD})
    return session_cookie(headers)


def register(app, **extra) -> str:
    status, body, _headers = call(
        app, "POST", "/oauth/register", json_body={"client_name": "Claude Code", "redirect_uris": [REDIRECT], **extra}
    )
    assert status == 201, body
    return json.loads(body)["client_id"]


def authorize(app, registered: str, **changes) -> str:
    """Start an authorization request and return the consent page address it sends the browser to."""
    asked = {
        "response_type": "code",
        "client_id": registered,
        "redirect_uri": REDIRECT,
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        "state": "xyz",
        "resource": ENDPOINT,
        **changes,
    }
    asked = {key: value for key, value in asked.items() if value is not None}
    status, _body, headers = call(app, "GET", "/oauth/authorize", query=urlencode(asked))
    assert status == 302
    location = headers["location"][0]
    assert location.startswith("/parent/settings/mcp/connect?request=")
    return location


def request_id(location: str) -> str:
    return parse_qs(urlsplit(location).query)["request"][0]


def consent(app, cookie: str, location: str) -> dict:
    status, body, _headers = call(app, "GET", "/parent/api/settings/mcp/connect", query=f"request={request_id(location)}", cookie=cookie)
    assert status == 200
    return json.loads(body)


def decide(app, cookie: str, location: str, decision: str) -> tuple[int, dict]:
    status, body, _headers = call(
        app, "POST", "/parent/api/settings/mcp/connect", json_body={"request": request_id(location), "decision": decision}, cookie=cookie
    )
    return status, json.loads(body)


def token(app, **form) -> tuple[int, dict]:
    status, body, headers = call(app, "POST", "/oauth/token", body=urlencode(form).encode(), content_type="application/x-www-form-urlencoded")
    assert headers["cache-control"] == ["no-store"]
    return status, json.loads(body)


def exchange(app, client_id: str, code: str) -> tuple[int, dict]:
    return token(
        app, grant_type="authorization_code", code=code, client_id=client_id, redirect_uri=REDIRECT,
        code_verifier=VERIFIER, resource=ENDPOINT,
    )


def connect(app, cookie: str | None = None) -> tuple[str, dict]:
    """Register, approve, and exchange the code. Return the client id and the tokens."""
    cookie = cookie or sign_in(app)
    client_id = register(app)
    location = authorize(app, client_id)
    status, decided = decide(app, cookie, location, "approve")
    assert status == 200, decided
    code = parse_qs(urlsplit(decided["location"]).query)["code"][0]
    status, tokens = exchange(app, client_id, code)
    assert status == 200, tokens
    return client_id, tokens


def mcp(app, access: str | None, method: str, params: dict | None = None, *, headers: dict | None = None, cookie=None):
    sent = {"accept": "application/json, text/event-stream", "mcp-protocol-version": "2025-06-18", **(headers or {})}
    if access is not None:
        sent["authorization"] = f"Bearer {access}"
    message = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        message["params"] = params
    return call(app, "POST", "/mcp", json_body=message, headers=sent, cookie=cookie)


def tool_names(app, access: str) -> list[str]:
    status, body, _headers = mcp(app, access, "tools/list")
    assert status == 200, body
    return [tool["name"] for tool in json.loads(body)["result"]["tools"]]


def call_tool(app, access: str, name: str, arguments: dict | None = None) -> dict:
    status, body, _headers = mcp(app, access, "tools/call", {"name": name, "arguments": arguments or {}})
    assert status == 200, body
    return json.loads(body)["result"]


def tool_answer(app, access: str, name: str, arguments: dict | None = None):
    result = call_tool(app, access, name, arguments)
    assert result["isError"] is False, result
    return json.loads(result["content"][0]["text"])


def page(app, cookie: str) -> dict:
    status, body, _headers = call(app, "GET", "/parent/api/settings/mcp", cookie=cookie)
    assert status == 200
    return json.loads(body)


def save(app, cookie: str, **settings) -> tuple[int, dict]:
    shown = page(app, cookie)
    status, body, _headers = call(
        app, "POST", "/parent/api/settings/mcp", json_body={"version": shown["version"], "settings": {**shown["settings"], **settings}}, cookie=cookie
    )
    return status, json.loads(body)


def activity(app, cookie: str) -> list[dict]:
    status, body, _headers = call(app, "GET", "/parent/api/settings/mcp/activity", cookie=cookie)
    assert status == 200
    return json.loads(body)["entries"]


# The server off

OFF_ADDRESSES = (
    ("POST", "/mcp"),
    ("GET", "/.well-known/oauth-protected-resource/mcp"),
    ("GET", "/.well-known/oauth-authorization-server"),
    ("POST", "/oauth/register"),
    ("GET", "/oauth/authorize"),
    ("POST", "/oauth/token"),
    ("POST", "/oauth/revoke"),
)


@pytest.mark.parametrize("file_text", [None, "enabled: false\n"])
def test_with_no_file_or_turned_off_every_address_answers_404(service, file_text):
    mcp_file = service.state.config / "mcp.yaml"
    if file_text is None:
        mcp_file.unlink()
    else:
        mcp_file.write_text(file_text, encoding="utf-8")
    app = service.state.remake()
    for method, path in OFF_ADDRESSES:
        assert call(app, method, path, json_body={})[0] == 404, path
    shown = page(app, sign_in(app))
    assert shown["on"] is False
    assert shown["exists"] is (file_text is not None)


def test_turning_on_with_no_file_gives_read_on_every_class(service):
    (service.state.config / "mcp.yaml").unlink()
    app = service.state.remake()
    cookie = sign_in(app)
    shown = page(app, cookie)
    assert shown["settings"]["enabled"] is False
    assert all(granted == ["read"] for granted in shown["settings"]["permissions"].values())
    status, saved = save(app, cookie, enabled=True)
    assert status == 200, saved
    written = (service.state.config / "mcp.yaml").read_text(encoding="utf-8")
    assert "enabled: true" in written
    assert page(app, cookie)["on"] is True
    _client, tokens = connect(app, cookie)
    assert "get_household" in tool_names(app, tokens["access_token"])
    assert "list_requests" in tool_names(app, tokens["access_token"])


def test_a_file_with_problems_leaves_the_server_off_and_the_page_lists_them(service):
    (service.state.config / "mcp.yaml").write_text("permissions:\n  site_group: [read]\n  attempts: [update]\naccess_token: 0h\n", encoding="utf-8")
    app = service.state.remake()
    assert call(app, "POST", "/mcp", json_body={})[0] == 404
    shown = page(app, sign_in(app))
    assert shown["on"] is False
    assert len(shown["problems"]) == 3
    assert any("site_group is not a permission class" in problem for problem in shown["problems"])
    assert any("update is not a permission attempts has" in problem for problem in shown["problems"])
    assert any("0h is not a duration" in problem for problem in shown["problems"])


def test_dw_check_reports_each_problem_in_mcp_yaml(service, monkeypatch, capsys):
    from policy import check

    monkeypatch.setenv("POLICY_FILE", str(service.state.config / "policy.yaml"))
    (service.state.config / "mcp.yaml").write_text("permissions:\n  site_group: [read]\n  attempts: [update]\nrefresh_idle: 0h\n", encoding="utf-8")
    assert check.main([]) == 1
    err = capsys.readouterr().err
    assert "dw: the policy has 3 errors." in err
    assert "site_group is not a permission class" in err
    assert "attempts: update is not a permission attempts has" in err
    assert "refresh_idle: 0h is not a duration" in err

    (service.state.config / "mcp.yaml").write_text(MCP_FILE, encoding="utf-8")
    assert check.main([]) == 0
    assert "MCP server is on" in capsys.readouterr().out


def test_reload_applies_a_hand_edit_and_refuses_a_broken_one(service):
    app = service
    _client, tokens = connect(app)
    access = tokens["access_token"]
    mcp_file = service.state.config / "mcp.yaml"

    mcp_file.write_text(MCP_FILE.replace("attempts: [read]", "attempts: [update]"), encoding="utf-8")
    status, body, _headers = call(app, "POST", "/v1/reload", scheme="http")
    answer = json.loads(body)
    assert answer["reloaded"] is False
    assert any("update is not a permission attempts has" in error for error in answer["errors"])
    assert "list_attempts" in tool_names(app, access)

    mcp_file.write_text(MCP_FILE.replace("  attempts: [read]\n", ""), encoding="utf-8")
    status, body, _headers = call(app, "POST", "/v1/reload", scheme="http")
    assert json.loads(body)["reloaded"] is True
    assert "list_attempts" not in tool_names(app, access)


# Connecting


def test_metadata_names_the_resource_and_the_authorization_server(service):
    status, body, _headers = call(service, "GET", "/.well-known/oauth-protected-resource/mcp", headers={"host": "garden:8443"})
    assert status == 200
    assert json.loads(body) == {
        "resource": ENDPOINT,
        "authorization_servers": [ORIGIN],
        "bearer_methods_supported": ["header"],
        "resource_name": "Daywarden",
    }
    status, body, _headers = call(service, "GET", "/.well-known/oauth-authorization-server", headers={"host": "garden"})
    found = json.loads(body)
    assert found["issuer"] == ORIGIN
    assert found["token_endpoint"] == ORIGIN + "/oauth/token"
    assert found["code_challenge_methods_supported"] == ["S256"]
    assert found["grant_types_supported"] == ["authorization_code", "refresh_token"]
    # Another parent name the agent used is kept, so the issuer matches what it fetched.
    status, body, _headers = call(service, "GET", "/.well-known/oauth-authorization-server", headers={"host": "localhost:8443"})
    assert json.loads(body)["issuer"] == "https://localhost:8084"


def test_mcp_with_no_token_answers_401_naming_the_resource_metadata(service):
    for access in (None, "0" * 64, "not a token"):
        status, _body, headers = mcp(service, access, "tools/list", headers={"host": "garden:8443"})
        assert status == 401
        assert headers["www-authenticate"] == [f'Bearer resource_metadata="{ORIGIN}/.well-known/oauth-protected-resource/mcp"']


def test_an_approved_agent_initializes_and_lists_its_tools(service):
    cookie = sign_in(service)
    client_id = register(service)
    location = authorize(service, client_id)
    shown = consent(service, cookie, location)
    assert shown["agent"] == "Claude Code"
    assert shown["client_id"] == client_id
    assert shown["redirect_uri"] == REDIRECT
    assert shown["problem"] is None
    assert shown["permissions"] == [
        {"name": "tasks", "permissions": ["read"]},
        {"name": "attempts", "permissions": ["read"]},
        {"name": "usage", "permissions": ["read"]},
    ]
    status, decided = decide(service, cookie, location, "approve")
    assert status == 200
    sent = urlsplit(decided["location"])
    assert f"{sent.scheme}://{sent.netloc}{sent.path}" == REDIRECT
    returned = parse_qs(sent.query)
    assert returned["state"] == ["xyz"]
    status, tokens = exchange(service, client_id, returned["code"][0])
    assert status == 200
    assert tokens["token_type"] == "Bearer"
    assert tokens["expires_in"] == 3600
    assert len(tokens["access_token"]) == 64 and len(tokens["refresh_token"]) == 64

    status, body, _headers = mcp(
        service, tokens["access_token"], "initialize",
        {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
    )
    assert status == 200
    assert json.loads(body)["result"]["serverInfo"]["name"] == "daywarden"
    assert tool_names(service, tokens["access_token"]) == [
        "list_tasks", "get_task", "list_attempts", "get_task_trend", "get_arithmetic_facts", "get_attempt", "get_usage", "list_requests",
    ]
    assert [entry["outcome"] for entry in activity(service, cookie)] == ["approved"]


def test_loading_the_consent_page_approves_nothing_and_deny_returns_access_denied(service):
    cookie = sign_in(service)
    client_id = register(service)
    location = authorize(service, client_id)
    consent(service, cookie, location)
    assert page(service, cookie)["connections"] == []
    status, decided = decide(service, cookie, location, "deny")
    assert status == 200
    returned = parse_qs(urlsplit(decided["location"]).query)
    assert returned["error"] == ["access_denied"]
    assert "code" not in returned
    assert decide(service, cookie, location, "approve")[0] == 400


def test_the_consent_page_needs_a_session(service):
    location = authorize(service, register(service))
    status, _body, _headers = call(service, "GET", "/parent/api/settings/mcp/connect", query=f"request={request_id(location)}")
    assert status == 401


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({"code_challenge_method": None}, "PKCE with S256"),
        ({"code_challenge_method": "plain"}, "PKCE with S256"),
        ({"code_challenge": None}, "PKCE with S256"),
        ({"redirect_uri": "http://localhost:9/elsewhere"}, "did not register"),
        ({"resource": "https://elsewhere:8084/mcp"}, "resource"),
        ({"client_id": "nobody"}, "not registered"),
    ],
)
def test_a_bad_request_shows_the_problem_and_sends_the_browser_nowhere(service, changes, problem):
    cookie = sign_in(service)
    location = authorize(service, register(service), **changes)
    shown = consent(service, cookie, location)
    assert problem in shown["problem"]
    status, refused = decide(service, cookie, location, "approve")
    assert status == 400
    assert "location" not in refused


def test_an_unknown_request_id_shows_the_problem(service):
    cookie = sign_in(service)
    shown = consent(service, cookie, "/parent/settings/mcp/connect?request=nonsense")
    assert "not known" in shown["problem"]
    assert "agent" not in shown


def test_the_consent_page_cannot_be_framed(service):
    status, _body, headers = call(service, "GET", "/parent/settings/mcp/connect", query="request=abc")
    assert status == 200
    assert headers["content-security-policy"] == ["frame-ancestors 'none'"]


def test_a_code_works_once_and_a_second_use_ends_its_connection(service):
    cookie = sign_in(service)
    client_id = register(service)
    _status, decided = decide(service, cookie, authorize(service, client_id), "approve")
    code = parse_qs(urlsplit(decided["location"]).query)["code"][0]
    status, tokens = exchange(service, client_id, code)
    assert status == 200
    assert len(page(service, cookie)["connections"]) == 1
    status, refused = exchange(service, client_id, code)
    assert status == 400 and refused["error"] == "invalid_grant"
    assert page(service, cookie)["connections"] == []
    assert mcp(service, tokens["access_token"], "tools/list")[0] == 401


def test_a_code_lasts_one_minute(service):
    start = datetime(2026, 11, 17, 9, 0, tzinfo=ZONE)
    at(service, start)
    cookie = sign_in(service)
    client_id = register(service)
    _status, decided = decide(service, cookie, authorize(service, client_id), "approve")
    code = parse_qs(urlsplit(decided["location"]).query)["code"][0]
    at(service, start + timedelta(seconds=61))
    status, refused = exchange(service, client_id, code)
    assert status == 400 and "expired" in refused["error_description"]


def test_a_code_needs_the_right_verifier(service):
    cookie = sign_in(service)
    client_id = register(service)
    _status, decided = decide(service, cookie, authorize(service, client_id), "approve")
    code = parse_qs(urlsplit(decided["location"]).query)["code"][0]
    status, refused = token(
        service, grant_type="authorization_code", code=code, client_id=client_id, redirect_uri=REDIRECT, code_verifier="w" * 64
    )
    assert status == 400 and refused["error"] == "invalid_grant"


def test_refreshing_keeps_the_agent_working_and_an_old_refresh_token_ends_the_connection(service):
    (service.state.config / "mcp.yaml").write_text(MCP_FILE.replace("access_token: 1h", "access_token: 2m"), encoding="utf-8")
    app = service.state.remake()
    start = datetime(2026, 11, 17, 9, 0, tzinfo=ZONE)
    at(app, start)
    client_id, tokens = connect(app)
    at(app, start + timedelta(minutes=3))
    assert mcp(app, tokens["access_token"], "tools/list")[0] == 401
    status, fresh = token(app, grant_type="refresh_token", refresh_token=tokens["refresh_token"], client_id=client_id)
    assert status == 200
    assert fresh["refresh_token"] != tokens["refresh_token"]
    assert fresh["expires_in"] == 120
    assert mcp(app, fresh["access_token"], "tools/list")[0] == 200

    status, refused = token(app, grant_type="refresh_token", refresh_token=tokens["refresh_token"], client_id=client_id)
    assert status == 400 and refused["error"] == "invalid_grant"
    assert mcp(app, fresh["access_token"], "tools/list")[0] == 401
    status, _refused = token(app, grant_type="refresh_token", refresh_token=fresh["refresh_token"], client_id=client_id)
    assert status == 400


def test_a_connection_unused_for_refresh_idle_lapses(service):
    (service.state.config / "mcp.yaml").write_text(MCP_FILE + "refresh_idle: 5m\n", encoding="utf-8")
    app = service.state.remake()
    start = datetime(2026, 11, 17, 9, 0, tzinfo=ZONE)
    at(app, start)
    client_id, tokens = connect(app)
    at(app, start + timedelta(minutes=4))
    assert mcp(app, tokens["access_token"], "tools/list")[0] == 200
    at(app, start + timedelta(minutes=9, seconds=1))
    assert mcp(app, tokens["access_token"], "tools/list")[0] == 401
    status, _refused = token(app, grant_type="refresh_token", refresh_token=tokens["refresh_token"], client_id=client_id)
    assert status == 400
    entries = activity(app, sign_in(app))
    assert entries[0]["outcome"] == "lapsed"
    assert entries[0]["at"] == "2026-11-17 09:09:00"


def test_a_connection_used_every_minute_still_lapses_at_refresh_lifetime(service):
    (service.state.config / "mcp.yaml").write_text(MCP_FILE + "refresh_lifetime: 10m\n", encoding="utf-8")
    app = service.state.remake()
    start = datetime(2026, 11, 17, 9, 0, tzinfo=ZONE)
    at(app, start)
    client_id, tokens = connect(app)
    refresh = tokens["refresh_token"]
    for minute in range(1, 10):
        at(app, start + timedelta(minutes=minute))
        status, fresh = token(app, grant_type="refresh_token", refresh_token=refresh, client_id=client_id)
        assert status == 200
        refresh = fresh["refresh_token"]
    at(app, start + timedelta(minutes=10, seconds=1))
    status, _refused = token(app, grant_type="refresh_token", refresh_token=refresh, client_id=client_id)
    assert status == 400
    assert mcp(app, fresh["access_token"], "tools/list")[0] == 401


def test_the_session_cookie_is_not_accepted_at_mcp_nor_a_token_under_parent_api(service):
    cookie = sign_in(service)
    _client, tokens = connect(service, cookie)
    assert mcp(service, None, "tools/list", cookie=cookie)[0] == 401
    status, _body, _headers = call(service, "GET", "/parent/api/tasks", headers={"authorization": f"Bearer {tokens['access_token']}"})
    assert status == 401


def test_another_origin_is_refused(service):
    _client, tokens = connect(service)
    assert mcp(service, tokens["access_token"], "tools/list", headers={"origin": "https://evil.example"})[0] == 403
    assert mcp(service, tokens["access_token"], "tools/list", headers={"origin": ORIGIN})[0] == 200


def test_get_and_delete_open_no_stream(service):
    _client, tokens = connect(service)
    auth = {"authorization": f"Bearer {tokens['access_token']}"}
    assert call(service, "GET", "/mcp", headers=auth)[0] == 405
    assert call(service, "DELETE", "/mcp", headers=auth)[0] == 405


def test_revoking_a_refresh_token_at_the_revocation_endpoint_ends_the_connection(service):
    _client, tokens = connect(service)
    status, _body, _headers = call(
        service, "POST", "/oauth/revoke", body=urlencode({"token": tokens["refresh_token"]}).encode(),
        content_type="application/x-www-form-urlencoded",
    )
    assert status == 200
    assert mcp(service, tokens["access_token"], "tools/list")[0] == 401


def test_an_unapproved_registration_is_removed_after_24_hours(service):
    start = datetime(2026, 11, 17, 9, 0, tzinfo=ZONE)
    at(service, start)
    client_id = register(service)
    at(service, start + timedelta(hours=25))
    cookie = sign_in(service)
    shown = consent(service, cookie, authorize(service, client_id))
    assert "not registered" in shown["problem"]


# Connections


def test_the_page_lists_connections_and_revoke_ends_one_at_once(service):
    start = datetime(2026, 11, 17, 9, 0, tzinfo=ZONE)
    at(service, start)
    cookie = sign_in(service)
    _client, tokens = connect(service, cookie)
    at(service, start + timedelta(minutes=50))
    assert mcp(service, tokens["access_token"], "tools/list")[0] == 200
    # The portal session's idle limit is shorter than this, unlike the connection's.
    cookie = sign_in(service)
    (listed,) = page(service, cookie)["connections"]
    assert listed["agent"] == "Claude Code"
    assert listed["parent"] == "ada"
    assert listed["approved"] == "2026-11-17 09:00"
    assert listed["last_used"] == "2026-11-17 09:50"
    assert listed["lapses"] == "2026-12-17 09:50"

    status, body, _headers = call(service, "POST", f"/parent/api/settings/mcp/connections/{listed['id']}/revoke", json_body={}, cookie=cookie)
    assert status == 200, body
    assert page(service, cookie)["connections"] == []
    assert mcp(service, tokens["access_token"], "tools/list")[0] == 401
    assert activity(service, cookie)[0]["outcome"] == "revoked"


def test_replacing_a_password_ends_the_connections_that_parent_approved(service):
    _client, tokens = connect(service)
    with PolicyStore(service.state.database) as store:
        Accounts(store.connection).set_password("ada", "new-pass")
    assert mcp(service, tokens["access_token"], "tools/list")[0] == 401


# Saving the MCP page


def test_a_save_writes_the_file_keeps_comments_and_applies_at_once(service):
    cookie = sign_in(service)
    _client, tokens = connect(service, cookie)
    permissions = page(service, cookie)["settings"]["permissions"]
    permissions["tasks"] = []
    permissions["household"] = ["read"]
    status, saved = save(service, cookie, permissions=permissions, access_token="2h")
    assert status == 200, saved
    written = (service.state.config / "mcp.yaml").read_text(encoding="utf-8")
    assert "# Agents for the household." in written
    assert "enabled: true   # on" in written
    assert "access_token: 2h" in written
    assert "tasks:" not in written
    assert "household: [read]" in written
    names = tool_names(service, tokens["access_token"])
    assert "get_household" in names and "list_tasks" not in names


def test_a_stale_or_refused_save_writes_nothing(service):
    cookie = sign_in(service)
    before = (service.state.config / "mcp.yaml").read_text(encoding="utf-8")
    status, body, _headers = call(
        service, "POST", "/parent/api/settings/mcp", json_body={"version": "old", "settings": page(service, cookie)["settings"]}, cookie=cookie
    )
    assert status == 409
    status, refused = save(service, cookie, access_token="0h", refresh_idle="soon")
    assert status == 400
    assert len(refused["errors"]) == 2
    assert (service.state.config / "mcp.yaml").read_text(encoding="utf-8") == before


def test_turning_the_server_off_ends_every_connection(service):
    cookie = sign_in(service)
    _client, tokens = connect(service, cookie)
    status, _saved = save(service, cookie, enabled=False)
    assert status == 200
    assert call(service, "POST", "/mcp", json_body={})[0] == 404
    status, _saved = save(service, cookie, enabled=True)
    assert status == 200
    assert mcp(service, tokens["access_token"], "tools/list")[0] == 401
    assert page(service, cookie)["connections"] == []


def test_a_save_is_committed_when_the_config_directory_keeps_a_history(service):
    import shutil
    import subprocess

    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    config = service.state.config
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "PATH": "/usr/bin:/bin"}
    subprocess.run(["git", "init", "-q", str(config)], check=True, env=env)
    subprocess.run(["git", "-C", str(config), "add", "-A"], check=True, env=env)
    subprocess.run(
        ["git", "-C", str(config), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "first"], check=True, env=env
    )
    status, _saved = save(service, sign_in(service), access_token="3h")
    assert status == 200
    log = subprocess.run(["git", "-C", str(config), "log", "--format=%an %s", "-1"], capture_output=True, text=True, env=env).stdout
    assert log.startswith("ada ") and "saved MCP settings" in log


# Tools


def test_a_tool_the_matrix_no_longer_allows_is_refused_and_logged(service):
    cookie = sign_in(service)
    _client, tokens = connect(service, cookie)
    assert tool_answer(service, tokens["access_token"], "list_tasks") == {"tasks": [{"type": "worksheet", "name": "worksheet-1"}]}
    permissions = page(service, cookie)["settings"]["permissions"]
    permissions["tasks"] = []
    assert save(service, cookie, permissions=permissions)[0] == 200
    result = call_tool(service, tokens["access_token"], "get_task", {"type": "worksheet", "name": "worksheet-1"})
    assert result["isError"] is True
    assert result["content"][0]["text"] == "This needs tasks: read."
    entry = activity(service, cookie)[0]
    assert (entry["agent"], entry["parent"], entry["tool"], entry["target"], entry["outcome"]) == (
        "Claude Code", "ada", "get_task", "worksheet/worksheet-1", "refused",
    )
    assert entry["reasons"] == ["This needs tasks: read."]


def test_reads_that_succeed_are_not_logged_and_old_entries_are_removed(service):
    start = datetime(2026, 11, 17, 9, 0, tzinfo=ZONE)
    at(service, start)
    cookie = sign_in(service)
    _client, tokens = connect(service, cookie)
    tool_answer(service, tokens["access_token"], "list_tasks")
    assert [entry["outcome"] for entry in activity(service, cookie)] == ["approved"]
    # The approval is older than activity_days and is removed. The lapse, 30 days after last use, is kept.
    at(service, start + timedelta(days=91))
    cookie = sign_in(service)
    assert [entry["outcome"] for entry in activity(service, cookie)] == ["lapsed"]


def test_list_attempts_and_get_usage_match_their_portal_pages(service):
    cookie = sign_in(service)
    _client, tokens = connect(service, cookie)
    access = tokens["access_token"]
    _status, body, _headers = call(service, "GET", "/parent/api/attempts", query="client=younger&range=past-month", cookie=cookie)
    assert tool_answer(service, access, "list_attempts", {"client": "younger", "period": "past_month"}) == json.loads(body)
    _status, body, _headers = call(service, "GET", "/parent/api/usage/minutes", query="range=today&by=client&line=younger", cookie=cookie)
    found = tool_answer(service, access, "get_usage", {"unit": "minutes", "period": "today", "by": "client", "line": "younger"})
    expected = json.loads(body)
    expected.pop("presets")
    assert found == expected
    _status, body, _headers = call(service, "GET", "/parent/api/usage/requests", query="range=past-week", cookie=cookie)
    expected = json.loads(body)
    expected.pop("presets")
    assert tool_answer(service, access, "list_requests") == expected


def test_get_arithmetic_facts_gives_the_facts_page_with_its_all_time_figures(service):
    from policy.tasks import AttemptStore, TaskKey

    now = datetime(2026, 11, 17, 18, 0, tzinfo=ZONE)
    at(service, now)
    questions = [
        {"run": 1, "m": 7, "n": 8, "question": "7 × 8 =", "expected": 56, "answer": answer, "outcome": outcome,
         "allowed_ms": 10_000, "taken_ms": 3000}
        for answer, outcome in (("56", "correct"), ("54", "incorrect"))
    ]
    with AttemptStore(service.state.database) as store:
        for days, asked in ((60, questions[:1]), (2, questions[1:])):
            started = now - timedelta(days=days)
            detail = {"settings": {"operation": "multiplication"}, "runs": [{"run": 1}], "questions": asked}
            store.record("younger", TaskKey("arithmetic", "times"), "abandoned", started, started_at=started, detail=detail)
    cookie = sign_in(service)
    _client, tokens = connect(service, cookie)
    found = tool_answer(service, tokens["access_token"], "get_arithmetic_facts", {"client": "younger", "operation": "multiplication", "period": "past_week"})
    _status, body, _headers = call(service, "GET", "/parent/api/attempts/facts/multiplication", query="client=younger&range=past-week", cookie=cookie)
    assert found == json.loads(body)
    fact = found["facts"]["facts"][0]
    assert (fact["asked"], fact["all_time"]["asked"], fact["all_time"]["run"], fact["all_time"]["weight"]) == (1, 2, 0, 4.333)
    assert found["slow"]["text"].startswith("Slow boost starts once 10 facts")


def test_a_custom_period_is_from_and_to(service):
    _client, tokens = connect(service)
    found = tool_answer(service, tokens["access_token"], "list_attempts", {"client": "younger", "from": "2026-11-01", "to": "2026-11-07"})
    assert found["view"]["range"] == "custom"
    assert found["days"] == {"from": "2026-11-01", "to": "2026-11-07"}
    result = call_tool(service, tokens["access_token"], "list_attempts", {"client": "younger", "from": "2026-11-01"})
    assert result["isError"] is True and "both from and to" in result["content"][0]["text"]


def test_the_policy_read_tools(service):
    cookie = sign_in(service)
    permissions = {name: ["read"] for name in page(service, cookie)["settings"]["permissions"] if name not in ("attempts", "usage")}
    permissions.update(attempts=[], usage=[])
    assert save(service, cookie, permissions=permissions)[0] == 200
    _client, tokens = connect(service, cookie)
    access = tokens["access_token"]
    at(service, datetime(2026, 11, 17, 9, 30, tzinfo=timezone.utc))
    household = tool_answer(service, access, "get_household")
    assert household == {
        "entry": "entry", "timezone": "Australia/Sydney", "bucket_length": "3m",
        "time_grace": "5m", "volume_grace": "1M", "host_retention": "30d", "request_retention": "30d",
        "proxy_configuration": {"direct": {"localhost": True, "plain_host_names": True, "policy_server": True, "local_subnets": True, "local_domains": True, "extra": []}},
        "date": "2026-11-17", "time": "20:30:00", "weekday": "tuesday",
    }
    assert tool_answer(service, access, "list_client_groups") == {"client_groups": [{"name": "younger", "addresses": ["192.0.2.40"]}]}
    assert tool_answer(service, access, "list_site_groups")["site_groups"] == [{"name": "school", "priority": 10, "patterns": ["*.school.example"]}]
    assert tool_answer(service, access, "list_time_windows")["time_windows"] == [
        {"name": "bedtime", "periods": [{"start": "20:00", "end": "07:00+1", "days": ["monday", "tuesday", "wednesday", "thursday", "friday"]}]}
    ]
    (quota,) = tool_answer(service, access, "list_quotas")["quotas"]
    assert quota["name"] == "fun" and quota["time"] == "45m" and quota["ruleset"] == "entry"
    rules = tool_answer(service, access, "list_rule_sets")["rule_sets"]
    assert rules[0]["rules"][0]["when_true"] == {"action": "allow"}
    task = tool_answer(service, access, "get_task", {"type": "worksheet", "name": "worksheet-1"})
    assert task["name"] == "worksheet-1" and task["groups"] == ["younger"]
    result = call_tool(service, access, "get_task", {"type": "worksheet", "name": "nope"})
    assert result["isError"] is True and "There is no worksheet task named nope" in result["content"][0]["text"]
    assert tool_answer(service, access, "list_sentence_pools") == {"pools": []}


def test_a_client_id_metadata_document_registers_the_agent(service, monkeypatch):
    from policy import mcp_server

    document_url = "https://agent.example/client.json"
    fetched = []

    def fetch(url):
        fetched.append(url)
        return "Document Agent", (REDIRECT,)

    monkeypatch.setattr(mcp_server, "_fetch_document", fetch)
    cookie = sign_in(service)
    location = authorize(service, document_url)
    shown = consent(service, cookie, location)
    assert fetched == [document_url]
    assert shown["agent"] == "Document Agent" and shown["client_id"] == document_url and shown["problem"] is None
    _status, decided = decide(service, cookie, location, "approve")
    code = parse_qs(urlsplit(decided["location"]).query)["code"][0]
    assert exchange(service, document_url, code)[0] == 200


def test_registration_refuses_a_return_address_off_this_machine_over_http(service):
    status, body, _headers = call(service, "POST", "/oauth/register", json_body={"redirect_uris": ["http://evil.example/cb"]})
    assert status == 400 and json.loads(body)["error"] == "invalid_redirect_uri"


def test_a_restart_with_the_server_off_still_needs_each_agent_approved_again(service):
    _client, tokens = connect(service)
    (service.state.config / "mcp.yaml").write_text(MCP_FILE.replace("enabled: true", "enabled: false"), encoding="utf-8")
    service.state.remake()
    (service.state.config / "mcp.yaml").write_text(MCP_FILE, encoding="utf-8")
    app = service.state.remake()
    assert mcp(app, tokens["access_token"], "tools/list")[0] == 401


def test_the_client_document_is_fetched_with_a_named_user_agent(monkeypatch):
    """claude.ai answers 403 to urllib's default Python-urllib user agent."""
    import io
    import urllib.request

    from policy import mcp_server

    document_url = "https://agent.example/client.json"
    sent = []

    def urlopen(request, timeout):
        sent.append(request)
        body = {"client_id": document_url, "client_name": "Document Agent", "redirect_uris": ["http://localhost/callback"]}
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert mcp_server._fetch_document(document_url) == ("Document Agent", ("http://localhost/callback",))
    agent = sent[0].get_header("User-agent")
    assert agent and not agent.startswith("Python-urllib")


def test_a_loopback_return_address_may_use_any_port(service, monkeypatch):
    """Claude Code registers http://localhost/callback and returns on a port it picks at run time (RFC 8252 7.3)."""
    from policy import mcp_server

    document_url = "https://agent.example/client.json"
    monkeypatch.setattr(mcp_server, "_fetch_document", lambda url: ("Document Agent", ("http://localhost/callback",)))
    cookie = sign_in(service)
    location = authorize(service, document_url)
    shown = consent(service, cookie, location)
    assert shown["problem"] is None and shown["redirect_uri"] == REDIRECT
    _status, decided = decide(service, cookie, location, "approve")
    assert decided["location"].startswith(REDIRECT + "?")
    code = parse_qs(urlsplit(decided["location"]).query)["code"][0]
    assert exchange(service, document_url, code)[0] == 200


@pytest.mark.parametrize("elsewhere", ["http://localhost:43123/elsewhere", "http://127.0.0.1:43123/callback", "https://localhost:43123/callback"])
def test_only_the_port_of_a_loopback_return_address_may_differ(service, monkeypatch, elsewhere):
    from policy import mcp_server

    monkeypatch.setattr(mcp_server, "_fetch_document", lambda url: ("Document Agent", ("http://localhost/callback",)))
    cookie = sign_in(service)
    location = authorize(service, "https://agent.example/client.json", redirect_uri=elsewhere)
    assert "did not register" in consent(service, cookie, location)["problem"]
