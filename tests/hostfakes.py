"""A stand-in machine for the install package tests.

``Host`` gives each test a temporary HOME, an /etc with a hostname and a
resolv.conf, and a PATH that holds only the real tools the host scripts
need plus fake ``docker``, ``systemctl``, ``loginctl``, ``getent``, ``ip``,
``ss``, ``id``, ``ffmpeg``, ``python3``, and ``journalctl``. The fakes read the machine's
state from one JSON file, record each call, and write back what a call
changed. A test leaves a fake or a real tool out to make that tool missing.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from deploy.build import stage  # noqa: E402

VERSION = "20261105-184500"
NEWER = "20261106-091500"
FAKES = ("docker", "systemctl", "loginctl", "getent", "ip", "ss", "id", "ffmpeg", "python3", "journalctl")
REAL_TOOLS = (
    "bash", "sh", "env", "cat", "cp", "mv", "rm", "mkdir", "ln", "readlink", "dirname", "basename",
    "sed", "awk", "grep", "tr", "cut", "sort", "head", "tail", "date", "sha256sum", "timeout", "sleep",
    "chmod", "mktemp", "touch", "wc", "uname", "tee", "stat", "ls", "cmp", "realpath", "printf", "true", "git",
)
SERVICES = ("decisions", "observations", "proxy", "autoconfig")

FAKE = r'''
import json, os, re, signal, sys, time
from pathlib import Path

SERVICES = ("decisions", "observations", "proxy", "autoconfig")
# The host ports each service is created with, as Compose would hash them.
HASHED = {"decisions": ("POLICY_PORT", "PROXY_CONFIG_PORT"), "proxy": ("PROXY_PORT",), "autoconfig": ("PROXY_PORT", "PROXY_CONFIG_PORT")}
DEFAULT_PORTS = {"PROXY_PORT": "8080", "POLICY_PORT": "8084", "PROXY_CONFIG_PORT": "8088"}

state_path = Path(os.environ["FAKE_STATE"])
state = json.loads(state_path.read_text())
program = Path(sys.argv[0]).name
args = sys.argv[1:]
venv_python = "/venv/bin/" in sys.argv[0]
with open(str(state_path) + ".calls", "a") as log:
    log.write(json.dumps(["venv-python" if venv_python else program, *args]) + "\n")


def save():
    state_path.write_text(json.dumps(state))


def config_hash(service):
    if service in state.get("config_hash", {}):
        return state["config_hash"][service]
    ports = [os.environ.get(key, DEFAULT_PORTS[key]) for key in HASHED.get(service, ())]
    if ports == [DEFAULT_PORTS[key] for key in HASHED.get(service, ())]:
        return "hash-" + service
    return "hash-" + service + "-" + "-".join(ports)


def in_container(sub, rest):
    """docker compose exec or run of a policy module, as the policy image would answer."""
    options = [arg for arg in rest if arg.startswith("-")]
    words = [arg for arg in rest if not arg.startswith("-")]
    service, command = words[0], rest[rest.index(words[0]) + 1:]
    if sub == "exec" and service not in state["running"]:
        print(f"service {service!r} is not running", file=sys.stderr)
        sys.exit(1)
    if sub == "run":
        state.setdefault("runs", []).append(service)
        save()
    if command[:3] == ["python", "-m", "policy.check"]:
        errors = state.get("policy_errors", [])
        if errors:
            refused = command[command.index("--refused") + 1] if "--refused" in command else ""
            count = f"dw: the policy has {len(errors)} error{'' if len(errors) == 1 else 's'}."
            print(f"{count} {refused}".strip(), file=sys.stderr)
            for error in errors:
                print(error, file=sys.stderr)
            sys.exit(1)
        if "--quiet" not in command:
            print("household timezone Australia/Sydney")
    elif command[:3] == ["python", "-m", "policy.reload"]:
        reloading = command[command.index("--service") + 1]
        refused = state.get("reload_refused", {}).get(reloading)
        if refused:
            print(refused, file=sys.stderr)
            sys.exit(1)
        state.setdefault("reloaded", []).append(reloading)
        save()
        if reloading == "decisions":
            print("household timezone Australia/Sydney")
    elif command[:4] == ["python", "-m", "policy.autoconfig", "--url"]:
        print(state.get("config_url", f"http://tundra:{os.environ.get('PROXY_CONFIG_PORT', '8088')}/proxy.pac"))


def compose(args):
    while args and args[0] in ("--project-directory", "-p", "-f", "--progress"):
        args = args[2:]
    sub, rest = (args[0], args[1:]) if args else ("", [])
    if sub == "version":
        print("Docker Compose version v5.4.0")
    elif sub == "up":
        # A stopped container is started again unless its settings changed. Any other is created.
        failing = state.get("up_fails", {})
        recreated = state.setdefault("recreated", {})
        hashes = state.setdefault("running_hash", {})
        exited = state.get("exited", [])
        for service in SERVICES:
            if service in state["running"]:
                continue
            if service in exited and hashes.get(service, "hash-" + service) == config_hash(service):
                continue
            recreated[service] = recreated.get(service, 0) + 1
            hashes[service] = config_hash(service)
            state.setdefault("ids", {})[service] = f"id-{service}-{recreated[service]}"
        state["exited"] = []
        state["up_env"] = {key: os.environ.get(key) for key in (*DEFAULT_PORTS, "RESOLV_CONF_DIR", "RESOLV_CONF_NAME")}
        state["running"] = {service: failing.get(service, "healthy") for service in SERVICES}
        save()
        if failing:
            print("container is unhealthy", file=sys.stderr)
            sys.exit(1)
    elif sub == "config" and rest[:1] == ["--hash"]:
        for service in SERVICES:
            print(f"{service} {config_hash(service)}")
    elif sub in ("exec", "run"):
        in_container(sub, rest)
    elif sub == "down":
        state["running"] = {}
        state["exited"] = []
        save()
    elif sub == "stop":
        state["exited"] = sorted(set(state.get("exited", [])) | set(state["running"]))
        state["running"] = {}
        save()
    elif sub == "ps" and "-q" in rest:
        named = [arg for arg in rest if not arg.startswith("-")]
        for service in named or SERVICES:
            if service in state["running"] or service in state.get("exited", []):
                print(state.get("ids", {}).get(service, f"id-{service}"))
    elif sub == "ps":
        for service, health in state["running"].items():
            print(f"{service}\trunning\t{health}")
        for service in state.get("exited", []):
            print(f"{service}\texited\t")
    elif sub == "logs":
        logs(rest)
    else:
        sys.exit(f"fake docker compose: {sub} is not faked")


def wait_for_ctrl_c(status):
    """Follow until SIGINT, then exit with status, as docker compose logs -f (130) and journalctl -f (0) do."""
    signal.signal(signal.SIGINT, lambda *_: sys.exit(status))
    print("following", flush=True)
    while True:
        time.sleep(1)


def logs(rest):
    takes_value = ("--tail", "--since")
    if "--since" in rest:
        since = rest[rest.index("--since") + 1]
        if not re.fullmatch(r"(\d+(\.\d+)?(ns|us|ms|s|m|h))+|\d{4}-\d\d-\d\d(T[0-9:.]+(Z|[+-][0-9:]+)?)?", since):
            print(f'invalid value for "since": failed to parse value as time or duration: "{since}"', file=sys.stderr)
            sys.exit(1)
    named = [arg for i, arg in enumerate(rest) if not arg.startswith("-") and rest[i - 1] not in takes_value]
    for service in named:
        said = state.get("logs", {}).get(service, f"{service} said nothing")
        for line in said.splitlines():
            print(line if "--no-log-prefix" in rest else f"{service}-1  | {line}")
    if "--follow" in rest and state.get("follow_waits"):
        wait_for_ctrl_c(130)


def journalctl():
    lines = state.get("journal", [])
    if "--lines" in args:
        count = int(args[args.index("--lines") + 1])
        lines = lines[-count:] if count else []
    if "-n" in args:
        lines = lines[-int(args[args.index("-n") + 1]):]
    print("\n".join(lines) if lines else "-- No entries --")
    if "--follow" in args and state.get("follow_waits"):
        wait_for_ctrl_c(0)


def docker():
    daemon = state.get("daemon", "up")
    if args[:1] == ["compose"]:
        if not state.get("compose", True):
            print("docker: unknown command: docker compose", file=sys.stderr)
            sys.exit(1)
        if args[1:2] != ["version"] and daemon != "up":
            print("Cannot connect to the Docker daemon", file=sys.stderr)
            sys.exit(1)
        compose(args[1:])
        return
    if daemon == "down":
        print("Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?", file=sys.stderr)
        sys.exit(1)
    if daemon == "denied":
        print("permission denied while trying to connect to the docker API at unix:///var/run/docker.sock", file=sys.stderr)
        sys.exit(1)
    if args[:1] == ["info"]:
        return
    if args[:1] == ["load"]:
        print(f"Loaded image: daywarden-policy:{state.get('version', 'x')}")
        return
    if args[:1] == ["ps"]:
        labels = [args[i + 1] for i, arg in enumerate(args) if arg == "--filter"]
        project = state.get("project", "daywarden")
        running = state["running"]
        if f"label=com.docker.compose.project={project}" not in labels:
            running = {}
        for label in labels:
            if label.startswith("label=com.docker.compose.service="):
                wanted = label.split("=", 2)[2]
                running = {s: h for s, h in running.items() if s == wanted}
        if "--format" in args and "config-hash" in args[args.index("--format") + 1]:
            for service in running:
                print(f"{service}\t{state.get('running_hash', {}).get(service, 'hash-' + service)}")
        elif "--format" in args:
            for service in running:
                print(state.get("ports", {}).get(service, "8090/tcp"))
        else:
            for service in running:
                print(f"id-{service}")
        return
    sys.exit(f"fake docker: {args} is not faked")


def systemctl():
    systemd = state["systemd"]
    if args[:1] != ["--user"]:
        if args[:1] == ["is-enabled"]:
            unit = args[1]
            answer = "enabled" if unit in systemd.get("docker_boot", []) else "disabled"
            print(answer)
            sys.exit(0 if answer == "enabled" else 1)
        sys.exit(f"fake systemctl: {args} is not faked")
    if not systemd.get("user_manager", True):
        print("Failed to connect to bus: No medium found", file=sys.stderr)
        sys.exit(1)
    rest = [arg for arg in args[1:] if arg != "--quiet"]
    verb = rest[0]
    if verb == "show-environment":
        print("HOME=/home/tester")
    elif verb == "is-enabled":
        answer = "enabled" if systemd.get("enabled") else "disabled"
        print(answer)
        sys.exit(0 if answer == "enabled" else 1)
    elif verb == "is-active":
        print(systemd.get("active", "inactive"))
        sys.exit(0 if systemd.get("active") == "active" else 3)
    elif verb == "show":
        print(systemd.get("active", "inactive"))
    elif verb == "enable":
        systemd["enabled"] = True
    elif verb == "disable":
        systemd["enabled"] = False
    elif verb == "start":
        if systemd.get("start_fails"):
            sys.exit(1)
        systemd["active"] = "active"
    elif verb == "stop":
        systemd["active"] = "inactive"
    elif verb == "daemon-reload":
        systemd["reloads"] = systemd.get("reloads", 0) + 1
    else:
        sys.exit(f"fake systemctl: {args} is not faked")
    save()


def loginctl():
    if args[:1] == ["show-user"]:
        print(state.get("linger", "no"))
    elif args[:1] == ["enable-linger"]:
        if state.get("linger_fails"):
            print("Could not enable linger: Access denied", file=sys.stderr)
            sys.exit(1)
        state["linger"] = "yes"
        save()
    else:
        sys.exit(f"fake loginctl: {args} is not faked")


def getent():
    name = args[1]
    if name in state.get("slow", []):
        time.sleep(30)
    addresses = state.get("dns", {}).get(name.lower())
    if not addresses:
        sys.exit(2)
    for address in addresses:
        for kind in ("STREAM", "DGRAM", "RAW"):
            print(f"{address:<15} {kind} {name}")


def ip():
    for number, (interface, address) in enumerate(state.get("interfaces", []), 1):
        family = "inet6" if ":" in address else "inet"
        print(f"{number}: {interface}    {family} {address} scope global {interface}\\       valid_lft forever")


def ss():
    for port in state.get("listening", []):
        print(f"LISTEN 0      4096         0.0.0.0:{port}       0.0.0.0:*")


def identity():
    if args == ["-u"]:
        print(state.get("uid", 1000))
    elif args == ["-un"]:
        print("tester")
    else:
        sys.exit(f"fake id: {args} is not faked")


def ffmpeg():
    if state.get("ffmpeg") == "opus":
        print(" A....D libopus              libopus Opus (codec opus)")
    print(" A....D aac                  AAC (Advanced Audio Coding)")


def python():
    if venv_python:
        if args[:2] == ["-m", "pip"]:
            if state.get("pypi") == "down":
                print("ERROR: Could not find a version that satisfies the requirement fastapi==0.148.0", file=sys.stderr)
                sys.exit(1)
            return
        if args[:1] == ["-c"]:
            sys.exit(0 if state.get("venv_works", True) else 1)
        if args[:2] == ["-m", "policy.clips"]:
            state["clips_cwd"] = os.getcwd()
            state["clips_path"] = os.environ.get("PYTHONPATH", "")
            save()
            return
        sys.exit(f"fake venv python: {args} is not faked")
    if args[:1] == ["-c"]:
        print(state.get("python_version", "3.14.2"))
    elif args[:2] == ["-m", "venv"]:
        target = Path(args[2])
        (target / "bin").mkdir(parents=True)
        python = target / "bin" / "python"
        python.write_text(Path(sys.argv[0]).read_text())
        python.chmod(0o755)
    else:
        sys.exit(f"fake python3: {args} is not faked")


{"docker": docker, "systemctl": systemctl, "loginctl": loginctl, "getent": getent, "ip": ip,
 "ss": ss, "id": identity, "ffmpeg": ffmpeg, "journalctl": journalctl}.get(program, python)()
'''


def machine_arch() -> str:
    machine = platform.machine()
    return {"x86_64": "amd64", "aarch64": "arm64"}.get(machine, machine)


def make_package(directory: Path, version: str = VERSION) -> Path:
    """Stage a package as make dist does, with a stand-in images.tar."""
    package = directory / f"daywarden-{version}"
    stage(package, version, machine_arch())
    (package / "images.tar").write_bytes(b"images")
    return package


class Host:
    def __init__(self, tmp_path: Path, *, without: tuple[str, ...] = ()):
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        self.home.mkdir()
        (self.home / "bin").mkdir()
        self.etc = tmp_path / "etc"
        self.etc.mkdir()
        (self.etc / "hostname").write_text("tundra\n", encoding="utf-8")
        (self.etc / "resolv.conf").write_text("nameserver 192.0.2.1\n", encoding="utf-8")
        self.state_path = tmp_path / "state.json"
        self.state: dict = {
            "daemon": "up",
            "compose": True,
            "running": {},
            "systemd": {"user_manager": True, "enabled": False, "active": "inactive", "docker_boot": ["docker.service"]},
            "linger": "no",
            "ffmpeg": "opus",
            "interfaces": [["eth0", "192.0.2.10/24"]],
        }
        self.fakes = tmp_path / "fakes"
        self.fakes.mkdir()
        script = f"#!{sys.executable}\n{FAKE}"
        for name in FAKES:
            if name not in without:
                fake = self.fakes / name
                fake.write_text(script, encoding="utf-8")
                fake.chmod(0o755)
        self.tools = tmp_path / "tools"
        self.tools.mkdir()
        for name in REAL_TOOLS:
            real = shutil.which(name)
            if real and name not in without:
                (self.tools / name).symlink_to(real)
        self.path = f"{self.home / 'bin'}:{self.fakes}:{self.tools}"
        self.root = self.home / "daywarden"

    @property
    def unit(self) -> Path:
        return self.home / ".config" / "systemd" / "user" / "daywarden.service"

    def _environment(self, env: dict | None) -> dict:
        self.state_path.write_text(json.dumps(self.state), encoding="utf-8")
        return {
            "HOME": str(self.home),
            "PATH": self.path,
            "USER": "tester",
            "LANG": "C.UTF-8",
            "FAKE_STATE": str(self.state_path),
            "DAYWARDEN_ETC": str(self.etc),
            **(env or {}),
        }

    def run(self, *command: str | Path, input: str = "", cwd: Path | None = None, env: dict | None = None):
        done = subprocess.run(
            [str(part) for part in command],
            input=input,
            cwd=cwd or self.tmp,
            env=self._environment(env),
            text=True,
            capture_output=True,
            timeout=60,
        )
        self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
        return done

    def start_dw(self, *args: str) -> subprocess.Popen:
        """Start dw in its own process group, as a terminal runs it, so a test can press Ctrl-C on the group."""
        return subprocess.Popen(
            [str(self.home / "bin" / "dw"), *args],
            cwd=self.tmp,
            env=self._environment(None),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )

    def install(self, package: Path, *, input: str = "", **kwargs):
        return self.run(package / "install.sh", input=input, **kwargs)

    def dw(self, *args: str, **kwargs):
        return self.run(self.home / "bin" / "dw", *args, **kwargs)

    def calls(self, program: str | None = None) -> list[list[str]]:
        path = Path(str(self.state_path) + ".calls")
        if not path.exists():
            return []
        calls = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        return [call for call in calls if program is None or call[0] == program]

    def forget_calls(self) -> None:
        Path(str(self.state_path) + ".calls").unlink(missing_ok=True)

    def all_running(self) -> None:
        self.state["running"] = {service: "healthy" for service in SERVICES}
