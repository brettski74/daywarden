"""When a flow's body bytes are worth an observation, and when the answer cuts."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proxy"))

import observe


def test_bytes_wait_until_the_interval_and_are_not_cumulative():
    meter = observe.TrafficMeter(interval=60, started_at=0)
    assert meter.add(10, 0) == 0
    assert meter.add(5, 59) == 0
    assert meter.add(1, 60) == 16
    assert meter.add(4, 119) == 0
    assert meter.add(1, 120) == 5
    assert meter.pending == 0


def test_idle_after_a_report_produces_nothing():
    meter = observe.TrafficMeter(interval=60, started_at=0)
    assert meter.add(10, 60) == 10
    assert meter.due(120) == 0
    assert meter.due(10_000) == 0
    assert meter.finish(10_001) == 0


def test_only_the_cut_instruction_stops_a_transfer():
    assert observe.is_cut_instruction(200, b'{"action":"cut"}')
    assert observe.is_cut_instruction(200, b'\n{"action": "cut"}\n')
    assert not observe.is_cut_instruction(204, b"")
    assert not observe.is_cut_instruction(204, b'{"action":"cut"}')
    assert not observe.is_cut_instruction(200, b"")
    assert not observe.is_cut_instruction(200, b"not-json")
    assert not observe.is_cut_instruction(200, b'{"action":"allow"}')
    assert not observe.is_cut_instruction(200, b'{"action":"cut","quota":"entertainment"}')
    assert not observe.is_cut_instruction(500, b'{"action":"cut"}')
    assert not observe.is_cut_instruction(200, b"[]")


def test_stopping_a_transfer_closes_both_sockets():
    flow = _Flow()
    client = _Transport()
    server = _Transport()
    handler = _Handler({flow.client_conn: client, flow.server_conn: server})
    observe.stop_transfer(flow, handler)
    assert flow.killed
    assert client.writer.closed
    assert server.writer.closed
    assert handler.closed == [flow.client_conn, flow.server_conn]


def test_a_missing_handler_still_marks_the_flow_killed():
    flow = _Flow()
    observe.stop_transfer(flow, None)
    assert flow.killed


def test_a_kill_error_still_closes_the_sockets():
    flow = _Flow()
    flow.killable = True

    def explode():
        raise RuntimeError("already gone")

    flow.kill = explode
    client = _Transport()
    handler = _Handler({flow.client_conn: client})
    try:
        observe.stop_transfer(flow, handler)
    except RuntimeError as exc:
        assert str(exc) == "already gone"
    else:
        raise AssertionError("the kill error should surface")
    assert client.writer.closed
    assert handler.closed == [flow.client_conn]


def test_finish_reports_a_short_transfer_once():
    meter = observe.TrafficMeter(interval=60, started_at=0)
    assert meter.add(8, 1) == 0
    assert meter.finish(2) == 8
    assert meter.finish(3) == 0
    assert meter.due(100) == 0


class _Writer:
    def __init__(self) -> None:
        self.closed = False

    def is_closing(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.closed = True


class _Transport:
    def __init__(self) -> None:
        self.writer = _Writer()


class _Handler:
    def __init__(self, transports: dict) -> None:
        self.transports = transports
        self.closed: list = []

    def close_connection(self, conn) -> None:
        self.closed.append(conn)


class _Flow:
    def __init__(self) -> None:
        self.killable = True
        self.killed = False
        self.client_conn = object()
        self.server_conn = object()

    def kill(self) -> None:
        self.killed = True
        self.killable = False
