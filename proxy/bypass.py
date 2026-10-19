"""Host globs that skip the decision API and are always forwarded."""

from __future__ import annotations

import re
from pathlib import Path


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


def is_bypassed(host: str, patterns: list[str]) -> bool:
    normalized = host.lower().rstrip(".")
    return any(_compile(pattern).fullmatch(normalized) is not None for pattern in patterns)


def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile("".join(_atom(char) for char in pattern.lower()))


def _atom(char: str) -> str:
    if char == "*":
        return ".*"
    if char == "?":
        return "."
    return re.escape(char)
