"""SQLite storage for the household policy."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path

from policy.clients import Client
from policy.groups import SiteGroup

# _MIGRATIONS[n] takes a database from schema version n to n + 1.
_MIGRATIONS = (
    """
    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    CREATE TABLE clients (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        address TEXT NOT NULL
    );
    CREATE TABLE client_ips (
        ip TEXT PRIMARY KEY,
        client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE
    );
    """,
    # Unique priorities and a single default are checked when the file is parsed.
    """
    CREATE TABLE site_groups (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        priority INTEGER NOT NULL,
        is_default INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE site_group_patterns (
        group_id INTEGER NOT NULL REFERENCES site_groups(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        pattern TEXT NOT NULL,
        PRIMARY KEY (group_id, position)
    );
    """,
)
SCHEMA_VERSION = len(_MIGRATIONS)


class PolicyStore:
    def __init__(self, path: str | Path) -> None:
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def __enter__(self) -> PolicyStore:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def _migrate(self) -> None:
        (version,) = self.connection.execute("PRAGMA user_version").fetchone()
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"policy database schema {version} is newer than this service ({SCHEMA_VERSION})"
            )
        if version < SCHEMA_VERSION:
            self.connection.executescript(
                "BEGIN;"
                + "".join(_MIGRATIONS[version:])
                + f"PRAGMA user_version = {SCHEMA_VERSION}; COMMIT;"
            )

    def timezone(self) -> str | None:
        row = self.connection.execute(
            "SELECT value FROM settings WHERE key = 'timezone'"
        ).fetchone()
        return row[0] if row else None

    def clients(self) -> list[Client]:
        rows = self.connection.execute(
            "SELECT id, name, address FROM clients ORDER BY id"
        ).fetchall()
        ips: dict[int, list[str]] = {}
        for ip, client_id in self.connection.execute(
            "SELECT ip, client_id FROM client_ips ORDER BY rowid"
        ):
            ips.setdefault(client_id, []).append(ip)
        return [
            Client(client_id, name, address, tuple(ips.get(client_id, ())))
            for client_id, name, address in rows
        ]

    def groups(self) -> list[SiteGroup]:
        patterns: dict[int, list[str]] = {}
        for group_id, pattern in self.connection.execute(
            "SELECT group_id, pattern FROM site_group_patterns ORDER BY group_id, position"
        ):
            patterns.setdefault(group_id, []).append(pattern)
        return [
            SiteGroup(name, priority, tuple(patterns.get(group_id, ())), bool(is_default))
            for group_id, name, priority, is_default in self.connection.execute(
                "SELECT id, name, priority, is_default FROM site_groups ORDER BY id"
            )
        ]

    def save_household(
        self,
        timezone: str | None,
        clients: Sequence[tuple[str, str, Sequence[str]]],
        groups: Sequence[SiteGroup],
    ) -> None:
        """Replace the timezone, the client list and the site groups in one transaction.

        clients holds (name, address, ips). A client or a group keeps its id
        while its name stays the same, so later records stay attached.
        """
        with self.connection:
            self.connection.execute(
                "INSERT INTO settings (key, value) VALUES ('timezone', ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (timezone,),
            )
            self.connection.execute("DELETE FROM client_ips")
            keep = {name for name, _address, _ips in clients}
            for (name,) in self.connection.execute("SELECT name FROM clients").fetchall():
                if name not in keep:
                    self.connection.execute("DELETE FROM clients WHERE name = ?", (name,))
            for name, address, ips in clients:
                self.connection.execute(
                    "INSERT INTO clients (name, address) VALUES (?, ?) "
                    "ON CONFLICT (name) DO UPDATE SET address = excluded.address",
                    (name, address),
                )
                (client_id,) = self.connection.execute(
                    "SELECT id FROM clients WHERE name = ?", (name,)
                ).fetchone()
                self.connection.executemany(
                    "INSERT INTO client_ips (ip, client_id) VALUES (?, ?)",
                    [(ip, client_id) for ip in ips],
                )

            self.connection.execute("DELETE FROM site_group_patterns")
            keep = {group.name for group in groups}
            for (name,) in self.connection.execute("SELECT name FROM site_groups").fetchall():
                if name not in keep:
                    self.connection.execute("DELETE FROM site_groups WHERE name = ?", (name,))
            for group in groups:
                self.connection.execute(
                    "INSERT INTO site_groups (name, priority, is_default) VALUES (?, ?, ?) "
                    "ON CONFLICT (name) DO UPDATE SET "
                    "priority = excluded.priority, is_default = excluded.is_default",
                    (group.name, group.priority, int(group.default)),
                )
                (group_id,) = self.connection.execute(
                    "SELECT id FROM site_groups WHERE name = ?", (group.name,)
                ).fetchone()
                self.connection.executemany(
                    "INSERT INTO site_group_patterns (group_id, position, pattern) VALUES (?, ?, ?)",
                    [(group_id, position, pattern) for position, pattern in enumerate(group.patterns)],
                )
