"""S001.3: ordered rules and time windows. The task count is S001.4. Quota is S001.5."""

import re
import sqlite3
import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy import config
from policy.rules import Action, Rule, TimeWindow, evaluate
from policy.store import _MIGRATIONS, SCHEMA_VERSION, PolicyStore
from proxy.decision import recognize

SYDNEY = ZoneInfo("Australia/Sydney")
PLACEHOLDER = "http://tasks.example/next"
WEDNESDAY = datetime(2026, 10, 21, tzinfo=SYDNEY)
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday")

SCHEDULE = """
[household]
revision_task = "http://tasks.example/next"

[[groups]]
name = "School work"
priority = 10
patterns = ["classroom.google.com"]

[[groups.rules]]
condition = "always"
when_true = { action = "allow" }
when_false = { action = "continue" }

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

BEDTIME = {"action": "deny", "status": 403, "message": "It's bedtime."}
CLOSED = {"action": "deny", "status": 403, "message": "YouTube is closed for today."}
REDIRECT = {"action": "redirect", "status": 302, "location": PLACEHOLDER}
ALLOW = {"action": "allow"}
TIME_UP = {"action": "deny", "status": 403, "message": "Time is up for today."}


def _quiet(_message):
    return None


def _at(hour: int, minute: int, day: int = 21) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=SYDNEY)


_DAY_NUMBER = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _window(start: str, end: str, days: tuple[str, ...] | None = None) -> TimeWindow:
    weekdays = None if days is None else frozenset(_DAY_NUMBER[day] for day in days)
    return TimeWindow(time.fromisoformat(start), time.fromisoformat(end), weekdays)


def _open_when(window: TimeWindow, at: datetime) -> bool:
    decision = evaluate(
        [Rule("time_window", Action("allow"), Action("deny", "closed"), (window,))],
        at,
    )
    return decision == ALLOW


def _schedule(**hooks) -> dict:
    rules = next(
        group.rules for group in config.parse(SCHEDULE).groups if group.name == "Entertainment"
    )
    return evaluate(rules, hooks.pop("at"), revision_task=PLACEHOLDER, **hooks)


def test_wednesday_is_the_day_the_schedule_uses():
    assert WEDNESDAY.weekday() == 2


def test_allow_stops_the_list():
    rules = [
        Rule("always", Action("allow"), Action("deny", "no")),
        Rule("always", Action("deny", "should not run"), Action("deny", "should not run")),
    ]
    assert evaluate(rules, WEDNESDAY) == ALLOW


def test_deny_stops_the_list():
    rules = [
        Rule("always", Action("deny", "It's bedtime."), Action("allow")),
        Rule("always", Action("allow"), Action("allow")),
    ]
    assert evaluate(rules, WEDNESDAY) == BEDTIME


def test_redirect_stops_the_list_with_an_absolute_url():
    rules = [
        Rule("always", Action("redirect", location="https://tasks.example/next"), Action("allow")),
        Rule("always", Action("allow"), Action("allow")),
    ]
    decision = evaluate(rules, WEDNESDAY)
    assert decision == {"action": "redirect", "status": 302, "location": "https://tasks.example/next"}
    assert recognize(decision) == decision


def test_continue_evaluates_the_next_rule():
    rules = [
        Rule("always", Action("continue"), Action("deny", "wrong branch")),
        Rule("always", Action("deny", "Time is up for today."), Action("allow")),
    ]
    assert evaluate(rules, WEDNESDAY) == TIME_UP


def test_an_empty_rule_list_denies_the_request():
    parsed = config.parse('[[groups]]\nname = "A"\npriority = 1\nrules = []\n')
    decision = evaluate(parsed.groups[0].rules, WEDNESDAY)
    assert decision == {"action": "deny", "status": 403, "message": "No rule allowed this request."}
    assert recognize(decision) == decision


def test_a_list_that_only_continues_denies_the_request():
    rules = [Rule("always", Action("continue"), Action("continue"))]
    assert evaluate(rules, WEDNESDAY)["message"] == "No rule allowed this request."


def test_a_morning_window_matches_0659_on_wednesday_and_not_0700():
    window = _window("00:00", "07:00", WEEKDAYS)
    assert _open_when(window, _at(6, 59))
    assert _open_when(window, _at(6, 59).replace(second=59))
    assert _open_when(window, _at(0, 0))
    assert not _open_when(window, _at(7, 0))


def test_a_window_across_midnight_matches_the_evening_and_the_morning():
    window = _window("22:00", "07:00")
    assert _open_when(window, _at(23, 30))
    assert _open_when(window, _at(6, 30, day=22))
    assert not _open_when(window, _at(12, 0))
    assert not _open_when(window, _at(7, 0))


def test_a_saturday_window_does_not_match_on_wednesday():
    window = _window("10:00", "12:00", ("saturday",))
    assert not _open_when(window, _at(10, 30))
    assert _open_when(window, _at(10, 30, day=24))


def test_a_saturday_night_window_includes_sunday_morning_and_not_saturday_morning():
    window = _window("22:00", "07:00", ("saturday",))
    assert _open_when(window, _at(23, 30, day=24))
    assert _open_when(window, _at(6, 30, day=25))
    assert not _open_when(window, _at(6, 30, day=24))
    assert not _open_when(window, _at(23, 30, day=25))


def test_a_weekday_window_and_an_everyday_window_are_combined():
    rule = Rule(
        "time_window",
        Action("allow"),
        Action("deny", "closed"),
        (
            _window("22:00", "07:00", ("saturday",)),
            _window("12:00", "13:00"),
        ),
    )

    def open_at(day: int, hour: int) -> bool:
        return evaluate([rule], _at(hour, 30, day=day)) == ALLOW

    assert open_at(24, 23)
    assert open_at(25, 6)
    assert open_at(21, 12)
    assert not open_at(21, 23)


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (6, 30, BEDTIME),
        (10, 0, REDIRECT),
        (16, 0, REDIRECT),
        (20, 0, CLOSED),
    ],
)
def test_the_entertainment_schedule_on_wednesday(hour, minute, expected):
    decision = _schedule(at=_at(hour, minute))
    assert decision == expected
    assert recognize(decision) == decision


def test_the_boundary_between_school_and_the_evening_belongs_to_the_later_window():
    assert _schedule(at=_at(14, 59), completed=2) == REDIRECT
    assert _schedule(at=_at(15, 0), completed=2) == ALLOW
    assert _schedule(at=_at(19, 0), completed=2) == CLOSED


def test_two_completions_at_1600_let_the_quota_rule_decide():
    two_hours = 2 * 60 * 60
    assert _schedule(at=_at(16, 0), completed=2, quota=two_hours, consumed=0) == ALLOW
    assert _schedule(at=_at(16, 0), completed=2, quota=two_hours, consumed=two_hours) == TIME_UP


def test_completions_do_not_skip_an_earlier_rule():
    assert _schedule(at=_at(10, 0), completed=2) == REDIRECT
    assert _schedule(at=_at(16, 0), completed=1, quota=2 * 60 * 60, consumed=2 * 60 * 60) == REDIRECT


def test_a_missing_placeholder_fails_closed():
    rules = [Rule("always", Action("redirect", location="revision_task"), Action("allow"))]
    decision = evaluate(rules, WEDNESDAY)
    assert decision == {
        "action": "deny",
        "status": 403,
        "message": "The revision task page is not configured.",
    }
    assert recognize(decision) == decision


def test_a_bare_toml_time_is_accepted():
    text = """
[[groups]]
name = "A"
priority = 1

[[groups.rules]]
condition = "time_window"
when_true = { action = "allow" }
when_false = { action = "deny", message = "closed" }

[[groups.rules.windows]]
start = 00:00:00
end = 07:00:00
days = ["Wednesday"]
"""
    window = config.parse(text).groups[0].rules[0].windows[0]
    assert window == _window("00:00", "07:00", ("wednesday",))


def test_the_schedule_round_trips_through_sqlite_and_keeps_group_ids():
    with PolicyStore(":memory:") as store:
        config.apply(config.parse(SCHEDULE), store, warn=_quiet)
        first = dict(store.connection.execute("SELECT name, id FROM site_groups"))
        assert store.revision_task() == PLACEHOLDER
        config.apply(config.parse(SCHEDULE), store, warn=_quiet)
        assert dict(store.connection.execute("SELECT name, id FROM site_groups")) == first
        (rules,) = store.connection.execute("SELECT count(*) FROM rules").fetchone()
        assert rules == 6
        stored = store.groups()
        assert stored == list(config.parse(SCHEDULE).groups)
        entertainment = next(group for group in stored if group.name == "Entertainment")
        assert evaluate(entertainment.rules, _at(16, 0), revision_task=store.revision_task()) == REDIRECT


def test_omitting_the_placeholder_clears_the_stored_one():
    with PolicyStore(":memory:") as store:
        config.apply(config.parse(SCHEDULE), store, warn=_quiet)
        config.apply(config.parse('[[groups]]\nname = "School work"\npriority = 10\n'), store, warn=_quiet)
        assert store.revision_task() is None
        assert store.groups() == list(config.parse('[[groups]]\nname = "School work"\npriority = 10\n').groups)


def test_a_version_2_database_is_upgraded_and_keeps_its_groups(tmp_path):
    database = tmp_path / "policy.sqlite3"
    plain = '[[groups]]\nname = "Entertainment"\npriority = 30\npatterns = ["*.youtube.com"]\n'
    old = sqlite3.connect(database)
    old.executescript(
        "".join(_MIGRATIONS[:2])
        + """
        INSERT INTO site_groups (id, name, priority, is_default) VALUES (1, 'Entertainment', 30, 0);
        INSERT INTO site_group_patterns (group_id, position, pattern) VALUES (1, 0, '*.youtube.com');
        PRAGMA user_version = 2;
        """
    )
    old.close()
    with PolicyStore(database) as upgraded:
        (version,) = upgraded.connection.execute("PRAGMA user_version").fetchone()
        assert version == SCHEMA_VERSION
        assert upgraded.groups() == list(config.parse(plain).groups)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            '[[groups]]\nname = "A"\npriority = 1\n[[groups.rules]]\nwhen_true = { action = "allow" }\n'
            'when_false = { action = "continue" }\n',
            "condition must be time_window",
        ),
        (
            '[[groups]]\nname = "A"\npriority = 1\n[[groups.rules]]\ncondition = "time_window"\n'
            'when_true = { action = "allow" }\nwhen_false = { action = "continue" }\n',
            "needs at least one window",
        ),
        (
            '[[groups]]\nname = "A"\npriority = 1\n[[groups.rules]]\ncondition = "always"\n'
            'when_true = { action = "allow" }\nwhen_false = { action = "continue" }\n'
            "[[groups.rules.windows]]\nstart = \"10:00\"\nend = \"11:00\"\n",
            "does not take windows",
        ),
        (
            '[[groups]]\nname = "A"\npriority = 1\n[[groups.rules]]\ncondition = "tasks_complete"\n'
            'when_true = { action = "continue" }\n',
            "when_true and when_false are both required",
        ),
        (
            '[[groups]]\nname = "A"\npriority = 1\n[[groups.rules]]\ncondition = "tasks_complete"\n'
            'when_true = { action = "continue" }\nwhen_false = { action = "continue" }\n',
            "needs a required count",
        ),
        (
            '[[groups]]\nname = "A"\npriority = 1\n[[groups.rules]]\ncondition = "tasks_complete"\n'
            'required = -1\nwhen_true = { action = "continue" }\nwhen_false = { action = "continue" }\n',
            "whole number, zero or more",
        ),
        (
            '[[groups]]\nname = "A"\npriority = 1\n[[groups.rules]]\ncondition = "tasks_complete"\n'
            'required = true\nwhen_true = { action = "continue" }\nwhen_false = { action = "continue" }\n',
            "whole number, zero or more",
        ),
        (
            '[[groups]]\nname = "A"\npriority = 1\n[[groups.rules]]\ncondition = "tasks_complete"\n'
            'required = 2\nwhen_true = { action = "continue" }\nwhen_false = { action = "continue" }\n'
            '[[groups.rules.weekdays]]\nday = "funday"\nrequired = 1\n',
            "not a weekday",
        ),
        (
            '[[groups]]\nname = "A"\npriority = 1\n[[groups.rules]]\ncondition = "tasks_complete"\n'
            'required = 2\nwhen_true = { action = "continue" }\nwhen_false = { action = "continue" }\n'
            '[[groups.rules.weekdays]]\nday = "wednesday"\nrequired = 1\n'
            '[[groups.rules.weekdays]]\nday = "Wednesday"\nrequired = 0\n',
            "listed twice",
        ),
        (
            '[[groups]]\nname = "A"\npriority = 1\n[[groups.rules]]\ncondition = "always"\n'
            'required = 1\nwhen_true = { action = "allow" }\nwhen_false = { action = "continue" }\n',
            "does not take a required count",
        ),
        (
            '[[groups]]\nname = "A"\npriority = 1\n[[groups.rules]]\ncondition = "time_window"\n'
            'required = 1\nwhen_true = { action = "allow" }\nwhen_false = { action = "continue" }\n'
            '[[groups.rules.windows]]\nstart = "10:00"\nend = "11:00"\n',
            "does not take a required count",
        ),
        (
            '[[groups]]\nname = "A"\npriority = 1\n[[groups.rules]]\ncondition = "time_window"\n'
            'when_true = { action = "deny", message = "Bed." }\nwhen_false = { action = "continue" }\n'
            '[[groups.rules.windows]]\nstart = "07:00"\nend = "07:00"\n',
            "the end is exclusive",
        ),
        (
            '[[groups]]\nname = "A"\npriority = 1\n[[groups.rules]]\ncondition = "time_window"\n'
            'when_true = { action = "deny", message = "Bed." }\nwhen_false = { action = "continue" }\n'
            '[[groups.rules.windows]]\nstart = "morning"\nend = "07:00"\n',
            "must be a time",
        ),
        (
            '[[groups]]\nname = "A"\npriority = 1\n[[groups.rules]]\ncondition = "time_window"\n'
            'when_true = { action = "deny", message = "Bed." }\nwhen_false = { action = "continue" }\n'
            '[[groups.rules.windows]]\nstart = "22:00"\nend = "07:00"\ndays = ["funday"]\n',
            "not a weekday",
        ),
        (
            '[[groups]]\nname = "A"\npriority = 1\n[[groups.rules]]\ncondition = "time_window"\n'
            'when_true = { action = "deny", message = "Bed." }\nwhen_false = { action = "continue" }\n'
            '[[groups.rules.windows]]\nstart = "22:00"\nend = "07:00"\ndays = []\n',
            "at least one weekday",
        ),
        (
            '[[groups]]\nname = "A"\npriority = 1\n[[groups.rules]]\ncondition = "time_window"\n'
            'when_true = { action = "deny", message = "Bed." }\nwhen_false = { action = "continue" }\n'
            '[[groups.rules.windows]]\nstart = "22:00"\nend = "07:00"\ndays = ["monday", "Monday"]\n',
            "listed twice",
        ),
        (
            '[[groups]]\nname = "A"\npriority = 1\n[[groups.rules]]\ncondition = "always"\n'
            'when_true = { action = "deny" }\nwhen_false = { action = "continue" }\n',
            "deny needs a message",
        ),
        (
            '[[groups]]\nname = "A"\npriority = 1\n[[groups.rules]]\ncondition = "always"\n'
            'when_true = { action = "deny", message = "  " }\nwhen_false = { action = "continue" }\n',
            "deny needs a message",
        ),
        (
            '[[groups]]\nname = "A"\npriority = 1\n[[groups.rules]]\ncondition = "always"\n'
            'when_true = { action = "redirect", location = "/tasks" }\nwhen_false = { action = "continue" }\n',
            "absolute http or https URL",
        ),
        (
            '[[groups]]\nname = "A"\npriority = 1\n[[groups.rules]]\ncondition = "always"\n'
            'when_true = { action = "continue", message = "no" }\nwhen_false = { action = "continue" }\n',
            "takes no other settings",
        ),
        (
            '[[groups]]\nname = "A"\npriority = 1\n[[groups.rules]]\ncondition = "always"\n'
            'when_true = { action = "redirect", location = "revision_task" }\n'
            'when_false = { action = "continue" }\n',
            "household.revision_task is not set",
        ),
        (
            '[household]\nrevision_task = "javascript:alert(1)"\n',
            "household.revision_task must be an absolute",
        ),
        (
            '[[groups]]\nname = "A"\npriority = 1\nrules = "allow"\n',
            "[[groups.rules]]",
        ),
    ],
)
def test_invalid_rules_are_rejected(text, message):
    with pytest.raises(config.ConfigError, match=re.escape(message)):
        config.parse(text)
