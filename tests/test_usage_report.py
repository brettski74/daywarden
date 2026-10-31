"""S008.4: the usage report slices by site group, client group, or quota."""

import asyncio
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy.clock import HouseholdClock  # noqa: E402
from policy.accounts import Accounts  # noqa: E402
from policy.hierarchy import load  # noqa: E402
from policy.report import respond_hierarchy  # noqa: E402
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


def _accounts(usage: UsageStore) -> Accounts:
    accounts = Accounts(usage.connection)
    accounts.set_password("parent", PASSWORD)
    return accounts


def _token(page) -> str:
    header = dict(page.headers)["set-cookie"]
    value = header.split(";", 1)[0]
    name, token = value.split("=", 1)
    assert name == "parent_session"
    assert "HttpOnly" in header
    assert "Secure" in header
    assert "SameSite=Lax" in header
    assert "Path=/" in header
    return token


def _signed(policy, usage: UsageStore, now: datetime, query: dict) -> str:
    accounts = _accounts(usage)
    opened = respond_hierarchy(
        policy,
        usage,
        accounts,
        method="POST",
        query=query,
        cookie=None,
        form={"username": "parent", "password": PASSWORD},
        now=now,
    )
    assert opened.status == 303
    page = respond_hierarchy(
        policy,
        usage,
        accounts,
        method="GET",
        query=query,
        cookie=_token(opened),
        form={},
        now=now,
    )
    assert page.status == 200
    assert "Enter your username and password." not in page.body
    assert dict(page.headers)["cache-control"] == "no-store"
    return page.body


def _section(body: str, heading: str, following: str) -> str:
    _before, rest = body.split(heading, 1)
    section, _after = rest.split(following, 1)
    return section


def _select(body: str, element_id: str) -> str:
    return body.split(f'id="{element_id}"', 1)[1].split("</select>", 1)[0]


def test_the_site_group_page_shows_the_local_day_including_school(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        local = datetime(2026, 10, 22, 0, 32, tzinfo=SYDNEY)
        utc = local.astimezone(timezone.utc)
        assert utc.strftime("%H:%M") != "00:32"
        _observe(policy, usage, utc, nbytes=100)
        _observe(policy, usage, local.replace(minute=33), nbytes=40)
        _observe(policy, usage, _at(9, 2, day=22), url=CLASSROOM, nbytes=50)
        now = _at(12, day=22)
        body = _signed(
            policy,
            usage,
            now,
            {"view": "site", "client": "younger", "site": "entertainment"},
        )
        assert "Times are Australia/Sydney." in body
        assert utc.strftime("%H:%M") not in body
        assert 'value="site" selected' in body
        thursday = _section(body, "Thursday 22 October 2026", "Wednesday 21 October 2026")
        assert thursday.count("00:30 to 00:35") == 1
        assert "140 bytes" in thursday
        assert "<td>5m</td>" in thursday
        assert "Counted time: 5m." in thursday
        assert "09:00" not in thursday
        assert "50 bytes" not in thursday
        wednesday = _section(body, "Wednesday 21 October 2026", "Tuesday 20 October 2026")
        assert "no usage" in wednesday

        school = _signed(
            policy, usage, now, {"view": "site", "client": "younger", "site": "school"}
        )
        school_day = _section(school, "Thursday 22 October 2026", "Wednesday 21 October 2026")
        assert "09:00 to 09:05" in school_day
        assert "50 bytes" in school_day
        assert "00:30" not in school_day
        assert "140 bytes" not in school_day

        quota = _signed(
            policy,
            usage,
            now,
            {"view": "quota", "quota": "entertainment", "client": "younger"},
        )
        assert "Ended time: 5m of 2h." in quota
        assert "Stored bytes: 140 bytes of 1 KB." in quota
        assert "50 bytes" not in quota


def test_the_client_group_view_shows_the_same_buckets(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        _observe(policy, usage, _at(9, 2), url=CLASSROOM, nbytes=50)
        _observe(policy, usage, _at(15, 2), nbytes=90)
        _observe(policy, usage, _at(16, 2), ip=OLDER, nbytes=20)
        now = _at(17)
        body = _signed(policy, usage, now, {"view": "client", "client": "younger"})
        wednesday = _section(body, "Wednesday 21 October 2026", "Tuesday 20 October 2026")
        assert "09:00 to 09:05" in wednesday
        assert "school" in wednesday
        assert "50 bytes" in wednesday
        assert "15:00 to 15:05" in wednesday
        assert "entertainment" in wednesday
        assert "90 bytes" in wednesday
        assert "Counted time: 10m." in wednesday
        assert "<th>Site group</th>" in wednesday
        assert "16:00" not in body
        assert "20 bytes" not in body

        older = _signed(policy, usage, now, {"view": "client", "client": "older"})
        assert "16:00 to 16:05" in older
        assert "20 bytes" in older
        assert "15:00" not in older
        assert "09:00" not in older

        site = _signed(
            policy,
            usage,
            now,
            {"view": "site", "client": "younger", "site": "entertainment"},
        )
        assert "15:00 to 15:05" in site
        assert "90 bytes" in site
        assert "09:00" not in site
        assert "50 bytes" not in site


def test_a_quota_shows_ended_time_and_bytes_and_yesterday_stays_yesterday(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        _observe(policy, usage, _at(15, 2, day=20), nbytes=20)
        noon = _at(12, day=21)
        before = _signed(
            policy,
            usage,
            noon,
            {"view": "quota", "quota": "entertainment", "client": "younger"},
        )
        assert "Wednesday 21 October 2026" in before
        assert "Ended time: 0s of 2h." in before
        assert "Stored bytes: 0 bytes of 1 KB." in before
        assert "Time limit: 2h." in before
        assert "Byte limit: 1 KB." in before
        listed = _signed(policy, usage, noon, {"view": "quota", "quota": "entertainment"})
        table = listed.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
        assert "younger" in table
        assert "0s of 2h." in table
        assert "0 bytes of 1 KB." in table

        history = _signed(
            policy,
            usage,
            noon,
            {"view": "site", "client": "younger", "site": "entertainment"},
        )
        tuesday = _section(history, "Tuesday 20 October 2026", "Monday 19 October 2026")
        assert "15:00 to 15:05" in tuesday
        assert "20 bytes" in tuesday
        wednesday = _section(history, "Wednesday 21 October 2026", "Tuesday 20 October 2026")
        assert "no usage" in wednesday

        _observe(policy, usage, _at(15, 0, 1), nbytes=80)
        early = _signed(
            policy,
            usage,
            _at(15, 4),
            {"view": "quota", "quota": "entertainment", "client": "younger"},
        )
        assert "Ended time: 0s of 2h." in early
        assert "Stored bytes: 80 bytes of 1 KB." in early
        open_day = _signed(
            policy,
            usage,
            _at(15, 4),
            {"view": "site", "client": "younger", "site": "entertainment"},
        )
        assert "15:00 to 15:05" in open_day
        assert "not counted yet" in open_day
        assert "80 bytes" in open_day
        assert "Counted time: none yet." in open_day

        ended = _signed(
            policy,
            usage,
            _at(15, 5),
            {"view": "quota", "quota": "entertainment", "client": "younger"},
        )
        assert "Ended time: 5m of 2h." in ended
        assert "Stored bytes: 80 bytes of 1 KB." in ended


def test_a_zero_limit_is_shown(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        now = _at(12)
        quiet = _signed(policy, usage, now, {"view": "quota", "quota": "notes", "client": "younger"})
        assert "Time limit: 0s." in quiet
        assert "Byte limit: 0 bytes." in quiet
        assert "Ended time: 0s of 0s." in quiet
        assert "Stored bytes: 0 bytes of 0 bytes." in quiet
        assert "Traceback" not in quiet
        empty = _signed(policy, usage, now, {"view": "quota", "quota": "notes"})
        assert "Time limit: 0s." in empty
        assert "Byte limit: 0 bytes." in empty
        assert "No client group has a balance." in empty

        _observe(policy, usage, _at(15, 2), nbytes=80)
        used = _signed(
            policy, usage, _at(16), {"view": "quota", "quota": "notes", "client": "younger"}
        )
        assert "Time limit: 0s." in used
        assert "Byte limit: 0 bytes." in used
        assert "Ended time: 5m of 0s." in used
        assert "Stored bytes: 80 bytes of 0 bytes." in used


def test_a_quota_without_a_client_lists_every_balance_including_default(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        _observe(policy, usage, _at(15, 2), nbytes=100)
        _observe(policy, usage, _at(15, 2), ip=UNKNOWN, nbytes=40)
        body = _signed(policy, usage, _at(16), {"view": "quota", "quota": "entertainment"})
        table = body.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
        assert table.index("default") < table.index("younger")
        assert "older" not in table
        assert "40 bytes of 1 KB." in table
        assert "100 bytes of 1 KB." in table
        assert "5m of 2h." in table
        assert "Ended time" in body
        assert "Stored bytes" in body


def test_a_quiet_day_is_no_usage_and_the_chooser_offers_default(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        now = _at(12)
        waiting = _signed(policy, usage, now, {})
        assert "Choose a site group, a client group, or a quota." in waiting
        assert "no usage" not in waiting
        assert "Times are Australia/Sydney." in waiting
        client = _select(waiting, "client")
        site = _select(waiting, "site")
        quota = _select(waiting, "quota")
        assert client.index("younger") < client.index("older") < client.index('value="default"')
        assert site.index("school") < site.index("entertainment") < site.index('value="default"')
        assert quota.index("entertainment") < quota.index("notes")

        page = _signed(
            policy,
            usage,
            now,
            {"view": "site", "client": "younger", "site": "entertainment"},
        )
        assert page.count("no usage") == 14
        assert "Counted time" not in page
        assert "Traceback" not in page
        assert "Choose a client group and a site group." not in page

        missing_client = _signed(policy, usage, now, {"view": "site", "site": "school"})
        assert "Choose a client group and a site group." in missing_client
        assert "no usage" not in missing_client
        missing_group = _signed(policy, usage, now, {"view": "client"})
        assert "Choose a client group." in missing_group
        missing_quota = _signed(policy, usage, now, {"view": "quota"})
        assert "Choose a quota." in missing_quota
        assert "no usage" not in missing_quota


def test_default_is_a_selectable_group_for_an_unknown_computer_and_site(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        _observe(policy, usage, _at(10, 2), ip=UNKNOWN, url=UNKNOWN_SITE, nbytes=30)
        now = _at(12)
        site = _signed(
            policy, usage, now, {"view": "site", "client": "default", "site": "default"}
        )
        assert "10:00 to 10:05" in site
        assert "30 bytes" in site
        assert "Counted time: 5m." in site
        client = _signed(policy, usage, now, {"view": "client", "client": "default"})
        assert "10:00 to 10:05" in client
        assert "30 bytes" in client
        assert "default" in _section(client, "Wednesday 21 October 2026", "Tuesday 20 October 2026")
        alone = _signed(policy, usage, now, {"view": "quota", "quota": "entertainment"})
        assert "No client group has a balance." in alone

        _observe(policy, usage, _at(11, 2), ip=UNKNOWN, nbytes=70)
        both = _signed(policy, usage, now, {"view": "client", "client": "default"})
        wednesday = _section(both, "Wednesday 21 October 2026", "Tuesday 20 October 2026")
        assert "10:00 to 10:05" in wednesday
        assert "11:00 to 11:05" in wednesday
        assert "70 bytes" in wednesday
        quota = _signed(policy, usage, now, {"view": "quota", "quota": "entertainment"})
        table = quota.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
        assert "default" in table
        assert "70 bytes of 1 KB." in table
        assert "30 bytes" not in table


def test_an_open_bucket_a_midnight_bucket_and_an_old_bucket(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        _observe(policy, usage, _at(15, 0, 1), nbytes=80)
        early = _signed(
            policy,
            usage,
            _at(15, 4),
            {"view": "site", "client": "younger", "site": "entertainment"},
        )
        assert "not counted yet" in early
        assert "Counted time: none yet." in early
        assert early.count("no usage") == 13
        later = _signed(
            policy,
            usage,
            _at(15, 5),
            {"view": "site", "client": "younger", "site": "entertainment"},
        )
        assert "<td>5m</td>" in later
        assert "not counted yet" not in later
        assert "Counted time: 5m." in later

        _observe(policy, usage, _at(23, 57), nbytes=7)
        next_day = _signed(
            policy,
            usage,
            _at(12, day=22),
            {"view": "client", "client": "younger"},
        )
        thursday = _section(next_day, "Thursday 22 October 2026", "Wednesday 21 October 2026")
        assert "no usage" in thursday
        assert "23:55" not in thursday
        wednesday = _section(next_day, "Wednesday 21 October 2026", "Tuesday 20 October 2026")
        assert "23:55 to 24:00" in wednesday
        assert "7 bytes" in wednesday

        _observe(policy, usage, _at(10, 2, day=8), nbytes=5)
        _observe(policy, usage, _at(11, 2, day=9), nbytes=6)
        fortnight = _signed(
            policy,
            usage,
            _at(12, day=22),
            {"view": "site", "client": "younger", "site": "entertainment"},
        )
        assert "Friday 9 October 2026" in fortnight
        assert "11:00 to 11:05" in fortnight
        assert "Thursday 8 October 2026" not in fortnight
        assert "10:00" not in fortnight


def test_an_unknown_choice_is_not_an_empty_report(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        now = _at(12)
        missing_client = _signed(
            policy,
            usage,
            now,
            {"view": "site", "client": "nope", "site": "entertainment"},
        )
        assert "That client group is not in the household." in missing_client
        assert "no usage" not in missing_client
        missing_site = _signed(
            policy, usage, now, {"view": "site", "client": "younger", "site": "nope"}
        )
        assert "That site group is not in the household." in missing_site
        assert "no usage" not in missing_site
        missing_quota = _signed(policy, usage, now, {"view": "quota", "quota": "nope"})
        assert "That quota is not in the household." in missing_quota
        assert "Time limit" not in missing_quota
        missing_on_quota = _signed(
            policy,
            usage,
            now,
            {"view": "quota", "quota": "entertainment", "client": "nope"},
        )
        assert "That client group is not in the household." in missing_on_quota
        assert "Ended time" not in missing_on_quota


def test_names_are_escaped_and_an_unset_timezone_is_the_machines(tmp_path):
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
        body = _signed(
            policy,
            usage,
            _at(12),
            {"view": "site", "client": "A<b>", "site": "School <work>"},
        )
        assert "A<b>" not in body
        assert "School <work>" not in body
        assert body.count("A&lt;b&gt;") >= 2
        assert body.count("School &lt;work&gt;") >= 2
        assert body.count("no usage") == 14
        quota = _signed(policy, usage, _at(12), {"view": "quota", "quota": "you<tube>"})
        assert "you<tube>" not in quota
        assert "you&lt;tube&gt;" in quota
        assert "Time limit: 0s." in quota

    plain = _load(tmp_path, HOUSE.replace("timezone: Australia/Sydney\n", ""))
    with UsageStore(":memory:") as usage:
        body = _signed(plain, usage, _at(12), {})
        assert "Times are the timezone of this machine." in body
        assert "Australia/Sydney" not in body


def test_a_missing_policy_still_offers_default():
    with UsageStore(":memory:") as usage:
        body = _signed(None, usage, _at(12), {})
        assert "Choose a site group, a client group, or a quota." in body
        assert 'value="default"' in body
        assert "Times are the timezone of this machine." in body
        missing = _signed(None, usage, _at(12), {"view": "quota", "quota": "entertainment"})
        assert "That quota is not in the household." in missing
        assert "no usage" not in missing


def test_without_an_account_the_page_is_closed(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        _observe(policy, usage, _at(0, 32, day=22), nbytes=140)
        now = _at(12, day=22)
        query = {"view": "site", "client": "younger", "site": "entertainment"}
        accounts = Accounts(usage.connection)
        page = respond_hierarchy(
            policy, usage, accounts, method="GET", query=query, cookie=None, form={}, now=now
        )
        assert page.status == 403
        assert "This page is closed until a parent account is added." in page.body
        assert "younger" not in page.body
        assert "school" not in page.body
        assert "entertainment" not in page.body
        assert "00:30" not in page.body
        assert "140" not in page.body
        assert "<option" not in page.body
        assert dict(page.headers)["cache-control"] == "no-store"
        posted = respond_hierarchy(
            policy,
            usage,
            accounts,
            method="POST",
            query=query,
            cookie=None,
            form={"username": "parent", "password": PASSWORD},
            now=now,
        )
        assert posted.status == 403
        assert "set-cookie" not in dict(posted.headers)
        assert "140" not in posted.body


def test_the_password_opens_the_report_and_a_forged_cookie_does_not(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        _observe(policy, usage, _at(0, 32, day=22), nbytes=140)
        now = _at(12, day=22)
        accounts = _accounts(usage)
        query = {"view": "site", "client": "younger", "site": "entertainment", "quota": "notes"}
        page = respond_hierarchy(
            policy, usage, accounts, method="GET", query=query, cookie=None, form={}, now=now
        )
        assert page.status == 200
        assert "Enter your username and password." in page.body
        assert "<option" not in page.body
        assert "00:30" not in page.body
        assert "140" not in page.body
        assert "no usage" not in page.body

        posted = respond_hierarchy(
            policy,
            usage,
            accounts,
            method="POST",
            query={**query, "password": PASSWORD},
            cookie=None,
            form={"username": "parent", "password": "nope-secret"},
            now=now,
        )
        assert posted.status == 401
        assert "That username or password is not right." in posted.body
        assert "nope-secret" not in posted.body
        assert "set-cookie" not in dict(posted.headers)
        assert "00:30" not in posted.body
        assert "140" not in posted.body

        opened = respond_hierarchy(
            policy,
            usage,
            accounts,
            method="POST",
            query=query,
            cookie=None,
            form={"username": "parent", "password": PASSWORD},
            now=now,
        )
        assert opened.status == 303
        location = dict(opened.headers)["location"]
        assert PASSWORD not in location
        parsed = parse_qs(urlparse(location).query)
        assert parsed["view"] == ["site"]
        assert parsed["client"] == ["younger"]
        assert parsed["site"] == ["entertainment"]
        assert parsed["quota"] == ["notes"]
        token = _token(opened)
        shown = respond_hierarchy(
            policy, usage, accounts, method="GET", query=query, cookie=token, form={}, now=now
        )
        assert "00:30 to 00:35" in shown.body
        assert "140 bytes" in shown.body

        forged = token[:-1] + ("0" if token[-1] != "0" else "1")
        rejected = respond_hierarchy(
            policy, usage, accounts, method="GET", query=query, cookie=forged, form={}, now=now
        )
        assert "Enter your username and password." in rejected.body
        assert "00:30" not in rejected.body
        assert "140" not in rejected.body

        from_query = respond_hierarchy(
            policy,
            usage,
            accounts,
            method="GET",
            query={**query, "password": PASSWORD},
            cookie=None,
            form={},
            now=now,
        )
        assert "Enter your username and password." in from_query.body
        assert "00:30" not in from_query.body


def test_the_service_serves_the_report_behind_the_same_barrier(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(HOUSE, encoding="utf-8")
    database = tmp_path / "policy.sqlite3"
    monkeypatch.setenv("POLICY_FILE", str(policy_path))
    monkeypatch.setenv("POLICY_DB", str(database))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    monkeypatch.setenv("DECISION_FILE", str(tmp_path / "decision.json"))
    monkeypatch.delenv("DECISION_STUB", raising=False)
    monkeypatch.delenv("PARENT_PASSWORD", raising=False)
    monkeypatch.delenv("PARENT_IDLE", raising=False)
    monkeypatch.delenv("PARENT_LIFETIME", raising=False)
    closed = create_app()
    status, body, _headers = _call(closed, "GET", "/usage", scheme="https")
    assert status == 403
    assert "This page is closed until a parent account is added." in body
    assert "younger" not in body
    assert "00:30" not in body

    Accounts(sqlite3.connect(database)).set_password("parent", PASSWORD)
    app = create_app()
    policy = load(policy_path)
    assert policy is not None
    with UsageStore(database) as usage:
        observe(policy, usage, _clock(), _report(datetime.now(SYDNEY), nbytes=140))
    query = "view=site&client=younger&site=entertainment"
    status, body, _headers = _call(app, "GET", "/usage", query=query, scheme="https")
    assert status == 200
    assert "Enter your username and password." in body
    assert "<option" not in body
    assert "140" not in body
    assert "00:30" not in body

    status, _body, headers = _call(
        app,
        "POST",
        "/usage",
        query=query + "&password=secret",
        body=b"username=parent&password=secret",
        content_type="application/x-www-form-urlencoded",
        scheme="https",
    )
    assert status == 303
    location = headers["location"][0]
    assert "password" not in location
    assert "client=younger" in location
    token = headers["set-cookie"][0].split(";", 1)[0].split("=", 1)[1]
    assert "Secure" in headers["set-cookie"][0]
    assert "HttpOnly" in headers["set-cookie"][0]
    status, body, headers = _call(
        app, "GET", "/usage", query=query, cookie=f"parent_session={token}", scheme="https"
    )
    assert status == 200
    assert "younger, entertainment" in body
    assert "140 bytes" in body
    assert "Enter your username and password." not in body
    assert headers["cache-control"] == ["no-store"]


def _call(app, method, path, *, query="", body=b"", cookie=None, content_type=None, scheme="http"):
    messages = []
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    headers = []
    if content_type:
        headers.append((b"content-type", content_type.encode()))
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": scheme,
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 80),
        "root_path": "",
    }
    asyncio.run(app(scope, receive, send))
    start = next(item for item in messages if item["type"] == "http.response.start")
    payload = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
    found: dict[str, list[str]] = {}
    for key, value in start["headers"]:
        found.setdefault(key.decode(), []).append(value.decode())
    return start["status"], payload.decode(), found
