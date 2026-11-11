"""S027: creating a task and renaming one from the parent portal."""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from asgi import call  # noqa: E402
from test_task_admin import EXTRA, HOUSE, House, _git  # noqa: E402
from policy.check import load_required  # noqa: E402
from policy.task_names import file_stem, free_file, name_problem  # noqa: E402
from policy.task_page import respond_task  # noqa: E402
from policy.tasks import PASS, AttemptStore, TaskKey  # noqa: E402

ZONE = ZoneInfo("America/Toronto")
YOUNGER = "192.0.2.40"
NOW = datetime(2026, 11, 10, 16, 0, tzinfo=ZONE)
SUMS = {
    "fields": {"pass_cooldown": "2"},
    "groups": ["younger"],
    "settings": {"operation": "addition", "max_timeout": "10s", "min_timeout": "4s", "correct_answers_required": "3"},
    "lists": {"operands": [{"from": "7", "to": "", "weight": ""}]},
}


class Creating(House):
    def post(self, path: str, body: dict, *, cookie: str | None = "") -> tuple[int, dict]:
        status, text, _headers = call(self.app, "POST", path, json_body=body, cookie=self.cookie if cookie == "" else cookie)
        return status, json.loads(text)

    def lock(self, kind: str, name: str) -> tuple[int, dict]:
        return self.post("/parent/api/new-task/check", {"type": kind, "name": name})

    def create(self, kind: str, name: str, **body) -> tuple[int, dict]:
        return self.post("/parent/api/new-task", {"type": kind, "name": name, **body})

    def rename(self, task: str, name: str) -> tuple[int, dict]:
        return self.post(f"/parent/api/tasks/{task}/rename", {"name": name, "version": self.page(task)["version"]})

    def catalogue(self) -> list[str]:
        return [f"{task['type']}/{task['name']}" for task in self.get("/parent/api/tasks")[1]["tasks"]]

    def tasks_d(self) -> list[str]:
        directory = self.config / "tasks.d"
        return sorted(child.name for child in directory.iterdir()) if directory.is_dir() else []

    def store(self) -> AttemptStore:
        return AttemptStore(self.database)


@pytest.fixture
def house(tmp_path, monkeypatch):
    return Creating(tmp_path, monkeypatch)


@pytest.fixture
def kept(tmp_path, monkeypatch):
    return Creating(tmp_path, monkeypatch, history=True)


def _with_tasks_d(house: Creating, files: dict[str, str]) -> None:
    house.policy.write_text(HOUSE.replace("  - extra.yaml\n", "  - extra.yaml\n  - tasks.d\n"), encoding="utf-8")
    (house.config / "tasks.d").mkdir(exist_ok=True)
    for name, text in files.items():
        (house.config / "tasks.d" / name).write_text(text, encoding="utf-8")


ADDITION = """\
# Addition for the younger one.
tasks:
  arithmetic:
    {name}:
      group: younger   # kept
      body:
        operation: addition
        max_timeout: 10s
        min_timeout: 4s
        correct_answers_required: 3
        operands:
          - {{ value: 7, weight: 1 }}
"""


# Names and file names


@pytest.mark.parametrize(
    ("name", "problem"),
    [
        ("", "Give the task a name."),
        (" sums", "A name has no space at either end."),
        ("sums ", "A name has no space at either end."),
        ("x" * 41, "A name is at most 40 characters."),
        ("week/1", "A name cannot hold a /, because the task's address could not."),
    ],
)
def test_a_name_that_breaks_a_rule_says_why(name, problem):
    assert name_problem(name) == problem


@pytest.mark.parametrize("name", ["x" * 40, "Café Sums", "Week 3 — Times Tables!", "中文", "a b"])
def test_any_other_name_is_allowed(name):
    assert name_problem(name) is None


@pytest.mark.parametrize(
    ("name", "stem"),
    [
        ("Café Sums", "cafe_sums"),
        ("year-3 spelling", "year-3_spelling"),
        ("Week 3 — Times Tables!", "week_3_times_tables_"),
        ("Straße", "strasse"),
        ("Øre Ærø Łódź", "ore_aero_lodz"),
        ("snake_case  name", "snake_case_name"),
        ("中文 words", "_words"),
        ("..", "_"),
    ],
)
def test_a_file_name_is_folded_to_lower_case_ascii(name, stem):
    assert file_stem(name) == stem


def test_a_used_file_name_takes_the_next_free_number_with_either_extension(tmp_path):
    (tmp_path / "some_new_task.yaml").write_text("")
    (tmp_path / "some_new_task.2.yaml").write_text("")
    (tmp_path / "sums.yml").write_text("")
    assert free_file(tmp_path, "Some New Task") == tmp_path / "some_new_task.3.yaml"
    assert free_file(tmp_path, "Sums") == tmp_path / "sums.2.yaml"
    assert free_file(tmp_path / "missing", "Sums") == tmp_path / "missing" / "sums.yaml"


def test_the_tasks_own_file_is_not_a_clash(tmp_path):
    (tmp_path / "sums.yml").write_text("")
    (tmp_path / "sums.2.yaml").write_text("")
    assert free_file(tmp_path, "SUMS", own=tmp_path / "sums.yml") == tmp_path / "sums.yml"
    assert free_file(tmp_path, "Sums", own=tmp_path / "sums.2.yaml") == tmp_path / "sums.2.yaml"
    assert free_file(tmp_path, "Take", own=tmp_path / "sums.2.yaml") == tmp_path / "take.yaml"


# The new task page and its lock-in


def test_the_new_task_page_offers_every_type_but_parent_check_and_empty_fields(house):
    status, body = house.get("/parent/api/new-task")
    assert status == 200
    assert body["types"] == ["arithmetic", "parts_of_speech", "skip_counting", "spelling"]
    assert body["clients"] == ["younger", "older", "default"]
    assert set(body["fields"].values()) == {""}


@pytest.mark.parametrize("kind", ["arithmetic", "parts_of_speech", "skip_counting", "spelling"])
def test_locking_in_returns_the_page_of_a_task_with_an_empty_body_and_writes_nothing(house, kind):
    before = house.policy.read_text()
    status, page = house.lock(kind, "Café Sums")
    assert status == 200, page
    assert (page["name"], page["type"], page["version"], page["groups"]) == ("Café Sums", kind, "", [])
    assert page["file"] == str(house.config / "tasks.d" / "cafe_sums.yaml")
    assert set(page["fields"].values()) == {""}
    assert kind in page
    assert house.policy.read_text() == before
    assert house.tasks_d() == []


def test_an_empty_body_shows_each_types_defaults_and_no_problems(house):
    assert house.lock("parts_of_speech", "pos")[1]["parts_of_speech"] == {
        "settings": {"timeout": "", "correct_answers_required": ""},
        "sentences": [],
        "problems": [],
    }
    skip = house.lock("skip_counting", "skips")[1]["skip_counting"]
    assert skip["difference"] is None and skip["default"]
    sums = house.lock("arithmetic", "adding")[1]["arithmetic"]
    assert (sums["first"], sums["operands"], sums["problems"]) == ([], [], [])
    words = house.lock("spelling", "words")[1]["spelling"]
    assert {word["key"] for word in words["words"]} == {"rope", "cat", "dog", "fish", "owl"}


@pytest.mark.parametrize(
    ("kind", "name", "error"),
    [
        ("parent_check", "check-2", "Choose the task's type."),
        ("", "new", "Choose the task's type."),
        ("arithmetic", " new", "A name has no space at either end."),
        ("spelling", "SPELLING", "A spelling task named spelling already exists."),
        ("worksheet", "sums", "Choose the task's type."),
    ],
)
def test_a_name_or_type_that_cannot_be_used_is_refused_at_the_lock_in(house, kind, name, error):
    assert house.lock(kind, name) == (400, {"error": error})


def test_a_name_is_taken_only_within_its_type(house):
    assert house.lock("arithmetic", "spelling")[0] == 200


def test_a_name_with_attempts_stored_from_a_removed_task_is_taken(house):
    with house.store() as store:
        store.record("younger", TaskKey("arithmetic", "old sums"), PASS, NOW)
    assert house.lock("arithmetic", "Old Sums") == (
        400,
        {
            "error": "Attempts are still stored under arithmetic/old sums, from a task no longer in the policy. "
            "Choose another name, or remove them with `bin/rm-attempts --task 'old sums' --type arithmetic`."
        },
    )
    assert house.lock("spelling", "old sums")[0] == 200


def test_the_new_task_addresses_need_a_session_and_a_json_post(house):
    for path, body in (("/parent/api/new-task/check", {}), ("/parent/api/new-task", {}), ("/parent/api/tasks/spelling/spelling/rename", {})):
        status, text, headers = call(house.app, "POST", path, json_body=body)
        assert status == 401 and "location" not in headers, text
        status, _text, _headers = call(house.app, "POST", path, body=b"type=arithmetic", content_type="application/x-www-form-urlencoded", cookie=house.cookie)
        assert status == 415
    status, _text, headers = call(house.app, "GET", "/parent/api/new-task")
    assert status == 401 and "location" not in headers


# Creating


def test_a_new_task_gets_its_own_file_tasks_d_and_an_include_in_one_commit(kept):
    root_before = kept.policy.read_text()
    status, body = kept.create("arithmetic", "Café Sums", **SUMS)
    assert status == 200, body
    assert body["task"] == {"type": "arithmetic", "name": "Café Sums"}
    assert body["message"].startswith(f"Created Café Sums in {kept.config / 'tasks.d' / 'cafe_sums.yaml'}.")
    assert (kept.config / "tasks.d" / "cafe_sums.yaml").read_text() == (
        "tasks:\n"
        "  arithmetic:\n"
        "    Café Sums:\n"
        "      groups: [younger]\n"
        "      pass_cooldown: 2\n"
        "      body:\n"
        "        operation: addition\n"
        "        max_timeout: 10s\n"
        "        min_timeout: 4s\n"
        "        correct_answers_required: 3\n"
        "        operands:\n"
        "          - { value: 7, weight: 1 }\n"
    )
    assert kept.policy.read_text() == root_before.replace("  - extra.yaml\n", "  - extra.yaml\n  - tasks.d\n")
    assert kept.catalogue() == ["arithmetic/Café Sums", "parent_check/check", "spelling/spelling", "worksheet/sums"]
    assert kept.task("arithmetic/Café Sums").pass_cooldown == 2
    log = kept.log()
    assert len(log) == 2 and log[0].endswith("ada: created task arithmetic/Café Sums")
    changed = _git(kept.config, "show", "--name-only", "--no-renames", "--format=", "HEAD").split()
    assert sorted(changed) == ["policy.yaml", "tasks.d/cafe_sums.yaml"]
    load_required(kept.policy, warn=lambda _message: None)


def test_the_child_is_offered_a_new_task_by_the_same_rules_as_any_other(house):
    house.create("arithmetic", "adding", **SUMS)
    policy = house.app.state.holder.loaded.policy
    with house.store() as store:
        page = respond_task(policy, store, method="GET", path="/tasks/arithmetic/adding", client_ip=YOUNGER, now=NOW)
    assert page.status == 200


def test_an_include_is_added_as_a_list_when_the_root_file_has_none(house):
    house.policy.write_text(HOUSE.replace("include:\n  - extra.yaml\n", ""), encoding="utf-8")
    assert house.create("arithmetic", "adding", **SUMS)[0] == 200
    assert house.policy.read_text() == HOUSE.replace("include:\n  - extra.yaml\n", "") + "include:\n  - tasks.d\n"


def test_a_flow_include_list_gains_tasks_d(house):
    house.policy.write_text(HOUSE.replace("include:\n  - extra.yaml\n", "include: [extra.yaml]\n"), encoding="utf-8")
    assert house.create("arithmetic", "adding", **SUMS)[0] == 200
    assert "include:\n  - extra.yaml\n  - tasks.d\nclient_groups:" in house.policy.read_text()


def test_with_tasks_d_already_included_only_the_new_file_is_written_and_numbered(kept):
    _with_tasks_d(kept, {"adding.yaml": ADDITION.format(name="addition"), "adding.2.yml": ADDITION.format(name="more")})
    _git(kept.config, "add", "--all")
    _git(kept.config, "commit", "--quiet", "-m", "tasks.d")
    root = kept.policy.read_text()
    assert kept.create("arithmetic", "Adding", **SUMS)[0] == 200
    assert kept.tasks_d() == ["adding.2.yml", "adding.3.yaml", "adding.yaml"]
    assert kept.policy.read_text() == root
    assert _git(kept.config, "show", "--name-only", "--no-renames", "--format=", "HEAD").split() == ["tasks.d/adding.3.yaml"]


def test_each_type_can_be_created_from_its_page(house):
    sentence = {"text": "The cat sat.", "timeout": "", "parts": [{"name": "noun", "words": [1]}, {"name": "verb", "words": [2]}]}
    assert house.create("parts_of_speech", "pos", groups=["younger"], settings={"timeout": "40s"}, sentences=[sentence])[0] == 200
    assert house.create("skip_counting", "skips", groups=["younger"], settings={"sequence_length": "6"}, lists={"difference": "default"})[0] == 200
    assert house.create("spelling", "words", groups=["younger"], settings={"revision_required": "1"}, moves={"cat": "revision"})[0] == 200
    assert house.task("parts_of_speech/pos").document()["sentences"][0]["sentence"] == "The cat sat."
    assert house.task("skip_counting/skips").document() == {"sequence_length": 6}
    assert house.files("revision") == ["cat.wav", "fish.wav"]
    assert "body:\n        revision_required: 1\n" in (house.config / "tasks.d" / "words.yaml").read_text()


def test_a_new_task_the_policy_refuses_is_not_written_and_the_errors_are_listed(kept):
    status, body = kept.create("arithmetic", "adding", **{**SUMS, "groups": []})
    assert status == 400
    assert body["errors"] == [f"{kept.config / 'tasks.d' / 'adding.yaml'}:4:7: task 'arithmetic/adding': group or groups is required"]
    assert kept.tasks_d() == [] and not (kept.config / "tasks.d").exists()
    assert kept.policy.read_text() == HOUSE
    assert len(kept.log()) == 1


def test_a_failure_partway_through_a_create_takes_back_every_step(house, monkeypatch):
    import policy.task_create as task_create

    def broken(path, text):
        raise OSError("disk full")

    monkeypatch.setattr(task_create, "replace_text", broken)
    status, body = house.create("arithmetic", "adding", **SUMS)
    assert status == 500 and "disk full" in body["error"], body
    assert not (house.config / "tasks.d").exists()
    assert house.policy.read_text() == HOUSE


def test_a_taken_name_is_refused_when_the_task_is_written_too(house):
    assert house.create("arithmetic", "adding", **SUMS)[0] == 200
    assert house.create("arithmetic", "ADDING", **SUMS) == (400, {"error": "An arithmetic task named adding already exists."})


# Renaming


def test_a_rename_in_the_root_file_changes_only_the_key_and_keeps_its_file(kept):
    status, body = kept.rename("spelling/spelling", "Week 3 words")
    assert status == 200, body
    assert body["task"] == {"type": "spelling", "name": "Week 3 words"}
    assert body["message"].startswith("Renamed spelling to Week 3 words.")
    assert kept.policy.read_text() == HOUSE.replace("    spelling:\n      group", "    Week 3 words:\n      group")
    assert kept.get("/parent/api/tasks/spelling/spelling") == (404, {"error": "There is no spelling task named spelling."})
    assert kept.page("spelling/Week 3 words")["name"] == "Week 3 words"
    assert kept.log()[0].endswith("ada: renamed task spelling/spelling to spelling/Week 3 words")


def test_a_rename_carries_the_history_and_the_attempt_in_progress(house):
    with house.store() as store:
        store.record("younger", TaskKey("spelling", "spelling"), PASS, NOW)
        open_attempt = store.begin("younger", TaskKey("spelling", "spelling"), NOW)
        store.record("younger", TaskKey("parent_check", "spelling"), PASS, NOW)
    assert house.rename("spelling/spelling", "words")[0] == 200
    with house.store() as store:
        assert [attempt.task for attempt in store.attempts("younger")] == ["words", "words", "spelling"]
        assert store.in_progress("younger", TaskKey("spelling", "words")).id == open_attempt.id


def test_a_task_alone_in_tasks_d_has_its_file_renamed_with_its_history_followed(kept):
    _with_tasks_d(kept, {"adding.yaml": ADDITION.format(name="adding")})
    _git(kept.config, "add", "--all")
    _git(kept.config, "commit", "--quiet", "-m", "tasks.d")
    assert kept.rename("arithmetic/adding", "Take Away")[0] == 200
    assert kept.tasks_d() == ["take_away.yaml"]
    assert (kept.config / "tasks.d" / "take_away.yaml").read_text() == ADDITION.format(name="Take Away")
    assert sorted(_git(kept.config, "show", "--name-only", "--no-renames", "--format=", "HEAD").split()) == ["tasks.d/adding.yaml", "tasks.d/take_away.yaml"]
    assert len(_git(kept.config, "log", "--follow", "--format=%s", "--", "tasks.d/take_away.yaml").splitlines()) == 2


def test_a_rename_whose_file_name_comes_out_the_same_keeps_the_file(house):
    _with_tasks_d(house, {"adding.yaml": ADDITION.format(name="adding")})
    assert house.rename("arithmetic/adding", "Adding")[0] == 200
    assert house.tasks_d() == ["adding.yaml"]


def test_a_task_sharing_its_file_or_outside_tasks_d_keeps_its_file(house):
    shared = ADDITION.format(name="adding") + ADDITION.format(name="more").split("  arithmetic:\n", 1)[1]
    _with_tasks_d(house, {"adding.yaml": shared})
    assert house.rename("arithmetic/adding", "plus")[0] == 200
    assert house.tasks_d() == ["adding.yaml"]
    assert house.rename("worksheet/sums", "work")[0] == 200
    assert (house.config / "extra.yaml").read_text() == EXTRA.replace("    sums:", "    work:")


def test_a_taken_name_is_refused_but_a_change_of_case_is_not(house):
    _with_tasks_d(house, {"adding.yaml": ADDITION.format(name="adding"), "plus.yaml": ADDITION.format(name="plus")})
    assert house.rename("arithmetic/adding", "Plus") == (400, {"error": "An arithmetic task named plus already exists."})
    assert house.rename("arithmetic/adding", "ADDING")[0] == 200


def test_a_rename_to_a_bad_name_or_from_a_stale_page_is_refused(house):
    assert house.rename("spelling/spelling", "a/b") == (400, {"error": "A name cannot hold a /, because the task's address could not."})
    status, body = house.post("/parent/api/tasks/spelling/spelling/rename", {"name": "words", "version": "old"})
    assert status == 409 and body["stale"]


def test_a_spelling_tasks_new_week_moves_with_it(house):
    status, _body = house.post("/parent/api/tasks/spelling/spelling/week", {"rows": [], "add": "frog toad"})
    assert status == 200
    assert house.rename("spelling/spelling", "Week 3 words")[0] == 200
    status, week = house.get("/parent/api/tasks/spelling/Week 3 words/week")
    assert status == 200 and [word["key"] for word in week["words"]] == ["frog", "toad"]


def test_a_failure_partway_through_a_rename_takes_back_every_step(house, monkeypatch):
    _with_tasks_d(house, {"adding.yaml": ADDITION.format(name="adding")})
    with house.store() as store:
        store.record("younger", TaskKey("arithmetic", "adding"), PASS, NOW)

    def broken(self, old, new):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(AttemptStore, "rename", broken)
    status, body = house.rename("arithmetic/adding", "plus")
    assert status == 500 and "database is locked" in body["error"]
    assert house.tasks_d() == ["adding.yaml"]
    assert (house.config / "tasks.d" / "adding.yaml").read_text() == ADDITION.format(name="adding")
    monkeypatch.undo()
    with house.store() as store:
        assert [attempt.task for attempt in store.attempts("younger")] == ["adding"]


def test_the_childs_open_page_goes_to_the_picker_and_the_renamed_task_carries_on(house):
    assert house.create("arithmetic", "adding", **SUMS)[0] == 200
    with house.store() as store:
        policy = house.app.state.holder.loaded.policy
        opened = respond_task(policy, store, method="GET", path="/tasks/arithmetic/adding", client_ip=YOUNGER, now=NOW)
        assert opened.status == 200
        started = store.in_progress("younger", TaskKey("arithmetic", "adding"))
    assert house.rename("arithmetic/adding", "plus")[0] == 200
    policy = house.app.state.holder.loaded.policy
    with house.store() as store:
        answer = respond_task(
            policy, store, method="POST", path="/tasks/arithmetic/adding", client_ip=YOUNGER, now=NOW, query={"do": "answer"}, body=b"{}"
        )
        assert answer.status == 409 and json.loads(answer.body) == {"reload": True}
        reopened = respond_task(policy, store, method="GET", path="/tasks/arithmetic/adding", client_ip=YOUNGER, now=NOW)
        assert reopened.status == 302 and dict(reopened.headers)["location"].endswith("/tasks/next")
        respond_task(policy, store, method="GET", path="/tasks/arithmetic/plus", client_ip=YOUNGER, now=NOW)
        assert store.in_progress("younger", TaskKey("arithmetic", "plus")).id == started.id
