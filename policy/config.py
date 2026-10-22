"""The household policy file, loaded into SQLite when the service starts.

DNS names are resolved here, once per load, so a decision only does a
dictionary lookup. A name that does not resolve keeps the addresses stored
by the last load that did resolve it. Rules are stored with their group.
A group's quota is stored as a duration in seconds, never as a bucket count.
"""

from __future__ import annotations

import re
import socket
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path

from policy.buckets import divides_day
from policy.clients import Lookup, UnresolvedAddress, resolve_address
from policy.clock import named_zone
from policy.groups import SiteGroup
from policy.rules import REVISION_TASK, Action, Rule, TaskRequirement, TimeWindow, absolute_http_url
from policy.store import DEFAULT_BUCKET_SECONDS, PolicyStore

_UNIT_SECONDS = {"h": 3600, "m": 60, "s": 1}

_CONDITIONS = {"time_window", "tasks_complete", "quota_remaining", "always"}
_ACTIONS = {"continue", "deny", "redirect", "allow"}
_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ClientConfig:
    name: str
    address: str


@dataclass(frozen=True)
class HouseholdConfig:
    timezone: str | None
    clients: tuple[ClientConfig, ...]
    groups: tuple[SiteGroup, ...] = ()
    revision_task: str | None = None
    bucket_length: int = DEFAULT_BUCKET_SECONDS


def load(path: str | Path) -> HouseholdConfig:
    return parse(Path(path).read_text(encoding="utf-8"), str(path))


def parse(text: str, source: str = "policy file") -> HouseholdConfig:
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{source}: {exc}") from exc
    _only(document, {"household", "clients", "groups"}, source)

    household = document.get("household", {})
    if not isinstance(household, dict):
        raise ConfigError(f"{source}: household must be a table")
    _only(household, {"timezone", "revision_task", "bucket_length"}, f"{source}: [household]")
    timezone = household.get("timezone")
    if timezone is not None:
        if not isinstance(timezone, str) or not timezone.strip():
            raise ConfigError(f"{source}: household.timezone must be an IANA name")
        timezone = timezone.strip()
        try:
            named_zone(timezone)
        except ValueError as exc:
            raise ConfigError(f"{source}: household.timezone: {exc}") from exc
    revision_task = _revision_task(household.get("revision_task"), source)
    if "bucket_length" in household:
        bucket_length = _duration(household["bucket_length"], f"{source}: household.bucket_length")
        if bucket_length < 1:
            raise ConfigError(f"{source}: household.bucket_length must be at least one second")
        if not divides_day(bucket_length):
            raise ConfigError(
                f"{source}: household.bucket_length must divide a 24-hour day "
                "with nothing left over, so the buckets meet midnight"
            )
    else:
        bucket_length = DEFAULT_BUCKET_SECONDS

    entries = document.get("clients", [])
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ConfigError(f"{source}: clients must be written as [[clients]] tables")
    clients: list[ClientConfig] = []
    for number, entry in enumerate(entries, start=1):
        where = f"{source}: client {number}"
        _only(entry, {"name", "address"}, where)
        name = _text(entry, "name", where)
        address = _text(entry, "address", where)
        if any(client.name == name for client in clients):
            raise ConfigError(f"{where}: the name {name!r} is used twice")
        clients.append(ClientConfig(name, address))
    groups = _groups(document, source)
    if _uses_revision_token(groups) and revision_task is None:
        raise ConfigError(
            f"{source}: a rule redirects to revision_task, but household.revision_task is not set"
        )
    return HouseholdConfig(timezone, tuple(clients), groups, revision_task, bucket_length)


def _groups(document: dict, source: str) -> tuple[SiteGroup, ...]:
    entries = document.get("groups", [])
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ConfigError(f"{source}: groups must be written as [[groups]] tables")
    groups: list[SiteGroup] = []
    for number, entry in enumerate(entries, start=1):
        where = f"{source}: group {number}"
        _only(entry, {"name", "priority", "patterns", "default", "rules", "quota"}, where)
        name = _text(entry, "name", where)
        priority = entry.get("priority")
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise ConfigError(f"{where}: priority must be a whole number")
        patterns = entry.get("patterns", [])
        if not isinstance(patterns, list) or not all(
            isinstance(pattern, str) and pattern.strip() for pattern in patterns
        ):
            raise ConfigError(f"{where}: patterns must be a list of non-empty strings")
        default = entry.get("default", False)
        if not isinstance(default, bool):
            raise ConfigError(f"{where}: default must be true or false")
        for other in groups:
            if other.name == name:
                raise ConfigError(f"{where}: the name {name!r} is used twice")
            if other.priority == priority:
                raise ConfigError(
                    f"{source}: groups {other.name!r} and {name!r} both have priority {priority}"
                )
            if other.default and default:
                raise ConfigError(f"{source}: groups {other.name!r} and {name!r} are both the default")
        quota = _duration(entry["quota"], f"{where}: quota") if "quota" in entry else None
        groups.append(
            SiteGroup(
                name,
                priority,
                tuple(pattern.strip() for pattern in patterns),
                default,
                _rules(entry.get("rules", []), where),
                quota,
            )
        )
    return tuple(groups)


def _rules(entries: object, where: str) -> tuple[Rule, ...]:
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ConfigError(f"{where}: rules must be written as [[groups.rules]] tables")
    return tuple(
        _rule(entry, f"{where}: rule {number}") for number, entry in enumerate(entries, start=1)
    )


def _rule(entry: dict, where: str) -> Rule:
    _only(entry, {"condition", "when_true", "when_false", "windows", "required", "weekdays"}, where)
    condition = entry.get("condition")
    if condition not in _CONDITIONS:
        raise ConfigError(
            f"{where}: condition must be time_window, tasks_complete, quota_remaining, or always"
        )
    if "when_true" not in entry or "when_false" not in entry:
        raise ConfigError(f"{where}: when_true and when_false are both required")
    if condition == "time_window":
        if "required" in entry or "weekdays" in entry:
            raise ConfigError(f"{where}: time_window does not take a required count")
        windows_value = entry.get("windows", [])
        if not isinstance(windows_value, list) or not windows_value:
            raise ConfigError(f"{where}: time_window needs at least one window")
        windows = tuple(
            _window(window, f"{where}: window {number}")
            for number, window in enumerate(windows_value, start=1)
        )
    elif "windows" in entry:
        raise ConfigError(f"{where}: {condition} does not take windows")
    else:
        windows = ()
    if condition == "tasks_complete":
        requirement = _requirement(entry, where)
    elif "required" in entry or "weekdays" in entry:
        raise ConfigError(f"{where}: {condition} does not take a required count")
    else:
        requirement = None
    return Rule(
        condition,
        _action(entry["when_true"], f"{where}: when_true"),
        _action(entry["when_false"], f"{where}: when_false"),
        windows,
        requirement,
    )


def _requirement(entry: dict, where: str) -> TaskRequirement:
    if "required" not in entry:
        raise ConfigError(f"{where}: tasks_complete needs a required count")
    required = _count(entry["required"], f"{where}: required")
    rows = entry.get("weekdays", [])
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ConfigError(f"{where}: weekdays must be written as [[groups.rules.weekdays]] tables")
    overrides: list[tuple[int, int]] = []
    seen: set[int] = set()
    for number, row in enumerate(rows, start=1):
        place = f"{where}: weekday {number}"
        _only(row, {"day", "required"}, place)
        if "day" not in row:
            raise ConfigError(f"{place}: day is required")
        weekday = _weekday(row["day"], place)
        if weekday in seen:
            name = row["day"].strip().lower() if isinstance(row["day"], str) else row["day"]
            raise ConfigError(f"{place}: {name} is listed twice")
        seen.add(weekday)
        if "required" not in row:
            raise ConfigError(f"{place}: needs a required count")
        overrides.append((weekday, _count(row["required"], f"{place}: required")))
    return TaskRequirement(required, tuple(sorted(overrides)))


def _weekday(value: object, where: str) -> int:
    name = value.strip().lower() if isinstance(value, str) else ""
    number = _WEEKDAYS.get(name)
    if number is None:
        raise ConfigError(f"{where}: {value!r} is not a weekday")
    return number


def _count(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError(f"{where} must be a whole number, zero or more")
    return value


def _duration(value: object, where: str) -> int:
    """Return seconds for a duration such as 2h, 120m, or 7200s.

    A bare number is rejected. It would be ambiguous with a count of buckets,
    and the quota is a length of time, not a number of buckets.
    """
    text = value.strip() if isinstance(value, str) else ""
    match = re.fullmatch(r"(\d+)([hms])", text, re.IGNORECASE)
    if match is None:
        raise ConfigError(
            f"{where} must be a duration like 2h, 120m, or 7200s, not a number of buckets"
        )
    return int(match.group(1)) * _UNIT_SECONDS[match.group(2).lower()]


def _window(entry: object, where: str) -> TimeWindow:
    if not isinstance(entry, dict):
        raise ConfigError(f"{where} must be a table")
    _only(entry, {"start", "end", "days"}, where)
    if "start" not in entry or "end" not in entry:
        raise ConfigError(f"{where}: start and end are required")
    start = _clock(entry["start"], f"{where}: start")
    end = _clock(entry["end"], f"{where}: end")
    if start == end:
        raise ConfigError(f"{where}: start and end are the same, and the end is exclusive")
    weekdays = _weekdays(entry["days"], where) if "days" in entry else None
    return TimeWindow(start, end, weekdays)


def _clock(value: object, where: str) -> time:
    if isinstance(value, time):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = time.fromisoformat(value)
        except ValueError:
            raise ConfigError(f"{where} must be a time like 07:00") from None
    else:
        raise ConfigError(f"{where} must be a time like 07:00")
    if parsed.tzinfo is not None:
        raise ConfigError(f"{where} must be a time without a timezone")
    return parsed.replace(tzinfo=None)


def _weekdays(value: object, where: str) -> frozenset[int]:
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{where}: days must list at least one weekday, or be left out")
    found: list[int] = []
    for day in value:
        name = day.strip().lower() if isinstance(day, str) else ""
        number = _WEEKDAYS.get(name)
        if number is None:
            raise ConfigError(f"{where}: {day!r} is not a weekday")
        if number in found:
            raise ConfigError(f"{where}: {name} is listed twice")
        found.append(number)
    return frozenset(found)


def _action(value: object, where: str) -> Action:
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a table")
    _only(value, {"action", "message", "location"}, where)
    kind = value.get("action")
    if kind not in _ACTIONS:
        raise ConfigError(f"{where}: action must be continue, deny, redirect, or allow")
    if kind in {"continue", "allow"}:
        if "message" in value or "location" in value:
            raise ConfigError(f"{where}: {kind} takes no other settings")
        return Action(kind)
    if kind == "deny":
        if "location" in value:
            raise ConfigError(f"{where}: deny takes a message, not a location")
        message = value.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ConfigError(f"{where}: deny needs a message")
        return Action("deny", message.strip())
    if "message" in value:
        raise ConfigError(f"{where}: redirect takes a location, not a message")
    location = value.get("location")
    if not isinstance(location, str) or not location.strip():
        raise ConfigError(f"{where}: redirect needs a location")
    location = location.strip()
    if location != REVISION_TASK and not absolute_http_url(location):
        raise ConfigError(
            f"{where}: location must be an absolute http or https URL, or revision_task"
        )
    return Action("redirect", location=location)


def _revision_task(value: object, source: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not absolute_http_url(value.strip()):
        raise ConfigError(f"{source}: household.revision_task must be an absolute http or https URL")
    return value.strip()


def _uses_revision_token(groups: tuple[SiteGroup, ...]) -> bool:
    return any(
        action.location == REVISION_TASK
        for group in groups
        for rule in group.rules
        for action in (rule.when_true, rule.when_false)
    )


def apply(
    config: HouseholdConfig,
    store: PolicyStore,
    lookup: Lookup = socket.getaddrinfo,
    warn: Callable[[str], None] = lambda message: print(message, flush=True),
    loaded_at: datetime | None = None,
) -> None:
    """Store the timezone, clients and site groups, resolving each client address to IPs.

    loaded_at is the household-local time of this load. A change of bucket
    length uses it to close buckets that are still open. The same length does
    not. An aware value is already household-local; its offset is dropped.
    """
    stored = {client.name: client for client in store.clients()}
    fresh: dict[str, tuple[str, ...]] = {}
    kept: dict[str, tuple[str, ...]] = {}
    for client in config.clients:
        try:
            fresh[client.name] = resolve_address(client.address, lookup)
        except UnresolvedAddress as exc:
            previous = stored.get(client.name)
            if previous and previous.address == client.address and previous.ips:
                kept[client.name] = previous.ips
                warn(f"client {client.name}: {exc}; keeping {', '.join(previous.ips)}")
            else:
                warn(f"client {client.name}: {exc}; it has no IP until the name resolves")

    owners: dict[str, str] = {}
    for name, ips in fresh.items():
        for ip in ips:
            if ip in owners:
                raise ConfigError(f"clients {owners[ip]!r} and {name!r} both have the IP {ip}")
            owners[ip] = name
    for name, ips in list(kept.items()):
        stale = [ip for ip in ips if ip in owners]
        if stale:
            warn(f"client {name}: dropping {', '.join(stale)}, now used by another client")
        kept[name] = tuple(ip for ip in ips if ip not in owners)

    store.save_household(
        config.timezone,
        [
            (client.name, client.address, fresh.get(client.name) or kept.get(client.name, ()))
            for client in config.clients
        ],
        config.groups,
        config.revision_task,
        config.bucket_length,
        loaded_at,
    )


def _only(table: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown setting {', '.join(unknown)}")


def _text(entry: dict, key: str, where: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where}: {key} is required")
    return value.strip()
