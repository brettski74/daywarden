"""S008.6: an observation past grace answers with a cut, and nothing else does."""

import asyncio
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

import pytest
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy.clock import HouseholdClock  # noqa: E402
from policy.engine import MemoryLedger, decide, judge  # noqa: E402
from policy.hierarchy import DEFAULT_TIME_GRACE, DEFAULT_VOLUME_GRACE, load  # noqa: E402
from policy.observations import CUT_BODY, listen, status_for  # noqa: E402
from policy.store import PolicyStore  # noqa: E402
from policy.usage import UsageStore  # noqa: E402

SYDNEY = ZoneInfo("Australia/Sydney")
WEDNESDAY = date(2026, 10, 21)
FIVE_MINUTES = 300
YOUTUBE = "https://www.youtube.com/watch?v=abc"
CLASSROOM = "https://classroom.google.com/u/0"
YOUNGER = "192.0.2.40"
ALLOW = {"action": "allow"}
TOO_MUCH = {"action": "deny", "status": 403, "message": "That's enough video for today."}

HOUSE = """\
timezone: Australia/Sydney
bucket_length: 5m

client_groups:
  younger:
    addresses: ["192.0.2.40"]

site_groups:
  school:
    priority: 10
    patterns:
      - classroom.google.com
  entertainment:
    priority: 30
    patterns:
      - "*.youtube.com"
      - youtube.com
"""

METER = """\
  entertainment_meter:
    - condition: site_group
      group: entertainment
      when_true: { action: continue }
      when_false: { action: deny, message: "Not entertainment." }
"""


def test_the_built_in_grace_is_five_minutes_and_one_mebibyte():
    assert DEFAULT_TIME_GRACE == FIVE_MINUTES
    assert DEFAULT_VOLUME_GRACE == 1024**2


def test_time_grace_waits_for_ended_buckets_and_volume_grace_counts_the_open_one(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  entertainment:
    time: 5m
    bytes: 1000b
    time_grace: 0s
    volume_grace: 100b
    ruleset: entertainment_meter
rule_sets:
  entry:
    - condition: volume_remaining
      quota: entertainment
      when_true: { action: allow }
      when_false: { action: deny, message: "That's enough video for today." }
"""
        + METER,
    )
    with UsageStore(":memory:") as usage:
        _approve(policy, usage, _at(15, 0))
        # Still inside the first bucket, so ended time is zero. The bytes are
        # already stored, and they are still under the limit plus grace.
        assert _answer(policy, usage, _at(15, 4), nbytes=1099) == (204, b"")
        assert usage.ended_seconds("younger", "entertainment", _at(15, 4)) == 0
        assert usage.stored_bytes("younger", "entertainment", _at(15, 4)) == 1099
        # The same open bucket crosses the volume grace. Time has not moved.
        assert _answer(policy, usage, _at(15, 4, 30), nbytes=1) == (200, CUT_BODY)
        assert usage.ended_seconds("younger", "entertainment", _at(15, 4, 30)) == 0


def test_default_grace_is_used_when_the_file_and_the_quota_omit_it(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  entertainment:
    time: 5m
    bytes: 100b
    ruleset: entertainment_meter
rule_sets:
  entry:
    - condition: time_remaining
      quota: entertainment
      when_true: { action: allow }
      when_false: { action: deny, message: "Time is up for today." }
"""
        + METER,
    )
    quota = policy.quota("entertainment")
    assert quota is not None
    assert quota.time_grace == DEFAULT_TIME_GRACE
    assert quota.volume_grace == DEFAULT_VOLUME_GRACE
    with UsageStore(":memory:") as usage:
        assumption = _approve(policy, usage, _at(15, 0, 1))
        assert assumption.recheck_at == _at(15, 10)
        assert _answer(policy, usage, _at(15, 0, 1), nbytes=1) == (204, b"")
        # One ended bucket is the limit, and the default five minutes is still left.
        assert _answer(policy, usage, _at(15, 5, 1), nbytes=1) == (204, b"")
        assert usage.ended_seconds("younger", "entertainment", _at(15, 5, 1)) == FIVE_MINUTES
        assert _answer(policy, usage, _at(15, 10, 1), nbytes=1) == (200, CUT_BODY)

    volume = _house(
        tmp_path,
        """\
entry: entry
quotas:
  entertainment:
    time: 5m
    bytes: 100b
    ruleset: entertainment_meter
rule_sets:
  entry:
    - condition: volume_remaining
      quota: entertainment
      when_true: { action: allow }
      when_false: { action: deny, message: "That's enough video for today." }
"""
        + METER,
    )
    with UsageStore(":memory:") as usage:
        _approve(volume, usage, _at(16, 0))
        under = 100 + DEFAULT_VOLUME_GRACE - 1
        assert _answer(volume, usage, _at(16, 0, 1), nbytes=under) == (204, b"")
        assert _answer(volume, usage, _at(16, 0, 2), nbytes=1) == (200, CUT_BODY)


def test_the_file_grace_applies_until_the_quota_sets_its_own(tmp_path):
    shared = """\
time_grace: 10m
volume_grace: 20b
entry: entry
quotas:
  pipe:
    time: 5m
    bytes: 100b
    ruleset: meter
rule_sets:
  entry:
    - condition: volume_remaining
      quota: pipe
      when_true: { action: allow }
      when_false: { action: deny, message: "That's enough video for today." }
  meter: []
"""
    inherited = _house(tmp_path, shared)
    quota = inherited.quota("pipe")
    assert quota is not None
    assert quota.time_grace == 10 * 60
    assert quota.volume_grace == 20
    with UsageStore(":memory:") as usage:
        _approve(inherited, usage, _at(15, 0))
        assert _answer(inherited, usage, _at(15, 0, 1), nbytes=119) == (204, b"")
        assert _answer(inherited, usage, _at(15, 0, 2), nbytes=1) == (200, CUT_BODY)
    timed = _house(
        tmp_path,
        shared.replace(
            "    - condition: volume_remaining\n      quota: pipe\n",
            "    - condition: time_remaining\n      quota: pipe\n",
        ),
    )
    with UsageStore(":memory:") as usage:
        assumption = _approve(timed, usage, _at(15, 0, 1))
        assert assumption.recheck_at == _at(15, 15)
        assert _answer(timed, usage, _at(15, 0, 1), nbytes=1) == (204, b"")
        assert _answer(timed, usage, _at(15, 5, 1), nbytes=1) == (204, b"")
        assert _answer(timed, usage, _at(15, 10, 1), nbytes=1) == (204, b"")
        assert usage.ended_seconds("younger", "pipe", _at(15, 10, 1)) == 2 * FIVE_MINUTES
        assert _answer(timed, usage, _at(15, 15, 1), nbytes=1) == (200, CUT_BODY)

    explicit = _house(
        tmp_path,
        shared.replace(
            "    ruleset: meter\n",
            "    time_grace: 0s\n    volume_grace: 0b\n    ruleset: meter\n",
        ),
    )
    quota = explicit.quota("pipe")
    assert quota is not None
    assert quota.time_grace == 0
    assert quota.volume_grace == 0
    with UsageStore(":memory:") as usage:
        _approve(explicit, usage, _at(15, 0))
        assert _answer(explicit, usage, _at(15, 0, 1), nbytes=99) == (204, b"")
        assert _answer(explicit, usage, _at(15, 0, 2), nbytes=1) == (200, CUT_BODY)
    explicit_time = _house(
        tmp_path,
        shared.replace(
            "    ruleset: meter\n",
            "    time_grace: 0s\n    volume_grace: 0b\n    ruleset: meter\n",
        ).replace(
            "    - condition: volume_remaining\n      quota: pipe\n",
            "    - condition: time_remaining\n      quota: pipe\n",
        ),
    )
    with UsageStore(":memory:") as usage:
        assumption = _approve(explicit_time, usage, _at(15, 0, 1))
        assert assumption.recheck_at == _at(15, 5)
        assert _answer(explicit_time, usage, _at(15, 0, 1), nbytes=1) == (204, b"")
        assert _answer(explicit_time, usage, _at(15, 5, 1), nbytes=1) == (200, CUT_BODY)


def test_one_quota_past_grace_cuts_even_when_another_is_inside(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  tight:
    bytes: 50b
    volume_grace: 0b
    time_grace: 1h
    ruleset: both
  loose:
    bytes: 5000b
    volume_grace: 0b
    time_grace: 1h
    ruleset: both
rule_sets:
  entry:
    - condition: volume_remaining
      quota: tight
      when_true: { action: allow }
      when_false: { action: deny, message: "That's enough video for today." }
  both: []
""",
    )
    with UsageStore(":memory:") as usage:
        _approve(policy, usage, _at(15, 0))
        assert _answer(policy, usage, _at(15, 0, 1), nbytes=49) == (204, b"")
        assert usage.stored_bytes("younger", "loose", _at(15, 0, 1)) == 49
        assert _answer(policy, usage, _at(15, 0, 2), nbytes=1) == (200, CUT_BODY)
        assert usage.stored_bytes("younger", "loose", _at(15, 0, 2)) == 50
        assert usage.stored_bytes("younger", "tight", _at(15, 0, 2)) == 50


def test_a_flow_inside_every_grace_is_not_cut(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  tight:
    bytes: 100b
    volume_grace: 50b
    ruleset: both
  loose:
    bytes: 100b
    volume_grace: 50b
    ruleset: both
rule_sets:
  entry:
    - condition: volume_remaining
      quota: tight
      when_true: { action: allow }
      when_false: { action: deny, message: "That's enough video for today." }
  both: []
""",
    )
    with UsageStore(":memory:") as usage:
        _approve(policy, usage, _at(15, 0))
        assert _answer(policy, usage, _at(15, 0, 1), nbytes=149) == (204, b"")
        assert usage.stored_bytes("younger", "tight", _at(15, 0, 1)) == 149
        assert usage.stored_bytes("younger", "loose", _at(15, 0, 1)) == 149


def test_traffic_that_does_not_accrue_is_not_cut(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  entertainment:
    bytes: 10b
    volume_grace: 0b
    ruleset: entertainment_meter
rule_sets:
  entry:
    - condition: site_group
      group: school
      when_true: { action: allow }
    - condition: volume_remaining
      quota: entertainment
      when_true: { action: allow }
      when_false: { action: deny, message: "That's enough video for today." }
"""
        + METER,
    )
    with UsageStore(":memory:") as usage:
        _approve(policy, usage, _at(15, 0))
        assert _answer(policy, usage, _at(15, 0, 1), nbytes=10) == (200, CUT_BODY)
        _approve(policy, usage, _at(15, 0), flow="school", url=CLASSROOM)
        assert _answer(policy, usage, _at(15, 0, 2), url=CLASSROOM, nbytes=100, flow="school") == (
            204,
            b"",
        )
        assert usage.stored_bytes("younger", "entertainment", _at(15, 0, 2)) == 10
        assert usage.site_buckets("younger", "school", WEDNESDAY)[0][3] == 100


def test_a_zero_limit_does_not_cut_that_side(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  entertainment:
    time: 5m
    ruleset: entertainment_meter
rule_sets:
  entry:
    - condition: time_remaining
      quota: entertainment
      when_true: { action: allow }
      when_false: { action: deny, message: "Time is up for today." }
"""
        + METER,
    )
    quota = policy.quota("entertainment")
    assert quota is not None
    assert quota.byte_limit == 0
    assert quota.volume_grace == DEFAULT_VOLUME_GRACE
    with UsageStore(":memory:") as usage:
        _approve(policy, usage, _at(15, 0, 1))
        assert _answer(policy, usage, _at(15, 0, 1), nbytes=2 * DEFAULT_VOLUME_GRACE) == (204, b"")
        assert _answer(policy, usage, _at(15, 5, 1), nbytes=1) == (204, b"")
        assert usage.ended_seconds("younger", "entertainment", _at(15, 5, 1)) == FIVE_MINUTES
        assert _answer(policy, usage, _at(15, 10, 1), nbytes=1) == (200, CUT_BODY)

    volume_only = _house(
        tmp_path,
        """\
time_grace: 0s
entry: entry
quotas:
  pipe:
    bytes: 100b
    volume_grace: 0b
    time_grace: 0s
    ruleset: meter
rule_sets:
  entry:
    - condition: volume_remaining
      quota: pipe
      when_true: { action: allow }
      when_false: { action: deny, message: "That's enough video for today." }
  meter: []
""",
    )
    with UsageStore(":memory:") as usage:
        _approve(volume_only, usage, _at(15, 0))
        assert _answer(volume_only, usage, _at(15, 0, 1), nbytes=1) == (204, b"")
        assert _answer(volume_only, usage, _at(15, 5, 1), nbytes=1) == (204, b"")
        assert _answer(volume_only, usage, _at(15, 10, 1), nbytes=1) == (204, b"")
        assert usage.ended_seconds("younger", "pipe", _at(15, 10, 1)) == 2 * FIVE_MINUTES
        assert _answer(volume_only, usage, _at(15, 10, 2), nbytes=97) == (200, CUT_BODY)


def test_a_new_request_at_the_limit_is_denied_without_a_cut(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  entertainment:
    bytes: 1000b
    volume_grace: 100b
    ruleset: entertainment_meter
rule_sets:
  entry:
    - condition: volume_remaining
      quota: entertainment
      when_true: { action: allow }
      when_false: { action: deny, message: "That's enough video for today." }
"""
        + METER,
    )
    with UsageStore(":memory:") as usage:
        _approve(policy, usage, _at(15, 0))
        assert _answer(policy, usage, _at(15, 0, 1), nbytes=1000) == (204, b"")
        assert _decision(policy, usage, _at(15, 1)) == TOO_MUCH
        assert _answer(policy, usage, _at(15, 1, 1), nbytes=99) == (204, b"")
        assert _decision(policy, usage, _at(15, 1, 2)) == TOO_MUCH
        assert _answer(policy, usage, _at(15, 1, 3), nbytes=1) == (200, CUT_BODY)


def test_a_failed_or_empty_answer_is_not_a_cut(tmp_path, monkeypatch):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  entertainment:
    bytes: 1000b
    volume_grace: 0b
    ruleset: entertainment_meter
rule_sets:
  entry:
    - condition: volume_remaining
      quota: entertainment
      when_true: { action: allow }
      when_false: { action: deny, message: "That's enough video for today." }
"""
        + METER,
    )
    database = tmp_path / "policy.sqlite3"
    with PolicyStore(database, check_same_thread=False) as store:
        usage = UsageStore(connection=store.connection)
        server = listen(
            store, "127.0.0.1", 0, tmp_path / "observations.jsonl", policy=policy, usage=usage
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        try:
            _wait_until_ready(port)
            _approve(policy, usage, _at(15, 0))
            status, content_type, body = _post(port, _report(_at(15, 0, 1), nbytes=10))
            assert (status, content_type, body) == (204, "text/plain", b"")
            assert _decision(policy, usage, _at(15, 1)) == ALLOW

            status, content_type, body = _post(port, _report(_at(15, 1, 1), nbytes=1000))
            assert status == 200
            assert content_type == "application/json"
            assert body == CUT_BODY
            assert _decision(policy, usage, _at(15, 2)) == TOO_MUCH

            status, content_type, body = _post(port, b"not-json")
            assert (status, content_type, body) == (400, "text/plain", b"")
            assert usage.stored_bytes("younger", "entertainment", _at(15, 2)) == 1010

            def fail(*_args, **_kwargs):
                raise RuntimeError("disk")

            monkeypatch.setattr(UsageStore, "file_observation", fail)
            status, content_type, body = _post(port, _report(_at(15, 3), nbytes=10))
            assert (status, content_type, body) == (500, "text/plain", b"")
            assert usage.stored_bytes("younger", "entertainment", _at(15, 3)) == 1010
            assert _decision(policy, usage, _at(15, 3)) == TOO_MUCH
        finally:
            server.shutdown()
            server.server_close()


def test_metering_without_a_remaining_check_does_not_cut(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  entertainment:
    bytes: 10b
    volume_grace: 0b
    ruleset: entertainment_meter
rule_sets:
  entry:
    - condition: always
      when_true: { action: allow }
"""
        + METER,
    )
    with UsageStore(":memory:") as usage:
        assumption = _approve(policy, usage, _at(15, 0))
        assert assumption.recheck_at is None
        assert assumption.ceilings == ()
        assert _answer(policy, usage, _at(15, 0, 1), nbytes=1000) == (204, b"")
        assert usage.stored_bytes("younger", "entertainment", _at(15, 0, 1)) == 1000


def test_a_report_without_a_recorded_allow_is_not_cut(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  entertainment:
    bytes: 10b
    volume_grace: 0b
    ruleset: entertainment_meter
rule_sets:
  entry:
    - condition: volume_remaining
      quota: entertainment
      when_true: { action: allow }
      when_false: { action: deny, message: "That's enough video for today." }
"""
        + METER,
    )
    with UsageStore(":memory:") as usage:
        _approve(policy, usage, _at(15, 0))
        assert _answer(policy, usage, _at(15, 0, 1), nbytes=1000, flow=None) == (204, b"")
        assert _answer(policy, usage, _at(15, 0, 2), nbytes=1000, flow="someone-else") == (204, b"")
        assert _answer(policy, usage, _at(15, 0, 3), nbytes=1000) == (200, CUT_BODY)


def test_a_spent_quota_can_hand_the_transfer_to_another(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  tight:
    bytes: 50b
    volume_grace: 0b
    ruleset: both
  loose:
    bytes: 80b
    volume_grace: 0b
    ruleset: both
rule_sets:
  entry:
    - condition: volume_remaining
      quota: tight
      when_true: { action: allow }
      when_false: { action: continue }
    - condition: volume_remaining
      quota: loose
      when_true: { action: allow }
      when_false: { action: deny, message: "That's enough video for today." }
  both: []
""",
    )
    with UsageStore(":memory:") as usage:
        assumption = _approve(policy, usage, _at(15, 0))
        assert assumption.ceilings == (("tight", 50),)
        assert _answer(policy, usage, _at(15, 0, 1), nbytes=49) == (204, b"")
        assert _answer(policy, usage, _at(15, 0, 2), nbytes=1) == (204, b"")
        kept = usage.transfer("flow-1")
        assert kept is not None
        assert kept[4] == (("loose", 80),)
        assert _answer(policy, usage, _at(15, 0, 3), nbytes=30) == (200, CUT_BODY)


def test_a_time_limit_does_not_cut_on_volume(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  entertainment:
    time: 2h
    bytes: 100b
    volume_grace: 0b
    ruleset: entertainment_meter
rule_sets:
  entry:
    - condition: time_remaining
      quota: entertainment
      when_true: { action: allow }
      when_false: { action: deny, message: "Time is up for today." }
"""
        + METER,
    )
    with UsageStore(":memory:") as usage:
        assumption = _approve(policy, usage, _at(15, 0, 1))
        assert assumption.ceilings == ()
        assert _answer(policy, usage, _at(15, 0, 2), nbytes=10_000) == (204, b"")
        assert usage.stored_bytes("younger", "entertainment", _at(15, 0, 2)) == 10_000


def test_the_earliest_window_boundary_includes_grace(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
time_windows:
  bedtime:
    periods:
      - start: "20:30"
        end: "07:00"
  evening:
    periods:
      - start: "15:00"
        end: "19:00"
rule_sets:
  entry:
    - condition: time_window
      window: bedtime
      when_true: { action: deny, message: "It's bedtime." }
    - condition: time_window
      window: evening
      when_true: { action: allow }
      when_false: { action: deny, message: "YouTube is closed for today." }
""",
    )
    with UsageStore(":memory:") as usage:
        assumption = _approve(policy, usage, _at(18, 50))
        assert assumption.recheck_at == _at(19, 5)
        assert _answer(policy, usage, _at(19, 4), nbytes=1) == (204, b"")
        assert _answer(policy, usage, _at(19, 5), nbytes=1) == (200, CUT_BODY)


def test_an_overlapping_deny_window_is_sooner_than_the_allow_window(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
time_windows:
  bedtime:
    periods:
      - start: "21:00"
        end: "07:00"
  evening:
    periods:
      - start: "15:00"
        end: "22:00"
rule_sets:
  entry:
    - condition: time_window
      window: bedtime
      when_true: { action: deny, message: "It's bedtime." }
    - condition: time_window
      window: evening
      when_true: { action: allow }
      when_false: { action: deny, message: "YouTube is closed for today." }
""",
    )
    with UsageStore(":memory:") as usage:
        assumption = _approve(policy, usage, _at(20, 0))
        assert assumption.recheck_at == _at(21, 5)


def test_ten_minutes_remaining_and_five_minutes_grace_recheck_at_the_third_bucket(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  entertainment:
    time: 10m
    time_grace: 5m
    ruleset: entertainment_meter
rule_sets:
  entry:
    - condition: time_remaining
      quota: entertainment
      when_true: { action: allow }
      when_false: { action: deny, message: "Time is up for today." }
"""
        + METER,
    )
    with UsageStore(":memory:") as usage:
        assumption = _approve(policy, usage, _at(19, 32))
        assert assumption.recheck_at == _at(19, 45)


def test_tasks_required_rechecks_at_midnight_plus_grace(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
rule_sets:
  entry:
    - condition: tasks_required
      required: 2
      when_true: { action: allow }
      when_false: { action: deny, message: "Revision first." }
""",
    )
    ledger = MemoryLedger()
    ledger.set_successes("younger", WEDNESDAY, 2)
    _trace, assumption = judge(
        policy, client_ip=YOUNGER, url=YOUTUBE, at=_at(23, 0), ledger=ledger
    )
    assert assumption.recheck_at == datetime(2026, 10, 22, 0, 5, tzinfo=SYDNEY)


def test_a_failed_time_check_does_not_schedule_a_quota_deadline(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  entertainment:
    time: 5m
    time_grace: 0s
    ruleset: entertainment_meter
rule_sets:
  entry:
    - condition: time_remaining
      quota: entertainment
      when_false: { action: allow }
"""
        + METER,
    )
    with UsageStore(":memory:") as usage:
        usage.file_observation("younger", "entertainment", _at(15, 0, 1), 1, ["entertainment"])
        assumption = _approve(policy, usage, _at(15, 6))
        assert assumption.recheck_at is None
        assert _answer(policy, usage, _at(15, 11), nbytes=1) == (204, b"")


def test_the_decision_service_records_an_allow(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  entertainment:
    bytes: 1000b
    volume_grace: 0b
    ruleset: entertainment_meter
rule_sets:
  entry:
    - condition: volume_remaining
      quota: entertainment
      when_true: { action: allow }
      when_false: { action: deny, message: "That's enough video for today." }
"""
        + METER,
    )
    database = tmp_path / "policy.sqlite3"
    monkeypatch.setenv("POLICY_FILE", str(tmp_path / "policy.yaml"))
    monkeypatch.setenv("POLICY_DB", str(database))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    monkeypatch.setenv("DECISION_FILE", str(tmp_path / "decision.json"))
    monkeypatch.delenv("DECISION_STUB", raising=False)
    monkeypatch.delenv("PARENT_PASSWORD", raising=False)
    app = create_app()
    status, body = _post_decision(
        app,
        {
            "client_ip": YOUNGER,
            "method": "GET",
            "url": YOUTUBE,
            "occurred_at": _at(15, 0).isoformat(),
            "flow_id": "flow-1",
        },
    )
    assert status == 200
    assert json.loads(body) == ALLOW
    with UsageStore(database) as usage:
        row = usage.transfer("flow-1")
        assert row is not None
        assert row[4] == (("entertainment", 1000),)
        assert _answer(policy, usage, _at(15, 0, 1), nbytes=1000) == (200, CUT_BODY)


def test_the_toml_ledger_answers_empty(tmp_path):
    with PolicyStore(":memory:") as store:
        body = json.dumps(_report(_at(15, 0, 1))).encode()
        assert status_for(store, body) == (204, b"")


def _house(directory: Path, body: str):
    path = directory / "policy.yaml"
    path.write_text(HOUSE + "\n" + body, encoding="utf-8")
    loaded = load(path)
    assert loaded is not None
    return loaded


def _at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 10, 21, hour, minute, second, tzinfo=SYDNEY)


def _approve(policy, usage: UsageStore, moment: datetime, *, flow: str = "flow-1", url: str = YOUTUBE):
    trace, assumption = judge(policy, client_ip=YOUNGER, url=url, at=moment, ledger=usage)
    assert trace.decision["action"] == "allow", trace.decision
    usage.save_transfer(flow, trace.client_group, trace.site_group, url, assumption)
    return assumption


def _report(
    moment: datetime,
    *,
    url: str = YOUTUBE,
    nbytes: int = 100,
    flow: str | None = "flow-1",
) -> dict:
    document = {
        "client_ip": YOUNGER,
        "url": url,
        "occurred_at": moment.isoformat(),
        "bytes": nbytes,
    }
    if flow is not None:
        document["flow_id"] = flow
    return document


def _answer(policy, usage: UsageStore, moment: datetime, **kwargs) -> tuple[int, bytes]:
    body = json.dumps(_report(moment, **kwargs)).encode()
    with PolicyStore(":memory:") as store:
        return status_for(store, body, policy=policy, usage=usage)


def _decision(policy, usage: UsageStore, moment: datetime) -> dict:
    return decide(policy, client_ip=YOUNGER, url=YOUTUBE, at=moment, ledger=usage).decision


def _post_decision(app, document: dict) -> tuple[int, bytes]:
    messages = []
    body = json.dumps(document).encode()
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/decisions",
        "raw_path": b"/v1/decisions",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 80),
        "root_path": "",
    }
    asyncio.run(app(scope, receive, send))
    status = next(item["status"] for item in messages if item["type"] == "http.response.start")
    payload = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
    return status, payload


def _wait_until_ready(port: int) -> None:
    deadline = time.monotonic() + 2
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.2) as response:
                if response.status == 200:
                    return
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.02)


def _post(port: int, payload: dict | bytes) -> tuple[int, str, bytes]:
    if isinstance(payload, dict):
        payload = json.dumps(payload).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/observations",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status, response.headers.get_content_type(), response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get_content_type(), error.read()
