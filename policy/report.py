"""The parent usage report.

The TOML policy still asks for one enrolled client and one site group. A YAML
policy asks for a site group, a client group, or a quota. A site group or a
client group shows the last 14 household-local days. Each day lists the
buckets that contained traffic: the clock times, the length stored for that
bucket, and the bytes. A bucket counts toward the day's time once its end
has passed. A day with no rows says no usage. Traffic that no quota accepts
is listed the same way.

A quota shows one client group's ended time against the time limit and the
stored bytes against the byte limit, including a limit of zero. With no
client group, it lists every client group that has a balance on it.

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
from policy.config import BYTE_UNITS
from policy.gate import ParentGate
from policy.groups import SiteGroup
from policy.hierarchy import Policy
from policy.store import PolicyStore
from policy.usage import UsageStore

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
    site_group: str = ""


@dataclass(frozen=True)
class DayLine:
    day: date
    buckets: tuple[BucketLine, ...]

    @property
    def counted_seconds(self) -> int:
        return sum(bucket.length_seconds for bucket in self.buckets if bucket.counted)

    @property
    def byte_count(self) -> int:
        return sum(bucket.byte_count for bucket in self.buckets)


@dataclass(frozen=True)
class UsageReport:
    client: str
    group: str
    quota: int | None
    byte_limit: int | None
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
    return UsageReport(client.name, group.name, group.quota, group.byte_limit, store.timezone(), days)


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
    limit = ""
    if report.byte_limit is not None:
        limit = f"\n<p>Byte limit: {_e(format_byte_limit(report.byte_limit))}.</p>"
    days = "\n".join(_day_section(day, report.byte_limit) for day in report.days)
    return f"<h2>{_e(report.client)}, {_e(report.group)}</h2>\n<p>{quota}</p>{limit}\n{days}"


def _day_section(day: DayLine, byte_limit: int | None, *, site_column: bool = False) -> str:
    heading = format_day(day.day)
    volume = _volume_line(day, byte_limit)
    if not day.buckets:
        return f"<section><h3>{heading}</h3><p>no usage</p>{volume}</section>"
    if day.counted_seconds == 0:
        summary = "Counted time: none yet."
    else:
        summary = f"Counted time: {format_duration(day.counted_seconds)}."
    rows = "\n".join(_bucket_row(bucket, site_column=site_column) for bucket in day.buckets)
    site_head = "<th>Site group</th>" if site_column else ""
    return (
        "<section>\n"
        f"<h3>{heading}</h3>\n"
        f"<p>{summary}</p>{volume}\n"
        "<table>\n"
        f"<thead><tr><th>When</th>{site_head}<th>Time</th><th>Bytes</th></tr></thead>\n"
        "<tbody>\n"
        f"{rows}\n"
        "</tbody>\n"
        "</table>\n"
        "</section>"
    )


def _volume_line(day: DayLine, byte_limit: int | None) -> str:
    if byte_limit is None:
        return ""
    text = f"Bytes: {format_bytes(day.byte_count)} of {format_byte_limit(byte_limit)}."
    return f"\n<p>{_e(text)}</p>"


def _bucket_row(bucket: BucketLine, *, site_column: bool = False) -> str:
    duration = format_duration(bucket.length_seconds)
    if not bucket.counted:
        duration += ", not counted yet"
    site = f"<td>{_e(bucket.site_group)}</td>" if site_column else ""
    return (
        "<tr>"
        f"<td>{_e(format_span(bucket.start, bucket.length_seconds))}</td>"
        f"{site}"
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


def _option(name: str, chosen: str, label: str | None = None) -> str:
    selected = " selected" if name == chosen else ""
    shown = name if label is None else label
    return f'<option value="{_e(name)}"{selected}>{_e(shown)}</option>'


def ordered_groups(groups: Sequence[SiteGroup]) -> tuple[SiteGroup, ...]:
    """Return groups lowest priority first, with the default group last."""
    ordinary = sorted((group for group in groups if not group.default), key=lambda group: group.priority)
    default = [group for group in groups if group.default]
    return tuple([*ordinary, *default])


def _password_page(
    query: Mapping[str, str],
    *,
    rejected: bool,
    keys: Sequence[str] = ("client", "group"),
) -> str:
    notice = "<p>That password is not right.</p>\n" if rejected else ""
    action = _e(_return_to(query, keys))
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


def _return_to(query: Mapping[str, str], keys: Sequence[str] = ("client", "group")) -> str:
    kept = [(key, query[key]) for key in keys if query.get(key)]
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


_HIERARCHY_KEYS = ("view", "client", "site", "quota")


def respond_hierarchy(
    policy: Policy | None,
    usage: UsageStore,
    gate: ParentGate,
    *,
    method: str,
    query: Mapping[str, str],
    cookie: str | None,
    form: Mapping[str, str],
    now: datetime,
) -> PageResponse:
    """Return the group and quota report, the password form, or a closed page.

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
                (
                    ("location", _return_to(query, _HIERARCHY_KEYS)),
                    ("set-cookie", gate.cookie_header()),
                ),
            )
        return _response(401, _password_page(query, rejected=True, keys=_HIERARCHY_KEYS))
    if not gate.accepts_cookie(cookie):
        return _response(200, _password_page(query, rejected=False, keys=_HIERARCHY_KEYS))
    return _response(200, _hierarchy_signed_in(policy, usage, query, now))


def _hierarchy_signed_in(
    policy: Policy | None,
    usage: UsageStore,
    query: Mapping[str, str],
    now: datetime,
) -> str:
    clients, sites, quotas = _catalog(policy)
    timezone = None if policy is None else policy.timezone
    view = query.get("view", "")
    parts = [
        "<h1>Usage</h1>",
        f"<p>{_timezone_line(timezone)}</p>",
        _hierarchy_chooser(clients, sites, quotas, query),
    ]
    if view == "site":
        parts.append(_site_section(usage, clients, sites, query, now))
    elif view == "client":
        parts.append(_client_section(usage, clients, query, now))
    elif view == "quota":
        parts.append(_quota_section(policy, usage, clients, query, now))
    else:
        parts.append("<p>Choose a site group, a client group, or a quota.</p>")
    return _document("\n".join(parts))


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


def _hierarchy_chooser(
    clients: Sequence[str],
    sites: Sequence[str],
    quotas: Sequence[str],
    query: Mapping[str, str],
) -> str:
    view = query.get("view", "")
    client = query.get("client", "")
    site = query.get("site", "")
    quota = query.get("quota", "")
    view_options = "\n".join(
        _option(value, view, label)
        for value, label in (
            ("", "Choose"),
            ("site", "Site group"),
            ("client", "Client group"),
            ("quota", "Quota"),
        )
    )
    client_options = "\n".join(
        [_option("", client, "All client groups"), *(_option(name, client) for name in clients)]
    )
    site_options = "\n".join([_option("", site, "Choose"), *(_option(name, site) for name in sites)])
    quota_options = "\n".join(
        [_option("", quota, "Choose"), *(_option(name, quota) for name in quotas)]
    )
    return (
        '<form method="get" action="/usage">\n'
        '<label for="view">Show</label>\n'
        '<select id="view" name="view">\n'
        f"{view_options}\n"
        "</select>\n"
        '<label for="client">Client group</label>\n'
        '<select id="client" name="client">\n'
        f"{client_options}\n"
        "</select>\n"
        '<label for="site">Site group</label>\n'
        '<select id="site" name="site">\n'
        f"{site_options}\n"
        "</select>\n"
        '<label for="quota">Quota</label>\n'
        '<select id="quota" name="quota">\n'
        f"{quota_options}\n"
        "</select>\n"
        '<button type="submit">Show</button>\n'
        "</form>"
    )


def _site_section(
    usage: UsageStore,
    clients: Sequence[str],
    sites: Sequence[str],
    query: Mapping[str, str],
    now: datetime,
) -> str:
    client = query.get("client", "")
    site = query.get("site", "")
    if not client or not site:
        return "<p>Choose a client group and a site group.</p>"
    if client not in clients:
        return "<p>That client group is not in the household.</p>"
    if site not in sites:
        return "<p>That site group is not in the household.</p>"
    days = _fill_days(usage.site_buckets(client, site, *_oldest_and_newest(now)), now, with_site=False)
    body = "\n".join(_day_section(day, None) for day in days)
    return f"<h2>{_e(client)}, {_e(site)}</h2>\n<p>The last {RECENT_DAYS} days.</p>\n{body}"


def _client_section(
    usage: UsageStore,
    clients: Sequence[str],
    query: Mapping[str, str],
    now: datetime,
) -> str:
    client = query.get("client", "")
    if not client:
        return "<p>Choose a client group.</p>"
    if client not in clients:
        return "<p>That client group is not in the household.</p>"
    days = _fill_days(usage.client_buckets(client, *_oldest_and_newest(now)), now, with_site=True)
    body = "\n".join(_day_section(day, None, site_column=True) for day in days)
    return f"<h2>{_e(client)}</h2>\n<p>The last {RECENT_DAYS} days.</p>\n{body}"


def _quota_section(
    policy: Policy | None,
    usage: UsageStore,
    clients: Sequence[str],
    query: Mapping[str, str],
    now: datetime,
) -> str:
    name = query.get("quota", "")
    if not name:
        return "<p>Choose a quota.</p>"
    quota = None if policy is None else policy.quota(name)
    if quota is None:
        return "<p>That quota is not in the household.</p>"
    client = query.get("client", "")
    if client and client not in clients:
        return "<p>That client group is not in the household.</p>"
    wall = _wall(now)
    limits = (
        f"<p>Time limit: {_e(format_duration(quota.time_limit))}.</p>\n"
        f"<p>Byte limit: {_e(format_byte_limit(quota.byte_limit))}.</p>"
    )
    day = f"<p>{format_day(wall.date())}</p>"
    if client:
        seconds = usage.ended_seconds(client, name, wall)
        nbytes = usage.stored_bytes(client, name, wall)
        return (
            f"<h2>{_e(client)}, {_e(name)}</h2>\n"
            f"{day}\n"
            f"{limits}\n"
            f"<p>Ended time: {_e(_against(format_duration(seconds), format_duration(quota.time_limit)))}</p>\n"
            f"<p>Stored bytes: {_e(_against(format_bytes(nbytes), format_byte_limit(quota.byte_limit)))}</p>"
        )
    names = usage.quota_clients(name)
    heading = f"<h2>{_e(name)}</h2>\n{day}\n{limits}"
    if not names:
        return heading + "\n<p>No client group has a balance.</p>"
    rows = "\n".join(_balance_row(usage, group, name, quota.time_limit, quota.byte_limit, wall) for group in names)
    return (
        f"{heading}\n"
        "<table>\n"
        "<thead><tr><th>Client group</th><th>Ended time</th><th>Stored bytes</th></tr></thead>\n"
        "<tbody>\n"
        f"{rows}\n"
        "</tbody>\n"
        "</table>"
    )


def _balance_row(
    usage: UsageStore,
    client: str,
    quota: str,
    time_limit: int,
    byte_limit: int,
    wall: datetime,
) -> str:
    seconds = usage.ended_seconds(client, quota, wall)
    nbytes = usage.stored_bytes(client, quota, wall)
    return (
        "<tr>"
        f"<td>{_e(client)}</td>"
        f"<td>{_e(_against(format_duration(seconds), format_duration(time_limit)))}</td>"
        f"<td>{_e(_against(format_bytes(nbytes), format_byte_limit(byte_limit)))}</td>"
        "</tr>"
    )


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
