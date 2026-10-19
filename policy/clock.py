"""What time it is in the household, and which local date that falls on."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from datetime import date, datetime, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MACHINE_LOCALTIME = Path("/etc/localtime")


def named_zone(name: str) -> ZoneInfo:
    """Return the IANA zone called name. Raise ValueError when there is no such zone."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ValueError(f"unknown timezone {name!r}") from exc


def machine_zone(
    environ: Mapping[str, str] = os.environ,
    localtime: Path = MACHINE_LOCALTIME,
) -> tzinfo:
    """Return the timezone of the machine running the service.

    TZ wins when it names an IANA zone. Otherwise localtime is read: by its
    symlink target when it has one, so the zone keeps its name, and as a zone
    file when it has been copied or bind-mounted. UTC is the last resort.
    """
    name = environ.get("TZ", "").lstrip(":")
    if name:
        try:
            return named_zone(name)
        except ValueError:
            pass
    try:
        target = os.readlink(localtime)
    except OSError:
        target = ""
    if "zoneinfo/" in target:
        try:
            return named_zone(target.split("zoneinfo/", 1)[1])
        except ValueError:
            pass
    try:
        with open(localtime, "rb") as handle:
            return ZoneInfo.from_file(handle, key="localtime")
    except (OSError, ValueError):
        return timezone.utc


class HouseholdClock:
    def __init__(self, zone: tzinfo, now: Callable[[], datetime] | None = None) -> None:
        self.zone = zone
        self._now = now or (lambda: datetime.now(timezone.utc))

    def local(self, moment: datetime | None = None) -> datetime:
        """Return moment, or now, as household-local time.

        A naive moment is taken to be household-local already.
        """
        if moment is None:
            moment = self._now()
        if moment.tzinfo is None:
            return moment.replace(tzinfo=self.zone)
        return moment.astimezone(self.zone)

    def today(self, moment: datetime | None = None) -> date:
        """Return the household-local date of moment, or of now."""
        return self.local(moment).date()
