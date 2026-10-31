"""S001.1 through S001.5, and the S002.2 report route: the policy service stores
clients, the timezone, site groups, rules, today's revision count, and today's
usage, keeps them across a restart, and leaves the usage report closed until
a parent account is added."""

import json
import os
import socket
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
DECISION_LOG = "/tmp/decisions.jsonl"
SYDNEY = ZoneInfo("Australia/Sydney")

POLICY = """
[household]
timezone = "Australia/Sydney"
revision_task = "http://tasks.example/next"

[[clients]]
name = "Younger child"
address = "192.0.2.40"

[[clients]]
name = "Older child"
address = "older-child.household.test"

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
quota = "2h"
patterns = ["*.youtube.com", "youtu.be"]

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
UNGROUPED = {"action": "deny", "status": 403, "message": "This site is not in a configured group."}
PLACEHOLDER = "http://tasks.example/next"
BEDTIME = {"action": "deny", "status": 403, "message": "It's bedtime."}
CLOSED = {"action": "deny", "status": 403, "message": "YouTube is closed for today."}
REDIRECT = {"action": "redirect", "status": 302, "location": PLACEHOLDER}
ALLOW = {"action": "allow"}
TIME_UP = {"action": "deny", "status": 403, "message": "Time is up for today."}

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


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Stack:
    def __init__(self, ca_dir: Path, config_dir: Path, project: str):
        self.config_dir = config_dir
        self.env = os.environ.copy()
        self.env["PROXY_PORT"] = str(_free_port())
        self.env["REPORT_PORT"] = str(_free_port())
        self.env["PARENT_PASSWORD"] = ""
        self.env["CA_VOLUME_PATH"] = str(ca_dir)
        self.env["SMARTPROXY_CONFIG_DIR"] = str(config_dir)
        self.env["POLICY_FILE"] = "/etc/smartproxy/policy.toml"
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

    def up_decisions(self, *extra):
        self.run(["up", "-d", "--wait", "--wait-timeout", "120", *extra, "decisions"])

    def down(self):
        self.run(["down", "-v", "--remove-orphans", "--timeout", "5"], check=False, timeout=60)

    def logs(self) -> str:
        completed = self.run(["logs", "--no-color", "decisions"], check=False, timeout=30)
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


def _request(
    client_ip: str,
    occurred_at: str = "2026-10-19T12:59:59+00:00",
    url: str = "https://www.youtube.com/watch?v=abc",
) -> dict:
    return {
        "client_ip": client_ip,
        "method": "GET",
        "url": url,
        "occurred_at": occurred_at,
    }


@pytest.fixture(scope="module")
def stack(request):
    with tempfile.TemporaryDirectory(prefix="smartproxy-s0011-") as raw:
        root = Path(raw)
        (root / "ca").mkdir()
        config_dir = root / "config"
        config_dir.mkdir()
        (config_dir / "decision.json").write_text('{"action": "allow", "marker": "from the file"}')
        (config_dir / "policy.toml").write_text(POLICY)
        running = Stack(root / "ca", config_dir, f"smartproxy-s0011-{os.getpid()}")
        try:
            running.up_decisions()
            yield running
        except Exception:
            print(running.logs())
            raise
        finally:
            if request.session.testsfailed:
                print(running.logs())
            running.down()


def _local(hour: int, minute: int, day: int = 21) -> str:
    """UTC instant for a Sydney wall time. 21 October 2026 is a Wednesday."""
    return datetime(2026, 10, day, hour, minute, tzinfo=SYDNEY).astimezone(timezone.utc).isoformat()


def _assert_household(stack: Stack):
    status, body, entry = stack.decide(_request("192.0.2.40"))
    assert status == 200
    assert json.loads(body) == CLOSED
    assert "from the file" not in body
    assert entry["client"] == "Younger child"
    assert entry["request"] == _request("192.0.2.40")
    local = datetime.fromisoformat(entry["local_time"])
    assert local == datetime(2026, 10, 19, 23, 59, 59, tzinfo=SYDNEY)
    assert local.utcoffset() == SYDNEY.utcoffset(datetime(2026, 10, 19, 23, 59, 59))

    _status, _body, entry = stack.decide(_request("192.0.2.41"))
    assert entry["client"] == "Older child"

    _status, _body, entry = stack.decide(_request("192.0.2.40", "2026-10-19T13:00:00+00:00"))
    assert datetime.fromisoformat(entry["local_time"]).date().isoformat() == "2026-10-20"


def _assert_groups(stack: Stack):
    _status, body, entry = stack.decide(_request("192.0.2.40"))
    assert json.loads(body) == CLOSED
    assert entry["group"] == "Entertainment"

    status, body, entry = stack.decide(_request("192.0.2.40", url="https://Classroom.Google.com/u/0/h"))
    assert status == 200
    assert json.loads(body) == ALLOW
    assert entry["group"] == "School work"

    status, body, entry = stack.decide(_request("192.0.2.40", url="https://example.org/"))
    assert status == 200
    assert json.loads(body) == UNGROUPED
    assert entry["group"] is None
    assert entry["decision"] == UNGROUPED

    wednesday = {
        (6, 30): BEDTIME,
        (10, 0): REDIRECT,
        (16, 0): REDIRECT,
        (20, 0): CLOSED,
    }
    for (hour, minute), expected in wednesday.items():
        status, body, entry = stack.decide(_request("192.0.2.40", _local(hour, minute)))
        assert status == 200
        assert json.loads(body) == expected
        assert entry["group"] == "Entertainment"
        assert datetime.fromisoformat(entry["local_time"]) == datetime(2026, 10, 21, hour, minute, tzinfo=SYDNEY)


SET_COUNT = """
import json, sys
from datetime import date
from policy.store import PolicyStore
document = json.load(sys.stdin)
store = PolicyStore("/var/lib/smartproxy/policy.sqlite3")
row = store.connection.execute(
    "SELECT id FROM clients WHERE name = ?", (document["name"],)
).fetchone()
if row is None:
    raise SystemExit("no client " + document["name"])
store.set_task_completions(row[0], date.fromisoformat(document["day"]), document["count"])
store.close()
"""


def test_clients_are_named_and_time_is_household_local(stack):
    _assert_household(stack)


def test_urls_are_put_in_site_groups_and_rules_decide(stack):
    _assert_groups(stack)
    logs = stack.logs()
    assert "no default group" in logs
    assert "revision task placeholder http://tasks.example/next" in logs
    assert "group Entertainment: priority 30, 2 patterns, 5 rules, quota 2h, no byte limit" in logs
    assert "usage buckets are 5m" in logs


MARK_BUCKETS = """
import json, sys
from datetime import datetime, timedelta
from policy.store import PolicyStore
document = json.load(sys.stdin)
store = PolicyStore("/var/lib/smartproxy/policy.sqlite3")
row = store.connection.execute(
    "SELECT id FROM clients WHERE name = ?", (document["name"],)
).fetchone()
if row is None:
    raise SystemExit("no client " + document["name"])
start = datetime.fromisoformat(document["start"])
step = timedelta(minutes=5)
for index in range(document["count"]):
    store.mark_bucket(
        row[0], document["group"], start + index * step, length_seconds=300
    )
store.close()
"""

CLEAR_BUCKETS = """
from policy.store import PolicyStore
store = PolicyStore("/var/lib/smartproxy/policy.sqlite3")
store.connection.execute("DELETE FROM usage_buckets")
store.connection.commit()
store.close()
"""


def _set_count(stack: Stack, name: str, day: str, count: int) -> None:
    stack.run(
        ["exec", "-T", "decisions", "python", "-c", SET_COUNT],
        stdin=json.dumps({"name": name, "day": day, "count": count}),
        timeout=30,
    )


def test_a_stored_count_of_two_allows_wednesday_evening_and_one_redirects(stack):
    try:
        _set_count(stack, "Younger child", "2026-10-21", 2)
        status, body, entry = stack.decide(_request("192.0.2.40", _local(16, 0)))
        assert status == 200
        assert json.loads(body) == ALLOW
        assert entry["client"] == "Younger child"

        _set_count(stack, "Younger child", "2026-10-21", 1)
        status, body, _entry = stack.decide(_request("192.0.2.40", _local(16, 0)))
        assert status == 200
        assert json.loads(body) == REDIRECT
    finally:
        _set_count(stack, "Younger child", "2026-10-21", 0)


def _mark_buckets(stack: Stack, name: str, group: str, start: str, count: int) -> None:
    stack.run(
        ["exec", "-T", "decisions", "python", "-c", MARK_BUCKETS],
        stdin=json.dumps({"name": name, "group": group, "start": start, "count": count}),
        timeout=30,
    )


def _clear_buckets(stack: Stack) -> None:
    stack.run(["exec", "-T", "decisions", "python", "-c", CLEAR_BUCKETS], timeout=30)


def test_twenty_three_buckets_allow_wednesday_evening_and_twenty_four_deny(stack):
    try:
        _set_count(stack, "Younger child", "2026-10-21", 2)
        _mark_buckets(stack, "Younger child", "Entertainment", "2026-10-21T08:00:00", 23)
        status, body, entry = stack.decide(_request("192.0.2.40", _local(16, 0)))
        assert status == 200
        assert json.loads(body) == ALLOW
        assert entry["group"] == "Entertainment"

        _mark_buckets(stack, "Younger child", "Entertainment", "2026-10-21T08:00:00", 24)
        status, body, _entry = stack.decide(_request("192.0.2.40", _local(16, 0)))
        assert status == 200
        assert json.loads(body) == TIME_UP
    finally:
        _clear_buckets(stack)
        _set_count(stack, "Younger child", "2026-10-21", 0)


OBSERVE = """
import json, sys, urllib.error, urllib.request
request = urllib.request.Request(
    "http://127.0.0.1:8091/v1/observations",
    data=sys.stdin.buffer.read(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=5) as response:
        print(response.status)
except urllib.error.HTTPError as error:
    print(error.code)
"""

LEDGER = """
import json
from datetime import datetime
from policy.store import PolicyStore
store = PolicyStore("/var/lib/smartproxy/policy.sqlite3")
(client_id,) = store.connection.execute(
    "SELECT id FROM clients WHERE name = 'Younger child'"
).fetchone()
rows = store.connection.execute(
    "SELECT started_at, length_seconds, byte_count FROM usage_buckets ORDER BY started_at"
).fetchall()
print(json.dumps({
    "rows": rows,
    "while_open": store.consumed_seconds(client_id, "Entertainment", datetime(2026, 10, 21, 15, 4)),
    "once_closed": store.consumed_seconds(client_id, "Entertainment", datetime(2026, 10, 21, 15, 5)),
}))
store.close()
"""


def _observe(stack: Stack, document: dict) -> int:
    completed = stack.run(
        ["exec", "-T", "observations", "python", "-c", OBSERVE],
        stdin=json.dumps(document),
        timeout=30,
    )
    return int(completed.stdout.strip())


def test_an_observation_marks_a_bucket_the_quota_reads(stack):
    stack.run(["up", "-d", "--wait", "--wait-timeout", "120", "observations"], timeout=300)
    try:
        moment = datetime(2026, 10, 21, 15, 0, 1, tzinfo=SYDNEY).isoformat()
        assert _observe(stack, {
            "client_ip": "192.0.2.40",
            "url": "https://www.youtube.com/watch?v=abc",
            "occurred_at": moment,
            "bytes": 100,
        }) == 204
        assert _observe(stack, {
            "client_ip": "192.0.2.40",
            "url": "https://example.org/",
            "occurred_at": moment,
            "bytes": 50,
        }) == 204
        later = datetime(2026, 10, 21, 15, 1, tzinfo=SYDNEY).isoformat()
        assert _observe(stack, {
            "client_ip": "192.0.2.40",
            "url": "https://www.youtube.com/watch?v=abc",
            "occurred_at": later,
            "bytes": 40,
        }) == 204
        completed = stack.run(
            ["exec", "-T", "decisions", "python", "-c", LEDGER],
            timeout=30,
        )
        report = json.loads(completed.stdout)
        assert report["rows"] == [["2026-10-21T15:00:00", 300, 140]]
        assert report["while_open"] == 0
        assert report["once_closed"] == 300
    finally:
        _clear_buckets(stack)


def test_an_unenrolled_ip_still_gets_a_decision(stack):
    status, body, entry = stack.decide(_request("192.0.2.99"))
    assert status == 200
    assert json.loads(body) == CLOSED
    assert entry["client"] is None


def test_a_malformed_request_is_refused(stack):
    status, _body, entry = stack.decide({"method": "GET", "url": "http://x/"})
    assert status == 400
    assert entry["decision"] is None


GET_USAGE = """
import json, urllib.error, urllib.request
request = urllib.request.Request(
    "http://127.0.0.1:8090/usage",
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


def test_the_usage_report_is_closed_without_a_parent_password(stack):
    completed = stack.run(["exec", "-T", "decisions", "python", "-c", GET_USAGE], timeout=30)
    answer = json.loads(completed.stdout)
    assert answer["status"] == 403
    assert "Open this page over HTTPS." in answer["body"]
    assert "Younger child" not in answer["body"]
    assert "00:30" not in answer["body"]
    assert answer["set_cookie"] is None
    assert "usage report is closed until a parent account is added" in stack.logs()


def test_clients_timezone_groups_and_rules_survive_a_new_container_without_the_file(stack):
    (stack.config_dir / "policy.toml").unlink()
    stack.up_decisions("--force-recreate", "--no-deps")
    assert "using the stored policy" in stack.logs()
    _assert_household(stack)
    _assert_groups(stack)
