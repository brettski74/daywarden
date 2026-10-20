"""The household policy file, loaded into SQLite when the service starts.

DNS names are resolved here, once per load, so a decision only does a
dictionary lookup. A name that does not resolve keeps the addresses stored
by the last load that did resolve it.
"""

from __future__ import annotations

import socket
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from policy.clients import Lookup, UnresolvedAddress, resolve_address
from policy.clock import named_zone
from policy.groups import SiteGroup
from policy.store import PolicyStore


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
    _only(household, {"timezone"}, f"{source}: [household]")
    timezone = household.get("timezone")
    if timezone is not None:
        if not isinstance(timezone, str) or not timezone.strip():
            raise ConfigError(f"{source}: household.timezone must be an IANA name")
        timezone = timezone.strip()
        try:
            named_zone(timezone)
        except ValueError as exc:
            raise ConfigError(f"{source}: household.timezone: {exc}") from exc

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
    return HouseholdConfig(timezone, tuple(clients), _groups(document, source))


def _groups(document: dict, source: str) -> tuple[SiteGroup, ...]:
    entries = document.get("groups", [])
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ConfigError(f"{source}: groups must be written as [[groups]] tables")
    groups: list[SiteGroup] = []
    for number, entry in enumerate(entries, start=1):
        where = f"{source}: group {number}"
        _only(entry, {"name", "priority", "patterns", "default"}, where)
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
        groups.append(SiteGroup(name, priority, tuple(pattern.strip() for pattern in patterns), default))
    return tuple(groups)


def apply(
    config: HouseholdConfig,
    store: PolicyStore,
    lookup: Lookup = socket.getaddrinfo,
    warn: Callable[[str], None] = lambda message: print(message, flush=True),
) -> None:
    """Store the timezone, clients and site groups, resolving each client address to IPs."""
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
