"""Parent accounts and sessions on the decisions service.

There is no sign-up page. A host command adds or replaces one username.
The password is read once and stored as an Argon2id hash. Replacing a
password ends that account's sessions and the MCP connections it approved.
Each account has one role, ``admin`` or ``reviewer`` (S043). The host command
sets it, and changing it ends the account's sessions. A session key is 256 bits from the
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
from typing import NamedTuple

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from argon2.low_level import Type

COOKIE_NAME = "parent_session"
ADMIN = "admin"
REVIEWER = "reviewer"
ROLES = (ADMIN, REVIEWER)
USAGE = """\
usage: python -m policy.accounts USERNAME
       python -m policy.accounts --role ROLE USERNAME
       python -m policy.accounts --set-role ROLE USERNAME
       python -m policy.accounts --list
Add a parent account, or replace its password and end its sessions.
The password is read once, from the terminal or from one line of stdin.

Roles:
  admin      runs the system: every page, data address, and MCP tool.
  reviewer   reads attempts and usage, and records parent checks. Nothing else.

  USERNAME              add an admin, or replace an account's password. Its role is kept.
  --role ROLE USERNAME  add a new account with ROLE. Refused for an existing account.
  --set-role ROLE USERNAME
                        change an existing account's role. No password is asked for.
                        Its sessions end, so it must sign in again.
  --list                list each account and its role."""

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
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin'
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


class AccountError(ValueError):
    """A change to the accounts that is refused. Nothing was changed."""


class Parent(NamedTuple):
    """The account a session belongs to."""

    username: str
    role: str

    @property
    def admin(self) -> bool:
        return self.role == ADMIN


def role_problem(role: object) -> str | None:
    """Return why role is not a role, or None."""
    if role in ROLES:
        return None
    return f"{role} is not a role. The roles are admin and reviewer."


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
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(parent_accounts)")}
        if "role" not in columns:
            # Accounts from before S043 run the system, so each becomes an admin.
            with self.connection:
                self.connection.execute("ALTER TABLE parent_accounts ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")

    def count(self) -> int:
        """Return how many parent accounts are stored."""
        (count,) = self.connection.execute("SELECT COUNT(*) FROM parent_accounts").fetchone()
        return int(count)

    def account_id(self, username: str) -> int | None:
        row = self.connection.execute("SELECT id FROM parent_accounts WHERE username = ?", (username,)).fetchone()
        return None if row is None else int(row[0])

    def accounts(self) -> list[Parent]:
        """Return every account and its role, in username order."""
        rows = self.connection.execute("SELECT username, role FROM parent_accounts ORDER BY username").fetchall()
        return [Parent(username, role) for username, role in rows]

    def check_new(self, username: str, role: str | None) -> None:
        """Raise AccountError when ``set_password(username, ..., role)`` would be refused, before a password is read."""
        if role is not None and role_problem(role) is not None:
            raise AccountError(role_problem(role))
        if role is not None and self.account_id(username) is not None:
            raise AccountError(
                f"{username} already exists, so --role is refused and nothing was changed. "
                f"Change its role with --set-role, or leave out --role to replace its password."
            )

    def set_password(self, username: str, password: str, role: str | None = None) -> None:
        """Add this username, or replace its password and end its sessions.

        A new account has role, or ``admin`` when role is None. An existing
        account keeps its role, and naming a role for it is refused.
        The password is hashed. It is not written anywhere else.
        """
        if not isinstance(username, str) or username == "":
            raise ValueError("username is required")
        if not isinstance(password, str) or password == "":
            raise ValueError("a password is required")
        self.check_new(username, role)
        digest = _HASHER.hash(password)
        row = self.connection.execute(
            "SELECT id FROM parent_accounts WHERE username = ?",
            (username,),
        ).fetchone()
        with self.connection:
            if row is None:
                self.connection.execute(
                    "INSERT INTO parent_accounts (username, password_hash, role) VALUES (?, ?, ?)",
                    (username, digest, role or ADMIN),
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
        # The agents this parent approved must be approved again, as the browser must sign in again.
        from policy.mcp_store import McpStore

        McpStore(self.connection).end_for_account(account_id, datetime.now(timezone.utc), "the parent's password was replaced")

    def set_role(self, username: str, role: str) -> None:
        """Change an existing account's role and end its sessions.

        The MCP connections it approved are kept: each call reads the role again.
        Refused, changing nothing, for an unknown username, a role that is not
        one, or making the only admin a reviewer.
        """
        problem = role_problem(role)
        if problem is not None:
            raise AccountError(problem)
        row = self.connection.execute("SELECT id, role FROM parent_accounts WHERE username = ?", (username,)).fetchone()
        if row is None:
            raise AccountError(f"There is no parent account {username}. Nothing was changed.")
        account_id, before = row
        if before == ADMIN and role != ADMIN:
            (admins,) = self.connection.execute("SELECT COUNT(*) FROM parent_accounts WHERE role = ?", (ADMIN,)).fetchone()
            if admins <= 1:
                raise AccountError(f"{username} is the only admin. Add another admin first.")
        with self.connection:
            self.connection.execute("UPDATE parent_accounts SET role = ? WHERE id = ?", (role, account_id))
            self.connection.execute("DELETE FROM parent_sessions WHERE account_id = ?", (account_id,))

    def role_of(self, account_id: int) -> str | None:
        """Return an account's role, or None when the account is gone."""
        row = self.connection.execute("SELECT role FROM parent_accounts WHERE id = ?", (account_id,)).fetchone()
        return None if row is None else row[0]

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

    def accept(self, token: str | None, now: datetime) -> Parent | None:
        """Return the account, with its role, when token is still valid, and refresh its idle time.

        A key past the idle limit or the lifetime is removed. That request
        does not refresh the idle time, and the key cannot be used again.
        """
        key = _key_bytes(token)
        if key is None:
            return None
        row = self.connection.execute(
            """
            SELECT parent_sessions.id, parent_sessions.signed_in_at, parent_sessions.last_seen_at,
                   parent_accounts.username, parent_accounts.role
            FROM parent_sessions
            JOIN parent_accounts ON parent_accounts.id = parent_sessions.account_id
            WHERE parent_sessions.key_hash = ?
            """,
            (hashlib.sha256(key).hexdigest(),),
        ).fetchone()
        if row is None:
            return None
        session_id, signed_in, last_seen, username, role = row
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
        return Parent(username, role)

    def end(self, token: str | None) -> None:
        """Remove the session for token, so that key cannot be used again."""
        key = _key_bytes(token)
        if key is None:
            return
        with self.connection:
            self.connection.execute(
                "DELETE FROM parent_sessions WHERE key_hash = ?",
                (hashlib.sha256(key).hexdigest(),),
            )

    def cookie_header(self, token: str) -> str:
        """Return the Set-Cookie value for a session key."""
        return f"{COOKIE_NAME}={token}; Secure; HttpOnly; SameSite=Lax; Path=/"

    def clear_cookie_header(self) -> str:
        """Return the Set-Cookie value that removes the session cookie."""
        return f"{COOKIE_NAME}=; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"

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


def _arguments(args: list[str]) -> tuple[str, str | None, str | None]:
    """Return the action (add, set-role, or list), the role named, and the username. Exit with the usage when they do not fit."""
    action, role, rest = "add", None, []
    index = 0
    while index < len(args):
        arg = args[index]
        name, equals, value = arg.partition("=")
        if name in ("--role", "--set-role"):
            if not equals:
                index += 1
                if index >= len(args):
                    raise SystemExit(f"{name} needs a role: admin or reviewer")
                value = args[index]
            if role is not None:
                raise SystemExit(USAGE.splitlines()[0])
            role = value
            if name == "--set-role":
                action = "set-role"
        elif arg == "--list":
            action = "list" if action == "add" and role is None else ""
        elif arg.startswith("-"):
            raise SystemExit(f"{arg} is not an option.\n{USAGE}")
        else:
            rest.append(arg)
        index += 1
    if action == "list":
        if rest or role is not None:
            raise SystemExit(USAGE.splitlines()[0])
        return action, None, None
    if action == "" or len(rest) != 1 or rest[0] == "":
        raise SystemExit(USAGE.splitlines()[0])
    return action, role, rest[0]


def main(argv: list[str] | None = None) -> None:
    """Add or replace one parent username, change its role, or list the accounts."""
    args = list(sys.argv[1:] if argv is None else argv)
    if "--help" in args or "-h" in args:
        print(USAGE, flush=True)
        return
    action, role, username = _arguments(args)
    if role is not None and role_problem(role) is not None:
        raise SystemExit(role_problem(role))
    # Imported here so a sign-in check does not load the policy loader.
    from policy.store import PolicyStore

    database = Path(os.environ.get("POLICY_DB", "/var/lib/daywarden/policy.sqlite3"))
    database.parent.mkdir(parents=True, exist_ok=True)
    store = PolicyStore(database)
    try:
        accounts = Accounts(store.connection)
        if action == "list":
            for parent in accounts.accounts():
                print(f"{parent.username} {parent.role}", flush=True)
            return
        assert username is not None
        if action == "set-role":
            assert role is not None
            accounts.set_role(username, role)
            print(f"{username} is now {'an' if role == ADMIN else 'a'} {role}. Its sessions have ended.", flush=True)
            return
        accounts.check_new(username, role)
        password = read_password_once()
        if password == "":
            raise SystemExit("a password is required")
        accounts.set_password(username, password, role)
        saved = next(parent.role for parent in accounts.accounts() if parent.username == username)
    except AccountError as error:
        raise SystemExit(str(error)) from None
    finally:
        store.close()
    print(f"parent account {username} is saved, as {'an' if saved == ADMIN else 'a'} {saved}", flush=True)


if __name__ == "__main__":
    main()
