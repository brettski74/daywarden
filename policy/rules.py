"""Ordered rules for one site group.

A rule has a condition and two actions. The first action other than continue
is the decision. If the list runs out, the request is denied.

A time window includes its start and excludes its end, so 07:00 belongs to
the later of two adjoining windows. A window whose end is earlier than its
start crosses midnight: the evening belongs to the named weekday, and the
morning belongs to that same window on the following day. A window with no
weekdays applies every day. A request is inside the condition when it is
inside any one of the windows.

`tasks_complete` and `quota_remaining` are booleans supplied by the caller.
S001.4 and S001.5 replace those booleans with real counts. Until then a test,
or the service, passes them in.
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
class Rule:
    condition: str
    when_true: Action
    when_false: Action
    windows: tuple[TimeWindow, ...] = ()


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
    tasks_complete: bool = False,
    quota_remaining: bool = True,
    revision_task: str | None = None,
) -> dict:
    """Return the decision for rules at household-local time at.

    tasks_complete and quota_remaining are the test hook for those two
    conditions. The defaults are the ones the entertainment schedule is
    specified with: no task is complete, and quota is still remaining.
    """
    for rule in rules:
        action = rule.when_true if _holds(rule, at, tasks_complete, quota_remaining) else rule.when_false
        if action.kind == "continue":
            continue
        return _decision(action, revision_task)
    return {"action": "deny", "status": 403, "message": FALLTHROUGH_MESSAGE}


def _holds(rule: Rule, at: datetime, tasks_complete: bool, quota_remaining: bool) -> bool:
    if rule.condition == "always":
        return True
    if rule.condition == "time_window":
        return any(_contains(window, at) for window in rule.windows)
    if rule.condition == "tasks_complete":
        return tasks_complete
    if rule.condition == "quota_remaining":
        return quota_remaining
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
