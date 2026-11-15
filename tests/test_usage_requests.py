"""S030.3: request rows, retention, the list endpoint, and end-of-flow reports."""

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
from policy.observations import keep_pruning, listen, status_for  # noqa: E402
from policy.store import PolicyStore  # noqa: E402
from policy.usage import UsageStore, file_report, note_request, parts_of, prune_requests  # noqa: E402
from policy.usage_graph import Presets  # noqa: E402
from policy.usage_requests import PAGE_SIZE, usage_requests  # noqa: E402

SYDNEY = ZoneInfo("Australia/Sydney")
PASSWORD = "secret"
YOUNGER = "192.0.2.40"
OLDER = "192.0.2.41"
WATCH = "https://www.youtube.com/watch?v=abc123&t=42"
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

NOW = datetime(2026, 11, 13, 21, 30)
# past-week ends at NOW, exclusive, so filed requests sit a minute earlier.
AT = NOW - timedelta(minutes=1)


def _load(directory: Path, text: str = HOUSE):
    path = directory / "policy.yaml"
    path.write_text(text, encoding="utf-8")
    return load(path)


def _record(usage: UsageStore, flow_id: str, moment: datetime, **kwargs) -> None:
    usage.record_request(
        flow_id,
        started_at=moment,
        client_ip=kwargs.get("ip", YOUNGER),
        client_group=kwargs.get("client", "younger"),
        site_group=kwargs.get("site", "youtube"),
        method=kwargs.get("method", "GET"),
        url=kwargs.get("url", WATCH),
        outcome=kwargs.get("outcome", "allowed"),
        status=kwargs.get("status"),
    )


def _observe(policy, usage: UsageStore, flow_id: str, moment: datetime, **kwargs) -> None:
    document = {
        "client_ip": kwargs.get("ip", YOUNGER),
        "url": kwargs.get("url", WATCH),
        "occurred_at": moment.replace(tzinfo=SYDNEY).isoformat(),
        "bytes": kwargs.get("down", 100) + kwargs.get("up", 0),
        "bytes_up": kwargs.get("up", 0),
        "bytes_down": kwargs.get("down", 100),
        "flow_id": flow_id,
    }
    if kwargs.get("ended"):
        document["ended"] = True
        document["status"] = kwargs.get("http_status", 200)
        document["content_type"] = kwargs.get("content_type", "text/html")
    clock = HouseholdClock(SYDNEY)
    filing = file_report(policy, usage, clock, document)
    note_request(usage, clock, document, quotas=() if filing is None else filing.quotas)


def _list(policy, usage, query: str, *, now: datetime = NOW) -> dict:
    pairs = [tuple(part.split("=", 1)) for part in query.split("&") if part]
    return usage_requests(policy, usage, Presets(usage.connection), pairs, now)


@pytest.mark.parametrize(
    ("url", "host", "path", "query"),
    [
        (WATCH, "www.youtube.com", "https://www.youtube.com/watch", "v=abc123&t=42"),
        ("https://www.youtube.com/watch", "www.youtube.com", "https://www.youtube.com/watch", ""),
        ("http://localhost:3000/app?x=1", "localhost:3000", "http://localhost:3000/app", "x=1"),
    ],
)
def test_parts_of_splits_host_path_and_query(url, host, path, query):
    assert parts_of(url) == (host, path, query)


def test_a_decision_inserts_a_request_and_observations_add_bytes_and_end(tmp_path):
    policy = _load(tmp_path)
    usage = UsageStore()
    start = AT
    _record(usage, "flow-1", start)
    _observe(policy, usage, "flow-1", start, down=2048, up=40)
    _observe(policy, usage, "flow-1", start + timedelta(seconds=5), down=0, up=0, ended=True, http_status=200, content_type="video/mp4; charset=utf-8")
    data = _list(policy, usage, "range=past-week&host=www.youtube.com&exact=1")
    assert data["total"] == 1
    row = data["rows"][0]
    assert row["host"] == "www.youtube.com"
    assert row["path"] == "https://www.youtube.com/watch"
    assert row["query"] == "v=abc123&t=42"
    assert row["down"] == "2 KB"
    assert row["up"] == "40 bytes"
    assert row["status"] == "200"
    assert row["type"] == "video/mp4"
    assert row["outcome"] == "allowed"
    assert "youtube" in row["quotas"]
    assert row["end"]


def test_denied_and_redirected_requests_are_listed_with_status_and_no_bytes(tmp_path):
    policy = _load(tmp_path)
    usage = UsageStore()
    _record(usage, "deny-1", AT, outcome="denied", status=403, url="https://blocked.example/x")
    _record(usage, "redir-1", AT, outcome="redirected", status=302, url="https://go.example/")
    data = _list(policy, usage, "range=past-week&outcome=denied&outcome=redirected")
    assert data["total"] == 2
    by_id = {row["id"]: row for row in data["rows"]}
    assert by_id["deny-1"]["status"] == "403"
    assert by_id["deny-1"]["down"] == "0 bytes"
    assert by_id["redir-1"]["status"] == "302"
    assert by_id["redir-1"]["outcome"] == "redirected"


def test_host_fragment_and_exact_host_filter_the_table(tmp_path):
    policy = _load(tmp_path)
    usage = UsageStore()
    _record(usage, "a", AT, url=WATCH)
    _record(usage, "b", AT, url=VIDEO, site="youtube")
    _record(usage, "c", AT, url=CLASSROOM, site="school")
    fragment = _list(policy, usage, "range=past-week&host=googlevideo")
    assert {row["id"] for row in fragment["rows"]} == {"b"}
    exact = _list(policy, usage, "range=past-week&host=www.youtube.com&exact=1")
    assert {row["id"] for row in exact["rows"]} == {"a"}


def test_sorting_and_paging_cover_every_request(tmp_path):
    policy = _load(tmp_path)
    usage = UsageStore()
    for index in range(PAGE_SIZE + 5):
        _record(usage, f"f-{index}", AT - timedelta(seconds=index), url=f"https://www.youtube.com/watch?v={index}")
    first = _list(policy, usage, "range=past-week&sort=start&dir=desc")
    assert first["from"] == 1
    assert first["to"] == PAGE_SIZE
    assert first["total"] == PAGE_SIZE + 5
    assert first["status"] == f"Requests 1 to {PAGE_SIZE} of {PAGE_SIZE + 5}."
    assert first["rows"][0]["id"] == "f-0"
    second = _list(policy, usage, "range=past-week&sort=start&dir=desc&page=2")
    assert second["from"] == PAGE_SIZE + 1
    assert second["to"] == PAGE_SIZE + 5
    assert len(second["rows"]) == 5
    by_host = _list(policy, usage, "range=past-week&sort=query&dir=asc&page=1")
    assert by_host["rows"][0]["query"] <= by_host["rows"][1]["query"]


def test_drill_down_filters_to_the_line_and_host(tmp_path):
    policy = _load(tmp_path)
    usage = UsageStore()
    _record(usage, "y", AT, client="younger", url=WATCH)
    _record(usage, "o", AT, client="older", ip=OLDER, url=WATCH)
    data = _list(policy, usage, "by=client&range=past-week&line=younger&host=www.youtube.com&exact=1")
    assert {row["id"] for row in data["rows"]} == {"y"}


def test_a_zero_byte_end_report_updates_status_without_filing_buckets(tmp_path):
    policy = _load(tmp_path)
    usage = UsageStore()
    _record(usage, "flow-end", AT)
    document = {
        "client_ip": YOUNGER,
        "url": WATCH,
        "occurred_at": AT.replace(tzinfo=SYDNEY).isoformat(),
        "bytes": 0,
        "bytes_up": 0,
        "bytes_down": 0,
        "flow_id": "flow-end",
        "ended": True,
        "status": 204,
        "content_type": "text/plain",
    }
    code, body = status_for(policy, usage, json.dumps(document).encode())
    assert code == 204
    assert body == b""
    data = _list(policy, usage, "range=past-week&host=www.youtube.com&exact=1")
    assert data["rows"][0]["status"] == "204"
    assert data["rows"][0]["type"] == "text/plain"
    assert usage.host_rows_between("site", AT - timedelta(days=1), NOW + timedelta(days=1)) == []


@pytest.mark.parametrize(("text", "days"), [(None, 30), ("30d", 30), ("1d", 1), ("48h", 2)])
def test_request_retention_is_whole_days_and_defaults_to_thirty(tmp_path, text, days):
    house = HOUSE if text is None else HOUSE + f"request_retention: {text}\n"
    assert _load(tmp_path, house).request_retention == days


@pytest.mark.parametrize("text", ["0d", "36h", "30", "thirty"])
def test_a_request_retention_that_is_not_whole_days_is_a_load_error_naming_the_key(tmp_path, text):
    with pytest.raises(ConfigError) as caught:
        _load(tmp_path, HOUSE + f"request_retention: {text}\n")
    assert any(
        "request_retention must be a whole number of days, at least one, such as 30d" in problem
        for problem in caught.value.problems
    )


def test_old_requests_are_pruned_and_the_table_never_lists_them(tmp_path):
    policy = _load(tmp_path, HOUSE + "request_retention: 10d\n")
    usage = UsageStore()
    _record(usage, "old", NOW - timedelta(days=20))
    _record(usage, "kept", NOW - timedelta(days=5))
    assert prune_requests(policy, usage, NOW) == 1
    data = _list(policy, usage, "range=past-month")
    assert {row["id"] for row in data["rows"]} == {"kept"}
    assert data["kept"] == "Requests are kept for 10 days, from Tuesday 3 November 2026."


def test_the_observations_service_prunes_requests_with_hosts(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text(HOUSE + "request_retention: 10d\nhost_retention: 10d\n", encoding="utf-8")
    policy = load(path)
    today = datetime.now(SYDNEY).replace(tzinfo=None, microsecond=0)
    with PolicyStore(tmp_path / "policy.sqlite3", check_same_thread=False) as store:
        usage = UsageStore(connection=store.connection)
        _record(usage, "old", today - timedelta(days=20))
        _record(usage, "new", today - timedelta(days=5))
        server = listen(policy, usage, "127.0.0.1", 0, tmp_path / "observations.jsonl", policy_file=path)
        try:
            stop = threading.Event()
            stop.set()
            keep_pruning(server, stop, every=0)
            data = _list(policy, usage, "range=past-month", now=today)
            assert {row["id"] for row in data["rows"]} == {"new"}
        finally:
            server.server_close()


def test_the_service_answers_the_request_table(tmp_path, monkeypatch):
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
    connection = sqlite3.connect(database)
    usage = UsageStore(connection=connection)
    _record(usage, "api-1", datetime.now(SYDNEY).replace(tzinfo=None) - timedelta(hours=1))
    connection.close()

    Accounts(sqlite3.connect(database)).set_password("parent", PASSWORD)
    app = create_app()
    _status, _body, headers = call(app, "POST", "/parent/api/login", json_body={"username": "parent", "password": PASSWORD})
    cookie = session_cookie(headers)
    status, body, _headers = call(app, "GET", "/parent/api/usage/requests", query="range=past-week", cookie=cookie)
    assert status == 200
    payload = json.loads(body)
    assert payload["total"] == 1
    assert payload["rows"][0]["id"] == "api-1"
    status, body, _headers = call(app, "GET", "/parent/api/usage/requests", query="range=past-week")
    assert status == 401


def test_decisions_record_a_request_row(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(HOUSE, encoding="utf-8")
    database = tmp_path / "policy.sqlite3"
    monkeypatch.setenv("POLICY_FILE", str(policy_path))
    monkeypatch.setenv("POLICY_DB", str(database))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    UsageStore(database).close()
    app = create_app()
    when = datetime.now(SYDNEY).replace(tzinfo=None) - timedelta(minutes=1)
    status, body, _headers = call(
        app,
        "POST",
        "/v1/decisions",
        json_body={
            "client_ip": YOUNGER,
            "method": "GET",
            "url": WATCH,
            "occurred_at": when.replace(tzinfo=SYDNEY).isoformat(),
            "flow_id": "decide-1",
        },
    )
    assert status == 200
    assert json.loads(body)["action"] == "allow"
    usage = UsageStore(database)
    data = _list(load(policy_path), usage, "range=past-week", now=datetime.now(SYDNEY).replace(tzinfo=None))
    assert data["rows"][0]["id"] == "decide-1"
    assert data["rows"][0]["outcome"] == "allowed"
