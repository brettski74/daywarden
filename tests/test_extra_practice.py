"""S024: the selector's After These and Extra Practice, the practice palette, and the favicon."""

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "proxy"))

from conftest import merge_task_types, needs_node, run_page  # noqa: E402
from policy.child_page import FAVICON_FILE, PRACTICE_LINE, WAITING_LINE  # noqa: E402
from policy.hierarchy import load  # noqa: E402
from policy.report import _e  # noqa: E402
from policy.review import QUIZ_PAGE  # noqa: E402
from policy.task_page import NOTHING, respond_task  # noqa: E402
from policy.selection import task_page_path  # noqa: E402
from policy.tasks import AttemptStore, TaskKey  # noqa: E402

ZONE = ZoneInfo("America/Toronto")
YOUNGER = "192.0.2.40"
SITE = "https://tasks.example"
CHOOSER = SITE + "/tasks/choose"
PICKER = SITE + "/tasks/next"
ICON = '<link rel="icon" type="image/png" href="/favicon.png">'
PALETTE = '<html lang="en" data-palette="practice">'
SUMS = {
    "operation": "addition",
    "max_timeout": "10s",
    "min_timeout": "4s",
    "correct_answers_required": 1,
    "first": [{"value": 6, "weight": 1}],
    "operands": [{"value": 7, "weight": 1}],
}
SENTENCES = {"sentences": [{"sentence": "The cat sat.", "parts": {"noun": ["cat"]}}]}


def _at(month: int, day: int, hour: int = 16, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=ZONE)


NOW = _at(10, 31)


def _policy(tasks: str, directory: Path):
    path = directory / "policy.yaml"
    path.write_text(
        f"""\
entry: gate
timezone: America/Toronto
hostname: tasks.example
port: 443
client_groups:
  younger:
    addresses: ["{YOUNGER}"]
  older:
    addresses: ["192.0.2.50"]
tasks:
{merge_task_types(tasks)}
rule_sets:
  gate:
    - condition: always
      when_true: {{ action: allow }}
""",
        encoding="utf-8",
    )
    loaded = load(path)
    assert loaded is not None
    return loaded


def _task(name: str, kind: str = "worksheet", extra: str = "", *, cooldown: int = 0, group: str = "younger", body=None) -> str:
    lines = f"  {kind}:\n    {name}:\n      group: {group}\n      pass_cooldown: {cooldown}\n"
    if body is not None:
        lines += f"      body: {json.dumps(body)}\n"
    return lines + "".join(f"      {line}\n" for line in extra.splitlines() if line.strip())


def _key(policy, name: str) -> TaskKey:
    """Return the key of the one task in the policy with this name."""
    [key] = [task.key for task in policy.tasks if task.name == name]
    return key


def _path(policy, name: str) -> str:
    return task_page_path(_key(policy, name))


QUIZZES = {
    "sums": _task("sums", "arithmetic", body=SUMS),
    "words": _task("words", "parts_of_speech", body=SENTENCES),
    "count": _task("count", "skip_counting", body={}),
    "spell": _task("spell", "spelling"),
}


def _open(now, path, policy, store, *, method="GET", query=None, body=b""):
    return respond_task(policy, store, method=method, path=path, client_ip=YOUNGER, now=now, query=query, body=body)


def _location(page) -> str | None:
    return next((value for name, value in page.headers if name == "location"), None)


def _main(page) -> list[str]:
    found = re.search(r'<ul id="choices" class="choices">(.*?)</ul>', page.body, re.S)
    return [] if found is None else re.findall(r'<a class="big" href="[^"]+">([^<]+)</a>', found.group(1))


def _section(page, key: str) -> list[str] | None:
    """Return the task names in a section in order, or None when the page has no such section."""
    found = re.search(rf'<div id="{key}"[^>]*>(.*?)</ul>', page.body, re.S)
    return None if found is None else re.findall(r'<a class="big \w+" href="[^"]+">([^<]+)</a>', found.group(1))


def _expanded(page, key: str) -> bool:
    toggle = re.search(rf'aria-expanded="(true|false)" aria-controls="{key}"', page.body)
    panel = re.search(rf'<div id="{key}"[^>]*>', page.body)
    assert toggle is not None and panel is not None
    expanded = toggle.group(1) == "true"
    assert (" inert" not in panel.group(0)) is expanded
    return expanded


# The selector's sections


def test_uc2_required_tasks_then_after_these_then_extra_practice_each_collapsed(tmp_path):
    tasks = (
        _task("parts", extra="due_date: 2026-10-31")
        + _task("sums", extra="due_date: 2026-10-31")
        + _task("spelling")
        + _task("skip", cooldown=2)
    )
    policy = _policy(tasks, tmp_path)
    with AttemptStore(":memory:") as store:
        store.record("younger", _key(policy, "skip"), "pass", _at(10, 30))
        page = _open(NOW, "/tasks/choose", policy, store)
        assert page.status == 200
        assert _main(page) == ["parts", "sums"]
        assert _section(page, "after-these") == ["spelling"]
        assert _section(page, "extra-practice") == ["skip"]
        assert not _expanded(page, "after-these") and not _expanded(page, "extra-practice")
        assert _e("These count once the tasks above are done.") in page.body
        assert _e("Practice is just for fun. It doesn't count toward your internet time today.") in page.body
        assert f'<a class="big after" href="{SITE}{_path(policy, "spelling")}">' in page.body
        assert f'<a class="big extra" href="{SITE}{_path(policy, "skip")}">' in page.body
        assert PALETTE not in page.body and ICON in page.body
        assert _location(_open(NOW, "/tasks/next", policy, store)) in {SITE + _path(policy, "parts"), SITE + _path(policy, "sums")}
        for name, expected in (("spelling", "potential"), ("skip", "practice")):
            _open(NOW, _path(policy, name), policy, store)
            assert store.in_progress("younger", _key(policy, name)).task_set == expected


def test_every_task_is_in_exactly_one_section_and_extra_practice_is_alphabetical(tmp_path):
    tasks = (
        _task("due", extra="due_date: 2026-10-31")
        + _task("optional")
        + _task("resting", cooldown=3)
        + _task("done_today")
        + _task("cooling", extra="failure_cooldown: 3")
        + _task("capped", extra="max_passes: 1")
        + _task("later", extra="available_from: 2026-12-01")
        + _task("theirs", group="older")
        + _task("credit", "parent_check")
    )
    policy = _policy(tasks, tmp_path)
    with AttemptStore(":memory:") as store:
        store.record("younger", _key(policy, "resting"), "pass", _at(10, 29))
        store.record("younger", _key(policy, "done_today"), "pass", _at(10, 31, 9))
        store.record("younger", _key(policy, "cooling"), "failure", _at(10, 30))
        store.record("younger", _key(policy, "capped"), "pass", _at(9, 1))
        page = _open(NOW, "/tasks/choose", policy, store)
        main, after, practice = _main(page), _section(page, "after-these"), _section(page, "extra-practice")
        assert (main, after, practice) == (["due"], ["optional"], ["capped", "cooling", "done_today", "resting"])
        for missing in ("later", "theirs", "credit"):
            assert f"/{missing}\"" not in page.body
        _open(NOW, _path(policy, "later"), policy, store)
        assert store.in_progress("younger", _key(policy, "later")).task_set == "practice"


def test_after_these_is_in_the_pickers_order(tmp_path):
    policy = _policy(_task("due", extra="due_date: 2026-10-31") + _task("alpha") + _task("zeta") + _task("beta"), tmp_path)
    with AttemptStore(":memory:") as store:
        store.record("younger", _key(policy, "alpha"), "pass", _at(10, 20))
        assert _section(_open(NOW, "/tasks/choose", policy, store), "after-these") == ["beta", "zeta", "alpha"]


def test_with_nothing_required_the_optional_tasks_are_the_main_list_and_there_is_no_after_these(tmp_path):
    policy = _policy(_task("alpha") + _task("beta") + _task("done"), tmp_path)
    with AttemptStore(":memory:") as store:
        store.record("younger", _key(policy, "done"), "pass", _at(10, 31, 9))
        page = _open(NOW, "/tasks/choose", policy, store)
        assert _main(page) == ["alpha", "beta"]
        assert _section(page, "after-these") is None
        assert "After These" not in page.body
        assert _section(page, "extra-practice") == ["done"]


# When the selector jumps


def test_uc3_one_available_task_with_extra_practice_shows_the_page_instead_of_jumping(tmp_path):
    policy = _policy(_task("sums") + _task("spelling") + _task("skip"), tmp_path)
    with AttemptStore(":memory:") as store:
        for name in ("spelling", "skip"):
            store.record("younger", _key(policy, name), "pass", _at(10, 31, 9))
        page = _open(NOW, "/tasks/choose", policy, store)
        assert page.status == 200
        assert _main(page) == ["sums"]
        assert _section(page, "extra-practice") == ["skip", "spelling"]
        assert not _expanded(page, "extra-practice")


def test_one_available_task_and_nothing_else_still_jumps_straight_to_it(tmp_path):
    policy = _policy(_task("sums") + _task("later", extra="available_from: 2026-12-01"), tmp_path)
    with AttemptStore(":memory:") as store:
        assert _location(_open(NOW, "/tasks/choose", policy, store)) == SITE + _path(policy, "sums")


def test_giving_up_the_only_available_task_shows_it_with_extra_practice_beneath(tmp_path):
    policy = _policy(_task("only") + _task("done"), tmp_path)
    with AttemptStore(":memory:") as store:
        store.record("younger", _key(policy, "done"), "pass", _at(10, 31, 9))
        _open(NOW, _path(policy, "only"), policy, store)
        assert _location(_open(NOW, _path(policy, "only"), policy, store, method="POST")) == CHOOSER
        page = _open(NOW, "/tasks/choose", policy, store)
        assert (_main(page), _section(page, "extra-practice")) == (["only"], ["done"])


# Nothing to revise


@pytest.mark.parametrize("path", ["/tasks/next", "/tasks/choose"])
def test_uc1_nothing_to_revise_shows_extra_practice_expanded(tmp_path, path):
    policy = _policy(_task("spelling") + _task("sums"), tmp_path)
    with AttemptStore(":memory:") as store:
        for name in ("spelling", "sums"):
            store.record("younger", _key(policy, name), "pass", _at(10, 31, 9))
        page = _open(NOW, path, policy, store)
        assert page.status == 200
        assert _e(NOTHING) in page.body
        assert _main(page) == []
        assert _section(page, "extra-practice") == ["spelling", "sums"]
        assert _expanded(page, "extra-practice")
        assert PALETTE not in page.body and ICON in page.body


@pytest.mark.parametrize("path", ["/tasks/next", "/tasks/choose"])
def test_nothing_to_revise_and_nothing_to_practise_says_only_that(tmp_path, path):
    policy = _policy(_task("later", extra="available_from: 2026-12-01"), tmp_path)
    with AttemptStore(":memory:") as store:
        page = _open(NOW, path, policy, store)
        assert page.status == 200
        assert _e(NOTHING) in page.body
        assert "Extra Practice" not in page.body
        assert ICON in page.body


# The quiz pages' palette and line


def _waiting_house() -> str:
    return "".join(QUIZZES.values()) + _task("chores", extra="due_date: 2026-10-31")


@pytest.mark.parametrize("name", list(QUIZZES))
@pytest.mark.parametrize(
    ("situation", "line"),
    [("required", ""), ("counts", ""), ("waiting", WAITING_LINE), ("practice", PRACTICE_LINE)],
)
def test_the_palette_and_line_follow_the_attempt_on_every_quiz_type(tmp_path, name, situation, line):
    tasks = "".join(QUIZZES.values())
    if situation == "required":
        tasks = tasks.replace(f"    {name}:\n", f"    {name}:\n      due_date: 2026-10-31\n", 1)
    if situation == "waiting":
        tasks = _waiting_house()
    policy = _policy(tasks, tmp_path)
    with AttemptStore(":memory:") as store:
        if situation == "practice":
            store.record("younger", _key(policy, name), "pass", _at(10, 31, 9))
        page = _open(NOW, _path(policy, name), policy, store)
        assert page.status == 200, page.body
        assert ICON in page.body
        if line:
            assert PALETTE in page.body
            assert f'<p class="counting" id="counting">{_e(line)}</p>' in page.body
        else:
            assert PALETTE not in page.body
            assert 'class="counting"' not in page.body


def test_a_waiting_attempt_carried_on_after_the_required_tasks_are_cleared_now_counts(tmp_path):
    policy = _policy(_waiting_house(), tmp_path)
    with AttemptStore(":memory:") as store:
        assert _e(WAITING_LINE) in _open(NOW, _path(policy, "sums"), policy, store).body
        assert _location(_open(NOW, _path(policy, "sums"), policy, store, method="POST")) == CHOOSER
        store.record("younger", _key(policy, "chores"), "pass", NOW + timedelta(minutes=5))
        page = _open(NOW + timedelta(minutes=30), _path(policy, "sums"), policy, store)
        attempt = store.in_progress("younger", _key(policy, "sums"))
        assert (attempt.task_set, len(attempt.reopened)) == ("potential", 1)
        assert PALETTE not in page.body
        assert _e(WAITING_LINE) not in page.body


def test_the_plain_revision_task_page_keeps_the_standard_palette_even_as_practice(tmp_path):
    policy = _policy(_task("sheet"), tmp_path)
    with AttemptStore(":memory:") as store:
        store.record("younger", _key(policy, "sheet"), "pass", _at(10, 31, 9))
        page = _open(NOW, _path(policy, "sheet"), policy, store)
        assert store.in_progress("younger", _key(policy, "sheet")).task_set == "practice"
        assert "This is a revision task." in page.body
        assert PALETTE not in page.body and ICON in page.body


# The end screen's Extra Practice link


def _pass_sums(policy, store) -> dict:
    _open(NOW, _path(policy, "sums"), policy, store)

    def post(action, payload):
        page = _open(NOW, _path(policy, "sums"), policy, store, method="POST", query={"do": action}, body=json.dumps(payload).encode())
        return json.loads(page.body)

    post("visit", {})
    question = post("question", {})
    judged = post("answer", {"id": question["id"], "answer": "13", "expired": False})
    assert judged["finished"] is True
    return judged


def test_passing_the_last_task_offers_extra_practice_instead_of_a_next_task(tmp_path):
    policy = _policy(QUIZZES["sums"], tmp_path)
    with AttemptStore(":memory:") as store:
        judged = _pass_sums(policy, store)
        assert (judged["next"], judged["practice"]) == (None, CHOOSER)


def test_with_a_next_task_there_is_no_extra_practice_link(tmp_path):
    policy = _policy(QUIZZES["sums"] + _task("other"), tmp_path)
    with AttemptStore(":memory:") as store:
        judged = _pass_sums(policy, store)
        assert (judged["next"], judged["practice"]) == (PICKER, None)


def test_with_extra_practice_empty_there_is_no_link(tmp_path):
    policy = _policy(QUIZZES["sums"].replace("      pass_cooldown: 0\n", "      pass_cooldown: 0\n      available_from: 2026-12-01\n"), tmp_path)
    with AttemptStore(":memory:") as store:
        judged = _pass_sums(policy, store)
        assert store.attempts("younger", _key(policy, "sums"))[-1].task_set == "practice"
        assert (judged["next"], judged["practice"]) == (None, None)


BACK = "https://www.youtube.com/watch?v=abc"
END_IDS = ["extra-practice", "next-task", "going-back", "go-now"]


def _end_screen(tmp_path, *, practice, back=None, leave=()):
    policy = _policy(QUIZZES["sums"], tmp_path)
    with AttemptStore(":memory:") as store:
        page = _open(NOW, _path(policy, "sums"), policy, store).body
    replies = {
        "visit": [{"correct": 0, "required": 1}],
        "question": [{"id": 0, "question": "6 + 7 =", "allowed_ms": 10_000, "correct": 0, "required": 1}],
        "answer": [
            {
                "outcome": "correct",
                "full": "6 + 7 = 13",
                "correct": 1,
                "required": 1,
                "finished": True,
                "next": None,
                "practice": practice,
                "back": back,
                "sound": None,
            }
        ],
    }
    steps = [
        {"click": "start-button"},
        {"type": ["answer", "13"]},
        {"key": ["answer", "Enter"]},
        {"wait": 1000},
        {"snap": END_IDS, "label": "end"},
        *leave,
    ]
    events = run_page(page, replies, steps=steps)
    snap = next(event["elements"] for event in events if event["kind"] == "snap")
    gone = [(event["at"], event["what"]) for event in events if event["kind"] == "navigate"]
    return snap, gone


@needs_node
def test_all_done_for_now_shows_the_extra_practice_link_to_the_selector(tmp_path):
    shown, _gone = _end_screen(tmp_path, practice=CHOOSER)
    assert shown["extra-practice"]["hidden"] is False
    assert shown["extra-practice"]["href"] == CHOOSER
    assert shown["next-task"]["hidden"] is True


@needs_node
def test_without_extra_practice_the_link_stays_hidden(tmp_path):
    shown, _gone = _end_screen(tmp_path, practice=None)
    assert shown["extra-practice"]["hidden"] is True


@needs_node
def test_extra_practice_stops_the_countdown_back_to_the_page_he_was_sent_from(tmp_path):
    shown, gone = _end_screen(
        tmp_path, practice=CHOOSER, back=BACK, leave=[{"wait": 2000}, {"click": "extra-practice"}, {"wait": 10_000}]
    )
    assert shown["going-back"]["hidden"] is False
    assert shown["extra-practice"]["hidden"] is False
    assert gone == []


# The favicon


def test_the_policy_server_serves_the_owl_without_a_session_on_either_listener(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from asgi import call
    from policy.app import create_app

    monkeypatch.setenv("POLICY_FILE", str(tmp_path / "policy.yaml"))
    monkeypatch.setenv("POLICY_DB", str(tmp_path / "policy.sqlite3"))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    app = create_app()
    for scheme in ("https", "http"):
        status, _body, headers = call(app, "GET", "/favicon.png", scheme=scheme)
        assert status == 200, scheme
        assert headers["content-type"] == ["image/png"]
        assert "set-cookie" not in headers
    assert FAVICON_FILE.read_bytes().startswith(b"\x89PNG")


def test_the_quiz_page_shows_the_owl():
    assert ICON in QUIZ_PAGE


def test_the_not_allowed_page_embeds_the_owl_and_loads_nothing():
    from deny_page import deny_body

    page = deny_body("Time is up <for today>.")
    icon = re.search(r'<link rel="icon" type="image/png" href="([^"]+)">', page)
    assert icon is not None and icon.group(1).startswith("data:image/png;base64,")
    assert "<p>Time is up &lt;for today&gt;.</p>" in page
    assert "http" not in page
