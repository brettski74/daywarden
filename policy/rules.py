"""Ordered rules for one site group.

A rule has a condition and two actions. The first action other than continue
is the decision. If the list runs out, the request is denied.

A time window includes its start and excludes its end, so 07:00 belongs to
the later of two adjoining windows. A window whose end is earlier than its
start crosses midnight: the evening belongs to the named weekday, and the
morning belongs to that same window on the following day. A window with no
weekdays applies every day. A request is inside the condition when it is
inside any one of the windows.

`tasks_complete` is true when this client's stored revision successes for the
local date are at least the required count. A weekday can require a different
count. The count is only a number; which tasks made it up is left to later
stories.

`quota_remaining` is true when this client's ended usage for the group on
that date is strictly below the group's quota. The quota is a duration in
seconds. A group with no quota makes the condition true. Usage is the sum of
the lengths of buckets that contained traffic and have already ended.

`volume_remaining` is true while today's stored bytes for this client and
group are strictly under the group's byte limit. A group with no byte limit
makes the condition true. The bytes are the ones already stored on today's
buckets, including a bucket that has not ended.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, time
from urllib.parse import urlparse

REVISION_TASK = "revision_task"
FALLTHROUGH_MESSAGE = "No rule allowed this request."
UNCONFIGURED_TASK_MESSAGE = "The revision task page is not configured."


@dataclass(frozen=True)
class Action:
    kind: str
    message: str = ""
    location: str = ""


@dataclass(frozen=True)
class TimeWindow:
    start: time
    end: time
    weekdays: frozenset[int] | None = None


@dataclass(frozen=True)
class TaskRequirement:
    """How many successes today satisfy a tasks_complete rule.

    required is the count on days without an override. overrides maps a
    weekday number (Monday is 0, the same as datetime.weekday) to a different
    count.
    """

    required: int
    overrides: tuple[tuple[int, int], ...] = ()

    def for_weekday(self, weekday: int) -> int:
        for day, count in self.overrides:
            if day == weekday:
                return count
        return self.required


@dataclass(frozen=True)
class Rule:
    condition: str
    when_true: Action
    when_false: Action
    windows: tuple[TimeWindow, ...] = ()
    requirement: TaskRequirement | None = None


def absolute_http_url(value: str) -> bool:
    """True when value is an absolute http or https URL the addon will accept."""
    if any(char in value for char in "\r\n\t "):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def evaluate(
    rules: Iterable[Rule],
    at: datetime,
    *,
    completed: int = 0,
    consumed: int = 0,
    quota: int | None = None,
    observed: int = 0,
    byte_limit: int | None = None,
    revision_task: str | None = None,
) -> dict:
    """Return the decision for rules at household-local time at.

    completed is how many revision tasks this client has finished on the
    household-local date of at. It is compared with the required count for
    that weekday. The default is none finished.

    consumed is how many seconds of ended buckets this client has already
    used for the group on that date. quota is the group's limit in seconds,
    or None when the group has no quota. The condition is true when quota is
    absent or consumed is strictly below it.

    observed is how many bytes are already stored for this client and group
    on that date, including a bucket that has not ended. byte_limit is the
    group's daily cap in bytes, or None when the group has none. The
    condition is true when the cap is absent or observed is strictly below it.
    """
    for rule in rules:
        holds = _holds(rule, at, completed, consumed, quota, observed, byte_limit)
        action = rule.when_true if holds else rule.when_false
        if action.kind == "continue":
            continue
        return _decision(action, revision_task)
    return {"action": "deny", "status": 403, "message": FALLTHROUGH_MESSAGE}


def _holds(
    rule: Rule,
    at: datetime,
    completed: int,
    consumed: int,
    quota: int | None,
    observed: int,
    byte_limit: int | None,
) -> bool:
    if rule.condition == "always":
        return True
    if rule.condition == "time_window":
        return any(_contains(window, at) for window in rule.windows)
    if rule.condition == "tasks_complete":
        requirement = rule.requirement
        return requirement is not None and completed >= requirement.for_weekday(at.weekday())
    if rule.condition == "quota_remaining":
        return quota is None or consumed < quota
    if rule.condition == "volume_remaining":
        return byte_limit is None or observed < byte_limit
    raise ValueError(f"unknown condition {rule.condition!r}")


def _contains(window: TimeWindow, at: datetime) -> bool:
    clock = at.time()
    today = at.weekday()
    if window.start == window.end:
        return False
    if window.start < window.end:
        return _on(window, today) and window.start <= clock < window.end
    if clock >= window.start:
        return _on(window, today)
    if clock < window.end:
        return _on(window, (today - 1) % 7)
    return False


def _on(window: TimeWindow, weekday: int) -> bool:
    return window.weekdays is None or weekday in window.weekdays


def _decision(action: Action, revision_task: str | None) -> dict:
    if action.kind == "allow":
        return {"action": "allow"}
    if action.kind == "deny":
        return {"action": "deny", "status": 403, "message": action.message}
    location = revision_task if action.location == REVISION_TASK else action.location
    if location and absolute_http_url(location):
        return {"action": "redirect", "status": 302, "location": location}
    return {"action": "deny", "status": 403, "message": UNCONFIGURED_TASK_MESSAGE}
