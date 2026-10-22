"""Where an observation sits on the household's usage grid.

The day is cut into equal lengths counted from local midnight. The length
divides 86400 seconds, so the last boundary of an ordinary day is the next
midnight. A daylight-saving day is not given a special case.

A load that changes the length closes every bucket that is still open, and
the following bucket starts at that load instead of on the old grid. It ends
at the next midnight boundary of the new length. Every bucket after that
boundary is the full new length again.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, time, timedelta

DAY_SECONDS = 24 * 60 * 60


def divides_day(length: int) -> bool:
    """Return whether length cuts a 24-hour day into equal buckets."""
    return (
        isinstance(length, int)
        and not isinstance(length, bool)
        and length >= 1
        and DAY_SECONDS % length == 0
    )


def require_day_length(length: object) -> int:
    """Return length when it divides the day. Raise ValueError otherwise."""
    if isinstance(length, bool) or not isinstance(length, int) or length < 1:
        raise ValueError("the bucket length is a whole number of seconds, one or more")
    if DAY_SECONDS % length != 0:
        raise ValueError(
            "the bucket length must divide a 24-hour day with nothing left over, "
            "so the buckets meet midnight"
        )
    return length


def place(moment: datetime, regimes: Sequence[Mapping[str, object]]) -> tuple[datetime, int]:
    """Return the bucket start and the length to store for moment.

    regimes is the length history, oldest first. The first entry has no "at"
    and applies from the beginning of the ledger. Later entries have "at", the
    household-local time the length was loaded. moment is household-local. An
    aware value is already in that zone; its offset is dropped, not converted.
    """
    if not regimes:
        raise ValueError("the bucket grid is not configured")
    wall = _naive(moment)
    chosen = 0
    anchors = [_anchor(regime) for regime in regimes]
    for index, anchor in enumerate(anchors):
        if anchor is None or anchor <= wall:
            chosen = index
        else:
            break
    length = _length(regimes[chosen])
    anchor = anchors[chosen]
    if anchor is not None:
        boundary = _boundary_after(anchor, length)
        if wall < boundary:
            return anchor, int((boundary - anchor).total_seconds())
    start = _align(wall, length)
    span = length
    for later in anchors[chosen + 1 :]:
        if later is None:
            continue
        end = start + timedelta(seconds=span)
        if start < later < end:
            span = int((later - start).total_seconds())
            break
    return start, span


def _align(wall: datetime, length: int) -> datetime:
    """Return the midnight boundary that contains wall."""
    midnight = datetime.combine(wall.date(), time.min)
    elapsed = int((wall - midnight).total_seconds())
    return midnight + timedelta(seconds=(elapsed // length) * length)


def _boundary_after(anchor: datetime, length: int) -> datetime:
    """Return the first midnight boundary of length strictly after anchor.

    When anchor is already on a boundary there is no short bucket, and the
    result is anchor itself so the caller keeps the ordinary grid.
    """
    aligned = _align(anchor, length)
    if aligned == anchor:
        return anchor
    return aligned + timedelta(seconds=length)


def _anchor(regime: Mapping[str, object]) -> datetime | None:
    raw = regime.get("at")
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("a bucket regime starts at a household-local time")
    return _naive(datetime.fromisoformat(raw))


def _length(regime: Mapping[str, object]) -> int:
    length = regime.get("length")
    if isinstance(length, bool) or not isinstance(length, int) or length < 1:
        raise ValueError("a bucket regime has a length of one or more seconds")
    return length


def _naive(moment: datetime) -> datetime:
    if not isinstance(moment, datetime):
        raise ValueError("time must be a datetime")
    if moment.tzinfo is not None:
        moment = moment.replace(tzinfo=None)
    return moment.replace(microsecond=0)
