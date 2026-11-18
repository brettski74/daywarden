"""S036.2: the MCP write tools for tasks and sentence pools, through /mcp."""

import json
from contextlib import contextmanager
from datetime import datetime, timezone
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_mcp_server import activity, call_tool, connect, sign_in, tool_answer, tool_names  # noqa: E402

from asgi import call  # noqa: E402
from policy.accounts import Accounts  # noqa: E402
from policy.sentence_pools import pools_directory, write_pool  # noqa: E402
from policy.mcp_writes import CONFIRM  # noqa: E402
from policy.store import PolicyStore  # noqa: E402
from policy.tasks import AttemptStore, TaskKey  # noqa: E402

PASSWORD = "s3cret-pass"
HOUSE = """\
timezone: Australia/Sydney
entry: entry
client_groups:
  younger:
    addresses: ["192.0.2.40"]
include:
  - tasks.d
rule_sets:
  entry:
    - condition: always
      when_true: { action: allow }
"""
TIMES = """\
# The six times table.
tasks:
  arithmetic:
    times-6:
      group: younger   # kept
      pass_cooldown: 1
      failure_cooldown: 0
      body:
        operation: multiplication
        max_timeout: 10s
        min_timeout: 4s
        correct_answers_required: 3   # three right
        first:
          - { value: 6, weight: 1 }
        operands:
          - { from: 2, to: 12, weight: 1 }
"""
WORDS = """\
tasks:
  parts_of_speech:
    words:
      group: younger
      body:
        pools: [Year 3 Basic]
"""
MCP_FILE = """\
enabled: true
permissions:
  tasks: [create, read, update, delete]
  sentence_pools: [create, read, update, delete]
"""
CAT = {"sentence": "The cat sat on the mat.", "parts": {"noun": ["cat", "mat"], "verb": ["sat"], "article": ["the[1]"]}}
DOG = {"sentence": "A dog ran fast.", "parts": {"noun": ["dog"], "verb": ["ran"]}}


def git(config: Path, *arguments: str) -> str:
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    return subprocess.run(
        ["git", "-C", str(config), "-c", "user.name=t", "-c", "user.email=t@t", *arguments],
        check=True, capture_output=True, text=True, env=env,
    ).stdout


@pytest.fixture
def house(tmp_path, monkeypatch):
    """The decisions app with an arithmetic task, a parts of speech task, two pools, and an agent connected."""
    pytest.importorskip("mcp")
    from policy.app import create_app

    data = tmp_path / "data"
    shutil.copytree(os.environ["DAYWARDEN_DATA_DIR"], data)
    shutil.copytree(data / "spelling" / "current", data / "spelling" / "year-3")
    monkeypatch.setenv("DAYWARDEN_DATA_DIR", str(data))
    built = tmp_path / "dist"
    built.mkdir()
    (built / "index.html").write_text("<!DOCTYPE html><title>Daywarden</title>", encoding="utf-8")
    config = tmp_path / "config"
    (config / "tasks.d").mkdir(parents=True)
    (config / "policy.yaml").write_text(HOUSE, encoding="utf-8")
    (config / "tasks.d" / "times-6.yaml").write_text(TIMES, encoding="utf-8")
    (config / "tasks.d" / "words.yaml").write_text(WORDS, encoding="utf-8")
    (config / "mcp.yaml").write_text(MCP_FILE, encoding="utf-8")
    pools = pools_directory(config)
    write_pool(pools, "year-3-basic", "Year 3 Basic", [CAT])
    write_pool(pools, "verbs", "Verbs", [DOG])
    if shutil.which("git") is not None:
        git(config, "init", "-q")
        git(config, "add", "-A")
        git(config, "commit", "-qm", "first")
    database = tmp_path / "policy.sqlite3"
    monkeypatch.setenv("POLICY_FILE", str(config / "policy.yaml"))
    monkeypatch.setenv("POLICY_DB", str(database))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    monkeypatch.setenv("PORTAL_DIR", str(built))
    monkeypatch.setenv("PARENT_NAMES", "garden,localhost")
    monkeypatch.setenv("POLICY_PORT", "8084")
    monkeypatch.delenv("MCP_FILE", raising=False)
    with PolicyStore(database) as store:
        Accounts(store.connection).set_password("ada", PASSWORD)
    app = create_app()
    app.state.config = config
    cookie = sign_in(app)
    _client, tokens = connect(app, cookie)
    return House(app, config, tokens["access_token"], cookie)


class House:
    def __init__(self, app, config: Path, access: str, cookie: str) -> None:
        self.app, self.config, self.access, self.cookie = app, config, access, cookie

    def ok(self, name: str, arguments: dict) -> dict:
        return tool_answer(self.app, self.access, name, arguments)

    def refused(self, name: str, arguments: dict) -> str:
        result = call_tool(self.app, self.access, name, arguments)
        assert result["isError"] is True, result
        return result["content"][0]["text"]

    def text(self, relative: str) -> str:
        return (self.config / relative).read_text(encoding="utf-8")

    def files(self) -> dict[str, str]:
        return {str(path.relative_to(self.config)): path.read_text() for path in sorted(self.config.rglob("*.yaml"))}

    def last(self) -> dict:
        return activity(self.app, self.cookie)[0]

    def portal_task(self, kind: str, name: str) -> dict:
        status, body, _headers = call(self.app, "GET", f"/parent/api/tasks/{kind}/{name}", cookie=self.cookie)
        assert status == 200, body
        return json.loads(body)

    @contextmanager
    def attempts(self):
        with PolicyStore(self.config.parent / "policy.sqlite3") as store:
            yield AttemptStore(connection=store.connection)

    def in_force(self):
        return self.app.state.holder.loaded.policy

    def commit(self) -> str:
        if shutil.which("git") is None:
            pytest.skip("git is not installed")
        return git(self.config, "log", "-1", "--format=%an|%s")


TIMES_6 = {"type": "arithmetic", "name": "times-6"}


# Tools offered


def test_the_write_tools_are_listed_by_the_matrix(house):
    names = tool_names(house.app, house.access)
    for name in ("create_task", "update_task", "rename_task", "retire_task", "create_sentence_pool",
                 "update_sentence_pool", "rename_sentence_pool", "delete_sentence_pool"):
        assert name in names


# Writing


def test_update_changes_only_the_fields_it_names_and_is_in_force_at_once(house):
    before = house.text("tasks.d/times-6.yaml")
    found = house.ok("update_task", {**TIMES_6, "settings": {"pass_cooldown": 2}})
    after = house.text("tasks.d/times-6.yaml")
    assert after == before.replace("pass_cooldown: 1\n", "pass_cooldown: 2\n")
    assert found["task"] == {key: value for key, value in house.portal_task("arithmetic", "times-6").items() if key != "version"}
    assert found["task"]["fields"]["pass_cooldown"] == "2"
    task = next(task for task in house.in_force().tasks if task.name == "times-6")
    assert task.pass_cooldown == 2
    entry = house.last()
    assert (entry["tool"], entry["target"], entry["outcome"], entry["parent"], entry["agent"]) == (
        "update_task", "arithmetic/times-6", "done", "ada", "Claude Code",
    )
    assert house.commit().startswith("ada|")
    assert house.commit().endswith(" ada via Claude Code: saved task arithmetic/times-6\n")


def test_a_number_is_taken_as_the_page_takes_its_text_and_an_arithmetic_weight_is_ignored(house):
    house.ok("update_task", {**TIMES_6, "settings": {"correct_answers_required": 5, "first": [{"value": 7, "weight": 2}], "operands": [{"from": 1, "to": 12}]}})
    text = house.text("tasks.d/times-6.yaml")
    assert "correct_answers_required: 5   # three right" in text
    assert yaml.safe_load(text)["tasks"]["arithmetic"]["times-6"]["body"]["first"] == [{"value": 7}]
    assert "- { from: 1, to: 12 }" in text


def test_practice_fallback_can_be_set_and_cleared_with_null(house):
    house.ok("update_task", {**TIMES_6, "settings": {"practice_fallback": 2}})
    assert yaml.safe_load(house.text("tasks.d/times-6.yaml"))["tasks"]["arithmetic"]["times-6"]["body"]["practice_fallback"] == 2
    house.ok("update_task", {**TIMES_6, "settings": {"practice_fallback": None}})
    assert "practice_fallback" not in house.text("tasks.d/times-6.yaml")
    assert "practice_fallback: must be a whole number, 1 or more" in house.refused(
        "update_task", {**TIMES_6, "settings": {"practice_fallback": 0}}
    )


def test_a_dry_run_checks_and_writes_nothing(house):
    before = house.files()
    found = house.ok("update_task", {**TIMES_6, "settings": {"pass_cooldown": 2}, "dry_run": True})
    assert found["dry_run"] is True
    assert "-      pass_cooldown: 1\n" in found["changes"] and "+      pass_cooldown: 2\n" in found["changes"]
    assert "saved task arithmetic/times-6" in found["message"]
    assert house.files() == before
    assert house.last()["outcome"] == "checked"
    if shutil.which("git") is not None:
        assert git(house.config, "status", "--porcelain") == ""


def test_a_refused_write_lists_its_reasons_writes_nothing_and_is_logged(house):
    before = house.files()
    text = house.refused("update_task", {**TIMES_6, "settings": {"correct_answers_required": 0}})
    _status, body, _headers = call(
        house.app, "POST", "/parent/api/tasks/arithmetic/times-6",
        json_body={"version": house.portal_task("arithmetic", "times-6")["version"], "settings": {"correct_answers_required": "0"}},
        cookie=house.cookie,
    )
    page = json.loads(body)
    assert page["errors"] and all(reason in text for reason in page["errors"])
    assert page["error"] in text
    assert house.files() == before
    entry = house.last()
    assert entry["outcome"] == "refused" and entry["reasons"] == page["errors"]


def test_a_dry_run_that_would_be_refused_is_refused(house):
    text = house.refused("update_task", {**TIMES_6, "settings": {"correct_answers_required": 0}, "dry_run": True})
    assert "correct_answers_required" in text
    assert house.last()["outcome"] == "refused"


def test_every_unknown_setting_is_a_reason(house):
    text = house.refused("update_task", {**TIMES_6, "settings": {"colour": "red", "pools": ["verbs"]}})
    assert "colour is not a setting of a arithmetic task" in text and "pools is not a setting" in text
    assert house.last()["reasons"][0].startswith("colour")


def test_a_write_keeps_the_comments_of_the_file(house):
    house.ok("update_task", {**TIMES_6, "settings": {"groups": ["younger"], "max_timeout": "12s"}})
    text = house.text("tasks.d/times-6.yaml")
    assert text.startswith("# The six times table.\n")
    assert "group: younger   # kept" in text and "# three right" in text and "max_timeout: 12s" in text


def test_a_due_date_already_passed_is_refused_until_confirmed(house):
    house.ok("update_task", {**TIMES_6, "settings": {"due_date": "2099-01-01"}})
    with house.attempts() as store:
        store.record("younger", TaskKey("arithmetic", "times-6"), "pass", datetime(2026, 11, 2, 16, tzinfo=timezone.utc))
    before = house.files()
    text = house.refused("update_task", {**TIMES_6, "settings": {"pass_cooldown": 3}})
    assert text == "younger already has a pass for times-6. Saving does not ask it to do the task again. " + CONFIRM
    assert house.files() == before
    house.ok("update_task", {**TIMES_6, "settings": {"pass_cooldown": 3}, "confirmed": True})
    assert "pass_cooldown: 3" in house.text("tasks.d/times-6.yaml")


# Tasks


def test_create_task_makes_it_as_the_new_task_page_does(house):
    settings = {
        "groups": ["younger"], "pass_cooldown": 1, "operation": "multiplication", "max_timeout": "10s",
        "min_timeout": "4s", "correct_answers_required": 3,
        "first": [{"value": 7, "weight": 1}], "operands": [{"from": 2, "to": 12, "weight": 1}],
    }
    found = house.ok("create_task", {"type": "arithmetic", "name": "times-7", "settings": settings})
    assert found["task"]["name"] == "times-7" and found["task"]["fields"]["pass_cooldown"] == "1"
    assert found["task"]["arithmetic"]["first"] == [{"from": "7", "to": ""}]
    status, body, _headers = call(house.app, "GET", "/parent/api/tasks", cookie=house.cookie)
    assert {"type": "arithmetic", "name": "times-7"} in json.loads(body)["tasks"]
    assert "times-7" in {task.name for task in house.in_force().tasks}
    assert house.commit().endswith("ada via Claude Code: created task arithmetic/times-7\n")
    assert "already exists" in house.refused("create_task", {"type": "arithmetic", "name": "times-7", "settings": settings})


def test_create_task_refuses_a_type_it_cannot_make(house):
    assert "is not a type a task can be made with" in house.refused("create_task", {"type": "worksheet", "name": "sheet"})


def test_rename_task_takes_its_attempts_with_it(house):
    with house.attempts() as store:
        store.record("younger", TaskKey("arithmetic", "times-6"), "pass", datetime(2026, 11, 2, 16, tzinfo=timezone.utc))
    found = house.ok("rename_task", {**TIMES_6, "new_name": "sixes"})
    assert found["task"]["name"] == "sixes"
    assert not (house.config / "tasks.d" / "times-6.yaml").exists()
    assert "sixes:" in house.text("tasks.d/sixes.yaml")
    with house.attempts() as store:
        assert [attempt.task for attempt in store.attempts("younger")] == ["sixes"]
    assert house.commit().endswith("ada via Claude Code: renamed task arithmetic/times-6 to arithmetic/sixes\n")


def test_retire_task_takes_it_out_of_the_policy(house):
    found = house.ok("retire_task", TIMES_6)
    assert found["retired"] == TIMES_6
    assert not (house.config / "tasks.d" / "times-6.yaml").exists()
    assert "times-6" not in {task.name for task in house.in_force().tasks}
    assert house.commit().endswith("ada via Claude Code: retired task arithmetic/times-6\n")
    assert house.last()["outcome"] == "done"


def test_retire_task_in_a_shared_file_removes_only_its_lines(house):
    shared = house.config / "tasks.d" / "words.yaml"
    shared.write_text(WORDS + "    more:\n      group: younger\n      body:\n        pools: [Verbs]\n  # end of the list\n", encoding="utf-8")
    house.ok("retire_task", {"type": "parts_of_speech", "name": "more"})
    assert shared.read_text() == WORDS + "  # end of the list\n"


def test_retire_task_dry_run_shows_the_file_removed(house):
    found = house.ok("retire_task", {**TIMES_6, "dry_run": True})
    assert "+++ /dev/null" in found["changes"]
    assert (house.config / "tasks.d" / "times-6.yaml").exists()


def test_a_parts_of_speech_task_chooses_pools_by_id(house):
    found = house.ok("update_task", {"type": "parts_of_speech", "name": "words", "settings": {"pools": ["year-3-basic", "verbs"]}})
    assert found["task"]["parts_of_speech"]["pools"] == ["Year 3 Basic", "Verbs"]
    assert "pools: [\"Year 3 Basic\", Verbs]" in house.text("tasks.d/words.yaml")
    text = house.refused("update_task", {"type": "parts_of_speech", "name": "words", "settings": {"pools": ["nouns"]}})
    assert "nouns is not a pool id" in text


def test_a_spelling_task_takes_its_settings_and_an_existing_directory_but_not_words(house):
    settings = {"groups": ["younger"], "timeout": "40s", "current_dir": "spelling/year-3"}
    found = house.ok("create_task", {"type": "spelling", "name": "spell", "settings": settings})
    assert found["task"]["spelling"]["directories"]["current_dir"] == "spelling/year-3"
    text = house.refused("update_task", {"type": "spelling", "name": "spell", "settings": {"words": ["rope"]}})
    assert text == "A spelling task's words are set in the portal, where they are recorded."
    text = house.refused("update_task", {"type": "spelling", "name": "spell", "settings": {"revision_dir": "spelling/nowhere"}})
    assert "is not an existing directory" in text
    assert not (Path(os.environ["DAYWARDEN_DATA_DIR"]) / "spelling" / "nowhere").exists()


# Sentence pools


def test_create_sentence_pool_makes_a_listed_pool(house):
    found = house.ok("create_sentence_pool", {"name": "Nouns", "sentences": [CAT, DOG]})
    assert found["pool"]["name"] == "Nouns"
    assert [sentence["text"] for sentence in found["pool"]["sentences"]] == [CAT["sentence"], DOG["sentence"]]
    status, body, _headers = call(house.app, "GET", "/parent/api/parts-of-speech-pools", cookie=house.cookie)
    assert "Nouns" in [pool["name"] for pool in json.loads(body)["pools"]]
    written = yaml.safe_load(house.text("parts_of_speech_pools/nouns.yaml"))
    # A word is written as the sentence has it, as the pool page writes it.
    assert written == {"name": "Nouns", "sentences": [{**CAT, "parts": {**CAT["parts"], "article": ["The"]}}, DOG]}
    assert house.commit().endswith("ada via Claude Code: made parts of speech pool Nouns\n")


def test_a_marked_word_not_in_its_sentence_is_refused(house):
    before = house.files()
    text = house.refused("create_sentence_pool", {"name": "Bad", "sentences": [{"sentence": "A dog ran.", "parts": {"noun": ["cat"]}}]})
    assert "cat" in text
    assert house.files() == before


def test_update_sentence_pool_adds_and_removes_together(house):
    found = house.ok("update_sentence_pool", {"id": "year-3-basic", "add": [DOG], "remove": [CAT["sentence"]]})
    assert [sentence["text"] for sentence in found["pool"]["sentences"]] == [DOG["sentence"]]
    text = house.refused("update_sentence_pool", {"id": "year-3-basic", "remove": ["Not there."]})
    assert "reads exactly: Not there." in text


def test_rename_and_delete_a_pool_as_its_page_does(house):
    found = house.ok("rename_sentence_pool", {"id": "year-3-basic", "name": "Year Three"})
    assert found["pool"]["name"] == "Year Three"
    assert "pools: [\"Year Three\"]" in house.text("tasks.d/words.yaml")
    text = house.refused("delete_sentence_pool", {"id": "year-3-basic"})
    assert "cannot be deleted while a task uses it: words" in text
    found = house.ok("delete_sentence_pool", {"id": "verbs"})
    assert found["deleted"] == {"id": "verbs", "name": "Verbs"}
    assert not (house.config / "parts_of_speech_pools" / "verbs.yaml").exists()
