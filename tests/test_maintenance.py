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
from policy.tasks import AttemptStore  # noqa: E402

ZONE = ZoneInfo("America/Toronto")
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
  sums:
    type: arithmetic
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
    type: arithmetic
    group: younger
    pass_cooldown: 1
    body:
      operation: addition
      max_timeout: 10s
      min_timeout: 4s
      correct_answers_required: 5
      operands:
        - { from: 1, to: 9, weight: 1 }
  words:
    type: spelling
    groups: [younger, older]
    pass_cooldown: 0
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
        store.record("younger", "sums", "pass", NOW - timedelta(minutes=30))
        store.record("younger", "sums", "failure", NOW - timedelta(hours=2))
        store.record("older", "sums", "pass", NOW - timedelta(minutes=10))
        store.record("younger", "times", "abandoned", NOW - timedelta(days=3))
        store.record("younger", "words", "pass", NOW - timedelta(minutes=5))
        store.record("younger", "parent_check", "pass", NOW - timedelta(minutes=20))
        store.begin("older", "words", NOW - timedelta(hours=3))
    return database, policy_file


def _run(*argv):
    out = io.StringIO()
    status = main(list(argv), now=NOW, out=out)
    return status, out.getvalue()


def _left(database):
    with AttemptStore(database) as store:
        return [(row.client_group, row.task, row.outcome) for row in store.everything()]


def _removed(database, *argv):
    before = _left(database)
    status, output = _run(*argv, "--yes")
    assert status == 0, output
    after = _left(database)
    return [row for row in before if row not in after]


def test_client_and_task_together_match_only_that_groups_attempts_on_that_task(house):
    database, _policy = house
    assert _removed(database, "remove-attempts", "--client", "younger", "--task", "sums") == [
        ("younger", "sums", "pass"),
        ("younger", "sums", "failure"),
    ]


def test_two_task_values_match_either_task(house):
    database, _policy = house
    removed = _removed(database, "remove-attempts", "--task", "times", "--task", "words")
    assert sorted(removed) == sorted(
        [("younger", "times", "abandoned"), ("younger", "words", "pass"), ("older", "words", "in_progress")]
    )


def test_type_matches_every_task_of_that_type_in_the_policy_file(house):
    database, _policy = house
    removed = _removed(database, "remove-attempts", "--type", "arithmetic")
    assert {task for _client, task, _outcome in removed} == {"sums", "times"}
    assert len(removed) == 4


def test_a_type_no_task_has_matches_nothing_and_says_so(house):
    database, _policy = house
    before = _left(database)
    status, output = _run("remove-attempts", "--type", "division", "--yes")
    assert status == 0
    assert "no task in the policy file has type division" in output
    assert "no attempts match" in output
    assert _left(database) == before


def test_parent_check_type_matches_rows_stored_under_that_name(house):
    database, _policy = house
    assert _removed(database, "remove-attempts", "--type", "parent_check") == [("younger", "parent_check", "pass")]


def test_newer_than_and_older_than_split_on_the_finish_time(house):
    database, _policy = house
    status, output = _run("remove-attempts", "--task", "sums", "--client", "younger", "--newer-than", "1h")
    assert status == 0
    assert "pass" in output and "failure" not in output
    assert _removed(database, "remove-attempts", "--task", "sums", "--client", "younger", "--older-than", "1h") == [
        ("younger", "sums", "failure")
    ]


def test_an_attempt_in_progress_is_aged_from_its_start(house):
    database, _policy = house
    assert _removed(database, "remove-attempts", "--client", "older", "--task", "words", "--newer-than", "2h") == []
    assert _removed(database, "remove-attempts", "--client", "older", "--task", "words", "--older-than", "2h") == [
        ("older", "words", "in_progress")
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
    assert "removed 7 attempts" in output
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
    task = policy.task("sums")
    with AttemptStore(database) as store:
        assert not store.is_eligible(task, "younger", NOW.date())
        assert store.passes_on("younger", NOW.date()) == 3
    _removed(database, "remove-attempts", "--client", "younger", "--task", "sums", "--newer-than", "1h")
    with AttemptStore(database) as store:
        assert store.is_eligible(task, "younger", NOW.date())
        assert store.passes_on("younger", NOW.date()) == 2


def test_type_without_a_policy_file_stops_and_removes_nothing(house, monkeypatch, tmp_path):
    database, _policy = house
    monkeypatch.setenv("POLICY_FILE", str(tmp_path / "missing.yaml"))
    before = _left(database)
    with pytest.raises(SystemExit) as stopped:
        _run("remove-attempts", "--type", "arithmetic", "--yes")
    assert "--type needs the policy file" in str(stopped.value.code)
    assert _left(database) == before
