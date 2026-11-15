"""File an observation under its groups, and under each quota that accepts it.

The report is classified once. It is stored once for that client group and
site group, including the implicit group ``default``. Each quota's rule set
is then evaluated on that same observation. ``allow`` and ``continue`` accrue
to this client group's balance. ``deny`` and ``redirect`` do not. Falling off
the end of the set is a continue, so it accrues.

The same report is filed again under its host, beside the site group and
beside each quota, with its bytes down and up kept apart. A host gains a
bucket's length once however many reports it has in that bucket. The host
rows are kept for the policy's ``host_retention``. The site-group and quota
rows are kept for good.

Each judged request is also one row keyed by the proxy's flow id, written when
the decision is taken and updated as observation reports arrive. Those rows are
kept for the policy's ``request_retention``.

Time is the sum of ended buckets. Bytes include a bucket that has not ended.
A bucket keeps the length it was opened with. The length still divides the
local day, and a load that changes it shortens a bucket that is still open
without resizing a quota or rewriting a bucket that has already ended.
Yesterday and another client group do not count.

Grace is not added to either access check. A new transfer is still refused
at the limit. A live transfer is cut only when a clock deadline or a volume
ceiling recorded for that flow has been reached, and walking the access
rules again no longer allows it. A quota the report accrues to does not
cut the flow on its own. A limit of zero is not a budget. Any other answer
leaves the transfer running.

This is the store S008.4 reads.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from policy.buckets import place, require_day_length
from policy.clients import normalize_ip
from policy.clock import HouseholdClock
from policy.engine import (
    Assumption,
    Ledger,
    classify_client,
    classify_site,
    evaluate,
    judge_frozen,
)
from policy.hierarchy import DEFAULT_BUCKET_SECONDS, Policy
from policy.tasks import Task, ensure_attempts, pass_count

# A quota rule set is read before the access path turns a top-level continue
# into a deny. On a quota, allow and continue both mean the traffic belongs.
_ACCRUING = frozenset({"allow", "continue"})
_DEFAULT_PORTS = {"http": 80, "ws": 80, "https": 443, "wss": 443}
# The household-local start of the earliest host row, so a drill-down knows how far back hosts reach.
_HOSTS_SINCE = "hosts_since"
_REQUESTS_SINCE = "requests_since"
_HOST_LEDGERS = {"site": ("host_buckets", "site_group"), "quota": ("host_quota_buckets", "quota")}
_REQUEST_OUTCOMES = {"allow": "allowed", "deny": "denied", "redirect": "redirected"}
_ENDED_OUTCOMES = frozenset({"denied", "redirected", "cut"})


class UsageStore(Ledger):
    """Buckets for a classified pair, and the same buckets again per quota.

    The connection may be one ``PolicyStore`` already opened, so the decisions
    service and the observations service share the file. A store constructed
    from a path owns its connection and closes it.
    """

    def __init__(
        self,
        path: str | Path = ":memory:",
        *,
        connection: sqlite3.Connection | None = None,
        check_same_thread: bool = True,
    ) -> None:
        if connection is not None:
            self.connection = connection
            self._owns = False
        else:
            self.connection = sqlite3.connect(path, check_same_thread=check_same_thread)
            self._owns = True
            self.connection.execute("PRAGMA busy_timeout = 5000")
            if str(path) != ":memory:":
                self.connection.execute("PRAGMA journal_mode = WAL").fetchone()
        self._ensure_schema()

    def __enter__(self) -> UsageStore:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        if self._owns:
            self.connection.close()

    def stored_length(self) -> int | None:
        """Return the bucket length last installed, or None before any load."""
        raw = self._setting("bucket_length")
        return None if raw is None else int(raw)

    def bucket_regimes(self) -> list[dict[str, object]]:
        """Return the length history, oldest first.

        The first entry has no start. A later entry starts at the load that
        stored that length. Before any load, the grid is the five-minute default.
        """
        existing = self._regimes_raw()
        if existing:
            return existing
        stored = self.stored_length()
        if stored is not None:
            return [{"length": stored}]
        return [{"length": DEFAULT_BUCKET_SECONDS}]

    def ensure_length(self, length: int) -> None:
        """Install length when no load has recorded one yet.

        A length already stored is left alone, including its open buckets.
        The load that changes the length is ``install_length``.
        """
        if self.stored_length() is None:
            self.install_length(length, None)

    def install_length(self, length: int, loaded_at: datetime | None) -> None:
        """Store the household bucket length.

        The first load only establishes the midnight grid. The same length
        does not close anything. A different length shortens every bucket that
        has started and has not yet ended, on the site-group rows and on the
        quota rows, down to the seconds from the start to ``loaded_at``.
        A bucket that has already ended keeps the length it stored. ``loaded_at``
        is household-local, and it is required only when the length changes.
        """
        length = require_day_length(length)
        with self.connection:
            previous = self.stored_length()
            existing = self._regimes_raw()
            if previous is None:
                regimes: list[dict[str, object]] = [{"length": length}]
            elif previous == length:
                regimes = existing if existing is not None else [{"length": length}]
            else:
                if loaded_at is None:
                    raise ValueError(
                        "changing the bucket length needs the household-local time of the load"
                    )
                wall = _wall(loaded_at)
                self._end_open_buckets(wall)
                base = existing if existing is not None else [{"length": previous}]
                regimes = [*base, {"at": wall.isoformat(timespec="seconds"), "length": length}]
            self._put("bucket_length", str(length))
            self._put("bucket_regimes", json.dumps(regimes, separators=(",", ":")))

    def file_observation(
        self,
        client_group: str,
        site_group: str,
        moment: datetime,
        byte_count: int,
        quotas: Sequence[str],
        *,
        host: str | None = None,
        bytes_up: int = 0,
    ) -> None:
        """Store one report under the pair, and under each named quota.

        ``moment`` is household-local. The bucket is placed once and that same
        start, length, and byte count are written for the site group and for
        every quota. A second report in the bucket adds bytes and does not
        change the length or insert another row. The writes commit together.

        With ``host``, the same report is written again under the host, beside
        the site group and each quota, with ``bytes_up`` of the byte count sent
        up and the rest down. A second report for the host in the bucket adds
        its bytes and not its time.
        """
        byte_count = _zero_or_more(byte_count, "a byte count")
        bytes_up = _zero_or_more(bytes_up, "a byte count sent up")
        if bytes_up > byte_count:
            raise ValueError("the bytes sent up are part of the byte count")
        if host is not None and (not isinstance(host, str) or not host):
            raise ValueError("a host is a name")
        start, length = place(moment, self.bucket_regimes())
        names: list[str] = []
        for name in quotas:
            if not isinstance(name, str) or not name:
                raise ValueError("a quota name is required")
            if name not in names:
                names.append(name)
        with self.connection:
            self._mark("group_buckets", "site_group", client_group, site_group, start, length, byte_count)
            for name in names:
                self._mark("quota_buckets", "quota", client_group, name, start, length, byte_count)
            if host is None:
                return
            down = byte_count - bytes_up
            self._mark_host("host_buckets", "site_group", client_group, site_group, host, start, length, down, bytes_up)
            for name in names:
                self._mark_host("host_quota_buckets", "quota", client_group, name, host, start, length, down, bytes_up)
            self.connection.execute(
                "INSERT INTO hierarchy_settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE "
                "SET value = excluded.value WHERE excluded.value < hierarchy_settings.value",
                (_HOSTS_SINCE, start.isoformat(timespec="seconds")),
            )

    def host_rows_between(
        self, ledger: str, start: datetime, end: datetime
    ) -> list[tuple[str, str, str, datetime, int, int, int]]:
        """Return every host row of one ledger that starts at or after start and before end.

        ``ledger`` is ``site`` or ``quota``, as for ``rows_between``. Each item
        is the client group, the site group or quota, the host, the local
        start, the stored length, the bytes down, and the bytes up.
        """
        table, column = _HOST_LEDGERS[ledger]
        rows = self.connection.execute(
            f"SELECT client_group, {column}, host, started_at, length_seconds, bytes_down, bytes_up FROM {table} "
            "WHERE started_at >= ? AND started_at < ? ORDER BY started_at",
            (_wall(start).isoformat(timespec="seconds"), _wall(end).isoformat(timespec="seconds")),
        ).fetchall()
        return [
            (client_group, name, host, datetime.fromisoformat(started_at), int(length), int(down), int(up))
            for client_group, name, host, started_at, length, down, up in rows
        ]

    def hosts_since(self) -> datetime | None:
        """Return the household-local start of the earliest host row ever filed, or None before any."""
        raw = self._setting(_HOSTS_SINCE)
        return None if raw is None else datetime.fromisoformat(raw)

    def prune_hosts(self, before: datetime) -> int:
        """Delete every host row that starts before ``before``. Return how many went."""
        cutoff = _wall(before).isoformat(timespec="seconds")
        removed = 0
        with self.connection:
            for table, _column in _HOST_LEDGERS.values():
                removed += self.connection.execute(f"DELETE FROM {table} WHERE started_at < ?", (cutoff,)).rowcount
        return removed

    def record_request(
        self,
        flow_id: str,
        *,
        started_at: datetime,
        client_ip: str,
        client_group: str,
        site_group: str,
        method: str,
        url: str,
        outcome: str,
        status: int | None = None,
    ) -> None:
        """Insert one request row for a judged flow. A later insert for the same flow replaces it."""
        if not flow_id or not isinstance(flow_id, str):
            raise ValueError("a flow id is required")
        if outcome not in ("allowed", "denied", "redirected", "cut"):
            raise ValueError("outcome is allowed, denied, redirected, or cut")
        host, path, query = parts_of(url)
        start = _wall(started_at).isoformat(timespec="seconds")
        ended = start if outcome in _ENDED_OUTCOMES else None
        with self.connection:
            self.connection.execute(
                "INSERT INTO requests ("
                "flow_id, started_at, ended_at, client_ip, client_group, site_group, "
                "method, host, path, query, url, status, content_type, bytes_down, bytes_up, outcome"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, 0, ?) "
                "ON CONFLICT (flow_id) DO UPDATE SET "
                "started_at = excluded.started_at, "
                "ended_at = excluded.ended_at, "
                "client_ip = excluded.client_ip, "
                "client_group = excluded.client_group, "
                "site_group = excluded.site_group, "
                "method = excluded.method, "
                "host = excluded.host, "
                "path = excluded.path, "
                "query = excluded.query, "
                "url = excluded.url, "
                "status = excluded.status, "
                "content_type = NULL, "
                "bytes_down = 0, "
                "bytes_up = 0, "
                "outcome = excluded.outcome",
                (
                    flow_id,
                    start,
                    ended,
                    client_ip,
                    client_group,
                    site_group,
                    method,
                    host,
                    path,
                    query,
                    url,
                    status,
                    outcome,
                ),
            )
            self.connection.execute("DELETE FROM request_quotas WHERE flow_id = ?", (flow_id,))
            self.connection.execute(
                "INSERT INTO hierarchy_settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE "
                "SET value = excluded.value WHERE excluded.value < hierarchy_settings.value",
                (_REQUESTS_SINCE, start),
            )

    def update_request(
        self,
        flow_id: str,
        *,
        at: datetime,
        bytes_down: int = 0,
        bytes_up: int = 0,
        quotas: Sequence[str] = (),
        status: int | None = None,
        content_type: str | None = None,
        ended: bool = False,
        outcome: str | None = None,
    ) -> None:
        """Add bytes and quotas to a request, and optionally end it.

        A report for an unknown flow is ignored. ``outcome`` of ``cut`` replaces
        an earlier allowed outcome. Ending sets ``ended_at`` when it is still open.
        """
        if not flow_id:
            return
        down = _zero_or_more(bytes_down, "bytes_down")
        up = _zero_or_more(bytes_up, "bytes_up")
        names: list[str] = []
        for name in quotas:
            if not isinstance(name, str) or not name:
                raise ValueError("a quota name is required")
            if name not in names:
                names.append(name)
        moment = _wall(at).isoformat(timespec="seconds")
        with self.connection:
            row = self.connection.execute(
                "SELECT outcome, ended_at FROM requests WHERE flow_id = ?", (flow_id,)
            ).fetchone()
            if row is None:
                return
            current_outcome, ended_at = row
            next_outcome = current_outcome
            if outcome == "cut":
                next_outcome = "cut"
            elif outcome is not None and outcome in ("allowed", "denied", "redirected", "cut"):
                next_outcome = outcome
            next_ended = ended_at
            if ended and ended_at is None:
                next_ended = moment
            self.connection.execute(
                "UPDATE requests SET "
                "bytes_down = bytes_down + ?, "
                "bytes_up = bytes_up + ?, "
                "status = COALESCE(?, status), "
                "content_type = COALESCE(?, content_type), "
                "ended_at = ?, "
                "outcome = ? "
                "WHERE flow_id = ?",
                (down, up, status, content_type, next_ended, next_outcome, flow_id),
            )
            for name in names:
                self.connection.execute(
                    "INSERT INTO request_quotas (flow_id, quota) VALUES (?, ?) "
                    "ON CONFLICT (flow_id, quota) DO NOTHING",
                    (flow_id, name),
                )

    def prune_requests(self, before: datetime) -> int:
        """Delete every request that started before ``before``. Return how many went."""
        cutoff = _wall(before).isoformat(timespec="seconds")
        with self.connection:
            gone = self.connection.execute(
                "SELECT flow_id FROM requests WHERE started_at < ?", (cutoff,)
            ).fetchall()
            if not gone:
                return 0
            ids = [flow_id for (flow_id,) in gone]
            placeholders = ",".join("?" for _ in ids)
            self.connection.execute(f"DELETE FROM request_quotas WHERE flow_id IN ({placeholders})", ids)
            self.connection.execute(f"DELETE FROM requests WHERE flow_id IN ({placeholders})", ids)
            return len(ids)

    def requests_since(self) -> datetime | None:
        """Return the household-local start of the earliest request ever recorded, or None before any."""
        raw = self._setting(_REQUESTS_SINCE)
        return None if raw is None else datetime.fromisoformat(raw)

    def ended_seconds(self, client_group: str, quota: str, when: date | datetime) -> int:
        """Return this client group's ended time on the quota.

        A bucket counts when ``when`` is at or after the bucket's end. An open
        bucket does not. Yesterday, another client group, and another quota
        are left out. Grace is not added.
        """
        wall = _as_of(when)
        total = 0
        for started_at, length in self.connection.execute(
            "SELECT started_at, length_seconds FROM quota_buckets "
            "WHERE client_group = ? AND quota = ? AND day = ?",
            (client_group, quota, wall.date().isoformat()),
        ):
            start = datetime.fromisoformat(started_at)
            if start + timedelta(seconds=int(length)) <= wall:
                total += int(length)
        return total

    def stored_bytes(self, client_group: str, quota: str, when: date | datetime) -> int:
        """Return this client group's stored bytes on the quota.

        Every bucket on that local day counts, including one that has not
        ended. Yesterday and another client group are left out. A quota with
        no byte limit still has its bytes here. The limit of zero lives on
        the quota, not in this total.
        """
        wall = _as_of(when)
        (total,) = self.connection.execute(
            "SELECT COALESCE(SUM(byte_count), 0) FROM quota_buckets "
            "WHERE client_group = ? AND quota = ? AND day = ?",
            (client_group, quota, wall.date().isoformat()),
        ).fetchone()
        return int(total)

    def successes(self, client_group: str, day: date, tasks: Sequence[Task] = ()) -> int:
        """Return this client group's score on the household day.

        The rows are the attempt catalogue, scored by ``policy.tasks.day_score``.
        A day with none is zero. Another client group is a different count.
        """
        return pass_count(self.connection, client_group, day, tasks)

    def site_buckets(
        self,
        client_group: str,
        site_group: str,
        first: date,
        last: date | None = None,
    ) -> list[tuple[date, datetime, int, int]]:
        """Return site-group buckets from first through last, oldest start first.

        Each item is the day, the local start, the stored length, and the
        bytes. A day with no traffic contributes nothing. This is the
        site-group view S008.4 reads, including ``default``.
        """
        return self._between(
            "group_buckets",
            "site_group",
            client_group,
            site_group,
            first,
            first if last is None else last,
        )

    def client_buckets(
        self,
        client_group: str,
        first: date,
        last: date | None = None,
    ) -> list[tuple[str, date, datetime, int, int]]:
        """Return every site-group bucket for one client group, oldest first.

        Each item is the site group, the day, the start, the stored length,
        and the bytes. Traffic that no quota accepts is still here.
        """
        end = first if last is None else last
        _dates(first, end)
        rows = self.connection.execute(
            "SELECT site_group, day, started_at, length_seconds, byte_count FROM group_buckets "
            "WHERE client_group = ? AND day >= ? AND day <= ? ORDER BY started_at, site_group",
            (client_group, first.isoformat(), end.isoformat()),
        ).fetchall()
        return [
            (
                site_group,
                date.fromisoformat(day),
                datetime.fromisoformat(started_at),
                int(length),
                int(nbytes),
            )
            for site_group, day, started_at, length, nbytes in rows
        ]

    def quota_buckets(
        self,
        client_group: str,
        quota: str,
        first: date,
        last: date | None = None,
    ) -> list[tuple[date, datetime, int, int]]:
        """Return one client group's buckets for a quota, oldest start first."""
        return self._between(
            "quota_buckets",
            "quota",
            client_group,
            quota,
            first,
            first if last is None else last,
        )

    def rows_between(self, ledger: str, start: datetime, end: datetime) -> list[tuple[str, str, datetime, int, int]]:
        """Return every bucket of one ledger that starts at or after start and before end.

        ``ledger`` is ``site`` for the site-group rows or ``quota`` for the
        quota rows. Each item is the client group, the site group or quota,
        the local start, the stored length, and the bytes, oldest start first.
        """
        table, column = {"site": ("group_buckets", "site_group"), "quota": ("quota_buckets", "quota")}[ledger]
        rows = self.connection.execute(
            f"SELECT client_group, {column}, started_at, length_seconds, byte_count FROM {table} "
            "WHERE started_at >= ? AND started_at < ? ORDER BY started_at",
            (_wall(start).isoformat(timespec="seconds"), _wall(end).isoformat(timespec="seconds")),
        ).fetchall()
        return [
            (client_group, name, datetime.fromisoformat(started_at), int(length), int(nbytes))
            for client_group, name, started_at, length, nbytes in rows
        ]

    def quota_clients(self, quota: str) -> list[str]:
        """Return client groups that have any balance on this quota.

        ``default`` is included when that group has a row. The order is the
        client-group name.
        """
        rows = self.connection.execute(
            "SELECT DISTINCT client_group FROM quota_buckets WHERE quota = ? ORDER BY client_group",
            (quota,),
        ).fetchall()
        return [name for (name,) in rows]

    def _between(
        self,
        table: str,
        column: str,
        client_group: str,
        name: str,
        first: date,
        last: date,
    ) -> list[tuple[date, datetime, int, int]]:
        _dates(first, last)
        rows = self.connection.execute(
            f"SELECT day, started_at, length_seconds, byte_count FROM {table} "
            f"WHERE client_group = ? AND {column} = ? AND day >= ? AND day <= ? "
            "ORDER BY started_at",
            (client_group, name, first.isoformat(), last.isoformat()),
        ).fetchall()
        return [
            (
                date.fromisoformat(day),
                datetime.fromisoformat(started_at),
                int(length),
                int(nbytes),
            )
            for day, started_at, length, nbytes in rows
        ]

    def _ensure_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS hierarchy_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS group_buckets (
                client_group TEXT NOT NULL,
                site_group TEXT NOT NULL,
                day TEXT NOT NULL,
                started_at TEXT NOT NULL,
                length_seconds INTEGER NOT NULL,
                byte_count INTEGER NOT NULL,
                PRIMARY KEY (client_group, site_group, started_at)
            );
            CREATE TABLE IF NOT EXISTS quota_buckets (
                client_group TEXT NOT NULL,
                quota TEXT NOT NULL,
                day TEXT NOT NULL,
                started_at TEXT NOT NULL,
                length_seconds INTEGER NOT NULL,
                byte_count INTEGER NOT NULL,
                PRIMARY KEY (client_group, quota, started_at)
            );
            CREATE INDEX IF NOT EXISTS group_buckets_by_day
                ON group_buckets (client_group, site_group, day, started_at);
            CREATE INDEX IF NOT EXISTS quota_buckets_by_day
                ON quota_buckets (client_group, quota, day);
            CREATE INDEX IF NOT EXISTS quota_buckets_by_quota
                ON quota_buckets (quota, client_group);
            CREATE INDEX IF NOT EXISTS group_buckets_by_start ON group_buckets (started_at);
            CREATE INDEX IF NOT EXISTS quota_buckets_by_start ON quota_buckets (started_at);
            CREATE TABLE IF NOT EXISTS host_buckets (
                client_group TEXT NOT NULL,
                site_group TEXT NOT NULL,
                host TEXT NOT NULL,
                started_at TEXT NOT NULL,
                length_seconds INTEGER NOT NULL,
                bytes_down INTEGER NOT NULL,
                bytes_up INTEGER NOT NULL,
                PRIMARY KEY (client_group, site_group, host, started_at)
            );
            CREATE TABLE IF NOT EXISTS host_quota_buckets (
                client_group TEXT NOT NULL,
                quota TEXT NOT NULL,
                host TEXT NOT NULL,
                started_at TEXT NOT NULL,
                length_seconds INTEGER NOT NULL,
                bytes_down INTEGER NOT NULL,
                bytes_up INTEGER NOT NULL,
                PRIMARY KEY (client_group, quota, host, started_at)
            );
            CREATE INDEX IF NOT EXISTS host_buckets_by_start ON host_buckets (started_at);
            CREATE INDEX IF NOT EXISTS host_quota_buckets_by_start ON host_quota_buckets (started_at);
            CREATE TABLE IF NOT EXISTS requests (
                flow_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                client_ip TEXT NOT NULL,
                client_group TEXT NOT NULL,
                site_group TEXT NOT NULL,
                method TEXT NOT NULL,
                host TEXT NOT NULL,
                path TEXT NOT NULL,
                query TEXT NOT NULL,
                url TEXT NOT NULL,
                status INTEGER,
                content_type TEXT,
                bytes_down INTEGER NOT NULL DEFAULT 0,
                bytes_up INTEGER NOT NULL DEFAULT 0,
                outcome TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS request_quotas (
                flow_id TEXT NOT NULL,
                quota TEXT NOT NULL,
                PRIMARY KEY (flow_id, quota)
            );
            CREATE INDEX IF NOT EXISTS requests_by_client_host_start
                ON requests (client_group, host, started_at);
            CREATE INDEX IF NOT EXISTS requests_by_start ON requests (started_at);
            CREATE TABLE IF NOT EXISTS transfers (
                flow_id TEXT PRIMARY KEY,
                client_group TEXT NOT NULL,
                site_group TEXT NOT NULL,
                url TEXT NOT NULL,
                recheck_at TEXT,
                ceilings TEXT NOT NULL
            );
            """
        )
        ensure_attempts(self.connection)

    def _end_open_buckets(self, loaded_at: datetime) -> None:
        wall = _wall(loaded_at)
        # No bucket is longer than a day, so an older one has already ended.
        earliest = (wall - timedelta(days=1)).isoformat(timespec="seconds")
        for table in ("group_buckets", "quota_buckets", "host_buckets", "host_quota_buckets"):
            rows = self.connection.execute(
                f"SELECT rowid, started_at, length_seconds FROM {table} WHERE started_at >= ?",
                (earliest,),
            ).fetchall()
            for rowid, started_at, length in rows:
                start = datetime.fromisoformat(started_at)
                if start >= wall:
                    continue
                remaining = int((wall - start).total_seconds())
                if remaining < 1 or remaining >= int(length):
                    continue
                self.connection.execute(
                    f"UPDATE {table} SET length_seconds = ? WHERE rowid = ?",
                    (remaining, rowid),
                )

    def _mark(
        self,
        table: str,
        column: str,
        client_group: str,
        name: str,
        start: datetime,
        length: int,
        byte_count: int,
    ) -> None:
        self.connection.execute(
            f"INSERT INTO {table} ("
            f"client_group, {column}, day, started_at, length_seconds, byte_count"
            ") VALUES (?, ?, ?, ?, ?, ?) "
            f"ON CONFLICT (client_group, {column}, started_at) DO UPDATE SET "
            f"byte_count = {table}.byte_count + excluded.byte_count",
            (
                client_group,
                name,
                start.date().isoformat(),
                start.isoformat(timespec="seconds"),
                length,
                byte_count,
            ),
        )

    def _mark_host(
        self,
        table: str,
        column: str,
        client_group: str,
        name: str,
        host: str,
        start: datetime,
        length: int,
        down: int,
        up: int,
    ) -> None:
        self.connection.execute(
            f"INSERT INTO {table} ("
            f"client_group, {column}, host, started_at, length_seconds, bytes_down, bytes_up"
            ") VALUES (?, ?, ?, ?, ?, ?, ?) "
            f"ON CONFLICT (client_group, {column}, host, started_at) DO UPDATE SET "
            f"bytes_down = {table}.bytes_down + excluded.bytes_down, "
            f"bytes_up = {table}.bytes_up + excluded.bytes_up",
            (client_group, name, host, start.isoformat(timespec="seconds"), length, down, up),
        )

    def save_transfer(
        self,
        flow_id: str,
        client_group: str,
        site_group: str,
        url: str,
        assumption: Assumption,
    ) -> None:
        """Remember the allow for this flow. A later allow replaces it."""
        moment = None if assumption.recheck_at is None else assumption.recheck_at.isoformat()
        payload = json.dumps(list(assumption.ceilings), separators=(",", ":"))
        with self.connection:
            self.connection.execute(
                "INSERT INTO transfers "
                "(flow_id, client_group, site_group, url, recheck_at, ceilings) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (flow_id) DO UPDATE SET "
                "client_group = excluded.client_group, "
                "site_group = excluded.site_group, "
                "url = excluded.url, "
                "recheck_at = excluded.recheck_at, "
                "ceilings = excluded.ceilings",
                (flow_id, client_group, site_group, url, moment, payload),
            )

    def transfer(self, flow_id: str) -> tuple[str, str, str, datetime | None, tuple[tuple[str, int], ...]] | None:
        """Return the stored allow, or None when this flow was not recorded."""
        row = self.connection.execute(
            "SELECT client_group, site_group, url, recheck_at, ceilings "
            "FROM transfers WHERE flow_id = ?",
            (flow_id,),
        ).fetchone()
        if row is None:
            return None
        client_group, site_group, url, raw_time, raw_ceilings = row
        recheck_at = None if raw_time is None else datetime.fromisoformat(raw_time)
        parsed = json.loads(raw_ceilings)
        ceilings = tuple((str(name), int(level)) for name, level in parsed)
        return client_group, site_group, url, recheck_at, ceilings

    def _setting(self, key: str) -> str | None:
        row = self.connection.execute(
            "SELECT value FROM hierarchy_settings WHERE key = ?", (key,)
        ).fetchone()
        if row is None or row[0] in (None, ""):
            return None
        return str(row[0])

    def _regimes_raw(self) -> list[dict[str, object]] | None:
        raw = self._setting("bucket_regimes")
        if raw is None:
            return None
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValueError("bucket regimes are a list")
        return parsed

    def _put(self, key: str, value: str) -> None:
        self.connection.execute(
            "INSERT INTO hierarchy_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


@dataclass(frozen=True)
class Filing:
    """One stored report, and the quotas it accrued to.

    ``at`` is household-local. ``quotas`` is the names accepted before the
    bytes were written, in policy order, without duplicates.
    """

    client_group: str
    at: datetime
    quotas: tuple[str, ...]


def observe(policy: Policy, usage: UsageStore, clock: HouseholdClock, document: object) -> bool:
    """File one observation. Return False when it carried no new bytes.

    A malformed report raises ValueError. The caller still answers success
    for a report with nothing to add, and a failure here does not change an
    access decision already taken.
    """
    return file_report(policy, usage, clock, document) is not None


def file_report(
    policy: Policy, usage: UsageStore, clock: HouseholdClock, document: object
) -> Filing | None:
    """File one observation. Return None when it carried no new bytes.

    A malformed report raises ValueError. The quotas on the result are the
    ones whose rule sets accepted the report before it was stored. A zero-byte
    end-of-flow report still updates the request row through ``note_request``.
    """
    parsed = _parse(document)
    if parsed is None:
        return None
    client_ip, url, occurred, nbytes, up = parsed
    moment = clock.local(occurred)
    usage.ensure_length(policy.bucket_length)
    client_group = classify_client(policy, client_ip)
    site_group = classify_site(policy, url)
    accepted = [
        quota.name
        for quota in policy.quotas
        if _accepts(policy, usage, quota.ruleset, client_group, site_group, moment)
    ]
    usage.file_observation(client_group, site_group, moment, nbytes, accepted, host=host_of(url), bytes_up=up)
    return Filing(client_group, moment, tuple(accepted))


def note_request(
    usage: UsageStore,
    clock: HouseholdClock,
    document: object,
    *,
    quotas: Sequence[str] = (),
    cut: bool = False,
) -> None:
    """Update the request row named on an observation, including a zero-byte end report.

    ``quotas`` are the ones that accepted this report's bytes. ``cut`` marks the
    outcome as cut. A report with no flow id is ignored. A malformed end field
    raises ValueError.
    """
    if not isinstance(document, dict):
        raise ValueError("an observation is a JSON object")
    flow_id = document.get("flow_id")
    if flow_id is None:
        return
    if not isinstance(flow_id, str) or not flow_id:
        raise ValueError("flow_id must be a string")
    occurred_at = document.get("occurred_at")
    if not isinstance(occurred_at, str):
        raise ValueError("occurred_at must be an ISO 8601 time")
    try:
        moment = clock.local(datetime.fromisoformat(occurred_at))
    except ValueError as exc:
        raise ValueError("occurred_at must be an ISO 8601 time") from exc
    nbytes = document.get("bytes", 0)
    if isinstance(nbytes, bool) or not isinstance(nbytes, int) or nbytes < 0:
        raise ValueError("bytes is a whole number, zero or more")
    up = 0
    down = nbytes
    if "bytes_up" in document or "bytes_down" in document:
        up = _zero_or_more(document.get("bytes_up"), "bytes_up")
        down = _zero_or_more(document.get("bytes_down"), "bytes_down")
        if up + down != nbytes:
            raise ValueError("bytes is bytes_up and bytes_down added together")
    status = document.get("status")
    if status is not None and (isinstance(status, bool) or not isinstance(status, int) or status < 100 or status > 599):
        raise ValueError("status is an HTTP status code")
    content_type = document.get("content_type")
    if content_type is not None and not isinstance(content_type, str):
        raise ValueError("content_type must be a string")
    ended = bool(document.get("ended"))
    if content_type is not None and ";" in content_type:
        content_type = content_type.split(";", 1)[0].strip() or None
    usage.update_request(
        flow_id,
        at=moment,
        bytes_down=down,
        bytes_up=up,
        quotas=quotas,
        status=status,
        content_type=content_type,
        ended=ended or cut,
        outcome="cut" if cut else None,
    )


def host_of(url: str) -> str:
    """Return the host a URL fetched, with its port only when it is not the scheme's default.

    ``https://www.youtube.com:443/x`` is ``www.youtube.com`` and
    ``http://localhost:3000/`` is ``localhost:3000``. An IPv6 address keeps its
    brackets when it has a port. A URL with no host name is itself.
    """
    parts = urlsplit(url)
    name = parts.hostname
    if not name:
        return url
    try:
        port = parts.port
    except ValueError:
        port = None
    if port is None or port == _DEFAULT_PORTS.get(parts.scheme.lower()):
        return name
    return f"[{name}]:{port}" if ":" in name else f"{name}:{port}"


def parts_of(url: str) -> tuple[str, str, str]:
    """Return the host, the address without its query string, and the query without its ``?``."""
    parts = urlsplit(url)
    path = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return host_of(url), path, parts.query


def outcome_of(decision: Mapping[str, object] | dict) -> tuple[str, int | None]:
    """Return the request outcome and HTTP status for a decision payload."""
    action = decision.get("action")
    outcome = _REQUEST_OUTCOMES.get(action if isinstance(action, str) else "", "denied")
    raw = decision.get("status")
    status = int(raw) if isinstance(raw, int) and not isinstance(raw, bool) else None
    if outcome == "denied" and status is None:
        status = 403
    if outcome == "redirected" and status is None:
        status = 302
    if outcome == "allowed":
        status = None
    return outcome, status


def host_cutoff(retention_days: int, now: datetime) -> datetime:
    """Return the local midnight before which host rows are older than the retention.

    Kept for 30 days on Friday 13 November means kept from Wednesday 14 October.
    """
    return datetime.combine(_wall(now).date() - timedelta(days=retention_days), time.min)


def prune_hosts(policy: Policy, usage: UsageStore, now: datetime) -> int:
    """Delete the host rows older than the policy's retention. Return how many went."""
    return usage.prune_hosts(host_cutoff(policy.host_retention, now))


def prune_requests(policy: Policy, usage: UsageStore, now: datetime) -> int:
    """Delete the request rows older than the policy's retention. Return how many went."""
    return usage.prune_requests(host_cutoff(policy.request_retention, now))


def cut_required(
    policy: Policy,
    usage: UsageStore,
    filing: Filing,
    flow_id: str | None,
) -> bool:
    """Return whether this report should stop the transfer it belongs to.

    No recorded allow means do not cut. The bytes are still filed. A recorded
    allow is left alone until the clock reaches its deadline or a recorded
    volume ceiling is reached. Then the access rules are walked again with
    the groups from the approval. Allow replaces the deadline and the
    ceilings. Anything else cuts. A fresh allow whose new deadline is already
    due cuts as well, so the same observation cannot allow and expire together.
    """
    if not flow_id:
        return False
    row = usage.transfer(flow_id)
    if row is None:
        return False
    client_group, site_group, url, recheck_at, ceilings = row
    moment = _wall(filing.at)
    due = recheck_at is not None and moment >= _wall(recheck_at)
    if not due:
        for name, level in ceilings:
            if usage.stored_bytes(client_group, name, filing.at) >= level:
                due = True
                break
    if not due:
        return False
    trace, assumption = judge_frozen(
        policy,
        client_group=client_group,
        site_group=site_group,
        at=filing.at,
        ledger=usage,
    )
    if trace.decision.get("action") != "allow":
        return True
    if assumption.recheck_at is not None and moment >= _wall(assumption.recheck_at):
        return True
    for name, level in assumption.ceilings:
        if usage.stored_bytes(client_group, name, filing.at) >= level:
            return True
    usage.save_transfer(flow_id, client_group, site_group, url, assumption)
    return False


def _accepts(
    policy: Policy,
    usage: UsageStore,
    ruleset: str,
    client_group: str,
    site_group: str,
    moment: datetime,
) -> bool:
    rules = policy.rule_set(ruleset)
    if rules is None:
        return False
    trace = evaluate(
        policy,
        rules,
        client_group=client_group,
        site_group=site_group,
        at=moment,
        ledger=usage,
        rule_set=ruleset,
    )
    return trace.decision.get("action") in _ACCRUING


def _parse(document: object) -> tuple[str, str, datetime, int, int] | None:
    """Return client, url, time, bytes, and the bytes sent up. None when no bytes moved.

    ``bytes`` is the total. A report that also has ``bytes_up`` and
    ``bytes_down`` must add up to it. A report from an older proxy with only
    ``bytes`` sent nothing up.
    """
    if not isinstance(document, dict):
        raise ValueError("an observation is a JSON object")
    client_ip = document.get("client_ip")
    if not isinstance(client_ip, str) or normalize_ip(client_ip) is None:
        raise ValueError("client_ip must be an IP address")
    url = document.get("url")
    if not isinstance(url, str) or not url:
        raise ValueError("url is required")
    occurred_at = document.get("occurred_at")
    if not isinstance(occurred_at, str):
        raise ValueError("occurred_at must be an ISO 8601 time")
    try:
        moment = datetime.fromisoformat(occurred_at)
    except ValueError as exc:
        raise ValueError("occurred_at must be an ISO 8601 time") from exc
    nbytes = document.get("bytes")
    if isinstance(nbytes, bool) or not isinstance(nbytes, int) or nbytes < 0:
        raise ValueError("bytes is a whole number, zero or more")
    up = 0
    if "bytes_up" in document or "bytes_down" in document:
        up = _zero_or_more(document.get("bytes_up"), "bytes_up")
        down = _zero_or_more(document.get("bytes_down"), "bytes_down")
        if up + down != nbytes:
            raise ValueError("bytes is bytes_up and bytes_down added together")
    if nbytes == 0:
        return None
    return client_ip, url, moment, nbytes, up


def _as_of(when: date | datetime) -> datetime:
    """Return the household-local moment a balance is read at.

    A date is the last second of that local day, so every bucket that ended
    during the day counts, and one that ends on the next midnight does not.
    """
    if isinstance(when, datetime):
        return _wall(when)
    if type(when) is date:
        return datetime.combine(when + timedelta(days=1), time.min) - timedelta(seconds=1)
    raise ValueError("usage is read at a date or a time")


def _wall(moment: datetime) -> datetime:
    """Return household-local wall time to the second, without a timezone.

    An aware value is already household-local. The offset is dropped, not
    converted.
    """
    if not isinstance(moment, datetime):
        raise ValueError("time must be a datetime")
    if moment.tzinfo is not None:
        moment = moment.replace(tzinfo=None)
    return moment.replace(microsecond=0)


def _dates(first: date, last: date) -> None:
    if type(first) is not date or type(last) is not date:
        raise ValueError("days must be dates")


def _zero_or_more(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} is a whole number, zero or more")
    return value
