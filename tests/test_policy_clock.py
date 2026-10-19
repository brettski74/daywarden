"""S001.1: "today" and the local time come from the household timezone."""

import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy.clock import HouseholdClock, machine_zone, named_zone

TORONTO = ZoneInfo("America/Toronto")
SYDNEY = ZoneInfo("Australia/Sydney")


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("zone", "moment", "expected"),
    [
        # Toronto is UTC-4 in October. Its midnight is 04:00 UTC.
        (TORONTO, _utc("2026-10-20T03:59:59"), date(2026, 10, 19)),
        (TORONTO, _utc("2026-10-20T04:00:00"), date(2026, 10, 20)),
        # Sydney is UTC+11 in October. Its midnight is 13:00 UTC the day before.
        (SYDNEY, _utc("2026-10-19T12:59:59"), date(2026, 10, 19)),
        (SYDNEY, _utc("2026-10-19T13:00:00"), date(2026, 10, 20)),
        (timezone.utc, _utc("2026-10-19T23:59:59"), date(2026, 10, 19)),
        (timezone.utc, _utc("2026-10-20T00:00:00"), date(2026, 10, 20)),
    ],
)
def test_today_turns_over_at_household_midnight(zone, moment, expected):
    assert HouseholdClock(zone).today(moment) == expected


def test_today_differs_from_the_utc_date_late_in_a_western_evening():
    moment = _utc("2026-10-20T02:30:00")
    assert moment.date() == date(2026, 10, 20)
    assert HouseholdClock(TORONTO).today(moment) == date(2026, 10, 19)


def test_today_uses_the_clock_when_no_moment_is_given():
    before = HouseholdClock(SYDNEY, now=lambda: _utc("2026-10-19T12:59:59"))
    after = HouseholdClock(SYDNEY, now=lambda: _utc("2026-10-19T13:00:00"))
    assert before.today() == date(2026, 10, 19)
    assert after.today() == date(2026, 10, 20)
    assert after.local() == datetime(2026, 10, 20, 0, 0, tzinfo=SYDNEY)


def test_a_time_sent_with_another_offset_is_converted_to_household_time():
    clock = HouseholdClock(TORONTO)
    sent = datetime.fromisoformat("2026-10-20T03:59:59+00:00")
    local = clock.local(sent)
    assert (local.hour, local.minute, local.second) == (23, 59, 59)
    assert local.utcoffset().total_seconds() == -4 * 3600
    assert clock.today(sent) == date(2026, 10, 19)


def test_a_naive_time_is_already_household_local():
    clock = HouseholdClock(SYDNEY)
    assert clock.today(datetime(2026, 10, 19, 23, 59, 59)) == date(2026, 10, 19)
    assert clock.local(datetime(2026, 10, 20, 0, 0)) == datetime(2026, 10, 20, tzinfo=SYDNEY)


def test_midnight_after_a_daylight_saving_change_uses_the_new_offset():
    # Toronto leaves daylight saving on 2026-11-01. Midnight that night is 05:00 UTC.
    clock = HouseholdClock(TORONTO)
    assert clock.today(_utc("2026-11-02T04:59:59")) == date(2026, 11, 1)
    assert clock.today(_utc("2026-11-02T05:00:00")) == date(2026, 11, 2)


def test_named_zone_rejects_names_that_are_not_zones():
    for bad in ("Mars/Olympus_Mons", "America", "", "../etc/passwd"):
        with pytest.raises(ValueError):
            named_zone(bad)


def test_machine_zone_prefers_tz(tmp_path):
    zone = machine_zone({"TZ": "Australia/Sydney"}, tmp_path / "missing")
    assert zone.utcoffset(datetime(2026, 10, 19)).total_seconds() == 11 * 3600


def test_machine_zone_reads_a_localtime_symlink_by_name(tmp_path):
    link = tmp_path / "localtime"
    os.symlink("/usr/share/zoneinfo/America/Toronto", link)
    assert str(machine_zone({}, link)) == "America/Toronto"


def test_machine_zone_reads_a_copied_zone_file(tmp_path):
    copied = tmp_path / "localtime"
    copied.write_bytes(Path("/usr/share/zoneinfo/Australia/Sydney").read_bytes())
    zone = machine_zone({}, copied)
    clock = HouseholdClock(zone)
    assert clock.today(_utc("2026-10-19T13:00:00")) == date(2026, 10, 20)


def test_machine_zone_ignores_a_bad_tz_and_falls_back_to_utc(tmp_path):
    zone = machine_zone({"TZ": "Not/AZone"}, tmp_path / "missing")
    assert zone.utcoffset(datetime(2026, 10, 19)).total_seconds() == 0
