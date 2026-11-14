"""S030.1: the usage graph, its date ranges and lines, and its presets."""

import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from asgi import call, session_cookie  # noqa: E402
from policy.accounts import Accounts  # noqa: E402
from policy.clock import HouseholdClock  # noqa: E402
from policy.hierarchy import load  # noqa: E402
from policy.usage import UsageStore, observe  # noqa: E402
from policy.usage_graph import Presets, describe_range, intervals, resolve_range, usage_graph  # noqa: E402

SYDNEY = ZoneInfo("Australia/Sydney")
PASSWORD = "secret"
YOUTUBE = "https://www.youtube.com/watch?v=abc"
CLASSROOM = "https://classroom.google.com/u/0/h"
UNKNOWN_SITE = "https://example.com/page"
YOUNGER = "192.0.2.40"
OLDER = "192.0.2.41"

HOUSE = """\
timezone: Australia/Sydney
bucket_length: 3m
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
  youtube:
    priority: 30
    patterns:
      - "*.youtube.com"

quotas:
  youtube:
    time: 2h
    ruleset: youtube_meter
  screen-time:
    time: 3h
    ruleset: everything

rule_sets:
  entry:
    - condition: always
      when_true: { action: allow }
  youtube_meter:
    - condition: site_group
      group: youtube
      when_true: { action: continue }
      when_false: { action: deny, message: "Not YouTube." }
  everything:
    - condition: always
      when_true: { action: continue }
"""

# Friday 13 November 2026, 21:30 in the household.
NOW = datetime(2026, 11, 13, 21, 30)


def _load(directory: Path, text: str = HOUSE):
    path = directory / "policy.yaml"
    path.write_text(text, encoding="utf-8")
    loaded = load(path)
    assert loaded is not None
    return loaded


def _observe(policy, usage: UsageStore, moment: datetime, *, ip: str = YOUNGER, url: str = YOUTUBE, nbytes: int = 100) -> None:
    document = {"client_ip": ip, "url": url, "occurred_at": moment.replace(tzinfo=SYDNEY).isoformat(), "bytes": nbytes}
    assert observe(policy, usage, HouseholdClock(SYDNEY), document)


def _graph(policy, usage, query: str, *, unit: str = "minutes", now: datetime = NOW, presets: Presets | None = None) -> dict:
    pairs = [tuple(part.split("=", 1)) for part in query.split("&") if part]
    return usage_graph(policy, usage, presets or Presets(usage.connection), pairs, now, unit)


def _lines(data: dict) -> dict[str, list[int]]:
    return {line["name"]: line["values"] for line in data["graph"]["lines"]}


def _totals(data: dict) -> dict[str, int]:
    return {name: sum(values) for name, values in _lines(data).items()}


@pytest.mark.parametrize(
    ("name", "now", "start", "end"),
    [
        ("today", NOW, datetime(2026, 11, 13), NOW),
        ("yesterday", NOW, datetime(2026, 11, 12), datetime(2026, 11, 13)),
        ("this-week", NOW, datetime(2026, 11, 8), NOW),
        ("this-week", datetime(2026, 11, 8, 9, 0), datetime(2026, 11, 8), datetime(2026, 11, 8, 9, 0)),
        ("this-month", NOW, datetime(2026, 11, 1), NOW),
        ("past-week", NOW, datetime(2026, 11, 6, 21, 30), NOW),
        ("past-month", NOW, datetime(2026, 10, 13, 21, 30), NOW),
        ("past-month", datetime(2027, 3, 31, 10, 0), datetime(2027, 2, 28, 10, 0), datetime(2027, 3, 31, 10, 0)),
        ("past-month", datetime(2027, 1, 15, 8, 0), datetime(2026, 12, 15, 8, 0), datetime(2027, 1, 15, 8, 0)),
        ("previous-week", NOW, datetime(2026, 11, 1), datetime(2026, 11, 8)),
        ("previous-week", datetime(2026, 11, 8, 9, 0), datetime(2026, 11, 1), datetime(2026, 11, 8)),
        ("previous-month", NOW, datetime(2026, 10, 1), datetime(2026, 11, 1)),
        ("previous-month", datetime(2027, 1, 2), datetime(2026, 12, 1), datetime(2027, 1, 1)),
    ],
)
def test_each_date_range_starts_and_ends_where_the_story_says(name, now, start, end):
    assert resolve_range(name, now) == (start, end)


def test_a_custom_range_is_whole_days_from_through_to():
    assert resolve_range("custom", NOW, date(2026, 11, 1), date(2026, 11, 3)) == (datetime(2026, 11, 1), datetime(2026, 11, 4))


def test_the_status_bar_says_what_the_range_covers():
    assert describe_range(*resolve_range("past-week", NOW)) == "Friday 6 November 2026 21:30 to Friday 13 November 2026 21:30"
    assert describe_range(*resolve_range("previous-week", NOW)) == "Sunday 1 November 2026 to Saturday 7 November 2026"
    assert describe_range(*resolve_range("yesterday", NOW)) == "Thursday 12 November 2026"
    assert describe_range(*resolve_range("today", NOW)) == "Friday 13 November 2026 00:00 to 21:30"


def test_hourly_daily_and_weekly_points_with_partial_ends():
    kind, spans = intervals(*resolve_range("yesterday", NOW))
    assert (kind, len(spans)) == ("hour", 24)
    kind, spans = intervals(datetime(2026, 11, 11, 21, 30), NOW)
    assert (kind, len(spans)) == ("hour", 49)
    assert spans[0] == (datetime(2026, 11, 11, 21, 30), datetime(2026, 11, 11, 22, 0))

    kind, spans = intervals(*resolve_range("past-week", NOW))
    assert kind == "day"
    assert spans[0] == (datetime(2026, 11, 6, 21, 30), datetime(2026, 11, 7))
    assert spans[-1] == (datetime(2026, 11, 13), NOW)
    assert len(spans) == 8

    kind, spans = intervals(datetime(2026, 8, 13), datetime(2026, 11, 13))
    assert (kind, len(spans)) == ("day", 92)
    kind, spans = intervals(datetime(2026, 8, 12), datetime(2026, 11, 13))
    assert kind == "week"
    assert spans[0] == (datetime(2026, 8, 12), datetime(2026, 8, 16))
    assert all(start.weekday() == 6 for start, _end in spans[1:])


def test_minutes_count_ended_buckets_and_bytes_count_every_bucket(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        _observe(policy, usage, datetime(2026, 11, 13, 10, 1), nbytes=1000)
        _observe(policy, usage, datetime(2026, 11, 13, 21, 28), nbytes=500)
        minutes = _graph(policy, usage, "by=none&range=today", now=datetime(2026, 11, 13, 21, 29))
        assert _totals(minutes) == {"Total": 180}
        assert _lines(minutes)["Total"][10] == 180
        bytes_ = _graph(policy, usage, "by=none&range=today", unit="bytes", now=datetime(2026, 11, 13, 21, 29))
        assert _totals(bytes_) == {"Total": 1500}
        assert _lines(bytes_)["Total"][21] == 500


def test_a_line_adds_every_row_it_covers_across_site_groups_and_quotas(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        _observe(policy, usage, datetime(2026, 11, 10, 15, 0, 30), url=YOUTUBE, nbytes=100)
        _observe(policy, usage, datetime(2026, 11, 10, 15, 1), url=CLASSROOM, nbytes=40)
        by_site = _graph(policy, usage, "by=client&range=past-week")
        assert _totals(by_site) == {"younger": 360}
        both_quotas = _graph(policy, usage, "by=client&range=past-week&quota=youtube&quota=screen-time", unit="bytes")
        assert _totals(both_quotas) == {"younger": 100 + 100 + 40}
        both_minutes = _graph(policy, usage, "by=client&range=past-week&quota=youtube&quota=screen-time")
        assert _totals(both_minutes) == {"younger": 360}


def test_group_by_draws_the_chosen_groups_or_every_one_with_usage(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        _observe(policy, usage, datetime(2026, 11, 10, 15, 1), url=YOUTUBE)
        _observe(policy, usage, datetime(2026, 11, 11, 9, 1), ip=OLDER, url=CLASSROOM)
        chosen = _graph(policy, usage, "client=younger&client=older&by=client&range=past-week")
        assert [line["name"] for line in chosen["graph"]["lines"]] == ["younger", "older"]
        sites = _graph(policy, usage, "by=site&range=past-week")
        assert [line["name"] for line in sites["graph"]["lines"]] == ["school", "youtube"]
        one_site = _graph(policy, usage, "site=school&by=client&range=past-week")
        assert _totals(one_site) == {"older": 180}
        total = _graph(policy, usage, "by=none&range=past-week")
        assert _totals(total) == {"Total": 360}
        quotas = _graph(policy, usage, "by=quota&range=past-week")
        assert _totals(quotas) == {"youtube": 180, "screen-time": 360}
        unused = _graph(policy, usage, "client=default&by=client&range=past-week")
        assert _totals(unused) == {"default": 0}


def test_no_quota_includes_traffic_no_quota_accepts_and_a_quota_counts_only_its_own(tmp_path):
    house = HOUSE.replace("    ruleset: everything", "    ruleset: youtube_meter")
    policy = _load(tmp_path, house)
    with UsageStore(":memory:") as usage:
        _observe(policy, usage, datetime(2026, 11, 10, 15, 1), url=CLASSROOM, nbytes=40)
        _observe(policy, usage, datetime(2026, 11, 10, 16, 1), url=YOUTUBE, nbytes=60)
        assert _totals(_graph(policy, usage, "by=none&range=past-week", unit="bytes")) == {"Total": 100}
        assert _totals(_graph(policy, usage, "quota=youtube&by=none&range=past-week", unit="bytes")) == {"Total": 60}


def test_a_range_with_no_usage_has_points_and_no_lines(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        data = _graph(policy, usage, "by=client&range=previous-week")
        assert data["graph"]["lines"] == []
        assert len(data["graph"]["points"]) == 7
        assert data["graph"]["points"][2]["label"] == "Tuesday 3 November 2026"
        assert data["range"] == "Sunday 1 November 2026 to Saturday 7 November 2026"
        assert data["times"] == "Times are Australia/Sydney."
        assert data["days"] == {"from": "2026-11-01", "to": "2026-11-07"}


def test_site_groups_and_quotas_are_never_used_together(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        both = _graph(policy, usage, "site=school&quota=youtube&by=client&range=past-week")
        assert both["settings"]["site"] == []
        assert both["settings"]["quota"] == ["youtube"]
        assert "Left out the site groups, because usage by quota is not kept per site group." in both["notes"]
        by_site = _graph(policy, usage, "quota=youtube&by=site&range=past-week")
        assert by_site["settings"]["quota"] == []
        assert "Left out the quotas, because usage by quota is not kept per site group." in by_site["notes"]


def test_a_custom_range_that_cannot_be_drawn_says_why(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        backwards = _graph(policy, usage, "by=client&range=custom&from=2026-11-05&to=2026-11-01")
        assert backwards["graph"] is None
        assert "To is before From." in backwards["notes"]
        assert backwards["settings"]["from"] == "2026-11-05"
        nonsense = _graph(policy, usage, "by=client&range=custom&from=2026-02-30&to=2026-11-01")
        assert nonsense["graph"] is None
        assert "From is not a date. Use yyyy-mm-dd, such as 2026-10-31." in nonsense["notes"]
        good = _graph(policy, usage, "by=client&range=custom&from=2026-11-01&to=2026-11-03")
        assert good["range"] == "Sunday 1 November 2026 to Tuesday 3 November 2026"
        assert good["graph"]["interval"] == "day"


def test_an_address_without_settings_shows_the_default_preset(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        presets = Presets(usage.connection)
        data = _graph(policy, usage, "", presets=presets)
        assert data["preset"] == "Default"
        assert data["presets"] == ["Default"]
        assert data["settings"] == {"client": [], "site": [], "quota": [], "by": "client", "range": "past-week", "from": "", "to": ""}
        assert data["choices"] == {
            "clients": ["younger", "older", "default"],
            "sites": ["school", "youtube", "default"],
            "quotas": ["youtube", "screen-time"],
        }
        assert _graph(policy, usage, "by=client&range=past-week", presets=presets)["preset"] == "Default"
        assert _graph(policy, usage, "by=site&range=past-week", presets=presets)["preset"] == ""


def test_saving_choosing_matching_replacing_and_deleting_presets(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        presets = Presets(usage.connection)
        school = {"client": ["younger"], "site": ["school"], "quota": [], "by": "site", "range": "this-week", "from": "", "to": ""}
        saved = presets.save({"name": " School week ", "settings": school}, "ada", NOW)
        assert (saved.status, saved.body["name"]) == (200, "School week")
        assert presets.names() == ["Default", "School week"]

        chosen = _graph(policy, usage, "preset=School week", presets=presets)
        assert chosen["preset"] == "School week"
        assert chosen["settings"]["range"] == "this-week"
        assert chosen["range"] == "Sunday 8 November 2026 00:00 to Friday 13 November 2026 21:30"
        later = _graph(policy, usage, "preset=school week", presets=presets, now=datetime(2026, 11, 16, 8, 0))
        assert later["range"] == "Sunday 15 November 2026 00:00 to Monday 16 November 2026 08:00"
        matched = _graph(policy, usage, "site=school&client=younger&by=site&range=this-week", presets=presets)
        assert matched["preset"] == "School week"

        again = presets.save({"name": "school WEEK", "settings": {**school, "range": "past-month"}}, "bea", NOW)
        assert again.status == 409
        assert again.body["error"] == "There is already a preset called School week."
        replaced = presets.save({"name": "school WEEK", "settings": {**school, "range": "past-month"}, "replace": True}, "bea", NOW)
        assert replaced.body == {"name": "School week", "message": "Replaced preset School week."}
        assert _graph(policy, usage, "preset=School week", presets=presets)["settings"]["range"] == "past-month"

        refused = presets.delete({"name": "Default"})
        assert (refused.status, refused.body["error"]) == (400, "Default can be replaced but not deleted.")
        assert presets.delete({"name": "School week"}).status == 200
        missing = _graph(policy, usage, "preset=School week", presets=presets)
        assert missing["preset"] == "Default"
        assert "There is no preset called School week, so this is Default." in missing["notes"]


def test_default_can_be_replaced_and_a_custom_preset_keeps_its_dates(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        presets = Presets(usage.connection)
        weekly = {"client": [], "site": [], "quota": [], "by": "none", "range": "previous-week", "from": "", "to": ""}
        assert presets.save({"name": "Default", "settings": weekly}, "ada", NOW).status == 409
        assert presets.save({"name": "Default", "settings": weekly, "replace": True}, "ada", NOW).status == 200
        assert _graph(policy, usage, "", presets=presets)["settings"]["by"] == "none"

        custom = {**weekly, "range": "custom", "from": "2026-10-01", "to": "2026-10-31"}
        assert presets.save({"name": "October", "settings": custom}, "ada", NOW).status == 200
        october = _graph(policy, usage, "preset=October", presets=presets, now=datetime(2027, 5, 1))
        assert october["range"] == "Thursday 1 October 2026 to Saturday 31 October 2026"


def test_a_preset_naming_a_group_the_policy_no_longer_has_applies_the_rest(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        presets = Presets(usage.connection)
        old = {"client": ["younger", "middle"], "site": [], "quota": ["tv"], "by": "client", "range": "today", "from": "", "to": ""}
        assert presets.save({"name": "Old", "settings": old}, "ada", NOW).status == 200
        data = _graph(policy, usage, "preset=Old", presets=presets)
        assert data["settings"]["client"] == ["younger"]
        assert data["settings"]["range"] == "today"
        assert "Left out client group middle and quota tv, which the policy no longer has." in data["notes"]


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"name": "  ", "settings": {}}, "Give the preset a name."),
        ({"name": "x" * 61, "settings": {}}, "A preset name is at most 60 characters."),
        ({"name": "a\tb", "settings": {}}, "A preset name cannot hold control characters."),
        ({"name": "Odd", "settings": {"by": "colour", "range": "today"}}, "Those are not settings for the usage graph."),
        ({"name": "Odd", "settings": {"by": "none", "range": "custom", "from": "2026-11-05", "to": "2026-11-01"}}, "To is before From."),
    ],
)
def test_a_preset_that_cannot_be_saved_says_why(body, error):
    with UsageStore(":memory:") as usage:
        answer = Presets(usage.connection).save(body, "ada", NOW)
        assert (answer.status, answer.body["error"]) == (400, error)


def _service(tmp_path, monkeypatch):
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
    return create_app, database


def test_the_service_serves_the_graph_and_keeps_presets_only_for_a_signed_in_parent(tmp_path, monkeypatch):
    create_app, database = _service(tmp_path, monkeypatch)
    closed = create_app()
    status, body, _headers = call(closed, "GET", "/parent/api/usage/minutes")
    assert (status, json.loads(body)["closed"]) == (403, True)

    Accounts(sqlite3.connect(database)).set_password("parent", PASSWORD)
    app = create_app()
    status, body, headers = call(app, "GET", "/parent/api/usage/bytes", query="by=client&range=today")
    assert status == 401
    assert "younger" not in body
    assert "location" not in headers
    status, _body, headers = call(app, "POST", "/parent/api/login", json_body={"username": "parent", "password": PASSWORD})
    cookie = session_cookie(headers)

    status, body, headers = call(app, "GET", "/parent/api/usage/bytes", query="client=younger&client=older&by=client&range=today", cookie=cookie)
    assert status == 200
    assert headers["cache-control"] == ["no-store"]
    data = json.loads(body)
    assert data["unit"] == "bytes"
    assert data["settings"]["client"] == ["younger", "older"]
    status, _body, _headers = call(app, "GET", "/parent/api/usage/hours", cookie=cookie)
    assert status == 404

    preset = {"name": "School week", "settings": data["settings"]}
    status, _body, _headers = call(app, "POST", "/parent/api/usage/presets", body=json.dumps(preset).encode(), content_type="text/plain", cookie=cookie)
    assert status == 415
    status, body, _headers = call(app, "POST", "/parent/api/usage/presets", json_body=preset)
    assert status == 401
    status, body, _headers = call(app, "POST", "/parent/api/usage/presets", json_body=preset, cookie=cookie)
    assert (status, json.loads(body)["message"]) == (200, "Saved preset School week.")

    restarted = create_app()
    status, body, _headers = call(restarted, "GET", "/parent/api/usage/minutes", query="preset=School%20week", cookie=cookie)
    data = json.loads(body)
    assert data["preset"] == "School week"
    assert data["presets"] == ["Default", "School week"]
    assert data["settings"]["client"] == ["younger", "older"]

    status, body, _headers = call(restarted, "POST", "/parent/api/usage/presets/delete", json_body={"name": "School week"}, cookie=cookie)
    assert (status, json.loads(body)["message"]) == (200, "Deleted preset School week.")
    status, body, _headers = call(restarted, "POST", "/parent/api/usage/presets/delete", json_body={"name": "Default"}, cookie=cookie)
    assert status == 400
