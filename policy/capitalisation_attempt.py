"""A capitalisation attempt's page (S040.2): its runs, each sentence in order with every try he made.

A try shows the sentence as the pool spells it, with each word he clicked
blue when it needed a capital and red when it did not, and each capital he
missed red, as the answer after the last try does (S040.1). A try that was
right shows the points it earned. A try that ran out of time shows a timeout.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from policy.attempt_figures import figures
from policy.capitalisation import CAPITALISATION, marked
from policy.parts_of_speech import POINTS
from policy.quiz import CORRECT, INCORRECT, TIMEOUT
from policy.tasks import Attempt

OUTCOMES = {CORRECT: "Correct", INCORRECT: "Incorrect", TIMEOUT: "Timed out"}


def capitalisation_runs(attempt: Attempt, stamp: Callable[[str], str]) -> dict | None:
    """Return a capitalisation attempt's runs for its page: the last run, then each earlier run in order.

    Each run has its figures, as S035.1 works them out, and its sentences in
    order. None when the attempt holds no capitalisation record.
    """
    detail = attempt.detail if isinstance(attempt.detail, Mapping) else {}
    questions, runs = detail.get("questions"), detail.get("runs")
    if attempt.task_type != CAPITALISATION or not isinstance(questions, list) or not isinstance(runs, list) or not runs:
        return None
    shown = []
    for run in runs:
        if not isinstance(run, Mapping):
            continue
        number = run.get("run")
        mine = [item for item in questions if isinstance(item, Mapping) and item.get("run") == number]
        found = figures(CAPITALISATION, detail, number)
        expired = run.get("expired")
        shown.append(
            {
                "run": number,
                "expired": stamp(expired) if isinstance(expired, str) else None,
                "figures": None if found is None else found.as_json(),
                "sentences": [_sentence(item) for item in mine],
            }
        )
    if not shown:
        return None
    return {"last": shown[-1], "expired": shown[:-1]}


def _sentence(question: Mapping) -> dict:
    outcome = question.get("outcome")
    words = question.get("words") if isinstance(question.get("words"), list) else []
    tries = [each for each in question.get("tries", []) if isinstance(each, Mapping)] if isinstance(question.get("tries"), list) else []
    shown = [_try(question, each, number, outcome, number == len(tries)) for number, each in enumerate(tries, 1)]
    if outcome == TIMEOUT and not tries:
        # The sentence closed with no try sent, so the only thing to show is what he missed.
        shown.append({"words": marked({"words": words}, ()), "points": 0, "timeout": True, "taken_ms": _ms(question.get("allowed_ms"))})
    return {
        "text": " ".join(str(item.get("word", "")) for item in words if isinstance(item, Mapping)),
        "outcome": outcome if outcome in OUTCOMES else None,
        "outcome_label": OUTCOMES.get(outcome, "Not answered yet"),
        "points": question.get("points") if isinstance(question.get("points"), (int, float)) else 0,
        "tries": shown,
    }


def _try(question: Mapping, sent: Mapping, number: int, outcome: object, last: bool) -> dict:
    clicks = sent.get("clicks") if isinstance(sent.get("clicks"), list) else []
    right = not sent.get("wrong") and not sent.get("missed")
    timeout = last and outcome == TIMEOUT
    points = POINTS[number - 1] if right and not timeout and number <= len(POINTS) else 0
    return {
        "words": marked(question, clicks),
        "points": points,
        "timeout": timeout,
        "taken_ms": _ms(sent.get("received_ms")),
    }


def _ms(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, round(value))
