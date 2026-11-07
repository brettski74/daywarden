"""Where an observation sits on the household's usage grid."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy.buckets import place, require_day_length  # noqa: E402

FIVE_MINUTES = [{"length": 300}]
# The household changed from five minutes to two at 15:02:30.
CHANGED = [{"length": 300}, {"at": "2026-10-21T15:02:30", "length": 120}]
# The household changed from five minutes to two exactly on a boundary.
ON_A_BOUNDARY = [{"length": 300}, {"at": "2026-10-21T15:00:00", "length": 120}]


def _at(hour: int, minute: int, second: int = 0, day: int = 21) -> datetime:
    return datetime(2026, 10, day, hour, minute, second)


def test_buckets_are_aligned_to_local_midnight():
    assert place(_at(15, 2), FIVE_MINUTES) == (_at(15, 0), 300)
    start, length = place(_at(23, 58), FIVE_MINUTES)
    assert (start, length) == (_at(23, 55), 300)
    assert start + timedelta(seconds=length) == _at(0, 0, day=22)


def test_an_aware_time_keeps_its_clock_and_drops_its_offset():
    sydney_wall = datetime(2026, 10, 21, 15, 0, 1, tzinfo=timezone(timedelta(hours=11)))
    assert place(sydney_wall, FIVE_MINUTES) == (_at(15, 0), 300)


def test_a_change_of_length_shortens_the_open_bucket_and_returns_to_midnight():
    assert place(_at(14, 0, 1), CHANGED) == (_at(14, 0), 300)
    assert place(_at(15, 1), CHANGED) == (_at(15, 0), 150)
    assert place(_at(15, 3), CHANGED) == (_at(15, 2, 30), 90)
    assert place(_at(15, 4), CHANGED) == (_at(15, 4), 120)
    assert place(_at(15, 8, 59), CHANGED) == (_at(15, 8), 120)


def test_a_change_on_a_boundary_does_not_open_a_short_bucket():
    assert place(_at(14, 57), ON_A_BOUNDARY) == (_at(14, 55), 300)
    assert place(_at(15, 0), ON_A_BOUNDARY) == (_at(15, 0), 120)
    assert place(_at(15, 2), ON_A_BOUNDARY) == (_at(15, 2), 120)


def test_a_single_length_uses_the_midnight_grid():
    assert place(_at(15, 3), [{"length": 120}]) == (_at(15, 2), 120)


def test_a_grid_with_no_length_is_refused():
    with pytest.raises(ValueError, match="not configured"):
        place(_at(15, 0), [])


@pytest.mark.parametrize("length", [120, 300, 600, 3600, 86400])
def test_lengths_that_meet_midnight_are_accepted(length):
    assert require_day_length(length) == length


@pytest.mark.parametrize("length", [7 * 60, 0, -300, True, "300"])
def test_other_lengths_are_refused(length):
    with pytest.raises(ValueError):
        require_day_length(length)
