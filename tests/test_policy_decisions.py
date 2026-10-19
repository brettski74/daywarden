"""S001.1: a decision request is tied to a client, when there is one, and to local time."""

import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy.clients import Client, ClientDirectory
from policy.clock import HouseholdClock
from policy.decisions import context_for, household_decision, log_entry, parse_request

SYDNEY = ZoneInfo("Australia/Sydney")
YOUNGER = Client(1, "Younger child", "192.168.1.40", ("192.168.1.40",))


def _request(**overrides):
    document = {
        "client_ip": "192.168.1.40",
        "method": "GET",
        "url": "https://www.youtube.com/watch?v=abc",
        "occurred_at": "2026-10-19T12:59:59+00:00",
    }
    document.update(overrides)
    return {key: value for key, value in document.items() if value is not None}


def _context(document, clock=None):
    clock = clock or HouseholdClock(SYDNEY)
    return context_for(parse_request(document), clock, ClientDirectory([YOUNGER]))


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
        "decision": {"action": "allow"},
    }


def test_the_log_entry_for_an_unenrolled_ip_has_no_client():
    document = _request(client_ip="192.168.1.99")
    entry = log_entry(document, _context(document), b"not json")
    assert entry["client"] is None
    assert entry["decision"] == {"raw": "not json"}
