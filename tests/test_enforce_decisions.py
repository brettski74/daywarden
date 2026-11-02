"""S000.2: the proxy enforces allow, 403, and 302, and fails closed."""

import ipaddress
import json
import os
import socket
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DECISION_LOG = "/tmp/decisions.jsonl"
ORIGIN_LOG = "/tmp/origin.jsonl"
DENY_MESSAGE = "Time is up for today."
UNAVAILABLE = "The authorization service is unavailable."
UNRECOGNIZED = "The authorization service returned an unrecognized decision."
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
    if isinstance(document, str):
        text = document
    else:
        text = json.dumps(document)
    temporary.write_text(text)
    temporary.replace(target)


class Stack:
    def __init__(self, ca_dir: Path, config_dir: Path, port: int, project: str):
        self.ca_dir = ca_dir
        self.config_dir = config_dir
        self.port = port
        self.project = project
        self.env = os.environ.copy()
        self.env["PROXY_PORT"] = str(port)
        self.env["POLICY_PORT"] = str(_free_port())
        self.env["PARENT_PASSWORD"] = ""
        self.env["CA_VOLUME_PATH"] = str(ca_dir)
        self.env["DAYWARDEN_CONFIG_DIR"] = str(config_dir)
        self.env["POLICY_FILE"] = "/etc/daywarden/policy.toml"
        self.cmd = [
            "docker",
            "compose",
            "-p",
            project,
            "-f",
            "docker-compose.yml",
            "-f",
            "tests/recording-origin.compose.yml",
            "-f",
            "tests/decision-stub.compose.yml",
        ]

    @property
    def proxy_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def cert_pem(self) -> Path:
        return self.ca_dir / "mitmproxy-ca-cert.pem"

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

    def stop_decisions(self):
        self.run(["stop", "--timeout", "5", "decisions"], timeout=30)

    def start_decisions(self):
        self.run(["up", "-d", "--wait", "--wait-timeout", "30", "--no-deps", "decisions"])


def _curl(args, *, timeout=20):
    return subprocess.run(
        ["curl", "-sS", "--http1.1", "--max-time", str(timeout), *args],
        capture_output=True,
        timeout=timeout + 5,
    )


def _exchange(proxy: Stack, url: str, *, method: str = "GET", data: str | None = None, tls: bool = False):
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
    if tls:
        command += ["--cacert", str(proxy.cert_pem), "-v"]
    if data is not None:
        command += ["--data", data]
    command.append(url)
    completed = _curl(command)
    headers = header_path.read_text() if header_path.exists() else ""
    body = body_path.read_bytes() if body_path.exists() else b""
    return completed, headers, body


def _status(headers: str) -> int:
    """Return the status of the last HTTP response in a curl header dump.

    An intercepted HTTPS request dumps the CONNECT acknowledgement first and
    the decrypted response after it.
    """
    statuses = [
        int(line.split()[1])
        for line in headers.splitlines()
        if line.startswith("HTTP/")
    ]
    if not statuses:
        raise AssertionError(f"no status line in\n{headers}")
    return statuses[-1]


def _header(headers: str, name: str) -> str:
    prefix = name.lower() + ":"
    for line in headers.splitlines():
        if line.lower().startswith(prefix):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"missing {name} in\n{headers}")


def _paths(entries: list[dict]) -> list[str]:
    return [entry["path"] for entry in entries]


@pytest.fixture(scope="module")
def stack(request):
    with tempfile.TemporaryDirectory(prefix="daywarden-s0002-") as raw:
        root = Path(raw)
        ca_dir = root / "ca"
        config_dir = root / "config"
        ca_dir.mkdir()
        config_dir.mkdir()
        (config_dir / "bypass.txt").write_text(
            "# task site and classroom\n*.google.test\ntasks.daywarden.test\n"
        )
        _write_decision(config_dir, {"action": "allow"})
        (config_dir / "policy.toml").write_text(
            '[[groups]]\nname = "Everything"\npriority = 1\ndefault = true\n'
        )
        running = Stack(
            ca_dir,
            config_dir,
            _free_port(),
            f"daywarden-s0002-{os.getpid()}",
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


def test_allow_returns_the_origin_response(stack):
    _write_decision(stack.config_dir, {"action": "allow"})
    stack.clear_jsonl("decisions", DECISION_LOG)
    stack.clear_jsonl("origin", ORIGIN_LOG)
    url = "http://origin/index.html?v=abc"
    completed, headers, body = _exchange(stack, url)
    assert completed.returncode == 0, completed.stderr
    assert _status(headers) == 200
    assert body == b"daywarden-origin-ok /index.html?v=abc"
    assert _paths(stack.jsonl("origin", ORIGIN_LOG)) == ["/index.html?v=abc"]

    logged = stack.jsonl("decisions", DECISION_LOG)[-1]
    assert logged["client"] is None
    assert logged["decision"] == {"action": "allow"}
    entry = logged["request"]
    assert set(entry) == {"client_ip", "method", "url", "occurred_at", "flow_id"}
    assert isinstance(entry["flow_id"], str) and entry["flow_id"]
    ipaddress.ip_address(entry["client_ip"])
    assert entry["method"] == "GET"
    assert entry["url"] == url
    occurred = datetime.fromisoformat(entry["occurred_at"])
    assert occurred.tzinfo is not None
    assert abs((datetime.now().astimezone() - occurred).total_seconds()) < 120


def test_deny_returns_403_and_the_origin_sees_nothing(stack):
    _write_decision(
        stack.config_dir,
        {"action": "deny", "status": 403, "message": DENY_MESSAGE},
    )
    stack.clear_jsonl("decisions", DECISION_LOG)
    stack.clear_jsonl("origin", ORIGIN_LOG)
    completed, headers, body = _exchange(
        stack,
        "http://origin/posted",
        method="POST",
        data="not-for-origin",
    )
    assert completed.returncode == 0, completed.stderr
    assert _status(headers) == 403
    assert _header(headers, "Content-Type").startswith("text/html")
    assert DENY_MESSAGE.encode() in body
    assert _paths(stack.jsonl("origin", ORIGIN_LOG)) == []

    entry = stack.jsonl("decisions", DECISION_LOG)[-1]["request"]
    assert entry["method"] == "POST"
    assert entry["url"] == "http://origin/posted"
    assert "body" not in entry


def test_redirect_returns_302_and_the_origin_sees_nothing(stack):
    _write_decision(
        stack.config_dir,
        {"action": "redirect", "status": 302, "location": REDIRECT_LOCATION},
    )
    stack.clear_jsonl("origin", ORIGIN_LOG)
    completed, headers, _body = _exchange(stack, "http://origin/go")
    assert completed.returncode == 0, completed.stderr
    assert _status(headers) == 302
    assert _header(headers, "Location") == REDIRECT_LOCATION
    assert _paths(stack.jsonl("origin", ORIGIN_LOG)) == []


def test_bypass_host_skips_the_decision_api(stack):
    _write_decision(
        stack.config_dir,
        {"action": "deny", "status": 403, "message": "should-not-see"},
    )
    stack.clear_jsonl("decisions", DECISION_LOG)
    stack.clear_jsonl("origin", ORIGIN_LOG)
    completed, headers, body = _exchange(stack, "http://Class.Google.Test/index.html")
    assert completed.returncode == 0, completed.stderr
    assert _status(headers) == 200
    assert b"daywarden-origin-ok /index.html" in body
    assert stack.jsonl("decisions", DECISION_LOG) == []
    assert stack.jsonl("origin", ORIGIN_LOG)[0]["host"].lower().startswith("class.google.test")

    refused, refused_headers, refused_body = _exchange(stack, "http://origin/blocked")
    assert refused.returncode == 0, refused.stderr
    assert _status(refused_headers) == 403
    assert b"should-not-see" in refused_body


def test_unrecognized_decision_is_forbidden(stack):
    _write_decision(
        stack.config_dir,
        {"action": "redirect", "status": 302, "location": "/tasks/next"},
    )
    stack.clear_jsonl("origin", ORIGIN_LOG)
    completed, headers, body = _exchange(stack, "http://origin/odd")
    assert completed.returncode == 0, completed.stderr
    assert _status(headers) == 403
    assert UNRECOGNIZED.encode() in body
    assert _paths(stack.jsonl("origin", ORIGIN_LOG)) == []


def test_https_redirect_is_applied_after_connect(stack):
    _write_decision(
        stack.config_dir,
        {"action": "redirect", "status": 302, "location": REDIRECT_LOCATION},
    )
    stack.clear_jsonl("origin", ORIGIN_LOG)
    completed, headers, _body = _exchange(stack, "https://origin/secret", tls=True)
    assert completed.returncode == 0, completed.stderr.decode()
    assert headers.startswith("HTTP/1.1 200 Connection established")
    assert _status(headers) == 302
    assert _header(headers, "Location") == REDIRECT_LOCATION
    assert _paths(stack.jsonl("origin", ORIGIN_LOG)) == []


def test_decision_api_down_fails_closed_except_for_the_bypass_list(stack):
    stack.stop_decisions()
    try:
        stack.clear_jsonl("origin", ORIGIN_LOG)
        allowed, allowed_headers, allowed_body = _exchange(
            stack, "http://tasks.daywarden.test/tasks/next"
        )
        assert allowed.returncode == 0, allowed.stderr
        assert _status(allowed_headers) == 200
        assert b"daywarden-origin-ok /tasks/next" in allowed_body

        refused, refused_headers, refused_body = _exchange(stack, "http://notgoogle.test/secret")
        assert refused.returncode == 0, refused.stderr
        assert _status(refused_headers) == 403
        assert UNAVAILABLE.encode() in refused_body
        assert "/secret" not in _paths(stack.jsonl("origin", ORIGIN_LOG))
    finally:
        stack.start_decisions()
