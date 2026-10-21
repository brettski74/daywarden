"""Which site group a URL belongs to.

A pattern with "://" is matched against the whole URL, less its fragment. Any
other pattern is matched against the host alone. Matching ignores case, "*"
matches any run of characters including "/", and "?" matches one character.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlsplit

from policy.rules import Rule


@dataclass(frozen=True)
class SiteGroup:
    name: str
    priority: int
    patterns: tuple[str, ...] = ()
    default: bool = False
    rules: tuple[Rule, ...] = ()
    quota: int | None = None


def matches(pattern: str, url: str) -> bool:
    return _matches(pattern, *_subjects(url))


class SiteGroups:
    """The groups in the order they are tried. The default group is always last."""

    def __init__(self, groups: Iterable[SiteGroup]) -> None:
        groups = list(groups)
        self._ordered = sorted((group for group in groups if not group.default), key=lambda g: g.priority)
        self._default = next((group for group in groups if group.default), None)

    def classify(self, url: str) -> SiteGroup | None:
        """Return the first group with a pattern that matches url, else the default, if any."""
        subjects = _subjects(url)
        for group in self._ordered:
            if any(_matches(pattern, *subjects) for pattern in group.patterns):
                return group
        return self._default


def _subjects(url: str) -> tuple[str, str]:
    """Return the URL without its fragment, and its host, both in lower case."""
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        host = ""
    return url.split("#", 1)[0].lower(), host.rstrip(".")


def _matches(pattern: str, url: str, host: str) -> bool:
    return _compile(pattern).fullmatch(url if "://" in pattern else host) is not None


@lru_cache(maxsize=1024)
def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile("".join(_atom(char) for char in pattern.lower()), re.DOTALL)


def _atom(char: str) -> str:
    if char == "*":
        return ".*"
    if char == "?":
        return "."
    return re.escape(char)
