"""S000.1: mitmproxy starts from Compose, keeps one CA, and proxies."""

import hashlib
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "mitmproxy/mitmproxy:12.2.3"
CA_TARGET = "/home/mitmproxy/.mitmproxy"
ORIGIN_BODY = b"daywarden-origin-ok"
ALLOW_EVERYTHING = """\
entry: household
rule_sets:
  household:
    - condition: always
      when_true: { action: allow }
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


def _stack_dirs(root: Path) -> tuple[Path, Path]:
    ca_dir = root / "ca"
    config_dir = root / "config"
    ca_dir.mkdir()
    config_dir.mkdir()
    (config_dir / "policy.yaml").write_text(ALLOW_EVERYTHING, encoding="utf-8")
    (config_dir / "bypass.txt").write_text("", encoding="utf-8")
    return ca_dir, config_dir


class ProxyStack:
    def __init__(self, ca_dir: Path, config_dir: Path, port: int, project: str, *, with_origin: bool):
        self.ca_dir = ca_dir
        self.port = port
        self.project = project
        self.env = os.environ.copy()
        self.env["PROXY_PORT"] = str(port)
        self.env["POLICY_PORT"] = str(_free_port())
        self.env["PARENT_PASSWORD"] = ""
        self.env["CA_VOLUME_PATH"] = str(ca_dir)
        self.env["DAYWARDEN_CONFIG_DIR"] = str(config_dir)
        self.env["POLICY_FILE"] = "/etc/daywarden/policy.yaml"
        self.cmd = ["docker", "compose", "-p", project, "-f", "docker-compose.yml"]
        if with_origin:
            self.cmd += ["-f", "tests/origin.compose.yml"]

    @property
    def proxy_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def cert_pem(self) -> Path:
        return self.ca_dir / "mitmproxy-ca-cert.pem"

    @property
    def key_pem(self) -> Path:
        return self.ca_dir / "mitmproxy-ca.pem"

    def run(self, args, *, check=True, timeout=120):
        return _run(self.cmd + args, env=self.env, timeout=timeout, check=check)

    def up(self):
        self.run(["up", "-d", "--wait", "--wait-timeout", "60"])

    def down(self):
        self.run(["down", "-v", "--remove-orphans", "--timeout", "5"], check=False, timeout=60)

    def logs(self) -> str:
        completed = self.run(["logs", "--no-color"], check=False, timeout=30)
        return completed.stdout + completed.stderr


def _chown_ca(ca_dir: Path, owner: str):
    _run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{ca_dir}:/ca",
            "--entrypoint",
            "chown",
            IMAGE,
            "-R",
            owner,
            "/ca",
        ],
        env=os.environ.copy(),
        timeout=60,
    )


def _curl(args, *, timeout=20):
    return subprocess.run(
        ["curl", "-sS", "--http1.1", "--max-time", str(timeout), *args],
        capture_output=True,
        timeout=timeout + 5,
    )


@pytest.fixture(scope="module")
def proxy(request):
    with tempfile.TemporaryDirectory(prefix="daywarden-ca-") as raw:
        ca_dir, config_dir = _stack_dirs(Path(raw))
        stack = ProxyStack(
            ca_dir,
            config_dir,
            _free_port(),
            f"daywarden-s0001-{os.getpid()}",
            with_origin=True,
        )
        try:
            stack.up()
            yield stack
        except Exception:
            print(stack.logs())
            raise
        finally:
            if request.session.testsfailed:
                print(stack.logs())
            stack.down()


def test_listen_port_and_ca_path_come_from_configuration(tmp_path):
    ca_dir = tmp_path / "household-ca"
    ca_dir.mkdir()
    env = os.environ.copy()
    env["PROXY_PORT"] = "17431"
    env["CA_VOLUME_PATH"] = str(ca_dir)

    completed = _run(
        ["docker", "compose", "-p", "daywarden-config", "config", "--format", "json"],
        env=env,
        timeout=30,
    )
    config = json.loads(completed.stdout)
    service = config["services"]["proxy"]

    published = [str(item["published"]) for item in service["ports"]]
    assert published == ["17431"]

    ca_mounts = [
        item["source"]
        for item in service["volumes"]
        if item.get("target") == CA_TARGET
    ]
    assert ca_mounts == [str(ca_dir)]

    command = service["command"]
    assert command[0] == "mitmdump"
    assert "regular" in command


def test_every_service_has_mounts_docker_can_create(tmp_path):
    ca_dir = tmp_path / "household-ca"
    data_dir = tmp_path / "household-data"
    ca_dir.mkdir()
    data_dir.mkdir()
    env = os.environ.copy()
    env["PROXY_PORT"] = "17432"
    env["CA_VOLUME_PATH"] = str(ca_dir)
    env["DAYWARDEN_DATA_DIR"] = str(data_dir)

    completed = _run(
        ["docker", "compose", "-p", "daywarden-config", "config", "--format", "json"],
        env=env,
        timeout=30,
    )
    config = json.loads(completed.stdout)

    for name, service in config["services"].items():
        mounts = service.get("volumes", [])
        targets = [item["target"] for item in mounts]
        assert len(targets) == len(set(targets)), f"{name} mounts a target twice: {targets}"
        read_only = [item["target"] for item in mounts if item.get("read_only")]
        for parent in read_only:
            nested = [t for t in targets if t.startswith(parent.rstrip("/") + "/")]
            assert not nested, f"{name} nests {nested} under read-only {parent}"

    decisions = config["services"]["decisions"]
    data_targets = [
        item["target"]
        for item in decisions["volumes"]
        if item.get("source") == str(data_dir)
    ]
    assert data_targets == [decisions["environment"]["DAYWARDEN_DATA_DIR"]]


def test_http_request_reaches_the_origin(proxy):
    deadline = time.time() + 20
    last = None
    while time.time() < deadline:
        last = _curl(
            ["--proxy", proxy.proxy_url, "http://origin/index.html"]
        )
        if last.returncode == 0 and ORIGIN_BODY in last.stdout:
            return
        time.sleep(0.5)
    raise AssertionError(
        f"origin body did not come back through the proxy\n"
        f"exit {last.returncode}\nstdout {last.stdout!r}\nstderr {last.stderr!r}\n"
        f"{proxy.logs()}"
    )


def test_https_fails_without_the_ca_and_succeeds_with_it(proxy):
    deadline = time.time() + 40
    untrusted = None
    while time.time() < deadline:
        untrusted = _curl(["--proxy", proxy.proxy_url, "https://example.com/"])
        if untrusted.returncode != 0 and b"certificate" in untrusted.stderr.lower():
            break
        time.sleep(0.5)
    else:
        raise AssertionError(
            "expected a certificate error without the CA\n"
            f"exit {untrusted.returncode}\nstdout {untrusted.stdout!r}\n"
            f"stderr {untrusted.stderr!r}\n{proxy.logs()}"
        )

    trusted = None
    while time.time() < deadline:
        trusted = _curl(
            [
                "--proxy",
                proxy.proxy_url,
                "--cacert",
                str(proxy.cert_pem),
                "https://example.com/",
            ]
        )
        if trusted.returncode == 0 and b"Example Domain" in trusted.stdout:
            return
        time.sleep(0.5)
    raise AssertionError(
        "HTTPS through the proxy did not succeed with the CA\n"
        f"exit {trusted.returncode}\nstdout {trusted.stdout!r}\n"
        f"stderr {trusted.stderr!r}\n{proxy.logs()}"
    )


def test_ca_is_a_pem_certificate_without_the_key(proxy):
    pem = proxy.cert_pem.read_text()
    assert "-----BEGIN CERTIFICATE-----" in pem
    assert "PRIVATE KEY" not in pem
    assert proxy.key_pem.is_file()
    assert "PRIVATE KEY" in proxy.key_pem.read_text()

    parsed = subprocess.run(
        ["openssl", "x509", "-in", str(proxy.cert_pem), "-noout", "-subject"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert parsed.returncode == 0, parsed.stderr
    assert os.access(proxy.cert_pem, os.R_OK)


def test_new_container_reuses_the_same_ca(proxy):
    before = {
        "cert": hashlib.sha256(proxy.cert_pem.read_bytes()).hexdigest(),
        "key": hashlib.sha256(proxy.key_pem.read_bytes()).hexdigest(),
    }
    proxy.run(["up", "-d", "--wait", "--wait-timeout", "60", "--force-recreate", "--no-deps", "proxy"])
    after = {
        "cert": hashlib.sha256(proxy.cert_pem.read_bytes()).hexdigest(),
        "key": hashlib.sha256(proxy.key_pem.read_bytes()).hexdigest(),
    }
    assert after == before


def test_ca_volume_owned_by_a_group_the_image_does_not_know():
    """The published image refuses a CA directory whose group is missing."""
    with tempfile.TemporaryDirectory(prefix="daywarden-ca-foreign-") as raw:
        ca_dir, config_dir = _stack_dirs(Path(raw))
        _chown_ca(ca_dir, "1001:1001")
        stack = ProxyStack(
            ca_dir,
            config_dir,
            _free_port(),
            f"daywarden-s0001-foreign-{os.getpid()}",
            with_origin=False,
        )
        try:
            stack.up()
            completed = _run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-v",
                    f"{ca_dir}:/ca:ro",
                    "--entrypoint",
                    "cat",
                    IMAGE,
                    "/ca/mitmproxy-ca-cert.pem",
                ],
                env=os.environ.copy(),
                timeout=30,
            )
            assert "-----BEGIN CERTIFICATE-----" in completed.stdout
            assert "PRIVATE KEY" not in completed.stdout
        except Exception:
            print(stack.logs())
            raise
        finally:
            stack.down()
            _chown_ca(ca_dir, f"{os.getuid()}:{os.getgid()}")
