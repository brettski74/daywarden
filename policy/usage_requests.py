"""The request table for the usage drill-down and the Requests page.

One endpoint lists every matching request within the filters and range, with
sorting and paging across the whole set. The drill-down from a host on the
graph uses an exact host and the line's group; the Requests page uses a host
fragment and optional outcomes. Group by is ignored: it is only how the graph
draws its lines.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, time, timedelta

from policy.hierarchy import DEFAULT_REQUEST_RETENTION_DAYS, Policy
from policy.report import format_day, format_duration, timezone_note
from policy.usage import UsageStore, host_cutoff
from policy.usage_graph import (
    DEFAULT_PRESET,
    SETTING_KEYS,
    Presets,
    Settings,
    catalog,
    custom_problems,
    describe_range,
    fit,
    parse_day,
    resolve_range,
    settings_from_query,
)

PAGE_SIZE = 100
OUTCOMES = ("allowed", "denied", "redirected", "cut")
SORTS = (
    "start",
    "end",
    "duration",
    "address",
    "client",
    "site",
    "quotas",
    "method",
    "host",
    "path",
    "query",
    "status",
    "type",
    "down",
    "up",
    "outcome",
)
_SORT_COLUMNS = {
    "start": "r.started_at",
    "end": "r.ended_at",
    "address": "r.client_ip",
    "client": "r.client_group",
    "site": "r.site_group",
    "method": "r.method",
    "host": "r.host",
    "path": "r.path",
    "query": "r.query",
    "status": "r.status",
    "type": "r.content_type",
    "down": "r.bytes_down",
    "up": "r.bytes_up",
    "outcome": "r.outcome",
}
_BYTE_UNITS = (("TB", 1024**4), ("GB", 1024**3), ("MB", 1024**2), ("KB", 1024))


def usage_requests(
    policy: Policy | None,
    usage: UsageStore,
    presets: Presets,
    pairs: Sequence[tuple[str, str]],
    now: datetime,
) -> dict:
    """Return the request table a page address asks for."""
    now = _wall(now)
    names = catalog(policy)
    notes: list[str] = []
    named = _last_value(pairs, "preset")
    on_show = ""
    if named is not None:
        stored = presets.find(named)
        if stored is None:
            notes.append(f"There is no preset called {named}, so this is {DEFAULT_PRESET}.")
            on_show, raw = DEFAULT_PRESET, presets.settings(DEFAULT_PRESET)
        else:
            on_show, raw = stored
    elif any(key in SETTING_KEYS for key, _value in pairs):
        raw, read_notes = settings_from_query(pairs)
        notes.extend(read_notes)
    else:
        on_show, raw = DEFAULT_PRESET, presets.settings(DEFAULT_PRESET)
    host = (_last_value(pairs, "host") or "").strip()
    exact = (_last_value(pairs, "exact") or "").strip() in ("1", "true", "yes")
    outcomes = _chosen_outcomes(pairs)
    sort = (_last_value(pairs, "sort") or "start").strip()
    if sort not in SORTS:
        notes.append(f"{sort} is not a column to sort by, so the table is sorted by Start.")
        sort = "start"
    direction = (_last_value(pairs, "dir") or "desc").strip().lower()
    if direction not in ("asc", "desc"):
        notes.append(f"{direction} is not a sort direction, so the table is newest first.")
        direction = "desc"
    page = _page_number(_last_value(pairs, "page"), notes)
    line = (_last_value(pairs, "line") or "").strip()
    # Group by only shapes the graph's lines. The Requests page ignores it; a host
    # drill-down keeps it so the line's group still filters the rows.
    if not line:
        raw = replace(raw, by="none")
    settings, fitted = fit(raw, names)
    notes.extend(fitted)
    if not on_show:
        held_by = "none" if not line else None
        on_show = next(
            (
                name
                for name, held in presets.every()
                if fit(held if held_by is None else replace(held, by=held_by), names)[0].same_as(settings)
            ),
            "",
        )
    problems = custom_problems(settings)
    notes.extend(problems)

    answer = {
        "today": now.date().isoformat(),
        "choices": {
            "clients": list(names.clients),
            "sites": list(names.sites),
            "quotas": list(names.quotas),
            "outcomes": list(OUTCOMES),
        },
        "settings": settings.as_json(),
        "preset": on_show,
        "presets": presets.names(),
        "host": host,
        "exact": exact,
        "outcome": list(outcomes),
        "sort": sort,
        "dir": direction,
        "page": page,
        "notes": notes,
        "times": timezone_note(None if policy is None else policy.timezone),
        "range": None,
        "days": None,
        "kept": None,
        "total": 0,
        "from": 0,
        "to": 0,
        "pages": 0,
        "rows": [],
        "status": None,
    }
    if problems:
        return answer
    start, end = resolve_range(settings.range, now, parse_day(settings.first), parse_day(settings.last))
    last_day = (end - timedelta(seconds=1)).date() if end > start else start.date()
    answer["range"] = describe_range(start, end)
    answer["days"] = {"from": start.date().isoformat(), "to": last_day.isoformat()}

    retention = DEFAULT_REQUEST_RETENTION_DAYS if policy is None else policy.request_retention
    since = usage.requests_since() or now
    kept = max(host_cutoff(retention, now), datetime.combine(since.date(), time.min))
    if start < kept:
        days = f"{retention} day" + ("" if retention == 1 else "s")
        answer["kept"] = f"Requests are kept for {days}, from {format_day(kept.date())}."

    where, params = _filters(
        settings,
        line,
        host,
        exact,
        outcomes,
        max(start, kept),
        end,
    )
    order = _order(sort, direction, now)
    total = usage.connection.execute(
        f"SELECT COUNT(*) FROM requests r WHERE {where}",
        params,
    ).fetchone()[0]
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE) if total else 0
    if pages and page > pages:
        page = pages
    offset = (page - 1) * PAGE_SIZE if page else 0
    rows = usage.connection.execute(
        "SELECT r.flow_id, r.started_at, r.ended_at, r.client_ip, r.client_group, r.site_group, "
        "r.method, r.host, r.path, r.query, r.url, r.status, r.content_type, "
        "r.bytes_down, r.bytes_up, r.outcome, "
        "(SELECT group_concat(q.quota, ', ') FROM "
        "(SELECT quota FROM request_quotas WHERE flow_id = r.flow_id ORDER BY quota) q) "
        f"FROM requests r WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
        [*params, PAGE_SIZE, offset],
    ).fetchall()
    answer["total"] = total
    answer["page"] = page if total else 0
    answer["pages"] = pages
    answer["from"] = offset + 1 if total else 0
    answer["to"] = offset + len(rows)
    answer["rows"] = [_row(row, now) for row in rows]
    if total:
        answer["status"] = f"Requests {answer['from']:,} to {answer['to']:,} of {total:,}."
    else:
        answer["status"] = "No requests in this range."
    return answer


def _filters(
    settings: Settings,
    line: str,
    host: str,
    exact: bool,
    outcomes: tuple[str, ...],
    start: datetime,
    end: datetime,
) -> tuple[str, list]:
    clauses = ["r.started_at >= ?", "r.started_at < ?"]
    params: list = [_wall(start).isoformat(timespec="seconds"), _wall(end).isoformat(timespec="seconds")]
    if settings.clients:
        placeholders = ",".join("?" for _ in settings.clients)
        clauses.append(f"r.client_group IN ({placeholders})")
        params.extend(settings.clients)
    if settings.sites:
        placeholders = ",".join("?" for _ in settings.sites)
        clauses.append(f"r.site_group IN ({placeholders})")
        params.extend(settings.sites)
    if settings.quotas:
        placeholders = ",".join("?" for _ in settings.quotas)
        clauses.append(
            f"EXISTS (SELECT 1 FROM request_quotas rq WHERE rq.flow_id = r.flow_id AND rq.quota IN ({placeholders}))"
        )
        params.extend(settings.quotas)
    if host:
        if exact:
            clauses.append("r.host = ?")
            params.append(host)
        else:
            clauses.append("instr(lower(r.host), lower(?)) > 0")
            params.append(host)
    if outcomes:
        placeholders = ",".join("?" for _ in outcomes)
        clauses.append(f"r.outcome IN ({placeholders})")
        params.extend(outcomes)
    if line and settings.by == "client":
        clauses.append("r.client_group = ?")
        params.append(line)
    elif line and settings.by == "site":
        clauses.append("r.site_group = ?")
        params.append(line)
    elif line and settings.by == "quota":
        clauses.append(
            "EXISTS (SELECT 1 FROM request_quotas rq WHERE rq.flow_id = r.flow_id AND rq.quota = ?)"
        )
        params.append(line)
    return " AND ".join(clauses), params


def _order(sort: str, direction: str, now: datetime) -> str:
    ascending = direction == "asc"
    suffix = "ASC" if ascending else "DESC"
    nulls = "NULLS LAST" if ascending else "NULLS FIRST"
    if sort == "duration":
        # Running requests use the time so far.
        wall = _wall(now).isoformat(timespec="seconds")
        expr = (
            "CASE WHEN r.ended_at IS NULL THEN "
            f"(julianday('{wall}') - julianday(r.started_at)) * 86400 "
            "ELSE (julianday(r.ended_at) - julianday(r.started_at)) * 86400 END"
        )
        return f"{expr} {suffix}, r.started_at DESC, r.flow_id ASC"
    if sort == "quotas":
        expr = (
            "(SELECT group_concat(q.quota, ', ') FROM "
            "(SELECT quota FROM request_quotas WHERE flow_id = r.flow_id ORDER BY quota) q)"
        )
        return f"{expr} {suffix} {nulls}, r.started_at DESC, r.flow_id ASC"
    column = _SORT_COLUMNS[sort]
    if sort in ("end", "status", "type"):
        return f"{column} {suffix} {nulls}, r.started_at DESC, r.flow_id ASC"
    return f"{column} {suffix}, r.started_at DESC, r.flow_id ASC"


def _row(row: tuple, now: datetime) -> dict:
    (
        flow_id,
        started_at,
        ended_at,
        client_ip,
        client_group,
        site_group,
        method,
        host,
        path,
        query,
        url,
        status,
        content_type,
        down,
        up,
        outcome,
        quotas,
    ) = row
    start = datetime.fromisoformat(started_at)
    end = None if ended_at is None else datetime.fromisoformat(ended_at)
    finish = end if end is not None else _wall(now)
    seconds = max(0, int((finish - start).total_seconds()))
    return {
        "id": flow_id,
        "start": _local(start),
        "end": "" if end is None else _local(end),
        "duration": format_duration(seconds),
        "address": client_ip,
        "client_group": client_group,
        "site_group": site_group,
        "quotas": quotas or "",
        "method": method,
        "host": host,
        "path": path,
        "query": query,
        "url": url,
        "status": "" if status is None else str(status),
        "type": content_type or "",
        "down": _bytes(int(down)),
        "up": _bytes(int(up)),
        "outcome": outcome,
    }


def _chosen_outcomes(pairs: Sequence[tuple[str, str]]) -> tuple[str, ...]:
    found: list[str] = []
    for key, value in pairs:
        if key != "outcome":
            continue
        name = value.strip()
        if name in OUTCOMES and name not in found:
            found.append(name)
    return tuple(found)


def _page_number(raw: str | None, notes: list[str]) -> int:
    if raw is None or raw.strip() == "":
        return 1
    text = raw.strip()
    if not text.isdigit() or int(text) < 1:
        notes.append(f"{text} is not a page number, so this is page 1.")
        return 1
    return int(text)


def _last_value(pairs: Sequence[tuple[str, str]], key: str) -> str | None:
    found = None
    for name, value in pairs:
        if name == key:
            found = value
    return found


def _local(moment: datetime) -> str:
    moment = _wall(moment).replace(microsecond=0)
    clock = moment.strftime("%H:%M:%S") if moment.second else moment.strftime("%H:%M")
    return f"{format_day(moment.date())}, {clock}"


def _bytes(count: int) -> str:
    if count < 1024:
        return "1 byte" if count == 1 else f"{count} bytes"
    for name, size in _BYTE_UNITS:
        if count >= size:
            value = count / size
            rounded = round(value * 10) / 10 if value < 10 else round(value)
            text = str(int(rounded) if rounded == int(rounded) else rounded)
            return f"{text} {name}"
    return f"{count} bytes"


def _wall(moment: datetime) -> datetime:
    if moment.tzinfo is not None:
        moment = moment.replace(tzinfo=None)
    return moment.replace(microsecond=0)
