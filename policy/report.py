"""Formatting the parent and task pages share.

Durations, household-local dates, the timezone sentence of a status bar, and
the plain HTML response a task page answers with. The usage graph itself is
``policy.usage_graph``.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date

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


@dataclass(frozen=True)
class PageResponse:
    status: int
    body: str
    headers: tuple[tuple[str, str], ...] = ()


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


def format_day(day: date) -> str:
    """Return a household-local date such as Wednesday 21 October 2026."""
    return f"{_WEEKDAYS[day.weekday()]} {day.day} {_MONTHS[day.month - 1]} {day.year}"


def timezone_note(timezone: str | None) -> str:
    """Return the sentence that says which timezone the times are in."""
    if timezone:
        return f"Times are {timezone}."
    return "Times are the timezone of this machine."


def _response(
    status: int,
    body: str,
    extra: tuple[tuple[str, str], ...] = (),
) -> PageResponse:
    return PageResponse(status, body, (("cache-control", "no-store"), *extra))


def _e(value: str) -> str:
    return html.escape(value, quote=True)
