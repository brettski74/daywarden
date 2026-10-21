"""S001.4: tasks_complete reads a stored per-client count for the household date."""

import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy import config
from policy.clients import ClientDirectory
from policy.clock import HouseholdClock
from policy.decisions import DecisionRequest, completed_today, context_for, decide
from policy.groups import SiteGroups
from policy.rules import evaluate
from policy.store import SCHEMA_VERSION, _MIGRATIONS, PolicyStore

SYDNEY = ZoneInfo("Australia/Sydney")
PLACEHOLDER = "http://tasks.example/next"
WEDNESDAY = datetime(2026, 10, 21, 16, tzinfo=SYDNEY)
THURSDAY = datetime(2026, 10, 22, 16, tzinfo=SYDNEY)

RULE = """
[[groups]]
name = "Entertainment"
priority = 30

[[groups.rules]]
condition = "tasks_complete"
required = 2
when_true = { action = "allow" }
when_false = { action = "deny", message = "Not yet." }
"""

OVERRIDE = """
[[groups]]
name = "Entertainment"
priority = 30

[[groups.rules]]
condition = "tasks_complete"
required = 2
when_true = { action = "allow" }
when_false = { action = "deny", message = "Not yet." }

[[groups.rules.weekdays]]
day = "wednesday"
required = 1

[[groups.rules.weekdays]]
day = "Saturday"
required = 0
"""

HOUSEHOLD = """
[household]
timezone = "Australia/Sydney"
revision_task = "http://tasks.example/next"

[[clients]]
name = "Younger child"
address = "192.0.2.40"

[[clients]]
name = "Older child"
address = "192.0.2.41"

[[groups]]
name = "Entertainment"
priority = 30
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
NOT_YET = {"action": "deny", "status": 403, "message": "Not yet."}
REDIRECT = {"action": "redirect", "status": 302, "location": PLACEHOLDER}


def _quiet(_message):
    return None


def _rule(text: str = RULE):
    return config.parse(text).groups[0].rules[0]


@pytest.mark.parametrize(
    ("completed", "met"),
    [(0, False), (1, False), (2, True), (3, True)],
)
def test_two_completions_are_required(completed, met):
    decision = evaluate([_rule()], WEDNESDAY, completed=completed)
    assert decision == (ALLOW if met else NOT_YET)


def test_wednesday_uses_its_override_and_thursday_uses_the_default():
    rule = _rule(OVERRIDE)
    assert rule.requirement.for_weekday(WEDNESDAY.weekday()) == 1
    assert rule.requirement.for_weekday(THURSDAY.weekday()) == 2
    assert evaluate([rule], WEDNESDAY, completed=0) == NOT_YET
    assert evaluate([rule], WEDNESDAY, completed=1) == ALLOW
    assert evaluate([rule], THURSDAY, completed=1) == NOT_YET
    assert evaluate([rule], THURSDAY, completed=2) == ALLOW
    assert evaluate([rule], datetime(2026, 10, 24, 16, tzinfo=SYDNEY), completed=0) == ALLOW


def test_the_override_round_trips_through_sqlite():
    with PolicyStore(":memory:") as store:
        config.apply(config.parse(OVERRIDE), store, warn=_quiet)
        stored = store.groups()
        assert stored == list(config.parse(OVERRIDE).groups)
        rule = stored[0].rules[0]
        assert evaluate([rule], WEDNESDAY, completed=1) == ALLOW
        assert evaluate([rule], THURSDAY, completed=1) == NOT_YET


def test_completions_are_per_client(tmp_path):
    day = date(2026, 10, 21)
    with PolicyStore(tmp_path / "policy.sqlite3") as store:
        config.apply(config.parse(HOUSEHOLD), store, warn=_quiet)
        clients = {client.name: client for client in store.clients()}
        store.set_task_completions(clients["Older child"].id, day, 4)
        store.set_task_completions(clients["Younger child"].id, day, 1)
        directory = ClientDirectory(store.clients())
        groups = SiteGroups(store.groups())
        clock = HouseholdClock(SYDNEY)

        def counted(ip: str) -> int:
            context = context_for(
                DecisionRequest(ip, "GET", "https://www.youtube.com/watch", WEDNESDAY),
                clock,
                directory,
                groups,
            )
            return completed_today(store, context)

        assert counted("192.0.2.40") == 1
        assert counted("192.0.2.41") == 4
        assert evaluate([_rule()], WEDNESDAY, completed=counted("192.0.2.40")) == NOT_YET
        assert evaluate([_rule()], WEDNESDAY, completed=counted("192.0.2.41")) == ALLOW


def test_a_count_stored_for_yesterday_does_not_count_today():
    with PolicyStore(":memory:") as store:
        config.apply(config.parse(HOUSEHOLD), store, warn=_quiet)
        younger = next(client for client in store.clients() if client.name == "Younger child")
        store.set_task_completions(younger.id, date(2026, 10, 20), 2)
        directory = ClientDirectory(store.clients())
        groups = SiteGroups(store.groups())
        clock = HouseholdClock(SYDNEY)

        def counted(moment: datetime) -> int:
            context = context_for(
                DecisionRequest("192.0.2.40", "GET", "https://www.youtube.com/watch", moment),
                clock,
                directory,
                groups,
            )
            return completed_today(store, context)

        before_midnight = datetime(2026, 10, 19, 12, 59, 59, tzinfo=ZoneInfo("UTC"))
        after_midnight = datetime(2026, 10, 19, 13, 0, tzinfo=ZoneInfo("UTC"))
        assert counted(before_midnight) == 0
        assert counted(after_midnight) == 2
        assert counted(WEDNESDAY) == 0
        assert evaluate([_rule()], WEDNESDAY, completed=counted(WEDNESDAY)) == NOT_YET


def test_an_unenrolled_computer_has_no_completions():
    with PolicyStore(":memory:") as store:
        config.apply(config.parse(HOUSEHOLD), store, warn=_quiet)
        store.set_task_completions(store.clients()[0].id, date(2026, 10, 21), 5)
        context = context_for(
            DecisionRequest("192.0.2.99", "GET", "https://www.youtube.com/watch", WEDNESDAY),
            HouseholdClock(SYDNEY),
            ClientDirectory(store.clients()),
            SiteGroups(store.groups()),
        )
        assert context.client is None
        assert completed_today(store, context) == 0


def test_reloading_the_policy_keeps_the_count_and_removing_a_client_drops_it():
    with PolicyStore(":memory:") as store:
        config.apply(config.parse(HOUSEHOLD), store, warn=_quiet)
        clients = {client.name: client for client in store.clients()}
        day = date(2026, 10, 21)
        store.set_task_completions(clients["Younger child"].id, day, 2)
        store.set_task_completions(clients["Older child"].id, day, 1)
        config.apply(config.parse(HOUSEHOLD), store, warn=_quiet)
        kept = {client.name: client.id for client in store.clients()}
        assert kept["Younger child"] == clients["Younger child"].id
        assert store.task_completions(kept["Younger child"], day) == 2
        younger_only = HOUSEHOLD.replace(
            '[[clients]]\nname = "Older child"\naddress = "192.0.2.41"\n\n', ""
        )
        config.apply(config.parse(younger_only), store, warn=_quiet)
        assert [client.name for client in store.clients()] == ["Younger child"]
        assert store.task_completions(kept["Younger child"], day) == 2
        (rows,) = store.connection.execute("SELECT count(*) FROM task_completions").fetchone()
        assert rows == 1


def test_another_connection_sees_a_count_an_administrator_stored(tmp_path):
    database = tmp_path / "policy.sqlite3"
    with PolicyStore(database) as service:
        config.apply(config.parse(HOUSEHOLD), service, warn=_quiet)
        younger = next(client for client in service.clients() if client.name == "Younger child")
        with PolicyStore(database) as admin:
            admin.set_task_completions(younger.id, date(2026, 10, 21), 2)
        assert service.task_completions(younger.id, date(2026, 10, 21)) == 2
        admin_again = PolicyStore(database)
        try:
            admin_again.set_task_completions(younger.id, date(2026, 10, 21), 1)
            assert service.task_completions(younger.id, date(2026, 10, 21)) == 1
        finally:
            admin_again.close()


def test_the_wednesday_schedule_follows_the_stored_count():
    with PolicyStore(":memory:") as store:
        config.apply(config.parse(HOUSEHOLD), store, warn=_quiet)
        younger = next(client for client in store.clients() if client.name == "Younger child")
        directory = ClientDirectory(store.clients())
        groups = SiteGroups(store.groups())
        clock = HouseholdClock(SYDNEY)

        def decision(count: int) -> dict:
            store.set_task_completions(younger.id, date(2026, 10, 21), count)
            context = context_for(
                DecisionRequest("192.0.2.40", "GET", "https://www.youtube.com/watch?v=abc", WEDNESDAY),
                clock,
                directory,
                groups,
            )
            return json.loads(
                decide(
                    context,
                    revision_task=store.revision_task(),
                    completed=completed_today(store, context),
                )
            )

        assert decision(2) == ALLOW
        assert decision(1) == REDIRECT
        assert decision(0) == REDIRECT


def test_a_version_3_database_keeps_its_rules_and_gains_completion_storage(tmp_path):
    database = tmp_path / "policy.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript("".join(_MIGRATIONS[:3]) + "PRAGMA user_version = 3;")
    connection.execute(
        "INSERT INTO site_groups (name, priority, is_default) VALUES ('Entertainment', 30, 0)"
    )
    connection.execute(
        "INSERT INTO rules (group_id, position, condition) VALUES (1, 0, 'tasks_complete')"
    )
    connection.executemany(
        "INSERT INTO rule_actions (rule_id, branch, kind, message, location) VALUES (?, ?, ?, ?, ?)",
        (
            (1, "when_true", "continue", "", ""),
            (1, "when_false", "deny", "Not yet.", ""),
        ),
    )
    connection.execute("INSERT INTO clients (name, address) VALUES ('Younger child', '192.0.2.40')")
    connection.commit()
    connection.close()

    with PolicyStore(database) as store:
        (version,) = store.connection.execute("PRAGMA user_version").fetchone()
        assert version == SCHEMA_VERSION
        rule = store.groups()[0].rules[0]
        assert rule.condition == "tasks_complete"
        assert rule.requirement is None
        assert evaluate([rule], WEDNESDAY, completed=5) == NOT_YET
        store.set_task_completions(1, date(2026, 10, 21), 2)
        assert store.task_completions(1, date(2026, 10, 21)) == 2


def test_a_count_has_to_be_a_whole_number_for_a_real_client():
    with PolicyStore(":memory:") as store:
        config.apply(config.parse(HOUSEHOLD), store, warn=_quiet)
        client_id = store.clients()[0].id
        with pytest.raises(ValueError, match="whole number"):
            store.set_task_completions(client_id, date(2026, 10, 21), -1)
        with pytest.raises(ValueError, match="whole number"):
            store.set_task_completions(client_id, date(2026, 10, 21), True)
        with pytest.raises(ValueError, match="not in the household"):
            store.set_task_completions(client_id + 99, date(2026, 10, 21), 1)
        with pytest.raises(ValueError, match="must be a date"):
            store.set_task_completions(client_id, datetime(2026, 10, 21), 1)
