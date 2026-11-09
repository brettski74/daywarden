"""The parent usage report.

The report asks for a site group, a client group, or a quota. A site group or
a client group shows the last 14 household-local days. Each day lists the
buckets that contained traffic: the clock times, the length stored for that
bucket, and the bytes. A bucket counts toward the day's time once its end
has passed. A day with no rows says no usage. Traffic that no quota accepts
is listed the same way.

A quota shows one client group's ended time against the time limit and the
stored bytes against the byte limit, including a limit of zero. With no
client group, it lists every client group that has a balance on it.

``usage_report`` assembles the report as plain data for the parent portal's
usage page. The values are already formatted, so the page shows them as they
are. The portal decides who may see it.
"""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from policy.hierarchy import Policy
from policy.usage import UsageStore

RECENT_DAYS = 14
# The units the policy file's byte limits are written in, largest first.
BYTE_UNITS = (
    ("TB", 1024**4),
    ("GB", 1024**3),
    ("MB", 1024**2),
    ("KB", 1024),
)
USAGE_KEYS = ("view", "client", "site", "quota")

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


@dataclass(frozen=True)
class BucketLine:
    start: datetime
    length_seconds: int
    byte_count: int
    counted: bool
    site_group: str = ""


@dataclass(frozen=True)
class DayLine:
    day: date
    buckets: tuple[BucketLine, ...]

    @property
    def counted_seconds(self) -> int:
        return sum(bucket.length_seconds for bucket in self.buckets if bucket.counted)


@dataclass(frozen=True)
class PageResponse:
    status: int
    body: str
    headers: tuple[tuple[str, str], ...] = ()


def recent_dates(today: date, count: int = RECENT_DAYS) -> tuple[date, ...]:
    """Return count household-local dates, today first."""
    if count < 1:
        raise ValueError("the report covers at least one day")
    return tuple(today - timedelta(days=offset) for offset in range(count))


def format_duration(seconds: int) -> str:
    """Return a short duration such as 2h, 5m, 2m 30s, or 90s."""
    if seconds < 0:
        raise ValueError("a duration is zero or more seconds")
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def format_span(start: datetime, length: int) -> str:
    """Return the clock times a bucket covers, in household-local time.

    start is the local start stored on the bucket. An end that falls on the
    next midnight is written 24:00 so the range reads forward. Any other end
    on the next day says so.
    """
    end = start + timedelta(seconds=length)
    if end.date() != start.date():
        if (end.hour, end.minute, end.second) == (0, 0, 0):
            return f"{_clock(start)} to 24:00"
        return f"{_clock(start)} to {_clock(end)} the next day"
    return f"{_clock(start)} to {_clock(end)}"


def format_bytes(count: int) -> str:
    """Return a byte total such as 1 byte or 1,000 bytes."""
    if count == 1:
        return "1 byte"
    return f"{count:,} bytes"


def format_byte_limit(count: int) -> str:
    """Return a size such as 500 MB, 2 KB, or 1,500 bytes.

    KB, MB, GB, and TB are the powers of 1,024 the policy file accepts.
    A count that is not a whole number of those units is left in bytes.
    """
    if count < 0:
        raise ValueError("a byte limit is zero or more")
    for unit, size in BYTE_UNITS:
        if count >= size and count % size == 0:
            return f"{count // size:,} {unit}"
    return format_bytes(count)


def format_day(day: date) -> str:
    """Return a household-local date such as Wednesday 21 October 2026."""
    return f"{_WEEKDAYS[day.weekday()]} {day.day} {_MONTHS[day.month - 1]} {day.year}"


def timezone_note(timezone: str | None) -> str:
    """Return the sentence that says which timezone the times are in."""
    if timezone:
        return f"Times are {timezone}."
    return "Times are the timezone of this machine."


def usage_report(
    policy: Policy | None,
    usage: UsageStore,
    query: Mapping[str, str],
    now: datetime,
) -> dict:
    """Return the group or quota report the query asks for.

    now is household-local. ``choices`` lists what each pull-down offers.
    ``report`` is the chosen report, or None with ``message`` saying what is
    missing or not in the household.
    """
    clients, sites, quotas = _catalog(policy)
    timezone = None if policy is None else policy.timezone
    chosen = {key: query.get(key, "") for key in USAGE_KEYS}
    view = chosen["view"]
    if view == "site":
        report, message = _site_report(usage, clients, sites, chosen, now)
    elif view == "client":
        report, message = _client_report(usage, clients, chosen, now)
    elif view == "quota":
        report, message = _quota_report(policy, usage, clients, chosen, now)
    else:
        report, message = None, "Choose a site group, a client group, or a quota."
    return {
        "times": timezone_note(timezone),
        "choices": {"clients": list(clients), "sites": list(sites), "quotas": list(quotas)},
        "chosen": chosen,
        "report": report,
        "message": message,
    }


def _catalog(policy: Policy | None) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Return client groups, site groups, and quotas, with ``default`` selectable."""
    if policy is None:
        return ("default",), ("default",), ()
    clients = [group.name for group in policy.client_groups]
    if "default" not in clients:
        clients.append("default")
    sites = [group.name for group in sorted(policy.site_groups, key=lambda group: group.priority)]
    if "default" not in sites:
        sites.append("default")
    return tuple(clients), tuple(sites), tuple(quota.name for quota in policy.quotas)


def _site_report(
    usage: UsageStore,
    clients: Sequence[str],
    sites: Sequence[str],
    chosen: Mapping[str, str],
    now: datetime,
) -> tuple[dict | None, str | None]:
    client = chosen["client"]
    site = chosen["site"]
    if not client or not site:
        return None, "Choose a client group and a site group."
    if client not in clients:
        return None, "That client group is not in the household."
    if site not in sites:
        return None, "That site group is not in the household."
    days = _fill_days(usage.site_buckets(client, site, *_oldest_and_newest(now)), now, with_site=False)
    return _days_report(f"{client}, {site}", days, site_column=False), None


def _client_report(
    usage: UsageStore,
    clients: Sequence[str],
    chosen: Mapping[str, str],
    now: datetime,
) -> tuple[dict | None, str | None]:
    client = chosen["client"]
    if not client:
        return None, "Choose a client group."
    if client not in clients:
        return None, "That client group is not in the household."
    days = _fill_days(usage.client_buckets(client, *_oldest_and_newest(now)), now, with_site=True)
    return _days_report(client, days, site_column=True), None


def _days_report(heading: str, days: Sequence[DayLine], *, site_column: bool) -> dict:
    return {
        "kind": "days",
        "heading": heading,
        "note": f"The last {RECENT_DAYS} days.",
        "site_column": site_column,
        "days": [_day(day, site_column=site_column) for day in days],
    }


def _day(day: DayLine, *, site_column: bool) -> dict:
    if not day.buckets:
        return {"heading": format_day(day.day), "summary": None, "rows": []}
    if day.counted_seconds == 0:
        summary = "Counted time: none yet."
    else:
        summary = f"Counted time: {format_duration(day.counted_seconds)}."
    return {
        "heading": format_day(day.day),
        "summary": summary,
        "rows": [_bucket_row(bucket, site_column=site_column) for bucket in day.buckets],
    }


def _bucket_row(bucket: BucketLine, *, site_column: bool) -> dict:
    duration = format_duration(bucket.length_seconds)
    if not bucket.counted:
        duration += ", not counted yet"
    row = {
        "when": format_span(bucket.start, bucket.length_seconds),
        "time": duration,
        "bytes": format_bytes(bucket.byte_count),
    }
    if site_column:
        row["site"] = bucket.site_group
    return row


def _quota_report(
    policy: Policy | None,
    usage: UsageStore,
    clients: Sequence[str],
    chosen: Mapping[str, str],
    now: datetime,
) -> tuple[dict | None, str | None]:
    name = chosen["quota"]
    if not name:
        return None, "Choose a quota."
    quota = None if policy is None else policy.quota(name)
    if quota is None:
        return None, "That quota is not in the household."
    client = chosen["client"]
    if client and client not in clients:
        return None, "That client group is not in the household."
    wall = _wall(now)
    time_limit = format_duration(quota.time_limit)
    byte_limit = format_byte_limit(quota.byte_limit)
    report = {
        "day": format_day(wall.date()),
        "limits": [f"Time limit: {time_limit}.", f"Byte limit: {byte_limit}."],
    }
    if client:
        seconds = usage.ended_seconds(client, name, wall)
        nbytes = usage.stored_bytes(client, name, wall)
        return {
            **report,
            "kind": "quota",
            "heading": f"{client}, {name}",
            "lines": [
                f"Ended time: {_against(format_duration(seconds), time_limit)}",
                f"Stored bytes: {_against(format_bytes(nbytes), byte_limit)}",
            ],
        }, None
    rows = [
        {
            "client": group,
            "time": _against(format_duration(usage.ended_seconds(group, name, wall)), time_limit),
            "bytes": _against(format_bytes(usage.stored_bytes(group, name, wall)), byte_limit),
        }
        for group in usage.quota_clients(name)
    ]
    return {
        **report,
        "kind": "balances",
        "heading": name,
        "rows": rows,
        "empty": "No client group has a balance.",
    }, None


def _against(used: str, limit: str) -> str:
    return f"{used} of {limit}."


def _fill_days(rows: Sequence[tuple], now: datetime, *, with_site: bool) -> tuple[DayLine, ...]:
    """Group stored rows into the recent local days, today first.

    Buckets inside a day stay in the order the store returned. A row from the
    client-group ledger starts with the site group. A row from the site-group
    ledger does not. Days outside the fortnight are left out.
    """
    wall = _wall(now)
    dates = recent_dates(wall.date())
    allowed = set(dates)
    grouped: dict[date, list[BucketLine]] = {}
    for item in rows:
        if with_site:
            site_name, day, start, length, nbytes = item
        else:
            day, start, length, nbytes = item
            site_name = ""
        if day not in allowed:
            continue
        end = start + timedelta(seconds=int(length))
        grouped.setdefault(day, []).append(BucketLine(start, int(length), int(nbytes), end <= wall, site_name))
    return tuple(DayLine(day, tuple(grouped.get(day, ()))) for day in dates)


def _oldest_and_newest(now: datetime) -> tuple[date, date]:
    dates = recent_dates(_wall(now).date())
    return dates[-1], dates[0]


def _response(
    status: int,
    body: str,
    extra: tuple[tuple[str, str], ...] = (),
) -> PageResponse:
    return PageResponse(status, body, (("cache-control", "no-store"), *extra))


def _clock(moment: datetime) -> str:
    if moment.second:
        return moment.strftime("%H:%M:%S")
    return moment.strftime("%H:%M")


def _wall(moment: datetime) -> datetime:
    """Return household-local time to the second, offset dropped rather than converted."""
    if not isinstance(moment, datetime):
        raise ValueError("time must be a datetime")
    if moment.tzinfo is not None:
        moment = moment.replace(tzinfo=None)
    return moment.replace(microsecond=0)


def _e(value: str) -> str:
    return html.escape(value, quote=True)
