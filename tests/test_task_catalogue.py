"""S003.1: task catalogue, cooldown, skip days, pass cap, and attempt rows."""

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy.engine import classify_client, decide  # noqa: E402
from policy.hierarchy import ConfigError, load  # noqa: E402
from policy.tasks import AttemptStore, Task  # noqa: E402
from policy.usage import UsageStore  # noqa: E402

ZONE = ZoneInfo("America/Toronto")
YOUNGER = "192.0.2.40"
TABLET = "192.0.2.41"
OLDER = "192.0.2.50"
NOVEMBER = 11


def _at(day: int, hour: int = 16, minute: int = 0, *, month: int = NOVEMBER) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=ZONE)


def _day(day: int, *, month: int = NOVEMBER) -> date:
    return date(2026, month, day)


def _task(**overrides) -> Task:
    fields = {
        "name": "parts-of-speech-1",
        "type": "parts_of_speech",
        "groups": ("younger",),
        "pass_cooldown": 21,
        "body": "{}",
        "failure_cooldown": 1,
        "available_from": None,
        "due_date": None,
        "max_skips": None,
        "max_passes": None,
    }
    fields.update(overrides)
    return Task(**fields)


def _file(directory: Path, text: str) -> Path:
    path = directory / "policy.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _policy(text: str, directory: Path):
    loaded = load(_file(directory, text))
    assert loaded is not None
    return loaded


HOUSE = """\
entry: gate
timezone: America/Toronto
client_groups:
  younger:
    addresses: ["192.0.2.40", "192.0.2.41"]
  older:
    addresses: ["192.0.2.50"]
tasks:
  parts-of-speech-1:
    type: parts_of_speech
    group: younger
    pass_cooldown: 21
    failure_cooldown: 1
    body:
      sentences:
        - sentence: "The cat sat."
          parts: { noun: [cat] }
  parts-of-speech-2:
    type: parts_of_speech
    groups: [younger, older]
    pass_cooldown: 21
    due_date: 2026-11-09
    body:
      sentences:
        - sentence: "A dog ran."
          parts: { verb: [ran] }
rule_sets:
  gate:
    - condition: tasks_required
      required: 1
      when_true: { action: allow }
      when_false: { action: deny, message: "Not yet." }
"""


def test_a_task_is_only_eligible_for_an_assigned_group(tmp_path):
    policy = _policy(HOUSE, tmp_path)
    task = policy.task("parts-of-speech-1")
    assert task is not None
    assert task.document() == {"sentences": [{"sentence": "The cat sat.", "parts": {"noun": ["cat"]}}]}
    assert classify_client(policy, YOUNGER) == "younger"
    assert classify_client(policy, TABLET) == "younger"
    assert classify_client(policy, OLDER) == "older"
    today = _day(2)
    with AttemptStore(":memory:") as store:
        assert store.is_eligible(task, "younger", today)
        assert store.is_eligible(task, "younger", today)
        assert not store.is_eligible(task, "older", today)
        store.record("younger", task.name, "failure", _at(2), detail={"picked": "verb"})
        assert [row.outcome for row in store.attempts("younger", task.name)] == ["failure"]
        assert store.attempts("older", task.name) == ()
        assert store.attempts("younger")[0].detail == {"picked": "verb"}


def test_a_pass_cooldown_waits_until_the_household_day_it_names():
    task = _task(pass_cooldown=21, failure_cooldown=1)
    passed = _day(5)
    with AttemptStore(":memory:") as store:
        store.record("younger", task.name, "pass", _at(5))
        assert not store.is_eligible(task, "younger", passed + timedelta(days=20))
        assert store.is_eligible(task, "younger", passed + timedelta(days=21))


def test_a_failure_uses_the_failure_cooldown_and_an_abandon_does_not():
    task = _task(pass_cooldown=21, failure_cooldown=1)
    with AttemptStore(":memory:") as store:
        store.record("younger", task.name, "failure", _at(2))
        assert not store.is_eligible(task, "younger", _day(2))
        assert store.is_eligible(task, "younger", _day(3))

    abandoned = _task()
    with AttemptStore(":memory:") as store:
        store.record("younger", abandoned.name, "abandoned", _at(2))
        assert store.is_eligible(abandoned, "younger", _day(2))
        assert store.is_eligible(abandoned, "younger", _day(3))


def test_an_omitted_failure_cooldown_does_not_make_a_failure_wait():
    task = _task(failure_cooldown=None, pass_cooldown=21)
    with AttemptStore(":memory:") as store:
        store.record("younger", task.name, "failure", _at(2))
        assert store.is_eligible(task, "younger", _day(2))


def test_coming_back_returns_the_attempt_already_in_progress():
    with AttemptStore(":memory:") as store:
        first = store.begin("younger", "parts-of-speech-1", _at(2), detail={"shown": [1]})
        second = store.begin("younger", "parts-of-speech-1", _at(2, 17))
        other_task = store.begin("younger", "parts-of-speech-2", _at(2))
        other_group = store.begin("older", "parts-of-speech-1", _at(2))
        assert second.id == first.id
        assert second.started_at == first.started_at
        assert second.detail == {"shown": [1]}
        assert other_task.id != first.id
        assert other_group.id != first.id
        done = store.finish(first.id, "pass", _at(2, 18), {"answers": ["noun"]})
        assert done.outcome == "pass"
        assert done.detail == {"answers": ["noun"]}
        assert done.finished_at == _at(2, 18)
        with pytest.raises(ValueError, match="already finished"):
            store.finish(first.id, "failure", _at(2, 19), {})


def test_todays_pass_count_is_the_passes_finished_on_this_household_day(tmp_path):
    policy = _policy(
        HOUSE.replace("required: 1", "required: 2"),
        tmp_path,
    )
    with UsageStore(":memory:") as usage:
        store = AttemptStore(connection=usage.connection)
        moment = _at(2, 16)
        assert usage.successes("younger", _day(2)) == 0
        assert decide(policy, client_ip=YOUNGER, url="https://example.com/", at=moment, ledger=usage).decision[
            "action"
        ] == "deny"
        store.record("younger", "parts-of-speech-1", "pass", moment)
        store.record("younger", "parts-of-speech-1", "failure", _at(2, 17))
        store.record("older", "parts-of-speech-2", "pass", _at(2, 18))
        assert usage.successes("younger", _day(2)) == 1
        assert store.passes_on("younger", _day(2)) == 1
        assert usage.successes("older", _day(2)) == 1
        assert decide(policy, client_ip=YOUNGER, url="https://example.com/", at=moment, ledger=usage).decision[
            "action"
        ] == "deny"
        store.record("younger", "parts-of-speech-2", "pass", _at(2, 19))
        assert usage.successes("younger", _day(2)) == 2
        assert decide(policy, client_ip=YOUNGER, url="https://example.com/", at=moment, ledger=usage).decision[
            "action"
        ] == "allow"
        assert usage.successes("younger", _day(1)) == 0


def test_a_pass_at_the_first_minutes_of_the_day_counts_for_the_new_day(tmp_path):
    policy = _policy(HOUSE, tmp_path)
    early = datetime(2026, 11, 3, 0, 10, tzinfo=ZONE)
    late = datetime(2026, 11, 2, 23, 50, tzinfo=ZONE)
    with UsageStore(":memory:") as usage:
        store = AttemptStore(connection=usage.connection)
        store.record("younger", "parts-of-speech-1", "pass", early)
        assert usage.successes("younger", date(2026, 11, 3)) == 1
        assert usage.successes("younger", date(2026, 11, 2)) == 0
        assert decide(policy, client_ip=YOUNGER, url="https://example.com/", at=early, ledger=usage).decision[
            "action"
        ] == "allow"
        assert decide(policy, client_ip=YOUNGER, url="https://example.com/", at=late, ledger=usage).decision[
            "action"
        ] == "deny"
        store.record("younger", "parts-of-speech-2", "pass", late)
        assert usage.successes("younger", date(2026, 11, 2)) == 1
        assert usage.successes("younger", date(2026, 11, 3)) == 1


def test_attempt_rows_and_the_skip_days_derived_from_them_survive_a_restart(tmp_path):
    task = _task(max_skips=3, failure_cooldown=0, pass_cooldown=0)
    path = tmp_path / "attempts.sqlite3"
    with AttemptStore(path) as store:
        store.record("younger", task.name, "abandoned", _at(2))
        store.record("younger", task.name, "failure", _at(3))
        started = store.begin("younger", task.name, _at(4))
    with AttemptStore(path) as store:
        assert [row.outcome for row in store.attempts("younger", task.name)] == [
            "abandoned",
            "failure",
            "in_progress",
        ]
        assert store.in_progress("younger", task.name).id == started.id
        assert not store.is_required(task, "younger", _day(4))
        store.finish(started.id, "abandoned", _at(4), {})
        assert store.is_required(task, "younger", _day(5))
    with AttemptStore(path) as store:
        assert store.is_required(task, "younger", _day(5))


def test_available_from_hides_the_task_until_that_household_day():
    task = _task(available_from=_day(3), pass_cooldown=0, failure_cooldown=None)
    with AttemptStore(":memory:") as store:
        assert not store.is_eligible(task, "younger", _day(2))
        assert not store.is_required(task, "younger", _day(2))
        assert store.is_eligible(task, "younger", _day(3))


def test_a_future_due_date_does_not_require_the_task_and_the_due_day_does():
    task = _task(due_date=_day(5), pass_cooldown=0, failure_cooldown=None)
    shared = _task(groups=("younger", "older"), due_date=_day(5), pass_cooldown=0, failure_cooldown=None)
    with AttemptStore(":memory:") as store:
        assert store.is_eligible(task, "younger", _day(4))
        assert not store.is_required(task, "younger", _day(4))
        assert store.is_required(task, "younger", _day(5))
        store.record("older", shared.name, "pass", _at(4))
        assert store.is_required(shared, "younger", _day(5))
        assert not store.is_required(shared, "older", _day(5))


def test_a_pass_before_the_due_date_means_that_date_does_not_require_it():
    task = _task(due_date=_day(5), pass_cooldown=1, failure_cooldown=0, max_skips=1)
    with AttemptStore(":memory:") as store:
        store.record("younger", task.name, "pass", _at(2))
        assert not store.is_required(task, "younger", _day(5))
        assert store.is_eligible(task, "younger", _day(3))
        store.record("younger", task.name, "abandoned", _at(3))
        assert not store.is_required(task, "younger", _day(3))
        assert store.is_required(task, "younger", _day(4))


def test_a_due_failure_stays_required_once_the_failure_cooldown_ends():
    # A 1-day failure cooldown blocks the finish day and allows the next one.
    task = _task(due_date=_day(2), failure_cooldown=1, pass_cooldown=21)
    with AttemptStore(":memory:") as store:
        store.record("younger", task.name, "failure", _at(2))
        assert store.passes_on("younger", _day(2)) == 0
        assert not store.is_eligible(task, "younger", _day(2))
        assert not store.is_required(task, "younger", _day(2))
        assert store.is_eligible(task, "younger", _day(3))
        assert store.is_required(task, "younger", _day(3))


def test_two_tasks_of_one_type_keep_separate_histories():
    first = _task(name="parts-of-speech-1", due_date=_day(2), pass_cooldown=0, failure_cooldown=None)
    second = _task(name="parts-of-speech-2", due_date=_day(2), pass_cooldown=0, failure_cooldown=None)
    with AttemptStore(":memory:") as store:
        store.record("younger", first.name, "pass", _at(2))
        assert not store.is_required(first, "younger", _day(2))
        assert store.is_required(second, "younger", _day(2))
        assert store.attempts("younger", second.name) == ()


def test_three_skip_days_leave_the_task_optional_until_the_next_day():
    task = _task(max_skips=3, pass_cooldown=0, failure_cooldown=0)
    with AttemptStore(":memory:") as store:
        store.record("younger", task.name, "abandoned", _at(2))
        store.record("younger", task.name, "abandoned", _at(2, 18))
        assert not store.is_required(task, "younger", _day(2))
        assert not store.is_required(task, "younger", _day(3))
        store.record("younger", task.name, "failure", _at(3))
        store.record("younger", task.name, "abandoned", _at(3, 18))
        assert not store.is_required(task, "younger", _day(3))
        store.record("younger", task.name, "abandoned", _at(4))
        assert not store.is_required(task, "younger", _day(4))
        assert store.is_eligible(task, "younger", _day(5))
        assert store.is_required(task, "younger", _day(5))


def test_the_november_abandon_calendar_resets_after_a_pass():
    task = _task(max_skips=3, pass_cooldown=21, failure_cooldown=1)
    with AttemptStore(":memory:") as store:
        assert store.is_eligible(task, "younger", _day(2))
        for day in (2, 3, 4):
            assert not store.is_required(task, "younger", _day(day))
            store.record("younger", task.name, "abandoned", _at(day))
            assert not store.is_required(task, "younger", _day(day))
        assert store.is_required(task, "younger", _day(5))
        store.record("younger", task.name, "pass", _at(5))
        assert not store.is_eligible(task, "younger", _day(25))
        assert store.is_eligible(task, "younger", _day(26))
        for day in (26, 27, 28):
            assert not store.is_required(task, "younger", _day(day))
            store.record("younger", task.name, "abandoned", _at(day))
            assert not store.is_required(task, "younger", _day(day))
        assert store.is_required(task, "younger", _day(29))


def test_a_pass_clears_skip_days():
    task = _task(max_skips=3, pass_cooldown=0, failure_cooldown=1)
    with AttemptStore(":memory:") as store:
        store.record("younger", task.name, "pass", _at(1))
        store.record("younger", task.name, "abandoned", _at(2))
        store.record("younger", task.name, "abandoned", _at(3))
        assert not store.is_required(task, "younger", _day(4))
        store.record("younger", task.name, "failure", _at(4))
        assert not store.is_required(task, "younger", _day(4))
        assert store.is_eligible(task, "younger", _day(5))
        assert store.is_required(task, "younger", _day(5))


def test_several_misses_on_one_household_day_are_one_skip():
    task = _task(max_skips=3, pass_cooldown=21, failure_cooldown=0)
    with AttemptStore(":memory:") as store:
        for hour in (16, 17, 18):
            assert store.is_eligible(task, "younger", _day(2))
            store.record("younger", task.name, "failure", _at(2, hour))
        assert not store.is_required(task, "younger", _day(3))
    with AttemptStore(":memory:") as store:
        store.record("younger", task.name, "failure", _at(2))
        store.record("younger", task.name, "abandoned", _at(2, 18))
        assert not store.is_required(task, "younger", _day(3))


def test_failures_on_three_days_require_the_task_on_the_fourth():
    task = _task(max_skips=3, pass_cooldown=21, failure_cooldown=1)
    with AttemptStore(":memory:") as store:
        for day in (2, 3, 4):
            assert store.is_eligible(task, "younger", _day(day))
            assert not store.is_required(task, "younger", _day(day))
            store.record("younger", task.name, "failure", _at(day))
            assert not store.is_required(task, "younger", _day(day))
        assert store.is_eligible(task, "younger", _day(5))
        assert store.is_required(task, "younger", _day(5))


def test_max_skips_of_zero_requires_the_task_on_the_first_eligible_day():
    task = _task(max_skips=0, pass_cooldown=21, failure_cooldown=1)
    with AttemptStore(":memory:") as store:
        assert store.is_required(task, "younger", _day(2))


def test_due_date_and_max_skips_each_require_the_task_on_their_own():
    by_skips = _task(due_date=_day(10), max_skips=1, pass_cooldown=0, failure_cooldown=0)
    by_due = _task(due_date=_day(2), max_skips=3, pass_cooldown=0, failure_cooldown=None)
    with AttemptStore(":memory:") as store:
        store.record("younger", by_skips.name, "abandoned", _at(2))
        assert store.is_required(by_skips, "younger", _day(3))
        assert store.is_required(by_due, "younger", _day(2))
        assert not store.is_required(by_due, "younger", _day(1))


def test_available_from_after_the_due_date_holds_the_task_back():
    task = _task(
        available_from=_day(5),
        due_date=_day(2),
        pass_cooldown=0,
        failure_cooldown=None,
    )
    with AttemptStore(":memory:") as store:
        for day in (2, 3, 4):
            assert not store.is_eligible(task, "younger", _day(day))
            assert not store.is_required(task, "younger", _day(day))
        assert store.is_eligible(task, "younger", _day(5))
        assert store.is_required(task, "younger", _day(5))


def test_parent_check_ignores_dates_skips_and_the_pass_cap():
    task = _task(
        name="reading-log",
        type="parent_check",
        pass_cooldown=0,
        failure_cooldown=None,
        available_from=_day(3),
        due_date=_day(2),
        max_skips=0,
        max_passes=1,
    )
    with AttemptStore(":memory:") as store:
        assert store.is_eligible(task, "younger", _day(2))
        assert not store.is_required(task, "younger", _day(2))
        assert not store.is_eligible(task, "older", _day(2))
        store.record("younger", task.name, "pass", _at(2), task_set="parent_check")
        store.record("younger", task.name, "pass", _at(2, 17), task_set="parent_check")
        assert store.passes_on("younger", _day(2)) == 2
        assert store.is_eligible(task, "younger", _day(2))
        assert not store.is_required(task, "younger", _day(2))
        cooled = _task(
            name="reading-log",
            type="parent_check",
            pass_cooldown=21,
            max_passes=1,
            due_date=_day(2),
            max_skips=0,
        )
        assert not store.is_eligible(cooled, "younger", _day(3))


def test_max_passes_retires_the_task_for_that_client_group_only():
    task = _task(max_passes=3, pass_cooldown=21, failure_cooldown=1, groups=("younger", "older"))
    other = _task(name="parts-of-speech-2", max_passes=3, pass_cooldown=21)
    with AttemptStore(":memory:") as store:
        store.record("younger", task.name, "pass", _at(1, month=10))
        store.record("younger", task.name, "pass", _at(22, month=10))
        third_day = date(2026, 11, 12)
        assert store.is_eligible(task, "younger", third_day)
        assert store.is_eligible(task, "older", _day(2))
        assert store.is_eligible(other, "younger", _day(2))
        store.record("younger", task.name, "pass", datetime(2026, 11, 12, 16, tzinfo=ZONE))
        assert store.passes_on("younger", third_day) == 1
        assert not store.is_eligible(task, "younger", third_day + timedelta(days=21))
        due = _task(
            max_passes=3,
            due_date=third_day + timedelta(days=21),
            pass_cooldown=0,
            failure_cooldown=None,
        )
        assert not store.is_eligible(due, "younger", due.due_date)
        assert not store.is_required(due, "younger", due.due_date)


def test_changing_max_passes_uses_the_passes_already_stored():
    history = _task(max_passes=3, pass_cooldown=21)
    with AttemptStore(":memory:") as store:
        store.record("younger", history.name, "pass", _at(1, month=10))
        store.record("younger", history.name, "pass", _at(22, month=10))
        today = date(2026, 11, 12)
        assert store.is_eligible(history, "younger", today)
        started = store.begin("younger", history.name, datetime(2026, 11, 12, 16, tzinfo=ZONE))
        lowered = _task(max_passes=2, pass_cooldown=21)
        assert not store.is_eligible(lowered, "younger", today)
        done = store.finish(started.id, "pass", datetime(2026, 11, 12, 17, tzinfo=ZONE), {"ok": True})
        assert done.outcome == "pass"
        assert store.passes_on("younger", today) == 1
        raised = _task(max_passes=4, pass_cooldown=21)
        cleared = _task(max_passes=None, pass_cooldown=21)
        assert not store.is_eligible(lowered, "younger", today + timedelta(days=21))
        assert store.is_eligible(raised, "younger", today + timedelta(days=21))
        assert store.is_eligible(cleared, "younger", today + timedelta(days=21))
        none = _task(name="fresh", max_passes=0, pass_cooldown=0, failure_cooldown=None)
        assert not store.is_eligible(none, "younger", today)
        assert not store.is_required(none, "younger", today)


def test_editing_the_body_does_not_ask_for_another_pass():
    cat = '{"sentences":[{"sentence":"The cat sat.","parts":{"noun":["cat"]}}]}'
    dog = '{"sentences":[{"sentence":"A dog ran.","parts":{"verb":["ran"]}}]}'
    original = _task(max_passes=1, pass_cooldown=0, failure_cooldown=None, body=cat)
    edited = _task(max_passes=1, pass_cooldown=0, failure_cooldown=None, body=dog)
    with AttemptStore(":memory:") as store:
        store.record("younger", original.name, "pass", _at(2))
        assert not store.is_eligible(edited, "younger", _day(3))
        assert edited.document()["sentences"][0]["sentence"] == "A dog ran."


def test_the_loader_reads_dates_groups_and_an_opaque_body(tmp_path):
    policy = _policy(
        """\
entry: open
client_groups:
  younger:
    addresses: ["192.0.2.40"]
tasks:
  worksheet-1:
    type: worksheet
    groups: [younger, default]
    pass_cooldown: 0
    failure_cooldown: 0
    available_from: "2026-11-02"
    due_date: 2026-11-05
    max_skips: 3
    max_passes: 3
    body:
      mark: 8
      sentences:
        - words: [The, cat]
          noun: [cat]
rule_sets:
  open:
    - condition: always
      when_true: { action: allow }
""",
        tmp_path,
    )
    task = policy.task("worksheet-1")
    assert task.groups == ("younger", "default")
    assert task.pass_cooldown == 0
    assert task.failure_cooldown == 0
    assert task.available_from == date(2026, 11, 2)
    assert task.due_date == date(2026, 11, 5)
    assert task.max_skips == 3
    assert task.max_passes == 3
    assert task.document() == {"mark": 8, "sentences": [{"noun": ["cat"], "words": ["The", "cat"]}]}


@pytest.mark.parametrize(
    ("task_body", "message"),
    [
        (
            "type: worksheet\n    group: younger\n    pass_cooldown: 21\n    max_skips: -1\n",
            "zero or more",
        ),
        (
            "type: worksheet\n    group: younger\n    pass_cooldown: 21\n    max_passes: -1\n",
            "zero or more",
        ),
        (
            'type: worksheet\n    group: younger\n    pass_cooldown: 21\n    available_from: "tomorrow"\n',
            "date",
        ),
        (
            "type: worksheet\n    group: younger\n    pass_cooldown: 21\n    due_date: 2026-11-05 15:00\n",
            "date",
        ),
        (
            "type: worksheet\n    group: older\n    pass_cooldown: 21\n",
            "unknown client group",
        ),
        (
            "type: worksheet\n    group: younger\n    pass_cooldown: 21d\n",
            "whole number",
        ),
        (
            "type: worksheet\n    group: younger\n    pass_cooldown: 21\n    body: [1, 2]\n",
            "mapping",
        ),
        (
            "type: worksheet\n    group: younger\n    pass_cooldown: 21\n    note: extra\n",
            "unknown setting",
        ),
    ],
)
def test_a_task_the_loader_cannot_read_is_a_load_error(tmp_path, task_body, message):
    text = (
        "entry: open\n"
        "client_groups:\n"
        "  younger:\n"
        '    addresses: ["192.0.2.40"]\n'
        "tasks:\n"
        "  quiz:\n"
        f"    {task_body}"
        "rule_sets:\n"
        "  open:\n"
        "    - condition: always\n"
        "      when_true: { action: allow }\n"
    )
    with pytest.raises(ConfigError, match=message):
        _policy(text, tmp_path)


def test_a_task_needs_a_type_a_pass_cooldown_and_a_client_group(tmp_path):
    base = (
        "entry: open\n"
        "tasks:\n"
        "  quiz:\n"
        "    type: worksheet\n"
        "    group: default\n"
        "rule_sets:\n"
        "  open:\n"
        "    - condition: always\n"
        "      when_true: { action: allow }\n"
    )
    with pytest.raises(ConfigError, match="pass_cooldown"):
        _policy(base, tmp_path)
    with pytest.raises(ConfigError, match="type is required"):
        _policy(base.replace("    type: worksheet\n", ""), tmp_path)
    with pytest.raises(ConfigError, match="group or groups"):
        _policy(base.replace("    group: default\n", "    pass_cooldown: 1\n"), tmp_path)
