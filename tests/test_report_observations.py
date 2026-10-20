"""S000.3: forwarded flows report body bytes, and a failed report changes nothing."""

import ipaddress
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DECISION_LOG = "/tmp/decisions.jsonl"
ORIGIN_LOG = "/tmp/origin.jsonl"
OBSERVATION_LOG = "/tmp/observations.jsonl"
DENY_MESSAGE = "Time is up for today."
REDIRECT_LOCATION = "http://192.0.2.1/tasks/next"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _run(cmd, *, env, timeout, check=True):
    completed = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if check and completed.returncode != 0:
        raise AssertionError(
            f"{cmd} exited {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return completed


def _write_decision(config_dir: Path, document) -> None:
    target = config_dir / "decision.json"
    temporary = config_dir / ".decision.json.tmp"
    temporary.write_text(json.dumps(document))
    temporary.replace(target)


class Stack:
    def __init__(self, ca_dir: Path, config_dir: Path, port: int, project: str):
        self.ca_dir = ca_dir
        self.config_dir = config_dir
        self.port = port
        self.project = project
        self.env = os.environ.copy()
        self.env["PROXY_PORT"] = str(port)
        self.env["CA_VOLUME_PATH"] = str(ca_dir)
        self.env["SMARTPROXY_CONFIG_DIR"] = str(config_dir)
        self.env["OBSERVATION_INTERVAL"] = "1"
        self.cmd = [
            "docker",
            "compose",
            "-p",
            project,
            "-f",
            "docker-compose.yml",
            "-f",
            "tests/recording-origin.compose.yml",
        ]

    @property
    def proxy_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def run(self, args, *, check=True, timeout=120):
        return _run(self.cmd + args, env=self.env, timeout=timeout, check=check)

    def up(self):
        self.run(["up", "-d", "--wait", "--wait-timeout", "90"])

    def down(self):
        self.run(["down", "-v", "--remove-orphans", "--timeout", "5"], check=False, timeout=60)

    def logs(self) -> str:
        completed = self.run(["logs", "--no-color"], check=False, timeout=30)
        return completed.stdout + completed.stderr

    def jsonl(self, service: str, path: str) -> list[dict]:
        completed = self.run(["exec", "-T", service, "cat", path], check=False, timeout=20)
        if completed.returncode != 0:
            return []
        return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]

    def clear_jsonl(self, service: str, path: str):
        self.run(["exec", "-T", service, "rm", "-f", path], timeout=20)

    def stop_observations(self):
        self.run(["stop", "--timeout", "5", "observations"], timeout=30)

    def start_observations(self):
        self.run(["up", "-d", "--wait", "--wait-timeout", "30", "--no-deps", "observations"])


def _curl(args, *, timeout=20):
    return subprocess.run(
        ["curl", "-sS", "--http1.1", "--max-time", str(timeout), *args],
        capture_output=True,
        timeout=timeout + 5,
    )


def _exchange(proxy: Stack, url: str, *, method: str = "GET", data: str | None = None, timeout: int = 20):
    header_path = proxy.config_dir / "headers.txt"
    body_path = proxy.config_dir / "body.bin"
    header_path.unlink(missing_ok=True)
    body_path.unlink(missing_ok=True)
    command = [
        "--proxy",
        proxy.proxy_url,
        "-D",
        str(header_path),
        "-o",
        str(body_path),
        "-X",
        method,
    ]
    if data is not None:
        command += ["--data", data]
    command.append(url)
    completed = _curl(command, timeout=timeout)
    headers = header_path.read_text() if header_path.exists() else ""
    body = body_path.read_bytes() if body_path.exists() else b""
    return completed, headers, body


def _status(headers: str) -> int:
    statuses = [
        int(line.split()[1])
        for line in headers.splitlines()
        if line.startswith("HTTP/")
    ]
    if not statuses:
        raise AssertionError(f"no status line in\n{headers}")
    return statuses[-1]


def _stamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _events(entries: list[dict], name: str) -> list[dict]:
    return [entry for entry in entries if entry.get("event") == name]


def _wait_for(ready, timeout: float, detail: str):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ready():
            return
        time.sleep(0.1)
    raise AssertionError(detail)


@pytest.fixture(scope="module")
def stack(request):
    with tempfile.TemporaryDirectory(prefix="smartproxy-s0003-") as raw:
        root = Path(raw)
        ca_dir = root / "ca"
        config_dir = root / "config"
        ca_dir.mkdir()
        config_dir.mkdir()
        (config_dir / "bypass.txt").write_text("tasks.smartproxy.test\n")
        _write_decision(config_dir, {"action": "allow"})
        (config_dir / "policy.toml").write_text(
            '[[groups]]\nname = "Everything"\npriority = 1\ndefault = true\n'
        )
        running = Stack(
            ca_dir,
            config_dir,
            _free_port(),
            f"smartproxy-s0003-{os.getpid()}",
        )
        try:
            running.up()
            yield running
        except Exception:
            print(running.logs())
            raise
        finally:
            if request.session.testsfailed:
                print(running.logs())
            running.down()


def _allow(stack: Stack) -> None:
    _write_decision(stack.config_dir, {"action": "allow"})
    stack.clear_jsonl("observations", OBSERVATION_LOG)
    stack.clear_jsonl("origin", ORIGIN_LOG)
    stack.clear_jsonl("decisions", DECISION_LOG)


def _require_observation(entry: dict, url: str) -> None:
    assert {"client_ip", "url", "occurred_at", "bytes"} <= set(entry)
    ipaddress.ip_address(entry["client_ip"])
    assert entry["url"] == url
    occurred = _stamp(entry["occurred_at"])
    assert occurred.tzinfo is not None
    assert abs((datetime.now().astimezone() - occurred).total_seconds()) < 120
    assert isinstance(entry["bytes"], int)
    assert entry["bytes"] > 0


def test_short_allowed_request_is_observed(stack):
    _allow(stack)
    url = "http://origin/index.html?v=abc"
    completed, headers, body = _exchange(stack, url)
    assert completed.returncode == 0, completed.stderr
    assert _status(headers) == 200
    assert body == b"smartproxy-origin-ok /index.html?v=abc"

    observations = stack.jsonl("observations", OBSERVATION_LOG)
    assert observations, stack.logs()
    for entry in observations:
        _require_observation(entry, url)
    assert sum(entry["bytes"] for entry in observations) == len(body)


def test_post_body_is_included_in_the_observation(stack):
    _allow(stack)
    url = "http://origin/posted"
    payload = "abcdef"
    completed, headers, body = _exchange(stack, url, method="POST", data=payload)
    assert completed.returncode == 0, completed.stderr
    assert _status(headers) == 200
    assert stack.jsonl("origin", ORIGIN_LOG)[0]["body_len"] == len(payload)

    observations = stack.jsonl("observations", OBSERVATION_LOG)
    assert observations
    for entry in observations:
        _require_observation(entry, url)
    assert sum(entry["bytes"] for entry in observations) == len(payload) + len(body)


def test_stream_is_reported_before_it_ends(stack):
    _allow(stack)
    url = "http://origin/drip?seconds=4"
    completed, headers, body = _exchange(stack, url, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert _status(headers) == 200
    assert body

    finished = _events(stack.jsonl("origin", ORIGIN_LOG), "finished")[-1]
    observations = stack.jsonl("observations", OBSERVATION_LOG)
    assert len(observations) > 1, observations
    for entry in observations:
        _require_observation(entry, url)
    assert sum(entry["bytes"] for entry in observations) == finished["bytes"]

    ended = _stamp(finished["at"])
    early = [
        entry
        for entry in observations
        if _stamp(entry["received_at"]) < ended - timedelta(milliseconds=300)
    ]
    assert len(early) >= 2, {
        "finished": finished,
        "observations": observations,
    }


def test_idle_flow_is_not_reported_again(stack):
    _allow(stack)
    url = "http://origin/hold?active=2&pause=5"
    box: dict = {}

    def run():
        box["result"] = _exchange(stack, url, timeout=30)

    worker = threading.Thread(target=run)
    worker.start()
    before: list[dict] = []
    try:
        _wait_for(
            lambda: bool(_events(stack.jsonl("origin", ORIGIN_LOG), "idle")),
            15,
            "origin did not go idle",
        )
        # The bytes from the active window are reported on the interval, which
        # can land just after the origin stops writing. Wait that out, then
        # the open connection must stay quiet.
        time.sleep(1.5)
        assert worker.is_alive()
        before = stack.jsonl("observations", OBSERVATION_LOG)
        assert before, stack.logs()
        time.sleep(2.0)
        during = stack.jsonl("observations", OBSERVATION_LOG)
        assert len(during) == len(before), {
            "before": before,
            "during": during,
        }
        assert worker.is_alive()
        worker.join(timeout=20)
        assert not worker.is_alive()
        completed, headers, _body = box["result"]
        assert completed.returncode == 0, completed.stderr
        assert _status(headers) == 200
        after = stack.jsonl("observations", OBSERVATION_LOG)
        assert len(after) == len(before)
        finished = _events(stack.jsonl("origin", ORIGIN_LOG), "finished")[-1]
        assert sum(entry["bytes"] for entry in after) == finished["bytes"]
    finally:
        if worker.is_alive():
            worker.join(timeout=5)


def test_observation_outage_does_not_change_an_allow(stack):
    _allow(stack)
    stack.stop_observations()
    try:
        completed, headers, body = _exchange(stack, "http://origin/still-allowed")
        assert completed.returncode == 0, completed.stderr
        assert _status(headers) == 200
        assert body == b"smartproxy-origin-ok /still-allowed"
    finally:
        stack.start_observations()

    stack.clear_jsonl("observations", OBSERVATION_LOG)
    url = "http://origin/after-outage"
    completed, headers, body = _exchange(stack, url)
    assert completed.returncode == 0, completed.stderr
    assert _status(headers) == 200
    observations = stack.jsonl("observations", OBSERVATION_LOG)
    assert observations
    _require_observation(observations[-1], url)
    assert sum(entry["bytes"] for entry in observations) == len(body)


def test_denied_and_redirected_requests_are_not_observed(stack):
    _write_decision(
        stack.config_dir,
        {"action": "deny", "status": 403, "message": DENY_MESSAGE},
    )
    stack.clear_jsonl("observations", OBSERVATION_LOG)
    stack.clear_jsonl("origin", ORIGIN_LOG)
    completed, headers, body = _exchange(stack, "http://origin/nope")
    assert completed.returncode == 0, completed.stderr
    assert _status(headers) == 403
    assert DENY_MESSAGE.encode() in body
    assert stack.jsonl("origin", ORIGIN_LOG) == []
    assert stack.jsonl("observations", OBSERVATION_LOG) == []

    _write_decision(
        stack.config_dir,
        {"action": "redirect", "status": 302, "location": REDIRECT_LOCATION},
    )
    stack.clear_jsonl("observations", OBSERVATION_LOG)
    stack.clear_jsonl("origin", ORIGIN_LOG)
    completed, headers, _body = _exchange(stack, "http://origin/go")
    assert completed.returncode == 0, completed.stderr
    assert _status(headers) == 302
    assert stack.jsonl("origin", ORIGIN_LOG) == []
    assert stack.jsonl("observations", OBSERVATION_LOG) == []


def test_bypassed_host_is_observed(stack):
    _write_decision(
        stack.config_dir,
        {"action": "deny", "status": 403, "message": "should-not-see"},
    )
    stack.clear_jsonl("observations", OBSERVATION_LOG)
    stack.clear_jsonl("origin", ORIGIN_LOG)
    stack.clear_jsonl("decisions", DECISION_LOG)
    url = "http://tasks.smartproxy.test/tasks/next"
    completed, headers, body = _exchange(stack, url)
    assert completed.returncode == 0, completed.stderr
    assert _status(headers) == 200
    assert body == b"smartproxy-origin-ok /tasks/next"
    assert stack.jsonl("decisions", DECISION_LOG) == []

    observations = stack.jsonl("observations", OBSERVATION_LOG)
    assert observations
    for entry in observations:
        _require_observation(entry, url)
    assert sum(entry["bytes"] for entry in observations) == len(body)
