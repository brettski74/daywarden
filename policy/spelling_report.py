"""Spelling words across attempts (S035.4), and one spelling attempt's runs.

A word is a spelling entry key folded to lower case, within a client group,
as in S033. A word is asked in an attempt when at least one of its questions
has an outcome. In that attempt it is right first time when its first such
question was correct, right after a miss when it was missed and later
correct, and missed when it was never correct. A timeout is a miss.

A word's pool now is each pool whose directory, named by one of the chosen
tasks in the policy, holds its recording when the page is asked for. It says
nothing about the pool the word was in when it was asked. A word in no chosen
task's directories has no pool now, which the Pool filter calls None.

Every question with an outcome counts, in every run of every chosen attempt.
Practice mode's walk asks no questions, so it adds nothing.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from policy.attempt_figures import figures
from policy.attempt_trends import NONE, Period, View, chosen
from policy.quiz import CORRECT, INCORRECT, TIMEOUT
from policy.report import format_day
from policy.spelling import ALL_POOLS, ATTIC, CURRENT, REVISION, entry_keys, parse_settings
from policy.spelling_words import SETTLED_RUN, SPELLING, Figures
from policy.tasks import Attempt, Task

FIRST_TIME = "first_time"
AFTER_MISS = "after_miss"
MISSED = "missed"
# The Pool filter's value for a word in none of the chosen tasks' directories.
NO_POOL = "no_pool"
POOL_CHOICES = (CURRENT, REVISION, ATTIC, NO_POOL)
POOL_LABELS = {CURRENT: "Current", REVISION: "Revision", ATTIC: "Attic", NO_POOL: "None"}
OUTCOME_WORDS = {CORRECT: "Right", INCORRECT: "Wrong", TIMEOUT: "Timeout"}


@dataclass(frozen=True)
class WordChoices:
    """The words page's own filters: the chosen spelling task names and pools. ``tasks`` None means every task offered."""

    tasks: tuple[str, ...] | None = None
    pools: tuple[str, ...] = POOL_CHOICES

    def as_json(self, offered: Sequence[str]) -> dict:
        return {"task": list(offered if self.tasks is None else self.tasks), "pool": list(self.pools)}


def read_choices(pairs: Iterable[tuple[str, str]]) -> tuple[WordChoices, list[str]]:
    """Read the Task and Pool filters from a page address. Missing, everything is chosen. ``none`` alone chooses nothing."""
    found: dict[str, list[str]] = {}
    for key, value in pairs:
        if key in ("task", "pool"):
            found.setdefault(key, []).append(value.strip())
    notes: list[str] = []
    tasks = None
    if "task" in found:
        tasks = tuple(dict.fromkeys(value for value in found["task"] if value and value != NONE))
    pools = POOL_CHOICES
    if "pool" in found:
        picked = set(found["pool"])
        notes += [f"{value} is not a pool, so it is left out." for value in sorted(picked - set(POOL_CHOICES) - {NONE, ""})]
        pools = tuple(value for value in POOL_CHOICES if value in picked)
    return WordChoices(tasks, pools), notes


@dataclass
class TaskPools:
    """What the chosen tasks' directories hold now: each word's pools, and each task's current words."""

    pools: dict[str, set[str]] = field(default_factory=dict)
    current: dict[str, set[str]] = field(default_factory=dict)

    def of(self, word: str) -> list[str]:
        return [pool for pool in ALL_POOLS if pool in self.pools.get(word, ())]


def offered_tasks(
    tasks: Sequence[Task], client: str, attempts: Sequence[Attempt], view: View, period: Period, today: date, task_type: str = SPELLING
) -> list[dict]:
    """Return the Task filter's choices: the group's tasks of a type, then any other of the type it has chosen attempts at.

    Each is its name and whether the policy has it. A spelling task in the
    policy but assigned only to other groups is offered when it has attempts,
    and, for spelling, keeps its directories. The parts of speech confusions
    page offers its tasks the same way.
    """
    in_policy = {task.name for task in tasks if task.type == task_type}
    offered = [task.name for task in tasks if task.type == task_type and client in task.groups]
    others = sorted(
        {
            attempt.task
            for attempt in attempts
            if attempt.task_type == task_type and attempt.task not in offered and chosen(attempt, view, period, today)
        }
    )
    return [{"name": name, "in_policy": name in in_policy} for name in [*dict.fromkeys(offered), *others]]


def pools_now(tasks: Sequence[Task], names: Iterable[str], root: Path) -> TaskPools:
    """Read the chosen tasks' pool directories as they are now. A task not in the policy has none."""
    by_name = {task.name: task for task in tasks if task.type == SPELLING}
    found = TaskPools()
    for name in names:
        task = by_name.get(name)
        if task is None:
            continue
        try:
            settings = parse_settings(task.document())
        except (ValueError, TypeError, KeyError):
            continue
        for pool in ALL_POOLS:
            keys = entry_keys(root / settings.directory(pool))
            for key in keys:
                found.pools.setdefault(key, set()).add(pool)
            if pool == CURRENT:
                found.current[name] = keys
    return found


def this_week_day(attempts: Sequence[Attempt], names: Iterable[str], held: TaskPools, today: date) -> date:
    """Return the day of the first attempt whose run asked exactly the words now in its task's current pool.

    With several tasks, the earliest of their days. With no such attempt, today.
    """
    days = []
    for name in names:
        current = held.current.get(name)
        if not current:
            continue
        for attempt in sorted(attempts, key=lambda each: (_wall(each.started_at), each.id)):
            if attempt.task_type == SPELLING and attempt.task == name and any(keys == current for keys in _run_current_words(attempt)):
                days.append(_wall(attempt.started_at).date())
                break
    return min(days) if days else today


def _run_current_words(attempt: Attempt) -> list[set[str]]:
    detail = attempt.detail if isinstance(attempt.detail, Mapping) else {}
    runs = detail.get("runs") if isinstance(detail.get("runs"), list) else []
    found = []
    for run in runs:
        words = run.get("words") if isinstance(run, Mapping) else None
        current = words.get(CURRENT) if isinstance(words, Mapping) else None
        if isinstance(current, list):
            found.append({str(each.get("key")).lower() for each in current if isinstance(each, Mapping) and isinstance(each.get("key"), str)})
    return found


def words(
    attempts: Sequence[Attempt],
    view: View,
    period: Period,
    today: date,
    task_names: Iterable[str],
    held: TaskPools,
    pools: Sequence[str],
    all_time: Mapping[str, Figures],
    started: Callable[[Attempt], str],
) -> dict:
    """Return the words of the chosen spelling attempts whose pool now is chosen, with the tiles and the grid's columns.

    Each word has its figures over the period, its misspellings, and the
    attempts that asked it, newest first. ``columns`` is every attempt that
    asked any of them, oldest first. ``attempts`` describes each by id.
    Run and weight are all-time, from ``all_time``.
    """
    names = set(task_names)
    asks: dict[str, dict[int, list[Mapping]]] = {}
    shown_key: dict[str, str] = {}
    by_id: dict[int, Attempt] = {}
    for attempt in sorted(attempts, key=lambda each: (_wall(each.started_at), each.id)):
        if attempt.task_type != SPELLING or attempt.task not in names or not chosen(attempt, view, period, today):
            continue
        detail = attempt.detail if isinstance(attempt.detail, Mapping) else {}
        questions = detail.get("questions")
        for question in questions if isinstance(questions, list) else ():
            if not isinstance(question, Mapping) or question.get("outcome") not in OUTCOME_WORDS or not isinstance(question.get("key"), str):
                continue
            word = question["key"].lower()
            if not _kept(held.of(word), pools):
                continue
            asks.setdefault(word, {}).setdefault(attempt.id, []).append(question)
            shown_key[word] = question["key"]
            by_id[attempt.id] = attempt
    rows = [_word_row(word, shown_key[word], asked, by_id, held.of(word), all_time.get(word, Figures())) for word, asked in asks.items()]
    rows.sort(key=lambda row: row["word"])
    columns = sorted(by_id.values(), key=lambda each: (_wall(each.started_at), each.id))
    total = sum(row["asked"] for row in rows)
    return {
        "tiles": {
            "words_asked": len(rows),
            "right_first_time": _percent(sum(row["first_time"] for row in rows), total),
            "words_missed": sum(1 for row in rows if row["after_miss"] or row["missed"]),
            "settled": sum(1 for row in rows if row["all_time"]["run"] >= SETTLED_RUN),
        },
        "words": rows,
        "columns": [attempt.id for attempt in columns],
        "attempts": {
            str(attempt.id): {
                "started": started(attempt),
                "day": _wall(attempt.started_at).date().isoformat(),
                "task": attempt.task,
            }
            for attempt in columns
        },
    }


def _kept(found: Sequence[str], pools: Sequence[str]) -> bool:
    if not found:
        return NO_POOL in pools
    return any(pool in pools for pool in found)


def _word_row(word: str, key: str, asked: Mapping[int, list[Mapping]], by_id: Mapping[int, Attempt], now: list[str], all_time: Figures) -> dict:
    counts = Counter()
    times: list[int] = []
    plays = 0
    questions = 0
    timeouts = 0
    misspellings: Counter[str] = Counter()
    last_missed: date | None = None
    listed = []
    for attempt_id, mine in asked.items():
        result = _result(mine)
        counts[result] += 1
        for question in mine:
            questions += 1
            plays += _count(question.get("word_replays")) + _count(question.get("sentence_plays"))
            outcome = question["outcome"]
            if outcome == CORRECT:
                taken = _ms(question.get("received_ms"))
                if taken is not None:
                    times.append(taken)
                continue
            if outcome == TIMEOUT:
                timeouts += 1
            elif isinstance(question.get("answer"), str):
                misspellings[question["answer"].lower()] += 1
            day = _issued_day(question, by_id[attempt_id].started_at)
            if last_missed is None or day > last_missed:
                last_missed = day
        listed.append(
            {
                "id": attempt_id,
                "result": result,
                "pools": list(dict.fromkeys(str(question.get("pool")) for question in mine if question.get("pool") in (CURRENT, REVISION))),
                "answers": [_answer_word(question) for question in mine],
            }
        )
    total = len(asked)
    not_first = counts[AFTER_MISS] + counts[MISSED]
    return {
        "word": word,
        "key": key,
        "pools": now,
        "asked": total,
        "first_time": counts[FIRST_TIME],
        "after_miss": counts[AFTER_MISS],
        "missed": counts[MISSED],
        "missed_percent": _percent(not_first, total),
        "timeouts": timeouts,
        "median_ms": statistics.median(times) if times else None,
        "replays_per_ask": round(plays / questions, 1) if questions else 0,
        "last_missed": None if last_missed is None else format_day(last_missed),
        "last_missed_day": None if last_missed is None else last_missed.isoformat(),
        "misspellings": [{"text": text, "count": count} for text, count in sorted(misspellings.items(), key=lambda item: (-item[1], item[0]))],
        "attempts": list(reversed(listed)),
        "all_time": {"run": all_time.run, "weight": round(all_time.weight, 3)},
    }


def _result(questions: Sequence[Mapping]) -> str:
    if questions[0].get("outcome") == CORRECT:
        return FIRST_TIME
    return AFTER_MISS if any(question.get("outcome") == CORRECT for question in questions) else MISSED


def no_words(client: str) -> str:
    return f"No spelling words for {client} in this period."


# A spelling attempt's page.


def spelling_runs(attempt: Attempt, stamp: Callable[[str], str]) -> dict | None:
    """Return a spelling attempt's runs for its page: the last run, then each earlier run in order.

    Each run has its figures, as S035.1 works them out, its questions in
    order, how it ended when it is not the last (expired, or left for
    practice mode, with the time), and, for a run practice mode started, the
    words practised before it. None when the attempt holds no spelling record.
    """
    detail = attempt.detail if isinstance(attempt.detail, Mapping) else {}
    questions, runs = detail.get("questions"), detail.get("runs")
    if attempt.task_type != SPELLING or not isinstance(questions, list) or not isinstance(runs, list):
        return None
    runs = [run for run in runs if isinstance(run, Mapping)]
    if not runs:
        return None
    shown = []
    for index, run in enumerate(runs):
        number = run.get("run")
        mine = [item for item in questions if isinstance(item, Mapping) and item.get("run") == number]
        found = figures(SPELLING, detail, number)
        later = runs[index + 1] if index + 1 < len(runs) else None
        expired = run.get("expired")
        ended = None
        if isinstance(expired, str):
            ended = {"how": "expired", "at": stamp(expired)}
        elif later is not None and isinstance(later.get("practice"), list):
            started = later.get("started")
            ended = {"how": "practice", "at": stamp(started) if isinstance(started, str) else ""}
        shown.append(
            {
                "run": number,
                "ended": ended,
                "figures": None if found is None else found.as_json(),
                "practised": _practised(run),
                "questions": [_question_row(item) for item in mine],
            }
        )
    return {"last": shown[-1], "earlier": shown[:-1]}


def _practised(run: Mapping) -> list[dict] | None:
    """Return the words practice mode walked through before this run, or None when practice did not start it."""
    practice = run.get("practice")
    if not isinstance(practice, list):
        return None
    words = run.get("words") if isinstance(run.get("words"), Mapping) else {}
    spelled = {
        (pool, item.get("key")): item.get("word")
        for pool in (CURRENT, REVISION)
        for item in (words.get(pool) if isinstance(words.get(pool), list) else [])
        if isinstance(item, Mapping)
    }
    found = []
    for entry in practice:
        if isinstance(entry, list) and len(entry) == 2 and isinstance(entry[1], str):
            pool, key = entry
            found.append({"key": key, "word": spelled.get((pool, key)) or key, "pool": pool, "pool_label": POOL_LABELS.get(pool, str(pool))})
    return found


def _question_row(question: Mapping) -> dict:
    outcome = question.get("outcome")
    answer = question.get("answer")
    key = question.get("key") if isinstance(question.get("key"), str) else ""
    requeued = question.get("requeued")
    return {
        "key": key,
        "word": key.lower(),
        "spelling": question.get("word") if isinstance(question.get("word"), str) else key,
        "pool": question.get("pool"),
        "pool_label": POOL_LABELS.get(question.get("pool"), ""),
        "answer": answer if isinstance(answer, str) else "",
        "outcome": outcome if outcome in OUTCOME_WORDS else None,
        "outcome_label": OUTCOME_WORDS.get(outcome, "Not answered yet"),
        "came_back": requeued if isinstance(requeued, bool) and outcome is not None else None,
        "word_replays": _count(question.get("word_replays")),
        "sentence_plays": _count(question.get("sentence_plays")),
        "taken_ms": _ms(question.get("received_ms")),
        "allowed_ms": _ms(question.get("allowed_ms")),
    }


def _answer_word(question: Mapping) -> str:
    """His answer as the words page lists it: what he typed, or ``timeout``."""
    if question.get("outcome") == TIMEOUT:
        return "timeout"
    answer = question.get("answer")
    return answer if isinstance(answer, str) else ""


def _issued_day(question: Mapping, fallback: datetime) -> date:
    issued = question.get("issued")
    if isinstance(issued, str):
        try:
            return datetime.fromisoformat(issued).replace(tzinfo=None).date()
        except ValueError:
            pass
    return _wall(fallback).date()


def _percent(part: int, whole: int) -> int | None:
    """Return a whole percentage, a half rounded up, or None of nothing."""
    return math.floor(100 * part / whole + 0.5) if whole else None


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _ms(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0, round(value))


def _wall(moment: datetime) -> datetime:
    return moment.replace(tzinfo=None, microsecond=0)
