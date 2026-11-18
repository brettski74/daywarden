"""Arithmetic facts across attempts, and one arithmetic attempt's runs.

A fact is one question as it is asked, given by its left number ``m`` and
right number ``n``, as in the policy's ``first`` and ``operands``. ``6 + 7``
and ``7 + 6`` are two facts. A fact is missed when it is answered wrongly or
times out.

Every finished question of every chosen attempt counts: questions in expired
runs, and in abandoned, unfinished, and in-progress attempts. A fact asked
twice in one attempt counts twice. Each question's operation is read from the
sign in its stored text, so an attempt whose task changed operation between
runs puts each question under its own operation.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime

from policy.arithmetic import ARITHMETIC, OPERATIONS
from policy.attempt_figures import figures
from policy.attempt_trends import Period, View, chosen
from policy.quiz import CORRECT, INCORRECT, TIMEOUT
from policy.report import format_day
from policy.tasks import Attempt

# The sign each operation writes between its numbers, as Operation.text does.
SIGNS = {"addition": "+", "subtraction": "−", "multiplication": "×", "division": "÷"}
_BY_SIGN = {sign: name for name, sign in SIGNS.items()}
OUTCOME_WORDS = {CORRECT: "Right", INCORRECT: "Wrong", TIMEOUT: "Timeout"}


def operation_of(question: Mapping, settings: Mapping | None = None) -> str | None:
    """Return the operation a stored question asked, from the sign in its text, or else the stored settings."""
    text = question.get("question")
    if isinstance(text, str):
        for part in text.split():
            if part in _BY_SIGN:
                return _BY_SIGN[part]
    named = settings.get("operation") if isinstance(settings, Mapping) else None
    return named if named in OPERATIONS else None


def _whole(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _ms(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0, round(value))


def _shown(question: Mapping) -> tuple[str, str]:
    """Return a question as asked without its ``=``, such as ``6 + 7``, and with its answer, such as ``6 + 7 = 13``."""
    text = question.get("question")
    asked = text.strip().removesuffix("=").strip() if isinstance(text, str) else ""
    expected = question.get("expected")
    return asked, f"{asked} = {expected}" if expected is not None else asked


def _issued_day(question: Mapping, fallback: datetime) -> date:
    issued = question.get("issued")
    if isinstance(issued, str):
        try:
            return datetime.fromisoformat(issued).replace(tzinfo=None).date()
        except ValueError:
            pass
    return fallback.replace(tzinfo=None).date()


def _answer_word(question: Mapping) -> str:
    """His answer as the facts page lists it: the number, or ``timeout``."""
    if question.get("outcome") == TIMEOUT:
        return "timeout"
    answer = question.get("answer")
    return "" if answer is None else str(answer)


def facts(
    attempts: Sequence[Attempt],
    operation: str,
    view: View,
    period: Period,
    today: date,
    started: Callable[[Attempt], str],
) -> dict:
    """Return the operation's facts over the chosen arithmetic attempts.

    ``rows`` and ``columns`` are the ``m`` and ``n`` values asked, smallest
    first. Each fact has its counts, the share missed as a whole percentage,
    the median time of its right answers, the day it was last missed, and the
    attempts that asked it, newest first, with each answer he gave.
    ``attempts`` describes each of those attempts by id.
    """
    found: dict[tuple[int, int], dict] = {}
    asked_in: dict[tuple[int, int], dict[int, list[str]]] = {}
    described: dict[str, dict] = {}
    newest_first = sorted(attempts, key=lambda each: (each.started_at.replace(tzinfo=None), each.id), reverse=True)
    for attempt in newest_first:
        if attempt.task_type != ARITHMETIC or not chosen(attempt, view, period, today):
            continue
        detail = attempt.detail if isinstance(attempt.detail, Mapping) else {}
        questions = detail.get("questions")
        if not isinstance(questions, list):
            continue
        settings = detail.get("settings") if isinstance(detail.get("settings"), Mapping) else {}
        for question in questions:
            if not isinstance(question, Mapping) or question.get("outcome") not in OUTCOME_WORDS:
                continue
            m, n = _whole(question.get("m")), _whole(question.get("n"))
            if m is None or n is None or operation_of(question, settings) != operation:
                continue
            key = (m, n)
            fact = found.get(key)
            if fact is None:
                cell, text = _shown(question)
                fact = found[key] = {
                    "m": m,
                    "n": n,
                    "cell": cell,
                    "text": text,
                    "asked": 0,
                    "right": 0,
                    "wrong": 0,
                    "timeouts": 0,
                    "times": [],
                    "last_missed": None,
                }
            fact["asked"] += 1
            outcome = question["outcome"]
            if outcome == CORRECT:
                fact["right"] += 1
                taken = _ms(question.get("taken_ms"))
                if taken is not None:
                    fact["times"].append(taken)
            else:
                fact["wrong" if outcome == INCORRECT else "timeouts"] += 1
                day = _issued_day(question, attempt.started_at)
                if fact["last_missed"] is None or day > fact["last_missed"]:
                    fact["last_missed"] = day
            asked_in.setdefault(key, {}).setdefault(attempt.id, []).append(_answer_word(question))
            described.setdefault(str(attempt.id), {"started": started(attempt), "task": attempt.task})
    rows = []
    for key in sorted(found):
        fact = found.pop(key)
        times = fact.pop("times")
        last = fact.pop("last_missed")
        missed = fact["wrong"] + fact["timeouts"]
        rows.append(
            {
                **fact,
                "missed": missed,
                "missed_percent": round(100 * missed / fact["asked"]),
                "median_ms": statistics.median(times) if times else None,
                "last_missed": None if last is None else format_day(last),
                "last_missed_day": None if last is None else last.isoformat(),
                "attempts": [{"id": number, "answers": answers} for number, answers in asked_in[key].items()],
            }
        )
    return {
        "rows": sorted({fact["m"] for fact in rows}),
        "columns": sorted({fact["n"] for fact in rows}),
        "facts": rows,
        "attempts": described,
    }


def no_questions(operation: str, client: str) -> str:
    return f"No {operation} questions for {client} in this period."


def attempt_runs(attempt: Attempt, stamp: Callable[[str], str]) -> dict | None:
    """Return an arithmetic attempt's runs for its page: the last run first, then each expired run in order.

    Each run has its figures, as S035.1 works them out, and its questions in
    order. ``stamp`` formats a stored time. None when the attempt holds no
    arithmetic record.
    """
    detail = attempt.detail if isinstance(attempt.detail, Mapping) else {}
    questions = detail.get("questions")
    runs = detail.get("runs")
    if attempt.task_type != ARITHMETIC or not isinstance(questions, list) or not isinstance(runs, list) or not runs:
        return None
    settings = detail.get("settings") if isinstance(detail.get("settings"), Mapping) else {}
    shown = []
    for run in runs:
        if not isinstance(run, Mapping):
            continue
        number = run.get("run")
        mine = [item for item in questions if isinstance(item, Mapping) and item.get("run") == number]
        operation = next((found for found in (operation_of(item, settings) for item in mine) if found), None)
        operation = operation or operation_of({}, settings)
        found = figures(ARITHMETIC, detail, number)
        expired = run.get("expired")
        shown.append(
            {
                "run": number,
                "expired": stamp(expired) if isinstance(expired, str) else None,
                "operation": operation,
                "operation_label": OPERATIONS[operation].label if operation in OPERATIONS else "Arithmetic",
                "figures": None if found is None else found.as_json(),
                "questions": [_question_row(item, operation) for item in mine],
            }
        )
    if not shown:
        return None
    # A run ends early only by expiring, so every run before the last is an expired one.
    return {"last": shown[-1], "expired": shown[:-1]}


def _question_row(question: Mapping, operation: str | None) -> dict:
    _cell, text = _shown(question)
    answer = question.get("answer")
    outcome = question.get("outcome")
    return {
        "text": text,
        "m": _whole(question.get("m")),
        "n": _whole(question.get("n")),
        "operation": operation_of(question) or operation,
        "answer": "" if answer is None else str(answer),
        "outcome": outcome if outcome in OUTCOME_WORDS else None,
        "outcome_label": OUTCOME_WORDS.get(outcome, "Not answered yet"),
        "taken_ms": _ms(question.get("taken_ms")),
        "allowed_ms": _ms(question.get("allowed_ms")),
    }
