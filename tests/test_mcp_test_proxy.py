"""S041: the test_proxy_request tool answers what the proxy would do, from a stated fixture, and leaves no trace."""

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import test_mcp_server as base  # noqa: E402
from asgi import call  # noqa: E402
from test_mcp_server import activity, at, service, call_tool, connect, page, save, sign_in, tool_answer, tool_names  # noqa: E402,F401,F811

HOUSE = """\
timezone: Australia/Sydney
entry: entry
bucket_length: 3m
client_groups:
  younger:
    addresses: ["192.0.2.40"]
site_groups:
  game:
    priority: 10
    patterns: ["*.game.example"]
  fun:
    priority: 20
    patterns: ["*.fun.example"]
  video:
    priority: 30
    patterns: ["*.video.example"]
time_windows:
  evening:
    periods:
      - start: "17:00"
        end: "19:00"
quotas:
  screen:
    time: 1h
    bytes: 1M
    ruleset: entry
rule_sets:
  entry:
    - condition: site_group
      group: game
      when_true:
        action: evaluate
        rules:
          - condition: time_window
            window: evening
            when_true: { action: allow }
            when_false: { action: deny, message: "the evening window has ended." }
    - condition: site_group
      group: fun
      when_true: { action: evaluate, ruleset: revise }
    - condition: site_group
      group: video
      when_true: { action: evaluate, ruleset: metered }
  revise:
    - condition: tasks_required
      required: 2
      when_true: { action: allow }
      when_false: { action: redirect, location: revision_task }
  metered:
    - condition: time_remaining
      quota: screen
      when_true:
        action: evaluate
        rules:
          - condition: volume_remaining
            quota: screen
            when_true: { action: allow }
            when_false: { action: deny, message: "No data left." }
      when_false: { action: deny, message: "Time is up." }
"""
KID = {"client_ip": "192.0.2.40", "method": "GET"}
GAME = {**KID, "url": "https://www.game.example/"}
FUN = {**KID, "url": "https://www.fun.example/"}
VIDEO = {**KID, "url": "https://www.video.example/"}
SATURDAY = "2026-11-14"


@pytest.fixture
def house(monkeypatch):
    monkeypatch.setattr(base, "HOUSE", HOUSE)


@pytest.fixture
def agent(house, service):
    cookie = sign_in(service)
    permissions = page(service, cookie)["settings"]["permissions"]
    permissions["rule_sets"] = ["read"]
    assert save(service, cookie, permissions=permissions)[0] == 200
    _client, tokens = connect(service, cookie)
    return service, cookie, tokens["access_token"]


def ask(agent, **arguments):
    app, _cookie, access = agent
    return tool_answer(app, access, "test_proxy_request", arguments)


def refused(agent, **arguments):
    app, _cookie, access = agent
    result = call_tool(app, access, "test_proxy_request", arguments)
    assert result["isError"] is True
    return result["content"][0]["text"]


def test_the_tool_needs_rule_sets_read_and_a_refusal_is_logged(agent):
    app, cookie, access = agent
    assert "test_proxy_request" in tool_names(app, access)
    ask(agent, **GAME, at=f"{SATURDAY}T17:30")
    assert [entry["outcome"] for entry in activity(app, cookie)] == ["approved"]
    permissions = page(app, cookie)["settings"]["permissions"]
    permissions["rule_sets"] = []
    assert save(app, cookie, permissions=permissions)[0] == 200
    assert "test_proxy_request" not in tool_names(app, access)
    assert refused(agent, **GAME) == "This needs rule_sets: read."
    entry = activity(app, cookie)[0]
    assert (entry["tool"], entry["outcome"]) == ("test_proxy_request", "refused")


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"client_ip": "not-an-ip"}, "client_ip must be an IP address"),
        ({"url": None}, "url is required"),
        ({"at": "last Tuesday"}, "ISO 8601"),
        ({"quotas": {"nope": {"seconds_used": 1}}}, "There is no quota named nope. The policy's quotas are screen."),
        ({"tasks_completed": -1}, "tasks_completed"),
    ],
)
def test_a_bad_argument_is_refused_with_its_reason(agent, changes, message):
    assert message in refused(agent, **{**GAME, **changes})


def test_the_time_decides_and_is_named_in_household_time(agent):
    early = ask(agent, **GAME, at=f"{SATURDAY}T16:30")
    assert early["action"] == "deny" and early["local_time"] == f"{SATURDAY} 16:30:00"
    inside = ask(agent, **GAME, at=f"{SATURDAY}T17:30")
    late = ask(agent, **GAME, at=f"{SATURDAY}T19:30")
    assert inside["action"] == "allow"
    assert (late["action"], late["status"], late["message"]) == ("deny", 403, "the evening window has ended.")
    assert late["summary"] == "Blocked with 403: the evening window has ended."
    assert (late["client_group"], late["site_group"]) == ("younger", "game")
    assert (late["rule_set"], late["rule_index"]) == ("entry rule 1 when_true", 1)
    # 06:30 UTC on Saturday is 17:30 in Sydney, inside the window.
    utc = ask(agent, **GAME, at=f"{SATURDAY}T06:30:00+00:00")
    assert utc["action"] == "allow" and utc["local_time"] == f"{SATURDAY} 17:30:00"


def test_an_allow_says_when_it_would_be_looked_at_again(agent):
    found = ask(agent, **GAME, at=f"{SATURDAY}T17:30")
    assert found["recheck_at"].startswith(f"{SATURDAY} 19:05")
    assert "19:05" in found["summary"]
    assert ask(agent, **{**FUN, "at": f"{SATURDAY}T10:00", "tasks_completed": 2})["recheck_at"] == "2026-11-15 00:05:00"


def test_unclassified_addresses_and_sites_are_default_and_an_unmatched_request_names_no_rule(agent):
    found = ask(agent, client_ip="198.51.100.9", method="GET", url="https://elsewhere.example/")
    assert (found["client_group"], found["site_group"]) == ("default", "default")
    assert found["rule_set"] is None and found["rule_index"] is None
    assert found["summary"].startswith("No rule matched")


def test_tasks_completed_decides_and_defaults_to_zero(agent):
    for given, action in ((None, "redirect"), (1, "redirect"), (2, "allow"), (5, "allow")):
        extra = {} if given is None else {"tasks_completed": given}
        assert ask(agent, **FUN, **extra)["action"] == action
    found = ask(agent, **FUN)
    assert found["status"] == 302 and found["location"].endswith("/tasks/next")
    assert found["rule_set"] == "revise"


def test_quota_balances_decide_at_the_limit(agent):
    def run(**used):
        return ask(agent, **VIDEO, quotas={"screen": used})

    assert run(seconds_used=3599)["action"] == "allow"
    assert run(seconds_used=3600)["message"] == "Time is up."
    assert run(seconds_used=0, bytes_used=1048575)["action"] == "allow"
    found = run(bytes_used=1048576)
    assert found["message"] == "No data left." and found["rule_set"] == "metered rule 1 when_true"
    assert ask(agent, **VIDEO)["action"] == "allow"


def test_nothing_is_recorded_and_the_real_decision_path_ignores_the_fixture(agent):
    app, _cookie, _access = agent
    database = Path(app.state.database)
    log = database.parent / "decisions.jsonl"

    def snapshot():
        connection = sqlite3.connect(database)
        try:
            tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            return {name: connection.execute(f'SELECT * FROM "{name}"').fetchall() for name in tables if not name.startswith(("mcp", "sqlite"))}
        finally:
            connection.close()

    before = snapshot()
    log_before = log.read_text() if log.exists() else ""
    assert ask(agent, **FUN, tasks_completed=5)["action"] == "allow"
    assert ask(agent, **VIDEO, quotas={"screen": {"seconds_used": 9999}}, at=f"{SATURDAY}T03:00")["action"] == "deny"
    assert ask(agent, **FUN)["action"] == "redirect"
    assert snapshot() == before
    assert (log.read_text() if log.exists() else "") == log_before

    at(app, datetime(2026, 11, 14, 6, 30, tzinfo=timezone.utc))
    body = {**FUN, "tasks_completed": 5, "quotas": {"screen": {"seconds_used": 9999}}, "at": "2020-01-01T00:00"}
    status, answer, _headers = call(app, "POST", "/v1/decisions", json_body=body)
    assert status == 200 and json.loads(answer)["action"] == "redirect"
    gate = {**GAME, "at": f"{SATURDAY}T03:00", "occurred_at": f"{SATURDAY}T17:30:00+11:00"}
    status, answer, _headers = call(app, "POST", "/v1/decisions", json_body=gate)
    assert json.loads(answer)["action"] == "allow"


def test_the_answer_is_the_one_the_proxy_gives(agent):
    app, _cookie, _access = agent
    moment = f"{SATURDAY}T19:30:00+11:00"
    for request in (GAME, FUN, VIDEO, {"client_ip": "198.51.100.9", "method": "GET", "url": "https://x.example/"}):
        _status, answer, _headers = call(app, "POST", "/v1/decisions", json_body={**request, "occurred_at": moment})
        proxy = json.loads(answer)
        tested = ask(agent, **request, at=moment)
        assert {key: tested[key] for key in proxy} == proxy
