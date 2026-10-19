"""SQLite storage for the household policy."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path

from policy.clients import Client

SCHEMA_VERSION = 1

_SCHEMA = """
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
"""


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
        if version == 0:
            self.connection.executescript(
                "BEGIN;" + _SCHEMA + f"PRAGMA user_version = {SCHEMA_VERSION}; COMMIT;"
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

    def save_household(
        self,
        timezone: str | None,
        clients: Sequence[tuple[str, str, Sequence[str]]],
    ) -> None:
        """Replace the timezone and the client list in one transaction.

        clients holds (name, address, ips). A client keeps its id while its
        name stays the same, so later per-client records stay attached.
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
