"""S016: the decisions and observations services reload the policy in place."""

import asyncio
import http.client
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from policy.hierarchy import load
from policy.observations import CUT_BODY, listen
from policy.store import PolicyStore
from policy.usage import UsageStore

TORONTO = ZoneInfo("America/Toronto")
YOUNGER = "192.0.2.40"
PROXY = "172.17.0.2"
VIDEO = "https://www.youtube.com/watch?v=abc"
READING = "https://reading.example/book"
PASSWORD = "correct horse battery"
SUMS = {
    "operation": "addition",
    "max_timeout": "10s",
    "min_timeout": "4s",
    "correct_answers_required": 2,
    "first": [{"value": 6, "weight": 1}],
    "operands": [{"value": 7, "weight": 1}],
}
HOUSE = f"""\
entry: gate
timezone: America/Toronto
hostname: tasks.example
port: 443
bucket_length: 5m
client_groups:
  younger:
    addresses: ["{YOUNGER}"]
site_groups:
  entertainment:
    priority: 10
    patterns: [www.youtube.com]
  reading:
    priority: 20
    patterns: [reading.example]
quotas:
  video:
    bytes: 1000b
    volume_grace: 0b
    ruleset: meter
tasks:
  arithmetic:
    sums:
      group: younger
      pass_cooldown: 0
      body: {json.dumps(SUMS)}
    spare:
      group: younger
      pass_cooldown: 0
      body: {json.dumps(SUMS)}
rule_sets:
  meter:
    - condition: site_group
      group: entertainment
      when_false: {{ action: deny, message: "Not video." }}
  gate:
    - condition: site_group
      group: reading
      when_true: {{ action: deny, message: "No reading." }}
    - condition: site_group
      group: entertainment
      when_true: {{ action: evaluate, ruleset: video }}
  video:
    - condition: volume_remaining
      quota: video
      when_true: {{ action: allow }}
      when_false: {{ action: deny, message: "That's enough video." }}
"""
NO_READING = 'when_true: { action: deny, message: "No reading." }'


class Service:
    """The decisions service, as the proxy, the browser, and dw reload reach it."""

    def __init__(self, directory: Path, monkeypatch):
        from policy.app import create_app

        self.directory = directory
        self.policy_file = directory / "policy.yaml"
        self.policy_file.write_text(HOUSE, encoding="utf-8")
        self.database = directory / "policy.sqlite3"
        self.log = directory / "decisions.jsonl"
        monkeypatch.setenv("POLICY_FILE", str(self.policy_file))
        monkeypatch.setenv("POLICY_DB", str(self.database))
        monkeypatch.setenv("DECISION_LOG", str(self.log))
        monkeypatch.delenv("PARENT_IDLE", raising=False)
        monkeypatch.delenv("PARENT_LIFETIME", raising=False)
        self._create = create_app
        self.app = create_app()

    def edit(self, old: str, new: str) -> None:
        text = self.policy_file.read_text(encoding="utf-8")
        assert old in text
        self.policy_file.write_text(text.replace(old, new), encoding="utf-8")

    def reload(self, *, peer: str = "127.0.0.1", scheme: str = "http") -> tuple[int, dict]:
        status, body, _headers = _call(self.app, "POST", "/v1/reload", peer=peer, scheme=scheme)
        return status, json.loads(body)

    def restart(self) -> None:
        self.app = self._create()

    def decide(self, url: str, *, at: str = "2026-11-02T20:00:00+00:00") -> dict:
        document = {"client_ip": YOUNGER, "method": "GET", "url": url, "occurred_at": at}
        status, body, _headers = _call(self.app, "POST", "/v1/decisions", body=json.dumps(document).encode(), peer=PROXY)
        assert status == 200, body
        return json.loads(body)

    def last_logged(self) -> dict:
        return json.loads(self.log.read_text(encoding="utf-8").splitlines()[-1])

    def task(self, method: str, name: str, action: str | None = None, body: bytes = b"") -> tuple[int, str]:
        query = b"" if action is None else f"do={action}".encode()
        status, text, _headers = _call(
            self.app, method, f"/tasks/arithmetic/{name}", query=query, body=body, peer=PROXY, client=YOUNGER
        )
        return status, text

    def answer(self, name: str) -> dict:
        """Ask for the next question of the open attempt and answer it right."""
        status, body = self.task("POST", name, "question")
        assert status == 200, body
        question = json.loads(body)
        reply = json.dumps({"id": question["id"], "answer": "13", "expired": False}).encode()
        status, body = self.task("POST", name, "answer", reply)
        assert status == 200, body
        return json.loads(body)

    def open_task(self, name: str) -> None:
        status, page = self.task("GET", name)
        assert status == 200, page
        status, body = self.task("POST", name, "visit")
        assert status == 200, body


@pytest.fixture
def service(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    return Service(tmp_path, monkeypatch)


# Decisions


def test_the_next_request_after_a_reload_is_decided_by_the_new_policy(service):
    assert service.decide(READING)["message"] == "No reading."
    service.edit(NO_READING, "when_true: { action: allow }")
    status, answer = service.reload()
    assert status == 200
    assert answer["reloaded"] is True
    assert "entry gate" in answer["summary"]
    assert "client group younger: 192.0.2.40" in answer["summary"]
    assert "site group entertainment: priority 10, 1 patterns" in answer["summary"]
    assert any(line.startswith("task pages are https://tasks.example/") for line in answer["summary"])
    assert service.decide(READING) == {"action": "allow"}


@pytest.mark.parametrize(
    ("peer", "scheme"),
    [(PROXY, "http"), (YOUNGER, "http"), ("127.0.0.1", "https"), ("::ffff:127.0.0.2", "http")],
)
def test_no_other_peer_and_no_https_request_can_reload(service, peer, scheme):
    service.edit(NO_READING, "when_true: { action: allow }")
    status, answer = service.reload(peer=peer, scheme=scheme)
    assert status == 404
    assert "reloaded" not in answer
    assert service.decide(READING)["message"] == "No reading."


def test_a_policy_with_errors_is_refused_and_the_old_one_stays_in_force(service):
    service.edit(NO_READING, "when_true: { action: allow }")
    service.edit("priority: 20", "priority: 10")
    service.edit("entry: gate", "entry: gate\nbucket_lenght: 5m")
    status, answer = service.reload()
    assert status == 200
    assert answer["reloaded"] is False
    assert len(answer["errors"]) == 2
    assert "unknown setting bucket_lenght" in answer["errors"][0]
    assert "both have priority 10" in answer["errors"][1]
    assert service.decide(READING)["message"] == "No reading."


def test_a_missing_policy_file_is_refused_and_does_not_leave_the_service_with_no_policy(service):
    service.policy_file.unlink()
    status, answer = service.reload()
    assert answer["reloaded"] is False
    assert answer["errors"] == [f"{service.policy_file}: the policy file does not exist"]
    assert service.decide(READING)["message"] == "No reading."


def test_a_change_in_an_included_file_is_reloaded(service):
    service.edit("entry: gate", "entry: gate\ninclude: [extra]")
    (service.directory / "extra").mkdir()
    extra = service.directory / "extra" / "sites.yaml"
    extra.write_text("site_groups:\n  news:\n    priority: 30\n    patterns: [news.example]\n", encoding="utf-8")
    assert service.reload()[1]["reloaded"] is True
    service.decide("https://news.example/")
    assert service.last_logged()["site_group"] == "news"
    extra.write_text("site_groups:\n  papers:\n    priority: 30\n    patterns: [news.example]\n", encoding="utf-8")
    assert service.reload()[1]["reloaded"] is True
    service.decide("https://news.example/")
    assert service.last_logged()["site_group"] == "papers"


def test_a_new_timezone_moves_the_household_clock_from_the_next_request(service):
    service.decide(READING, at="2026-11-02T23:30:00+00:00")
    assert service.last_logged()["local_time"] == "2026-11-02T18:30:00-05:00"
    service.edit("timezone: America/Toronto", "timezone: Australia/Sydney")
    assert service.reload()[1]["reloaded"] is True
    service.decide(READING, at="2026-11-02T23:30:00+00:00")
    assert service.last_logged()["local_time"] == "2026-11-03T10:30:00+11:00"


def test_a_new_hostname_changes_where_the_proxy_sends_him_for_revision(service):
    service.edit(NO_READING, "when_true: { action: redirect, location: revision_task }")
    service.reload()
    assert service.decide(READING)["location"].startswith("https://tasks.example/tasks/")
    service.edit("hostname: tasks.example", "hostname: revision.example")
    service.reload()
    assert service.decide(READING)["location"].startswith("https://revision.example/tasks/")


def test_a_new_quota_limit_applies_to_the_usage_already_recorded_today(service):
    moment = datetime(2026, 11, 2, 14, 0, 1, tzinfo=TORONTO)
    with UsageStore(service.database) as usage:
        usage.file_observation("younger", "entertainment", moment, 1500, ["video"])
    assert service.decide(VIDEO)["message"] == "That's enough video."
    service.edit("bytes: 1000b", "bytes: 5000b")
    assert service.reload()[1]["reloaded"] is True
    assert service.decide(VIDEO) == {"action": "allow"}


def test_a_new_bucket_length_closes_the_open_buckets_and_keeps_the_usage(service):
    now = datetime.now(TORONTO)
    with UsageStore(service.database) as usage:
        assert usage.bucket_regimes() == [{"length": 300}]
        usage.file_observation("younger", "entertainment", now, 40, ["video"])
    service.edit("bucket_length: 5m", "bucket_length: 10m")
    assert service.reload()[1]["reloaded"] is True
    with UsageStore(service.database) as usage:
        assert [regime["length"] for regime in usage.bucket_regimes()] == [300, 600]
        [(_day, _start, length, nbytes)] = usage.site_buckets("younger", "entertainment", now.date())
        assert nbytes == 40
        assert length < 300


def test_reloading_twice_with_no_change_succeeds_and_changes_nothing(service):
    first = service.reload()[1]
    second = service.reload()[1]
    assert first["reloaded"] is second["reloaded"] is True
    assert [line for line in first["summary"] if "local time" not in line] == [
        line for line in second["summary"] if "local time" not in line
    ]
    with UsageStore(service.database) as usage:
        assert usage.bucket_regimes() == [{"length": 300}]
    assert service.decide(READING)["message"] == "No reading."


def test_a_signed_in_parent_stays_signed_in_across_a_reload(service):
    from policy.accounts import Accounts

    with PolicyStore(service.database) as store:
        Accounts(store.connection).set_password("ada", PASSWORD)
    service.restart()
    status, _body, headers = _call(
        service.app,
        "POST",
        "/parent/api/login",
        body=json.dumps({"username": "ada", "password": PASSWORD}).encode(),
        content_type="application/json",
        scheme="https",
    )
    assert status == 200
    cookie = headers["set-cookie"][0].split(";", 1)[0]
    service.edit(NO_READING, "when_true: { action: allow }")
    assert service.reload()[1]["reloaded"] is True
    for path in ("/parent/api/session", "/parent/api/usage", "/parent/api/attempts"):
        status, body, _headers = _call(service.app, "GET", path, cookie=cookie, scheme="https")
        assert status == 200, body


@pytest.mark.parametrize("apply", ["reload", "restart"])
def test_a_quiz_in_progress_carries_on_as_it_would_after_a_restart(service, apply):
    service.open_task("sums")
    assert service.answer("sums")["finished"] is False
    service.edit('"correct_answers_required": 2', '"correct_answers_required": 3')
    service.edit("    spare:\n", "    more:\n")
    if apply == "reload":
        assert service.reload()[1]["reloaded"] is True
    else:
        service.restart()
    finished = service.answer("sums")
    assert finished["finished"] is True
    with sqlite3.connect(service.database) as connection:
        rows = connection.execute("SELECT task_name, outcome FROM attempts ORDER BY id").fetchall()
    assert rows == [("sums", "pass")]

    service.open_task("sums")
    assert [service.answer("sums")["finished"] for _ in range(3)] == [False, False, True]
    assert service.task("GET", "more")[0] == 200
    assert service.task("GET", "spare")[0] == 302


# Observations


def test_the_observations_service_reloads_only_from_its_own_loopback(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text(_metered("1000b"), encoding="utf-8")
    with _observations(tmp_path, path) as port:
        path.write_text(_metered("5000b"), encoding="utf-8")
        assert _post(port, "/v1/reload", source="127.0.0.2") == (404, b"not found")
        status, body = _post(port, "/v1/reload")
        assert status == 200
        assert json.loads(body) == {"reloaded": True, "warnings": []}
        path.write_text("bucket_lenght: 5m\n" + _metered("1000b"), encoding="utf-8")
        status, body = _post(port, "/v1/reload")
        answer = json.loads(body)
        assert answer["reloaded"] is False
        assert answer["errors"] == [f"{path}:1:1: unknown setting bucket_lenght"]


def test_a_reload_leaves_a_running_transfer_alone_until_its_ceiling(tmp_path):
    from policy.engine import judge

    path = tmp_path / "policy.yaml"
    path.write_text(_metered("1000b"), encoding="utf-8")
    with _observations(tmp_path, path) as port, UsageStore(tmp_path / "policy.sqlite3") as usage:
        start = datetime(2026, 10, 21, 15, 0, tzinfo=TORONTO)
        trace, assumption = judge(load(path), client_ip=YOUNGER, url=VIDEO, at=start, ledger=usage)
        assert trace.decision == {"action": "allow"}
        usage.save_transfer("flow-1", trace.client_group, trace.site_group, VIDEO, assumption)

        path.write_text(_metered("1000b").replace("when_true: { action: allow }", "when_true: { action: deny, message: No. }"), encoding="utf-8")
        assert json.loads(_post(port, "/v1/reload")[1])["reloaded"] is True
        assert _post(port, "/v1/observations", _report(start, 600)) == (204, b"")

        path.write_text(_metered("5000b"), encoding="utf-8")
        assert json.loads(_post(port, "/v1/reload")[1])["reloaded"] is True
        assert _post(port, "/v1/observations", _report(start, 600)) == (204, b"")

        path.write_text(_metered("1000b"), encoding="utf-8")
        assert json.loads(_post(port, "/v1/reload")[1])["reloaded"] is True
        assert _post(port, "/v1/observations", _report(start, 3000)) == (204, b"")
        assert _post(port, "/v1/observations", _report(start, 800)) == (200, CUT_BODY)


def _metered(limit: str) -> str:
    return f"""\
entry: entry
timezone: America/Toronto
client_groups:
  younger:
    addresses: ["{YOUNGER}"]
site_groups:
  entertainment:
    priority: 10
    patterns: [www.youtube.com]
quotas:
  video:
    bytes: {limit}
    volume_grace: 0b
    ruleset: meter
rule_sets:
  meter:
    - condition: site_group
      group: entertainment
      when_false: {{ action: deny, message: "Not video." }}
  entry:
    - condition: volume_remaining
      quota: video
      when_true: {{ action: allow }}
      when_false: {{ action: deny, message: "That's enough video." }}
"""


def _report(moment: datetime, nbytes: int) -> dict:
    return {"client_ip": YOUNGER, "url": VIDEO, "occurred_at": moment.isoformat(), "bytes": nbytes, "flow_id": "flow-1"}


class _observations:
    """Serve the observations service on a free loopback port, as main does."""

    def __init__(self, directory: Path, path: Path):
        self.store = PolicyStore(directory / "policy.sqlite3", check_same_thread=False)
        usage = UsageStore(connection=self.store.connection)
        self.server = listen(load(path), usage, "127.0.0.1", 0, directory / "observations.jsonl", policy_file=path)

    def __enter__(self) -> int:
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self.server.server_address[1]

    def __exit__(self, *_exc) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.store.close()


def _post(port: int, path: str, document: dict | None = None, *, source: str = "127.0.0.1") -> tuple[int, bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5, source_address=(source, 0))
    try:
        body = b"" if document is None else json.dumps(document).encode()
        connection.request("POST", path, body=body, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def _call(app, method, path, *, query=b"", body=b"", cookie=None, content_type=None, scheme="http", peer="127.0.0.1", client=None):
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

    headers = [(b"content-type", (content_type or "application/json").encode())]
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    if client:
        headers.append((b"x-daywarden-client", client.encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": scheme,
        "path": path,
        "raw_path": path.encode(),
        "query_string": query,
        "headers": headers,
        "client": (peer, 12345),
        "server": ("127.0.0.1", 443 if scheme == "https" else 8090),
        "root_path": "",
    }
    asyncio.run(app(scope, receive, send))
    start = next(item for item in messages if item["type"] == "http.response.start")
    payload = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
    found: dict[str, list[str]] = {}
    for key, value in start["headers"]:
        found.setdefault(key.decode(), []).append(value.decode())
    return start["status"], payload.decode(), found
