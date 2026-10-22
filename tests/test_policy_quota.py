"""S001.5: quota_remaining reads today's ended buckets against a stored duration."""

import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy import config
from policy.clients import ClientDirectory
from policy.clock import HouseholdClock
from policy.decisions import (
    DecisionRequest,
    completed_today,
    consumed_today,
    context_for,
    decide,
)
from policy.groups import SiteGroups
from policy.store import DEFAULT_BUCKET_SECONDS, SCHEMA_VERSION, _MIGRATIONS, PolicyStore

SYDNEY = ZoneInfo("Australia/Sydney")
WEDNESDAY = datetime(2026, 10, 21, 16, tzinfo=SYDNEY)
TWO_HOURS = 2 * 60 * 60
FIVE_MINUTES = 5 * 60

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

SCHEDULE = """
[household]
timezone = "Australia/Sydney"
revision_task = "http://tasks.example/next"
bucket_length = "5m"

[[clients]]
name = "Younger child"
address = "192.0.2.40"

[[groups]]
name = "Entertainment"
priority = 30
quota = "2h"
patterns = ["*.youtube.com"]

[[groups.rules]]
condition = "time_window"
when_true = { action = "deny", message = "It's bedtime." }
when_false = { action = "continue" }

[[groups.rules.windows]]
start = "00:00"
end = "07:00"
days = ["monday", "tuesday", "wednesday", "thursday"]

[[groups.rules]]
condition = "time_window"
when_true = { action = "redirect", location = "revision_task" }
when_false = { action = "continue" }

[[groups.rules.windows]]
start = "07:00"
end = "15:00"
days = ["monday", "tuesday", "wednesday", "thursday"]

[[groups.rules]]
condition = "time_window"
when_true = { action = "continue" }
when_false = { action = "deny", message = "YouTube is closed for today." }

[[groups.rules.windows]]
start = "15:00"
end = "19:00"
days = ["monday", "tuesday", "wednesday", "thursday"]

[[groups.rules]]
condition = "tasks_complete"
required = 2
when_true = { action = "continue" }
when_false = { action = "redirect", location = "revision_task" }

[[groups.rules]]
condition = "quota_remaining"
when_true = { action = "allow" }
when_false = { action = "deny", message = "Time is up for today." }
"""

ALLOW = {"action": "allow"}
TIME_UP = {"action": "deny", "status": 403, "message": "Time is up for today."}
REDIRECT = {"action": "redirect", "status": 302, "location": "http://tasks.example/next"}


def _quiet(_message):
    return None


def _quota(written: str) -> int | None:
    text = f'[[groups]]\nname = "Entertainment"\npriority = 30\nquota = "{written}"\n'
    return config.parse(text).groups[0].quota


def _apply(
    store: PolicyStore, text: str = HOUSEHOLD, loaded_at: datetime | None = None
) -> dict[str, int]:
    config.apply(config.parse(text), store, warn=_quiet, loaded_at=loaded_at)
    return {client.name: client.id for client in store.clients()}


def _mark(store: PolicyStore, client_id: int, group: str, start: datetime, count: int) -> None:
    step = timedelta(seconds=store.bucket_length())
    for index in range(count):
        store.mark_bucket(client_id, group, start + index * step)


def _decision(
    store: PolicyStore,
    moment: datetime,
    ip: str = "192.0.2.40",
    url: str = "https://www.youtube.com/watch?v=abc",
) -> dict:
    context = context_for(
        DecisionRequest(ip, "GET", url, moment),
        HouseholdClock(SYDNEY),
        ClientDirectory(store.clients()),
        SiteGroups(store.groups()),
    )
    return json.loads(
        decide(
            context,
            revision_task=store.revision_task(),
            completed=completed_today(store, context),
            consumed=consumed_today(store, context),
        )
    )


@pytest.mark.parametrize("written", ["2h", "2H", "120m", "7200s"])
def test_two_hours_is_the_same_quota_in_hours_minutes_or_seconds(written):
    assert _quota(written) == TWO_HOURS
    with PolicyStore(":memory:") as store:
        _apply(store, f'[[groups]]\nname = "Entertainment"\npriority = 30\nquota = "{written}"\n')
        assert store.groups()[0].quota == TWO_HOURS
        (stored,) = store.connection.execute(
            "SELECT quota_seconds FROM site_groups WHERE name = 'Entertainment'"
        ).fetchone()
        assert stored == TWO_HOURS


@pytest.mark.parametrize(
    "line",
    [
        'quota = "24"',
        "quota = 24",
        'quota = "24 buckets"',
        "quota = 7200",
        'quota = "2 hours"',
    ],
)
def test_a_bare_bucket_count_is_rejected(line):
    text = f'[[groups]]\nname = "Entertainment"\npriority = 30\n{line}\n'
    with pytest.raises(config.ConfigError, match="not a number of buckets"):
        config.parse(text)


def test_the_bucket_length_defaults_to_five_minutes():
    assert config.parse('[[groups]]\nname = "A"\npriority = 1\n').bucket_length == DEFAULT_BUCKET_SECONDS
    assert config.parse('[household]\nbucket_length = "10m"\n').bucket_length == 600
    assert config.parse('[household]\nbucket_length = "300s"\n').bucket_length == FIVE_MINUTES
    with PolicyStore(":memory:") as store:
        _apply(store, '[[groups]]\nname = "A"\npriority = 1\n')
        assert store.bucket_length() == FIVE_MINUTES
    with pytest.raises(config.ConfigError, match="not a number of buckets"):
        config.parse('[household]\nbucket_length = 5\n')
    with pytest.raises(config.ConfigError, match="at least one second"):
        config.parse('[household]\nbucket_length = "0s"\n')


def test_twenty_three_ended_buckets_remain_and_twenty_four_are_used_up():
    with PolicyStore(":memory:") as store:
        clients = _apply(store)
        start = datetime(2026, 10, 21, 8, 0, tzinfo=SYDNEY)
        _mark(store, clients["Younger child"], "Entertainment", start, 23)
        assert store.consumed_seconds(clients["Younger child"], "Entertainment", WEDNESDAY) == 23 * FIVE_MINUTES
        assert _decision(store, WEDNESDAY) == ALLOW
        _mark(store, clients["Younger child"], "Entertainment", start, 24)
        assert store.consumed_seconds(clients["Younger child"], "Entertainment", WEDNESDAY) == TWO_HOURS
        assert _decision(store, WEDNESDAY) == TIME_UP


def test_changing_the_bucket_length_does_not_change_the_quota():
    with PolicyStore(":memory:") as store:
        clients = _apply(store)
        younger = clients["Younger child"]
        start = datetime(2026, 10, 21, 8, 0)
        _mark(store, younger, "Entertainment", start, 23)
        longer = HOUSEHOLD.replace('bucket_length = "5m"', 'bucket_length = "10m"')
        # Noon is after those buckets have ended, so this load keeps each stored length.
        _apply(store, longer, loaded_at=datetime(2026, 10, 21, 12, 0))
        assert store.bucket_length() == 10 * 60
        (quota,) = store.connection.execute(
            "SELECT quota_seconds FROM site_groups WHERE name = 'Entertainment'"
        ).fetchone()
        assert quota == TWO_HOURS
        store.mark_bucket(younger, "Entertainment", start)
        lengths = [
            row[0]
            for row in store.connection.execute(
                "SELECT length_seconds FROM usage_buckets ORDER BY started_at"
            )
        ]
        assert lengths == [FIVE_MINUTES] * 23
        assert store.consumed_seconds(younger, "Entertainment", WEDNESDAY) == 23 * FIVE_MINUTES
        assert _decision(store, WEDNESDAY) == ALLOW
        store.mark_bucket(younger, "Entertainment", datetime(2026, 10, 21, 12, 0))
        lengths = [
            row[0]
            for row in store.connection.execute(
                "SELECT length_seconds FROM usage_buckets ORDER BY started_at"
            )
        ]
        assert lengths == [FIVE_MINUTES] * 23 + [10 * 60]
        assert store.consumed_seconds(younger, "Entertainment", WEDNESDAY) == 23 * FIVE_MINUTES + 10 * 60
        assert _decision(store, WEDNESDAY) == TIME_UP


def test_a_bucket_that_is_still_open_is_not_counted():
    text = HOUSEHOLD.replace('quota = "2h"', 'quota = "5m"')
    with PolicyStore(":memory:") as store:
        clients = _apply(store, text)
        start = datetime(2026, 10, 21, 15, 55, tzinfo=SYDNEY)
        store.mark_bucket(clients["Younger child"], "Entertainment", start)
        (rows,) = store.connection.execute("SELECT count(*) FROM usage_buckets").fetchone()
        assert rows == 1
        still_open = datetime(2026, 10, 21, 15, 59, 59, tzinfo=SYDNEY)
        just_ended = datetime(2026, 10, 21, 16, 0, tzinfo=SYDNEY)
        assert store.consumed_seconds(clients["Younger child"], "Entertainment", still_open) == 0
        assert _decision(store, still_open) == ALLOW
        assert store.consumed_seconds(clients["Younger child"], "Entertainment", just_ended) == FIVE_MINUTES
        assert _decision(store, just_ended) == TIME_UP


def test_yesterdays_buckets_are_not_counted_today():
    with PolicyStore(":memory:") as store:
        clients = _apply(store)
        younger = clients["Younger child"]
        _mark(store, younger, "Entertainment", datetime(2026, 10, 20, 8, 0, tzinfo=SYDNEY), 24)
        yesterday = datetime(2026, 10, 20, 16, tzinfo=SYDNEY)
        assert store.consumed_seconds(younger, "Entertainment", yesterday) == TWO_HOURS
        assert _decision(store, yesterday) == TIME_UP
        assert store.consumed_seconds(younger, "Entertainment", WEDNESDAY) == 0
        assert _decision(store, WEDNESDAY) == ALLOW
        # 00:30 in Sydney is still the previous UTC date. It belongs to today.
        store.mark_bucket(younger, "Entertainment", datetime(2026, 10, 21, 0, 30, tzinfo=SYDNEY))
        assert store.consumed_seconds(younger, "Entertainment", WEDNESDAY) == FIVE_MINUTES


def test_another_groups_buckets_are_not_counted():
    with PolicyStore(":memory:") as store:
        clients = _apply(store)
        younger = clients["Younger child"]
        _mark(store, younger, "School work", datetime(2026, 10, 21, 8, 0, tzinfo=SYDNEY), 24)
        assert store.consumed_seconds(younger, "Entertainment", WEDNESDAY) == 0
        assert store.consumed_seconds(younger, "School work", WEDNESDAY) == TWO_HOURS
        assert _decision(store, WEDNESDAY) == ALLOW
        school = _decision(store, WEDNESDAY, url="https://classroom.google.com/u/0/h")
        assert school == ALLOW


def test_another_clients_buckets_are_not_counted():
    with PolicyStore(":memory:") as store:
        clients = _apply(store)
        _mark(store, clients["Older child"], "Entertainment", datetime(2026, 10, 21, 8, 0, tzinfo=SYDNEY), 24)
        assert store.consumed_seconds(clients["Younger child"], "Entertainment", WEDNESDAY) == 0
        assert store.consumed_seconds(clients["Older child"], "Entertainment", WEDNESDAY) == TWO_HOURS
        assert _decision(store, WEDNESDAY, ip="192.0.2.40") == ALLOW
        assert _decision(store, WEDNESDAY, ip="192.0.2.41") == TIME_UP


def test_a_group_with_no_quota_stays_open():
    with PolicyStore(":memory:") as store:
        clients = _apply(store)
        _mark(store, clients["Younger child"], "School work", datetime(2026, 10, 21, 8, 0, tzinfo=SYDNEY), 24)
        assert store.groups()[0].name == "School work"
        assert store.groups()[0].quota is None
        assert store.consumed_seconds(clients["Younger child"], "School work", WEDNESDAY) == TWO_HOURS
        assert _decision(store, WEDNESDAY, url="https://classroom.google.com/u/0/h") == ALLOW


def test_the_wednesday_schedule_allows_while_quota_remains_and_denies_when_it_is_used():
    with PolicyStore(":memory:") as store:
        clients = _apply(store, SCHEDULE)
        younger = clients["Younger child"]
        store.set_task_completions(younger, date(2026, 10, 21), 2)
        start = datetime(2026, 10, 21, 8, 0, tzinfo=SYDNEY)
        _mark(store, younger, "Entertainment", start, 23)
        assert _decision(store, WEDNESDAY) == ALLOW
        _mark(store, younger, "Entertainment", start, 24)
        assert _decision(store, WEDNESDAY) == TIME_UP
        store.set_task_completions(younger, date(2026, 10, 21), 1)
        assert _decision(store, WEDNESDAY) == REDIRECT


def test_a_second_observation_does_not_count_the_bucket_twice():
    with PolicyStore(":memory:") as store:
        clients = _apply(store)
        start = datetime(2026, 10, 21, 8, 0, tzinfo=SYDNEY)
        store.mark_bucket(clients["Younger child"], "Entertainment", start, length_seconds=300, byte_count=100)
        store.mark_bucket(clients["Younger child"], "Entertainment", start, length_seconds=600, byte_count=40)
        (rows, length, byte_count) = store.connection.execute(
            "SELECT count(*), length_seconds, byte_count FROM usage_buckets"
        ).fetchone()
        assert (rows, length, byte_count) == (1, FIVE_MINUTES, 140)
        assert store.consumed_seconds(clients["Younger child"], "Entertainment", WEDNESDAY) == FIVE_MINUTES


def test_reloading_keeps_buckets_and_removing_a_client_or_group_drops_theirs():
    entertainment_only = """
[household]
timezone = "Australia/Sydney"
bucket_length = "5m"

[[clients]]
name = "Younger child"
address = "192.0.2.40"

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
    with PolicyStore(":memory:") as store:
        clients = _apply(store)
        start = datetime(2026, 10, 21, 8, 0)
        store.mark_bucket(clients["Younger child"], "Entertainment", start)
        store.mark_bucket(clients["Older child"], "Entertainment", start)
        store.mark_bucket(clients["Younger child"], "School work", start)
        _apply(store)
        assert store.consumed_seconds(clients["Younger child"], "Entertainment", WEDNESDAY) == FIVE_MINUTES
        assert store.consumed_seconds(clients["Older child"], "Entertainment", WEDNESDAY) == FIVE_MINUTES
        younger_only = HOUSEHOLD.replace(
            '[[clients]]\nname = "Older child"\naddress = "192.0.2.41"\n\n', ""
        )
        _apply(store, younger_only)
        (rows,) = store.connection.execute("SELECT count(*) FROM usage_buckets").fetchone()
        assert rows == 2
        assert store.consumed_seconds(clients["Younger child"], "Entertainment", WEDNESDAY) == FIVE_MINUTES
        _apply(store, entertainment_only)
        (rows,) = store.connection.execute("SELECT count(*) FROM usage_buckets").fetchone()
        assert rows == 1
        assert store.consumed_seconds(clients["Younger child"], "Entertainment", WEDNESDAY) == FIVE_MINUTES


def test_another_connection_sees_a_bucket_an_administrator_stored(tmp_path):
    database = tmp_path / "policy.sqlite3"
    with PolicyStore(database) as service:
        clients = _apply(service)
        younger = clients["Younger child"]
        with PolicyStore(database) as admin:
            admin.mark_bucket(younger, "Entertainment", datetime(2026, 10, 21, 8, 0))
        assert service.consumed_seconds(younger, "Entertainment", WEDNESDAY) == FIVE_MINUTES


def test_a_version_4_database_gains_a_quota_and_keeps_its_groups(tmp_path):
    database = tmp_path / "policy.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript("".join(_MIGRATIONS[:4]) + "PRAGMA user_version = 4;")
    connection.execute(
        "INSERT INTO site_groups (name, priority, is_default) VALUES ('Entertainment', 30, 0)"
    )
    connection.execute("INSERT INTO clients (name, address) VALUES ('Younger child', '192.0.2.40')")
    connection.commit()
    connection.close()

    with PolicyStore(database) as store:
        (version,) = store.connection.execute("PRAGMA user_version").fetchone()
        assert version == SCHEMA_VERSION
        assert store.groups()[0].quota is None
        assert store.bucket_length() == FIVE_MINUTES
        store.mark_bucket(1, "Entertainment", datetime(2026, 10, 21, 8, 0))
        assert store.consumed_seconds(1, "Entertainment", datetime(2026, 10, 21, 9, 0)) == FIVE_MINUTES


def test_a_bucket_has_to_be_for_a_real_client_and_group():
    with PolicyStore(":memory:") as store:
        clients = _apply(store)
        start = datetime(2026, 10, 21, 8, 0)
        client_id = clients["Younger child"]
        with pytest.raises(ValueError, match="not in the household"):
            store.mark_bucket(client_id + 99, "Entertainment", start)
        with pytest.raises(ValueError, match="not in the household"):
            store.mark_bucket(client_id, "Missing", start)
        with pytest.raises(ValueError, match="must be a datetime"):
            store.mark_bucket(client_id, "Entertainment", date(2026, 10, 21))
        with pytest.raises(ValueError, match="one or more"):
            store.mark_bucket(client_id, "Entertainment", start, length_seconds=0)
        with pytest.raises(ValueError, match="one or more"):
            store.mark_bucket(client_id, "Entertainment", start, length_seconds=True)
        with pytest.raises(ValueError, match="zero or more"):
            store.mark_bucket(client_id, "Entertainment", start, byte_count=-1)
