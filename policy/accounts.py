"""Parent accounts and sessions on the decisions service.

There is no sign-up page. A host command adds or replaces one username.
The password is read once and stored as an Argon2id hash. Replacing a
password ends that account's sessions. A session key is 256 bits from the
operating system's random source. The browser receives the key. The database
stores the SHA-256 of the key, the account, the sign-in time, and the time
of the last accepted request.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from getpass import getpass
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from argon2.low_level import Type

COOKIE_NAME = "parent_session"
USAGE = """\
usage: python -m policy.accounts USERNAME
Add a parent account, or replace its password and end its sessions.
The password is read once, from the terminal or from one line of stdin."""

# OWASP minimum for Argon2id: 19 MiB, 2 iterations, parallelism 1.
# memory_cost is kibibytes. Verification reads the parameters in the hash.
_HASHER = PasswordHasher(
    time_cost=2,
    memory_cost=19 * 1024,
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)
# Checked when the username is missing, so that refusal takes the same work
# as a wrong password. The password here is never an account.
_DUMMY = _HASHER.hash(secrets.token_hex(32))

_DURATION = re.compile(r"(\d+)([hms])\Z", re.IGNORECASE)
_UNIT_SECONDS = {"h": 3600, "m": 60, "s": 1}
_DEFAULT_IDLE = 15 * 60
_DEFAULT_LIFETIME = 180 * 60

_TABLES = """
CREATE TABLE IF NOT EXISTS parent_accounts (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS parent_sessions (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES parent_accounts(id) ON DELETE CASCADE,
    key_hash TEXT NOT NULL UNIQUE,
    signed_in_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS parent_checks (
    id INTEGER PRIMARY KEY,
    client_group TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
"""


class Accounts:
    """The parent account table and its sessions, on one SQLite connection."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        idle: timedelta = timedelta(seconds=_DEFAULT_IDLE),
        lifetime: timedelta = timedelta(seconds=_DEFAULT_LIFETIME),
    ) -> None:
        if idle <= timedelta(0) or lifetime <= timedelta(0):
            raise ValueError("session limits must be positive")
        self.connection = connection
        self.idle = idle
        self.lifetime = lifetime
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(_TABLES)

    def count(self) -> int:
        """Return how many parent accounts are stored."""
        (count,) = self.connection.execute("SELECT COUNT(*) FROM parent_accounts").fetchone()
        return int(count)

    def set_password(self, username: str, password: str) -> None:
        """Add this username, or replace its password and end its sessions.

        The password is hashed. It is not written anywhere else.
        """
        if not isinstance(username, str) or username == "":
            raise ValueError("username is required")
        if not isinstance(password, str) or password == "":
            raise ValueError("a password is required")
        digest = _HASHER.hash(password)
        row = self.connection.execute(
            "SELECT id FROM parent_accounts WHERE username = ?",
            (username,),
        ).fetchone()
        with self.connection:
            if row is None:
                self.connection.execute(
                    "INSERT INTO parent_accounts (username, password_hash) VALUES (?, ?)",
                    (username, digest),
                )
                return
            account_id = row[0]
            self.connection.execute(
                "UPDATE parent_accounts SET password_hash = ? WHERE id = ?",
                (digest, account_id),
            )
            self.connection.execute(
                "DELETE FROM parent_sessions WHERE account_id = ?",
                (account_id,),
            )

    def login(self, username: str, password: str, now: datetime) -> str | None:
        """Return a new session key, or None when the sign-in is refused.

        A missing username still runs a password check. A new sign-in does
        not end older keys for the same account.
        """
        if not isinstance(username, str):
            username = ""
        if not isinstance(password, str):
            password = ""
        row = self.connection.execute(
            "SELECT id, password_hash FROM parent_accounts WHERE username = ?",
            (username,),
        ).fetchone()
        stored = None if row is None else row[1]
        # Always check a hash. Short-circuiting on a missing username would
        # make that refusal faster than a wrong password.
        matched = _passwords_match(stored, password)
        if stored is None or not matched:
            return None
        key = secrets.token_bytes(32)
        moment = _utc_second(now).isoformat()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO parent_sessions (account_id, key_hash, signed_in_at, last_seen_at)
                VALUES (?, ?, ?, ?)
                """,
                (row[0], hashlib.sha256(key).hexdigest(), moment, moment),
            )
        return key.hex()

    def accept(self, token: str | None, now: datetime) -> str | None:
        """Return the username when token is still valid, and refresh its idle time.

        A key past the idle limit or the lifetime is removed. That request
        does not refresh the idle time, and the key cannot be used again.
        """
        key = _key_bytes(token)
        if key is None:
            return None
        row = self.connection.execute(
            """
            SELECT parent_sessions.id, parent_sessions.signed_in_at, parent_sessions.last_seen_at,
                   parent_accounts.username
            FROM parent_sessions
            JOIN parent_accounts ON parent_accounts.id = parent_sessions.account_id
            WHERE parent_sessions.key_hash = ?
            """,
            (hashlib.sha256(key).hexdigest(),),
        ).fetchone()
        if row is None:
            return None
        session_id, signed_in, last_seen, username = row
        moment = _utc_second(now)
        if moment - _parse(signed_in) > self.lifetime or moment - _parse(last_seen) > self.idle:
            with self.connection:
                self.connection.execute("DELETE FROM parent_sessions WHERE id = ?", (session_id,))
            return None
        with self.connection:
            self.connection.execute(
                "UPDATE parent_sessions SET last_seen_at = ? WHERE id = ?",
                (moment.isoformat(), session_id),
            )
        return username

    def cookie_header(self, token: str) -> str:
        """Return the Set-Cookie value for a session key."""
        return f"{COOKIE_NAME}={token}; Secure; HttpOnly; SameSite=Lax; Path=/"

    def record_parent_check(self, client_group: str, now: datetime) -> None:
        """Store one parent_check pass. Callers check the session first."""
        if not isinstance(client_group, str) or client_group.strip() == "":
            raise ValueError("a client group is required")
        with self.connection:
            self.connection.execute(
                "INSERT INTO parent_checks (client_group, recorded_at) VALUES (?, ?)",
                (client_group.strip(), _utc_second(now).isoformat()),
            )

    def parent_checks(self) -> tuple[tuple[str, str], ...]:
        """Return recorded parent_check passes, newest first."""
        rows = self.connection.execute(
            "SELECT client_group, recorded_at FROM parent_checks ORDER BY id DESC"
        ).fetchall()
        return tuple((client_group, recorded_at) for client_group, recorded_at in rows)


def session_limits(environ: os._Environ[str] | dict[str, str]) -> tuple[timedelta, timedelta]:
    """Return the idle limit and the lifetime.

    A missing value uses 15 minutes and 180 minutes. Any other value that is
    not a positive duration stops the service.
    """
    return (
        timedelta(seconds=_setting(environ, "PARENT_IDLE", _DEFAULT_IDLE)),
        timedelta(seconds=_setting(environ, "PARENT_LIFETIME", _DEFAULT_LIFETIME)),
    )


def cookie_value(header: str | None, name: str) -> str | None:
    """Return the value of name in a Cookie header, or None when it is absent."""
    if not header:
        return None
    prefix = name + "="
    for part in header.split(";"):
        item = part.strip()
        if item.startswith(prefix):
            return item[len(prefix) :]
    return None


def _passwords_match(stored: str | None, password: str) -> bool:
    """Check password against stored, or against the dummy hash when stored is missing."""
    try:
        return _HASHER.verify(_DUMMY if stored is None else stored, password)
    except (VerifyMismatchError, VerificationError):
        return False


def _setting(environ: os._Environ[str] | dict[str, str], name: str, default: int) -> int:
    if name not in environ:
        return default
    return _positive_duration(environ[name], name)


def _positive_duration(value: str, name: str) -> int:
    text = value.strip() if isinstance(value, str) else ""
    match = _DURATION.fullmatch(text)
    seconds = 0 if match is None else int(match.group(1)) * _UNIT_SECONDS[match.group(2).lower()]
    if match is None or seconds < 1:
        raise SystemExit(f"{name} must be a positive duration like 15m, 180m, or 90s")
    return seconds


def _key_bytes(token: str | None) -> bytes | None:
    if not isinstance(token, str) or len(token) != 64:
        return None
    try:
        key = bytes.fromhex(token)
    except ValueError:
        return None
    if len(key) != 32:
        return None
    return key


def _utc_second(moment: datetime) -> datetime:
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise ValueError("time must be an aware datetime")
    return moment.astimezone(timezone.utc).replace(microsecond=0)


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def read_password_once() -> str:
    """Read one password from the terminal, or one line from stdin."""
    if sys.stdin.isatty():
        return getpass("Password: ")
    line = sys.stdin.readline()
    if line.endswith("\n"):
        line = line[:-1]
    if line.endswith("\r"):
        line = line[:-1]
    return line


def main(argv: list[str] | None = None) -> None:
    """Add or replace one parent username. The password is read once."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["--help"], ["-h"]):
        print(USAGE, flush=True)
        return
    if len(args) != 1 or args[0] == "" or args[0].startswith("-"):
        raise SystemExit(USAGE.splitlines()[0])
    username = args[0]
    password = read_password_once()
    if password == "":
        raise SystemExit("a password is required")
    # Imported here so a sign-in check does not load the policy loader.
    from policy.store import PolicyStore

    database = Path(os.environ.get("POLICY_DB", "/var/lib/daywarden/policy.sqlite3"))
    database.parent.mkdir(parents=True, exist_ok=True)
    store = PolicyStore(database)
    try:
        Accounts(store.connection).set_password(username, password)
    finally:
        store.close()
    print(f"parent account {username} is saved", flush=True)


if __name__ == "__main__":
    main()
