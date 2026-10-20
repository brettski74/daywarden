"""S000.4: a browser trusts the CA, uses the explicit proxy, and the URL is visible."""

import json
import os
import signal
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DECISION_LOG = "/tmp/decisions.jsonl"
URL = "https://example.com/smartproxy-s0004"
FIREFOX_URL = "https://example.com/smartproxy-s0004-firefox"


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
        self.env["CA_VOLUME_PATH"] = str(ca_dir)
        self.env["SMARTPROXY_CONFIG_DIR"] = str(config_dir)
        self.cmd = ["docker", "compose", "-p", project, "-f", "docker-compose.yml"]

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


@pytest.fixture(scope="module")
def stack(request):
    with tempfile.TemporaryDirectory(prefix="smartproxy-s0004-") as raw:
        root = Path(raw)
        ca_dir = root / "ca"
        config_dir = root / "config"
        ca_dir.mkdir()
        config_dir.mkdir()
        (config_dir / "bypass.txt").write_text("# none\n")
        (config_dir / "decision.json").write_text('{"action": "allow"}\n')
        (config_dir / "policy.toml").write_text(
            '[[groups]]\nname = "Everything"\npriority = 1\ndefault = true\n'
        )
        running = Stack(
            ca_dir,
            config_dir,
            _free_port(),
            f"smartproxy-s0004-{os.getpid()}",
        )
        try:
            running.up()
            deadline = time.time() + 20
            while not running.cert_pem.is_file() and time.time() < deadline:
                time.sleep(0.2)
            yield running
        except Exception:
            print(running.logs())
            raise
        finally:
            if request.session.testsfailed:
                print(running.logs())
            running.down()


def _browser_home(stack: Stack, *, trust_ca: bool) -> Path:
    """Build the Chromium home the setup note describes.

    The note installs mitmproxy-ca-cert.pem with `trust anchor`, which puts it
    in the system store this Chromium reads through p11-kit. A test must not
    change that store, so the same PEM is imported into a temporary NSS
    database, the other store this browser consults. The proxy line is the
    one the note puts in ~/.config/chromium-flags.conf. --disable-quic stands
    in for the OPNsense UDP/443 block, which this machine does not have.
    """
    home = stack.config_dir / ("trusted-home" if trust_ca else "plain-home")
    if home.exists():
        return home
    config = home / ".config"
    config.mkdir(parents=True)
    (config / "chromium-flags.conf").write_text(
        f"--proxy-server=http://127.0.0.1:{stack.port}\n"
        "--disable-quic\n"
    )
    if trust_ca:
        nss = home / ".pki" / "nssdb"
        nss.mkdir(parents=True)
        _run(
            ["certutil", "-N", "-d", f"sql:{nss}", "--empty-password"],
            env=os.environ.copy(),
            timeout=20,
        )
        _run(
            [
                "certutil",
                "-A",
                "-d",
                f"sql:{nss}",
                "-t",
                "C,,",
                "-n",
                "mitmproxy",
                "-i",
                str(stack.cert_pem),
            ],
            env=os.environ.copy(),
            timeout=20,
        )
    return home


def _open(stack: Stack, home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    for name in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        env.pop(name, None)
    return subprocess.run(
        [
            "chromium",
            # A separate --user-data-dir value is a second headless target.
            f"--user-data-dir={home / 'profile'}",
            "--no-first-run",
            "--disable-gpu",
            "--headless=new",
            "--dump-dom",
            URL,
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )


def _urls(stack: Stack, *, wait_for_url: bool) -> list[str]:
    deadline = time.time() + (5 if wait_for_url else 0)
    while True:
        found = [entry["request"].get("url", "") for entry in stack.jsonl("decisions", DECISION_LOG)]
        if URL in found or time.time() >= deadline:
            return found
        time.sleep(0.2)


def test_untrusted_browser_does_not_reveal_the_https_url(stack):
    stack.clear_jsonl("decisions", DECISION_LOG)
    opened = _open(stack, _browser_home(stack, trust_ca=False))
    assert URL not in _urls(stack, wait_for_url=False), opened.stderr[-2000:]
    combined = opened.stdout + opened.stderr
    assert "ERR_CERT" in combined or "net_error -202" in combined, combined[-2000:]


def _firefox_profile(stack: Stack, *, trust_ca: bool) -> Path:
    """Build the Firefox profile the setup note describes.

    The note turns on security.enterprise_roots.enabled so Firefox uses the
    system store filled by `trust anchor`. A test must not change that store,
    so the PEM is imported into the profile, which is the note's other path
    (Authorities → Import). The proxy prefs are the manual proxy settings,
    including "Also use this proxy for HTTPS". HTTP/3 is off in place of the
    OPNsense UDP/443 block.
    """
    profile = stack.config_dir / ("firefox-trusted" if trust_ca else "firefox-plain")
    if profile.exists():
        return profile
    profile.mkdir()
    (profile / "user.js").write_text(
        "\n".join(
            [
                'user_pref("network.proxy.type", 1);',
                'user_pref("network.proxy.http", "127.0.0.1");',
                f'user_pref("network.proxy.http_port", {stack.port});',
                'user_pref("network.proxy.ssl", "127.0.0.1");',
                f'user_pref("network.proxy.ssl_port", {stack.port});',
                'user_pref("network.proxy.share_proxy_settings", true);',
                'user_pref("network.http.http3.enabled", false);',
                'user_pref("security.enterprise_roots.enabled", true);',
                'user_pref("browser.shell.checkDefaultBrowser", false);',
                'user_pref("browser.aboutwelcome.enabled", false);',
                'user_pref("datareporting.policy.dataSubmissionEnabled", false);',
            ]
        )
        + "\n"
    )
    if trust_ca:
        _run(
            ["certutil", "-N", "-d", f"sql:{profile}", "--empty-password"],
            env=os.environ.copy(),
            timeout=20,
        )
        _run(
            [
                "certutil",
                "-A",
                "-d",
                f"sql:{profile}",
                "-t",
                "C,,",
                "-n",
                "mitmproxy",
                "-i",
                str(stack.cert_pem),
            ],
            env=os.environ.copy(),
            timeout=20,
        )
    return profile


def _firefox_urls(stack: Stack, profile: Path, url: str, *, stop_on_rejection: bool) -> tuple[list[str], str, bool]:
    env = os.environ.copy()
    env["HOME"] = str(profile.parent / f"{profile.name}-home")
    Path(env["HOME"]).mkdir(exist_ok=True)
    env["MOZ_HEADLESS"] = "1"
    for name in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        env.pop(name, None)
    stderr_path = profile / "stderr.txt"
    with stderr_path.open("w") as stderr:
        process = subprocess.Popen(
            [
                "firefox",
                "--headless",
                "--new-instance",
                "--profile",
                str(profile),
                url,
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=stderr,
            start_new_session=True,
        )
    try:
        deadline = time.time() + 40
        rejected_before = stack.logs().count("bad certificate")
        found: list[str] = []
        while time.time() < deadline:
            found = [entry["request"].get("url", "") for entry in stack.jsonl("decisions", DECISION_LOG)]
            rejected = stack.logs().count("bad certificate") > rejected_before
            if url in found or (stop_on_rejection and rejected):
                return found, stderr_path.read_text(errors="replace"), rejected
            if process.poll() is not None:
                break
            time.sleep(0.5)
        rejected = stack.logs().count("bad certificate") > rejected_before
        return found, stderr_path.read_text(errors="replace"), rejected
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)


def test_untrusted_firefox_does_not_reveal_the_https_url(stack):
    stack.clear_jsonl("decisions", DECISION_LOG)
    profile = _firefox_profile(stack, trust_ca=False)
    urls, logged, rejected = _firefox_urls(stack, profile, FIREFOX_URL, stop_on_rejection=True)
    assert FIREFOX_URL not in urls, logged[-2000:]
    assert rejected, logged[-2000:]


def test_trusted_firefox_lets_the_proxy_see_the_https_url(stack):
    stack.clear_jsonl("decisions", DECISION_LOG)
    profile = _firefox_profile(stack, trust_ca=True)
    urls, logged, _rejected = _firefox_urls(stack, profile, FIREFOX_URL, stop_on_rejection=False)
    assert FIREFOX_URL in urls, (
        f"mitmproxy did not record {FIREFOX_URL}\n"
        f"urls: {urls}\n"
        f"firefox:\n{logged[-2000:]}\n"
        f"{stack.logs()}"
    )


def test_trusted_browser_lets_the_proxy_see_the_https_url(stack):
    stack.clear_jsonl("decisions", DECISION_LOG)
    opened = _open(stack, _browser_home(stack, trust_ca=True))
    urls = _urls(stack, wait_for_url=True)
    assert URL in urls, (
        f"mitmproxy did not record {URL}\n"
        f"urls: {urls}\n"
        f"stdout:\n{opened.stdout[-1500:]}\n"
        f"stderr:\n{opened.stderr[-1500:]}\n"
        f"{stack.logs()}"
    )
