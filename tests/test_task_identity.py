"""S012: a task is its type and its name, in the policy file, its address, and its history."""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from asgi import call  # noqa: E402
from conftest import merge_task_types  # noqa: E402
from policy.hierarchy import ConfigError, load  # noqa: E402
from policy.task_page import respond_task  # noqa: E402
from policy.tasks import PASS, AttemptStore, TaskKey  # noqa: E402

ZONE = ZoneInfo("America/Toronto")
YOUNGER = "192.0.2.40"
SITE = "https://tasks.example"
PICKER = SITE + "/tasks/next"
CHOOSER = SITE + "/tasks/choose"
NOW = datetime(2026, 11, 4, 16, 0, tzinfo=ZONE)
SUMS = {
    "operation": "addition",
    "max_timeout": "10s",
    "min_timeout": "4s",
    "correct_answers_required": 3,
    "operands": [{"value": 7, "weight": 1}],
}
ARITHMETIC_QUIZ = TaskKey("arithmetic", "quiz-1")
COUNTING_QUIZ = TaskKey("skip_counting", "quiz-1")


def _task(kind: str, name: str, extra: str = "", *, body: dict | None = None, group: str = "younger") -> str:
    lines = f"  {kind}:\n    {name}:\n      group: {group}\n"
    if body is not None:
        lines += f"      body: {json.dumps(body)}\n"
    return lines + "".join(f"      {line}\n" for line in extra.splitlines() if line.strip())


def _house(tasks: str) -> str:
    return f"""\
entry: gate
timezone: America/Toronto
hostname: tasks.example
port: 443
client_groups:
  younger:
    addresses: ["{YOUNGER}"]
tasks:
{merge_task_types(tasks)}rule_sets:
  gate:
    - condition: always
      when_true: {{ action: allow }}
"""


def _policy(tasks: str, directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "policy.yaml"
    path.write_text(_house(tasks), encoding="utf-8")
    loaded = load(path)
    assert loaded is not None
    return loaded


def _open(now, path, policy, store, *, method="GET"):
    return respond_task(policy, store, method=method, path=path, client_ip=YOUNGER, now=now)


def _location(page) -> str | None:
    return next((value for name, value in page.headers if name == "location"), None)


def _links(page) -> list[tuple[str, str]]:
    found = []
    for line in page.body.splitlines():
        if 'class="big' in line and "href=" in line:
            href = line.split('href="', 1)[1].split('"', 1)[0]
            found.append((line.split('">', 1)[1].split("<", 1)[0], href))
    return found


# The policy file


def test_two_tasks_may_share_a_name_when_their_types_differ(tmp_path):
    policy = _policy(_task("arithmetic", "week-1", body=SUMS) + _task("spelling", "week-1"), tmp_path)
    assert sorted(task.key for task in policy.tasks) == [TaskKey("arithmetic", "week-1"), TaskKey("spelling", "week-1")]
    assert policy.task(TaskKey("spelling", "week-1")).document() == {}
    assert policy.task(TaskKey("skip_counting", "week-1")) is None


def test_the_same_type_and_name_twice_in_one_file_names_both_places(tmp_path):
    text = _house(_task("spelling", "week-1")).replace(
        "tasks:\n  spelling:\n", "tasks:\n  spelling:\n    week-1:\n      group: younger\n"
    )
    path = tmp_path / "policy.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError) as refused:
        load(path)
    [problem] = refused.value.problems
    assert problem == f"{path}:12:5: task 'spelling/week-1' is already defined at {path}:10:5"


def test_the_same_type_and_name_in_an_included_file_names_both_places_and_other_names_join_the_type(tmp_path):
    (tmp_path / "tasks.d").mkdir()
    extra = tmp_path / "tasks.d" / "more.yaml"
    extra.write_text("tasks:\n  spelling:\n    week-2:\n      group: younger\n", encoding="utf-8")
    root = tmp_path / "policy.yaml"
    root.write_text(_house(_task("spelling", "week-1")) + "include:\n  - tasks.d\n", encoding="utf-8")
    assert {task.key for task in load(root).tasks} == {TaskKey("spelling", "week-1"), TaskKey("spelling", "week-2")}
    extra.write_text("tasks:\n  spelling:\n    week-1:\n      group: younger\n", encoding="utf-8")
    with pytest.raises(ConfigError) as refused:
        load(root)
    [problem] = refused.value.problems
    assert problem.startswith(f"{extra}:4:7: task 'spelling/week-1' is already defined at {root}:")


def test_every_load_error_about_a_task_names_its_type_and_name(tmp_path):
    bad = dict(SUMS, operands=[{"value": 7, "weight": 1}, {"value": "x", "weight": 1}])
    text = _house(_task("arithmetic", "sums", "pass_cooldown: soon\ncolour: red", body=bad) + _task("spelling", "words", group="older"))
    path = tmp_path / "policy.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError) as refused:
        load(path)
    problems = refused.value.problems
    assert len(problems) == 4
    assert all("task 'arithmetic/sums': " in problem for problem in problems[:3])
    assert "task 'arithmetic/sums': body.operands entry 2: " in problems[1]
    assert "task 'spelling/words': unknown client group 'older'" in problems[3]


# Addresses


def test_a_task_opens_at_its_type_and_name_and_other_addresses_go_to_the_picker(tmp_path):
    policy = _policy(_task("arithmetic", "sums", body=SUMS), tmp_path)
    with AttemptStore(":memory:") as store:
        assert _open(NOW, "/tasks/arithmetic/sums", policy, store).status == 200
        for path in ("/tasks/sums", "/tasks/work/sums", "/tasks/spelling/sums", "/tasks/arithmetic/nothing-here"):
            page = _open(NOW, path, policy, store)
            assert (page.status, _location(page)) == (302, PICKER), path
        assert _location(_open(NOW, "/tasks/next", policy, store)) == SITE + "/tasks/arithmetic/sums"
        assert [row.key for row in store.attempts("younger")] == [TaskKey("arithmetic", "sums")]


def test_the_service_routes_the_two_part_address_and_sends_any_other_to_the_picker(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text(_house(_task("arithmetic", "sums", body=SUMS, group="default")), encoding="utf-8")
    monkeypatch.setenv("POLICY_FILE", str(policy_file))
    monkeypatch.setenv("POLICY_DB", str(tmp_path / "policy.sqlite3"))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    app = create_app()
    status, body, _headers = call(app, "GET", "/tasks/arithmetic/sums")
    assert status == 200 and "Try a different task" in body
    for path in ("/tasks/sums", "/tasks/work/sums", "/tasks/spelling/sums"):
        status, _body, headers = call(app, "GET", path)
        assert (status, headers["location"]) == (302, [PICKER]), path
    status, _body, headers = call(app, "GET", "/tasks/next")
    assert headers["location"] == [SITE + "/tasks/arithmetic/sums"]


def test_tasks_that_share_a_name_tie_in_order_of_name_then_type_and_the_selector_tells_them_apart(tmp_path):
    policy = _policy(_task("spelling", "week-1") + _task("arithmetic", "week-1", body=SUMS) + _task("spelling", "alpha"), tmp_path)
    with AttemptStore(":memory:") as store:
        assert _links(_open(NOW, "/tasks/choose", policy, store)) == [
            ("alpha", SITE + "/tasks/spelling/alpha"),
            ("week-1 (arithmetic)", SITE + "/tasks/arithmetic/week-1"),
            ("week-1 (spelling)", SITE + "/tasks/spelling/week-1"),
        ]


def test_giving_up_one_task_leaves_the_task_of_the_same_name_and_another_type_on_offer(tmp_path):
    policy = _policy(_task("arithmetic", "week-1", body=SUMS) + _task("spelling", "week-1"), tmp_path)
    with AttemptStore(":memory:") as store:
        _open(NOW, "/tasks/arithmetic/week-1", policy, store)
        assert _location(_open(NOW, "/tasks/arithmetic/week-1", policy, store, method="POST")) == CHOOSER
        assert store.attempts("younger", TaskKey("arithmetic", "week-1"))[-1].outcome == "abandoned"
        listed = [href for _label, href in _links(_open(NOW, "/tasks/choose", policy, store))]
        assert SITE + "/tasks/spelling/week-1" in listed
        assert store.attempts("younger", TaskKey("spelling", "week-1")) == ()


# History


def test_a_new_type_under_an_old_name_has_none_of_the_old_tasks_history(tmp_path):
    old = _policy(_task("arithmetic", "quiz-1", "pass_cooldown: 21\nmax_passes: 1\nmax_skips: 1", body=SUMS), tmp_path / "old")
    with AttemptStore(":memory:") as store:
        store.record("younger", ARITHMETIC_QUIZ, "abandoned", NOW - timedelta(days=2))
        store.record("younger", ARITHMETIC_QUIZ, PASS, NOW - timedelta(hours=1))
        assert not store.task_sets(old.tasks, "younger", NOW.date()).available
        new = _policy(_task("skip_counting", "quiz-1", "pass_cooldown: 21\nmax_passes: 1\nmax_skips: 1", body={}), tmp_path / "new")
        sets = store.task_sets(new.tasks, "younger", NOW.date())
        assert ([task.key for task in sets.potential], sets.required) == ([COUNTING_QUIZ], ())
        assert _location(_open(NOW, "/tasks/next", new, store)) == SITE + "/tasks/skip_counting/quiz-1"


def test_an_attempt_in_progress_is_kept_for_its_own_type_and_comes_back_with_it(tmp_path):
    arithmetic = _policy(_task("arithmetic", "quiz-1", body=SUMS), tmp_path / "a")
    counting = _policy(_task("skip_counting", "quiz-1", body={}), tmp_path / "b")
    with AttemptStore(":memory:") as store:
        _open(NOW, "/tasks/arithmetic/quiz-1", arithmetic, store)
        first = store.in_progress("younger", ARITHMETIC_QUIZ)
        assert _open(NOW + timedelta(minutes=5), "/tasks/skip_counting/quiz-1", counting, store).status == 200
        counted = store.in_progress("younger", COUNTING_QUIZ)
        assert counted.id != first.id and counted.task_type == "skip_counting"
        _open(NOW + timedelta(minutes=10), "/tasks/arithmetic/quiz-1", arithmetic, store)
        assert store.in_progress("younger", ARITHMETIC_QUIZ).id == first.id
        assert len(store.attempts("younger")) == 2


def test_editing_a_body_under_the_same_type_and_name_keeps_the_history(tmp_path):
    before = _policy(_task("arithmetic", "sums", "pass_cooldown: 3", body=SUMS), tmp_path / "a")
    after = _policy(_task("arithmetic", "sums", "pass_cooldown: 3", body=dict(SUMS, correct_answers_required=5)), tmp_path / "b")
    with AttemptStore(":memory:") as store:
        store.record("younger", TaskKey("arithmetic", "sums"), PASS, NOW - timedelta(days=1))
        assert not store.is_eligible(after.task(TaskKey("arithmetic", "sums")), "younger", NOW.date())
        _open(NOW, "/tasks/arithmetic/sums", before, store)
        opened = store.in_progress("younger", TaskKey("arithmetic", "sums"))
        _open(NOW + timedelta(minutes=1), "/tasks/arithmetic/sums", after, store)
        assert store.in_progress("younger", TaskKey("arithmetic", "sums")).id == opened.id


def test_todays_score_counts_a_pass_of_a_task_since_removed_from_the_policy(tmp_path):
    policy = _policy(_task("spelling", "words"), tmp_path)
    with AttemptStore(":memory:") as store:
        store.record("younger", TaskKey("arithmetic", "gone"), PASS, NOW - timedelta(hours=2))
        assert store.score(policy.tasks, "younger", NOW.date()).points == 1
