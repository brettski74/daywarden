"""The attempts overview and each task's trend, over a period.

The attempts page and a task's trend page share their choices, which live in
the page address: the client group, the period, and the Set and Outcome
filters. The data endpoints take the same query string.

- ``range`` is one of the usage graph's date ranges, Past month when it is
  missing, with ``from`` and ``to`` for Custom.
- ``set`` and ``outcome`` may each appear any number of times. Missing, every
  choice is made. ``none`` alone makes no choice, so the parent can clear
  them all.

Parent checks hold no questions, so they are left out of the overview and the
trend. The attempts list still shows the period's parent checks, whatever the
filters. Each attempt's figures come from ``policy.attempt_figures``.

A range that ends now, such as Past month, takes in an attempt stored with a
start a moment later than now, as a clock just changed can store.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from policy.attempt_figures import figures
from policy.spelling_words import SPELLING
from policy.tasks import (
    ABANDONED,
    FAILURE,
    IN_PROGRESS,
    PARENT_CHECK,
    PASS,
    POTENTIAL,
    PRACTICE,
    REQUIRED,
    UNFINISHED,
    Attempt,
    TaskKey,
)
from policy.usage_graph import RANGES, Settings, custom_problems, describe_range, intervals, parse_day, resolve_range, time_ticks

SETS = (REQUIRED, POTENTIAL, PRACTICE)
OUTCOMES = (PASS, FAILURE, ABANDONED, UNFINISHED, IN_PROGRESS)
OUTCOME_LABELS = {
    PASS: "Pass",
    FAILURE: "Failure",
    ABANDONED: "Abandoned",
    UNFINISHED: "Unfinished",
    IN_PROGRESS: "In progress",
}
DEFAULT_RANGE = "past-month"
NONE = "none"
# Ranges that end at the moment the page is asked for.
_ENDS_NOW = frozenset({"today", "this-week", "this-month", "past-week", "past-month"})


@dataclass(frozen=True)
class View:
    """What the page shows. ``first`` and ``last`` are the Custom range's days, `yyyy-mm-dd`."""

    client: str = ""
    range: str = DEFAULT_RANGE
    first: str = ""
    last: str = ""
    sets: tuple[str, ...] = SETS
    outcomes: tuple[str, ...] = OUTCOMES

    def as_json(self) -> dict:
        return {
            "client": self.client,
            "range": self.range,
            "from": self.first,
            "to": self.last,
            "set": list(self.sets),
            "outcome": list(self.outcomes),
        }


@dataclass(frozen=True)
class Period:
    start: datetime
    end: datetime
    open_end: bool

    def holds(self, moment: datetime) -> bool:
        moment = _wall(moment)
        return moment >= self.start and (self.open_end or moment < self.end)

    def at(self, moment: datetime) -> int:
        """Return seconds from the start, within the period."""
        seconds = int((_wall(moment) - self.start).total_seconds())
        return min(max(seconds, 0), self.length)

    @property
    def length(self) -> int:
        return int((self.end - self.start).total_seconds())


def read_view(pairs: Iterable[tuple[str, str]]) -> tuple[View, list[str]]:
    """Read the choices a page address names, and say what was not a choice."""
    found: dict[str, list[str]] = {}
    for key, value in pairs:
        found.setdefault(key, []).append(value)
    notes: list[str] = []
    chosen_range = (found.get("range") or [""])[-1].strip() or DEFAULT_RANGE
    if chosen_range not in RANGES:
        notes.append(f"{chosen_range} is not a period, so this is the past month.")
        chosen_range = DEFAULT_RANGE
    custom = chosen_range == "custom"
    sets, set_notes = _choices(found.get("set"), SETS, "set")
    outcomes, outcome_notes = _choices(found.get("outcome"), OUTCOMES, "outcome")
    view = View(
        client=(found.get("client") or [""])[-1].strip(),
        range=chosen_range,
        first=(found.get("from") or [""])[-1].strip() if custom else "",
        last=(found.get("to") or [""])[-1].strip() if custom else "",
        sets=sets,
        outcomes=outcomes,
    )
    return view, notes + set_notes + outcome_notes


def period_of(view: View, now: datetime) -> tuple[Period | None, list[str]]:
    """Return the view's period at now, or None and why a Custom period cannot be shown."""
    settings = Settings(range=view.range, first=view.first, last=view.last)
    problems = custom_problems(settings)
    if problems:
        return None, problems
    start, end = resolve_range(view.range, _wall(now), parse_day(view.first), parse_day(view.last))
    return Period(start, end, view.range in _ENDS_NOW), []


def period_json(period: Period | None, now: datetime) -> dict:
    """Return what the page says of the period: its description and its first and last days."""
    if period is None:
        return {"today": _wall(now).date().isoformat(), "range": None, "days": None}
    last_day = (period.end - timedelta(seconds=1)).date() if period.end > period.start else period.start.date()
    return {
        "today": _wall(now).date().isoformat(),
        "range": describe_range(period.start, period.end),
        "days": {"from": period.start.date().isoformat(), "to": last_day.isoformat()},
    }


def outcome_of(attempt: Attempt, today: date) -> str:
    """Return the outcome, with an attempt left open on an earlier household day unfinished."""
    return UNFINISHED if attempt.left_open(today) else attempt.outcome


def chosen(attempt: Attempt, view: View, period: Period, today: date) -> bool:
    """Whether a task attempt is in the period and passes the filters. A parent check never is."""
    return (
        attempt.task_set != PARENT_CHECK
        and attempt.task_type != PARENT_CHECK
        and period.holds(attempt.started_at)
        and attempt.task_set in view.sets
        and outcome_of(attempt, today) in view.outcomes
    )


def listed(attempts: Sequence[Attempt], view: View, period: Period, today: date) -> list[Attempt]:
    """Return the attempts the list shows: those chosen, and every parent check in the period. The order is kept."""
    return [
        attempt
        for attempt in attempts
        if chosen(attempt, view, period, today)
        or ((attempt.task_set == PARENT_CHECK or attempt.task_type == PARENT_CHECK) and period.holds(attempt.started_at))
    ]


def overview(attempts: Sequence[Attempt], view: View, period: Period, today: date, known: set[TaskKey]) -> list[dict]:
    """Return one row for each task with a chosen attempt, ordered by type then name."""
    by_task: dict[TaskKey, list[Attempt]] = {}
    for attempt in _oldest_first(attempts):
        if chosen(attempt, view, period, today):
            by_task.setdefault(attempt.key, []).append(attempt)
    rows = []
    for key in sorted(by_task, key=lambda each: (each.type, each.name)):
        group = by_task[key]
        outcomes = [outcome_of(attempt, today) for attempt in group]
        worked = [found for found in (figures(attempt.task_type, attempt.detail) for attempt in group) if found is not None]
        questions = sum(found.questions for found in worked)
        points = sum(found.points for found in worked)
        spark = [{"points": found.points, "pass_mark": found.pass_mark} for found in worked]
        rows.append(
            {
                "type": key.type,
                "name": key.name,
                "label": str(key),
                "in_policy": key in known,
                "attempts": len(group),
                "passes": outcomes.count(PASS),
                "failures": outcomes.count(FAILURE),
                "abandoned": outcomes.count(ABANDONED),
                "unfinished": outcomes.count(UNFINISHED),
                "accuracy": _percent(points, questions),
                "spark": spark,
                "spark_label": _spark_label(len(group), spark),
            }
        )
    return rows


def trend(
    attempts: Sequence[Attempt],
    key: TaskKey,
    view: View,
    period: Period,
    today: date,
    row: Callable[[Attempt], dict],
) -> dict:
    """Return one task's chosen attempts as points across the period, oldest first, and as list rows, newest first."""
    mine = [attempt for attempt in _oldest_first(attempts) if attempt.key == key and chosen(attempt, view, period, today)]
    points = []
    for attempt in mine:
        found = figures(attempt.task_type, attempt.detail)
        outcome = outcome_of(attempt, today)
        shown = row(attempt)
        points.append(
            {
                "id": attempt.id,
                "at": period.at(attempt.started_at),
                "started": shown["started"],
                "set": shown["set"],
                "practice": attempt.task_set == PRACTICE,
                "outcome": outcome,
                "outcome_label": OUTCOME_LABELS.get(outcome, outcome),
                "figures": None if found is None else found.as_json(),
            }
        )
    kind, _spans = intervals(period.start, period.end)
    has_figures = any(point["figures"] is not None for point in points)
    return {
        "kind": None if not has_figures else ("spelling" if key.type == SPELLING else "points"),
        "has_maximum": any(point["figures"] is not None and point["figures"]["maximum"] is not None for point in points),
        "length": period.length,
        "ticks": time_ticks(kind, period.start, period.end),
        "points": points,
        "attempts": [row(attempt) for attempt in reversed(mine)],
    }


def no_attempts(key: TaskKey, client: str) -> str:
    return f"No attempts at {key} for {client} in this period."


def _percent(points: float, questions: int) -> int | None:
    """Return points over questions as a whole percentage, a half rounded up, or None with no questions."""
    return math.floor(100 * points / questions + 0.5) if questions else None


def _spark_label(count: int, spark: list[dict]) -> str:
    noun = "attempt" if count == 1 else "attempts"
    if not spark:
        return f"{count} {noun}"
    latest = spark[-1]
    mark = "" if latest["pass_mark"] is None else f" of {latest['pass_mark']}"
    return f"{count} {noun}, latest {latest['points']}{mark}"


def _choices(values: list[str] | None, allowed: tuple[str, ...], name: str) -> tuple[tuple[str, ...], list[str]]:
    if values is None:
        return allowed, []
    picked = {value.strip() for value in values}
    unknown = sorted(picked - set(allowed) - {NONE, ""})
    notes = [f"{value} is not a {name}, so it is left out." for value in unknown]
    return tuple(value for value in allowed if value in picked), notes


def _oldest_first(attempts: Sequence[Attempt]) -> list[Attempt]:
    return sorted(attempts, key=lambda attempt: (_wall(attempt.started_at), attempt.id))


def _wall(moment: datetime) -> datetime:
    """Return household-local time to the second, offset dropped rather than converted."""
    if moment.tzinfo is not None:
        moment = moment.replace(tzinfo=None)
    return moment.replace(microsecond=0)
