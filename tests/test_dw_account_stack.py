"""S044.1 in the policy image: the accounts upgrade on the image's SQLite, and the password prompt under docker exec -it.

The host's .venv has a newer SQLite than the image, so the upgrade is run in the image as well.
"""

import os
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IMAGE = f"daywarden-policy:{os.environ.get('DW_POLICY_TAG') or 'local'}"

UPGRADE = r"""
import hashlib, os, sqlite3
from datetime import datetime, timedelta, timezone
from policy.accounts import Accounts, _HASHER
from policy.store import PolicyStore

now = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
key = os.urandom(32)
with sqlite3.connect("/tmp/old.sqlite3") as connection:
    connection.executescript('''
        CREATE TABLE parent_accounts (id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'admin');
        CREATE TABLE parent_sessions (id INTEGER PRIMARY KEY,
            account_id INTEGER NOT NULL REFERENCES parent_accounts(id) ON DELETE CASCADE,
            key_hash TEXT NOT NULL UNIQUE, signed_in_at TEXT NOT NULL, last_seen_at TEXT NOT NULL);
    ''')
    connection.execute("INSERT INTO parent_accounts (id, username, password_hash) VALUES (5, 'ada', ?)", (_HASHER.hash("ada-pass"),))
    connection.execute("INSERT INTO parent_sessions (account_id, key_hash, signed_in_at, last_seen_at) VALUES (5, ?, ?, ?)",
                       (hashlib.sha256(key).hexdigest(), now.isoformat(), now.isoformat()))
with PolicyStore("/tmp/old.sqlite3") as store:
    accounts = Accounts(store.connection)
    assert accounts.accept(key.hex(), now + timedelta(minutes=1)) == ("ada", "admin")
    assert accounts.account_id("ada") == 5
    accounts.add("nana", email="nana@example.net")
    accounts.remove("nana")
    accounts.add("nana", email="nana@example.net")
    assert accounts.account_id("nana") == 7
print("upgraded on SQLite", sqlite3.sqlite_version)
"""

ECHO = "import termios; print('echo' if termios.tcgetattr(0)[3] & termios.ECHO else '-echo')"


def _docker(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], text=True, capture_output=True, check=False, timeout=600, **kwargs)


@pytest.fixture(scope="module")
def container():
    built = _docker("build", "--quiet", "--tag", IMAGE, str(ROOT / "policy"))
    assert built.returncode == 0, built.stderr
    name = f"daywarden-s0441-{os.getpid()}"
    started = _docker("run", "-d", "--rm", "--name", name, "-e", "POLICY_DB=/tmp/policy.sqlite3", "--entrypoint", "sleep", IMAGE, "600")
    assert started.returncode == 0, started.stderr
    try:
        added = _docker("exec", "-i", name, "python", "-m", "policy.accounts", "add", "--role", "admin", "--password", "ada", input="ada-pass\n")
        assert added.returncode == 0, added.stderr
        yield name
    finally:
        _docker("rm", "-f", name)


def test_the_upgrade_runs_on_the_images_sqlite(container):
    done = _docker("exec", "-i", container, "python", "-", input=UPGRADE)
    assert done.returncode == 0, done.stderr
    assert "upgraded on SQLite 3." in done.stdout


def _read_until(primary: int, seen: bytes, marker: bytes) -> bytes:
    deadline = time.monotonic() + 30
    while marker not in seen and time.monotonic() < deadline:
        seen += os.read(primary, 1024)
    assert marker in seen, seen
    return seen


def _prompt(container: str, answers: tuple[bytes, ...] = (), signal_name: str | None = None) -> str:
    """Run update --password under docker exec -it in a pseudo-terminal and return what the terminal showed.

    Each answer is typed after the next prompt appears. Then signal_name, if
    any, is sent to the command in the container. bash runs the command, then
    reports its status and whether the container's terminal echoes.
    """
    import pty

    primary, secondary = pty.openpty()
    script = f"python -m policy.accounts update --password ada; echo rc=$?; python -c \"{ECHO}\""
    process = subprocess.Popen(
        ["docker", "exec", "-it", container, "bash", "-c", script],
        stdin=secondary, stdout=secondary, stderr=secondary, start_new_session=True,
    )
    os.close(secondary)
    seen = _read_until(primary, b"", b"Password: ")
    for number, answer in enumerate(answers):
        if number:
            seen = _read_until(primary, seen, b"Password again: ")
        os.write(primary, answer)
    if signal_name:
        killed = _docker(
            "exec", container, "sh", "-c",
            # Only the python process: its arguments, NUL-separated, are exactly these.
            "for p in /proc/[0-9]*; do "
            f'[ "$(tr "\\0" " " < $p/cmdline 2>/dev/null)" = "python -m policy.accounts update --password ada " ] && kill -{signal_name} ${{p#/proc/}}; '
            "done; true",
        )
        assert killed.returncode == 0, killed.stderr
    process.wait(timeout=30)
    try:
        while True:
            chunk = os.read(primary, 1024)
            if not chunk:
                break
            seen += chunk
    except OSError:
        pass
    os.close(primary)
    return seen.decode(errors="replace").replace("\r", "")


def _signs_in(container: str, password: str) -> bool:
    done = _docker(
        "exec", "-i", container, "python", "-",
        input="from datetime import datetime, timezone\n"
        "from policy.accounts import Accounts\nfrom policy.store import PolicyStore\n"
        "with PolicyStore('/tmp/policy.sqlite3') as store:\n"
        f"    print(Accounts(store.connection).login('ada', {password!r}, datetime.now(timezone.utc)) is not None)\n",
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip() == "True"


@pytest.mark.parametrize(
    ("answers", "signal_name"),
    [((b"\x03",), None), ((b"\x1c",), None), ((b"\x04",), None), ((), "TERM"), ((), "HUP"), ((b"new-pass\r",), "TERM")],
    ids=["ctrl-c", "ctrl-backslash", "ctrl-d", "term", "hup", "term-at-second-prompt"],
)
def test_a_stopped_prompt_leaves_the_terminal_echoing_and_changes_nothing(container, answers, signal_name):
    shown = _prompt(container, answers, signal_name)
    assert "Nothing was changed." in shown
    assert "rc=130" in shown
    assert shown.rstrip().endswith("\necho")
    assert _signs_in(container, "ada-pass")


def test_two_passwords_typed_at_the_prompt_set_it_and_two_that_differ_do_not(container):
    shown = _prompt(container, (b"new-pass\r", b"other-pass\r"))
    assert "The two passwords differ. Nothing was changed." in shown
    assert _signs_in(container, "ada-pass")
    shown = _prompt(container, (b"new-pass\r", b"new-pass\r"))
    assert "ada's password is set." in shown
    assert shown.rstrip().endswith("\necho")
    assert _signs_in(container, "new-pass")
