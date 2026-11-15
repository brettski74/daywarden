"""S030.2: usage by host, its retention, and the drill-down from a graph line."""

import json
import sqlite3
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from asgi import call, session_cookie  # noqa: E402
from policy.accounts import Accounts  # noqa: E402
from policy.clock import HouseholdClock  # noqa: E402
from policy.hierarchy import ConfigError, load  # noqa: E402
from policy.observations import keep_pruning, listen  # noqa: E402
from policy.store import PolicyStore  # noqa: E402
from policy.usage import UsageStore, file_report, host_of, prune_hosts  # noqa: E402
from policy.usage_graph import Presets, usage_graph  # noqa: E402

SYDNEY = ZoneInfo("Australia/Sydney")
PASSWORD = "secret"
YOUNGER = "192.0.2.40"
OLDER = "192.0.2.41"
WATCH = "https://www.youtube.com/watch?v=abc"
VIDEO = "https://rr3---sn-ab5l6nrz.googlevideo.com/videoplayback?id=1"
CLASSROOM = "https://classroom.google.com/u/0/h"

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
      - "*.googlevideo.com"

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
    return load(path)


def _report(moment: datetime, *, ip: str = YOUNGER, url: str = WATCH, down: int = 100, up: int | None = 0) -> dict:
    document = {"client_ip": ip, "url": url, "occurred_at": moment.replace(tzinfo=SYDNEY).isoformat(), "bytes": down + (up or 0)}
    if up is not None:
        document.update(bytes_up=up, bytes_down=down)
    return document


def _file(policy, usage: UsageStore, moment: datetime, **kwargs) -> None:
    assert file_report(policy, usage, HouseholdClock(SYDNEY), _report(moment, **kwargs)) is not None


def _graph(policy, usage, query: str, *, unit: str = "minutes", now: datetime = NOW) -> dict:
    pairs = [tuple(part.split("=", 1)) for part in query.split("&") if part]
    return usage_graph(policy, usage, Presets(usage.connection), pairs, now, unit)


def _bars(data: dict) -> dict[str, int]:
    return {bar["host"]: bar["value"] for bar in data["hosts"]["bars"]}


@pytest.mark.parametrize(
    ("url", "host"),
    [
        ("https://www.youtube.com/watch?v=abc", "www.youtube.com"),
        ("https://www.youtube.com:443/watch", "www.youtube.com"),
        ("http://example.com:80/", "example.com"),
        ("http://localhost:3000/app", "localhost:3000"),
        ("https://example.com:8443/", "example.com:8443"),
        ("http://example.com:443/", "example.com:443"),
        ("https://WWW.Example.COM/", "www.example.com"),
        ("http://[2001:db8::1]:8080/", "[2001:db8::1]:8080"),
        ("http://[2001:db8::1]/", "2001:db8::1"),
    ],
)
def test_a_host_is_the_name_with_a_port_only_when_it_is_not_the_schemes_default(url, host):
    assert host_of(url) == host


def test_a_page_of_many_requests_in_one_bucket_gives_each_host_the_bucket_once(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        for second in range(10):
            _file(policy, usage, datetime(2026, 11, 13, 10, 0, second), url="https://www.youtube.com/s/asset", down=50)
        _file(policy, usage, datetime(2026, 11, 13, 10, 1), url=VIDEO, down=900)
        _file(policy, usage, datetime(2026, 11, 13, 10, 4), url=VIDEO, down=900)
        data = _graph(policy, usage, "by=client&range=today&line=younger")
        assert _bars(data) == {"rr3---sn-ab5l6nrz.googlevideo.com": 360, "www.youtube.com": 180}
        assert sum(_bars(data).values()) > sum(data["graph"]["lines"][0]["values"])
        assert data["hosts"]["line"] == "younger"
        assert data["hosts"]["kept"] is None


def test_minutes_count_ended_buckets_and_bytes_split_down_and_up(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        _file(policy, usage, datetime(2026, 11, 13, 10, 0), url=WATCH, down=1000, up=40)
        _file(policy, usage, datetime(2026, 11, 13, 21, 28), url=WATCH, down=500, up=5)
        _file(policy, usage, datetime(2026, 11, 13, 21, 28), url=CLASSROOM, down=1200, up=600)
        before_the_bucket_ends = datetime(2026, 11, 13, 21, 29)
        minutes = _graph(policy, usage, "by=client&range=today&line=younger", now=before_the_bucket_ends)
        assert _bars(minutes) == {"www.youtube.com": 180}
        assert "down" not in minutes["hosts"]["bars"][0]
        data = _graph(policy, usage, "by=client&range=today&line=younger", unit="bytes", now=before_the_bucket_ends)
        assert data["hosts"]["bars"] == [
            {"host": "classroom.google.com", "value": 1800, "down": 1200, "up": 600},
            {"host": "www.youtube.com", "value": 1545, "down": 1500, "up": 45},
        ]


def test_a_report_from_an_older_proxy_is_filed_as_downloaded(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        _file(policy, usage, datetime(2026, 11, 13, 10, 0), down=700, up=None)
        bars = _graph(policy, usage, "by=none&range=today&line=Total", unit="bytes")["hosts"]["bars"]
        assert bars == [{"host": "www.youtube.com", "value": 700, "down": 700, "up": 0}]
        with pytest.raises(ValueError, match="bytes is bytes_up and bytes_down added together"):
            file_report(policy, usage, HouseholdClock(SYDNEY), {**_report(NOW, down=10, up=5), "bytes": 99})


def test_at_most_twenty_hosts_are_listed_highest_first(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        for index in range(25):
            _file(policy, usage, datetime(2026, 11, 13, 9, 0), url=f"https://host{index:02}.example/", down=100 + index)
        bars = _graph(policy, usage, "by=none&range=today&line=Total", unit="bytes")["hosts"]["bars"]
        assert len(bars) == 20
        assert bars[0]["host"] == "host24.example"
        assert bars[-1]["host"] == "host05.example"


def test_a_line_covers_its_own_group_within_the_filters(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        _file(policy, usage, datetime(2026, 11, 10, 15, 0), url=WATCH)
        _file(policy, usage, datetime(2026, 11, 10, 15, 0), url=CLASSROOM)
        _file(policy, usage, datetime(2026, 11, 11, 9, 0), ip=OLDER, url=CLASSROOM)
        assert _bars(_graph(policy, usage, "by=client&range=past-week&line=older")) == {"classroom.google.com": 180}
        assert _bars(_graph(policy, usage, "site=youtube&by=client&range=past-week&line=younger")) == {"www.youtube.com": 180}
        assert _bars(_graph(policy, usage, "by=site&range=past-week&line=school")) == {"classroom.google.com": 360}
        assert _bars(_graph(policy, usage, "client=younger&by=site&range=past-week&line=school")) == {"classroom.google.com": 180}
        assert _bars(_graph(policy, usage, "by=quota&range=past-week&line=youtube")) == {"www.youtube.com": 180}
        assert _bars(_graph(policy, usage, "by=quota&range=past-week&line=screen-time")) == {
            "classroom.google.com": 360,
            "www.youtube.com": 180,
        }
        both = _graph(policy, usage, "quota=youtube&quota=screen-time&by=client&range=past-week&line=younger")
        assert _bars(both) == {"www.youtube.com": 360, "classroom.google.com": 180}
        assert _bars(_graph(policy, usage, "by=client&range=previous-week&line=younger")) == {}


def test_a_line_the_graph_cannot_draw_shows_no_hosts_and_says_why(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        _file(policy, usage, datetime(2026, 11, 10, 15, 0))
        data = _graph(policy, usage, "client=older&by=client&range=past-week&line=younger")
        assert data["hosts"] is None
        assert "younger is not a line on this graph, so its hosts are not shown." in data["notes"]
        assert _graph(policy, usage, "by=client&range=past-week&line=default")["hosts"]["bars"] == []
        assert _graph(policy, usage, "by=none&range=past-week&line=younger")["hosts"] is None
        assert _graph(policy, usage, "by=client&range=past-week")["hosts"] is None


def test_hosts_are_kept_for_the_retention_and_the_graph_still_reaches_back(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        _file(policy, usage, datetime(2026, 9, 1, 10, 0))
        _file(policy, usage, datetime(2026, 10, 13, 10, 0))
        _file(policy, usage, datetime(2026, 10, 14, 10, 0), url=CLASSROOM)
        month = _graph(policy, usage, "by=client&range=past-month&line=younger")
        assert month["hosts"]["kept"] == "Hosts are kept for 30 days, from Wednesday 14 October 2026."
        assert _bars(month) == {"classroom.google.com": 180}
        week = _graph(policy, usage, "by=client&range=past-week&line=younger")
        assert week["hosts"]["kept"] is None

        assert file_report(policy, usage, HouseholdClock(SYDNEY), _report(NOW)) is not None
        # Each old report is a row beside its site group and beside each of its two quotas.
        assert prune_hosts(policy, usage, NOW) == 6
        custom = _graph(policy, usage, "by=client&range=custom&from=2026-09-01&to=2026-11-13", unit="bytes")
        assert sum(custom["graph"]["lines"][0]["values"]) == 4 * 100


def test_before_the_upgrade_hosts_are_kept_from_the_first_host_row(tmp_path):
    policy = _load(tmp_path)
    with UsageStore(":memory:") as usage:
        assert _graph(policy, usage, "by=client&range=past-week&line=younger")["hosts"]["kept"] == (
            "Hosts are kept for 30 days, from Friday 13 November 2026."
        )
        assert _graph(policy, usage, "by=client&range=today&line=younger")["hosts"]["kept"] is None
        _file(policy, usage, datetime(2026, 11, 11, 16, 2))
        week = _graph(policy, usage, "by=client&range=past-week&line=younger")
        assert week["hosts"]["kept"] == "Hosts are kept for 30 days, from Wednesday 11 November 2026."
        assert _graph(policy, usage, "by=client&range=yesterday&line=younger")["hosts"]["kept"] is None
        _file(policy, usage, datetime(2026, 11, 12, 9, 0))
        _file(policy, usage, datetime(2026, 11, 9, 9, 0))
        week = _graph(policy, usage, "by=client&range=past-week&line=younger")
        assert week["hosts"]["kept"] == "Hosts are kept for 30 days, from Monday 9 November 2026."


@pytest.mark.parametrize(("text", "days"), [(None, 30), ("30d", 30), ("1d", 1), ("48h", 2), ("1440m", 1)])
def test_host_retention_is_whole_days_and_defaults_to_thirty(tmp_path, text, days):
    house = HOUSE if text is None else HOUSE + f"host_retention: {text}\n"
    assert _load(tmp_path, house).host_retention == days


@pytest.mark.parametrize("text", ["0d", "36h", "30", "thirty", "-2d", "2w"])
def test_a_host_retention_that_is_not_whole_days_is_a_load_error_naming_the_key(tmp_path, text):
    with pytest.raises(ConfigError) as caught:
        _load(tmp_path, HOUSE + f"host_retention: {text}\n")
    assert any("host_retention must be a whole number of days, at least one, such as 30d" in problem for problem in caught.value.problems)


def test_the_observations_service_prunes_at_start_and_after_a_reload_shortens_the_retention(tmp_path, monkeypatch):
    path = tmp_path / "policy.yaml"
    path.write_text(HOUSE, encoding="utf-8")
    policy = load(path)
    today = datetime.now(SYDNEY).replace(tzinfo=None, microsecond=0)
    with PolicyStore(tmp_path / "policy.sqlite3", check_same_thread=False) as store:
        usage = UsageStore(connection=store.connection)
        for days in (40, 20, 5, 0):
            _file(policy, usage, today - timedelta(days=days))
        server = listen(policy, usage, "127.0.0.1", 0, tmp_path / "observations.jsonl", policy_file=path)
        try:
            stop = threading.Event()
            stop.set()
            keep_pruning(server, stop, every=0)
            assert len(usage.host_rows_between("site", today - timedelta(days=60), today + timedelta(days=1))) == 3

            path.write_text(HOUSE + "host_retention: 10d\n", encoding="utf-8")
            assert server.reload_policy()["reloaded"] is True
            assert len(usage.host_rows_between("site", today - timedelta(days=60), today + timedelta(days=1))) == 2

            path.write_text(HOUSE + "host_retention: 1h\n", encoding="utf-8")
            refused = server.reload_policy()
            assert refused["reloaded"] is False
            assert any("host_retention" in problem for problem in refused["errors"])
            assert server.prune_hosts() == 0
            assert len(usage.host_rows_between("site", today - timedelta(days=60), today + timedelta(days=1))) == 2
        finally:
            server.server_close()


def test_the_service_answers_the_top_hosts_on_the_usage_address(tmp_path, monkeypatch):
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
    policy = load(policy_path)
    connection = sqlite3.connect(database)
    usage = UsageStore(connection=connection)
    moment = datetime.now(SYDNEY).replace(tzinfo=None) - timedelta(hours=1)
    _file(policy, usage, moment, down=2048, up=100)
    connection.close()

    Accounts(sqlite3.connect(database)).set_password("parent", PASSWORD)
    app = create_app()
    _status, _body, headers = call(app, "POST", "/parent/api/login", json_body={"username": "parent", "password": PASSWORD})
    cookie = session_cookie(headers)
    status, body, _headers = call(app, "GET", "/parent/api/usage/bytes", query="by=client&range=past-week&line=younger", cookie=cookie)
    assert status == 200
    hosts = json.loads(body)["hosts"]
    assert hosts["bars"] == [{"host": "www.youtube.com", "value": 2148, "down": 2048, "up": 100}]
    status, body, _headers = call(app, "GET", "/parent/api/usage/bytes", query="by=client&range=past-week&line=younger")
    assert status == 401
    assert "youtube" not in body
