"""Parent accounts and sessions on the decisions service.

There is no sign-up page. The host command, ``dw-account`` (S044.1), adds,
changes, lists, and removes accounts. An account may have no password yet, and
then no sign-in to it succeeds. A password is stored as an Argon2id hash.
Setting a password ends that account's sessions and the MCP connections it
approved. Each account has one role, ``admin`` or ``reviewer`` (S043), and at
most one email address. Changing the role ends the account's sessions.
Removing an account ends its sessions and its MCP connections, and its id is
never used again. A session key is 256 bits from the
operating system's random source. The browser receives the key. The database
stores the SHA-256 of the key, the account, the sign-in time, and the time
of the last accepted request.

A parent changes their own password on the portal's Account page, or resets
it with a link sent to the account's address (S044.2). A reset token is 256
bits, stored as its SHA-256 in ``password_resets``, one row per account, so a
newer link replaces an older one. Setting the password any way removes the
row, and removing the account removes it by cascade. The lifetime is checked
when the token is used.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import secrets
import signal
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from getpass import getpass
from pathlib import Path
from typing import NamedTuple, NoReturn

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from argon2.low_level import Type

COOKIE_NAME = "parent_session"
ADMIN = "admin"
REVIEWER = "reviewer"
ROLES = (ADMIN, REVIEWER)
# Counted in Unicode characters. Long enough for any passphrase, and keeps the
# service from hashing whatever an attacker sends.
LONGEST_PASSWORD = 200
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\Z")
_LONGEST_EMAIL = 254

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

_ACCOUNTS_TABLE = """
CREATE TABLE IF NOT EXISTS parent_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT,
    role TEXT NOT NULL DEFAULT 'reviewer',
    email TEXT
)"""
_TABLES = _ACCOUNTS_TABLE + """;
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
CREATE TABLE IF NOT EXISTS password_resets (
    account_id INTEGER PRIMARY KEY REFERENCES parent_accounts(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    made_at TEXT NOT NULL
);
"""
# A second reset link for the same account within this long of the last one is not sent.
RESET_COOLDOWN = timedelta(minutes=5)


class AccountError(ValueError):
    """A change to the accounts that is refused. Nothing was changed."""


class Parent(NamedTuple):
    """The account a session belongs to."""

    username: str
    role: str

    @property
    def admin(self) -> bool:
        return self.role == ADMIN


class ResetLink(NamedTuple):
    """A reset token just made for an account with an address. Only its SHA-256 is stored."""

    username: str
    email: str
    token: str


class PasswordReset(NamedTuple):
    """An account whose password a valid reset link just set."""

    username: str
    email: str | None
    # False when the reset set the account's first password.
    had_password: bool


class Account(NamedTuple):
    """One account as ``dw-account list`` shows it."""

    username: str
    role: str
    email: str | None
    has_password: bool


def role_problem(role: object) -> str | None:
    """Return why role is not a role, or None."""
    if role in ROLES:
        return None
    return f"{role} is not a role. The roles are admin and reviewer."


def email_problem(email: object) -> str | None:
    """Return why email is not an address of the form name@domain, or None."""
    if isinstance(email, str) and len(email) <= _LONGEST_EMAIL and _EMAIL.match(email):
        return None
    return f"{email} is not an email address. Give one of the form name@domain, such as nana@example.net."


def password_problem(password: object) -> str | None:
    """Return why password cannot be a password, or None."""
    if not isinstance(password, str) or password == "":
        return "The password is empty."
    if len(password) > LONGEST_PASSWORD:
        return f"The password is longer than {LONGEST_PASSWORD} characters."
    return None


def _article(role: str) -> str:
    return "an" if role == ADMIN else "a"


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
        if "email" not in self._columns():
            self._upgrade()

    def _columns(self) -> set[str]:
        return {row[1] for row in self.connection.execute("PRAGMA table_info(parent_accounts)")}

    def _upgrade(self) -> None:
        """Rebuild parent_accounts from before S044.1, keeping each row's id.

        The new table lets password_hash be null, adds email, and never reuses
        an id. SQLite 3.46, which the service runs, cannot drop a NOT NULL in
        place. Accounts from before S043 have no role and become admins.
        Foreign keys are off while the old table is dropped, so its sessions
        stay, and they match the same ids in the new table.
        """
        self.connection.commit()
        self.connection.execute("PRAGMA foreign_keys = OFF")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            columns = self._columns()
            if "email" in columns:
                # Another process upgraded it first.
                self.connection.execute("ROLLBACK")
                return
            role = "role" if "role" in columns else "'admin'"
            # One statement at a time: executescript would commit the open transaction.
            self.connection.execute(_ACCOUNTS_TABLE.replace("IF NOT EXISTS parent_accounts", "parent_accounts_upgraded"))
            self.connection.execute(
                "INSERT INTO parent_accounts_upgraded (id, username, password_hash, role) "
                f"SELECT id, username, password_hash, {role} FROM parent_accounts"
            )
            self.connection.execute("DROP TABLE parent_accounts")
            self.connection.execute("ALTER TABLE parent_accounts_upgraded RENAME TO parent_accounts")
            broken = self.connection.execute("PRAGMA foreign_key_check").fetchall()
            if broken:
                raise sqlite3.IntegrityError(f"the accounts upgrade broke {len(broken)} references")
            self.connection.execute("COMMIT")
        except BaseException:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise
        finally:
            self.connection.execute("PRAGMA foreign_keys = ON")

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

    def entries(self) -> list[Account]:
        """Return every account with its role, address, and whether it has a password, in username order."""
        rows = self.connection.execute(
            "SELECT username, role, email, password_hash IS NOT NULL FROM parent_accounts ORDER BY username"
        ).fetchall()
        return [Account(username, role, email, bool(has)) for username, role, email, has in rows]

    def entry(self, username: str) -> Account | None:
        return next((found for found in self.entries() if found.username == username), None)

    def _admins(self) -> int:
        (admins,) = self.connection.execute("SELECT COUNT(*) FROM parent_accounts WHERE role = ?", (ADMIN,)).fetchone()
        return int(admins)

    # Checks. Each runs before a password is read, and each refusal changes nothing.

    def check_add(self, username: str, role: str, email: str | None, password: bool) -> None:
        """Raise AccountError when ``add`` with these would be refused."""
        if not isinstance(username, str) or username.strip() == "":
            raise AccountError("A username is required. Nothing was added.")
        problem = role_problem(role) or (None if email is None else email_problem(email))
        if problem is not None:
            raise AccountError(f"{problem} Nothing was added.")
        if self.account_id(username) is not None:
            raise AccountError(f"{username} already exists, so nothing was added. Change it with dw-account update.")
        if role != ADMIN and self._admins() == 0:
            raise AccountError("There is no admin yet. Add the first account with --role admin.")
        if email is None and not password:
            raise AccountError(
                f"{username} would have no email address and no password, so there would be no way to set a password. "
                "Give --email, --password, or both. Nothing was added."
            )

    def check_update(self, username: str, role: str | None = None, email: str | None = None) -> None:
        """Raise AccountError when ``update`` with these would be refused."""
        row = self.connection.execute("SELECT role FROM parent_accounts WHERE username = ?", (username,)).fetchone()
        if row is None:
            raise AccountError(f"There is no parent account {username}. Nothing was changed. Add it with dw-account add.")
        problem = (None if role is None else role_problem(role)) or (None if email is None else email_problem(email))
        if problem is not None:
            raise AccountError(f"{problem} Nothing was changed.")
        if role is not None and row[0] == ADMIN and role != ADMIN and self._admins() <= 1:
            raise AccountError(f"{username} is the only admin. Add another admin first.")

    def check_remove(self, username: str) -> None:
        """Raise AccountError when ``remove`` would be refused."""
        row = self.connection.execute("SELECT role FROM parent_accounts WHERE username = ?", (username,)).fetchone()
        if row is None:
            raise AccountError(f"There is no parent account {username}. Nothing was removed. Add it with dw-account add.")
        if row[0] == ADMIN and self._admins() <= 1:
            raise AccountError(f"{username} is the only admin. Add another admin first.")

    # Changes

    def add(self, username: str, role: str = REVIEWER, email: str | None = None, password: str | None = None) -> None:
        """Add a new account. It has no password unless one is given."""
        self.check_add(username, role, email, password is not None)
        digest = None
        if password is not None:
            problem = password_problem(password)
            if problem is not None:
                raise AccountError(f"{problem} Nothing was added.")
            digest = _HASHER.hash(password)
        with self.connection:
            self.connection.execute(
                "INSERT INTO parent_accounts (username, password_hash, role, email) VALUES (?, ?, ?, ?)",
                (username, digest, role, email),
            )

    def update(
        self,
        username: str,
        *,
        role: str | None = None,
        email: str | None = None,
        no_email: bool = False,
        password: str | None = None,
    ) -> None:
        """Change an existing account. Every change is checked before any is made.

        A new role or a new password ends the account's sessions. A new
        password also ends the MCP connections the account approved. The MCP
        connections are kept on a role change: each call reads the role again.
        """
        if email is not None and no_email:
            raise AccountError("--email and --no-email cannot both be given. Nothing was changed.")
        self.check_update(username, role, email)
        digest = None
        if password is not None:
            problem = password_problem(password)
            if problem is not None:
                raise AccountError(f"{problem} Nothing was changed.")
            digest = _HASHER.hash(password)
        account_id = self.account_id(username)
        assert account_id is not None
        with self.connection:
            if role is not None:
                self.connection.execute("UPDATE parent_accounts SET role = ? WHERE id = ?", (role, account_id))
            if email is not None or no_email:
                self.connection.execute("UPDATE parent_accounts SET email = ? WHERE id = ?", (email, account_id))
            if digest is not None:
                self.connection.execute("UPDATE parent_accounts SET password_hash = ? WHERE id = ?", (digest, account_id))
                # A reset link sent before the change no longer works.
                self.connection.execute("DELETE FROM password_resets WHERE account_id = ?", (account_id,))
            if role is not None or digest is not None:
                self.connection.execute("DELETE FROM parent_sessions WHERE account_id = ?", (account_id,))
        if digest is not None:
            # The agents this parent approved must be approved again, as the browser must sign in again.
            from policy.mcp_store import McpStore

            McpStore(self.connection).end_for_account(account_id, datetime.now(timezone.utc), "the parent's password was replaced")

    def remove(self, username: str) -> None:
        """Remove an account, its sessions, its unused MCP codes, and the MCP connections it approved.

        The activity log keeps naming it. Its id is never used again, so a new
        account with the same username gets none of these back.
        """
        self.check_remove(username)
        account_id = self.account_id(username)
        assert account_id is not None
        from policy.mcp_store import McpStore

        McpStore(self.connection).end_for_account(account_id, datetime.now(timezone.utc), "the parent's account was removed")
        with self.connection:
            # mcp_codes has no foreign key, so its rows are removed here.
            self.connection.execute("DELETE FROM mcp_codes WHERE account_id = ?", (account_id,))
            self.connection.execute("DELETE FROM parent_accounts WHERE id = ?", (account_id,))

    def set_password(self, username: str, password: str, role: str | None = None) -> None:
        """Add an account with this password, or replace an existing account's password.

        A new account has role, or ``admin`` when role is None. An existing
        account keeps its role, and naming a role for it is refused. The tests
        use this to make accounts. The host command uses ``add`` and ``update``.
        """
        if self.account_id(username) is None:
            self.add(username, role or ADMIN, password=password)
            return
        if role is not None:
            raise AccountError(f"{username} already exists. Change its role with dw-account update --role.")
        self.update(username, password=password)

    def role_of(self, account_id: int) -> str | None:
        """Return an account's role, or None when the account is gone."""
        row = self.connection.execute("SELECT role FROM parent_accounts WHERE id = ?", (account_id,)).fetchone()
        return None if row is None else row[0]

    def login(self, username: str, password: str, now: datetime) -> str | None:
        """Return a new session key, or None when the sign-in is refused.

        A missing username, or an account with no password yet, still runs a
        password check, against the dummy hash. A password longer than
        LONGEST_PASSWORD is not hashed: the dummy hash is checked against a
        fixed one instead, so the refusal takes the same time. A new sign-in
        does not end older keys for the same account.
        """
        if not isinstance(username, str):
            username = ""
        if not isinstance(password, str):
            password = ""
        if len(password) > LONGEST_PASSWORD:
            _passwords_match(None, "")
            return None
        row = self.connection.execute(
            "SELECT id, password_hash FROM parent_accounts WHERE username = ?",
            (username,),
        ).fetchone()
        stored = None if row is None else row[1]
        # Always check a hash. Short-circuiting on a missing username or a
        # missing password would make that refusal faster than a wrong password.
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

    # Changing a password from the portal, and resetting one by email (S044.2)

    def change_password(self, username: str, session: str | None, current: object, new: object, again: object) -> str | None:
        """Change the signed-in account's own password. Return why it was refused, or None when it changed.

        The new password is checked first. The current one is then checked
        with the same work as a sign-in: one longer than LONGEST_PASSWORD is
        refused as a wrong one, after the same check of the dummy hash. On a
        change every other session of the account ends, the one named by
        session stays, any reset link stops working, and the MCP connections
        the account approved end. A refusal changes nothing.
        """
        problem = new_password_problem(new, again)
        if problem is not None:
            return f"{problem} Nothing was changed."
        assert isinstance(new, str)
        row = self.connection.execute("SELECT id, password_hash FROM parent_accounts WHERE username = ?", (username,)).fetchone()
        stored = None if row is None else row[1]
        if not isinstance(current, str) or len(current) > LONGEST_PASSWORD:
            _passwords_match(None, "")
            matched = False
        else:
            matched = _passwords_match(stored, current)
        if stored is None or not matched:
            return "The current password is wrong. Nothing was changed."
        account_id = row[0]
        digest = _HASHER.hash(new)
        key = _key_bytes(session)
        kept = "" if key is None else hashlib.sha256(key).hexdigest()
        with self.connection:
            self.connection.execute("UPDATE parent_accounts SET password_hash = ? WHERE id = ?", (digest, account_id))
            self.connection.execute("DELETE FROM parent_sessions WHERE account_id = ? AND key_hash != ?", (account_id, kept))
            self.connection.execute("DELETE FROM password_resets WHERE account_id = ?", (account_id,))
        self._end_mcp(account_id, "the parent's password was changed")
        return None

    def request_reset(self, username: object, now: datetime) -> tuple[ResetLink | None, bool]:
        """Make a reset token for username, when it is an account with an address.

        Return the link to send, or None, and whether the request was skipped
        because a link was sent to the account less than RESET_COOLDOWN ago.
        A new token replaces the account's older one, which stops working.
        """
        if not isinstance(username, str):
            return None, False
        row = self.connection.execute("SELECT id, email FROM parent_accounts WHERE username = ?", (username,)).fetchone()
        if row is None or row[1] is None:
            return None, False
        account_id, email = row
        moment = _utc_second(now)
        last = self.connection.execute("SELECT made_at FROM password_resets WHERE account_id = ?", (account_id,)).fetchone()
        if last is not None and moment - _parse(last[0]) < RESET_COOLDOWN:
            return None, True
        token = secrets.token_bytes(32)
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO password_resets (account_id, token_hash, made_at) VALUES (?, ?, ?)",
                (account_id, hashlib.sha256(token).hexdigest(), moment.isoformat()),
            )
        return ResetLink(username, email, token.hex()), False

    def reset_password(self, token: object, digest: str, now: datetime, lifetime: timedelta) -> PasswordReset | None:
        """Set the account a valid reset token belongs to to the password hashed as digest, and use the token up.

        The caller hashes the password with ``hash_password`` whether or not
        the token is valid, so both answers take the same work. A valid token
        is the newest made for its account, within lifetime of when it was
        made, and not used yet. Any other token changes nothing and returns
        None. A reset ends every session of the account and the MCP
        connections it approved, and does not sign the parent in.
        """
        key = _key_bytes(token if isinstance(token, str) else None)
        if key is None:
            return None
        row = self.connection.execute(
            """
            SELECT password_resets.account_id, password_resets.made_at, parent_accounts.username,
                   parent_accounts.email, parent_accounts.password_hash IS NOT NULL
            FROM password_resets
            JOIN parent_accounts ON parent_accounts.id = password_resets.account_id
            WHERE password_resets.token_hash = ?
            """,
            (hashlib.sha256(key).hexdigest(),),
        ).fetchone()
        if row is None:
            return None
        account_id, made_at, username, email, had_password = row
        with self.connection:
            # Used or not, a token checked after its lifetime is gone.
            self.connection.execute("DELETE FROM password_resets WHERE account_id = ?", (account_id,))
            if _utc_second(now) - _parse(made_at) > lifetime:
                return None
            self.connection.execute("UPDATE parent_accounts SET password_hash = ? WHERE id = ?", (digest, account_id))
            self.connection.execute("DELETE FROM parent_sessions WHERE account_id = ?", (account_id,))
        self._end_mcp(account_id, "the parent's password was reset")
        return PasswordReset(username, email, bool(had_password))

    def _end_mcp(self, account_id: int, reason: str) -> None:
        from policy.mcp_store import McpStore

        McpStore(self.connection).end_for_account(account_id, datetime.now(timezone.utc), reason)

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


def hash_password(password: str) -> str:
    """Return the Argon2id hash stored for password."""
    return _HASHER.hash(password)


def new_password_problem(new: object, again: object) -> str | None:
    """Return why a new password typed twice on a portal page is refused, saying which check failed, or None."""
    problem = password_problem(new)
    if problem is not None:
        return problem.replace("The password", "The new password")
    if new != again:
        return "The two new passwords differ."
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
    return positive_duration(environ[name], name)


def positive_duration(value: str, name: str) -> int:
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


# The host command: dw-account, which runs ``python -m policy.accounts`` in the
# decisions container.

PROG = "dw-account"
HELP = f"""\
usage: {PROG} SUBCOMMAND [SWITCHES] [USERNAME]

Add, change, list, and remove the parent accounts that sign in to the parent portal.

Subcommands:
  add [--role admin|reviewer] [--email ADDRESS] [--password] USERNAME
        Add a new account. USERNAME must not exist yet.
        --role      admin or reviewer. A new account is a reviewer unless --role admin is given.
                    While there is no admin, the first account must be added with --role admin.
        --email     the parent's email address, of the form name@domain.
        --password  ask for a password. Without it, the account has no password yet and no one
                    can sign in to it. Give --email, --password, or both.
        With --email and no --password, the parent is sent a welcome email that tells them
        to choose a password with Forgot password on the sign-in screen.
  update USERNAME [--role admin|reviewer] [--email ADDRESS | --no-email] [--password]
        Change an existing account. Give at least one switch. Every switch is checked
        before anything changes.
        --role      change the role. The account's sessions end, so it must sign in again.
                    The only admin cannot become a reviewer.
        --email     set the email address.   --no-email  remove it.
        --password  ask for a new password. The account's sessions and the MCP connections
                    it approved end, and an account with an address is emailed a notice.
  remove [--yes] USERNAME
        Remove an existing account, its sessions, and the MCP connections it approved.
        Asks first. Without a terminal, --yes is needed. The only admin cannot be removed.
  list  Each account: its username, role, email address or "no email", and "no password"
        when it has none yet.
  test-email USERNAME
        Send a short test email to USERNAME's address, to check the SMTP_ settings in .env.
        Says that the mail server accepted it, or why it was not sent.
  help  This help. {PROG} SUBCOMMAND --help describes one subcommand.

Roles:
  admin      runs the system: every page, data address, and MCP tool.
  reviewer   reads attempts and usage, and records parent checks. Nothing else.

A password is 1 to {LONGEST_PASSWORD} characters. It is asked for twice with echo off, and never read
from the command line. Without a terminal, it is read once, as one line of standard input."""


class _Stopped(Exception):
    """A signal that ends the command while it waits at a prompt."""


class _Usage(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: {message}\nRun {self.prog} --help for more.\n")


def _subcommands() -> dict[str, argparse.ArgumentParser]:
    def parser(name: str, description: str) -> argparse.ArgumentParser:
        return _Usage(prog=f"{PROG} {name}", description=description, allow_abbrev=False)

    add = parser("add", "Add a new account. USERNAME must not exist yet. Give --email, --password, or both.")
    add.add_argument(
        "--role", choices=ROLES, default=REVIEWER, help="admin or reviewer. A new account is a reviewer unless --role admin is given."
    )
    add.add_argument("--email", metavar="ADDRESS", help="the parent's email address, of the form name@domain.")
    add.add_argument(
        "--password", action="store_true", help="ask for a password. Without it, the account has no password yet."
    )
    add.add_argument("username", metavar="USERNAME")

    update = parser("update", "Change an existing account. Give at least one switch. If any is refused, nothing changes.")
    update.add_argument("username", metavar="USERNAME")
    update.add_argument("--role", choices=ROLES, help="change the role. The account's sessions end.")
    email = update.add_mutually_exclusive_group()
    email.add_argument("--email", metavar="ADDRESS", help="set the email address, of the form name@domain.")
    email.add_argument("--no-email", action="store_true", help="remove the email address.")
    update.add_argument(
        "--password",
        action="store_true",
        help="ask for a new password. The account's sessions and the MCP connections it approved end.",
    )

    remove = parser(
        "remove", "Remove an existing account, its sessions, and the MCP connections it approved. This cannot be undone."
    )
    remove.add_argument("--yes", action="store_true", help="remove without asking. Needed without a terminal.")
    remove.add_argument("username", metavar="USERNAME")

    listing = parser("list", 'List each account: username, role, email address or "no email", and "no password" when it has none.')
    testing = parser("test-email", "Send a short test email to USERNAME's address, to check the SMTP_ settings in .env.")
    testing.add_argument("username", metavar="USERNAME")
    helping = parser("help", "Describe every subcommand and switch.")
    return {"add": add, "update": update, "remove": remove, "list": listing, "test-email": testing, "help": helping}


def _command_line(args: list[str]) -> argparse.Namespace:
    """Return the subcommand and its switches, or exit with that subcommand's usage."""
    subcommands = _subcommands()
    if not args:
        print(HELP, file=sys.stderr, flush=True)
        raise SystemExit(2)
    if args[0] in ("-h", "--help"):
        args = ["help", *args[1:]]
    name = args[0]
    if name not in subcommands:
        print(HELP.splitlines()[0], file=sys.stderr)
        print(f"{PROG}: {name} is not a subcommand. The subcommands are {', '.join(subcommands)}.", file=sys.stderr)
        raise SystemExit(2)
    parser = subcommands[name]
    found = parser.parse_args(args[1:])
    found.action = name
    if name == "update" and found.role is None and found.email is None and not found.no_email and not found.password:
        parser.error("give at least one of --role, --email, --no-email, or --password")
    return found


# A prompt left this long ends. When the docker client is killed, the command
# in the container is not, and without this it would wait for ever.
PROMPT_SECONDS = 5 * 60


@contextmanager
def _signals_stop():
    """Turn SIGTERM, SIGHUP, SIGQUIT, and the prompt's time running out into _Stopped while a prompt is open.

    getpass restores the terminal's echo in a finally block, which runs for
    Ctrl+C and Ctrl+D but not when one of these signals ends the process.
    """

    def stop(signum: int, _frame: object) -> None:
        if signum == signal.SIGALRM:
            raise _Stopped(f"No answer came within {PROMPT_SECONDS // 60} minutes.")
        raise _Stopped("Stopped.")

    names = ("SIGTERM", "SIGHUP", "SIGQUIT", "SIGALRM")
    saved = {name: signal.signal(getattr(signal, name), stop) for name in names}
    signal.alarm(PROMPT_SECONDS)
    try:
        yield
    finally:
        signal.alarm(0)
        for name, handler in saved.items():
            signal.signal(getattr(signal, name), handler)


def read_password_once() -> str:
    """Read one line of stdin as a password."""
    line = sys.stdin.readline()
    if line.endswith("\n"):
        line = line[:-1]
    if line.endswith("\r"):
        line = line[:-1]
    return line


def read_new_password(nothing: str) -> str:
    """Ask for a password twice from the terminal, or read it once from stdin.

    nothing is the end of a refusal, such as "Nothing was added."
    """
    if not sys.stdin.isatty():
        password = read_password_once()
    else:
        with _signals_stop():
            password = getpass("Password: ")
            again = getpass("Password again: ")
        if password != again:
            raise AccountError(f"The two passwords differ. {nothing}")
    problem = password_problem(password)
    if problem is not None:
        raise AccountError(f"{problem} {nothing}")
    return password


def _confirm(question: str) -> bool:
    with _signals_stop():
        return input(question).strip() == "y"


def _list(accounts: Accounts) -> None:
    rows = [
        (found.username, found.role, found.email or "no email", "" if found.has_password else "no password")
        for found in accounts.entries()
    ]
    widths = [max((len(row[column]) for row in rows), default=0) for column in range(3)]
    for row in rows:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)) + ("  " + row[3] if row[3] else ""), flush=True)
    if not rows:
        print("There are no parent accounts. Add the first with dw-account add --role admin --password USERNAME.")


class _Failed(Exception):
    """The command did what it could, said why the rest was not done, and exits with status 1."""


def _mailer():
    """Return the Mailer for the SMTP_ settings, or why there is none. A setting that is wrong stops the command."""
    from policy.mail import OFF, Mailer, mail_settings

    settings = mail_settings(os.environ)
    if settings is None:
        return None, OFF
    return Mailer(settings), None


def _sign_in_address() -> str:
    """The sign-in screen at the first name in PARENT_NAMES, on POLICY_PORT."""
    from policy.mail import portal_address
    from policy.parent_tls import require_names
    from policy.selection import published_port

    return portal_address(require_names(os.environ.get("PARENT_NAMES"))[0], published_port(), "/parent/login")


def _household_now() -> datetime:
    """Now, in the household's timezone from the policy, or this machine's when the policy names none."""
    from policy.check import household_zone, machine_localtime
    from policy.hierarchy import load as load_hierarchy

    try:
        policy = load_hierarchy(Path(os.environ.get("POLICY_FILE", "/etc/daywarden/policy.yaml")))
        zone, _source = household_zone(None if policy is None else policy.timezone, machine_localtime())
    except Exception:  # A broken policy still gets the notice, in this machine's time.
        return datetime.now().astimezone()
    return datetime.now(zone)


def _add(accounts: Accounts, found: argparse.Namespace) -> None:
    username, role, email = found.username, found.role, found.email
    accounts.check_add(username, role, email, found.password)
    mailer, off = _mailer() if email is not None and not found.password else (None, None)
    password = read_new_password("Nothing was added.") if found.password else None
    accounts.add(username, role, email, password)
    address = f"with the email address {email}" if email else "with no email address"
    print(f"{username} is added, as {_article(role)} {role}, {address}.", flush=True)
    if password is not None:
        return
    if email is None:
        print(f"{username} has no password yet. dw-account update --password {username} sets one.", flush=True)
        return
    from policy.mail import MailError

    why = off
    if mailer is not None:
        try:
            mailer.welcome(email, username, role, _sign_in_address())
        except MailError as error:
            why = str(error)
    if why is None:
        print(f"A welcome email was sent to {email}. It tells {username} to choose a password with Forgot password.", flush=True)
        return
    print(f"No welcome email was sent to {email}. {why}", file=sys.stderr, flush=True)
    raise _Failed(f"{username} has no password yet. dw-account update --password {username} sets one now.")


def _test_email(accounts: Accounts, found: argparse.Namespace) -> None:
    from policy.mail import MailError

    username = found.username
    entry = accounts.entry(username)
    if entry is None:
        raise AccountError(f"There is no parent account {username}. Nothing was sent.")
    mailer, off = _mailer()
    if mailer is None:
        raise _Failed(f"{off} Nothing was sent.")
    if entry.email is None:
        raise _Failed(f"{username} has no email address. Add one with dw-account update --email ADDRESS {username}.")
    try:
        mailer.test(entry.email, username)
    except MailError as error:
        raise _Failed(f"The test email to {entry.email} was not sent. {error}") from None
    print(f"The mail server accepted a test email to {entry.email}.", flush=True)


def _update(accounts: Accounts, found: argparse.Namespace) -> None:
    username = found.username
    accounts.check_update(username, found.role, found.email)
    password = read_new_password("Nothing was changed.") if found.password else None
    accounts.update(username, role=found.role, email=found.email, no_email=found.no_email, password=password)
    if found.role is not None:
        print(f"{username} is now {_article(found.role)} {found.role}. Its sessions have ended.", flush=True)
    if found.email is not None:
        print(f"{username}'s email address is now {found.email}.", flush=True)
    if found.no_email:
        print(f"{username} has no email address now.", flush=True)
    if password is not None:
        print(f"{username}'s password is set. Its sessions and the MCP connections it approved have ended.", flush=True)
        _notify_set(accounts, username)


def _notify_set(accounts: Accounts, username: str) -> None:
    """Email the account that its password was set. A failure is said, and the password stays set."""
    from policy.mail import SET_ON_HOST, MailError, moment

    entry = accounts.entry(username)
    if entry is None or entry.email is None:
        return
    try:
        mailer, _off = _mailer()
    except SystemExit as stopped:
        print(f"The password-changed email was not sent: {stopped}", file=sys.stderr, flush=True)
        return
    if mailer is None:
        return
    try:
        mailer.changed(entry.email, username, SET_ON_HOST, moment(_household_now()))
    except MailError as error:
        print(f"The password-changed email to {entry.email} was not sent. {error}", file=sys.stderr, flush=True)
        return
    print(f"{username} was emailed that the password changed.", flush=True)


def _remove(accounts: Accounts, found: argparse.Namespace) -> None:
    username = found.username
    accounts.check_remove(username)
    if not found.yes:
        if not sys.stdin.isatty():
            raise AccountError(f"There is no terminal to ask in, so {username} was not removed. Give --yes to remove it.")
        if not _confirm(f"Remove {username}? This cannot be undone. [y/N] "):
            print(f"{username} was not removed.", flush=True)
            return
    accounts.remove(username)
    print(f"{username} is removed. Its sessions and the MCP connections it approved have ended.", flush=True)


def main(argv: list[str] | None = None) -> None:
    """Run one dw-account subcommand."""
    found = _command_line(list(sys.argv[1:] if argv is None else argv))
    if found.action == "help":
        print(HELP, flush=True)
        return
    # Imported here so a sign-in check does not load the policy loader.
    from policy.store import PolicyStore

    database = Path(os.environ.get("POLICY_DB", "/var/lib/daywarden/policy.sqlite3"))
    database.parent.mkdir(parents=True, exist_ok=True)
    store = PolicyStore(database)
    try:
        accounts = Accounts(store.connection)
        {"list": _list, "add": _add, "update": _update, "remove": _remove, "test-email": _test_email}[found.action](
            accounts, *([] if found.action == "list" else [found])
        )
    except (AccountError, _Failed) as error:
        raise SystemExit(str(error)) from None
    except (KeyboardInterrupt, EOFError, _Stopped) as stopped:
        why = str(stopped) if isinstance(stopped, _Stopped) else "Stopped."
        try:
            print(f"\n{why} Nothing was changed.", file=sys.stderr, flush=True)
        except OSError:
            pass
        raise SystemExit(130) from None
    finally:
        store.close()


if __name__ == "__main__":
    main()
