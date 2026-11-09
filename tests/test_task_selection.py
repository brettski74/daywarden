"""S003.2 and S018: the task sets, the picker and the selector, practice, the score, and coming back."""

import asyncio
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy.accounts import Accounts  # noqa: E402
from policy.engine import decide  # noqa: E402
from policy.hierarchy import load  # noqa: E402
from policy.review import attempt_report, attempts_report, record_parent_check  # noqa: E402
from policy.selection import read_turn  # noqa: E402
from policy.store import PolicyStore  # noqa: E402
from policy.task_page import MUST_FINISH, NOTHING, respond_task  # noqa: E402
from policy.tasks import AttemptStore, skip_days  # noqa: E402
from policy.usage import UsageStore  # noqa: E402

ZONE = ZoneInfo("America/Toronto")
YOUNGER = "192.0.2.40"
OLDER = "192.0.2.50"
SITE = "https://tasks.example"
PICKER = SITE + "/tasks/next"
CHOOSER = SITE + "/tasks/choose"
YOUTUBE = "https://www.youtube.com/watch?v=abc"
PASSWORD = "s3cret-pass"
SUMS = {
    "operation": "addition",
    "max_timeout": "10s",
    "min_timeout": "4s",
    "correct_answers_required": 3,
    "first": [{"value": 6, "weight": 1}],
    "operands": [{"value": 7, "weight": 1}],
}


def _at(month: int, day: int, hour: int = 16, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=ZONE)


def _policy(tasks: str, directory: Path, rules: str | None = None):
    path = directory / "policy.yaml"
    path.write_text(_house(tasks, rules or ALLOW), encoding="utf-8")
    loaded = load(path)
    assert loaded is not None
    return loaded


def _house(tasks: str, rules: str) -> str:
    return f"""\
entry: gate
timezone: America/Toronto
hostname: tasks.example
port: 443
client_groups:
  younger:
    addresses: ["{YOUNGER}"]
  older:
    addresses: ["{OLDER}"]
site_groups:
  entertainment:
    priority: 30
    patterns: ["*.youtube.com"]
tasks:
{tasks}
rule_sets:
{rules}
"""


ALLOW = """\
  gate:
    - condition: always
      when_true: { action: allow }
"""

REVISION = """\
  gate:
    - condition: always
      when_true: { action: redirect, location: revision_task }
"""


def _tasks_then_allow(required: int) -> str:
    return f"""\
  gate:
    - condition: tasks_required
      required: {required}
      when_true: {{ action: allow }}
      when_false: {{ action: redirect, location: revision_task }}
"""


def _sheet(name: str, extra: str = "", *, cooldown: int = 0, group: str = "younger") -> str:
    lines = f"  {name}:\n    type: worksheet\n    group: {group}\n    pass_cooldown: {cooldown}\n"
    return lines + "".join(f"    {line}\n" for line in extra.splitlines() if line.strip())


def _sums(name: str = "sums", extra: str = "", *, cooldown: int = 0) -> str:
    lines = f"  {name}:\n    type: arithmetic\n    group: younger\n    pass_cooldown: {cooldown}\n    body: {json.dumps(SUMS)}\n"
    return lines + "".join(f"    {line}\n" for line in extra.splitlines() if line.strip())


def _open(now, path, policy, store, *, method="GET", ip=YOUNGER, query=None, body=b""):
    return respond_task(policy, store, method=method, path=path, client_ip=ip, now=now, query=query, body=body)


def _location(page) -> str | None:
    for name, value in page.headers:
        if name == "location":
            return value
    return None


def _picked(now, policy, store, ip=YOUNGER) -> str | None:
    page = _open(now, "/tasks/next", policy, store, ip=ip)
    return _location(page) if page.status == 302 else None


def _listed(page) -> list[str]:
    """Return the task names the selector lists, in order."""
    return [line.split('">', 1)[1].split("<", 1)[0] for line in page.body.splitlines() if 'class="big" href=' in line]


def _finish(store, name, outcome, now, ip_group="younger"):
    attempt = store.in_progress(ip_group, name)
    assert attempt is not None
    return store.finish(attempt.id, outcome, now)


def _pass_by_page(now, name, policy, store):
    """Open a worksheet's page and pass the attempt it opened."""
    page = _open(now, f"/tasks/{name}", policy, store)
    assert page.status == 200, page.body
    return _finish(store, name, "pass", now)


def _quiz(now, name, policy, store, action, payload=None):
    page = _open(now, f"/tasks/{name}", policy, store, method="POST", query={"do": action}, body=json.dumps(payload or {}).encode())
    return page.status, json.loads(page.body)


def _answer_one(now, name, policy, store) -> dict:
    _status, question = _quiz(now, name, policy, store, "question")
    _status, judged = _quiz(now, name, policy, store, "answer", {"id": question["id"], "answer": "13", "expired": False})
    return judged


def _pass_quiz(now, name, policy, store) -> dict:
    page = _open(now, f"/tasks/{name}", policy, store)
    assert page.status == 200
    _quiz(now, name, policy, store, "visit")
    for _ in range(SUMS["correct_answers_required"]):
        judged = _answer_one(now, name, policy, store)
    assert judged["finished"] is True
    return judged


def _score(store, policy, now) -> int:
    return UsageStore(connection=store.connection).successes("younger", now.date(), policy.tasks)


def _youtube(store, policy, now) -> dict:
    return decide(policy, client_ip=YOUNGER, url=YOUTUBE, at=now, ledger=UsageStore(connection=store.connection)).decision


# The picker


def test_the_picker_prefers_a_task_never_passed_then_the_oldest_pass(tmp_path):
    policy = _policy(_sheet("zeta") + _sheet("alpha") + _sheet("beta"), tmp_path)
    with AttemptStore(":memory:") as store:
        store.record("younger", "alpha", "pass", _at(10, 20))
        store.record("younger", "beta", "pass", _at(10, 24))
        assert _picked(_at(10, 31), policy, store) == SITE + "/tasks/zeta"
        store.record("younger", "zeta", "pass", _at(10, 30))
        assert _picked(_at(10, 31), policy, store) == SITE + "/tasks/alpha"


def test_equal_candidates_rotate_in_name_order_and_the_selector_does_not_move_the_turn(tmp_path):
    policy = _policy(_sheet("beta") + _sheet("alpha"), tmp_path)
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        first = _picked(now, policy, store)
        for _ in range(3):
            assert _listed(_open(now, "/tasks/choose", policy, store)) == ["beta", "alpha"]
        assert read_turn(store, "younger") == 1
        picks = [first, _picked(now, policy, store), _picked(now, policy, store)]
    assert picks == [SITE + "/tasks/alpha", SITE + "/tasks/beta", SITE + "/tasks/alpha"]


def test_a_redirect_to_revision_goes_through_the_picker_to_a_required_task(tmp_path):
    policy = _policy(_sheet("optional") + _sheet("due", "due_date: 2026-10-31"), tmp_path, REVISION)
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        assert decide(policy, client_ip=YOUNGER, url=YOUTUBE, at=now).decision["location"] == PICKER
        for _ in range(3):
            assert _picked(now, policy, store) == SITE + "/tasks/due"
        assert _listed(_open(now, "/tasks/choose", policy, store)) == []
        assert _location(_open(now, "/tasks/choose", policy, store)) == SITE + "/tasks/due"


def test_a_task_with_no_pass_cooldown_is_not_offered_again_the_day_it_was_passed(tmp_path):
    policy = _policy(_sheet("words"), tmp_path)
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        _pass_by_page(now, "words", policy, store)
        assert _picked(now, policy, store) is None
        assert NOTHING in _open(now, "/tasks/choose", policy, store).body
        assert _picked(_at(11, 1), policy, store) == SITE + "/tasks/words"


def test_a_due_task_never_passed_is_required_and_one_passed_before_its_due_date_is_not(tmp_path):
    policy = _policy(
        _sheet("due", "due_date: 2026-10-31") + _sheet("early", "due_date: 2026-10-31") + _sheet("free"),
        tmp_path,
    )
    with AttemptStore(":memory:") as store:
        store.record("younger", "early", "pass", _at(10, 20))
        sets = store.task_sets(policy.tasks, "younger", _at(10, 31).date())
        assert [task.name for task in sets.required] == ["due"]
        assert [task.name for task in sets.available] == ["due"]
        assert {task.name for task in sets.potential} == {"early", "free"}


def test_skip_days_reaching_max_skips_make_a_task_required_until_it_is_passed(tmp_path):
    policy = _policy(_sheet("words", "max_skips: 2") + _sheet("free"), tmp_path)
    with AttemptStore(":memory:") as store:
        store.record("younger", "words", "failure", _at(10, 29))
        store.record("younger", "words", "abandoned", _at(10, 30))
        now = _at(10, 31)
        assert _picked(now, policy, store) == SITE + "/tasks/words"
        _pass_by_page(now, "words", policy, store)
        assert store.task_sets(policy.tasks, "younger", _at(11, 1).date()).required == ()


@pytest.mark.parametrize(
    ("extra", "history"),
    [
        ("failure_cooldown: 2", [("failure", (10, 30))]),
        ("max_passes: 1", [("pass", (9, 1))]),
        ("", [("pass", (10, 31, 9))]),
    ],
    ids=["cooldown", "max-passes", "passed-today"],
)
def test_a_task_that_would_be_required_but_is_held_back_is_neither_required_nor_offered(tmp_path, extra, history):
    policy = _policy(_sheet("held", "due_date: 2026-09-01\nmax_skips: 0\n" + extra) + _sheet("free"), tmp_path)
    with AttemptStore(":memory:") as store:
        for outcome, when in history:
            store.record("younger", "held", outcome, _at(*when))
        sets = store.task_sets(policy.tasks, "younger", _at(10, 31).date())
        assert sets.required == ()
        assert [task.name for task in sets.available] == ["free"]


def test_a_task_not_available_yet_is_never_offered_and_nothing_left_says_so(tmp_path):
    policy = _policy(_sheet("later", "available_from: 2026-11-01\ndue_date: 2026-10-01"), tmp_path, REVISION)
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        picker = _open(now, "/tasks/next", policy, store)
        chooser = _open(now, "/tasks/choose", policy, store)
        assert picker.status == chooser.status == 200
        assert NOTHING in picker.body and NOTHING in chooser.body
        assert _picked(_at(11, 1), policy, store) == SITE + "/tasks/later"


def test_the_picker_never_returns_a_parent_check_and_its_url_opens_nothing(tmp_path):
    credit = "  credit:\n    type: parent_check\n    group: younger\n    pass_cooldown: 0\n"
    policy = _policy(credit, tmp_path)
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        assert _picked(now, policy, store) is None
        page = _open(now, "/tasks/credit", policy, store)
        assert _location(page) == PICKER
        status, _payload = _quiz(now, "credit", policy, store, "answer", {"id": 0})
        assert status == 409
        assert _open(now, "/tasks/credit", policy, store, method="POST").status == 302
        assert store.attempts("younger") == ()


@pytest.mark.parametrize("path", ["/tasks/missing", "/tasks/theirs"])
def test_a_task_that_is_not_his_sends_him_to_the_picker(tmp_path, path):
    policy = _policy(_sheet("mine") + _sheet("theirs", group="older"), tmp_path)
    with AttemptStore(":memory:") as store:
        page = _open(_at(10, 31), path, policy, store)
        assert page.status == 302
        assert _location(page) == PICKER
        assert store.attempts("younger") == ()


# Direct task URLs and the set an attempt starts in


def test_every_configured_task_opens_from_a_bookmark_and_starts_in_the_set_it_is_in(tmp_path):
    tasks = (
        _sheet("due", "due_date: 2026-10-31")
        + _sheet("optional")
        + _sheet("done_today")
        + _sheet("cooling", "failure_cooldown: 3")
        + _sheet("capped", "max_passes: 1")
        + _sheet("later", "available_from: 2026-12-01")
    )
    policy = _policy(tasks, tmp_path)
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        store.record("younger", "done_today", "pass", _at(10, 31, 9))
        store.record("younger", "cooling", "failure", _at(10, 30))
        store.record("younger", "capped", "pass", _at(9, 1))
        sets = {}
        for name in ("due", "optional", "done_today", "cooling", "capped", "later"):
            page = _open(now, f"/tasks/{name}", policy, store)
            assert page.status == 200, name
            assert "Try a different task" in page.body
            sets[name] = store.in_progress("younger", name).task_set
    assert sets == {
        "due": "required",
        "optional": "potential",
        "done_today": "practice",
        "cooling": "practice",
        "capped": "practice",
        "later": "practice",
    }


def test_a_task_named_next_or_choose_is_served_under_work(tmp_path):
    policy = _policy(_sheet("next") + _sheet("choose"), tmp_path)
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        assert _picked(now, policy, store) in {SITE + "/tasks/work/next", SITE + "/tasks/work/choose"}
        assert _open(now, "/tasks/work/choose", policy, store).status == 200
        assert store.in_progress("younger", "choose") is not None
        listed = _open(now, "/tasks/choose", policy, store).body
        assert 'href="https://tasks.example/tasks/work/choose"' in listed
        assert 'href="https://tasks.example/tasks/work/next"' in listed


def test_an_older_child_does_not_resume_the_younger_attempt(tmp_path):
    policy = _policy(_sheet("shared").replace("group: younger", "groups: [younger, older]"), tmp_path)
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        _open(now, "/tasks/shared", policy, store)
        _open(now, "/tasks/shared", policy, store, ip=OLDER)
        assert store.in_progress("younger", "shared").id != store.in_progress("older", "shared").id


# Practice


def test_a_practice_pass_says_well_done_and_counts_for_nothing(tmp_path):
    policy = _policy(_sums("sums", "max_passes: 2\ndue_date: 2026-10-31", cooldown=2), tmp_path, _tasks_then_allow(2))
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        store.record("younger", "sums", "failure", _at(10, 29))
        store.record("younger", "sums", "pass", _at(10, 30))
        assert store.task_sets(policy.tasks, "younger", now.date()).available == ()
        judged = _pass_quiz(now, "sums", policy, store)
        assert judged["next"] is None
        practice = store.attempts("younger", "sums")[-1]
        assert (practice.outcome, practice.task_set) == ("pass", "practice")
        assert _score(store, policy, now) == 0
        tomorrow = _at(11, 1)
        assert [task.name for task in store.task_sets(policy.tasks, "younger", tomorrow.date()).available] == ["sums"]


def test_a_practice_pass_does_not_clear_a_due_date_or_reset_skip_days(tmp_path):
    policy = _policy(_sheet("due", "due_date: 2026-10-31\nfailure_cooldown: 1") + _sheet("skips", "max_skips: 1\nfailure_cooldown: 1"), tmp_path)
    with AttemptStore(":memory:") as store:
        store.record("younger", "due", "failure", _at(10, 31, 9))
        store.record("younger", "skips", "failure", _at(10, 30, 9))
        store.record("younger", "skips", "failure", _at(10, 31, 9))
        now = _at(10, 31)
        for name in ("due", "skips"):
            _pass_by_page(now, name, policy, store)
            assert store.attempts("younger", name)[-1].task_set == "practice"
        required = store.task_sets(policy.tasks, "younger", _at(11, 1).date()).required
        assert [task.name for task in required] == ["due", "skips"]


def test_a_practice_failure_starts_no_cooldown_and_a_practice_give_up_is_no_skip_day(tmp_path):
    policy = _policy(_sheet("words", "failure_cooldown: 1\nmax_skips: 1"), tmp_path)
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        _pass_by_page(now, "words", policy, store)
        _open(now, "/tasks/words", policy, store)
        _finish(store, "words", "failure", now + timedelta(minutes=5))
        _open(now + timedelta(minutes=6), "/tasks/words", policy, store)
        assert _location(_open(now + timedelta(minutes=7), "/tasks/words", policy, store, method="POST")) == CHOOSER
        assert [row.task_set for row in store.attempts("younger", "words")] == ["potential", "practice", "practice"]
        sets = store.task_sets(policy.tasks, "younger", _at(11, 1).date())
        assert [task.name for task in sets.potential] == ["words"]
        assert sets.required == ()


def test_an_attempt_keeps_the_set_it_started_in_through_a_reload(tmp_path):
    policy = _policy(_sheet("words"), tmp_path)
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        _open(now, "/tasks/words", policy, store)
        reloaded = _policy(_sheet("words", "due_date: 2026-10-01"), tmp_path)
        _open(now + timedelta(minutes=1), "/tasks/words", reloaded, store)
        attempt = _finish(store, "words", "pass", now + timedelta(minutes=2))
        assert attempt.task_set == "potential"


# Today's score


UC3 = (
    _sheet("parts_of_speech", "due_date: 2026-10-31\nfailure_cooldown: 1", cooldown=1)
    + _sheet("addition")
    + _sheet("spelling")
)


def test_uc3_easier_tasks_first_wait_until_the_hard_one_has_been_tried(tmp_path):
    policy = _policy(UC3, tmp_path, _tasks_then_allow(2))
    now = _at(10, 31)
    with PolicyStore(":memory:") as saved:
        store = AttemptStore(connection=saved.connection)
        for name in ("spelling", "addition"):
            _pass_by_page(now, name, policy, store)
        assert _score(store, policy, now) == 0
        assert _youtube(store, policy, now)["location"] == PICKER
        _open(now, "/tasks/parts_of_speech", policy, store)
        _finish(store, "parts_of_speech", "failure", now + timedelta(minutes=5))
        assert _score(store, policy, now) == 2
        assert _youtube(store, policy, now) == {"action": "allow"}


def test_uc3_passing_the_hard_task_instead_scores_three(tmp_path):
    policy = _policy(UC3, tmp_path, _tasks_then_allow(2))
    now = _at(10, 31)
    with PolicyStore(":memory:") as saved:
        store = AttemptStore(connection=saved.connection)
        for name in ("spelling", "addition", "parts_of_speech"):
            _pass_by_page(now, name, policy, store)
        assert _score(store, policy, now) == 3
        assert _youtube(store, policy, now) == {"action": "allow"}


def test_uc3_without_a_failure_cooldown_only_parent_checks_make_up_the_count(tmp_path):
    tasks = UC3.replace("    failure_cooldown: 1\n", "")
    credit = "  credit:\n    type: parent_check\n    group: younger\n    pass_cooldown: 0\n"
    policy = _policy(tasks + credit, tmp_path, _tasks_then_allow(2))
    now = _at(10, 31)
    with PolicyStore(":memory:") as saved:
        store = AttemptStore(connection=saved.connection)
        accounts = Accounts(saved.connection)
        accounts.set_password("ada", PASSWORD)
        for name in ("spelling", "addition"):
            _pass_by_page(now, name, policy, store)
        _open(now, "/tasks/parts_of_speech", policy, store)
        _finish(store, "parts_of_speech", "failure", now)
        assert _score(store, policy, now) == 0
        assert _youtube(store, policy, now)["location"] == PICKER
        for expected in (1, 2):
            assert record_parent_check(accounts, store, "younger", now=now, tasks=policy.tasks) is None
            assert _score(store, policy, now) == expected
        assert _youtube(store, policy, now) == {"action": "allow"}
        assert [row.task_set for row in store.attempts("younger", "credit")] == ["parent_check", "parent_check"]


def test_no_task_scores_twice_in_a_day_whatever_its_mix_of_passes(tmp_path):
    policy = _policy(_sheet("words") + _sheet("sums"), tmp_path)
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        store.record("younger", "words", "pass", _at(10, 31, 9), task_set="required")
        store.record("younger", "words", "pass", _at(10, 31, 10), task_set="potential")
        store.record("younger", "words", "pass", _at(10, 31, 11), task_set="practice")
        store.record("younger", "sums", "pass", _at(10, 31, 9), task_set="potential")
        store.record("younger", "sums", "pass", _at(10, 31, 10), task_set="potential")
        assert _score(store, policy, now) == 2


def test_a_reload_that_makes_a_task_due_stops_the_waiting_points_until_it_is_cleared(tmp_path):
    policy = _policy(_sheet("words") + _sheet("sums"), tmp_path, _tasks_then_allow(1))
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        _pass_by_page(now, "words", policy, store)
        assert _score(store, policy, now) == 1
        reloaded = _policy(_sheet("words", "due_date: 2026-10-31") + _sheet("sums", "due_date: 2026-10-31"), tmp_path, _tasks_then_allow(1))
        assert _score(store, reloaded, now) == 0
        assert store.attempts("younger", "words")[-1].task_set == "potential"
        assert _youtube(store, reloaded, now)["location"] == PICKER
        _pass_by_page(now, "sums", reloaded, store)
        assert _score(store, reloaded, now) == 2


def test_attempts_stored_before_task_sets_are_kept_and_count_as_required(tmp_path):
    database = tmp_path / "policy.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(OLD_SCHEMA)
        rows = [
            ("younger", "words", "2026-10-30T16:00:00-04:00", "2026-10-30T16:05:00-04:00", "pass"),
            ("younger", "sums", "2026-10-31T09:00:00-04:00", "2026-10-31T09:05:00-04:00", "pass"),
            ("younger", "sums", "2026-10-31T10:00:00-04:00", "2026-10-31T10:05:00-04:00", "pass"),
            ("younger", "late", "2026-10-31T11:00:00-04:00", None, "in_progress"),
        ]
        connection.executemany(
            "INSERT INTO attempts (client_group, task_name, started_at, finished_at, outcome, detail) VALUES (?, ?, ?, ?, ?, '{}')",
            rows,
        )
    policy = _policy(_sheet("words", cooldown=2) + _sheet("sums") + _sheet("late"), tmp_path)
    now = _at(10, 31)
    with AttemptStore(database) as store:
        stored = store.attempts("younger")
        assert [row.task_set for row in stored] == ["required"] * 4
        assert store.in_progress("younger", "late").id == 4
        assert _score(store, policy, now) == 1
        assert [task.name for task in store.task_sets(policy.tasks, "younger", now.date()).available] == ["late"]
    with AttemptStore(database) as again:
        assert len(again.attempts("younger")) == 4


OLD_SCHEMA = """
CREATE TABLE attempts (
    id INTEGER PRIMARY KEY,
    client_group TEXT NOT NULL,
    task_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT NOT NULL CHECK (outcome IN ('in_progress', 'pass', 'failure', 'abandoned')),
    detail TEXT NOT NULL,
    CHECK ((outcome = 'in_progress' AND finished_at IS NULL) OR (outcome != 'in_progress' AND finished_at IS NOT NULL))
);
CREATE INDEX attempts_by_group ON attempts (client_group, task_name, id);
CREATE UNIQUE INDEX attempts_one_in_progress ON attempts (client_group, task_name) WHERE outcome = 'in_progress';
"""


# Try a different task


def test_giving_up_goes_to_the_selector_which_lists_every_available_task_including_the_one_left(tmp_path):
    policy = _policy(_sheet("alpha") + _sheet("beta") + _sheet("gamma"), tmp_path)
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        _open(now, "/tasks/alpha", policy, store)
        assert _location(_open(now, "/tasks/alpha", policy, store, method="POST")) == CHOOSER
        _open(now, "/tasks/beta", policy, store)
        _open(now, "/tasks/beta", policy, store, method="POST")
        assert [row.outcome for row in store.attempts("younger")] == ["abandoned", "abandoned"]
        chooser = _open(now, "/tasks/choose", policy, store)
        assert chooser.status == 200
        assert _listed(chooser) == ["alpha", "beta", "gamma"]
        assert 'href="https://tasks.example/tasks/beta"' in chooser.body


def test_giving_up_the_only_available_task_comes_straight_back_to_it(tmp_path):
    policy = _policy(_sheet("only"), tmp_path)
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        _open(now, "/tasks/only", policy, store)
        _open(now, "/tasks/only", policy, store, method="POST")
        assert _location(_open(now, "/tasks/choose", policy, store)) == SITE + "/tasks/only"


def test_the_only_required_task_cannot_be_given_up(tmp_path):
    policy = _policy(_sheet("due", "due_date: 2026-10-31") + _sheet("optional"), tmp_path)
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        _open(now, "/tasks/due", policy, store)
        attempt = store.in_progress("younger", "due")
        refused = _open(now, "/tasks/due", policy, store, method="POST")
        assert refused.status == 200
        assert MUST_FINISH in refused.body
        assert store.in_progress("younger", "due").id == attempt.id


def test_one_of_two_required_tasks_can_be_given_up_and_the_selector_lists_the_required_ones(tmp_path):
    policy = _policy(_sheet("first", "due_date: 2026-10-31") + _sheet("second", "due_date: 2026-10-31") + _sheet("optional"), tmp_path)
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        _open(now, "/tasks/first", policy, store)
        assert _location(_open(now, "/tasks/first", policy, store, method="POST")) == CHOOSER
        assert _listed(_open(now, "/tasks/choose", policy, store)) == ["first", "second"]


@pytest.mark.parametrize("name", ["optional", "done"])
def test_a_potential_or_practice_attempt_can_always_be_given_up(tmp_path, name):
    policy = _policy(_sheet("due", "due_date: 2026-10-31") + _sheet("optional") + _sheet("done"), tmp_path)
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        store.record("younger", "done", "pass", _at(10, 31, 9))
        _open(now, f"/tasks/{name}", policy, store)
        assert _location(_open(now, f"/tasks/{name}", policy, store, method="POST")) == CHOOSER
        assert store.attempts("younger", name)[-1].outcome == "abandoned"
        assert _location(_open(now, "/tasks/choose", policy, store)) == SITE + "/tasks/due"


# Coming back to a task he gave up


def test_coming_back_within_the_hour_carries_on_the_attempt_he_gave_up(tmp_path):
    policy = _policy(_sums() + _sheet("other"), tmp_path)
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        _open(now, "/tasks/sums", policy, store)
        _quiz(now, "sums", policy, store, "visit")
        _answer_one(now, "sums", policy, store)
        _quiz(now, "sums", policy, store, "question")
        given_up = now + timedelta(minutes=1)
        _open(given_up, "/tasks/sums", policy, store, method="POST")
        before = store.attempts("younger", "sums")[-1]
        assert before.outcome == "abandoned"
        back = given_up + timedelta(minutes=59)
        page = _open(back, "/tasks/sums", policy, store)
        assert "1 / 3 correct" in page.body
        again = store.in_progress("younger", "sums")
        assert again.id == before.id
        assert again.detail["questions"] == before.detail["questions"]
        assert [item["outcome"] for item in again.detail["questions"]] == ["correct", "timeout"]
        assert len(store.attempts("younger", "sums")) == 1
        assert skip_days("sums", "younger", store.attempts("younger")) == frozenset()
        assert again.task_set == "potential"


@pytest.mark.parametrize("route", ["/tasks/next", "/tasks/choose"])
def test_the_picker_and_selector_lead_back_to_the_same_given_up_attempt(tmp_path, route):
    policy = _policy(_sheet("only"), tmp_path)
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        _open(now, "/tasks/only", policy, store)
        _open(now, "/tasks/only", policy, store, method="POST")
        first = store.attempts("younger", "only")[-1]
        assert _location(_open(now, route, policy, store)) == SITE + "/tasks/only"
        _open(now + timedelta(minutes=5), "/tasks/only", policy, store)
        assert store.in_progress("younger", "only").id == first.id


def test_after_the_hour_or_on_a_later_day_a_new_attempt_starts(tmp_path):
    policy = _policy(_sheet("words"), tmp_path)
    now = _at(10, 31, 20)
    with AttemptStore(":memory:") as store:
        _open(now, "/tasks/words", policy, store)
        _open(now, "/tasks/words", policy, store, method="POST")
        _open(now + timedelta(minutes=61), "/tasks/words", policy, store)
        assert [row.outcome for row in store.attempts("younger", "words")] == ["abandoned", "in_progress"]
        late = _at(10, 31, 23, 50)
        _open(late, "/tasks/words", policy, store, method="POST")
        _open(late + timedelta(minutes=20), "/tasks/words", policy, store)
        assert [row.outcome for row in store.attempts("younger", "words")] == ["abandoned", "abandoned", "in_progress"]


def test_a_given_up_attempt_is_not_reopened_once_a_newer_attempt_has_started(tmp_path):
    policy = _policy(_sheet("words"), tmp_path)
    with AttemptStore(":memory:") as store:
        store.record("younger", "words", "abandoned", _at(10, 31, 16, 0), started_at=_at(10, 31, 15, 55))
        store.record("younger", "words", "failure", _at(10, 31, 16, 10), started_at=_at(10, 31, 16, 5))
        _open(_at(10, 31, 16, 20), "/tasks/words", policy, store)
        assert [row.outcome for row in store.attempts("younger", "words")] == ["abandoned", "failure", "in_progress"]


def test_giving_up_again_abandons_again_and_the_parent_sees_each_give_up_and_return(tmp_path):
    policy = _policy(_sheet("words"), tmp_path)
    now = _at(10, 31)
    with PolicyStore(":memory:") as saved:
        store = AttemptStore(connection=saved.connection)
        for minutes in (0, 10, 20):
            _open(now + timedelta(minutes=minutes), "/tasks/words", policy, store)
            _open(now + timedelta(minutes=minutes + 5), "/tasks/words", policy, store, method="POST")
        [attempt] = store.attempts("younger", "words")
        assert attempt.outcome == "abandoned"
        assert [(event["gave_up"][11:16], event["came_back"][11:16]) for event in attempt.reopened] == [
            ("16:05", "16:10"),
            ("16:15", "16:20"),
        ]
        page = attempt_report(store, str(attempt.id), now=now)
        assert [(event["gave_up"][-5:], event["came_back"][-5:]) for event in page["reopened"]] == [
            ("16:05", "16:10"),
            ("16:15", "16:20"),
        ]


# An attempt belongs to one day


def test_an_attempt_left_open_is_closed_as_unfinished_and_a_fresh_one_starts_in_todays_set(tmp_path):
    policy = _policy(_sheet("words", "max_skips: 1") + _sheet("other"), tmp_path)
    with AttemptStore(":memory:") as store:
        _open(_at(11, 2), "/tasks/words", policy, store)
        assert store.in_progress("younger", "words").task_set == "potential"
        _open(_at(11, 3), "/tasks/words", policy, store)
        old, fresh = store.attempts("younger", "words")
        assert old.outcome == "unfinished"
        assert old.finished_at is None
        assert (fresh.outcome, fresh.task_set) == ("in_progress", "required")


def test_an_attempt_left_open_is_a_skip_day_for_the_day_it_started_even_if_never_opened_again(tmp_path):
    policy = _policy(_sheet("words", "max_skips: 1") + _sheet("other"), tmp_path)
    with AttemptStore(":memory:") as store:
        monday = _at(11, 2)
        _open(monday, "/tasks/words", policy, store)
        assert store.task_sets(policy.tasks, "younger", monday.date()).required == ()
        _open(monday, "/tasks/words", policy, store, method="POST")
        _open(monday + timedelta(minutes=90), "/tasks/words", policy, store)
        tuesday = store.task_sets(policy.tasks, "younger", _at(11, 3).date())
        assert [task.name for task in tuesday.required] == ["words"]
        assert skip_days("words", "younger", store.attempts("younger"), before=_at(11, 3).date()) == {monday.date()}


def test_an_unfinished_practice_attempt_has_no_effect(tmp_path):
    policy = _policy(_sheet("words", "max_skips: 1"), tmp_path)
    with AttemptStore(":memory:") as store:
        monday = _at(11, 2)
        _pass_by_page(monday, "words", policy, store)
        _open(monday + timedelta(minutes=5), "/tasks/words", policy, store)
        assert store.in_progress("younger", "words").task_set == "practice"
        assert store.task_sets(policy.tasks, "younger", _at(11, 3).date()).required == ()


def test_a_quiz_on_screen_when_the_day_ends_carries_on_and_scores_on_the_day_it_passes(tmp_path):
    policy = _policy(_sums(), tmp_path)
    late = _at(10, 31, 23, 58)
    with AttemptStore(":memory:") as store:
        _open(late, "/tasks/sums", policy, store)
        _quiz(late, "sums", policy, store, "visit")
        _answer_one(late, "sums", policy, store)
        after = _at(11, 1, 0, 2)
        _answer_one(after, "sums", policy, store)
        judged = _answer_one(after, "sums", policy, store)
        assert judged["finished"] is True
        [attempt] = store.attempts("younger", "sums")
        assert (attempt.outcome, attempt.task_set) == ("pass", "potential")
        assert _score(store, policy, after) == 1
        assert _score(store, policy, late) == 0


# The parent attempts page


def test_the_attempts_page_shows_each_set_unfinished_attempts_and_where_today_stands(tmp_path):
    policy = _policy(
        _sheet("due", "due_date: 2026-10-31") + _sheet("words") + _sheet("sums") + _sheet("left"),
        tmp_path,
    )
    now = _at(10, 31)
    with PolicyStore(":memory:") as saved:
        store = AttemptStore(connection=saved.connection)
        _open(_at(10, 30), "/tasks/left", policy, store)
        _pass_by_page(now, "words", policy, store)
        _pass_by_page(now + timedelta(minutes=5), "words", policy, store)
        accounts = Accounts(saved.connection)
        accounts.set_password("ada", PASSWORD)
        assert record_parent_check(accounts, store, "younger", now=now, tasks=policy.tasks) is None
        page = attempts_report(store, ("younger", "older"), "younger", now=now, tasks=policy.tasks)
        assert page["summary"] == [
            {"label": "Today's score", "value": "1"},
            {"label": "Required tasks outstanding", "value": "due"},
            {"label": "Potential tasks available", "value": "sums, left"},
            {"label": "Potential passes waiting on required tasks", "value": "words"},
        ]
        shown = {row["set"] for row in page["attempts"]} | {row["outcome"] for row in page["attempts"]}
        for label in ("Potential", "Practice", "Parent check", "Unfinished"):
            assert label in shown
        assert _score(store, policy, now) == 1


# Through the service


def test_the_service_opens_a_bookmarked_task_while_a_required_one_is_outstanding(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text(_house(_sheet("due", "due_date: 2020-01-01") + _sheet("optional"), _tasks_then_allow(1)), encoding="utf-8")
    database = tmp_path / "policy.sqlite3"
    monkeypatch.setenv("POLICY_FILE", str(policy_file))
    monkeypatch.setenv("POLICY_DB", str(database))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    app = create_app()

    def call(method, path, *, body=b"", client=YOUNGER, content_type=None):
        messages = []
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            messages.append(message)

        headers = [(b"x-daywarden-client", client.encode())]
        if content_type:
            headers.append((b"content-type", content_type.encode()))
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
            "client": ("172.17.0.2", 12345),
            "server": ("127.0.0.1", 80),
            "root_path": "",
        }
        asyncio.run(app(scope, receive, send))
        start = next(item for item in messages if item["type"] == "http.response.start")
        payload = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
        found: dict[str, list[str]] = {}
        for key, value in start["headers"]:
            found.setdefault(key.decode(), []).append(value.decode())
        return start["status"], payload.decode(), found

    status, body, _headers = call("GET", "/tasks/optional")
    assert status == 200
    assert "Try a different task" in body
    status, _body, headers = call("GET", "/tasks/next")
    assert headers["location"] == ["https://tasks.example/tasks/due"]
    decision = json.dumps({"client_ip": YOUNGER, "method": "GET", "url": YOUTUBE}).encode()
    status, body, _headers = call("POST", "/v1/decisions", body=decision, content_type="application/json")
    assert json.loads(body)["location"] == PICKER
    task_page = json.dumps({"client_ip": YOUNGER, "method": "GET", "url": SITE + "/tasks/optional"}).encode()
    status, body, _headers = call("POST", "/v1/decisions", body=task_page, content_type="application/json")
    assert json.loads(body)["location"] == PICKER
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT task_name, task_set FROM attempts").fetchall() == [("optional", "potential")]
