"""How many body bytes to report for one flow, and when.

Bytes are a delta since the previous report. An idle stretch, with nothing
new since that report, produces no observation. The flow end reports whatever
is still unreported, even when the interval has not elapsed.
"""

from __future__ import annotations


class TrafficMeter:
    def __init__(self, interval: float, started_at: float) -> None:
        if interval <= 0:
            raise ValueError("interval must be positive")
        self.interval = interval
        self.pending = 0
        self.last_report = started_at

    def add(self, nbytes: int, now: float) -> int:
        """Record bytes that just arrived. Return a count to send now, or 0."""
        if nbytes:
            self.pending += nbytes
        return self.due(now)

    def due(self, now: float) -> int:
        """Return a count when the interval has passed and bytes are waiting."""
        if self.pending <= 0 or now - self.last_report < self.interval:
            return 0
        return self._take(now)

    def finish(self, now: float) -> int:
        """Return any bytes not yet reported. Zero when the flow is idle."""
        if self.pending <= 0:
            return 0
        return self._take(now)

    def _take(self, now: float) -> int:
        count = self.pending
        self.pending = 0
        self.last_report = now
        return count
