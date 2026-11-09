"""S008.4 and S007.4: the usage report slices by site group, client group, or quota."""

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from asgi import call, session_cookie  # noqa: E402
from policy.accounts import Accounts  # noqa: E402
from policy.clock import HouseholdClock  # noqa: E402
from policy.hierarchy import load  # noqa: E402
from policy.report import format_byte_limit, usage_report  # noqa: E402
from policy.usage import UsageStore, observe  # noqa: E402

SYDNEY = ZoneInfo("Australia/Sydney")
PASSWORD = "secret"
YOUTUBE = "https://www.youtube.com/watch?v=abc"
CLASSROOM = "https://classroom.google.com/u/0/h"
UNKNOWN_SITE = "https://example.com/page"
YOUNGER = "192.0.2.40"
OLDER = "192.0.2.41"
UNKNOWN = "192.0.2.99"

HOUSE = """\
timezone: Australia/Sydney
bucket_length: 5m
entry: entry

client_groups:
  younger:
    addresses: ["192.0.2.40"]
  older:
    addresses: ["192.0.2.41"]

site_groups:
  school:
    priority: 10
    patterns:
      - classroom.google.com
  entertainment:
    priority: 30
    patterns:
      - "*.youtube.com"

quotas:
  entertainment:
    time: 2h
    bytes: 1k
    ruleset: entertainment_meter
  notes:
    ruleset: entertainment_meter

rule_sets:
  entry:
    - condition: always
      when_true: { action: allow }
  entertainment_meter:
    - condition: site_group
      group: entertainment
      when_true: { action: continue }
      when_false: { action: deny, message: "Not entertainment." }
"""


def _load(directory: Path, text: str = HOUSE):
    path = directory / "policy.yaml"
    path.write_text(text, encoding="utf-8")
    loaded = load(path)
    assert loaded is not None
    return loaded


def _at(hour: int, minute: int = 0, second: int = 0, day: int = 21) -> datetime:
    return datetime(2026, 10, day, hour, minute, second, tzinfo=SYDNEY)


def _clock() -> HouseholdClock:
    return HouseholdClock(SYDNEY)


def _report(moment: datetime, *, ip: str = YOUNGER, url: str = YOUTUBE, nbytes: int = 100) -> dict:
    return {"client_ip": ip, "url": url, "occurred_at": moment.isoformat(), "bytes": nbytes}


def _observe(policy, usage: UsageStore, moment: datetime, **kwargs) -> None:
    assert observe(policy, usage, _clock(), _report(moment, **kwargs))


def _usage(policy, usage: UsageStore, now: datetime, query: dict) -> dict:
    return usage_report(policy, usage, query, now)


def _text(value) -> str:
    return json.dumps(value)


def _day(data: dict, heading: str) -> dict:
    return next(day for day in data["report"]["days"] if day["heading"] == heading)


def _whens(day: dict) -> list[str]:
    return [row["when"] for row in day["rows"]]


def _empty_days(data: dict) -> int:
    return sum(1 for day in data["report"]["days"] if not day["rows"])


def test_the_site_group_report_shows_the_local_day_including_school(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        local = datetime(2026, 10, 22, 0, 32, tzinfo=SYDNEY)
        utc = local.astimezone(timezone.utc)
        assert utc.strftime("%H:%M") != "00:32"
        _observe(policy, usage, utc, nbytes=100)
        _observe(policy, usage, local.replace(minute=33), nbytes=40)
        _observe(policy, usage, _at(9, 2, day=22), url=CLASSROOM, nbytes=50)
        now = _at(12, day=22)
        data = _usage(policy, usage, now, {"view": "site", "client": "younger", "site": "entertainment"})
        assert data["times"] == "Times are Australia/Sydney."
        assert utc.strftime("%H:%M") not in _text(data)
        assert data["chosen"]["view"] == "site"
        assert data["report"]["heading"] == "younger, entertainment"
        thursday = _day(data, "Thursday 22 October 2026")
        assert thursday["rows"] == [{"when": "00:30 to 00:35", "time": "5m", "bytes": "140 bytes"}]
        assert thursday["summary"] == "Counted time: 5m."
        assert _day(data, "Wednesday 21 October 2026")["rows"] == []

        school = _usage(policy, usage, now, {"view": "site", "client": "younger", "site": "school"})
        school_day = _day(school, "Thursday 22 October 2026")
        assert school_day["rows"] == [{"when": "09:00 to 09:05", "time": "5m", "bytes": "50 bytes"}]

        quota = _usage(policy, usage, now, {"view": "quota", "quota": "entertainment", "client": "younger"})
        assert quota["report"]["lines"] == ["Ended time: 5m of 2h.", "Stored bytes: 140 bytes of 1 KB."]
        assert "50 bytes" not in _text(quota)


def test_the_client_group_view_shows_the_same_buckets_with_their_site_group(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        _observe(policy, usage, _at(9, 2), url=CLASSROOM, nbytes=50)
        _observe(policy, usage, _at(15, 2), nbytes=90)
        _observe(policy, usage, _at(16, 2), ip=OLDER, nbytes=20)
        now = _at(17)
        data = _usage(policy, usage, now, {"view": "client", "client": "younger"})
        assert data["report"]["site_column"] is True
        wednesday = _day(data, "Wednesday 21 October 2026")
        assert wednesday["rows"] == [
            {"when": "09:00 to 09:05", "time": "5m", "bytes": "50 bytes", "site": "school"},
            {"when": "15:00 to 15:05", "time": "5m", "bytes": "90 bytes", "site": "entertainment"},
        ]
        assert wednesday["summary"] == "Counted time: 10m."
        assert "16:00" not in _text(data)

        older = _usage(policy, usage, now, {"view": "client", "client": "older"})
        assert _whens(_day(older, "Wednesday 21 October 2026")) == ["16:00 to 16:05"]
        assert "20 bytes" in _text(older)

        site = _usage(policy, usage, now, {"view": "site", "client": "younger", "site": "entertainment"})
        assert site["report"]["site_column"] is False
        assert _day(site, "Wednesday 21 October 2026")["rows"] == [
            {"when": "15:00 to 15:05", "time": "5m", "bytes": "90 bytes"}
        ]


def test_a_quota_shows_ended_time_and_bytes_and_yesterday_stays_yesterday(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        _observe(policy, usage, _at(15, 2, day=20), nbytes=20)
        noon = _at(12, day=21)
        before = _usage(policy, usage, noon, {"view": "quota", "quota": "entertainment", "client": "younger"})
        report = before["report"]
        assert report["kind"] == "quota"
        assert report["day"] == "Wednesday 21 October 2026"
        assert report["limits"] == ["Time limit: 2h.", "Byte limit: 1 KB."]
        assert report["lines"] == ["Ended time: 0s of 2h.", "Stored bytes: 0 bytes of 1 KB."]
        listed = _usage(policy, usage, noon, {"view": "quota", "quota": "entertainment"})
        assert listed["report"]["kind"] == "balances"
        assert listed["report"]["rows"] == [{"client": "younger", "time": "0s of 2h.", "bytes": "0 bytes of 1 KB."}]

        history = _usage(policy, usage, noon, {"view": "site", "client": "younger", "site": "entertainment"})
        tuesday = _day(history, "Tuesday 20 October 2026")
        assert tuesday["rows"] == [{"when": "15:00 to 15:05", "time": "5m", "bytes": "20 bytes"}]
        assert _day(history, "Wednesday 21 October 2026")["rows"] == []

        _observe(policy, usage, _at(15, 0, 1), nbytes=80)
        early = _usage(policy, usage, _at(15, 4), {"view": "quota", "quota": "entertainment", "client": "younger"})
        assert early["report"]["lines"] == ["Ended time: 0s of 2h.", "Stored bytes: 80 bytes of 1 KB."]
        open_day = _usage(policy, usage, _at(15, 4), {"view": "site", "client": "younger", "site": "entertainment"})
        wednesday = _day(open_day, "Wednesday 21 October 2026")
        assert wednesday["rows"] == [{"when": "15:00 to 15:05", "time": "5m, not counted yet", "bytes": "80 bytes"}]
        assert wednesday["summary"] == "Counted time: none yet."

        ended = _usage(policy, usage, _at(15, 5), {"view": "quota", "quota": "entertainment", "client": "younger"})
        assert ended["report"]["lines"] == ["Ended time: 5m of 2h.", "Stored bytes: 80 bytes of 1 KB."]


def test_a_zero_limit_is_shown(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        now = _at(12)
        quiet = _usage(policy, usage, now, {"view": "quota", "quota": "notes", "client": "younger"})
        assert quiet["report"]["limits"] == ["Time limit: 0s.", "Byte limit: 0 bytes."]
        assert quiet["report"]["lines"] == ["Ended time: 0s of 0s.", "Stored bytes: 0 bytes of 0 bytes."]
        empty = _usage(policy, usage, now, {"view": "quota", "quota": "notes"})
        assert empty["report"]["limits"] == ["Time limit: 0s.", "Byte limit: 0 bytes."]
        assert empty["report"]["rows"] == []
        assert empty["report"]["empty"] == "No client group has a balance."

        _observe(policy, usage, _at(15, 2), nbytes=80)
        used = _usage(policy, usage, _at(16), {"view": "quota", "quota": "notes", "client": "younger"})
        assert used["report"]["lines"] == ["Ended time: 5m of 0s.", "Stored bytes: 80 bytes of 0 bytes."]


def test_a_quota_without_a_client_lists_every_balance_including_default(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        _observe(policy, usage, _at(15, 2), nbytes=100)
        _observe(policy, usage, _at(15, 2), ip=UNKNOWN, nbytes=40)
        data = _usage(policy, usage, _at(16), {"view": "quota", "quota": "entertainment"})
        assert data["report"]["rows"] == [
            {"client": "default", "time": "5m of 2h.", "bytes": "40 bytes of 1 KB."},
            {"client": "younger", "time": "5m of 2h.", "bytes": "100 bytes of 1 KB."},
        ]


def test_nothing_chosen_asks_for_a_choice_and_the_choices_offer_default(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        now = _at(12)
        waiting = _usage(policy, usage, now, {})
        assert waiting["message"] == "Choose a site group, a client group, or a quota."
        assert waiting["report"] is None
        assert waiting["times"] == "Times are Australia/Sydney."
        assert waiting["choices"] == {
            "clients": ["younger", "older", "default"],
            "sites": ["school", "entertainment", "default"],
            "quotas": ["entertainment", "notes"],
        }

        page = _usage(policy, usage, now, {"view": "site", "client": "younger", "site": "entertainment"})
        assert _empty_days(page) == 14
        assert all(day["summary"] is None for day in page["report"]["days"])
        assert page["message"] is None

        missing_client = _usage(policy, usage, now, {"view": "site", "site": "school"})
        assert missing_client["message"] == "Choose a client group and a site group."
        assert missing_client["report"] is None
        assert _usage(policy, usage, now, {"view": "client"})["message"] == "Choose a client group."
        missing_quota = _usage(policy, usage, now, {"view": "quota"})
        assert missing_quota["message"] == "Choose a quota."
        assert missing_quota["report"] is None


def test_default_is_a_selectable_group_for_an_unknown_computer_and_site(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        _observe(policy, usage, _at(10, 2), ip=UNKNOWN, url=UNKNOWN_SITE, nbytes=30)
        now = _at(12)
        site = _usage(policy, usage, now, {"view": "site", "client": "default", "site": "default"})
        wednesday = _day(site, "Wednesday 21 October 2026")
        assert wednesday["rows"] == [{"when": "10:00 to 10:05", "time": "5m", "bytes": "30 bytes"}]
        assert wednesday["summary"] == "Counted time: 5m."
        client = _usage(policy, usage, now, {"view": "client", "client": "default"})
        assert _day(client, "Wednesday 21 October 2026")["rows"] == [
            {"when": "10:00 to 10:05", "time": "5m", "bytes": "30 bytes", "site": "default"}
        ]
        alone = _usage(policy, usage, now, {"view": "quota", "quota": "entertainment"})
        assert alone["report"]["rows"] == []

        _observe(policy, usage, _at(11, 2), ip=UNKNOWN, nbytes=70)
        both = _usage(policy, usage, now, {"view": "client", "client": "default"})
        assert _whens(_day(both, "Wednesday 21 October 2026")) == ["10:00 to 10:05", "11:00 to 11:05"]
        quota = _usage(policy, usage, now, {"view": "quota", "quota": "entertainment"})
        assert quota["report"]["rows"] == [{"client": "default", "time": "5m of 2h.", "bytes": "70 bytes of 1 KB."}]


def test_an_open_bucket_a_midnight_bucket_and_an_old_bucket(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        _observe(policy, usage, _at(15, 0, 1), nbytes=80)
        query = {"view": "site", "client": "younger", "site": "entertainment"}
        early = _usage(policy, usage, _at(15, 4), query)
        assert "not counted yet" in _text(early)
        assert _day(early, "Wednesday 21 October 2026")["summary"] == "Counted time: none yet."
        assert _empty_days(early) == 13
        later = _usage(policy, usage, _at(15, 5), query)
        assert _day(later, "Wednesday 21 October 2026")["rows"][0]["time"] == "5m"
        assert _day(later, "Wednesday 21 October 2026")["summary"] == "Counted time: 5m."

        _observe(policy, usage, _at(23, 57), nbytes=7)
        next_day = _usage(policy, usage, _at(12, day=22), {"view": "client", "client": "younger"})
        assert _day(next_day, "Thursday 22 October 2026")["rows"] == []
        assert "23:55 to 24:00" in _whens(_day(next_day, "Wednesday 21 October 2026"))

        _observe(policy, usage, _at(10, 2, day=8), nbytes=5)
        _observe(policy, usage, _at(11, 2, day=9), nbytes=6)
        fortnight = _usage(policy, usage, _at(12, day=22), query)
        headings = [day["heading"] for day in fortnight["report"]["days"]]
        assert headings[-1] == "Friday 9 October 2026"
        assert "Thursday 8 October 2026" not in headings
        assert _whens(_day(fortnight, "Friday 9 October 2026")) == ["11:00 to 11:05"]
        assert "10:00" not in _text(fortnight)


def test_an_unknown_choice_is_not_an_empty_report(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        now = _at(12)
        for query, message in (
            ({"view": "site", "client": "nope", "site": "entertainment"}, "That client group is not in the household."),
            ({"view": "site", "client": "younger", "site": "nope"}, "That site group is not in the household."),
            ({"view": "quota", "quota": "nope"}, "That quota is not in the household."),
            ({"view": "quota", "quota": "entertainment", "client": "nope"}, "That client group is not in the household."),
        ):
            data = _usage(policy, usage, now, query)
            assert data["message"] == message
            assert data["report"] is None


def test_names_come_back_as_they_are_and_an_unset_timezone_is_the_machines(tmp_path):
    policy = _load(
        tmp_path,
        """\
timezone: Australia/Sydney
bucket_length: 5m
entry: entry
client_groups:
  "A<b>":
    addresses: ["192.0.2.40"]
site_groups:
  "School <work>":
    priority: 10
    patterns: ["classroom.google.com"]
quotas:
  "you<tube>":
    ruleset: meter
rule_sets:
  entry:
    - condition: always
      when_true: { action: allow }
  meter:
    - condition: always
      when_true: { action: deny, message: "No." }
""",
    )
    with UsageStore(":memory:") as usage:
        data = _usage(policy, usage, _at(12), {"view": "site", "client": "A<b>", "site": "School <work>"})
        assert data["report"]["heading"] == "A<b>, School <work>"
        assert _empty_days(data) == 14
        quota = _usage(policy, usage, _at(12), {"view": "quota", "quota": "you<tube>"})
        assert quota["report"]["heading"] == "you<tube>"
        assert quota["report"]["limits"][0] == "Time limit: 0s."

    plain = _load(tmp_path, HOUSE.replace("timezone: Australia/Sydney\n", ""))
    with UsageStore(":memory:") as usage:
        data = _usage(plain, usage, _at(12), {})
        assert data["times"] == "Times are the timezone of this machine."


def test_a_missing_policy_still_offers_default():
    with UsageStore(":memory:") as usage:
        data = _usage(None, usage, _at(12), {})
        assert data["message"] == "Choose a site group, a client group, or a quota."
        assert data["choices"]["clients"] == ["default"]
        assert data["times"] == "Times are the timezone of this machine."
        missing = _usage(None, usage, _at(12), {"view": "quota", "quota": "entertainment"})
        assert missing["message"] == "That quota is not in the household."
        assert missing["report"] is None


@pytest.mark.parametrize(
    ("count", "shown"),
    [
        (0, "0 bytes"),
        (1, "1 byte"),
        (1000, "1,000 bytes"),
        (1024, "1 KB"),
        (1500, "1,500 bytes"),
        (2 * 1024, "2 KB"),
        (500 * 1024**2, "500 MB"),
        (1024**3, "1 GB"),
        (2 * 1024**4, "2 TB"),
        (1024**4 + 1024, "1,073,741,825 KB"),
    ],
)
def test_a_byte_limit_is_shown_in_the_largest_whole_unit(count, shown):
    assert format_byte_limit(count) == shown


def test_the_service_serves_the_report_only_to_a_signed_in_parent(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(HOUSE, encoding="utf-8")
    database = tmp_path / "policy.sqlite3"
    monkeypatch.setenv("POLICY_FILE", str(policy_path))
    monkeypatch.setenv("POLICY_DB", str(database))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    monkeypatch.delenv("PARENT_IDLE", raising=False)
    monkeypatch.delenv("PARENT_LIFETIME", raising=False)
    query = "view=site&client=younger&site=entertainment"
    closed = create_app()
    status, body, headers = call(closed, "GET", "/parent/api/usage", query=query)
    assert status == 403
    assert json.loads(body)["closed"] is True
    assert "younger" not in body
    assert headers["cache-control"] == ["no-store"]

    Accounts(sqlite3.connect(database)).set_password("parent", PASSWORD)
    app = create_app()
    policy = load(policy_path)
    with UsageStore(database) as usage:
        observe(policy, usage, _clock(), _report(datetime.now(SYDNEY), nbytes=140))
    status, body, _headers = call(app, "GET", "/parent/api/usage", query=query)
    assert status == 401
    assert "140" not in body
    assert "younger" not in body

    status, _body, headers = call(
        app, "POST", "/parent/api/login", json_body={"username": "parent", "password": PASSWORD}
    )
    assert status == 200
    status, body, headers = call(app, "GET", "/parent/api/usage", query=query, cookie=session_cookie(headers))
    assert status == 200
    data = json.loads(body)
    assert data["report"]["heading"] == "younger, entertainment"
    assert "140 bytes" in body
    assert data["chosen"] == {"view": "site", "client": "younger", "site": "entertainment", "quota": ""}
    assert headers["cache-control"] == ["no-store"]
