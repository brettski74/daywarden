"""Hosts that skip the decision API and are always forwarded.

They are the globs in ``bypass.txt``, read on every request, and the policy
server's own names from ``PARENT_NAMES``, read when the proxy starts. The two
lists are merged in memory. Loopback names in ``PARENT_NAMES`` are left out,
because through the proxy they would name the proxy's own container.
"""

from __future__ import annotations

import re
from pathlib import Path

LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})


def load_patterns(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    patterns = []
    for line in text.splitlines():
        pattern = line.split("#", 1)[0].strip()
        if pattern:
            patterns.append(pattern)
    return patterns


def parent_names(raw: str | None) -> frozenset[str]:
    """Return the policy server's names in a ``PARENT_NAMES`` value, without the loopback names."""
    names = set()
    for token in (raw or "").split(","):
        name = _host(token.strip().strip("[]"))
        if name and name not in LOOPBACK_NAMES:
            names.add(name)
    return frozenset(names)


def is_parent(host: str, names: frozenset[str]) -> bool:
    """Return whether host is one of the policy server's names."""
    return _host(host.strip("[]")) in names


def is_bypassed(host: str, patterns: list[str], names: frozenset[str] = frozenset()) -> bool:
    if is_parent(host, names):
        return True
    normalized = _host(host)
    return any(_compile(pattern).fullmatch(normalized) is not None for pattern in patterns)


def _host(host: str) -> str:
    return host.lower().rstrip(".")


def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile("".join(_atom(char) for char in pattern.lower()))


def _atom(char: str) -> str:
    if char == "*":
        return ".*"
    if char == "?":
        return "."
    return re.escape(char)
