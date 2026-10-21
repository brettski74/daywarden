"""SQLite storage for the household policy and the usage ledger.

A usage bucket is one stretch of time, for one client and one site group,
that contained traffic. It keeps the length configured when it was opened.
S002.1 writes these rows from observations. Until then a test or an
administrator can write them. quota_remaining reads the ones that have ended.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from pathlib import Path

from policy.clients import Client
from policy.groups import SiteGroup
from policy.rules import Action, Rule, TaskRequirement, TimeWindow

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
    # days is NULL when the window applies every day, otherwise weekday numbers.
    """
    CREATE TABLE rules (
        id INTEGER PRIMARY KEY,
        group_id INTEGER NOT NULL REFERENCES site_groups(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        condition TEXT NOT NULL,
        UNIQUE (group_id, position)
    );
    CREATE TABLE rule_windows (
        rule_id INTEGER NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        start TEXT NOT NULL,
        end TEXT NOT NULL,
        days TEXT,
        PRIMARY KEY (rule_id, position)
    );
    CREATE TABLE rule_actions (
        rule_id INTEGER NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
        branch TEXT NOT NULL,
        kind TEXT NOT NULL,
        message TEXT,
        location TEXT,
        PRIMARY KEY (rule_id, branch)
    );
    """,
    # required is the tasks_complete count. A weekday row replaces it for that day.
    # Completions are successes for one client on one household-local date.
    """
    ALTER TABLE rules ADD COLUMN required INTEGER;
    CREATE TABLE rule_weekday_counts (
        rule_id INTEGER NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
        weekday INTEGER NOT NULL,
        required INTEGER NOT NULL,
        PRIMARY KEY (rule_id, weekday)
    );
    CREATE TABLE task_completions (
        client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
        day TEXT NOT NULL,
        completions INTEGER NOT NULL,
        PRIMARY KEY (client_id, day)
    );
    """,
    # quota_seconds is the group's daily duration, NULL when it has no quota.
    # It is never a count of buckets. A usage bucket keeps the length it was
    # opened with. A later observation in that same bucket adds bytes and
    # does not insert another row. S002.1 is the writer; this story reads.
    """
    ALTER TABLE site_groups ADD COLUMN quota_seconds INTEGER;
    CREATE TABLE usage_buckets (
        client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
        group_id INTEGER NOT NULL REFERENCES site_groups(id) ON DELETE CASCADE,
        day TEXT NOT NULL,
        started_at TEXT NOT NULL,
        length_seconds INTEGER NOT NULL,
        byte_count INTEGER NOT NULL,
        PRIMARY KEY (client_id, group_id, started_at)
    );
    """,
)
SCHEMA_VERSION = len(_MIGRATIONS)
DEFAULT_BUCKET_SECONDS = 300


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

    def revision_task(self) -> str | None:
        row = self.connection.execute(
            "SELECT value FROM settings WHERE key = 'revision_task'"
        ).fetchone()
        return row[0] if row and row[0] else None

    def groups(self) -> list[SiteGroup]:
        patterns: dict[int, list[str]] = {}
        for group_id, pattern in self.connection.execute(
            "SELECT group_id, pattern FROM site_group_patterns ORDER BY group_id, position"
        ):
            patterns.setdefault(group_id, []).append(pattern)
        rules = self._rules()
        return [
            SiteGroup(
                name,
                priority,
                tuple(patterns.get(group_id, ())),
                bool(is_default),
                tuple(rules.get(group_id, ())),
                None if quota_seconds is None else int(quota_seconds),
            )
            for group_id, name, priority, is_default, quota_seconds in self.connection.execute(
                "SELECT id, name, priority, is_default, quota_seconds FROM site_groups ORDER BY id"
            )
        ]

    def _rules(self) -> dict[int, list[Rule]]:
        actions: dict[int, dict[str, Action]] = {}
        for rule_id, branch, kind, message, location in self.connection.execute(
            "SELECT rule_id, branch, kind, message, location FROM rule_actions"
        ):
            actions.setdefault(rule_id, {})[branch] = Action(kind, message or "", location or "")
        windows: dict[int, list[TimeWindow]] = {}
        for rule_id, start, end, days in self.connection.execute(
            "SELECT rule_id, start, end, days FROM rule_windows ORDER BY rule_id, position"
        ):
            weekdays = None if days is None else frozenset(int(day) for day in days.split(","))
            windows.setdefault(rule_id, []).append(
                TimeWindow(time.fromisoformat(start), time.fromisoformat(end), weekdays)
            )
        overrides: dict[int, list[tuple[int, int]]] = {}
        for rule_id, weekday, required in self.connection.execute(
            "SELECT rule_id, weekday, required FROM rule_weekday_counts ORDER BY rule_id, weekday"
        ):
            overrides.setdefault(rule_id, []).append((int(weekday), int(required)))
        by_group: dict[int, list[Rule]] = {}
        for rule_id, group_id, condition, required in self.connection.execute(
            "SELECT id, group_id, condition, required FROM rules ORDER BY group_id, position"
        ):
            branches = actions[rule_id]
            requirement = None
            if condition == "tasks_complete" and required is not None:
                requirement = TaskRequirement(int(required), tuple(overrides.get(rule_id, ())))
            by_group.setdefault(group_id, []).append(
                Rule(
                    condition,
                    branches["when_true"],
                    branches["when_false"],
                    tuple(windows.get(rule_id, ())),
                    requirement,
                )
            )
        return by_group

    def task_completions(self, client_id: int, day: date) -> int:
        """Return the stored revision successes for this client on this local date.

        A day with no row is zero. The date is the household-local date, not UTC.
        """
        row = self.connection.execute(
            "SELECT completions FROM task_completions WHERE client_id = ? AND day = ?",
            (client_id, _day(day)),
        ).fetchone()
        return int(row[0]) if row else 0

    def set_task_completions(self, client_id: int, day: date, count: int) -> None:
        """Store how many revision tasks this client has finished on this local date.

        This is the count tasks_complete reads. A test or an administrator writes
        it until real completions do. The count replaces whatever was stored.
        """
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("a completion count is a whole number, zero or more")
        stored_day = _day(day)
        with self.connection:
            try:
                self.connection.execute(
                    "INSERT INTO task_completions (client_id, day, completions) VALUES (?, ?, ?) "
                    "ON CONFLICT (client_id, day) DO UPDATE SET completions = excluded.completions",
                    (client_id, stored_day, count),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"client {client_id} is not in the household") from exc

    def bucket_length(self) -> int:
        """Return the length, in seconds, used when a new bucket is opened.

        Five minutes is the length when the household has not set one.
        """
        row = self.connection.execute(
            "SELECT value FROM settings WHERE key = 'bucket_length'"
        ).fetchone()
        if row is None or row[0] in (None, ""):
            return DEFAULT_BUCKET_SECONDS
        return int(row[0])

    def mark_bucket(
        self,
        client_id: int,
        group: str,
        started_at: datetime,
        *,
        length_seconds: int | None = None,
        byte_count: int = 0,
    ) -> None:
        """Record that this bucket contained traffic.

        started_at is the household-local start. An aware value is already in
        that zone; its offset is dropped, not converted. The length is the
        one configured now when length_seconds is omitted. A bucket that is
        already stored keeps its length. byte_count is added to the stored
        total, and a second observation does not create a second row.
        """
        if length_seconds is None:
            length_seconds = self.bucket_length()
        length_seconds = _one_or_more(length_seconds, "a bucket length")
        byte_count = _zero_or_more(byte_count, "a byte count")
        start = _wall(started_at)
        group_id = self._group_id(group)
        with self.connection:
            try:
                self.connection.execute(
                    "INSERT INTO usage_buckets ("
                    "client_id, group_id, day, started_at, length_seconds, byte_count"
                    ") VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (client_id, group_id, started_at) DO UPDATE SET "
                    "byte_count = usage_buckets.byte_count + excluded.byte_count",
                    (
                        client_id,
                        group_id,
                        _day(start.date()),
                        start.isoformat(timespec="seconds"),
                        length_seconds,
                        byte_count,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"client {client_id} is not in the household") from exc

    def consumed_seconds(self, client_id: int, group: str, at: datetime) -> int:
        """Return today's ended usage, in seconds, for this client and group.

        A bucket counts when at is at or after the bucket's end. at is
        household-local. Buckets from another day, another client, or another
        group are left out, and so is a bucket that is still open.
        """
        wall = _wall(at)
        group_id = self._group_id(group)
        total = 0
        for started_at, length in self.connection.execute(
            "SELECT started_at, length_seconds FROM usage_buckets "
            "WHERE client_id = ? AND group_id = ? AND day = ?",
            (client_id, group_id, _day(wall.date())),
        ):
            start = datetime.fromisoformat(started_at)
            if start + timedelta(seconds=int(length)) <= wall:
                total += int(length)
        return total

    def _group_id(self, name: str) -> int:
        row = self.connection.execute(
            "SELECT id FROM site_groups WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            raise ValueError(f"group {name!r} is not in the household")
        return int(row[0])

    def save_household(
        self,
        timezone: str | None,
        clients: Sequence[tuple[str, str, Sequence[str]]],
        groups: Sequence[SiteGroup],
        revision_task: str | None = None,
        bucket_length: int = DEFAULT_BUCKET_SECONDS,
    ) -> None:
        """Replace the timezone, the client list and the site groups in one transaction.

        clients holds (name, address, ips). A client or a group keeps its id
        while its name stays the same, so later records stay attached. Rules are
        rewritten each load. A client's revision count is not in the file, and
        neither are usage buckets, so a reload leaves both in place. The quota
        and the bucket length do come from the file. Changing the bucket length
        does not resize a quota or a bucket that is already stored.
        """
        length = _one_or_more(bucket_length, "the bucket length")
        with self.connection:
            self.connection.executemany(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (
                    ("timezone", timezone),
                    ("revision_task", revision_task),
                    ("bucket_length", str(length)),
                ),
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

            self.connection.execute("DELETE FROM rules")
            self.connection.execute("DELETE FROM site_group_patterns")
            keep = {group.name for group in groups}
            for (name,) in self.connection.execute("SELECT name FROM site_groups").fetchall():
                if name not in keep:
                    self.connection.execute("DELETE FROM site_groups WHERE name = ?", (name,))
            for group in groups:
                self.connection.execute(
                    "INSERT INTO site_groups (name, priority, is_default, quota_seconds) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT (name) DO UPDATE SET "
                    "priority = excluded.priority, is_default = excluded.is_default, "
                    "quota_seconds = excluded.quota_seconds",
                    (group.name, group.priority, int(group.default), group.quota),
                )
                (group_id,) = self.connection.execute(
                    "SELECT id FROM site_groups WHERE name = ?", (group.name,)
                ).fetchone()
                self.connection.executemany(
                    "INSERT INTO site_group_patterns (group_id, position, pattern) VALUES (?, ?, ?)",
                    [(group_id, position, pattern) for position, pattern in enumerate(group.patterns)],
                )
                self._insert_rules(group_id, group)

    def _insert_rules(self, group_id: int, group: SiteGroup) -> None:
        for position, rule in enumerate(group.rules):
            cursor = self.connection.execute(
                "INSERT INTO rules (group_id, position, condition, required) VALUES (?, ?, ?, ?)",
                (
                    group_id,
                    position,
                    rule.condition,
                    None if rule.requirement is None else rule.requirement.required,
                ),
            )
            rule_id = cursor.lastrowid
            if rule.requirement is not None:
                self.connection.executemany(
                    "INSERT INTO rule_weekday_counts (rule_id, weekday, required) VALUES (?, ?, ?)",
                    [
                        (rule_id, weekday, count)
                        for weekday, count in rule.requirement.overrides
                    ],
                )
            self.connection.executemany(
                "INSERT INTO rule_actions (rule_id, branch, kind, message, location) VALUES (?, ?, ?, ?, ?)",
                [
                    (rule_id, branch, action.kind, action.message, action.location)
                    for branch, action in (
                        ("when_true", rule.when_true),
                        ("when_false", rule.when_false),
                    )
                ],
            )
            self.connection.executemany(
                "INSERT INTO rule_windows (rule_id, position, start, end, days) VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        rule_id,
                        position,
                        window.start.isoformat(),
                        window.end.isoformat(),
                        None
                        if window.weekdays is None
                        else ",".join(str(day) for day in sorted(window.weekdays)),
                    )
                    for position, window in enumerate(rule.windows)
                ],
            )


def _day(day: date) -> str:
    if type(day) is not date:
        raise ValueError("day must be a date")
    return day.isoformat()


def _wall(moment: datetime) -> datetime:
    """Return household-local wall time to the second, without a timezone.

    An aware value is already household-local. The offset is dropped, not
    converted, so 00:30+11:00 stays 00:30 on that same local date.
    """
    if not isinstance(moment, datetime):
        raise ValueError("time must be a datetime")
    if moment.tzinfo is not None:
        moment = moment.replace(tzinfo=None)
    return moment.replace(microsecond=0)


def _one_or_more(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} is a whole number of seconds, one or more")
    return value


def _zero_or_more(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} is a whole number, zero or more")
    return value
