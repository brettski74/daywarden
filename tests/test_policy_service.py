"""S001.1 and S001.2: the policy service stores clients, the timezone, and site groups,
and keeps them across a restart."""

import json
import os
import socket
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
DECISION_LOG = "/tmp/decisions.jsonl"
SYDNEY = ZoneInfo("Australia/Sydney")

POLICY = """
[household]
timezone = "Australia/Sydney"

[[clients]]
name = "Younger child"
address = "192.0.2.40"

[[clients]]
name = "Older child"
address = "older-child.household.test"

[[groups]]
name = "Entertainment"
priority = 30
patterns = ["*.youtube.com", "youtu.be"]

[[groups]]
name = "School work"
priority = 10
patterns = ["classroom.google.com"]
"""
UNGROUPED = {"action": "deny", "status": 403, "message": "This site is not in a configured group."}

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
        self.env["CA_VOLUME_PATH"] = str(ca_dir)
        self.env["SMARTPROXY_CONFIG_DIR"] = str(config_dir)
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
        (config_dir / "decision.json").write_text('{"action": "allow"}')
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


def _assert_household(stack: Stack):
    status, body, entry = stack.decide(_request("192.0.2.40"))
    assert status == 200
    assert json.loads(body) == {"action": "allow"}
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
    _status, _body, entry = stack.decide(_request("192.0.2.40"))
    assert entry["group"] == "Entertainment"

    status, body, entry = stack.decide(_request("192.0.2.40", url="https://Classroom.Google.com/u/0/h"))
    assert status == 200
    assert json.loads(body) == {"action": "allow"}
    assert entry["group"] == "School work"

    status, body, entry = stack.decide(_request("192.0.2.40", url="https://example.org/"))
    assert status == 200
    assert json.loads(body) == UNGROUPED
    assert entry["group"] is None
    assert entry["decision"] == UNGROUPED


def test_clients_are_named_and_time_is_household_local(stack):
    _assert_household(stack)


def test_urls_are_put_in_site_groups_and_the_rest_are_denied(stack):
    _assert_groups(stack)
    assert "no default group" in stack.logs()


def test_an_unenrolled_ip_still_gets_a_decision(stack):
    status, body, entry = stack.decide(_request("192.0.2.99"))
    assert status == 200
    assert json.loads(body) == {"action": "allow"}
    assert entry["client"] is None


def test_a_malformed_request_is_refused(stack):
    status, _body, entry = stack.decide({"method": "GET", "url": "http://x/"})
    assert status == 400
    assert entry["decision"] is None


def test_clients_timezone_and_groups_survive_a_new_container_without_the_file(stack):
    (stack.config_dir / "policy.toml").unlink()
    stack.up_decisions("--force-recreate", "--no-deps")
    assert "using the stored policy" in stack.logs()
    _assert_household(stack)
    _assert_groups(stack)
