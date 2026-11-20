"""What the MCP authorization server keeps in the policy database.

- A **client** is an agent that registered, by Dynamic Client Registration or
  by a Client ID Metadata Document. One that is never approved is removed
  after 24 hours.
- A **request** is an authorization request waiting on the consent page.
- A **code** is what Approve sends back to the agent. It works once, within
  a minute. It is kept after use, so a second use can end the connection it
  made.
- A **connection** is one approval of one agent. It holds the current
  refresh token, and lasts until it is revoked or lapses: ``refresh_idle``
  after its last use, or ``refresh_lifetime`` after approval, whichever is
  earlier. Each refresh replaces the refresh token, and the old one is kept,
  so using it again ends the connection.
- An **access token** belongs to a connection and lasts ``access_token``.

Tokens and codes are 256 bits from the operating system's random source. Only
their SHA-256 is stored, as with session keys.

The activity log holds each write, each refused call, and each connection
approved, revoked, or lapsed.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from policy.mcp_settings import McpSettings

CODE_LIFETIME = timedelta(minutes=1)
REQUEST_LIFETIME = timedelta(minutes=30)
UNAPPROVED_CLIENT_LIFETIME = timedelta(hours=24)

APPROVED, REVOKED, LAPSED, REFUSED, DONE, FAILED, CHECKED = "approved", "revoked", "lapsed", "refused", "done", "failed", "checked"

_TABLES = """
CREATE TABLE IF NOT EXISTS mcp_clients (
    client_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    redirect_uris TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mcp_requests (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    state TEXT,
    code_challenge TEXT NOT NULL,
    resource TEXT NOT NULL,
    problem TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mcp_codes (
    code_hash TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    client_name TEXT NOT NULL,
    account_id INTEGER NOT NULL,
    redirect_uri TEXT NOT NULL,
    code_challenge TEXT NOT NULL,
    resource TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    connection_id INTEGER
);
CREATE TABLE IF NOT EXISTS mcp_connections (
    id INTEGER PRIMARY KEY,
    client_id TEXT NOT NULL,
    client_name TEXT NOT NULL,
    account_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    last_used_at TEXT NOT NULL,
    refresh_hash TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS mcp_spent_refresh (
    refresh_hash TEXT PRIMARY KEY,
    connection_id INTEGER NOT NULL REFERENCES mcp_connections(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS mcp_access (
    token_hash TEXT PRIMARY KEY,
    connection_id INTEGER NOT NULL REFERENCES mcp_connections(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mcp_activity (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    agent TEXT NOT NULL,
    parent TEXT NOT NULL,
    tool TEXT NOT NULL,
    target TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reasons TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Client:
    client_id: str
    name: str
    redirect_uris: tuple[str, ...]


@dataclass(frozen=True)
class Request:
    id: str
    client_id: str
    redirect_uri: str
    state: str | None
    code_challenge: str
    resource: str
    problem: str | None


# A connection's columns, with the role its approving account has now, read again each time (S043).
# An account that is gone counts as a reviewer, the narrower role.
_COLUMNS = (
    "id, client_id, client_name, username, approved_at, last_used_at, "
    "COALESCE((SELECT role FROM parent_accounts WHERE parent_accounts.id = mcp_connections.account_id), 'reviewer')"
)


@dataclass(frozen=True)
class Connection:
    id: int
    client_id: str
    client_name: str
    username: str
    approved_at: datetime
    last_used_at: datetime
    # The approving account's role when the connection was read.
    role: str = "admin"

    def lapses_at(self, settings: McpSettings) -> datetime:
        return min(
            self.last_used_at + timedelta(seconds=settings.refresh_idle),
            self.approved_at + timedelta(seconds=settings.refresh_lifetime),
        )


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: str
    expires_in: int


class Refused(Exception):
    """A token request is refused. ``error`` is the OAuth error code."""

    def __init__(self, error: str, description: str) -> None:
        super().__init__(description)
        self.error = error
        self.description = description


def new_secret() -> str:
    return secrets.token_bytes(32).hex()


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("ascii", "replace")).hexdigest()


class McpStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(_TABLES)

    # Clients

    def register(self, name: str, redirect_uris: tuple[str, ...], now: datetime, client_id: str | None = None) -> Client:
        """Store a client. A Client ID Metadata Document's client is stored again with what its document says now."""
        self.forget_unapproved(now)
        client_id = client_id or secrets.token_hex(16)
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO mcp_clients (client_id, name, redirect_uris, registered_at) VALUES (?, ?, ?, ?)
                ON CONFLICT(client_id) DO UPDATE SET name = excluded.name, redirect_uris = excluded.redirect_uris
                """,
                (client_id, name, json.dumps(list(redirect_uris)), _text(now)),
            )
        return Client(client_id, name, redirect_uris)

    def client(self, client_id: str) -> Client | None:
        row = self.connection.execute(
            "SELECT client_id, name, redirect_uris FROM mcp_clients WHERE client_id = ?", (client_id,)
        ).fetchone()
        if row is None:
            return None
        return Client(row[0], row[1], tuple(json.loads(row[2])))

    def forget_unapproved(self, now: datetime) -> None:
        cutoff = _text(now - UNAPPROVED_CLIENT_LIFETIME)
        with self.connection:
            self.connection.execute("DELETE FROM mcp_clients WHERE approved = 0 AND registered_at < ?", (cutoff,))
            self.connection.execute("DELETE FROM mcp_requests WHERE created_at < ?", (_text(now - REQUEST_LIFETIME),))

    # Authorization requests

    def add_request(
        self, client_id: str, redirect_uri: str, state: str | None, code_challenge: str, resource: str, problem: str | None, now: datetime
    ) -> str:
        self.forget_unapproved(now)
        request_id = secrets.token_hex(16)
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO mcp_requests (id, client_id, redirect_uri, state, code_challenge, resource, problem, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (request_id, client_id, redirect_uri, state, code_challenge, resource, problem, _text(now)),
            )
        return request_id

    def request(self, request_id: str, now: datetime) -> Request | None:
        self.forget_unapproved(now)
        row = self.connection.execute(
            "SELECT id, client_id, redirect_uri, state, code_challenge, resource, problem FROM mcp_requests WHERE id = ?",
            (request_id,),
        ).fetchone()
        return None if row is None else Request(*row)

    def drop_request(self, request_id: str) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM mcp_requests WHERE id = ?", (request_id,))

    # Codes and connections

    def approve(self, request: Request, client: Client, account_id: int, now: datetime) -> str:
        """Approve a request: return a code for the agent, and mark its client approved."""
        code = new_secret()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO mcp_codes
                    (code_hash, client_id, client_name, account_id, redirect_uri, code_challenge, resource, approved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (digest(code), client.client_id, client.name, account_id, request.redirect_uri, request.code_challenge, request.resource, _text(now)),
            )
            self.connection.execute("UPDATE mcp_clients SET approved = 1 WHERE client_id = ?", (client.client_id,))
            self.connection.execute("DELETE FROM mcp_requests WHERE id = ?", (request.id,))
            self.connection.execute(
                "DELETE FROM mcp_codes WHERE approved_at < ? AND connection_id IS NULL", (_text(now - timedelta(hours=1)),)
            )
        return code

    def exchange(
        self, code: str, client_id: str, redirect_uri: str, verifier: str, resource: str | None, settings: McpSettings, now: datetime
    ) -> Tokens:
        """Turn a code into a connection and its first tokens.

        A code used a second time ends the connection it made.
        """
        row = self.connection.execute(
            """
            SELECT code_hash, client_id, client_name, account_id, redirect_uri, code_challenge, resource, approved_at, connection_id
            FROM mcp_codes WHERE code_hash = ?
            """,
            (digest(code),),
        ).fetchone()
        if row is None:
            raise Refused("invalid_grant", "That code is not known.")
        code_hash, owner, name, account_id, uri, challenge, bound, approved_at, made = row
        if made is not None:
            ended = self.connection_by_id(made)
            if ended is not None:
                self.end(ended, now, REVOKED, "the code that made it was used a second time")
            raise Refused("invalid_grant", "That code has already been used.")
        if now - _parse(approved_at) > CODE_LIFETIME:
            raise Refused("invalid_grant", "That code has expired.")
        if client_id != owner:
            raise Refused("invalid_grant", "That code was issued to another client.")
        if redirect_uri != uri:
            raise Refused("invalid_grant", "redirect_uri is not the one the code was issued for.")
        if resource is not None and resource != bound:
            raise Refused("invalid_target", "resource is not the one the code was issued for.")
        if not _pkce_matches(verifier, challenge):
            raise Refused("invalid_grant", "code_verifier does not match the code_challenge.")
        username = self._username(account_id)
        if username is None:
            raise Refused("invalid_grant", "The parent who approved this no longer has an account.")
        refresh = new_secret()
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO mcp_connections (client_id, client_name, account_id, username, approved_at, last_used_at, refresh_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (owner, name, account_id, username, approved_at, _text(now), digest(refresh)),
            )
            connection_id = cursor.lastrowid
            self.connection.execute("UPDATE mcp_codes SET connection_id = ? WHERE code_hash = ?", (connection_id, code_hash))
        made_connection = self.connection_by_id(connection_id)
        assert made_connection is not None
        self.log(made_connection.client_name, username, "", "", APPROVED, [], now)
        return Tokens(self._access(connection_id, settings, now), refresh, settings.access_token)

    def refresh(self, token: str, client_id: str, settings: McpSettings, now: datetime) -> Tokens:
        """Return new tokens for a refresh token, and replace it. An old one used again ends the connection."""
        self.sweep(settings, now)
        hashed = digest(token)
        spent = self.connection.execute(
            "SELECT connection_id FROM mcp_spent_refresh WHERE refresh_hash = ?", (hashed,)
        ).fetchone()
        if spent is not None:
            found = self.connection_by_id(spent[0])
            if found is not None:
                self.end(found, now, REVOKED, "an old refresh token was used again")
            raise Refused("invalid_grant", "That refresh token has already been used.")
        found = self._connection_where("refresh_hash = ?", (hashed,))
        if found is None:
            raise Refused("invalid_grant", "That refresh token is not known. Approve the agent again.")
        if found.client_id != client_id:
            raise Refused("invalid_grant", "That refresh token was issued to another client.")
        fresh = new_secret()
        with self.connection:
            self.connection.execute(
                "INSERT INTO mcp_spent_refresh (refresh_hash, connection_id) VALUES (?, ?)", (hashed, found.id)
            )
            self.connection.execute(
                "UPDATE mcp_connections SET refresh_hash = ?, last_used_at = ? WHERE id = ?",
                (digest(fresh), _text(now), found.id),
            )
        return Tokens(self._access(found.id, settings, now), fresh, settings.access_token)

    def accept(self, token: str, settings: McpSettings, now: datetime) -> Connection | None:
        """Return the connection an access token belongs to, and note it as used, or None."""
        self.sweep(settings, now)
        row = self.connection.execute(
            "SELECT connection_id, expires_at FROM mcp_access WHERE token_hash = ?", (digest(token),)
        ).fetchone()
        if row is None:
            return None
        if _parse(row[1]) <= now:
            with self.connection:
                self.connection.execute("DELETE FROM mcp_access WHERE token_hash = ?", (digest(token),))
            return None
        with self.connection:
            self.connection.execute("UPDATE mcp_connections SET last_used_at = ? WHERE id = ?", (_text(now), row[0]))
        return self.connection_by_id(row[0])

    def revoke_token(self, token: str, now: datetime) -> None:
        """RFC 7009: a refresh token ends its connection, an access token ends itself. Anything else does nothing."""
        hashed = digest(token)
        found = self._connection_where("refresh_hash = ?", (hashed,))
        if found is not None:
            self.end(found, now, REVOKED, "the agent revoked it")
            return
        with self.connection:
            self.connection.execute("DELETE FROM mcp_access WHERE token_hash = ?", (hashed,))

    def connections(self, settings: McpSettings | None, now: datetime) -> list[Connection]:
        if settings is not None:
            self.sweep(settings, now)
        rows = self.connection.execute(
            f"SELECT {_COLUMNS} FROM mcp_connections ORDER BY approved_at DESC, id DESC"
        ).fetchall()
        return [_connection(row) for row in rows]

    def connection_by_id(self, connection_id: int) -> Connection | None:
        return self._connection_where("id = ?", (connection_id,))

    def end(self, found: Connection, now: datetime, outcome: str, reason: str) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM mcp_connections WHERE id = ?", (found.id,))
        self.log(found.client_name, found.username, "", "", outcome, [reason] if reason else [], now)

    def end_all(self, now: datetime, reason: str) -> None:
        for found in self.connections(None, now):
            self.end(found, now, REVOKED, reason)

    def end_for_account(self, account_id: int, now: datetime, reason: str) -> None:
        rows = self.connection.execute(
            f"SELECT {_COLUMNS} FROM mcp_connections WHERE account_id = ?",
            (account_id,),
        ).fetchall()
        for row in rows:
            self.end(_connection(row), now, REVOKED, reason)

    def sweep(self, settings: McpSettings, now: datetime) -> None:
        """End each connection that has lapsed, logged at the moment it lapsed."""
        for found in self.connections(None, now):
            lapsed = found.lapses_at(settings)
            if lapsed <= now:
                reason = (
                    f"unused for {_days(settings.refresh_idle)}"
                    if lapsed == found.last_used_at + timedelta(seconds=settings.refresh_idle)
                    else f"{_days(settings.refresh_lifetime)} after it was approved"
                )
                self.end(found, lapsed, LAPSED, reason)
        with self.connection:
            self.connection.execute("DELETE FROM mcp_access WHERE expires_at <= ?", (_text(now),))

    # Activity

    def log(self, agent: str, parent: str, tool: str, target: str, outcome: str, reasons: list[str], at: datetime) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO mcp_activity (at, agent, parent, tool, target, outcome, reasons) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (_text(at), agent, parent, tool, target, outcome, json.dumps(reasons)),
            )

    def activity(self, keep_days: int, now: datetime) -> list[dict]:
        """Return the activity log, newest first, after removing entries older than ``keep_days``."""
        with self.connection:
            self.connection.execute("DELETE FROM mcp_activity WHERE at < ?", (_text(now - timedelta(days=keep_days)),))
        rows = self.connection.execute(
            "SELECT at, agent, parent, tool, target, outcome, reasons FROM mcp_activity ORDER BY at DESC, id DESC"
        ).fetchall()
        return [
            {"at": _parse(at), "agent": agent, "parent": parent, "tool": tool, "target": target, "outcome": outcome, "reasons": json.loads(reasons)}
            for at, agent, parent, tool, target, outcome, reasons in rows
        ]

    # Inside

    def _access(self, connection_id: int, settings: McpSettings, now: datetime) -> str:
        token = new_secret()
        with self.connection:
            self.connection.execute(
                "INSERT INTO mcp_access (token_hash, connection_id, expires_at) VALUES (?, ?, ?)",
                (digest(token), connection_id, _text(now + timedelta(seconds=settings.access_token))),
            )
        return token

    def _connection_where(self, clause: str, params: tuple) -> Connection | None:
        row = self.connection.execute(
            f"SELECT {_COLUMNS} FROM mcp_connections WHERE {clause}",
            params,
        ).fetchone()
        return None if row is None else _connection(row)

    def _username(self, account_id: int) -> str | None:
        row = self.connection.execute("SELECT username FROM parent_accounts WHERE id = ?", (account_id,)).fetchone()
        return None if row is None else row[0]


def _pkce_matches(verifier: object, challenge: str) -> bool:
    import base64

    if not isinstance(verifier, str) or not 43 <= len(verifier) <= 128:
        return False
    made = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii", "replace")).digest()).decode().rstrip("=")
    return secrets.compare_digest(made, challenge)


def _connection(row: tuple) -> Connection:
    return Connection(row[0], row[1], row[2], row[3], _parse(row[4]), _parse(row[5]), row[6])


def _text(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _days(seconds: int) -> str:
    from policy.mcp_settings import duration_text

    return duration_text(seconds)
