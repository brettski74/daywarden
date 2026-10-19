"""Which household computer a source IP belongs to."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass

Lookup = Callable[..., list]


@dataclass(frozen=True)
class Client:
    id: int
    name: str
    address: str
    ips: tuple[str, ...]


class UnresolvedAddress(LookupError):
    pass


def normalize_ip(value: str) -> str | None:
    """Return the canonical text of an IP address, or None when value is not one.

    An IPv4-mapped IPv6 address becomes the IPv4 address it carries, so a
    dual-stack listener and an IPv4 config entry agree.
    """
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return str(address)


def resolve_address(address: str, lookup: Lookup = socket.getaddrinfo) -> tuple[str, ...]:
    """Return the IPs for a configured address, which is an IP or a DNS name."""
    literal = normalize_ip(address)
    if literal is not None:
        return (literal,)
    try:
        answers = lookup(address, None, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise UnresolvedAddress(f"{address}: {exc}") from exc
    ips: list[str] = []
    for answer in answers:
        ip = normalize_ip(str(answer[4][0]))
        if ip is not None and ip not in ips:
            ips.append(ip)
    if not ips:
        raise UnresolvedAddress(f"{address}: no addresses")
    return tuple(ips)


class ClientDirectory:
    def __init__(self, clients: Iterable[Client]) -> None:
        self._by_ip = {ip: client for client in clients for ip in client.ips}

    def find(self, ip: str) -> Client | None:
        normalized = normalize_ip(ip)
        if normalized is None:
            return None
        return self._by_ip.get(normalized)
