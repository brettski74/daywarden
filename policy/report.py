"""The parent usage report.

A signed-in parent picks a client and a site group and sees the last 14
household-local days. Each day lists the buckets that contained traffic: the
clock times they covered, the length stored for that bucket, and the bytes
it carried. A bucket counts toward the day's time once its end has passed.
A day with no rows says no usage. A group with no quota is shown the same way.

The page is closed unless the temporary parent gate has a password. S007.1
replaces that gate.
"""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlencode

from policy.clients import Client
from policy.gate import ParentGate
from policy.groups import SiteGroup
from policy.store import PolicyStore

RECENT_DAYS = 14

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


class NotInHousehold(Exception):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


@dataclass(frozen=True)
class BucketLine:
    start: datetime
    length_seconds: int
    byte_count: int
    counted: bool


@dataclass(frozen=True)
class DayLine:
    day: date
    buckets: tuple[BucketLine, ...]

    @property
    def counted_seconds(self) -> int:
        return sum(bucket.length_seconds for bucket in self.buckets if bucket.counted)


@dataclass(frozen=True)
class UsageReport:
    client: str
    group: str
    quota: int | None
    timezone: str | None
    days: tuple[DayLine, ...]


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


def load_report(store: PolicyStore, client_name: str, group_name: str, now: datetime) -> UsageReport:
    """Return the recent days for this client and group.

    now is household-local. An aware value is already in that zone; its offset
    is dropped, not converted. A bucket is counted when now is at or past its end.
    """
    wall = _wall(now)
    client = next((item for item in store.clients() if item.name == client_name), None)
    if client is None:
        raise NotInHousehold("client")
    group = next((item for item in store.groups() if item.name == group_name), None)
    if group is None:
        raise NotInHousehold("group")
    dates = recent_dates(wall.date())
    grouped: dict[date, list[BucketLine]] = {}
    for day, start, length, nbytes in store.buckets_between(client.id, group.name, dates[-1], dates[0]):
        end = start + timedelta(seconds=length)
        grouped.setdefault(day, []).append(BucketLine(start, length, nbytes, end <= wall))
    days = tuple(DayLine(day, tuple(grouped.get(day, ()))) for day in dates)
    return UsageReport(client.name, group.name, group.quota, store.timezone(), days)


def parse_form(body: bytes) -> dict[str, str]:
    """Return the fields of an application/x-www-form-urlencoded body."""
    parsed = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items() if values}


def respond(
    store: PolicyStore,
    gate: ParentGate,
    *,
    method: str,
    query: Mapping[str, str],
    cookie: str | None,
    form: Mapping[str, str],
    now: datetime,
) -> PageResponse:
    """Return the usage page, the password form, or a closed page.

    now is household-local. The report is included only after the gate accepts
    the session cookie. A password in the query string does not open it.
    """
    if not gate.configured:
        return _response(403, _closed_page())
    if method == "POST":
        if gate.accepts_password(form.get("password", "")):
            return _response(
                303,
                "",
                (("location", _return_to(query)), ("set-cookie", gate.cookie_header())),
            )
        return _response(401, _password_page(query, rejected=True))
    if not gate.accepts_cookie(cookie):
        return _response(200, _password_page(query, rejected=False))
    return _response(200, _signed_in(store, query, now))


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


def format_day(day: date) -> str:
    """Return a household-local date such as Wednesday 21 October 2026."""
    return f"{_WEEKDAYS[day.weekday()]} {day.day} {_MONTHS[day.month - 1]} {day.year}"


def _signed_in(store: PolicyStore, query: Mapping[str, str], now: datetime) -> str:
    clients = store.clients()
    groups = ordered_groups(store.groups())
    client_name = query.get("client", "")
    group_name = query.get("group", "")
    parts = [
        "<h1>Usage</h1>",
        f"<p>{_timezone_line(store.timezone())}</p>",
        f"<p>The last {RECENT_DAYS} days.</p>",
        _chooser(clients, groups, client_name, group_name),
    ]
    if not client_name or not group_name:
        parts.append("<p>Choose a client and a site group.</p>")
    else:
        try:
            report = load_report(store, client_name, group_name, now)
        except NotInHousehold as exc:
            if exc.kind == "client":
                parts.append("<p>That client is not in the household.</p>")
            else:
                parts.append("<p>That site group is not in the household.</p>")
        else:
            parts.append(_report_block(report))
    return _document("\n".join(parts))


def _report_block(report: UsageReport) -> str:
    quota = (
        "No quota on this group."
        if report.quota is None
        else f"Quota: {format_duration(report.quota)}."
    )
    days = "\n".join(_day_section(day) for day in report.days)
    return f"<h2>{_e(report.client)}, {_e(report.group)}</h2>\n<p>{quota}</p>\n{days}"


def _day_section(day: DayLine) -> str:
    heading = format_day(day.day)
    if not day.buckets:
        return f"<section><h3>{heading}</h3><p>no usage</p></section>"
    if day.counted_seconds == 0:
        summary = "Counted time: none yet."
    else:
        summary = f"Counted time: {format_duration(day.counted_seconds)}."
    rows = "\n".join(_bucket_row(bucket) for bucket in day.buckets)
    return (
        "<section>\n"
        f"<h3>{heading}</h3>\n"
        f"<p>{summary}</p>\n"
        "<table>\n"
        "<thead><tr><th>When</th><th>Time</th><th>Bytes</th></tr></thead>\n"
        "<tbody>\n"
        f"{rows}\n"
        "</tbody>\n"
        "</table>\n"
        "</section>"
    )


def _bucket_row(bucket: BucketLine) -> str:
    duration = format_duration(bucket.length_seconds)
    if not bucket.counted:
        duration += ", not counted yet"
    return (
        "<tr>"
        f"<td>{_e(format_span(bucket.start, bucket.length_seconds))}</td>"
        f"<td>{_e(duration)}</td>"
        f"<td>{_e(format_bytes(bucket.byte_count))}</td>"
        "</tr>"
    )


def _chooser(
    clients: Sequence[Client],
    groups: Sequence[SiteGroup],
    client_name: str,
    group_name: str,
) -> str:
    client_options = "\n".join(_option(client.name, client_name) for client in clients)
    group_options = "\n".join(_option(group.name, group_name) for group in groups)
    return (
        '<form method="get" action="/usage">\n'
        '<label for="client">Client</label>\n'
        '<select id="client" name="client">\n'
        f"{client_options}\n"
        "</select>\n"
        '<label for="group">Site group</label>\n'
        '<select id="group" name="group">\n'
        f"{group_options}\n"
        "</select>\n"
        '<button type="submit">Show</button>\n'
        "</form>"
    )


def _option(name: str, chosen: str) -> str:
    selected = " selected" if name == chosen else ""
    escaped = _e(name)
    return f'<option value="{escaped}"{selected}>{escaped}</option>'


def ordered_groups(groups: Sequence[SiteGroup]) -> tuple[SiteGroup, ...]:
    """Return groups lowest priority first, with the default group last."""
    ordinary = sorted((group for group in groups if not group.default), key=lambda group: group.priority)
    default = [group for group in groups if group.default]
    return tuple([*ordinary, *default])


def _password_page(query: Mapping[str, str], *, rejected: bool) -> str:
    notice = "<p>That password is not right.</p>\n" if rejected else ""
    action = _e(_return_to(query))
    return _document(
        "<h1>Usage</h1>\n"
        f"{notice}"
        "<p>Enter the parent password.</p>\n"
        f'<form method="post" action="{action}">\n'
        '<label for="password">Password</label>\n'
        '<input id="password" name="password" type="password" autocomplete="current-password" autofocus>\n'
        '<button type="submit">Open</button>\n'
        "</form>"
    )


def _closed_page() -> str:
    return _document(
        "<h1>Usage</h1>\n"
        "<p>This page is closed until a parent password is set.</p>"
    )


def _timezone_line(timezone: str | None) -> str:
    if timezone:
        return f"Times are {_e(timezone)}."
    return "Times are the timezone of this machine."


def _return_to(query: Mapping[str, str]) -> str:
    kept = [(key, query[key]) for key in ("client", "group") if query.get(key)]
    if not kept:
        return "/usage"
    return "/usage?" + urlencode(kept)


def _document(body: str) -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        "<title>Usage</title>\n"
        "<style>\n"
        "body { font: 16px sans-serif; margin: 2rem auto; max-width: 42rem; line-height: 1.45; }\n"
        "h1 { font-size: 1.4rem; }\n"
        "table { border-collapse: collapse; width: 100%; margin: 0.4rem 0 1.2rem; }\n"
        "th, td { text-align: left; padding: 0.25rem 0.8rem 0.25rem 0;"
        " border-bottom: 1px solid #ccc; vertical-align: top; }\n"
        "form { margin: 1rem 0 1.4rem; }\n"
        "label { margin-right: 0.8rem; }\n"
        "select { margin-right: 0.8rem; }\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        f"{body}\n"
        "</body>\n"
        "</html>\n"
    )


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
