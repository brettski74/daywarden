"""S010.1: remove stored attempts from the command line."""

import io
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy.hierarchy import load  # noqa: E402
from policy.maintenance import main  # noqa: E402
from policy.tasks import AttemptStore, TaskKey  # noqa: E402

ZONE = ZoneInfo("America/Toronto")
SUMS = TaskKey("arithmetic", "sums")
WORDS = TaskKey("spelling", "words")
NOW = datetime(2026, 11, 2, 16, 0, tzinfo=ZONE)

POLICY = """\
entry: gate
timezone: America/Toronto
client_groups:
  younger:
    addresses: ["192.0.2.40"]
  older:
    addresses: ["192.0.2.50"]
tasks:
  arithmetic:
    sums:
      groups: [younger, older]
      pass_cooldown: 1
      body:
        operation: addition
        max_timeout: 10s
        min_timeout: 4s
        correct_answers_required: 5
        operands:
          - { from: 1, to: 9, weight: 1 }
    times:
      group: younger
      pass_cooldown: 1
      body:
        operation: addition
        max_timeout: 10s
        min_timeout: 4s
        correct_answers_required: 5
        operands:
          - { from: 1, to: 9, weight: 1 }
  spelling:
    words:
      groups: [younger, older]
      pass_cooldown: 0
    week-1:
      group: younger
rule_sets:
  gate:
    - condition: always
      when_true: { action: allow }
"""


@pytest.fixture
def house(tmp_path, monkeypatch):
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text(POLICY, encoding="utf-8")
    database = tmp_path / "policy.sqlite3"
    monkeypatch.setenv("POLICY_FILE", str(policy_file))
    monkeypatch.setenv("POLICY_DB", str(database))
    with AttemptStore(database) as store:
        store.record("younger", SUMS, "pass", NOW - timedelta(minutes=30))
        store.record("younger", SUMS, "failure", NOW - timedelta(hours=2))
        store.record("older", SUMS, "pass", NOW - timedelta(minutes=10))
        store.record("younger", TaskKey("arithmetic", "times"), "abandoned", NOW - timedelta(days=3))
        store.record("younger", WORDS, "pass", NOW - timedelta(minutes=5))
        store.record("younger", TaskKey("parent_check", "parent_check"), "pass", NOW - timedelta(minutes=20))
        store.begin("older", WORDS, NOW - timedelta(hours=3))
        # week-1 was an arithmetic task before it became a spelling task.
        store.record("younger", TaskKey("arithmetic", "week-1"), "pass", NOW - timedelta(days=2))
        store.record("younger", TaskKey("spelling", "week-1"), "failure", NOW - timedelta(days=1))
    return database, policy_file


def _run(*argv):
    out = io.StringIO()
    status = main(list(argv), now=NOW, out=out)
    return status, out.getvalue()


def _left(database):
    with AttemptStore(database) as store:
        return [(row.client_group, row.task_type, row.task, row.outcome) for row in store.everything()]


def _removed(database, *argv):
    before = _left(database)
    status, output = _run(*argv, "--yes")
    assert status == 0, output
    after = _left(database)
    return [row for row in before if row not in after]


def test_client_and_task_together_match_only_that_groups_attempts_on_that_task(house):
    database, _policy = house
    assert _removed(database, "remove-attempts", "--client", "younger", "--task", "sums") == [
        ("younger", "arithmetic", "sums", "pass"),
        ("younger", "arithmetic", "sums", "failure"),
    ]


def test_two_task_values_match_either_task(house):
    database, _policy = house
    removed = _removed(database, "remove-attempts", "--task", "times", "--task", "words")
    assert sorted(removed) == sorted(
        [
            ("younger", "arithmetic", "times", "abandoned"),
            ("younger", "spelling", "words", "pass"),
            ("older", "spelling", "words", "in_progress"),
        ]
    )


def test_type_matches_the_type_stored_with_each_attempt_whatever_the_policy_says_now(house):
    database, _policy = house
    status, output = _run("remove-attempts", "--type", "arithmetic")
    assert status == 0
    assert "type" in output.splitlines()[0]
    removed = _removed(database, "remove-attempts", "--type", "arithmetic")
    assert {(kind, task) for _client, kind, task, _outcome in removed} == {
        ("arithmetic", "sums"),
        ("arithmetic", "times"),
        ("arithmetic", "week-1"),
    }
    assert len(removed) == 5


def test_a_task_name_matches_every_type_and_with_a_type_matches_one_task(house):
    database, _policy = house
    status, output = _run("remove-attempts", "--task", "week-1")
    assert "2 attempts would be removed" in output
    assert _removed(database, "remove-attempts", "--task", "week-1", "--type", "spelling") == [
        ("younger", "spelling", "week-1", "failure")
    ]
    assert _removed(database, "remove-attempts", "--task", "week-1") == [("younger", "arithmetic", "week-1", "pass")]


def test_a_type_no_attempt_has_matches_nothing(house):
    database, _policy = house
    before = _left(database)
    status, output = _run("remove-attempts", "--type", "division", "--yes")
    assert status == 0
    assert "no attempts match" in output
    assert _left(database) == before


def test_parent_check_type_matches_rows_stored_with_that_type(house):
    database, _policy = house
    assert _removed(database, "remove-attempts", "--type", "parent_check") == [
        ("younger", "parent_check", "parent_check", "pass")
    ]


def test_newer_than_and_older_than_split_on_the_finish_time(house):
    database, _policy = house
    status, output = _run("remove-attempts", "--task", "sums", "--client", "younger", "--newer-than", "1h")
    assert status == 0
    assert "pass" in output and "failure" not in output
    assert _removed(database, "remove-attempts", "--task", "sums", "--client", "younger", "--older-than", "1h") == [
        ("younger", "arithmetic", "sums", "failure")
    ]


def test_an_attempt_in_progress_is_aged_from_its_start(house):
    database, _policy = house
    assert _removed(database, "remove-attempts", "--client", "older", "--task", "words", "--newer-than", "2h") == []
    assert _removed(database, "remove-attempts", "--client", "older", "--task", "words", "--older-than", "2h") == [
        ("older", "spelling", "words", "in_progress")
    ]


def test_without_yes_nothing_is_removed_and_the_count_is_shown(house):
    database, _policy = house
    before = _left(database)
    status, output = _run("remove-attempts", "--task", "sums")
    assert status == 0
    assert "3 attempts would be removed. Run again with --yes to remove them." in output
    assert "younger" in output and "older" in output
    assert _left(database) == before


def test_no_filter_is_refused_unless_all_is_given(house, capsys):
    database, _policy = house
    before = _left(database)
    with pytest.raises(SystemExit) as refused:
        _run("remove-attempts", "--yes")
    assert refused.value.code == 2
    assert "needs a filter, or --all" in capsys.readouterr().err
    assert _left(database) == before
    status, output = _run("remove-attempts", "--all", "--yes")
    assert status == 0
    assert "removed 9 attempts" in output
    assert _left(database) == []


@pytest.mark.parametrize("age", ["10", "1w", "-1h", "0m", "1.5h"])
def test_an_age_must_be_a_whole_number_of_minutes_hours_or_days(house, age, capsys):
    with pytest.raises(SystemExit) as refused:
        _run("remove-attempts", "--older-than", age)
    assert refused.value.code == 2
    assert "is not an age like 30m, 2h, or 7d" in capsys.readouterr().err


def test_removing_a_pass_makes_the_task_eligible_again_and_lowers_todays_count(house):
    database, policy_file = house
    policy = load(policy_file)
    task = policy.task(SUMS)
    with AttemptStore(database) as store:
        assert not store.is_eligible(task, "younger", NOW.date())
        assert store.passes_on("younger", NOW.date()) == 3
    _removed(database, "remove-attempts", "--client", "younger", "--task", "sums", "--newer-than", "1h")
    with AttemptStore(database) as store:
        assert store.is_eligible(task, "younger", NOW.date())
        assert store.passes_on("younger", NOW.date()) == 2


@pytest.mark.parametrize("broken", ["missing", "unloadable"])
def test_type_works_when_the_policy_file_does_not_load(house, monkeypatch, tmp_path, broken):
    database, _policy = house
    policy_file = tmp_path / "other.yaml"
    if broken == "unloadable":
        policy_file.write_text("tasks:\n  sums:\n    type: arithmetic\n", encoding="utf-8")
    monkeypatch.setenv("POLICY_FILE", str(policy_file))
    removed = _removed(database, "remove-attempts", "--type", "arithmetic")
    assert len(removed) == 5
