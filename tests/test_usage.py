"""S008.3: an observation is filed once, then accrued to each quota that accepts it."""

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy.clock import HouseholdClock  # noqa: E402
from policy.engine import decide, judge  # noqa: E402
from policy.hierarchy import load  # noqa: E402
from policy.observations import listen, status_for  # noqa: E402
from policy.store import PolicyStore  # noqa: E402
from policy.usage import UsageStore, observe  # noqa: E402

SYDNEY = ZoneInfo("Australia/Sydney")
WEDNESDAY = date(2026, 10, 21)
FIVE_MINUTES = 300
TWO_HOURS = 2 * 60 * 60
YOUTUBE = "https://www.youtube.com/watch?v=abc"
CLASSROOM = "https://classroom.google.com/u/0"
TASKS = "http://tasks.example/next"
YOUNGER = "192.0.2.40"
OLDER = "192.0.2.41"
UNKNOWN = "192.0.2.99"
ALLOW = {"action": "allow"}
TIME_UP = {"action": "deny", "status": 403, "message": "Time is up for today."}
NO_BYTES = {"action": "deny", "status": 403, "message": "No bytes left."}
TOO_MUCH = {"action": "deny", "status": 403, "message": "That's enough video for today."}

HOUSE = """\
timezone: Australia/Sydney
bucket_length: 5m

client_groups:
  younger:
    addresses: ["192.0.2.40"]
  older:
    addresses: ["192.0.2.41"]

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


def _load(directory: Path, text: str):
    path = directory / "policy.yaml"
    path.write_text(text, encoding="utf-8")
    loaded = load(path)
    assert loaded is not None
    return loaded


def _house(directory: Path, body: str):
    return _load(directory, HOUSE + "\n" + body)


def _at(hour: int, minute: int = 0, second: int = 0, day: int = 21) -> datetime:
    return datetime(2026, 10, day, hour, minute, second, tzinfo=SYDNEY)


def _clock() -> HouseholdClock:
    return HouseholdClock(SYDNEY)


def _report(
    moment: datetime,
    *,
    ip: str = YOUNGER,
    url: str = YOUTUBE,
    nbytes: int = 100,
    flow: str | None = None,
) -> dict:
    document = {
        "client_ip": ip,
        "url": url,
        "occurred_at": moment.isoformat(),
        "bytes": nbytes,
    }
    if flow is not None:
        document["flow_id"] = flow
    return document


def _observe(policy, usage: UsageStore, moment: datetime, **kwargs) -> bool:
    return observe(policy, usage, _clock(), _report(moment, **kwargs))


def _decision(policy, usage: UsageStore, moment: datetime, *, ip: str = YOUNGER, url: str = YOUTUBE) -> dict:
    return decide(policy, client_ip=ip, url=url, at=moment, ledger=usage).decision


def test_entertainment_accrues_and_classroom_stays_on_the_site_group(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  entertainment:
    time: 2h
    ruleset: entertainment_meter
rule_sets:
  entry:
    - condition: always
      when_true: { action: allow }
"""
        + METER,
    )
    with UsageStore(":memory:") as usage:
        assert _observe(policy, usage, _at(15, 0, 1), nbytes=100)
        assert _observe(policy, usage, _at(15, 3), nbytes=40)
        assert usage.site_buckets("younger", "entertainment", WEDNESDAY) == [
            (WEDNESDAY, datetime(2026, 10, 21, 15, 0), FIVE_MINUTES, 140)
        ]
        assert usage.quota_buckets("younger", "entertainment", WEDNESDAY) == [
            (WEDNESDAY, datetime(2026, 10, 21, 15, 0), FIVE_MINUTES, 140)
        ]
        assert usage.ended_seconds("younger", "entertainment", _at(15, 4)) == 0
        assert usage.ended_seconds("younger", "entertainment", _at(15, 5)) == FIVE_MINUTES
        assert usage.stored_bytes("younger", "entertainment", _at(15, 4)) == 140

        assert _observe(policy, usage, _at(15, 1), url=CLASSROOM, nbytes=80)
        assert usage.stored_bytes("younger", "entertainment", _at(15, 4)) == 140
        assert usage.quota_buckets("younger", "entertainment", WEDNESDAY)[0][3] == 140
        school = usage.site_buckets("younger", "school", WEDNESDAY)
        assert school == [(WEDNESDAY, datetime(2026, 10, 21, 15, 0), FIVE_MINUTES, 80)]
        assert [name for name, *_rest in usage.client_buckets("younger", WEDNESDAY)] == [
            "entertainment",
            "school",
        ]


def test_falling_off_a_quota_rule_set_accrues_including_school(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  loose:
    time: 2h
    ruleset: loose
  empty:
    time: 1h
    ruleset: empty
rule_sets:
  entry:
    - condition: always
      when_true: { action: allow }
  loose:
    - condition: site_group
      group: entertainment
      when_true: { action: continue }
  empty: []
""",
    )
    with UsageStore(":memory:") as usage:
        assert _observe(policy, usage, _at(15, 0, 1), url=CLASSROOM, nbytes=80)
        assert usage.stored_bytes("younger", "loose", WEDNESDAY) == 80
        assert usage.stored_bytes("younger", "empty", WEDNESDAY) == 80
        assert usage.site_buckets("younger", "school", WEDNESDAY)[0][3] == 80


def test_one_quota_definition_has_a_balance_per_client_group(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  entertainment:
    time: 2h
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
        start = _at(8, 0, 1)
        for index in range(24):
            _observe(policy, usage, start + timedelta(minutes=5 * index))
        _observe(policy, usage, _at(8, 0, 1, day=20), ip=OLDER, nbytes=20)
        assert _decision(policy, usage, _at(10, 0)) == TIME_UP
        assert _decision(policy, usage, _at(10, 0), ip=OLDER) == ALLOW
        assert usage.ended_seconds("older", "entertainment", _at(10, 0)) == 0
        assert usage.ended_seconds("older", "entertainment", _at(8, 5, day=20)) == FIVE_MINUTES
        assert usage.ended_seconds("younger", "entertainment", _at(10, 0)) == TWO_HOURS
        assert usage.quota_clients("entertainment") == ["older", "younger"]


def test_two_quotas_each_accrue_once_and_overlapping_patterns_do_not(tmp_path):
    both = _house(
        tmp_path,
        """\
entry: entry
quotas:
  screen:
    time: 2h
    ruleset: entertainment_meter
  youtube_bytes:
    bytes: 1M
    ruleset: entertainment_meter
rule_sets:
  entry:
    - condition: always
      when_true: { action: allow }
"""
        + METER,
    )
    with UsageStore(":memory:") as usage:
        assert _observe(both, usage, _at(15, 0, 1), nbytes=100)
        assert usage.stored_bytes("younger", "screen", _at(15, 4)) == 100
        assert usage.stored_bytes("younger", "youtube_bytes", _at(15, 4)) == 100
        assert usage.site_buckets("younger", "entertainment", WEDNESDAY)[0][3] == 100
        assert len(usage.quota_buckets("younger", "screen", WEDNESDAY)) == 1
        assert len(usage.quota_buckets("younger", "youtube_bytes", WEDNESDAY)) == 1

    overlap = _load(
        tmp_path,
        """\
entry: entry
timezone: Australia/Sydney
client_groups:
  younger:
    addresses: ["192.0.2.40"]
site_groups:
  classroom:
    priority: 10
    patterns:
      - classroom.google.com
  google:
    priority: 20
    patterns:
      - "*.google.com"
quotas:
  classroom_time:
    time: 1h
    ruleset: classroom_meter
  google_time:
    time: 1h
    ruleset: google_meter
rule_sets:
  entry:
    - condition: always
      when_true: { action: allow }
  classroom_meter:
    - condition: site_group
      group: classroom
      when_true: { action: continue }
      when_false: { action: deny, message: "Not classroom." }
  google_meter:
    - condition: site_group
      group: google
      when_true: { action: continue }
      when_false: { action: deny, message: "Not google." }
""",
    )
    with UsageStore(":memory:") as usage:
        assert _observe(overlap, usage, _at(15, 0, 1), url=CLASSROOM, nbytes=80)
        assert usage.stored_bytes("younger", "classroom_time", _at(15, 4)) == 80
        assert usage.stored_bytes("younger", "google_time", _at(15, 4)) == 0
        filed = usage.client_buckets("younger", WEDNESDAY)
        assert [name for name, *_rest in filed] == ["classroom"]
        assert filed[0][4] == 80


def test_twenty_three_buckets_leave_time_and_twenty_four_use_it_up(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  entertainment:
    time: 2h
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
    assert policy.quota("entertainment").time_limit == TWO_HOURS
    with UsageStore(":memory:") as usage:
        start = _at(8, 0, 1)
        for index in range(23):
            _observe(policy, usage, start + timedelta(minutes=5 * index))
        assert usage.ended_seconds("younger", "entertainment", _at(9, 55)) == 23 * FIVE_MINUTES
        assert _decision(policy, usage, _at(9, 55)) == ALLOW

        _observe(policy, usage, _at(9, 55, 1))
        assert usage.ended_seconds("younger", "entertainment", _at(9, 59)) == 23 * FIVE_MINUTES
        assert _decision(policy, usage, _at(9, 59)) == ALLOW
        assert usage.ended_seconds("younger", "entertainment", _at(10, 0)) == TWO_HOURS
        assert _decision(policy, usage, _at(10, 0)) == TIME_UP

        usage.install_length(10 * 60, _at(10, 30))
        lengths = [length for _day, _start, length, _nbytes in usage.quota_buckets("younger", "entertainment", WEDNESDAY)]
        assert lengths == [FIVE_MINUTES] * 24
        site_lengths = [
            length for _day, _start, length, _nbytes in usage.site_buckets("younger", "entertainment", WEDNESDAY)
        ]
        assert site_lengths == [FIVE_MINUTES] * 24
        assert policy.quota("entertainment").time_limit == TWO_HOURS
        assert _decision(policy, usage, _at(10, 30)) == TIME_UP

        _observe(policy, usage, _at(10, 31), nbytes=5)
        opened = usage.quota_buckets("younger", "entertainment", WEDNESDAY)[-1]
        assert opened[1:] == (datetime(2026, 10, 21, 10, 30), 10 * 60, 5)
        assert usage.ended_seconds("younger", "entertainment", _at(10, 31)) == TWO_HOURS


def test_an_open_bucket_is_shortened_when_the_length_changes_and_an_ended_one_is_not(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  entertainment:
    time: 2h
    ruleset: entertainment_meter
rule_sets:
  entry:
    - condition: always
      when_true: { action: allow }
"""
        + METER,
    )
    with UsageStore(":memory:") as usage:
        _observe(policy, usage, _at(14, 0, 1), nbytes=10)
        _observe(policy, usage, _at(15, 0, 1), nbytes=100)
        usage.install_length(120, _at(15, 2, 30))
        rows = usage.quota_buckets("younger", "entertainment", WEDNESDAY)
        assert [(start, length) for _day, start, length, _nbytes in rows] == [
            (datetime(2026, 10, 21, 14, 0), FIVE_MINUTES),
            (datetime(2026, 10, 21, 15, 0), 150),
        ]
        _observe(policy, usage, _at(15, 3), nbytes=7)
        _observe(policy, usage, _at(15, 4, 30), nbytes=1)
        rows = usage.site_buckets("younger", "entertainment", WEDNESDAY)
        assert [(start, length) for _day, start, length, _nbytes in rows] == [
            (datetime(2026, 10, 21, 14, 0), FIVE_MINUTES),
            (datetime(2026, 10, 21, 15, 0), 150),
            (datetime(2026, 10, 21, 15, 2, 30), 90),
            (datetime(2026, 10, 21, 15, 4), 120),
        ]


def test_open_bucket_bytes_count_and_a_missing_byte_limit_stays_false(tmp_path):
    limited = _house(
        tmp_path,
        """\
entry: entry
quotas:
  entertainment:
    time: 2h
    bytes: 1000b
    ruleset: entertainment_meter
rule_sets:
  entry:
    - condition: time_remaining
      quota: entertainment
      when_false: { action: deny, message: "Time is up for today." }
    - condition: volume_remaining
      quota: entertainment
      when_true: { action: allow }
      when_false: { action: deny, message: "That's enough video for today." }
"""
        + METER,
    )
    with UsageStore(":memory:") as usage:
        _observe(limited, usage, _at(15, 0, 1), nbytes=600)
        assert _decision(limited, usage, _at(15, 4)) == ALLOW
        _observe(limited, usage, _at(15, 2), nbytes=400)
        assert usage.ended_seconds("younger", "entertainment", _at(15, 4)) == 0
        assert usage.stored_bytes("younger", "entertainment", _at(15, 4)) == 1000
        assert _decision(limited, usage, _at(15, 4)) == TOO_MUCH

    missing = _house(
        tmp_path,
        """\
entry: entry
quotas:
  entertainment:
    time: 2h
    ruleset: entertainment_meter
rule_sets:
  entry:
    - condition: volume_remaining
      quota: entertainment
      when_true: { action: allow }
      when_false: { action: deny, message: "No bytes left." }
"""
        + METER,
    )
    assert missing.quota("entertainment").byte_limit == 0
    with UsageStore(":memory:") as usage:
        assert _decision(missing, usage, _at(15, 4)) == NO_BYTES
        _observe(missing, usage, _at(15, 0, 1), nbytes=500)
        assert usage.stored_bytes("younger", "entertainment", _at(15, 4)) == 500
        assert usage.site_buckets("younger", "entertainment", WEDNESDAY)[0][3] == 500
        assert _decision(missing, usage, _at(15, 4)) == NO_BYTES


def test_allow_accrues_and_redirect_does_not(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  opened:
    time: 1h
    ruleset: allow_it
  sent_away:
    time: 1h
    ruleset: redirect_it
rule_sets:
  entry:
    - condition: always
      when_true: { action: allow }
  allow_it:
    - condition: always
      when_true: { action: allow }
  redirect_it:
    - condition: always
      when_true: { action: redirect, location: "http://tasks.example/next" }
""",
    )
    with UsageStore(":memory:") as usage:
        _observe(policy, usage, _at(15, 0, 1), nbytes=30)
        assert usage.stored_bytes("younger", "opened", _at(15, 4)) == 30
        assert usage.stored_bytes("younger", "sent_away", _at(15, 4)) == 0
        assert usage.site_buckets("younger", "entertainment", WEDNESDAY)[0][3] == 30


def test_a_decision_does_not_record_and_the_next_request_is_its_own(tmp_path):
    policy = _load(
        tmp_path,
        """\
entry: entry
timezone: Australia/Sydney
revision_task: "http://tasks.example/next"
client_groups:
  younger:
    addresses: ["192.0.2.40"]
site_groups:
  tasks:
    priority: 10
    patterns:
      - tasks.example
  entertainment:
    priority: 30
    patterns:
      - "*.youtube.com"
quotas:
  entertainment:
    time: 2h
    ruleset: entertainment_meter
  tasks:
    time: 1h
    ruleset: task_meter
rule_sets:
  entry:
    - condition: site_group
      group: entertainment
      when_true: { action: redirect, location: "http://tasks.example/next" }
    - condition: site_group
      group: tasks
      when_true: { action: allow }
    - condition: always
      when_true: { action: deny, message: "No." }
  entertainment_meter:
    - condition: site_group
      group: entertainment
      when_true: { action: continue }
      when_false: { action: deny, message: "Not entertainment." }
  task_meter:
    - condition: site_group
      group: tasks
      when_true: { action: continue }
      when_false: { action: deny, message: "Not a task." }
""",
    )
    with UsageStore(":memory:") as usage:
        redirected = decide(policy, client_ip=YOUNGER, url=YOUTUBE, at=_at(15, 0), ledger=usage)
        assert redirected.decision["action"] == "redirect"
        denied = decide(policy, client_ip=YOUNGER, url="https://example.org/", at=_at(15, 0), ledger=usage)
        assert denied.decision == {"action": "deny", "status": 403, "message": "No."}
        assert usage.client_buckets("younger", WEDNESDAY) == []
        assert usage.quota_clients("entertainment") == []

        allowed = decide(policy, client_ip=YOUNGER, url=TASKS, at=_at(15, 1), ledger=usage)
        assert allowed.decision == ALLOW
        assert usage.client_buckets("younger", WEDNESDAY) == []

        _observe(policy, usage, _at(15, 1, 1), url=TASKS, nbytes=45)
        assert usage.stored_bytes("younger", "entertainment", _at(15, 2)) == 0
        assert usage.stored_bytes("younger", "tasks", _at(15, 2)) == 45
        assert [name for name, *_rest in usage.client_buckets("younger", WEDNESDAY)] == ["tasks"]


def test_an_unknown_computer_and_an_unknown_site_are_default(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  leftovers:
    time: 1h
    ruleset: empty
rule_sets:
  entry:
    - condition: always
      when_true: { action: allow }
  empty: []
""",
    )
    with UsageStore(":memory:") as usage:
        _observe(policy, usage, _at(15, 0, 1), ip=UNKNOWN, url="https://example.org/page", nbytes=12)
        assert [name for name, *_rest in usage.client_buckets("default", WEDNESDAY)] == ["default"]
        assert usage.stored_bytes("default", "leftovers", _at(15, 4)) == 12
        assert usage.quota_clients("leftovers") == ["default"]
        assert usage.stored_bytes("younger", "leftovers", _at(15, 4)) == 0


def test_a_failed_observation_leaves_the_decision_and_stores_past_grace(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  entertainment:
    time: 5m
    bytes: 1000b
    time_grace: 5m
    volume_grace: 100b
    ruleset: entertainment_meter
rule_sets:
  entry:
    - condition: time_remaining
      quota: entertainment
      when_false: { action: deny, message: "Time is up for today." }
    - condition: volume_remaining
      quota: entertainment
      when_true: { action: allow }
      when_false: { action: deny, message: "That's enough video for today." }
"""
        + METER,
    )
    quota = policy.quota("entertainment")
    assert quota is not None
    assert quota.time_grace == FIVE_MINUTES
    assert quota.volume_grace == 100
    with UsageStore(":memory:") as usage:
        assert _decision(policy, usage, _at(15, 0)) == ALLOW
        with pytest.raises(ValueError):
            observe(policy, usage, _clock(), {"client_ip": YOUNGER, "url": YOUTUBE, "occurred_at": "nope", "bytes": 10})
        assert _decision(policy, usage, _at(15, 0)) == ALLOW
        assert usage.client_buckets("younger", WEDNESDAY) == []

        original = usage._mark

        def fail_quota(table, *args, **kwargs):
            if table == "quota_buckets":
                raise RuntimeError("disk")
            return original(table, *args, **kwargs)

        usage._mark = fail_quota
        with pytest.raises(RuntimeError):
            _observe(policy, usage, _at(15, 0, 1), nbytes=50)
        usage._mark = original
        assert usage.client_buckets("younger", WEDNESDAY) == []
        assert _decision(policy, usage, _at(15, 4)) == ALLOW

        _observe(policy, usage, _at(15, 0, 1), nbytes=2000)
        assert usage.stored_bytes("younger", "entertainment", _at(15, 4)) == 2000
        assert _decision(policy, usage, _at(15, 4)) == TOO_MUCH
        for index in range(3):
            _observe(policy, usage, _at(16, 0, 1) + timedelta(minutes=5 * index), nbytes=1)
        # The 15:00 bucket has ended as well as the three that started at 16:00.
        # Twenty minutes is past the 5m limit plus the 5m grace, and nothing was cut.
        assert usage.ended_seconds("younger", "entertainment", _at(16, 15)) == 4 * FIVE_MINUTES
        assert usage.ended_seconds("younger", "entertainment", _at(16, 15)) > quota.time_limit + quota.time_grace
        assert _decision(policy, usage, _at(16, 15)) == TIME_UP


def test_a_report_with_no_bytes_is_ignored(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  entertainment:
    time: 2h
    ruleset: entertainment_meter
rule_sets:
  entry:
    - condition: always
      when_true: { action: allow }
"""
        + METER,
    )
    with UsageStore(":memory:") as usage:
        assert _observe(policy, usage, _at(15, 0, 1), nbytes=0) is False
        assert usage.client_buckets("younger", WEDNESDAY) == []


def test_the_old_client_and_site_group_rows_are_not_the_ledger(tmp_path):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  entertainment:
    time: 2h
    ruleset: entertainment_meter
rule_sets:
  entry:
    - condition: always
      when_true: { action: allow }
"""
        + METER,
    )
    with PolicyStore(":memory:") as store:
        usage = UsageStore(connection=store.connection)
        _observe(policy, usage, _at(15, 0, 1), nbytes=100)
        (old_rows,) = store.connection.execute("SELECT COUNT(*) FROM usage_buckets").fetchone()
        assert old_rows == 0
        assert usage.stored_bytes("younger", "entertainment", _at(15, 4)) == 100


def test_a_balance_on_a_zero_grace_is_a_cut_and_a_failure_is_not(tmp_path, monkeypatch):
    policy = _house(
        tmp_path,
        """\
entry: entry
quotas:
  entertainment:
    time: 5m
    bytes: 1000b
    time_grace: 0s
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
        server = listen(store, "127.0.0.1", 0, tmp_path / "observations.jsonl", policy=policy, usage=usage)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        try:
            _wait_until_ready(port)
            trace, assumption = judge(
                policy, client_ip=YOUNGER, url=YOUTUBE, at=_at(15, 0), ledger=usage
            )
            assert trace.decision == ALLOW
            usage.save_transfer("flow-1", trace.client_group, trace.site_group, YOUTUBE, assumption)
            status, body = _post(port, _report(_at(15, 0, 1), nbytes=2000, flow="flow-1"))
            assert status == 200
            assert body == b'{"action":"cut"}'
            assert usage.stored_bytes("younger", "entertainment", _at(15, 4)) == 2000
            assert _decision(policy, usage, _at(15, 4)) == TOO_MUCH

            status, body = _post(port, b"not-json")
            assert status == 400
            assert usage.stored_bytes("younger", "entertainment", _at(15, 4)) == 2000

            def fail(*_args, **_kwargs):
                raise RuntimeError("disk")

            monkeypatch.setattr(UsageStore, "file_observation", fail)
            status, body = _post(port, _report(_at(15, 6), nbytes=10))
            assert status == 500
            assert body == b""
            assert usage.stored_bytes("younger", "entertainment", _at(15, 4)) == 2000
            assert _decision(policy, usage, _at(15, 4)) == TOO_MUCH
        finally:
            server.shutdown()
            server.server_close()


def test_a_missing_yaml_policy_accepts_a_report_and_records_nothing(tmp_path):
    with PolicyStore(":memory:") as store:
        usage = UsageStore(connection=store.connection)
        body = json.dumps(_report(_at(15, 0, 1))).encode()
        assert status_for(store, body, policy=None, usage=usage) == (204, b"")
        assert usage.quota_clients("entertainment") == []


def test_the_decision_service_reads_the_quota_balance(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(
        HOUSE
        + """
entry: entry
quotas:
  entertainment:
    time: 2h
    bytes: 1000b
    ruleset: entertainment_meter
rule_sets:
  entry:
    - condition: volume_remaining
      quota: entertainment
      when_true: { action: allow }
      when_false: { action: deny, message: "That's enough video for today." }
"""
        + METER,
        encoding="utf-8",
    )
    database = tmp_path / "policy.sqlite3"
    monkeypatch.setenv("POLICY_FILE", str(policy_path))
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
            "occurred_at": _at(15, 4).isoformat(),
        },
    )
    assert status == 200
    assert json.loads(body) == ALLOW

    policy = load(policy_path)
    assert policy is not None
    with UsageStore(database) as usage:
        observe(policy, usage, _clock(), _report(_at(15, 0, 1), nbytes=1000))
    status, body = _post_decision(
        app,
        {
            "client_ip": YOUNGER,
            "method": "GET",
            "url": YOUTUBE,
            "occurred_at": _at(15, 4).isoformat(),
        },
    )
    assert status == 200
    assert json.loads(body) == TOO_MUCH


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


def _post(port: int, payload: dict | bytes) -> tuple[int, bytes]:
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
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _post_decision(app, document: dict) -> tuple[int, bytes]:
    import asyncio

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
