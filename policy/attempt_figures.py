"""The figures of one attempt, worked out from its stored ``detail``.

An attempt's figures come from its last run: the run that decided its
outcome, or the run still in progress. An earlier run, such as one that
expired or a spelling run left for practice mode, is left out. An attempt in
progress or unfinished has the figures of its questions so far.

- ``points`` against ``pass_mark``. Arithmetic counts right answers against
  ``correct_answers_required``. Skip counting and parts of speech add the
  points of each sentence, 1, 0.5, or 0.25. Spelling has current points
  against ``current_required`` and revision points against
  ``revision_required``, and its ``points`` and ``pass_mark`` add the two.
- The pass mark is the one the run started with, from the settings stored on
  the attempt when that run began.
- ``questions`` is the number of finished questions. A question closed by a
  give-up or a reload was stored as a timeout and counts as one.
- ``maximum`` is ``maximum_questions`` where the run had one: always for parts
  of speech, when set for skip counting, and never for arithmetic or spelling.
- ``wrong`` counts questions that ended with no points and did not time out,
  and ``timeouts`` those that timed out.
- ``time_ms`` adds, over the questions, the time from issue to the last
  answer, or the time allowed for a timeout. ``average_ms`` is the mean of that
  time over the questions that earned points, or None when none did.

A type with no figures here, such as a later type or a parent check, has
None, and its tasks show only counts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass

from policy.arithmetic import ARITHMETIC
from policy.parts_of_speech import PARTS_OF_SPEECH
from policy.quiz import CORRECT, TIMEOUT
from policy.skip_counting import SKIP_COUNTING
from policy.skip_counting import parse_settings as skip_counting_settings
from policy.spelling import CURRENT, REVISION
from policy.spelling_words import SPELLING

TYPES = (ARITHMETIC, PARTS_OF_SPEECH, SKIP_COUNTING, SPELLING)


@dataclass(frozen=True)
class Figures:
    points: float
    pass_mark: int | None
    questions: int
    maximum: int | None
    wrong: int
    timeouts: int
    time_ms: int
    average_ms: float | None
    current_points: int | None = None
    current_required: int | None = None
    revision_points: int | None = None
    revision_required: int | None = None

    def as_json(self) -> dict:
        found = asdict(self)
        if self.current_points is None:
            for key in ("current_points", "current_required", "revision_points", "revision_required"):
                del found[key]
        return found


def figures(task_type: str, detail: Mapping) -> Figures | None:
    """Return an attempt's figures, or None when its type has none or nothing was asked yet."""
    if task_type not in TYPES or not isinstance(detail, Mapping):
        return None
    questions = detail.get("questions")
    if not isinstance(questions, list):
        return None
    runs = detail.get("runs")
    run = runs[-1] if isinstance(runs, list) and runs and isinstance(runs[-1], Mapping) else None
    number = run.get("run") if run is not None else None
    finished = [
        item
        for item in questions
        if isinstance(item, Mapping) and item.get("outcome") is not None and (number is None or item.get("run") == number)
    ]
    settings = detail.get("settings") if isinstance(detail.get("settings"), Mapping) else {}
    earned = [_points(task_type, item) for item in finished]
    times = [_time_ms(task_type, item) for item in finished]
    right = [time for time, points in zip(times, earned) if points > 0]
    timeouts = sum(1 for item in finished if item.get("outcome") == TIMEOUT)
    wrong = sum(1 for item, points in zip(finished, earned) if points <= 0 and item.get("outcome") != TIMEOUT)
    common = {
        "points": _tidy(sum(earned)),
        "questions": len(finished),
        "wrong": wrong,
        "timeouts": timeouts,
        "time_ms": sum(times),
        "average_ms": sum(right) / len(right) if right else None,
    }
    if task_type == SPELLING:
        run = run or {}
        by_pool = {CURRENT: 0, REVISION: 0}
        for item, points in zip(finished, earned):
            if points > 0 and item.get("pool") in by_pool:
                by_pool[item["pool"]] += 1
        current = _whole(run.get("current_required"))
        revision = _whole(run.get("revision_required"))
        return Figures(
            **common,
            pass_mark=None if current is None or revision is None else current + revision,
            maximum=None,
            current_points=by_pool[CURRENT],
            current_required=current,
            revision_points=by_pool[REVISION],
            revision_required=revision,
        )
    return Figures(**common, pass_mark=_pass_mark(task_type, settings), maximum=_maximum(task_type, settings))


def _points(task_type: str, question: Mapping) -> float:
    if task_type in (ARITHMETIC, SPELLING):
        return 1 if question.get("outcome") == CORRECT else 0
    points = question.get("points")
    return points if isinstance(points, (int, float)) and not isinstance(points, bool) else 0


def _time_ms(task_type: str, question: Mapping) -> int:
    """Return the time from issue to the last answer, or the time allowed for a timeout."""
    if question.get("outcome") == TIMEOUT:
        return _ms(question.get("allowed_ms"))
    if task_type == ARITHMETIC:
        return _ms(question.get("taken_ms"))
    if task_type == SPELLING:
        return _ms(question.get("received_ms"))
    tries = question.get("tries")
    if isinstance(tries, list) and tries and isinstance(tries[-1], Mapping):
        return _ms(tries[-1].get("received_ms"))
    return 0


def _pass_mark(task_type: str, settings: Mapping) -> int | None:
    if task_type == SKIP_COUNTING:
        # An omitted correct_answers_required is worked out from the other counts.
        try:
            return skip_counting_settings(settings).required
        except (ValueError, TypeError, KeyError):
            return _whole(settings.get("correct_answers_required"))
    return _whole(settings.get("correct_answers_required"))


def _maximum(task_type: str, settings: Mapping) -> int | None:
    if task_type in (PARTS_OF_SPEECH, SKIP_COUNTING):
        return _whole(settings.get("maximum_questions"))
    return None


def _whole(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _ms(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, round(value))


def _tidy(value: float) -> float | int:
    """Return a whole number of points as an int, so 20.0 reads 20."""
    return int(value) if float(value).is_integer() else value
