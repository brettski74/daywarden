"""S002.1: observations mark midnight-aligned buckets, and the quota reads them."""

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy import config
from policy.clients import ClientDirectory
from policy.clock import HouseholdClock
from policy.decisions import DecisionRequest, consumed_today, context_for, decide
from policy.groups import SiteGroups
from policy.observations import listen, record
from policy.store import PolicyStore

SYDNEY = ZoneInfo("Australia/Sydney")
WEDNESDAY = datetime(2026, 10, 21, 16, tzinfo=SYDNEY)
TWO_HOURS = 2 * 60 * 60
FIVE_MINUTES = 5 * 60
YOUTUBE = "https://www.youtube.com/watch?v=abc"
CLASSROOM = "https://classroom.google.com/u/0/h"

HOUSEHOLD = """
[household]
timezone = "Australia/Sydney"
bucket_length = "5m"

[[clients]]
name = "Younger child"
address = "192.0.2.40"

[[clients]]
name = "Older child"
address = "192.0.2.41"

[[groups]]
name = "School work"
priority = 10
patterns = ["classroom.google.com"]

[[groups.rules]]
condition = "quota_remaining"
when_true = { action = "allow" }
when_false = { action = "deny", message = "Time is up for today." }

[[groups]]
name = "Entertainment"
priority = 30
quota = "2h"
patterns = ["*.youtube.com"]

[[groups.rules]]
condition = "quota_remaining"
when_true = { action = "allow" }
when_false = { action = "deny", message = "Time is up for today." }
"""

ALLOW = {"action": "allow"}
TIME_UP = {"action": "deny", "status": 403, "message": "Time is up for today."}


def _quiet(_message):
    return None


def _apply(store: PolicyStore, text: str = HOUSEHOLD, loaded_at: datetime | None = None) -> dict[str, int]:
    config.apply(config.parse(text), store, warn=_quiet, loaded_at=loaded_at)
    return {client.name: client.id for client in store.clients()}


def _moment(hour: int, minute: int, second: int = 0, day: int = 21) -> datetime:
    return datetime(2026, 10, day, hour, minute, second, tzinfo=SYDNEY)


def _observe(
    store: PolicyStore,
    moment: datetime,
    url: str = YOUTUBE,
    nbytes: int = 100,
    ip: str = "192.0.2.40",
) -> bool:
    return record(
        store,
        HouseholdClock(SYDNEY),
        {
            "client_ip": ip,
            "url": url,
            "occurred_at": moment.isoformat(),
            "bytes": nbytes,
        },
    )


def _rows(store: PolicyStore) -> list[tuple]:
    return store.connection.execute(
        "SELECT day, started_at, length_seconds, byte_count, "
        "(SELECT name FROM clients WHERE id = usage_buckets.client_id), "
        "(SELECT name FROM site_groups WHERE id = usage_buckets.group_id) "
        "FROM usage_buckets ORDER BY started_at, client_id"
    ).fetchall()


def _decision(store: PolicyStore, moment: datetime, url: str = YOUTUBE, ip: str = "192.0.2.40") -> dict:
    context = context_for(
        DecisionRequest(ip, "GET", url, moment),
        HouseholdClock(SYDNEY),
        ClientDirectory(store.clients()),
        SiteGroups(store.groups()),
    )
    return json.loads(decide(context, consumed=consumed_today(store, context)))


def _post(port: int, body: bytes) -> int:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/observations",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            response.read()
            return response.status
    except urllib.error.HTTPError as error:
        error.read()
        return error.code


def test_an_observation_marks_its_bucket_and_counts_only_after_the_bucket_ends():
    with PolicyStore(":memory:") as store:
        client = _apply(store)["Younger child"]
        assert _observe(store, _moment(15, 0, 1), nbytes=100)
        assert _rows(store) == [("2026-10-21", "2026-10-21T15:00:00", FIVE_MINUTES, 100, "Younger child", "Entertainment")]
        assert store.consumed_seconds(client, "Entertainment", _moment(15, 4)) == 0
        assert _decision(store, _moment(15, 4)) == ALLOW
        assert store.consumed_seconds(client, "Entertainment", _moment(15, 5)) == FIVE_MINUTES
        assert _decision(store, _moment(15, 5)) == ALLOW

        assert _observe(store, _moment(15, 3), nbytes=40)
        assert _rows(store) == [("2026-10-21", "2026-10-21T15:00:00", FIVE_MINUTES, 140, "Younger child", "Entertainment")]
        assert store.consumed_seconds(client, "Entertainment", _moment(15, 5)) == FIVE_MINUTES

        assert _observe(store, _moment(15, 6), nbytes=7)
        assert _rows(store) == [
            ("2026-10-21", "2026-10-21T15:00:00", FIVE_MINUTES, 140, "Younger child", "Entertainment"),
            ("2026-10-21", "2026-10-21T15:05:00", FIVE_MINUTES, 7, "Younger child", "Entertainment"),
        ]


def test_twenty_four_ended_buckets_are_two_hours_and_another_client_is_separate():
    with PolicyStore(":memory:") as store:
        clients = _apply(store)
        younger = clients["Younger child"]
        older = clients["Older child"]
        start = _moment(8, 0)
        for index in range(23):
            _observe(store, start + timedelta(minutes=5 * index, seconds=1))
        assert store.consumed_seconds(younger, "Entertainment", WEDNESDAY) == 23 * FIVE_MINUTES
        assert _decision(store, WEDNESDAY) == ALLOW
        _observe(store, start + timedelta(minutes=5 * 23, seconds=1))
        assert store.consumed_seconds(younger, "Entertainment", WEDNESDAY) == TWO_HOURS
        assert _decision(store, WEDNESDAY) == TIME_UP
        _observe(store, _moment(15, 0, 1, day=20), ip="192.0.2.41")
        assert store.consumed_seconds(younger, "Entertainment", WEDNESDAY) == TWO_HOURS
        assert store.consumed_seconds(older, "Entertainment", _moment(16, 0, day=20)) == FIVE_MINUTES
        assert store.consumed_seconds(older, "Entertainment", WEDNESDAY) == 0


def test_yesterdays_buckets_are_not_counted_today():
    with PolicyStore(":memory:") as store:
        client = _apply(store)["Younger child"]
        _observe(store, _moment(15, 0, 1, day=20))
        assert store.consumed_seconds(client, "Entertainment", _moment(16, 0, day=20)) == FIVE_MINUTES
        assert store.consumed_seconds(client, "Entertainment", WEDNESDAY) == 0
        assert _decision(store, WEDNESDAY) == ALLOW


@pytest.mark.parametrize("written, seconds", [("2m", 120), ("5m", 300), ("10m", 600)])
def test_lengths_that_meet_midnight_are_accepted(written, seconds):
    text = f'[household]\nbucket_length = "{written}"\n[[groups]]\nname = "A"\npriority = 1\n'
    assert config.parse(text).bucket_length == seconds
    with PolicyStore(":memory:") as store:
        _apply(store, text)
        assert store.bucket_length() == seconds


def test_seven_minutes_does_not_meet_midnight():
    with pytest.raises(config.ConfigError, match="midnight"):
        config.parse('[household]\nbucket_length = "7m"\n')


def test_buckets_are_aligned_to_household_local_midnight():
    with PolicyStore(":memory:") as store:
        _apply(store)
        _observe(store, _moment(15, 2))
        _observe(store, _moment(23, 58))
        rows = _rows(store)
        assert rows[0][1:3] == ("2026-10-21T15:00:00", FIVE_MINUTES)
        assert rows[1][1:3] == ("2026-10-21T23:55:00", FIVE_MINUTES)
        end = datetime.fromisoformat(rows[1][1]) + timedelta(seconds=rows[1][2])
        assert end == datetime(2026, 10, 22, 0, 0)
        client = store.clients()[0].id
        assert store.consumed_seconds(client, "Entertainment", _moment(23, 59, 59)) == FIVE_MINUTES
        assert store.consumed_seconds(client, "Entertainment", _moment(0, 0, day=22)) == 0


def test_a_utc_timestamp_is_read_as_household_local_time():
    with PolicyStore(":memory:") as store:
        _apply(store)
        utc = datetime(2026, 10, 21, 4, 0, 1, tzinfo=timezone.utc)
        assert _observe(store, utc)
        assert _rows(store)[0][1] == "2026-10-21T15:00:00"


def test_changing_the_length_closes_the_open_bucket_and_returns_to_midnight():
    with PolicyStore(":memory:") as store:
        client = _apply(store)["Younger child"]
        _observe(store, _moment(14, 0, 1), nbytes=9)
        _observe(store, _moment(15, 0, 1), nbytes=100)
        _observe(store, _moment(15, 0, 1), nbytes=11, ip="192.0.2.41")
        longer = HOUSEHOLD.replace('bucket_length = "5m"', 'bucket_length = "2m"')
        _apply(store, longer, loaded_at=_moment(15, 2, 30))
        assert store.bucket_length() == 120
        entertainment = next(group for group in store.groups() if group.name == "Entertainment")
        assert entertainment.quota == TWO_HOURS
        assert _rows(store) == [
            ("2026-10-21", "2026-10-21T14:00:00", FIVE_MINUTES, 9, "Younger child", "Entertainment"),
            ("2026-10-21", "2026-10-21T15:00:00", 150, 100, "Younger child", "Entertainment"),
            ("2026-10-21", "2026-10-21T15:00:00", 150, 11, "Older child", "Entertainment"),
        ]
        assert store.consumed_seconds(client, "Entertainment", _moment(15, 2, 29)) == FIVE_MINUTES
        assert store.consumed_seconds(client, "Entertainment", _moment(15, 2, 30)) == FIVE_MINUTES + 150

        assert _observe(store, _moment(15, 3), nbytes=40)
        assert _observe(store, _moment(15, 3, 40), nbytes=10)
        short = [row for row in _rows(store) if row[1] == "2026-10-21T15:02:30"]
        assert short == [("2026-10-21", "2026-10-21T15:02:30", 90, 50, "Younger child", "Entertainment")]
        assert store.consumed_seconds(client, "Entertainment", _moment(15, 3, 59)) == FIVE_MINUTES + 150
        assert store.consumed_seconds(client, "Entertainment", _moment(15, 4)) == FIVE_MINUTES + 150 + 90

        _observe(store, _moment(15, 4), nbytes=1)
        _observe(store, _moment(15, 5), nbytes=2)
        _observe(store, _moment(15, 6), nbytes=3)
        _observe(store, _moment(15, 8), nbytes=4)
        assert [row[1:4] for row in _rows(store)] == [
            ("2026-10-21T14:00:00", FIVE_MINUTES, 9),
            ("2026-10-21T15:00:00", 150, 100),
            ("2026-10-21T15:00:00", 150, 11),
            ("2026-10-21T15:02:30", 90, 50),
            ("2026-10-21T15:04:00", 120, 3),
            ("2026-10-21T15:06:00", 120, 3),
            ("2026-10-21T15:08:00", 120, 4),
        ]


def test_an_observation_from_before_the_load_stays_on_the_old_grid():
    with PolicyStore(":memory:") as store:
        _apply(store)
        _apply(store, HOUSEHOLD.replace('bucket_length = "5m"', 'bucket_length = "2m"'), loaded_at=_moment(15, 2, 30))
        assert _observe(store, _moment(15, 1))
        assert _rows(store) == [("2026-10-21", "2026-10-21T15:00:00", 150, 100, "Younger child", "Entertainment")]
        assert _observe(store, _moment(15, 3), nbytes=5)
        assert _rows(store)[1] == ("2026-10-21", "2026-10-21T15:02:30", 90, 5, "Younger child", "Entertainment")


def test_a_load_on_a_boundary_does_not_open_a_short_bucket():
    with PolicyStore(":memory:") as store:
        _apply(store)
        _observe(store, _moment(14, 57))
        _apply(store, HOUSEHOLD.replace('bucket_length = "5m"', 'bucket_length = "2m"'), loaded_at=_moment(15, 0))
        assert _rows(store) == [("2026-10-21", "2026-10-21T14:55:00", FIVE_MINUTES, 100, "Younger child", "Entertainment")]
        _observe(store, _moment(15, 0))
        _observe(store, _moment(15, 1), nbytes=4)
        _observe(store, _moment(15, 2), nbytes=6)
        assert [row[1:3] for row in _rows(store)] == [
            ("2026-10-21T14:55:00", FIVE_MINUTES),
            ("2026-10-21T15:00:00", 120),
            ("2026-10-21T15:02:00", 120),
        ]
        assert _rows(store)[1][3] == 104


def test_the_same_length_does_not_close_an_open_bucket():
    with PolicyStore(":memory:") as store:
        _apply(store)
        _observe(store, _moment(15, 0, 1))
        _apply(store, loaded_at=_moment(15, 2, 30))
        assert _rows(store)[0][2] == FIVE_MINUTES
        _observe(store, _moment(15, 3), nbytes=8)
        assert _rows(store) == [("2026-10-21", "2026-10-21T15:00:00", FIVE_MINUTES, 108, "Younger child", "Entertainment")]


def test_the_first_load_uses_the_midnight_grid():
    text = HOUSEHOLD.replace('bucket_length = "5m"', 'bucket_length = "2m"')
    with PolicyStore(":memory:") as store:
        _apply(store, text, loaded_at=_moment(15, 2, 30))
        _observe(store, _moment(15, 3))
        assert _rows(store)[0][1:3] == ("2026-10-21T15:02:00", 120)


def test_changing_the_length_without_the_load_time_is_refused():
    with PolicyStore(":memory:") as store:
        _apply(store)
        longer = HOUSEHOLD.replace('bucket_length = "5m"', 'bucket_length = "2m"')
        with pytest.raises(ValueError, match="load"):
            _apply(store, longer)
        assert store.bucket_length() == FIVE_MINUTES


def test_a_group_without_a_quota_is_still_marked():
    with PolicyStore(":memory:") as store:
        client = _apply(store)["Younger child"]
        assert _observe(store, _moment(15, 0, 1), url=CLASSROOM)
        assert _rows(store)[0][4:] == ("Younger child", "School work")
        assert store.groups()[0].quota is None
        assert store.consumed_seconds(client, "School work", _moment(15, 5)) == FIVE_MINUTES
        assert _decision(store, _moment(15, 5), url=CLASSROOM) == ALLOW


def test_traffic_outside_every_group_is_ignored_and_the_default_group_is_not():
    with PolicyStore(":memory:") as store:
        _apply(store)
        assert _observe(store, _moment(15, 0, 1), url="https://example.org/") is False
        assert _observe(store, _moment(15, 0, 1), ip="192.0.2.99") is False
        assert _observe(store, _moment(15, 0, 1), nbytes=0) is False
        assert _rows(store) == []

    defaulted = HOUSEHOLD + """
[[groups]]
name = "Everything else"
priority = 50
default = true

[[groups.rules]]
condition = "always"
when_true = { action = "allow" }
when_false = { action = "deny", message = "no" }
"""
    with PolicyStore(":memory:") as store:
        _apply(store, defaulted)
        assert _observe(store, _moment(15, 0, 1), url="https://example.org/")
        assert _rows(store)[0][4:] == ("Younger child", "Everything else")


def test_the_endpoint_accepts_a_grouped_url_and_does_not_error_on_anything_else(tmp_path):
    with PolicyStore(tmp_path / "policy.sqlite3", check_same_thread=False) as store:
        _apply(store)
        server = listen(store, "127.0.0.1", 0, tmp_path / "observations.jsonl")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        try:
            deadline = time.monotonic() + 2
            while True:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.2) as response:
                        if response.status == 200:
                            break
                except OSError:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(0.02)

            body = {
                "client_ip": "192.0.2.40",
                "url": YOUTUBE,
                "occurred_at": _moment(15, 0, 1).isoformat(),
                "bytes": 100,
            }
            assert _post(port, json.dumps(body).encode()) == 204
            assert _rows(store)[0][1:4] == ("2026-10-21T15:00:00", FIVE_MINUTES, 100)

            body["url"] = "https://example.org/"
            body["bytes"] = 50
            assert _post(port, json.dumps(body).encode()) == 204
            assert len(_rows(store)) == 1

            body["url"] = YOUTUBE
            body["client_ip"] = "192.0.2.99"
            assert _post(port, json.dumps(body).encode()) == 204
            assert len(_rows(store)) == 1

            assert _post(port, b"not-json") == 400
            logged = [
                json.loads(line)
                for line in (tmp_path / "observations.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            assert logged[0]["url"] == YOUTUBE
            assert logged[0]["bytes"] == 100
            assert logged[0]["client_ip"] == "192.0.2.40"
            assert "received_at" in logged[0]
        finally:
            server.shutdown()
            server.server_close()
