"""S016: dw check, dw reload, and dw restart against a running stack.

bin/dw runs on this repository with its own Compose project name, so it
never touches a household stack running from the same directory. systemctl
is replaced by one that cannot reach a user manager, so dw never starts the
household's user service.
"""

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="needs docker")

POLICY = """\
entry: household
timezone: Australia/Sydney
client_groups:
  younger:
    addresses: ["192.0.2.40"]
site_groups:
  reading:
    priority: 10
    patterns: ["reading.example"]
rule_sets:
  household:
    - condition: site_group
      group: reading
      when_true: { action: deny, message: "No reading." }
"""

DECIDE = """
import json, urllib.request
request = urllib.request.Request(
    "http://127.0.0.1:8090/v1/decisions",
    data=json.dumps({"client_ip": "192.0.2.40", "method": "GET", "url": "https://reading.example/"}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
print(urllib.request.urlopen(request, timeout=5).read().decode())
"""

# Run in the proxy container: the path a child's request through the proxy would take.
FROM_PROXY = """
import sys, urllib.error, urllib.request
for url in sys.argv[1:]:
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=b"", method="POST"), timeout=5)
        print(url, 200)
    except urllib.error.HTTPError as error:
        print(url, error.code)
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Daywarden:
    def __init__(self, directory: Path):
        self.config = directory / "config"
        self.config.mkdir()
        (self.config / "policy.yaml").write_text(POLICY, encoding="utf-8")
        (self.config / "bypass.txt").write_text("", encoding="utf-8")
        (directory / "ca").mkdir()
        fakes = directory / "fakes"
        fakes.mkdir()
        systemctl = fakes / "systemctl"
        systemctl.write_text("#!/bin/sh\necho 'Failed to connect to bus' >&2\nexit 1\n", encoding="utf-8")
        systemctl.chmod(0o755)
        self.project = f"dw-reload-{os.getpid()}"
        self.env = {
            **os.environ,
            "PATH": f"{fakes}:{os.environ['PATH']}",
            "COMPOSE_PROJECT_NAME": self.project,
            "DAYWARDEN_CONFIG_DIR": str(self.config),
            "CA_VOLUME_PATH": str(directory / "ca"),
            "PROXY_PORT": str(_free_port()),
            "POLICY_PORT": str(_free_port()),
            "PARENT_NAMES": "localhost",
            "OBSERVATION_INTERVAL": "60",
        }

    def dw(self, *args: str, env: dict | None = None, timeout: int = 400) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(ROOT / "bin" / "dw"), *args],
            env={**self.env, **(env or {})},
            text=True,
            capture_output=True,
            timeout=timeout,
        )

    def compose(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        done = subprocess.run(
            ["docker", "compose", "--project-directory", str(ROOT), *args],
            env=self.env,
            text=True,
            capture_output=True,
            timeout=120,
        )
        if check:
            assert done.returncode == 0, done.stderr
        return done

    def containers(self) -> dict[str, tuple[str, str]]:
        """Each service's container id and the time it started."""
        found = {}
        for service in ("decisions", "observations", "proxy"):
            ident = self.compose("ps", "-q", service).stdout.strip()
            started = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.StartedAt}}", ident],
                text=True, capture_output=True, check=True,
            ).stdout.strip()
            found[service] = (ident, started)
        return found

    def decide(self) -> dict:
        return json.loads(self.compose("exec", "-T", "decisions", "python", "-c", DECIDE).stdout)

    def edit(self, old: str, new: str) -> None:
        path = self.config / "policy.yaml"
        path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


@pytest.fixture(scope="module")
def daywarden():
    with tempfile.TemporaryDirectory(prefix="daywarden-reload-") as raw:
        running = Daywarden(Path(raw))
        named = json.loads(running.compose("config", "--format", "json").stdout)["name"]
        assert named == running.project, "dw would act on another Compose project"
        try:
            done = running.dw("up")
            assert done.returncode == 0, done.stdout + done.stderr
            yield running
        finally:
            running.compose("down", "-v", "--remove-orphans", "--timeout", "5", check=False)


def test_check_on_a_running_stack_prints_the_summary(daywarden):
    done = daywarden.dw("check")
    assert done.returncode == 0, done.stderr
    assert "entry household" in done.stdout
    assert "client group younger: 192.0.2.40" in done.stdout


def test_reload_applies_the_policy_without_restarting_a_container(daywarden):
    assert daywarden.decide()["message"] == "No reading."
    before = daywarden.containers()
    daywarden.edit('when_true: { action: deny, message: "No reading." }', "when_true: { action: allow }")
    done = daywarden.dw("reload")
    assert done.returncode == 0, done.stderr
    assert "site group reading: priority 10, 1 patterns" in done.stdout
    assert "The decisions and observations services are using the reloaded policy." in done.stdout
    assert "dw restart" not in done.stdout
    assert daywarden.decide() == {"action": "allow"}
    assert daywarden.containers() == before


def test_a_broken_policy_is_refused_and_the_old_one_stays_in_force(daywarden):
    good = (daywarden.config / "policy.yaml").read_text(encoding="utf-8")
    decided = daywarden.decide()
    try:
        daywarden.edit("timezone:", "timezon:")
        daywarden.edit("priority: 10", "priority: ten")
        done = daywarden.dw("reload")
        assert done.returncode == 1
        lines = done.stderr.splitlines()
        assert lines[0] == "dw: the policy has 2 errors. Nothing was reloaded."
        assert lines[1].startswith(f"{daywarden.config}/policy.yaml:2:1: unknown setting timezon")
        assert lines[2].startswith(f"{daywarden.config}/policy.yaml:8:")
        assert daywarden.decide() == decided
        checked = daywarden.dw("check")
        assert checked.returncode == 1
        assert checked.stderr.splitlines()[1:] == lines[1:]
    finally:
        (daywarden.config / "policy.yaml").write_text(good, encoding="utf-8")


def test_no_request_from_the_proxy_can_reload_either_service(daywarden):
    done = daywarden.compose(
        "exec", "-T", "proxy", "python3", "-c", FROM_PROXY,
        "http://decisions:8090/v1/reload", "http://observations:8091/v1/reload",
    )
    assert done.stdout.split() == ["http://decisions:8090/v1/reload", "404", "http://observations:8091/v1/reload", "404"]


def test_reload_names_the_services_a_changed_env_would_change(daywarden):
    before = daywarden.containers()
    done = daywarden.dw("reload", env={"OBSERVATION_INTERVAL": "30"})
    assert done.returncode == 0, done.stderr
    assert "Still running with the old settings: proxy. Run dw restart to apply the changes." in done.stdout
    assert daywarden.containers() == before


def test_restart_replaces_every_container_and_is_no_slower_than_down_and_up(daywarden):
    before = daywarden.containers()
    started = time.monotonic()
    done = daywarden.dw("restart")
    restart_seconds = time.monotonic() - started
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.strip().endswith("daywarden restarted.")
    after = daywarden.containers()
    assert all(after[service][0] != before[service][0] for service in before)
    assert daywarden.decide() == {"action": "allow"}

    started = time.monotonic()
    assert daywarden.dw("down").returncode == 0
    done = daywarden.dw("up")
    down_up_seconds = time.monotonic() - started
    assert done.returncode == 0, done.stdout + done.stderr
    print(f"dw restart took {restart_seconds:.1f}s; dw down and dw up took {down_up_seconds:.1f}s")
    assert restart_seconds <= down_up_seconds + 2
