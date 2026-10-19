"""When a flow's body bytes are worth an observation."""

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


def test_finish_reports_a_short_transfer_once():
    meter = observe.TrafficMeter(interval=60, started_at=0)
    assert meter.add(8, 1) == 0
    assert meter.finish(2) == 8
    assert meter.finish(3) == 0
    assert meter.due(100) == 0
