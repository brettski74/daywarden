"""S001.1 through S001.3: a decision request is tied to a client, local time, a site group, and that group's rules."""

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy.clients import Client, ClientDirectory
from policy.clock import HouseholdClock
from policy.decisions import answer, context_for, decide, household_decision, log_entry, parse_request
from policy.groups import SiteGroup, SiteGroups
from policy.rules import Action, Rule

SYDNEY = ZoneInfo("Australia/Sydney")
YOUNGER = Client(1, "Younger child", "192.168.1.40", ("192.168.1.40",))
ENTERTAINMENT = SiteGroup("Entertainment", 30, ("*.youtube.com",))
EVERYTHING_ELSE = SiteGroup("Everything else", 1000, (), default=True)


def _request(**overrides):
    document = {
        "client_ip": "192.168.1.40",
        "method": "GET",
        "url": "https://www.youtube.com/watch?v=abc",
        "occurred_at": "2026-10-19T12:59:59+00:00",
    }
    document.update(overrides)
    return {key: value for key, value in document.items() if value is not None}


def _context(document, clock=None, groups=(ENTERTAINMENT,)):
    clock = clock or HouseholdClock(SYDNEY)
    return context_for(parse_request(document), clock, ClientDirectory([YOUNGER]), SiteGroups(groups))


def test_an_enrolled_ip_gets_its_display_name():
    assert _context(_request()).client == YOUNGER


def test_an_unenrolled_ip_still_gets_a_context_without_a_client():
    context = _context(_request(client_ip="192.168.1.99"))
    assert context.client is None
    assert context.request.client_ip == "192.168.1.99"


def test_the_request_time_becomes_household_time_either_side_of_midnight():
    before = _context(_request(occurred_at="2026-10-19T12:59:59+00:00"))
    after = _context(_request(occurred_at="2026-10-19T13:00:00+00:00"))
    assert before.local_time.date() == date(2026, 10, 19)
    assert after.local_time.date() == date(2026, 10, 20)
    assert after.local_time == datetime(2026, 10, 20, tzinfo=SYDNEY)


def test_a_request_without_a_time_uses_the_service_clock():
    clock = HouseholdClock(SYDNEY, now=lambda: datetime(2026, 10, 19, 13, tzinfo=timezone.utc))
    context = _context(_request(occurred_at=None), clock)
    assert context.local_time == datetime(2026, 10, 20, tzinfo=SYDNEY)


@pytest.mark.parametrize(
    "document",
    [
        [],
        _request(client_ip=None),
        _request(client_ip="younger-child.lan"),
        _request(method=""),
        _request(url=None),
        _request(occurred_at="yesterday"),
        _request(occurred_at=12),
    ],
)
def test_malformed_requests_are_rejected(document):
    with pytest.raises(ValueError):
        parse_request(document)


def test_the_household_decision_is_read_from_the_file_each_time(tmp_path):
    path = tmp_path / "decision.json"
    assert household_decision(path) is None
    path.write_text('{"action": "allow"}')
    assert household_decision(path) == b'{"action": "allow"}'
    path.write_text('{"action": "deny", "status": 403, "message": "Bed."}')
    assert b"Bed." in household_decision(path)


def test_the_log_entry_names_the_client_and_its_local_time():
    document = _request()
    entry = log_entry(document, _context(document), b'{"action": "allow"}')
    assert entry == {
        "request": document,
        "client": "Younger child",
        "local_time": "2026-10-19T23:59:59+11:00",
        "group": "Entertainment",
        "decision": {"action": "allow"},
    }


def test_the_log_entry_for_an_unenrolled_ip_has_no_client():
    document = _request(client_ip="192.168.1.99")
    entry = log_entry(document, _context(document), b"not json")
    assert entry["client"] is None
    assert entry["decision"] == {"raw": "not json"}


def test_a_group_with_no_rules_is_denied():
    context = _context(_request())
    assert context.group == ENTERTAINMENT
    assert json.loads(decide(context)) == {
        "action": "deny",
        "status": 403,
        "message": "No rule allowed this request.",
    }


def test_decide_runs_the_rules_on_the_matching_group():
    allowed = SiteGroup(
        "Entertainment",
        30,
        ("*.youtube.com",),
        rules=(Rule("always", Action("allow"), Action("deny", "no")),),
    )
    context = _context(_request(), groups=(allowed,))
    assert json.loads(decide(context)) == {"action": "allow"}


def test_the_decision_file_is_used_only_when_the_stub_is_on(tmp_path):
    path = tmp_path / "decision.json"
    path.write_text('{"action": "allow"}')
    context = _context(_request())
    assert b"No rule allowed this request." in answer(context, path)
    assert answer(context, path, stub=True) == b'{"action": "allow"}'
    ungrouped = _context(_request(url="https://example.org/"))
    assert b"not in a configured group" in answer(ungrouped, path, stub=True)


def test_an_unrecognized_url_goes_to_the_default_group():
    context = _context(_request(url="https://example.org/"), groups=(ENTERTAINMENT, EVERYTHING_ELSE))
    assert context.group == EVERYTHING_ELSE
    assert json.loads(decide(context))["message"] == "No rule allowed this request."


def test_without_a_default_group_an_unrecognized_url_is_denied():
    document = _request(url="https://example.org/")
    context = _context(document)
    decision = decide(context)
    assert json.loads(decision) == {
        "action": "deny",
        "status": 403,
        "message": "This site is not in a configured group.",
    }
    assert log_entry(document, context, decision)["group"] is None
