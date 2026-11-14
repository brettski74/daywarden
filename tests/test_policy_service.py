"""The policy service stack: the decisions and observations services load the
household policy, resolve a client group named by DNS, decide in household
time, file observations the quota reads, keep that usage across new
containers, and leave the usage report closed until a parent account is
added."""

import json
import os
import socket
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
DECISION_LOG = "/tmp/decisions.jsonl"
SYDNEY = ZoneInfo("Australia/Sydney")

POLICY = """\
entry: household
timezone: Australia/Sydney
bucket_length: 5m

client_groups:
  younger:
    addresses: ["192.0.2.40"]
  older:
    addresses: ["older-child.household.test"]

site_groups:
  school:
    priority: 10
    patterns: ["classroom.google.com"]
  entertainment:
    priority: 30
    patterns: ["*.youtube.com", "youtu.be"]

time_windows:
  bedtime:
    periods:
      - start: "00:00"
        end: "07:00"
        days: monday-thursday

quotas:
  entertainment:
    time: 2h
    ruleset: entertainment_meter

rule_sets:
  entertainment_meter:
    - condition: site_group
      group: entertainment
      when_true: { action: continue }
      when_false: { action: deny, message: "Not entertainment." }

  household:
    - condition: site_group
      group: school
      when_true: { action: allow }
    - condition: site_group
      group: entertainment
      when_true: { action: evaluate, ruleset: entertainment }
      when_false: { action: deny, message: "Not on the list." }

  entertainment:
    - condition: time_window
      window: bedtime
      when_true: { action: deny, message: "It's bedtime." }
    - condition: time_remaining
      quota: entertainment
      when_true: { action: allow }
      when_false: { action: deny, message: "Time is up for today." }
"""
ALLOW = {"action": "allow"}
BEDTIME = {"action": "deny", "status": 403, "message": "It's bedtime."}
NOT_LISTED = {"action": "deny", "status": 403, "message": "Not on the list."}
TIME_UP = {"action": "deny", "status": 403, "message": "Time is up for today."}
YOUTUBE = "https://www.youtube.com/watch?v=abc"

# Runs inside the container, so the test does not need a published port.
POST = """
import json, sys, urllib.error, urllib.request
request = urllib.request.Request(
    "http://127.0.0.1:8090/v1/decisions",
    data=sys.stdin.buffer.read(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=5) as response:
        print(json.dumps({"status": response.status, "body": response.read().decode()}))
except urllib.error.HTTPError as error:
    print(json.dumps({"status": error.code, "body": error.read().decode()}))
"""

OBSERVE = """
import json, sys, urllib.error, urllib.request
statuses = []
for document in json.load(sys.stdin):
    request = urllib.request.Request(
        "http://127.0.0.1:8091/v1/observations",
        data=json.dumps(document).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            statuses.append(response.status)
    except urllib.error.HTTPError as error:
        statuses.append(error.code)
print(json.dumps(statuses))
"""

LEDGER = """
import json, sys
from datetime import date, datetime
from policy.usage import UsageStore
asked = json.load(sys.stdin)
with UsageStore("/var/lib/daywarden/policy.sqlite3") as usage:
    day = date.fromisoformat(asked["day"])
    print(json.dumps({
        "entertainment": [
            [start.isoformat(), length, nbytes]
            for _day, start, length, nbytes in usage.site_buckets(asked["client"], "entertainment", day)
        ],
        "default": [
            [start.isoformat(), length, nbytes]
            for _day, start, length, nbytes in usage.site_buckets(asked["client"], "default", day)
        ],
        "ended": {
            moment: usage.ended_seconds(asked["client"], "entertainment", datetime.fromisoformat(moment))
            for moment in asked["ended_at"]
        },
    }))
"""

GET_USAGE = """
import json, urllib.error, urllib.request
request = urllib.request.Request(
    "http://127.0.0.1:8090/parent/api/usage/minutes?client=younger",
    headers={"X-Forwarded-Proto": "https"},
)
try:
    with urllib.request.urlopen(request, timeout=5) as response:
        answer = response
        status = response.status
        body = response.read().decode()
except urllib.error.HTTPError as error:
    answer = error
    status = error.code
    body = error.read().decode()
print(json.dumps({
    "status": status,
    "body": body,
    "set_cookie": answer.headers.get("Set-Cookie"),
}))
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Stack:
    def __init__(self, ca_dir: Path, config_dir: Path, project: str):
        self.config_dir = config_dir
        self.env = os.environ.copy()
        self.env["PROXY_PORT"] = str(_free_port())
        self.env["POLICY_PORT"] = str(_free_port())
        self.env["PROXY_CONFIG_PORT"] = str(_free_port())
        self.env["PARENT_PASSWORD"] = ""
        self.env["CA_VOLUME_PATH"] = str(ca_dir)
        self.env["DAYWARDEN_CONFIG_DIR"] = str(config_dir)
        self.env["POLICY_FILE"] = "/etc/daywarden/policy.yaml"
        self.cmd = [
            "docker", "compose", "-p", project,
            "-f", "docker-compose.yml", "-f", "tests/policy.compose.yml",
        ]

    def run(self, args, *, check=True, timeout=300, stdin=None):
        completed = subprocess.run(
            self.cmd + args, cwd=ROOT, env=self.env, text=True,
            input=stdin, capture_output=True, timeout=timeout,
        )
        if check and completed.returncode != 0:
            raise AssertionError(
                f"{args} exited {completed.returncode}\n{completed.stdout}\n{completed.stderr}"
            )
        return completed

    def up(self, *extra):
        self.run(["up", "-d", "--wait", "--wait-timeout", "120", *extra, "decisions", "observations"])

    def down(self):
        self.run(["down", "-v", "--remove-orphans", "--timeout", "5"], check=False, timeout=60)

    def logs(self, service: str = "decisions") -> str:
        completed = self.run(["logs", "--no-color", service], check=False, timeout=30)
        return completed.stdout + completed.stderr

    def decide(self, document: dict) -> tuple[int, str, dict]:
        """POST a decision request and return the status, body, and log entry it wrote."""
        self.run(["exec", "-T", "decisions", "rm", "-f", DECISION_LOG], timeout=20)
        completed = self.run(
            ["exec", "-T", "decisions", "python", "-c", POST],
            stdin=json.dumps(document), timeout=30,
        )
        answer = json.loads(completed.stdout)
        logged = self.run(["exec", "-T", "decisions", "cat", DECISION_LOG], timeout=20)
        entries = [json.loads(line) for line in logged.stdout.splitlines() if line.strip()]
        assert len(entries) == 1, entries
        return answer["status"], answer["body"], entries[0]

    def observe(self, documents: list[dict]) -> list[int]:
        completed = self.run(
            ["exec", "-T", "observations", "python", "-c", OBSERVE],
            stdin=json.dumps(documents), timeout=60,
        )
        return json.loads(completed.stdout)

    def ledger(self, client: str, day: str, ended_at: list[str]) -> dict:
        completed = self.run(
            ["exec", "-T", "decisions", "python", "-c", LEDGER],
            stdin=json.dumps({"client": client, "day": day, "ended_at": ended_at}), timeout=30,
        )
        return json.loads(completed.stdout)


@pytest.fixture(scope="module")
def stack(request):
    with tempfile.TemporaryDirectory(prefix="daywarden-policy-") as raw:
        root = Path(raw)
        (root / "ca").mkdir()
        config_dir = root / "config"
        config_dir.mkdir()
        (config_dir / "policy.yaml").write_text(POLICY, encoding="utf-8")
        running = Stack(root / "ca", config_dir, f"daywarden-policy-{os.getpid()}")
        try:
            running.up()
            yield running
        except Exception:
            print(running.logs())
            raise
        finally:
            if request.session.testsfailed:
                print(running.logs())
                print(running.logs("observations"))
            running.down()


def _local(hour: int, minute: int, second: int = 0, *, day: int) -> datetime:
    """A Sydney wall time in October 2026. The 21st is a Wednesday."""
    return datetime(2026, 10, day, hour, minute, second, tzinfo=SYDNEY)


def _request(client_ip: str, occurred_at: str, url: str = YOUTUBE) -> dict:
    return {"client_ip": client_ip, "method": "GET", "url": url, "occurred_at": occurred_at}


def _report(client_ip: str, moment: datetime, nbytes: int, url: str = YOUTUBE) -> dict:
    return {"client_ip": client_ip, "url": url, "occurred_at": moment.isoformat(), "bytes": nbytes}


def _morning(client_ip: str, count: int, *, day: int) -> list[dict]:
    """One report in each of count five-minute buckets from 08:00."""
    start = _local(8, 0, 1, day=day)
    return [_report(client_ip, start + timedelta(minutes=5 * index), 10) for index in range(count)]


def _assert_household(stack: Stack):
    request = _request("192.0.2.40", "2026-10-19T12:59:59+00:00")
    status, body, entry = stack.decide(request)
    assert status == 200
    assert json.loads(body) == ALLOW
    assert entry["request"] == request
    assert entry["client_group"] == "younger"
    assert entry["site_group"] == "entertainment"
    local = datetime.fromisoformat(entry["local_time"])
    assert local == datetime(2026, 10, 19, 23, 59, 59, tzinfo=SYDNEY)
    assert local.utcoffset() == SYDNEY.utcoffset(datetime(2026, 10, 19, 23, 59, 59))

    status, body, entry = stack.decide(_request("192.0.2.41", "2026-10-19T13:00:00+00:00"))
    assert json.loads(body) == BEDTIME
    assert entry["client_group"] == "older"
    assert datetime.fromisoformat(entry["local_time"]).date().isoformat() == "2026-10-20"
    assert (entry["rule_set"], entry["rule_index"]) == ("entertainment", 1)


def _assert_rules(stack: Stack):
    wednesday = _local(16, 0, day=21).astimezone(timezone.utc).isoformat()
    status, body, entry = stack.decide(_request("192.0.2.40", wednesday, "https://Classroom.Google.com/u/0/h"))
    assert (status, json.loads(body)) == (200, ALLOW)
    assert entry["site_group"] == "school"

    status, body, entry = stack.decide(_request("192.0.2.40", wednesday, "https://example.org/"))
    assert (status, json.loads(body)) == (200, NOT_LISTED)
    assert entry["site_group"] == "default"
    assert entry["decision"] == NOT_LISTED

    status, body, entry = stack.decide(_request("192.0.2.99", wednesday))
    assert (status, json.loads(body)) == (200, ALLOW)
    assert entry["client_group"] == "default"

    early = _local(6, 30, day=21).astimezone(timezone.utc).isoformat()
    _status, body, _entry = stack.decide(_request("192.0.2.40", early))
    assert json.loads(body) == BEDTIME


def test_a_dns_named_client_group_resolves_and_time_is_household_local(stack):
    _assert_household(stack)
    logs = stack.logs()
    assert "client group older: 192.0.2.41" in logs
    assert "client group younger: 192.0.2.40" in logs


def test_site_groups_and_rule_sets_decide(stack):
    _assert_rules(stack)
    logs = stack.logs()
    assert "household timezone Australia/Sydney" in logs
    assert "entry household" in logs
    assert "usage buckets are 5m" in logs
    assert "site group entertainment: priority 30, 2 patterns" in logs


def test_an_observation_is_filed_and_the_quota_reads_it(stack):
    moment = _local(15, 0, 1, day=21)
    assert stack.observe([
        _report("192.0.2.40", moment, 100),
        _report("192.0.2.40", moment, 50, url="https://example.org/"),
        _report("192.0.2.40", _local(15, 1, day=21), 40),
    ]) == [204, 204, 204]
    ledger = stack.ledger(
        "younger", "2026-10-21", ["2026-10-21T15:04:59", "2026-10-21T15:05:00"]
    )
    assert ledger["entertainment"] == [["2026-10-21T15:00:00", 300, 140]]
    assert ledger["default"] == [["2026-10-21T15:00:00", 300, 50]]
    assert ledger["ended"] == {"2026-10-21T15:04:59": 0, "2026-10-21T15:05:00": 300}


def test_twenty_three_buckets_leave_time_and_twenty_four_use_it_up(stack):
    afternoon = _local(16, 0, day=22).astimezone(timezone.utc).isoformat()
    assert stack.observe(_morning("192.0.2.41", 23, day=22)) == [204] * 23
    _status, body, entry = stack.decide(_request("192.0.2.41", afternoon))
    assert json.loads(body) == ALLOW
    assert entry["client_group"] == "older"

    assert stack.observe([_report("192.0.2.41", _local(9, 55, 1, day=22), 10)]) == [204]
    _status, body, _entry = stack.decide(_request("192.0.2.41", afternoon))
    assert json.loads(body) == TIME_UP
    _status, body, _entry = stack.decide(_request("192.0.2.40", afternoon))
    assert json.loads(body) == ALLOW


def test_a_malformed_request_is_refused(stack):
    document = {"method": "GET", "url": "http://x/"}
    status, _body, entry = stack.decide(document)
    assert status == 400
    assert entry == {"request": document, "decision": None}


def test_the_usage_report_is_closed_without_a_parent_account(stack):
    completed = stack.run(["exec", "-T", "decisions", "python", "-c", GET_USAGE], timeout=30)
    answer = json.loads(completed.stdout)
    assert answer["status"] == 403
    assert "Open this page over HTTPS." in answer["body"]
    assert "younger" not in answer["body"]
    assert answer["set_cookie"] is None
    assert "parent portal is closed until a parent account is added" in stack.logs()


def test_the_policy_and_stored_usage_survive_new_containers(stack):
    afternoon = _local(16, 0, day=23).astimezone(timezone.utc).isoformat()
    assert stack.observe(_morning("192.0.2.40", 24, day=23)) == [204] * 24
    _status, body, _entry = stack.decide(_request("192.0.2.40", afternoon))
    assert json.loads(body) == TIME_UP

    stack.up("--force-recreate", "--no-deps")
    assert "loading /etc/daywarden/policy.yaml" in stack.logs()
    _status, body, _entry = stack.decide(_request("192.0.2.40", afternoon))
    assert json.loads(body) == TIME_UP
    ledger = stack.ledger("younger", "2026-10-23", ["2026-10-23T16:00:00"])
    assert ledger["ended"] == {"2026-10-23T16:00:00": 2 * 60 * 60}
    _assert_household(stack)
    _assert_rules(stack)
