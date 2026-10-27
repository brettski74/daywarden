"""S008.5: the household policy file is the YAML schedule the service loads."""

import asyncio
import json
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy.engine import MemoryLedger, classify_site, decide  # noqa: E402
from policy.hierarchy import load  # noqa: E402
from proxy import bypass  # noqa: E402

SAMPLE = ROOT / "config" / "policy.yaml"
BYPASS = ROOT / "config" / "bypass.txt"
ZONE = ZoneInfo("America/Toronto")
YOUNGER = "192.168.1.40"
UNKNOWN = "192.168.1.99"
YOUTUBE = "https://www.youtube.com/watch?v=abc"
CLASSROOM = "https://classroom.google.com/u/0/h"
OTHER = "https://example.org/"
WEDNESDAY = date(2026, 10, 21)

BEDTIME = {"action": "deny", "status": 403, "message": "It's bedtime."}
CLOSED = {"action": "deny", "status": 403, "message": "YouTube is closed for today."}
REDIRECT = {"action": "redirect", "status": 302, "location": "http://192.168.1.10:8080/tasks/next"}
ALLOW = {"action": "allow"}
TIME_UP = {"action": "deny", "status": 403, "message": "Time is up for today."}
INTERNET_CLOSED = {"action": "deny", "status": 403, "message": "The internet is closed for today."}
NO_RULE = {"action": "deny", "status": 403, "message": "No rule granted access."}


def _policy():
    loaded = load(SAMPLE)
    assert loaded is not None
    return loaded


def _at(hour: int, minute: int = 0, day: int = 21) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=ZONE)


def _decide(moment: datetime, url: str, ip: str = YOUNGER, ledger=None):
    return decide(_policy(), client_ip=ip, url=url, at=moment, ledger=ledger)


def test_wednesday_is_the_day_the_schedule_uses():
    assert _at(6, 30).weekday() == 2


def test_the_file_enrols_the_younger_child_and_a_two_hour_entertainment_quota():
    text = SAMPLE.read_text(encoding="utf-8")
    assert "time: 2h" in text
    assert "suggestion" in text
    policy = _policy()
    assert [group.name for group in policy.client_groups] == ["younger"]
    assert policy.client_groups[0].ips == (YOUNGER,)
    assert policy.site_group("default") is None
    assert policy.client_group("default") is None
    assert {group.name for group in policy.site_groups} == {"school", "entertainment"}
    quota = policy.quota("entertainment")
    assert quota is not None
    assert quota.time_limit == 2 * 60 * 60
    assert quota.byte_limit == 0
    assert policy.revision_task == REDIRECT["location"]


@pytest.mark.parametrize(
    ("url", "group"),
    [
        (YOUTUBE, "entertainment"),
        ("https://youtube.com/watch?v=abc", "entertainment"),
        ("https://youtu.be/abc", "entertainment"),
        ("https://www.youtube-nocookie.com/embed/abc", "entertainment"),
        ("https://r1---sn.googlevideo.com/videoplayback", "entertainment"),
        ("https://i.ytimg.com/vi/abc/hqdefault.jpg", "entertainment"),
        ("https://youtubei.googleapis.com/youtubei/v1/player", "entertainment"),
        (CLASSROOM, "school"),
        ("https://docs.google.com/document/d/abc", "school"),
        (OTHER, "default"),
    ],
)
def test_the_file_classifies_the_worked_urls(url, group):
    assert classify_site(_policy(), url) == group


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
    trace = _decide(_at(hour, minute), YOUTUBE)
    assert trace.client_group == "younger"
    assert trace.site_group == "entertainment"
    assert trace.decision == expected


def test_wednesday_morning_classroom_is_allowed():
    morning = _decide(_at(10, 0), CLASSROOM)
    assert morning.client_group == "younger"
    assert morning.site_group == "school"
    assert morning.decision == ALLOW
    assert _decide(_at(6, 30), CLASSROOM).decision == ALLOW
    assert _decide(_at(10, 0), "https://docs.google.com/document/d/abc").decision == ALLOW


def test_an_unmatched_url_uses_the_default_site_rules():
    morning = _decide(_at(10, 0), OTHER)
    assert morning.site_group == "default"
    assert morning.decision == REDIRECT
    evening = _decide(_at(20, 0), OTHER)
    assert evening.site_group == "default"
    assert evening.decision == INTERNET_CLOSED
    assert _decide(_at(20, 0), YOUTUBE).decision == CLOSED


def test_an_unknown_address_is_not_granted_access():
    classroom = _decide(_at(10, 0), CLASSROOM, ip=UNKNOWN)
    assert classroom.client_group == "default"
    assert classroom.decision == NO_RULE
    youtube = _decide(_at(16, 0), YOUTUBE, ip=UNKNOWN)
    assert youtube.client_group == "default"
    assert youtube.decision == NO_RULE


def test_twenty_four_ended_buckets_deny_youtube_and_leave_the_default_site_open():
    ledger = MemoryLedger()
    ledger.set_successes("younger", WEDNESDAY, 2)
    ready = _decide(_at(16, 0), YOUTUBE, ledger=ledger)
    assert ready.decision == ALLOW

    ledger.set_ended_seconds("younger", "entertainment", WEDNESDAY, 24 * 5 * 60)
    stopped = _decide(_at(16, 0), YOUTUBE, ledger=ledger)
    assert stopped.decision == TIME_UP
    other = _decide(_at(16, 0), OTHER, ledger=ledger)
    assert other.site_group == "default"
    assert other.decision == ALLOW


@pytest.mark.parametrize("day", [23, 24, 25])
def test_friday_to_sunday_evening_stays_open_later_than_wednesday(day):
    assert _at(20, day=day).weekday() in {4, 5, 6}
    assert _decide(_at(20), YOUTUBE).decision == CLOSED
    assert _decide(_at(20, day=day), YOUTUBE).decision == REDIRECT


def test_the_bypass_list_names_the_school_hosts_and_the_task_site():
    policy = _policy()
    school = policy.site_group("school")
    assert school is not None
    patterns = bypass.load_patterns(BYPASS)
    host = urlsplit(policy.revision_task).hostname
    assert set(patterns) == set(school.patterns) | {host}
    assert bypass.is_bypassed("classroom.google.com", patterns)
    assert bypass.is_bypassed("docs.google.com", patterns)
    assert bypass.is_bypassed("lh3.googleusercontent.com", patterns)
    assert bypass.is_bypassed(host, patterns)
    assert not bypass.is_bypassed("www.youtube.com", patterns)
    assert not bypass.is_bypassed("youtubei.googleapis.com", patterns)


def test_the_service_is_pointed_at_the_yaml_file():
    assert not (ROOT / "config" / "policy.toml").is_file()
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert compose.count("POLICY_FILE: ${POLICY_FILE:-/etc/smartproxy/policy.yaml}") == 2
    assert "policy.toml" not in compose
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "config/policy.yaml" in readme
    assert "docker compose restart decisions" in readme
    assert "[[groups.rules.windows]]" not in readme
    source = (ROOT / "policy" / "app.py").read_text(encoding="utf-8")
    assert 'os.environ.get("POLICY_FILE", "/etc/smartproxy/policy.yaml")' in source


def test_the_policy_service_answers_from_the_yaml_file(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    monkeypatch.setenv("POLICY_FILE", str(SAMPLE))
    monkeypatch.setenv("POLICY_DB", str(tmp_path / "policy.sqlite3"))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    monkeypatch.setenv("DECISION_FILE", str(tmp_path / "decision.json"))
    monkeypatch.setenv("DECISION_STUB", "1")
    monkeypatch.delenv("PARENT_PASSWORD", raising=False)
    (tmp_path / "decision.json").write_text(
        '{"action": "allow", "marker": "from the file"}',
        encoding="utf-8",
    )
    app = create_app()

    def post(document: dict) -> dict:
        status, body = _post(app, document)
        assert status == 200
        return json.loads(body)

    bedtime = post(_request(YOUNGER, "2026-10-21T06:30:00-04:00", YOUTUBE))
    assert bedtime == BEDTIME
    assert "from the file" not in json.dumps(bedtime)
    classroom = post(_request(YOUNGER, "2026-10-21T10:00:00-04:00", CLASSROOM))
    assert classroom == ALLOW
    unknown = post(_request(UNKNOWN, "2026-10-21T10:00:00-04:00", CLASSROOM))
    assert unknown == NO_RULE


def _request(client_ip: str, occurred_at: str, url: str) -> dict:
    return {
        "client_ip": client_ip,
        "method": "GET",
        "url": url,
        "occurred_at": occurred_at,
    }


def _post(app, document: dict) -> tuple[int, bytes]:
    messages: list[dict] = []
    body = json.dumps(document).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/decisions",
        "raw_path": b"/v1/decisions",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 1234),
        "server": ("127.0.0.1", 8090),
        "root_path": "",
    }
    asyncio.run(app(scope, receive, send))
    status = next(item["status"] for item in messages if item["type"] == "http.response.start")
    payload = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
    return status, payload
