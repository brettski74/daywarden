"""The usage graph and its presets.

The parent portal's Minutes and Bytes pages draw usage over a period as one
line per client group, site group, or quota, or one line of the total. The
page's address holds the settings: the chosen client groups, site groups,
and quotas, the Group by, and the date range, or the name of a preset that
holds them. The data endpoint takes the same query string, so the page only
draws what ``usage_graph`` returns.

Everything here is household-local wall time without an offset, as the usage
ledger stores it. A week runs from Sunday to Saturday.

The ledger keeps the site group on its client group rows and the quota on its
quota rows, never both on one row. Settings that would need both, such as a
site group chosen while grouping by quota, are fitted by leaving one out and
saying so.

A preset is a named set of the settings, kept in ``usage_presets``. Default
always exists. Until it is first replaced it is every group and quota,
grouped by client group, over the past week.
"""

from __future__ import annotations

import json
import re
import sqlite3
from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta

from policy.hierarchy import Policy
from policy.report import format_day, timezone_note
from policy.usage import UsageStore

UNITS = ("minutes", "bytes")
RANGES = (
    "today",
    "yesterday",
    "this-week",
    "this-month",
    "past-week",
    "past-month",
    "previous-week",
    "previous-month",
    "custom",
)
GROUP_BY = ("client", "site", "quota", "none")
SETTING_KEYS = ("client", "site", "quota", "by", "range", "from", "to")
DEFAULT_PRESET = "Default"
TOTAL = "Total"
LONGEST_NAME = 60
HOURLY_UP_TO = timedelta(days=2)
DAILY_UP_TO = timedelta(days=92)
MOST_TICKS = 12

_DAY_TEXT = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_SHORT_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_SHORT_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_KINDS = {"client": "client group", "site": "site group", "quota": "quota"}
_NOT_A_DATE = "is not a date. Use yyyy-mm-dd, such as 2026-10-31."
_QUOTA_SITE = "usage by quota is not kept per site group"


@dataclass(frozen=True)
class Settings:
    """What a graph shows. ``first`` and ``last`` are the Custom range's days, `yyyy-mm-dd`."""

    clients: tuple[str, ...] = ()
    sites: tuple[str, ...] = ()
    quotas: tuple[str, ...] = ()
    by: str = "client"
    range: str = "past-week"
    first: str = ""
    last: str = ""

    def as_json(self) -> dict:
        return {
            "client": list(self.clients),
            "site": list(self.sites),
            "quota": list(self.quotas),
            "by": self.by,
            "range": self.range,
            "from": self.first,
            "to": self.last,
        }

    def same_as(self, other: Settings) -> bool:
        """Whether both show the same graph. The order of the chosen names does not matter."""
        return _key(self) == _key(other)


BUILT_IN_DEFAULT = Settings()


@dataclass(frozen=True)
class Catalog:
    """The household's client groups, site groups, and quotas, in the order the pull-downs list them."""

    clients: tuple[str, ...]
    sites: tuple[str, ...]
    quotas: tuple[str, ...]

    def names(self, kind: str) -> tuple[str, ...]:
        return {"client": self.clients, "site": self.sites, "quota": self.quotas}[kind]


@dataclass(frozen=True)
class Answer:
    status: int
    body: dict


def catalog(policy: Policy | None) -> Catalog:
    """Return the household's names, with ``default`` among the client groups and the site groups."""
    if policy is None:
        return Catalog(("default",), ("default",), ())
    clients = [group.name for group in policy.client_groups]
    if "default" not in clients:
        clients.append("default")
    sites = [group.name for group in sorted(policy.site_groups, key=lambda group: group.priority)]
    if "default" not in sites:
        sites.append("default")
    return Catalog(tuple(clients), tuple(sites), tuple(quota.name for quota in policy.quotas))


def settings_from_query(pairs: Iterable[tuple[str, str]]) -> tuple[Settings, list[str]]:
    """Read the settings a page address names, and say what was not a choice.

    ``client``, ``site``, and ``quota`` may each appear any number of times.
    A missing or unknown Group by or date range is the built-in default's.
    """
    found: dict[str, list[str]] = {}
    for key, value in pairs:
        found.setdefault(key, []).append(value)
    notes: list[str] = []
    by = _last(found, "by") or BUILT_IN_DEFAULT.by
    if by not in GROUP_BY:
        notes.append(f"Group by {by} is not a choice, so the graph is grouped by client group.")
        by = BUILT_IN_DEFAULT.by
    chosen_range = _last(found, "range") or BUILT_IN_DEFAULT.range
    if chosen_range not in RANGES:
        notes.append(f"{chosen_range} is not a date range, so the graph shows the past week.")
        chosen_range = BUILT_IN_DEFAULT.range
    custom = chosen_range == "custom"
    settings = Settings(
        clients=_names(found.get("client", ())),
        sites=_names(found.get("site", ())),
        quotas=_names(found.get("quota", ())),
        by=by,
        range=chosen_range,
        first=(_last(found, "from") or "").strip() if custom else "",
        last=(_last(found, "to") or "").strip() if custom else "",
    )
    return settings, notes


def settings_from_json(document: object) -> Settings | None:
    """Return the settings a preset holds, or None when they are not settings."""
    if not isinstance(document, dict):
        return None
    lists = {key: document.get(key, []) for key in ("client", "site", "quota")}
    if any(not isinstance(value, list) or not all(isinstance(name, str) for name in value) for value in lists.values()):
        return None
    texts = {key: document.get(key, "") for key in ("by", "range", "from", "to")}
    if any(not isinstance(value, str) for value in texts.values()):
        return None
    if texts["by"] not in GROUP_BY or texts["range"] not in RANGES:
        return None
    custom = texts["range"] == "custom"
    return Settings(
        clients=_names(lists["client"]),
        sites=_names(lists["site"]),
        quotas=_names(lists["quota"]),
        by=texts["by"],
        range=texts["range"],
        first=texts["from"].strip() if custom else "",
        last=texts["to"].strip() if custom else "",
    )


def fit(settings: Settings, names: Catalog) -> tuple[Settings, list[str]]:
    """Fit settings to the household, and say what was left out.

    A name no longer in the policy is left out. Site groups and quotas are
    never used together: grouping by quota leaves out the site groups,
    grouping by site group leaves out the quotas, and with both chosen the
    site groups are left out. Chosen names come back in the pull-downs' order.
    """
    missing: list[str] = []
    chosen: dict[str, tuple[str, ...]] = {}
    for kind, picked in (("client", settings.clients), ("site", settings.sites), ("quota", settings.quotas)):
        known = names.names(kind)
        gone = [name for name in picked if name not in known]
        if gone:
            missing.append(_kind_phrase(kind, gone))
        chosen[kind] = tuple(name for name in known if name in picked)
    notes = [f"Left out {_and(missing)}, which the policy no longer has."] if missing else []
    if chosen["site"] and (settings.by == "quota" or chosen["quota"]):
        notes.append(f"Left out the site groups, because {_QUOTA_SITE}.")
        chosen["site"] = ()
    if chosen["quota"] and settings.by == "site":
        notes.append(f"Left out the quotas, because {_QUOTA_SITE}.")
        chosen["quota"] = ()
    return replace(settings, clients=chosen["client"], sites=chosen["site"], quotas=chosen["quota"]), notes


def custom_problems(settings: Settings) -> list[str]:
    """Return why a Custom range cannot be drawn, or nothing."""
    if settings.range != "custom":
        return []
    first, last = parse_day(settings.first), parse_day(settings.last)
    problems = []
    if first is None:
        problems.append(f"From {_NOT_A_DATE}")
    if last is None:
        problems.append(f"To {_NOT_A_DATE}")
    if first is not None and last is not None and last < first:
        problems.append("To is before From.")
    return problems


def parse_day(text: str) -> date | None:
    if not _DAY_TEXT.match(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def resolve_range(name: str, now: datetime, first: date | None = None, last: date | None = None) -> tuple[datetime, datetime]:
    """Return the start and the end, not included, of a date range at now.

    A week starts on Sunday. Past week and past month end now and start at
    the same clock time a week or a month earlier, on the last day of that
    month when it is shorter. Custom covers first through last, whole days.
    """
    now = _wall(now)
    midnight = datetime.combine(now.date(), time.min)
    week = midnight - timedelta(days=(now.weekday() + 1) % 7)
    month = midnight.replace(day=1)
    if name == "today":
        return midnight, now
    if name == "yesterday":
        return midnight - timedelta(days=1), midnight
    if name == "this-week":
        return week, now
    if name == "this-month":
        return month, now
    if name == "past-week":
        return now - timedelta(days=7), now
    if name == "past-month":
        return _months_back(now, 1), now
    if name == "previous-week":
        return week - timedelta(days=7), week
    if name == "previous-month":
        return _months_back(month, 1), month
    if name == "custom":
        if first is None or last is None:
            raise ValueError("a custom range needs its first and last days")
        return datetime.combine(first, time.min), datetime.combine(last + timedelta(days=1), time.min)
    raise ValueError(f"unknown date range {name!r}")


def intervals(start: datetime, end: datetime) -> tuple[str, list[tuple[datetime, datetime]]]:
    """Return the interval of the points and each point's span, clipped to the range.

    Two days or less is one point per hour, up to 92 days one per day, and
    longer one per week, Sunday to Saturday. A point at either end that is
    only partly inside the range covers only the part inside it.
    """
    length = end - start
    if length <= HOURLY_UP_TO:
        kind, step, boundary = "hour", timedelta(hours=1), start.replace(minute=0, second=0, microsecond=0)
    elif length <= DAILY_UP_TO:
        kind, step, boundary = "day", timedelta(days=1), datetime.combine(start.date(), time.min)
    else:
        sunday = start.date() - timedelta(days=(start.weekday() + 1) % 7)
        kind, step, boundary = "week", timedelta(days=7), datetime.combine(sunday, time.min)
    spans = []
    while boundary < end:
        spans.append((max(boundary, start), min(boundary + step, end)))
        boundary += step
    return kind, spans


def describe_range(start: datetime, end: datetime) -> str:
    """Return what a range covers, such as Friday 6 November 2026 21:30 to Friday 13 November 2026 21:30."""
    if start.time() == time.min and end.time() == time.min and end > start:
        return _days(start.date(), (end - timedelta(days=1)).date())
    if start.date() == end.date():
        return f"{format_day(start.date())} {_clock(start)} to {_clock(end)}"
    return f"{format_day(start.date())} {_clock(start)} to {format_day(end.date())} {_clock(end)}"


def usage_graph(
    policy: Policy | None,
    usage: UsageStore,
    presets: Presets,
    pairs: Sequence[tuple[str, str]],
    now: datetime,
    unit: str,
) -> dict:
    """Return the graph a page address asks for, with the choices and presets around it.

    ``preset`` names the preset whose settings are on show, or is empty.
    ``notes`` says what the status bar should, such as a preset that does not
    exist or a group the policy no longer has. ``graph`` is None when a
    Custom range cannot be drawn.
    """
    if unit not in UNITS:
        raise ValueError(f"unknown unit {unit!r}")
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
    settings, fitted = fit(raw, names)
    notes.extend(fitted)
    if not on_show:
        on_show = next(
            (name for name, held in presets.every() if fit(held, names)[0].same_as(settings)),
            "",
        )
    problems = custom_problems(settings)
    notes.extend(problems)
    answer = {
        "unit": unit,
        "today": now.date().isoformat(),
        "choices": {"clients": list(names.clients), "sites": list(names.sites), "quotas": list(names.quotas)},
        "settings": settings.as_json(),
        "preset": on_show,
        "presets": presets.names(),
        "notes": notes,
        "times": timezone_note(None if policy is None else policy.timezone),
        "range": None,
        "days": None,
        "graph": None,
    }
    if problems:
        return answer
    start, end = resolve_range(settings.range, now, parse_day(settings.first), parse_day(settings.last))
    last_day = (end - timedelta(seconds=1)).date() if end > start else start.date()
    answer["range"] = describe_range(start, end)
    answer["days"] = {"from": start.date().isoformat(), "to": last_day.isoformat()}
    answer["graph"] = _graph(usage, names, settings, start, end, now, unit)
    return answer


def _graph(
    usage: UsageStore,
    names: Catalog,
    settings: Settings,
    start: datetime,
    end: datetime,
    now: datetime,
    unit: str,
) -> dict:
    kind, spans = intervals(start, end)
    starts = [span_start for span_start, _span_end in spans]
    by_quota = bool(settings.quotas) or settings.by == "quota"
    wanted = settings.quotas if by_quota else settings.sites
    sums: dict[str, list[int]] = {}
    seen: set[str] = set()
    for client, name, started, length, nbytes in usage.rows_between("quota" if by_quota else "site", start, end):
        if settings.clients and client not in settings.clients:
            continue
        if wanted and name not in wanted:
            continue
        line = TOTAL if settings.by == "none" else client if settings.by == "client" else name
        seen.add(line)
        if unit == "minutes":
            if started + timedelta(seconds=length) > now:
                continue
            value = length
        else:
            value = nbytes
        values = sums.setdefault(line, [0] * len(spans))
        values[bisect_right(starts, started) - 1] += value
    return {
        "length": int((end - start).total_seconds()),
        "interval": kind,
        "ticks": _ticks(kind, start, end),
        "points": [
            {
                "at": int(((a - start) + (b - a) / 2).total_seconds()),
                "label": _span_label(kind, a, b),
            }
            for a, b in spans
        ],
        "lines": [
            {"name": line, "values": sums.get(line, [0] * len(spans))}
            for line in _lines(settings, names, seen)
        ],
    }


def _lines(settings: Settings, names: Catalog, seen: set[str]) -> list[str]:
    """Return the lines to draw: the chosen groups, or every one with usage, in the pull-downs' order."""
    if settings.by == "none":
        return [TOTAL]
    chosen = {"client": settings.clients, "site": settings.sites, "quota": settings.quotas}[settings.by]
    if chosen:
        return list(chosen)
    known = names.names(settings.by)
    return [name for name in known if name in seen] + sorted(seen - set(known), key=str.casefold)


def _ticks(kind: str, start: datetime, end: datetime) -> list[dict]:
    """Return the labelled marks along the time axis, no more than MOST_TICKS of them."""
    if kind == "hour":
        marks = _boundaries(start.replace(minute=0, second=0), start, end, timedelta(hours=1))
        step = next((hours for hours in (1, 2, 3, 4, 6, 12, 24) if len(marks) / hours <= MOST_TICKS), 24)
        marks = [mark for mark in marks if mark.hour % step == 0]
    elif kind == "day":
        marks = _boundaries(datetime.combine(start.date(), time.min), start, end, timedelta(days=1))
        if len(marks) > 2 * MOST_TICKS:
            marks = _every([mark for mark in marks if mark.weekday() == 6])
        else:
            marks = _every(marks)
    else:
        sunday = start.date() - timedelta(days=(start.weekday() + 1) % 7)
        marks = _every(_boundaries(datetime.combine(sunday, time.min), start, end, timedelta(days=7)))
    return [{"at": int((mark - start).total_seconds()), "label": _tick_label(kind, mark)} for mark in marks]


def _boundaries(first: datetime, start: datetime, end: datetime, step: timedelta) -> list[datetime]:
    """Return first and every step after it, from start through end."""
    found = []
    mark = first
    while mark <= end:
        if mark >= start:
            found.append(mark)
        mark += step
    return found


def _every(marks: list[datetime]) -> list[datetime]:
    step = max(1, -(-len(marks) // MOST_TICKS))
    return marks[::step]


def _tick_label(kind: str, mark: datetime) -> str:
    if kind == "hour" and (mark.hour, mark.minute) != (0, 0):
        return _clock(mark)
    if kind == "week":
        return f"{mark.day} {_SHORT_MONTHS[mark.month - 1]} {mark.year}"
    return f"{_SHORT_WEEKDAYS[mark.weekday()]} {mark.day} {_SHORT_MONTHS[mark.month - 1]}"


def _span_label(kind: str, start: datetime, end: datetime) -> str:
    """Return the interval a point covers, such as Tuesday 10 November 2026."""
    whole_days = start.time() == time.min and end.time() == time.min
    if kind == "week" or (kind == "day" and whole_days):
        return _days(start.date(), (end - timedelta(seconds=1)).date())
    finish = "24:00" if end.time() == time.min and end.date() != start.date() else _clock(end)
    return f"{format_day(start.date())} {_clock(start)} to {finish}"


def _days(first: date, last: date) -> str:
    if first == last:
        return format_day(first)
    return f"{format_day(first)} to {format_day(last)}"


class Presets:
    """Named settings for the usage graph, kept in ``usage_presets``.

    Names are told apart without regard to case. Default always exists, and is
    the built-in default until a preset is saved under its name.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS usage_presets ("
            "name TEXT PRIMARY KEY COLLATE NOCASE, "
            "settings TEXT NOT NULL, "
            "saved_at TEXT NOT NULL, "
            "saved_by TEXT NOT NULL)"
        )
        self.connection.commit()

    def every(self) -> list[tuple[str, Settings]]:
        """Return every preset by name, in alphabetical order, Default among them."""
        found: dict[str, tuple[str, Settings]] = {DEFAULT_PRESET.casefold(): (DEFAULT_PRESET, BUILT_IN_DEFAULT)}
        for name, raw in self.connection.execute("SELECT name, settings FROM usage_presets"):
            held = settings_from_json(json.loads(raw))
            if held is not None:
                found[name.casefold()] = (name, held)
        return sorted(found.values(), key=lambda item: (item[0].casefold(), item[0]))

    def names(self) -> list[str]:
        return [name for name, _settings in self.every()]

    def find(self, name: str) -> tuple[str, Settings] | None:
        """Return a preset's name as saved and its settings, or None when there is none of that name."""
        return next(((saved, held) for saved, held in self.every() if saved.casefold() == name.casefold()), None)

    def settings(self, name: str) -> Settings:
        found = self.find(name)
        if found is None:
            raise KeyError(name)
        return found[1]

    def save(self, body: Mapping[str, object], username: str, now: datetime) -> Answer:
        """Save the settings under a name. A name already used is replaced only when ``replace`` is true."""
        name = body.get("name")
        problem = _name_problem(name)
        if problem is not None:
            return Answer(400, {"error": problem})
        assert isinstance(name, str)
        name = name.strip()
        held = settings_from_json(body.get("settings"))
        if held is None:
            return Answer(400, {"error": "Those are not settings for the usage graph."})
        problems = custom_problems(held)
        if problems:
            return Answer(400, {"error": " ".join(problems)})
        existing = self.find(name)
        if existing is not None and body.get("replace") is not True:
            return Answer(409, {"error": f"There is already a preset called {existing[0]}.", "exists": True})
        saved_name = name if existing is None else existing[0]
        with self.connection:
            self.connection.execute(
                "INSERT INTO usage_presets (name, settings, saved_at, saved_by) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (name) DO UPDATE SET settings = excluded.settings, "
                "saved_at = excluded.saved_at, saved_by = excluded.saved_by",
                (
                    saved_name,
                    json.dumps(held.as_json(), separators=(",", ":")),
                    _wall(now).isoformat(timespec="seconds"),
                    username,
                ),
            )
        verb = "Replaced" if existing is not None else "Saved"
        return Answer(200, {"name": saved_name, "message": f"{verb} preset {saved_name}."})

    def delete(self, body: Mapping[str, object]) -> Answer:
        name = body.get("name")
        if not isinstance(name, str) or not name.strip():
            return Answer(400, {"error": "Name the preset to delete."})
        name = name.strip()
        if name.casefold() == DEFAULT_PRESET.casefold():
            return Answer(400, {"error": f"{DEFAULT_PRESET} can be replaced but not deleted."})
        existing = self.find(name)
        if existing is None:
            return Answer(404, {"error": f"There is no preset called {name}."})
        with self.connection:
            self.connection.execute("DELETE FROM usage_presets WHERE name = ?", (existing[0],))
        return Answer(200, {"name": existing[0], "message": f"Deleted preset {existing[0]}."})


def _name_problem(name: object) -> str | None:
    if not isinstance(name, str) or not name.strip():
        return "Give the preset a name."
    if len(name.strip()) > LONGEST_NAME:
        return f"A preset name is at most {LONGEST_NAME} characters."
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in name):
        return "A preset name cannot hold control characters."
    return None


def _key(settings: Settings) -> tuple:
    custom = settings.range == "custom"
    return (
        frozenset(settings.clients),
        frozenset(settings.sites),
        frozenset(settings.quotas),
        settings.by,
        settings.range,
        settings.first if custom else "",
        settings.last if custom else "",
    )


def _names(values: Iterable[str]) -> tuple[str, ...]:
    """Return the non-empty names once each, in the order given."""
    found: list[str] = []
    for value in values:
        name = value.strip()
        if name and name not in found:
            found.append(name)
    return tuple(found)


def _last(found: Mapping[str, list[str]], key: str) -> str | None:
    values = found.get(key)
    return values[-1] if values else None


def _last_value(pairs: Sequence[tuple[str, str]], key: str) -> str | None:
    values = [value for name, value in pairs if name == key]
    return values[-1] if values else None


def _kind_phrase(kind: str, names: Sequence[str]) -> str:
    noun = _KINDS[kind] + ("s" if len(names) > 1 else "")
    return f"{noun} {_and(names)}"


def _and(items: Sequence[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _months_back(moment: datetime, count: int) -> datetime:
    index = moment.year * 12 + (moment.month - 1) - count
    year, month = divmod(index, 12)
    month += 1
    following = date(year + (month == 12), month % 12 + 1, 1)
    longest = (following - timedelta(days=1)).day
    return moment.replace(year=year, month=month, day=min(moment.day, longest))


def _clock(moment: datetime) -> str:
    return moment.strftime("%H:%M")


def _wall(moment: datetime) -> datetime:
    """Return household-local time to the second, offset dropped rather than converted."""
    if moment.tzinfo is not None:
        moment = moment.replace(tzinfo=None)
    return moment.replace(microsecond=0)
