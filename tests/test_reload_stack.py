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
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from conftest import write_alphabet, write_wav

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
        self.data = directory / "data"
        write_alphabet(self.data / "spelling" / "alphabet")
        for word in ("rope", "cat"):
            write_wav(self.data / "spelling" / "current" / f"{word}.wav")
        (directory / "ca").mkdir()
        fakes = directory / "fakes"
        fakes.mkdir()
        systemctl = fakes / "systemctl"
        systemctl.write_text("#!/bin/sh\necho 'Failed to connect to bus' >&2\nexit 1\n", encoding="utf-8")
        systemctl.chmod(0o755)
        self.project = f"dw-reload-{os.getpid()}"
        self.hostname = Path("/etc/hostname").read_text(encoding="utf-8").strip()
        self.env = {
            **os.environ,
            "PATH": f"{fakes}:{os.environ['PATH']}",
            "COMPOSE_PROJECT_NAME": self.project,
            "DAYWARDEN_CONFIG_DIR": str(self.config),
            "DAYWARDEN_DATA_DIR": str(self.data),
            "CA_VOLUME_PATH": str(directory / "ca"),
            "PROXY_PORT": str(_free_port()),
            "POLICY_PORT": str(_free_port()),
            "PROXY_CONFIG_PORT": str(_free_port()),
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

    def compose(self, *args: str, check: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess:
        done = subprocess.run(
            ["docker", "compose", "--project-directory", str(ROOT), *args],
            env=self.env,
            text=True,
            capture_output=True,
            input=input_text,
            timeout=120,
        )
        if check:
            assert done.returncode == 0, done.stderr
        return done

    def containers(self) -> dict[str, tuple[str, str]]:
        """Each service's container id and the time it started."""
        found = {}
        for service in ("decisions", "observations", "proxy", "autoconfig"):
            ident = self.compose("ps", "-q", service).stdout.strip()
            started = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.StartedAt}}", ident],
                text=True, capture_output=True, check=True,
            ).stdout.strip()
            found[service] = (ident, started)
        return found

    def decide(self) -> dict:
        return json.loads(self.compose("exec", "-T", "decisions", "python", "-c", DECIDE).stdout)

    def pac(self, path: str = "/proxy.pac", method: str = "GET") -> tuple[int, str]:
        request = urllib.request.Request(f"http://127.0.0.1:{self.env['PROXY_CONFIG_PORT']}{path}", data=b"" if method == "POST" else None, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read().decode()
        except urllib.error.HTTPError as error:
            return error.code, ""

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
    assert "The decisions, observations, and autoconfig services are using the reloaded policy." in done.stdout
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


def test_up_printed_the_configuration_url_and_the_file_names_the_proxy_port(daywarden):
    status, pac = daywarden.pac()
    assert status == 200
    assert f':{daywarden.env["PROXY_PORT"]}";' in pac
    assert daywarden.pac("/wpad.dat") == (200, pac)
    done = daywarden.dw("status")
    assert f":{daywarden.env['PROXY_CONFIG_PORT']}/proxy.pac" in done.stdout
    assert "  autoconfig    healthy" in done.stdout.splitlines()


def test_a_reload_changes_the_auto_configuration_file_without_a_restart(daywarden):
    good = (daywarden.config / "policy.yaml").read_text(encoding="utf-8")
    before = daywarden.containers()
    try:
        daywarden.edit("timezone: Australia/Sydney\n", "timezone: Australia/Sydney\nproxy_configuration:\n  direct:\n    extra: ['*.home.arpa']\n")
        done = daywarden.dw("reload")
        assert done.returncode == 0, done.stderr
        assert "proxy configuration extra direct entries: *.home.arpa" in done.stdout
        assert 'var DIRECT_GLOBS = ["*.home.arpa"];' in daywarden.pac()[1]
        daywarden.edit("extra: ['*.home.arpa']", "extra: ['10.8.0.0/33']")
        refused = daywarden.dw("reload")
        assert refused.returncode == 1
        assert "'10.8.0.0/33' is not a host name" in refused.stderr
        assert 'var DIRECT_GLOBS = ["*.home.arpa"];' in daywarden.pac()[1]
        assert daywarden.containers() == before
    finally:
        (daywarden.config / "policy.yaml").write_text(good, encoding="utf-8")
        assert daywarden.dw("reload").returncode == 0


def test_no_request_to_the_auto_configuration_port_can_reload_it(daywarden):
    good = (daywarden.config / "policy.yaml").read_text(encoding="utf-8")
    before = daywarden.pac()[1]
    try:
        daywarden.edit("timezone: Australia/Sydney\n", "timezone: Australia/Sydney\nproxy_configuration:\n  direct:\n    extra: [nas.example]\n")
        for path in ("/proxy.pac", "/v1/reload", "/reload"):
            assert daywarden.pac(path, "POST")[0] in {404, 501}
        assert daywarden.pac()[1] == before
    finally:
        (daywarden.config / "policy.yaml").write_text(good, encoding="utf-8")


def _portal(daywarden, method: str, path: str, body: dict | None = None, cookie: str = "") -> tuple[int, dict, dict]:
    request = urllib.request.Request(
        f"https://127.0.0.1:{daywarden.env['POLICY_PORT']}{path}",
        data=None if body is None else json.dumps(body).encode(),
        method=method,
        headers={"Content-Type": "application/json", **({"Cookie": cookie} if cookie else {})},
    )
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(request, timeout=30, context=context) as response:
            return response.status, json.loads(response.read()), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}"), dict(error.headers)


def test_a_portal_save_commits_hand_edits_then_the_save_and_reloads_every_service(daywarden):
    """S023.2: the container writes the config and data directories as the host user and reloads the others."""
    good = (daywarden.config / "policy.yaml").read_text(encoding="utf-8")
    me = os.getuid()
    try:
        daywarden.edit(
            "timezone: Australia/Sydney\n",
            "timezone: Australia/Sydney\nproxy_configuration:\n  direct:\n    extra: ['*.portal.arpa']\n"
            "tasks:\n  spelling:\n    type: spelling\n    group: younger\n",
        )
        added = daywarden.compose("exec", "-T", "decisions", "python", "-m", "policy.accounts", "ada", input_text="s3cret-pass\n")
        assert "parent account ada is saved" in added.stdout
        status, _body, headers = _portal(daywarden, "POST", "/parent/api/login", {"username": "ada", "password": "s3cret-pass"})
        assert status == 200
        cookie = headers["set-cookie"].split(";", 1)[0]
        status, page, _headers = _portal(daywarden, "GET", "/parent/api/tasks/spelling", cookie=cookie)
        assert status == 200, page
        assert {word["key"] for word in page["spelling"]["words"]} == {"rope", "cat"}

        status, saved, _headers = _portal(
            daywarden,
            "POST",
            "/parent/api/tasks/spelling",
            {"version": page["version"], "fields": {"pass_cooldown": "3"}, "moves": {"cat": "revision"}},
            cookie=cookie,
        )
        assert status == 200, saved
        assert saved["warnings"] == []
        assert "Moved cat to revision." in saved["message"]
        assert "pass_cooldown: 3" in (daywarden.config / "policy.yaml").read_text(encoding="utf-8")
        assert 'var DIRECT_GLOBS = ["*.portal.arpa"];' in daywarden.pac()[1]
        log = subprocess.run(
            ["git", "-C", str(daywarden.config), "log", "-2", "--format=%an %s"], text=True, capture_output=True, check=True
        ).stdout.splitlines()
        assert log[0].startswith("ada ") and log[0].endswith(" ada: saved task spelling")
        assert log[1].startswith("ada ") and log[1].endswith(" hand edits found before a portal save")
        status = subprocess.run(["git", "-C", str(daywarden.config), "status", "--porcelain"], text=True, capture_output=True, check=True)
        assert status.stdout == ""

        status, retired, _headers = _portal(daywarden, "POST", "/parent/api/tasks/spelling/retire", {"word": "rope"}, cookie=cookie)
        assert status == 200, retired
        written = [
            daywarden.config / "policy.yaml",
            daywarden.data / "spelling" / "revision",
            daywarden.data / "spelling" / "revision" / "cat.wav",
            daywarden.data / "spelling" / "attic",
            daywarden.data / "spelling" / "attic" / "rope.wav",
            *(daywarden.config / ".git").rglob("*"),
        ]
        assert [path for path in written if path.stat().st_uid != me] == []
    finally:
        (daywarden.config / "policy.yaml").write_text(good, encoding="utf-8")
        assert daywarden.dw("reload").returncode == 0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg makes the browser-like recording")
def test_a_browser_recording_is_cut_and_kept_by_the_decisions_container_as_the_host_user(daywarden, tmp_path):
    """S023.3: the image cuts a WebM Opus take with its own ffmpeg and writes the kept clips into the pool."""
    from test_clips import _audio, _write_wav

    good = (daywarden.config / "policy.yaml").read_text(encoding="utf-8")
    me = os.getuid()
    write_wav(daywarden.data / "spelling" / "current" / "sun.wav")
    source = _write_wav(tmp_path / "take.wav", _audio(500, 500, 900, 1200, 600)[0])
    subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(source), "-c:a", "libopus", "-f", "webm", str(tmp_path / "take.webm")], check=True)
    try:
        daywarden.edit("timezone: Australia/Sydney\n", "timezone: Australia/Sydney\ntasks:\n  spelling:\n    type: spelling\n    group: younger\n")
        assert daywarden.dw("reload").returncode == 0
        daywarden.compose("exec", "-T", "decisions", "python", "-m", "policy.accounts", "ada", input_text="s3cret-pass\n")
        status, _body, headers = _portal(daywarden, "POST", "/parent/api/login", {"username": "ada", "password": "s3cret-pass"})
        assert status == 200
        cookie = headers["set-cookie"].split(";", 1)[0]

        request = urllib.request.Request(
            f"https://127.0.0.1:{daywarden.env['POLICY_PORT']}/parent/api/recordings",
            data=(tmp_path / "take.webm").read_bytes(),
            method="POST",
            headers={"Content-Type": "audio/webm;codecs=opus", "Cookie": cookie},
        )
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(request, timeout=30, context=context) as response:
            take = json.loads(response.read())["take"]
        status, cut, _headers = _portal(daywarden, "POST", f"/parent/api/recordings/{take}/cut", {"settings": {}}, cookie=cookie)
        assert status == 200, cut
        assert len(cut["clips"]) == 2
        status, kept, _headers = _portal(
            daywarden,
            "POST",
            "/parent/api/tasks/spelling/recordings",
            {"take": take, "word": "sun", "clips": {"word": cut["clips"][0]["id"], "sentence": cut["clips"][1]["id"]}},
            cookie=cookie,
        )
        assert status == 200, kept
        current = daywarden.data / "spelling" / "current"
        assert sorted(path.name for path in current.glob("sun*")) == ["sun.opus", "sun.sentence.opus"]
        assert [path for path in (current / "sun.opus", current / "sun.sentence.opus", daywarden.data / ".recordings") if path.stat().st_uid != me] == []
        assert list((daywarden.data / ".recordings").iterdir()) == []
    finally:
        (daywarden.config / "policy.yaml").write_text(good, encoding="utf-8")
        assert daywarden.dw("reload").returncode == 0


def test_the_proxy_and_the_policy_pages_work_with_the_auto_configuration_service_stopped(daywarden):
    daywarden.compose("stop", "autoconfig")
    try:
        with pytest.raises(urllib.error.URLError):
            daywarden.pac()
        assert "action" in daywarden.decide()
        proxy = urllib.request.build_opener(urllib.request.ProxyHandler({"http": f"http://127.0.0.1:{daywarden.env['PROXY_PORT']}"}))
        with pytest.raises(urllib.error.HTTPError) as denied:
            proxy.open("http://daywarden-reload-test.invalid/", timeout=10)
        assert denied.value.code == 403
        done = daywarden.dw("reload")
        assert done.returncode == 1
        assert "The autoconfig service is not running. dw up starts it with this policy." in done.stderr
    finally:
        assert daywarden.dw("up").returncode == 0


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
    assert done.stdout.splitlines()[-2:] == [
        "daywarden restarted.",
        f"Proxy configuration URL: http://{daywarden.hostname}:{daywarden.env['PROXY_CONFIG_PORT']}/proxy.pac",
    ]
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


def test_logs_show_a_decision_and_keep_holds_it_across_a_stop_and_a_restart(daywarden):
    """S021: dw logs, dw down --keep, and dw restart --keep."""
    proxy = urllib.request.build_opener(urllib.request.ProxyHandler({"http": f"http://127.0.0.1:{daywarden.env['PROXY_PORT']}"}))
    with pytest.raises(urllib.error.HTTPError):
        proxy.open("http://dw-logs-test.invalid/", timeout=10)
    said = "decision deny GET http://dw-logs-test.invalid/ (default) for default at "

    def decision_lines() -> list[str]:
        done = daywarden.dw("logs", "decisions", "--tail", "all")
        assert done.returncode == 0, done.stderr
        return [line for line in done.stdout.splitlines() if said in line]

    deadline = time.monotonic() + 15
    while not decision_lines() and time.monotonic() < deadline:
        time.sleep(0.5)
    [line] = decision_lines()
    assert line.startswith("decisions-1  | ") and line.endswith(" by no rule")
    before = daywarden.containers()

    down = daywarden.dw("down", "--keep")
    assert down.returncode == 0, down.stderr
    assert "Its containers were kept, so dw logs can still show what they logged." in down.stdout
    assert "  decisions     not running" in daywarden.dw("status").stdout.splitlines()
    assert decision_lines() == [line]
    followed = daywarden.dw("logs", "-f", timeout=60)
    assert followed.returncode == 0, followed.stderr
    assert "no new lines to follow" in followed.stderr
    text = line.split(" | ", 1)[1]
    assert [shown.split(" | ", 1)[1] for shown in followed.stdout.splitlines() if said in shown] == [text]

    assert daywarden.dw("up").returncode == 0
    assert {service: ident for service, (ident, _) in daywarden.containers().items()} == {
        service: ident for service, (ident, _) in before.items()
    }
    restarted = daywarden.dw("restart", "--keep")
    assert restarted.returncode == 0, restarted.stdout + restarted.stderr
    assert "daywarden restarted." in restarted.stdout
    assert "Recreated" not in restarted.stdout
    assert decision_lines() == [line]
    kept = daywarden.compose("exec", "-T", "decisions", "cat", "/tmp/decisions.jsonl").stdout
    assert "http://dw-logs-test.invalid/" in kept
