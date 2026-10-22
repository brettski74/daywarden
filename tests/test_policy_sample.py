"""S001.6: the sample household policy is the worked example, loaded from the file."""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy import config
from policy.clients import ClientDirectory
from policy.clock import HouseholdClock
from policy.decisions import DecisionRequest, completed_today, consumed_today, context_for, decide
from policy.groups import SiteGroups
from policy.store import PolicyStore
from proxy import bypass
from proxy.decision import recognize

SAMPLE = ROOT / "config" / "policy.toml"
BYPASS = ROOT / "config" / "bypass.txt"
ZONE = ZoneInfo("America/Toronto")
YOUTUBE = "https://www.youtube.com/watch?v=abc"
CLASSROOM = "https://classroom.google.com/u/0/h"
OTHER = "https://example.org/"
PLACEHOLDER = config.load(SAMPLE).revision_task

BEDTIME = {"action": "deny", "status": 403, "message": "It's bedtime."}
CLOSED = {"action": "deny", "status": 403, "message": "YouTube is closed for today."}
REDIRECT = {"action": "redirect", "status": 302, "location": PLACEHOLDER}
ALLOW = {"action": "allow"}
TIME_UP = {"action": "deny", "status": 403, "message": "Time is up for today."}
INTERNET_CLOSED = {"action": "deny", "status": 403, "message": "The internet is closed for today."}

ENTERTAINMENT_PATTERNS = {
    "*.youtube.com",
    "youtu.be",
    "*.youtube-nocookie.com",
    "*.googlevideo.com",
    "*.ytimg.com",
    "youtubei.googleapis.com",
}


def _quiet(_message):
    return None


def _at(hour: int, minute: int = 0, day: int = 21) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=ZONE)


def _loaded():
    store = PolicyStore(":memory:")
    config.apply(config.load(SAMPLE), store, warn=_quiet)
    return store


def _decide(store: PolicyStore, moment: datetime, url: str, ip: str | None = None):
    client = store.clients()[0]
    context = context_for(
        DecisionRequest(ip or client.ips[0], "GET", url, moment),
        HouseholdClock(ZONE),
        ClientDirectory(store.clients()),
        SiteGroups(store.groups()),
    )
    decision = json.loads(
        decide(
            context,
            revision_task=store.revision_task(),
            completed=completed_today(store, context),
            consumed=consumed_today(store, context),
        )
    )
    return context, decision


def test_wednesday_is_the_day_the_schedule_uses():
    assert _at(6, 30).weekday() == 2


def test_the_sample_stores_one_client_three_groups_and_a_two_hour_quota():
    text = SAMPLE.read_text(encoding="utf-8")
    assert text.count('quota = "2h"') == 1
    with _loaded() as store:
        assert [client.name for client in store.clients()] == ["Younger child"]
        assert store.clients()[0].ips == ("192.168.1.40",)
        groups = {group.name: group for group in store.groups()}
        assert set(groups) == {"School work", "Entertainment", "Everything else"}
        assert groups["Everything else"].default
        assert groups["School work"].quota is None
        assert groups["Everything else"].quota is None
        assert groups["Entertainment"].quota == 2 * 60 * 60
        assert ENTERTAINMENT_PATTERNS <= set(groups["Entertainment"].patterns)
        assert groups["Entertainment"].rules[3].requirement.required == 2
        assert groups["Everything else"].rules[3].requirement.required == 2
        assert not any(rule.condition == "quota_remaining" for rule in groups["Everything else"].rules)
        assert not any(rule.condition == "quota_remaining" for rule in groups["School work"].rules)


@pytest.mark.parametrize(
    ("url", "group"),
    [
        ("https://www.youtube.com/watch?v=abc", "Entertainment"),
        ("https://youtube.com/watch?v=abc", "Entertainment"),
        ("https://youtu.be/abc", "Entertainment"),
        ("https://www.youtube-nocookie.com/embed/abc", "Entertainment"),
        ("https://r1---sn.googlevideo.com/videoplayback", "Entertainment"),
        ("https://i.ytimg.com/vi/abc/hqdefault.jpg", "Entertainment"),
        ("https://youtubei.googleapis.com/youtubei/v1/player", "Entertainment"),
        (CLASSROOM, "School work"),
        ("https://docs.google.com/document/d/abc", "School work"),
        (OTHER, "Everything else"),
    ],
)
def test_the_sample_classifies_the_worked_urls(url, group):
    with _loaded() as store:
        assert SiteGroups(store.groups()).classify(url).name == group


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (6, 30, BEDTIME),
        (10, 0, REDIRECT),
        (16, 0, REDIRECT),
        (20, 0, CLOSED),
    ],
)
def test_wednesday_youtube_matches_the_worked_example(hour, minute, expected):
    with _loaded() as store:
        assert len(store.clients()) == 1
        context, decision = _decide(store, _at(hour, minute), YOUTUBE)
        assert context.client.name == "Younger child"
        assert context.client.ips == ("192.168.1.40",)
        assert context.group.name == "Entertainment"
        assert decision == expected
        assert recognize(decision) == decision


def test_wednesday_morning_classroom_is_allowed():
    with _loaded() as store:
        context, decision = _decide(store, _at(10, 0), CLASSROOM)
        assert context.client.name == "Younger child"
        assert context.group.name == "School work"
        assert decision == ALLOW
        _, early = _decide(store, _at(6, 30), CLASSROOM)
        assert early == ALLOW
        _, docs = _decide(store, _at(10, 0), "https://docs.google.com/document/d/abc")
        assert docs == ALLOW


def test_an_unmatched_url_uses_the_default_groups_rules():
    with _loaded() as store:
        morning, morning_decision = _decide(store, _at(10, 0), OTHER)
        assert morning.group.name == "Everything else"
        assert morning.group.default
        assert morning_decision == REDIRECT
        evening, evening_decision = _decide(store, _at(20, 0), OTHER)
        assert evening.group.name == "Everything else"
        assert evening_decision == INTERNET_CLOSED
        _, youtube = _decide(store, _at(20, 0), YOUTUBE)
        assert youtube == CLOSED


def test_the_default_group_has_no_quota_when_entertainment_is_used_up():
    with _loaded() as store:
        client_id = store.clients()[0].id
        store.set_task_completions(client_id, _at(16).date(), 2)
        start = _at(8)
        for index in range(24):
            store.mark_bucket(client_id, "Entertainment", start + timedelta(minutes=5) * index)
        _, youtube = _decide(store, _at(16), YOUTUBE)
        assert youtube == TIME_UP
        context, other = _decide(store, _at(16), OTHER)
        assert context.group.name == "Everything else"
        assert other == ALLOW


@pytest.mark.parametrize("day", [23, 24, 25])
def test_friday_to_sunday_evening_stays_open_later_than_wednesday(day):
    assert _at(20, day=day).weekday() in {4, 5, 6}
    with _loaded() as store:
        _, wednesday = _decide(store, _at(20), YOUTUBE)
        assert wednesday == CLOSED
        _, evening = _decide(store, _at(20, day=day), YOUTUBE)
        assert evening == REDIRECT


def test_loading_the_sample_twice_does_not_duplicate_groups_or_clients():
    tables = ("clients", "site_groups", "site_group_patterns", "rules", "rule_windows", "rule_actions")
    with _loaded() as store:
        client_id = store.clients()[0].id
        group_ids = dict(store.connection.execute("SELECT name, id FROM site_groups"))
        counts = {
            table: store.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in tables
        }
        config.apply(config.load(SAMPLE), store, warn=_quiet)
        assert store.clients()[0].id == client_id
        assert dict(store.connection.execute("SELECT name, id FROM site_groups")) == group_ids
        assert len(store.clients()) == 1
        assert len(store.groups()) == 3
        again = {
            table: store.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in tables
        }
        assert again == counts


def test_the_bypass_list_names_the_school_work_hosts_and_the_task_site():
    sample = config.load(SAMPLE)
    school = next(group for group in sample.groups if group.name == "School work")
    patterns = bypass.load_patterns(BYPASS)
    host = urlsplit(sample.revision_task).hostname
    assert set(patterns) == set(school.patterns) | {host}
    assert bypass.is_bypassed("classroom.google.com", patterns)
    assert bypass.is_bypassed("docs.google.com", patterns)
    assert bypass.is_bypassed("lh3.googleusercontent.com", patterns)
    assert bypass.is_bypassed(host, patterns)
    assert not bypass.is_bypassed("www.youtube.com", patterns)
    assert not bypass.is_bypassed("youtubei.googleapis.com", patterns)
