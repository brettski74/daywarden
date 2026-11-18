"""Arithmetic practice (S039): the walk through one number's table, and which number to practise.

The walk is for one ``m`` and goes through the task's ``n`` values in
increasing order, two steps up and one step down. With ``N`` values of ``n``
numbered 0 to ``N - 1`` it asks the values in groups of three, ``j``,
``j + 1``, ``j``, for ``j`` from 0 to ``N - 2``, then ``N - 1`` on its own. So
the first and last ``n`` are each asked twice, every other ``n`` three times,
and the walk has ``3N - 2`` questions. A question's place in that walk is its
**position**, counted from 0, and the walk's state is only the position of
the next question.

A wrong answer or a timeout falls back: the walk starts again ``fallback``
values of ``n`` below the one missed, or from the first, which is the position
three times that index.

``m`` is the one in ``first`` (or in ``operands`` when there is no ``first``)
whose facts with the task's ``n`` values have the highest total weight in the
child's record, as the facts page shows it. A fact never asked weighs 1.
"""

from __future__ import annotations

import random

from policy.fact_figures import Book
from policy.quiz import WeightedList

# A task offers practice when it has at least this many values in operands.
MIN_OPERANDS = 5
DEFAULT_FALLBACK = 3
# Totals are compared to this many decimal places, so a tie is not lost to rounding.
_PLACES = 9


def length(count: int) -> int:
    """Return the number of questions in a walk through ``count`` values of ``n``."""
    return 3 * count - 2


def index_at(position: int, count: int) -> int:
    """Return which of the ``count`` values of ``n``, counting from 0, the question at ``position`` asks."""
    if position < 0 or position >= length(count):
        raise ValueError("the position is outside the walk")
    group, step = divmod(position, 3)
    if group >= count - 1:
        return count - 1
    return group + (1 if step == 1 else 0)


def restart(index: int, fallback: int) -> int:
    """Return the position a walk starts again from after a miss at the value ``index``, falling back ``fallback`` values."""
    return 3 * max(0, index - fallback)


def choose_m(lefts: WeightedList, rights: WeightedList, book: Book, rng: random.Random) -> int:
    """Return the ``m`` whose facts with every ``n`` in ``rights`` have the highest total weight, a tie broken at random.

    A fact with no figures weighs 1, so an ``m`` with none is worth
    ``rights.count`` and is never listed. Only the ``m`` values with figures
    are worked out one by one.
    """
    size = rights.count
    totals: dict[int, float] = {}
    for (m, n), found in book.facts.items():
        if lefts.has(m) and rights.has(n):
            totals[m] = totals.get(m, float(size)) + book.weight(found) - 1.0
    unfigured = lefts.count - len(totals)
    best = max((round(total, _PLACES) for total in totals.values()), default=None)
    baseline = round(float(size), _PLACES)
    if unfigured > 0 and (best is None or baseline >= best):
        top = baseline
    elif best is not None:
        top = best
    else:
        raise ValueError("an operand list is empty")
    winners = sorted(m for m, total in totals.items() if round(total, _PLACES) == top)
    waiting = unfigured if unfigured > 0 and baseline == top else 0
    point = rng.randrange(len(winners) + waiting)
    if point < len(winners):
        return winners[point]
    return lefts.pick(point - len(winners), less=dict.fromkeys(totals, 1))
