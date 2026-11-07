"""IP addresses and the DNS names a client group may list instead."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable

Lookup = Callable[..., list]


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
