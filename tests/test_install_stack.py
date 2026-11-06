"""S014: a package built by make dist installs into a fresh HOME and runs with Docker.

The installed stack uses its own Compose project name and ports, so it does
not collide with a development stack on the same machine. systemctl and
loginctl are stand-ins that report no user manager, so the real user
manager is never touched.
"""

import http.client
import os
import shutil
import signal
import socket
import ssl
import subprocess
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import pytest

import hostfakes  # noqa: F401  puts the repository on the path
from conftest import write_alphabet, write_wav
from deploy.build import POLICY_IMAGE, PROXY_IMAGE, build

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="needs docker")

FAKE_SYSTEMCTL = """#!/usr/bin/env bash
if [ "$1" = is-enabled ]; then echo enabled; exit 0; fi
echo "Failed to connect to bus: No medium found" >&2
exit 1
"""
FAKE_LOGINCTL = """#!/usr/bin/env bash
echo "loginctl is not used by this test" >&2
exit 1
"""
PASSWORD = "correct horse battery"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Installed:
    def __init__(self, base: Path, package: Path, project: str):
        self.package = package
        self.project = project
        self.home = base / "home"
        (self.home / "bin").mkdir(parents=True)
        self.root = self.home / "daywarden"
        fakes = base / "fakes"
        fakes.mkdir()
        for name, text in (("systemctl", FAKE_SYSTEMCTL), ("loginctl", FAKE_LOGINCTL)):
            (fakes / name).write_text(text, encoding="utf-8")
            (fakes / name).chmod(0o755)
        self.proxy_port, self.policy_port = _free_port(), _free_port()
        env = {key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "DAYWARDEN_DATA_DIR", "VIRTUAL_ENV")}
        real_home = Path(os.environ["HOME"])
        env.update(
            HOME=str(self.home),
            PATH=f"{self.home / 'bin'}:{fakes}:{env['PATH']}",
            COMPOSE_PROJECT_NAME=project,
            PROXY_PORT=str(self.proxy_port),
            POLICY_PORT=str(self.policy_port),
            PIP_CACHE_DIR=str(real_home / ".cache" / "pip"),
        )
        if (real_home / ".docker").is_dir():
            env["DOCKER_CONFIG"] = str(real_home / ".docker")
        self.env = env
        self.elsewhere = base / "elsewhere"
        self.elsewhere.mkdir()

    def run(self, *command, input="", timeout=600, check=True):
        done = subprocess.run(
            [str(part) for part in command],
            cwd=self.elsewhere,
            env=self.env,
            input=input,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        if check and done.returncode != 0:
            raise AssertionError(f"{command} exited {done.returncode}\nstdout:\n{done.stdout}\nstderr:\n{done.stderr}")
        return done

    def command(self, name, *args, **kwargs):
        return self.run(self.home / "bin" / name, *args, **kwargs)

    def containers(self) -> dict[str, str]:
        listing = self.run("docker", "compose", "-p", self.project, "ps", "-a", "--format", "{{.Service}} {{.ID}}").stdout
        return dict(line.split() for line in listing.splitlines())

    def inspect(self, container: str, template: str) -> str:
        return self.run("docker", "inspect", "--format", template, container).stdout.strip()

    @property
    def ca(self) -> Path:
        return self.root / "ca" / "mitmproxy-ca-cert.pem"

    def policy_page(self, method="GET", body=None):
        """Open /usage over HTTPS, trusting only the installed CA. Retry while the parent listener starts."""
        context = ssl.create_default_context(cafile=str(self.ca))
        deadline = time.monotonic() + 60
        while True:
            try:
                connection = http.client.HTTPSConnection("localhost", self.policy_port, context=context, timeout=5)
                headers = {"Content-Type": "application/x-www-form-urlencoded"} if body else {}
                connection.request(method, "/usage", body=body, headers=headers)
                response = connection.getresponse()
                return response.status, dict(response.getheaders()), response.read().decode()
            except (OSError, ssl.SSLError):
                if time.monotonic() > deadline:
                    raise
                time.sleep(1)

    def sign_in(self) -> bool:
        body = urllib.parse.urlencode({"username": "ada", "password": PASSWORD})
        _status, headers, _page = self.policy_page("POST", body)
        return "parent_session=" in headers.get("set-cookie", "")


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    base = tmp_path_factory.mktemp("installed")
    version = datetime.now().strftime("%Y%m%d-%H%M%S")
    tarball = build(base / "dist", version, compresslevel=1)
    with tarfile.open(tarball) as archive:
        archive.extractall(base / "unpacked", filter="tar")
    package = base / "unpacked" / f"daywarden-{version}"
    machine = Installed(base, package, f"dwinstall{os.getpid()}")
    try:
        yield machine
    finally:
        subprocess.run(
            ["docker", "compose", "-p", machine.project, "--project-directory", str(machine.root), "down", "-v", "--timeout", "5"],
            env=machine.env,
            capture_output=True,
            timeout=120,
        )
        subprocess.run(["docker", "rmi", f"{POLICY_IMAGE}:{version}", f"{PROXY_IMAGE}:{version}"], capture_output=True, timeout=120)


def test_make_dist_builds_a_package_that_installs_and_runs(installed):
    done = installed.run(installed.package / "install.sh")
    assert f"daywarden {installed.package.name.removeprefix('daywarden-')} is installed in ~/daywarden." in done.stdout
    assert installed.containers() == {}

    # The household policy's spelling task needs ten revision words and the
    # alphabet, as cut-clips would write them.
    spelling = installed.root / "data" / "spelling"
    for word in ("ant", "bee", "cat", "dog", "eel", "fox", "gnu", "hen", "jay", "yak"):
        write_wav(spelling / "revision" / f"{word}.wav")
    write_alphabet(spelling / "alphabet")

    installed.command("dw", "up")
    status = installed.command("dw", "status")
    assert status.stdout.splitlines()[-3:] == ["  decisions     healthy", "  observations  healthy", "  proxy         healthy"]

    proxy = urllib.request.build_opener(urllib.request.ProxyHandler({"http": f"http://127.0.0.1:{installed.proxy_port}"}))
    with pytest.raises(urllib.error.HTTPError) as denied:
        proxy.open("http://daywarden-install-test.invalid/", timeout=10)
    assert denied.value.code == 403

    _status, _headers, page = installed.policy_page()
    assert "closed until a parent account is added" in page
    saved = installed.command("add-parent", "ada", input=PASSWORD + "\n")
    assert "parent account ada is saved" in saved.stdout
    assert "Enter your username and password." in installed.policy_page()[2]
    assert installed.sign_in()

    assert "--client" in installed.command("rm-attempts", "--help").stdout
    if shutil.which("python3"):
        assert "--out DIR" in installed.command("cut-clips", "--help").stdout


def test_a_crashed_container_comes_back_and_a_stopped_one_exits_cleanly(installed):
    installed.command("dw", "up")
    containers = installed.containers()
    for container in containers.values():
        assert installed.inspect(container, "{{.HostConfig.RestartPolicy.Name}}") == "on-failure"
    # docker kill counts as a manual stop, which no restart policy undoes.
    # The proxy runs as the CA directory's owner, so this user can crash it.
    os.kill(int(installed.inspect(containers["proxy"], "{{.State.Pid}}")), signal.SIGKILL)
    deadline = time.monotonic() + 60
    while installed.inspect(containers["proxy"], "{{.RestartCount}} {{.State.Running}}") != "1 true":
        assert time.monotonic() < deadline, "the crashed container was not restarted"
        time.sleep(1)
    installed.command("dw", "up")
    installed.run("docker", "compose", "-p", installed.project, "--project-directory", str(installed.root), "stop")
    for service, container in containers.items():
        assert installed.inspect(container, "{{.State.ExitCode}}") == "0", f"{service} did not exit 0 when stopped"


def test_down_and_up_keep_the_account_and_the_ca(installed):
    installed.command("dw", "up")
    ca = installed.ca.read_bytes()
    installed.command("dw", "down")
    assert installed.containers() == {}
    stopped = installed.command("dw", "status", check=False)
    assert stopped.returncode != 0
    assert "  proxy         not running" in stopped.stdout
    installed.command("dw", "up")
    assert installed.ca.read_bytes() == ca
    assert installed.sign_in()


def test_reinstalling_over_a_running_stack_restarts_it_healthy(installed):
    installed.command("dw", "up")
    (installed.root / "config" / "bypass.txt").write_text("mine.example\n", encoding="utf-8")
    refused = installed.run(installed.package / "install.sh", input="\n", check=False)
    assert refused.returncode == 1
    done = installed.run(installed.package / "install.sh", input="y\n")
    assert "every service is healthy" in done.stdout
    assert (installed.root / "config" / "bypass.txt").read_text(encoding="utf-8") == "mine.example\n"
    assert installed.command("dw", "status").returncode == 0
    assert installed.sign_in()
