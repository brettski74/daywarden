"""S008.6: a forwarded stream stops once it has used the grace.

A new request at the limit is still denied by the access rules. Stopping the
observation service, and any answer that is not the cut instruction, leaves
the transfer running.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OBSERVATION_LOG = "/tmp/observations.jsonl"
ORIGIN_LOG = "/tmp/origin.jsonl"

POLICY = """\
entry: household
bucket_length: 5m
time_grace: 1h
volume_grace: 1M

site_groups:
  drip:
    priority: 10
    patterns:
      - "http://origin/drip*"
      - "http://origin:80/drip*"

quotas:
  pipe:
    bytes: 2000b
    volume_grace: 0b
    time: 2h
    time_grace: 1h
    ruleset: drip_meter

rule_sets:
  drip_meter:
    - condition: site_group
      group: drip
      when_true: { action: continue }
      when_false: { action: deny, message: "Not a drip." }
  household:
    - condition: site_group
      group: drip
      when_true: { action: evaluate, ruleset: drip_access }
    - condition: always
      when_true: { action: allow }
  drip_access:
    - condition: volume_remaining
      quota: pipe
      when_true: { action: allow }
      when_false: { action: deny, message: "That's enough video for today." }
"""


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


class Stack:
    def __init__(self, ca_dir: Path, config_dir: Path, port: int, project: str):
        self.ca_dir = ca_dir
        self.config_dir = config_dir
        self.port = port
        self.project = project
        self.env = os.environ.copy()
        self.env["PROXY_PORT"] = str(port)
        self.env["POLICY_PORT"] = str(_free_port())
        self.env["PROXY_CONFIG_PORT"] = str(_free_port())
        self.env["PARENT_PASSWORD"] = ""
        self.env["CA_VOLUME_PATH"] = str(ca_dir)
        self.env["DAYWARDEN_CONFIG_DIR"] = str(config_dir)
        self.env["POLICY_FILE"] = "/etc/daywarden/policy.yaml"
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
        self.run(["up", "-d", "--wait", "--wait-timeout", "120"], timeout=300)

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


def _exchange(proxy: Stack, url: str, *, timeout: int = 20):
    header_path = proxy.config_dir / "headers.txt"
    body_path = proxy.config_dir / "body.bin"
    header_path.unlink(missing_ok=True)
    body_path.unlink(missing_ok=True)
    completed = _curl(
        [
            "--proxy",
            proxy.proxy_url,
            "-D",
            str(header_path),
            "-o",
            str(body_path),
            url,
        ],
        timeout=timeout,
    )
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


@pytest.fixture(scope="module")
def stack(request):
    with tempfile.TemporaryDirectory(prefix="daywarden-s0086-") as raw:
        root = Path(raw)
        ca_dir = root / "ca"
        config_dir = root / "config"
        ca_dir.mkdir()
        config_dir.mkdir()
        policy_path = config_dir / "policy.yaml"
        policy_path.write_text(POLICY, encoding="utf-8")
        from policy.hierarchy import load

        loaded = load(policy_path)
        assert loaded is not None and loaded.quota("pipe") is not None
        (config_dir / "bypass.txt").write_text("")
        running = Stack(ca_dir, config_dir, _free_port(), f"daywarden-s0086-{os.getpid()}")
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


def test_a_forwarded_stream_is_cut_at_the_limit_and_a_new_request_is_denied(stack):
    stack.stop_observations()
    try:
        completed, headers, body = _exchange(stack, "http://origin/still-allowed")
        assert completed.returncode == 0, completed.stderr
        assert _status(headers) == 200
        assert body == b"daywarden-origin-ok /still-allowed"
    finally:
        stack.start_observations()

    stack.clear_jsonl("observations", OBSERVATION_LOG)
    stack.clear_jsonl("origin", ORIGIN_LOG)
    short = "http://origin/drip?seconds=0.3"
    completed, headers, body = _exchange(stack, short, timeout=20)
    assert completed.returncode == 0, (completed.stderr, stack.logs())
    assert _status(headers) == 200
    assert body
    assert b"cut origin" not in stack.logs().encode()

    stack.clear_jsonl("origin", ORIGIN_LOG)
    long = "http://origin/drip?seconds=8"
    completed, headers, body = _exchange(stack, long, timeout=20)
    assert len(body) < 6500, (len(body), completed.returncode, stack.logs())
    assert body
    assert b"cut origin" in stack.logs().encode()
    observations = [
        entry
        for entry in stack.jsonl("observations", OBSERVATION_LOG)
        if entry.get("url") == long
    ]
    assert observations, stack.logs()
    assert sum(entry["bytes"] for entry in observations) < 8000

    completed, headers, body = _exchange(stack, "http://origin/drip?seconds=1")
    assert completed.returncode == 0, completed.stderr
    assert _status(headers) == 403
    assert b"enough video for today." in body

    completed, headers, body = _exchange(stack, "http://origin/after-the-cut")
    assert completed.returncode == 0, completed.stderr
    assert _status(headers) == 200
    assert body == b"daywarden-origin-ok /after-the-cut"
