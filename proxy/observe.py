"""How many body bytes to report for one flow, and when.

Bytes are a delta since the previous report. An idle stretch, with nothing
new since that report, produces no observation. The flow end reports whatever
is still unreported, even when the interval has not elapsed.

The observation answer cuts a transfer only when it is the cut instruction.
Anything else, including an empty body, leaves the transfer running.
"""

from __future__ import annotations

import json


def is_cut_instruction(status: int, body: bytes) -> bool:
    """Return whether this answer tells the proxy to stop the transfer.

    The only cut is HTTP 200 and a JSON object whose only field is
    ``action`` set to ``cut``. A timeout never reaches this function.
    An empty body, a non-JSON body, and any other document are not a cut.
    """
    if status != 200 or not body:
        return False
    try:
        document = json.loads(body)
    except json.JSONDecodeError:
        return False
    return document == {"action": "cut"}


def stop_transfer(flow, handler) -> None:
    """Stop a live transfer.

    ``flow.kill()`` marks the flow and does not close a body that is already
    streaming, so the client and server sockets are closed as well. A missing
    handler still marks the flow. The first error is raised after both
    connections have been attempted.
    """
    error: Exception | None = None
    try:
        if getattr(flow, "killable", False):
            flow.kill()
    except Exception as exc:
        error = exc
    if handler is not None:
        transports = handler.transports
        for conn in (
            getattr(flow, "client_conn", None),
            getattr(flow, "server_conn", None),
        ):
            if conn is None:
                continue
            try:
                _close_connection(handler, transports, conn)
            except Exception as exc:
                if error is None:
                    error = exc
    if error is not None:
        raise error


def _close_connection(handler, transports, conn) -> None:
    transport = transports.get(conn)
    if transport is None:
        return
    writer = getattr(transport, "writer", None)
    if writer is not None and not writer.is_closing():
        writer.close()
    handler.close_connection(conn)


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
