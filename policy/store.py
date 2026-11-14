"""The household SQLite database.

``PolicyStore`` opens the connection the decisions service, the observations
service, and the command-line tools share, and sets its pragmas. Each module
that keeps data there creates its own tables on that connection with
``CREATE TABLE IF NOT EXISTS``: parent accounts in ``policy.accounts``, task
attempts in ``policy.tasks``, the usage ledger in ``policy.usage``, the usage
graph's presets in ``policy.usage_graph``, and the pages a child was sent away
from in ``policy.returns``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


class PolicyStore:
    def __init__(self, path: str | Path, *, check_same_thread: bool = True) -> None:
        self.connection = sqlite3.connect(path, check_same_thread=check_same_thread)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 5000")
        if str(path) != ":memory:":
            self.connection.execute("PRAGMA journal_mode = WAL").fetchone()

    def __enter__(self) -> PolicyStore:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()
