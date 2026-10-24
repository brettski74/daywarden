"""S002.3: volume_remaining reads today's stored bytes against a byte limit."""

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy import config
from policy.clients import ClientDirectory
from policy.clock import HouseholdClock
from policy.decisions import DecisionRequest, answer_from_store, context_for
from policy.gate import ParentGate
from policy.groups import SiteGroups
from policy.observations import record
from policy.report import format_byte_limit, respond
from policy.store import SCHEMA_VERSION, _MIGRATIONS, PolicyStore

SYDNEY = ZoneInfo("Australia/Sydney")
WEDNESDAY = datetime(2026, 10, 21, 16, tzinfo=SYDNEY)
YOUTUBE = "https://www.youtube.com/watch?v=abc"
CLASSROOM = "https://classroom.google.com/u/0/h"
PASSWORD = "secret"
ONE_KILOBYTE = 1024
TWO_MEGABYTES = 2 * 1024 * 1024

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
condition = "volume_remaining"
when_true = { action = "allow" }
when_false = { action = "deny", message = "That's enough video for today." }

[[groups]]
name = "Entertainment"
priority = 30
quota = "2h"
byte_limit = "1KB"
patterns = ["*.youtube.com"]

[[groups.rules]]
condition = "quota_remaining"
when_true = { action = "continue" }
when_false = { action = "deny", message = "Time is up for today." }

[[groups.rules]]
condition = "volume_remaining"
when_true = { action = "allow" }
when_false = { action = "deny", message = "That's enough video for today." }
"""

ALLOW = {"action": "allow"}
TIME_UP = {"action": "deny", "status": 403, "message": "Time is up for today."}
TOO_MUCH = {"action": "deny", "status": 403, "message": "That's enough video for today."}


def _quiet(_message):
    return None


def _limit(written: str) -> int:
    text = f'[[groups]]\nname = "Entertainment"\npriority = 30\nbyte_limit = "{written}"\n'
    return config.parse(text).groups[0].byte_limit


def _apply(store: PolicyStore, text: str = HOUSEHOLD) -> dict[str, int]:
    config.apply(config.parse(text), store, warn=_quiet, loaded_at=None)
    return {client.name: client.id for client in store.clients()}


def _group(store: PolicyStore, name: str):
    return next(group for group in store.groups() if group.name == name)


def _decision(
    store: PolicyStore,
    moment: datetime,
    ip: str = "192.0.2.40",
    url: str = YOUTUBE,
) -> dict:
    context = context_for(
        DecisionRequest(ip, "GET", url, moment),
        HouseholdClock(SYDNEY),
        ClientDirectory(store.clients()),
        SiteGroups(store.groups()),
    )
    return json.loads(answer_from_store(store, context, Path("unused")))


def _observe(store: PolicyStore, moment: datetime, nbytes: int, url: str = YOUTUBE) -> bool:
    return record(
        store,
        HouseholdClock(SYDNEY),
        {
            "client_ip": "192.0.2.40",
            "url": url,
            "occurred_at": moment.isoformat(),
            "bytes": nbytes,
        },
    )


def _mark(store: PolicyStore, client_id: int, group: str, start: datetime, count: int) -> None:
    step = timedelta(seconds=store.bucket_length())
    for index in range(count):
        store.mark_bucket(client_id, group, start + index * step)


@pytest.mark.parametrize("written", ["1KB", "1kb", "1024B", "1024b"])
def test_one_kilobyte_is_1024_bytes(written):
    assert _limit(written) == ONE_KILOBYTE


def test_a_thousand_bytes_is_not_a_kilobyte():
    assert _limit("1000B") == 1000
    assert _limit("1KB") == 1024


@pytest.mark.parametrize(
    ("written", "expected", "shown"),
    [
        ("2KB", 2 * 1024, "2 KB"),
        ("1MB", 1024**2, "1 MB"),
        ("500MB", 500 * 1024**2, "500 MB"),
        ("500mb", 500 * 1024**2, "500 MB"),
        ("1GB", 1024**3, "1 GB"),
        ("1TB", 1024**4, "1 TB"),
        ("2tb", 2 * 1024**4, "2 TB"),
    ],
)
def test_byte_limits_are_powers_of_two_and_round_trip(written, expected, shown):
    assert _limit(written) == expected
    assert format_byte_limit(expected) == shown
    text = f'[[groups]]\nname = "Entertainment"\npriority = 30\nquota = "2h"\nbyte_limit = "{written}"\n'
    with PolicyStore(":memory:") as store:
        _apply(store, text)
        assert _group(store, "Entertainment").byte_limit == expected
        assert _group(store, "Entertainment").quota == 2 * 60 * 60
        (stored,) = store.connection.execute(
            "SELECT byte_limit FROM site_groups WHERE name = 'Entertainment'"
        ).fetchone()
        assert stored == expected


def test_a_size_that_is_not_a_whole_unit_stays_in_bytes():
    assert format_byte_limit(1500) == "1,500 bytes"


@pytest.mark.parametrize(
    "line",
    [
        'byte_limit = "500"',
        "byte_limit = 500",
        'byte_limit = "500 megabytes"',
        'byte_limit = "500MiB"',
        'byte_limit = "1.5GB"',
        'byte_limit = "500 MB"',
    ],
)
def test_a_bare_byte_count_is_rejected(line):
    text = f'[[groups]]\nname = "Entertainment"\npriority = 30\n{line}\n'
    with pytest.raises(config.ConfigError, match="not a bare number"):
        config.parse(text)


def test_a_group_with_no_byte_limit_stays_open():
    with PolicyStore(":memory:") as store:
        clients = _apply(store)
        assert _group(store, "School work").byte_limit is None
        store.mark_bucket(
            clients["Younger child"],
            "School work",
            datetime(2026, 10, 21, 9, 0, tzinfo=SYDNEY),
            byte_count=50_000_000,
        )
        assert store.observed_bytes(clients["Younger child"], "School work", WEDNESDAY) == 50_000_000
        assert _decision(store, WEDNESDAY, url=CLASSROOM) == ALLOW


def test_bytes_under_the_limit_allow_and_reaching_it_denies():
    with PolicyStore(":memory:") as store:
        clients = _apply(store)
        younger = clients["Younger child"]
        start = datetime(2026, 10, 21, 15, 0, tzinfo=SYDNEY)
        store.mark_bucket(younger, "Entertainment", start, byte_count=ONE_KILOBYTE - 1)
        assert store.observed_bytes(younger, "Entertainment", WEDNESDAY) == ONE_KILOBYTE - 1
        assert _decision(store, WEDNESDAY) == ALLOW
        store.mark_bucket(younger, "Entertainment", start, byte_count=1)
        assert store.observed_bytes(younger, "Entertainment", WEDNESDAY) == ONE_KILOBYTE
        assert _decision(store, WEDNESDAY) == TOO_MUCH


def test_a_zero_byte_limit_is_already_used_up():
    text = HOUSEHOLD.replace('byte_limit = "1KB"', 'byte_limit = "0B"')
    with PolicyStore(":memory:") as store:
        _apply(store, text)
        assert _group(store, "Entertainment").byte_limit == 0
        assert _decision(store, WEDNESDAY) == TOO_MUCH


def test_bytes_in_an_open_bucket_count_before_its_time_does():
    with PolicyStore(":memory:") as store:
        clients = _apply(store)
        younger = clients["Younger child"]
        start = datetime(2026, 10, 21, 15, 0, tzinfo=SYDNEY)
        store.mark_bucket(younger, "Entertainment", start, byte_count=ONE_KILOBYTE)
        still_open = datetime(2026, 10, 21, 15, 1, tzinfo=SYDNEY)
        assert store.consumed_seconds(younger, "Entertainment", still_open) == 0
        assert store.observed_bytes(younger, "Entertainment", still_open) == ONE_KILOBYTE
        assert _decision(store, still_open) == TOO_MUCH


def test_volume_and_time_each_deny_with_their_own_message():
    with PolicyStore(":memory:") as store:
        clients = _apply(store)
        younger = clients["Younger child"]
        assert _decision(store, WEDNESDAY) == ALLOW
        start = datetime(2026, 10, 21, 8, 0, tzinfo=SYDNEY)
        _mark(store, younger, "Entertainment", start, 23)
        store.mark_bucket(younger, "Entertainment", start, byte_count=ONE_KILOBYTE)
        assert store.consumed_seconds(younger, "Entertainment", WEDNESDAY) == 23 * 300
        assert _decision(store, WEDNESDAY) == TOO_MUCH
        _mark(store, younger, "Entertainment", start, 24)
        with store.connection:
            store.connection.execute("UPDATE usage_buckets SET byte_count = 0")
        assert store.observed_bytes(younger, "Entertainment", WEDNESDAY) == 0
        assert store.consumed_seconds(younger, "Entertainment", WEDNESDAY) == 24 * 300
        assert _decision(store, WEDNESDAY) == TIME_UP


def test_yesterdays_bytes_are_not_counted_today():
    with PolicyStore(":memory:") as store:
        clients = _apply(store)
        younger = clients["Younger child"]
        store.mark_bucket(
            younger, "Entertainment", datetime(2026, 10, 20, 8, 0, tzinfo=SYDNEY), byte_count=ONE_KILOBYTE
        )
        yesterday = datetime(2026, 10, 20, 16, tzinfo=SYDNEY)
        assert store.observed_bytes(younger, "Entertainment", yesterday) == ONE_KILOBYTE
        assert _decision(store, yesterday) == TOO_MUCH
        assert store.observed_bytes(younger, "Entertainment", WEDNESDAY) == 0
        assert _decision(store, WEDNESDAY) == ALLOW


def test_another_client_and_another_group_are_not_counted():
    with PolicyStore(":memory:") as store:
        clients = _apply(store)
        start = datetime(2026, 10, 21, 8, 0, tzinfo=SYDNEY)
        store.mark_bucket(clients["Older child"], "Entertainment", start, byte_count=ONE_KILOBYTE)
        store.mark_bucket(clients["Younger child"], "School work", start, byte_count=ONE_KILOBYTE)
        younger = clients["Younger child"]
        assert store.observed_bytes(younger, "Entertainment", WEDNESDAY) == 0
        assert store.observed_bytes(clients["Older child"], "Entertainment", WEDNESDAY) == ONE_KILOBYTE
        assert _decision(store, WEDNESDAY, ip="192.0.2.40") == ALLOW
        assert _decision(store, WEDNESDAY, ip="192.0.2.41") == TOO_MUCH
        assert _decision(store, WEDNESDAY, url=CLASSROOM) == ALLOW


def test_the_condition_reads_the_bytes_observations_store():
    with PolicyStore(":memory:") as store:
        clients = _apply(store)
        younger = clients["Younger child"]
        moment = datetime(2026, 10, 21, 15, 0, 1, tzinfo=SYDNEY)
        assert _observe(store, moment, 400)
        assert _observe(store, moment + timedelta(seconds=30), 623)
        (rows, total) = store.connection.execute(
            "SELECT count(*), byte_count FROM usage_buckets"
        ).fetchone()
        assert (rows, total) == (1, ONE_KILOBYTE - 1)
        assert store.observed_bytes(younger, "Entertainment", WEDNESDAY) == ONE_KILOBYTE - 1
        assert _decision(store, WEDNESDAY) == ALLOW
        with store.connection:
            store.connection.execute("UPDATE usage_buckets SET byte_count = ?", (ONE_KILOBYTE,))
        assert store.observed_bytes(younger, "Entertainment", WEDNESDAY) == ONE_KILOBYTE
        assert _decision(store, WEDNESDAY) == TOO_MUCH
        names = [
            row[0]
            for row in store.connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        ]
        assert "usage_buckets" in names
        assert not any("volume" in name for name in names)


def test_reloading_changes_the_limit_and_keeps_the_stored_bytes():
    with PolicyStore(":memory:") as store:
        clients = _apply(store)
        younger = clients["Younger child"]
        start = datetime(2026, 10, 21, 15, 0)
        store.mark_bucket(younger, "Entertainment", start, byte_count=100)
        larger = HOUSEHOLD.replace('byte_limit = "1KB"', 'byte_limit = "2KB"')
        _apply(store, larger)
        assert _group(store, "Entertainment").byte_limit == 2 * 1024
        assert _group(store, "Entertainment").quota == 2 * 60 * 60
        (byte_count,) = store.connection.execute("SELECT byte_count FROM usage_buckets").fetchone()
        assert byte_count == 100
        assert _decision(store, WEDNESDAY) == ALLOW
        without = HOUSEHOLD.replace('byte_limit = "1KB"\n', "")
        _apply(store, without)
        assert _group(store, "Entertainment").byte_limit is None
        (byte_count,) = store.connection.execute("SELECT byte_count FROM usage_buckets").fetchone()
        assert byte_count == 100
        with store.connection:
            store.connection.execute("UPDATE usage_buckets SET byte_count = 5000")
        assert _decision(store, WEDNESDAY) == ALLOW


def test_a_version_5_database_gains_a_null_byte_limit_and_keeps_its_buckets(tmp_path):
    database = tmp_path / "policy.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript("".join(_MIGRATIONS[:5]) + "PRAGMA user_version = 5;")
    connection.execute("INSERT INTO clients (name, address) VALUES ('Younger child', '192.0.2.40')")
    connection.execute(
        "INSERT INTO site_groups (name, priority, is_default, quota_seconds) "
        "VALUES ('Entertainment', 30, 0, 7200)"
    )
    connection.execute(
        "INSERT INTO usage_buckets (client_id, group_id, day, started_at, length_seconds, byte_count) "
        "VALUES (1, 1, '2026-10-21', '2026-10-21T15:00:00', 300, 140)"
    )
    connection.commit()
    connection.close()

    with PolicyStore(database) as store:
        (version,) = store.connection.execute("PRAGMA user_version").fetchone()
        assert version == SCHEMA_VERSION
        assert _group(store, "Entertainment").quota == 7200
        assert _group(store, "Entertainment").byte_limit is None
        assert store.observed_bytes(1, "Entertainment", WEDNESDAY) == 140


def _token(page) -> str:
    header = dict(page.headers)["set-cookie"]
    return header.split(";", 1)[0].split("=", 1)[1]


def _signed(store: PolicyStore, now: datetime, client: str, group: str) -> str:
    gate = ParentGate(PASSWORD)
    opened = respond(
        store,
        gate,
        method="POST",
        query={"client": client, "group": group},
        cookie=None,
        form={"password": PASSWORD},
        now=now,
    )
    assert opened.status == 303
    page = respond(
        store,
        gate,
        method="GET",
        query={"client": client, "group": group},
        cookie=_token(opened),
        form={},
        now=now,
    )
    assert page.status == 200
    return page.body


def _section(body: str, heading: str, following: str) -> str:
    _before, rest = body.split(heading, 1)
    section, _after = rest.split(following, 1)
    return section


def test_the_report_shows_the_days_bytes_beside_the_limit():
    text = HOUSEHOLD.replace('byte_limit = "1KB"', 'byte_limit = "2MB"')
    with PolicyStore(":memory:") as store:
        clients = _apply(store, text)
        younger = clients["Younger child"]
        store.mark_bucket(
            younger, "Entertainment", datetime(2026, 10, 21, 15, 0), byte_count=140
        )
        store.mark_bucket(
            younger, "Entertainment", datetime(2026, 10, 21, 15, 5), byte_count=1000
        )
        store.mark_bucket(
            younger, "Entertainment", datetime(2026, 10, 21, 15, 58), byte_count=7
        )
        store.mark_bucket(
            younger, "Entertainment", datetime(2026, 10, 20, 10, 0), byte_count=50
        )
        store.mark_bucket(
            younger, "School work", datetime(2026, 10, 21, 9, 0), byte_count=80
        )
        now = datetime(2026, 10, 21, 16, tzinfo=SYDNEY)
        body = _signed(store, now, "Younger child", "Entertainment")
        assert "Quota: 2h." in body
        assert "Byte limit: 2 MB." in body
        wednesday = _section(body, "Wednesday 21 October 2026", "Tuesday 20 October 2026")
        assert "Bytes: 1,147 bytes of 2 MB." in wednesday
        assert "Counted time: 10m." in wednesday
        assert "not counted yet" in wednesday
        tuesday = _section(body, "Tuesday 20 October 2026", "Monday 19 October 2026")
        assert "Bytes: 50 bytes of 2 MB." in tuesday
        monday = _section(body, "Monday 19 October 2026", "Sunday 18 October 2026")
        assert "no usage" in monday
        assert "Bytes: 0 bytes of 2 MB." in monday
        assert body.count("no usage") == 12

        school = _signed(store, now, "Younger child", "School work")
        assert "Byte limit" not in school
        assert "bytes of" not in school
        assert "80 bytes" in school
        assert "No quota on this group." in school
        assert _group(store, "Entertainment").byte_limit == TWO_MEGABYTES
