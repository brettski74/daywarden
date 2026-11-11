"""S023.2: the task pages' data, saving a task to its policy file, and moving spelling words."""

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from asgi import call, session_cookie  # noqa: E402
from conftest import write_alphabet, write_wav  # noqa: E402
from policy import control  # noqa: E402
from policy.accounts import Accounts  # noqa: E402
from policy.observations import listen  # noqa: E402
from policy.store import PolicyStore  # noqa: E402
from policy.tasks import AttemptStore, TaskKey  # noqa: E402
from policy.usage import UsageStore  # noqa: E402

PASSWORD = "s3cret-pass"
ZONE = ZoneInfo("America/Toronto")
HOUSE = """\
# The household policy.
entry: gate
timezone: America/Toronto
include:
  - extra.yaml
client_groups:
  younger:
    addresses: ["192.0.2.40"]
  older:
    addresses: ["192.0.2.50"]
rule_sets:
  gate:
    - condition: always
      when_true: { action: allow }   # spacing kept
tasks:
  spelling:
    # Words for this week.
    spelling:
      group: younger
      pass_cooldown: 1   # once a day
      max_skips: 3
      body:
        timeout: 30s
        revision_required: 1
  parent_check:
    check:
      group: younger
      pass_cooldown: 0
"""
EXTRA = """\
tasks:
  worksheet:
    sums:
      groups: [younger]
      pass_cooldown: 2
"""


def _git(directory: Path, *args: str) -> str:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(directory),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "blg",
        "GIT_AUTHOR_EMAIL": "blg@daywarden.invalid",
        "GIT_COMMITTER_NAME": "blg",
        "GIT_COMMITTER_EMAIL": "blg@daywarden.invalid",
    }
    return subprocess.run(["git", "-C", str(directory), *args], env=env, check=True, capture_output=True, text=True).stdout


class House:
    """The decisions app over a config directory and a data directory, with a signed-in parent."""

    def __init__(self, tmp_path: Path, monkeypatch, *, history: bool = False, text: str = HOUSE):
        from policy.app import create_app

        self.config = tmp_path / "config"
        self.config.mkdir()
        self.policy = self.config / "policy.yaml"
        self.policy.write_text(text, encoding="utf-8")
        (self.config / "extra.yaml").write_text(EXTRA, encoding="utf-8")
        self.data = tmp_path / "data"
        write_alphabet(self.data / "spelling/alphabet")
        for name in ("rope", "cat", "dog"):
            write_wav(self.data / f"spelling/current/{name}.wav")
        write_wav(self.data / "spelling/current/rope.sentence.wav")
        write_wav(self.data / "spelling/revision/fish.wav")
        write_wav(self.data / "spelling/attic/owl.wav")
        if history:
            _git(self.config, "init", "--quiet", "--initial-branch=main")
            _git(self.config, "add", "--all")
            _git(self.config, "commit", "--quiet", "-m", "2026-11-08 21:00 -0500 blg: install.sh")
        self.database = tmp_path / "policy.sqlite3"
        monkeypatch.setenv("POLICY_FILE", str(self.policy))
        monkeypatch.setenv("POLICY_DB", str(self.database))
        monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
        monkeypatch.setenv("DAYWARDEN_DATA_DIR", str(self.data))
        monkeypatch.setenv("PORTAL_DIR", str(tmp_path / "dist"))
        with PolicyStore(self.database) as store:
            Accounts(store.connection).set_password("ada", PASSWORD)
        self.app = create_app()
        _status, _body, headers = call(
            self.app, "POST", "/parent/api/login", json_body={"username": "ada", "password": PASSWORD}
        )
        self.cookie = session_cookie(headers)

    def get(self, path: str, *, cookie: str | None = "") -> tuple[int, dict]:
        status, body, _headers = call(self.app, "GET", path, cookie=self.cookie if cookie == "" else cookie)
        return status, json.loads(body)

    def page(self, task: str = "spelling/spelling") -> dict:
        """Return a task's page. ``task`` is its type and name, as in ``spelling/spelling``."""
        status, body = self.get(f"/parent/api/tasks/{task}")
        assert status == 200, body
        return body

    def save(self, task: str = "spelling/spelling", **changes) -> tuple[int, dict]:
        changes.setdefault("version", self.page(task)["version"])
        status, body, _headers = call(self.app, "POST", f"/parent/api/tasks/{task}", json_body=changes, cookie=self.cookie)
        return status, json.loads(body)

    def retire(self, word: str, task: str = "spelling/spelling") -> tuple[int, dict]:
        status, body, _headers = call(
            self.app, "POST", f"/parent/api/tasks/{task}/retire", json_body={"word": word}, cookie=self.cookie
        )
        return status, json.loads(body)

    def task(self, task: str = "spelling/spelling"):
        return self.app.state.holder.loaded.policy.task(TaskKey(*task.split("/")))

    def files(self, pool: str) -> list[str]:
        directory = self.data / "spelling" / pool
        return sorted(child.name for child in directory.iterdir()) if directory.is_dir() else []

    def log(self) -> list[str]:
        return _git(self.config, "log", "--format=%an <%ae> %s").splitlines()


@pytest.fixture
def house(tmp_path, monkeypatch):
    return House(tmp_path, monkeypatch)


@pytest.fixture
def kept(tmp_path, monkeypatch):
    """A house whose config directory has its own history."""
    return House(tmp_path, monkeypatch, history=True)


# Reading a task


def test_the_task_list_names_every_task_in_every_file_in_name_order(house):
    assert house.get("/parent/api/tasks") == (
        200,
        {
            "tasks": [
                {"type": "parent_check", "name": "check"},
                {"type": "spelling", "name": "spelling"},
                {"type": "worksheet", "name": "sums"},
            ]
        },
    )


def test_a_task_page_shows_the_file_and_the_words_in_each_pool(house):
    page = house.page()
    assert page["type"] == "spelling"
    assert page["groups"] == ["younger"]
    assert page["clients"] == ["younger", "older", "default"]
    assert page["fields"] == {
        "pass_cooldown": "1",
        "failure_cooldown": "",
        "max_skips": "3",
        "max_passes": "",
        "available_from": "",
        "due_date": "",
    }
    spelling = page["spelling"]
    assert spelling["settings"]["timeout"] == "30s"
    assert spelling["settings"]["revision_required"] == "1"
    assert spelling["directories"] == {
        "current_dir": "spelling/current",
        "revision_dir": "spelling/revision",
        "attic_dir": "spelling/attic",
        "alphabet_dir": "spelling/alphabet",
    }
    words = {word["key"]: (word["pool"], word["sentence"]) for word in spelling["words"]}
    assert words == {
        "rope": ("current", "rope.sentence.wav"),
        "cat": ("current", None),
        "dog": ("current", None),
        "fish": ("revision", None),
        "owl": ("attic", None),
    }


def test_a_parent_check_page_has_no_date_skip_or_pass_fields(house):
    assert house.page("parent_check/check")["fields"] == {"pass_cooldown": "0", "failure_cooldown": ""}
    assert "spelling" not in house.page("parent_check/check")


class _Instant(datetime):
    """A datetime whose now is always ``moment``, for the household clock."""

    moment = datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.moment.astimezone(tz)


@pytest.mark.parametrize(
    ("utc", "today"),
    [
        # 04:59 and 05:00 in Toronto, a day behind Kiritimati from 10:00 UTC.
        (datetime(2026, 11, 10, 9, 59, tzinfo=timezone.utc), "2026-11-10"),
        (datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc), "2026-11-11"),
    ],
)
def test_task_pages_carry_the_households_today_in_the_policys_timezone(tmp_path, monkeypatch, utc, today):
    monkeypatch.setattr("policy.clock.datetime", _Instant)
    monkeypatch.setattr(_Instant, "moment", utc)
    house = House(tmp_path, monkeypatch, text=HOUSE.replace("timezone: America/Toronto", "timezone: Pacific/Kiritimati"))
    assert house.page()["today"] == today
    assert house.page("parent_check/check")["today"] == today
    assert house.get("/parent/api/new-task")[1]["today"] == today


def test_an_unknown_task_is_not_found(house):
    assert house.get("/parent/api/tasks/worksheet/nope") == (404, {"error": "There is no worksheet task named nope."})


def test_without_a_session_the_task_data_and_audio_answer_401_and_never_redirect(house):
    for path in (
        "/parent/api/tasks",
        "/parent/api/tasks/spelling/spelling",
        "/parent/api/tasks/spelling/spelling/audio/current/rope.wav",
    ):
        status, body, headers = call(house.app, "GET", path)
        assert status == 401, path
        assert "location" not in headers
        assert "rope" not in body
    status, _body, _headers = call(house.app, "POST", "/parent/api/tasks/spelling/spelling", json_body={"version": "x"})
    assert status == 401
    status, _body, _headers = call(house.app, "POST", "/parent/api/tasks/spelling/spelling/retire", json_body={"word": "rope"})
    assert status == 401
    assert house.files("current") == ["cat.wav", "dog.wav", "rope.sentence.wav", "rope.wav"]


def test_a_save_must_be_a_json_post(house):
    status, _body, _headers = call(
        house.app, "POST", "/parent/api/tasks/spelling/spelling", body=b"pass_cooldown=4", content_type="application/x-www-form-urlencoded", cookie=house.cookie
    )
    assert status == 415


def test_the_recordings_play_from_their_pool_and_nothing_else_is_served(house):
    status, body, headers = call(house.app, "GET", "/parent/api/tasks/spelling/spelling/audio/current/rope.sentence.wav", cookie=house.cookie)
    assert status == 200
    assert headers["content-type"][0].startswith("audio/wav")
    assert body.startswith("RIFF")
    for path in (
        "/parent/api/tasks/spelling/spelling/audio/revision/rope.wav",
        "/parent/api/tasks/spelling/spelling/audio/alphabet/a.wav",
        "/parent/api/tasks/spelling/spelling/audio/current/..%2F..%2F..%2Fconfig%2Fpolicy.yaml",
        "/parent/api/tasks/worksheet/sums/audio/current/rope.wav",
    ):
        assert call(house.app, "GET", path, cookie=house.cookie)[0] == 404, path


# Saving the common settings


def test_a_save_changes_only_that_field_and_the_next_decision_uses_it(house):
    status, body = house.save(fields={"pass_cooldown": "4"})
    assert status == 200, body
    assert body["message"].startswith("Saved spelling.")
    assert house.policy.read_text(encoding="utf-8") == HOUSE.replace("pass_cooldown: 1   # once a day", "pass_cooldown: 4   # once a day")
    assert house.task().pass_cooldown == 4


def test_a_task_in_an_included_file_is_saved_in_that_file(house):
    status, body = house.save("worksheet/sums", fields={"max_passes": "5"})
    assert status == 200, body
    assert house.policy.read_text(encoding="utf-8") == HOUSE
    assert (house.config / "extra.yaml").read_text(encoding="utf-8") == EXTRA + "      max_passes: 5\n"
    assert house.task("worksheet/sums").max_passes == 5


def test_clearing_a_field_removes_it_and_the_rule_is_off(house):
    status, body = house.save(fields={"max_skips": "", "pass_cooldown": ""})
    assert status == 200, body
    text = house.policy.read_text(encoding="utf-8")
    assert "max_skips" not in text
    assert "    pass_cooldown: 1   # once a day\n" not in text
    assert house.task().max_skips is None
    assert house.task().pass_cooldown == 1


def test_new_fields_and_groups_are_written_inside_the_task(house):
    status, body = house.save(fields={"due_date": "2026-11-30", "failure_cooldown": "1"}, groups=["younger", "older"])
    assert status == 200, body
    task = house.task()
    assert (task.groups, str(task.due_date), task.failure_cooldown) == (("younger", "older"), "2026-11-30", 1)
    assert house.task("parent_check/check").groups == ("younger",)


@pytest.mark.parametrize(
    ("fields", "named"),
    [
        ({"max_passes": "-1"}, "max_passes"),
        ({"available_from": "next week"}, "available_from"),
        ({"pass_cooldown": "1.5"}, "pass_cooldown"),
        ({"max_skips": "3\nentry: other"}, "max_skips"),
    ],
)
def test_a_value_the_policy_refuses_is_named_and_nothing_is_written(house, fields, named):
    status, body = house.save(fields=fields)
    assert status == 400
    assert body["error"] == "This save would leave the policy unable to load, so nothing was saved."
    assert any(named in problem for problem in body["errors"])
    assert house.policy.read_text(encoding="utf-8") == HOUSE


def test_a_parent_check_cannot_be_given_a_due_date(house):
    status, body = house.save("parent_check/check", fields={"due_date": "2026-11-30"})
    assert (status, body) == (400, {"error": "due_date cannot be changed from the parent pages"})


def test_a_file_edited_since_the_page_opened_is_not_saved_over(house):
    version = house.page()["version"]
    edited = HOUSE.replace("max_skips: 3", "max_skips: 7")
    house.policy.write_text(edited, encoding="utf-8")
    status, body = house.save(version=version, fields={"pass_cooldown": "4"})
    assert status == 409
    assert "Reload the page" in body["error"]
    assert house.policy.read_text(encoding="utf-8") == edited


def test_a_task_with_a_due_date_that_a_group_has_passed_asks_first(house):
    house.policy.write_text(HOUSE.replace("max_skips: 3", "due_date: 2026-11-09"), encoding="utf-8")
    with PolicyStore(house.database) as store:
        AttemptStore(connection=store.connection).record("younger", TaskKey("spelling", "spelling"), "pass", datetime(2026, 11, 2, 16, tzinfo=ZONE))
    status, body = house.save(fields={"pass_cooldown": "4"})
    assert status == 409
    assert body["groups"] == ["younger"]
    assert body["confirm"] == "younger already has a pass for spelling. Saving does not ask it to do the task again."
    assert "pass_cooldown: 1" in house.policy.read_text(encoding="utf-8")
    status, body = house.save(fields={"pass_cooldown": "4"}, confirmed=True)
    assert status == 200, body
    assert house.task().pass_cooldown == 4


def test_a_task_with_no_due_date_saves_without_asking(house):
    with PolicyStore(house.database) as store:
        AttemptStore(connection=store.connection).record("younger", TaskKey("spelling", "spelling"), "pass", datetime(2026, 11, 2, 16, tzinfo=ZONE))
    assert house.save(fields={"pass_cooldown": "4"})[0] == 200


def test_a_spelling_setting_is_saved_in_the_body_and_the_next_run_uses_it(house):
    status, body = house.save(settings={"timeout": "20s", "word_pause": "500ms"})
    assert status == 200, body
    assert house.task().document() == {"timeout": "20s", "revision_required": 1, "word_pause": "500ms"}


def test_a_save_reloads_the_other_services_through_their_sockets(tmp_path, monkeypatch):
    socket_path = tmp_path / "observations.sock"
    monkeypatch.setenv("OBSERVATIONS_SOCKET", str(socket_path))
    monkeypatch.setenv("AUTOCONFIG_SOCKET", str(tmp_path / "nobody-listens.sock"))
    house = House(tmp_path, monkeypatch)
    usage = UsageStore(":memory:")
    server = listen(None, usage, host="127.0.0.1", port=0, policy_file=house.policy)
    controller = control.serve(socket_path, {"reload": server.reload_policy})
    threading.Thread(target=controller.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    try:
        status, body = house.save(fields={"pass_cooldown": "4"})
    finally:
        controller.shutdown()
        controller.server_close()
        server.server_close()
    assert status == 200, body
    assert [warning.split(":")[0] for warning in body["warnings"]] == [
        "The autoconfig service did not reload and keeps the policy it had"
    ]


# Spelling words


def test_a_new_pool_moves_the_word_and_its_sentence_on_save(house):
    status, body = house.save(moves={"rope": "revision", "owl": "current"})
    assert status == 200, body
    assert body["message"] == "Moved 2 words."
    assert house.files("current") == ["cat.wav", "dog.wav", "owl.wav"]
    assert house.files("revision") == ["fish.wav", "rope.sentence.wav", "rope.wav"]
    assert house.files("attic") == []
    assert house.policy.read_text(encoding="utf-8") == HOUSE


def test_a_save_cannot_put_a_word_in_the_attic_only_retire_can(house):
    status, body = house.save(moves={"cat": "attic"}, fields={"pass_cooldown": "4"})
    assert (status, body) == (400, {"error": "cat can only go to the attic with Retire, which asks first. Nothing was saved."})
    assert house.files("attic") == ["owl.wav"]
    assert house.policy.read_text(encoding="utf-8") == HOUSE
    assert house.save(moves={"owl": "attic"})[1]["message"] == "Nothing has changed, so nothing was saved."


def test_a_move_that_leaves_too_few_current_words_is_refused_until_the_target_is_lowered(house):
    house.policy.write_text(HOUSE.replace("timeout: 30s", "timeout: 30s\n        current_required: 3"), encoding="utf-8")
    status, body = house.save(moves={"cat": "revision"})
    assert status == 400
    assert any("current_required" in problem and "only 2" in problem for problem in body["errors"])
    assert house.files("current") == ["cat.wav", "dog.wav", "rope.sentence.wav", "rope.wav"]
    status, body = house.save(moves={"cat": "revision"}, settings={"current_required": "2"})
    assert status == 200, body
    assert "cat.wav" in house.files("revision")
    assert house.task().document()["current_required"] == 2


def test_retire_moves_the_recordings_to_the_attic_at_once(house):
    status, body = house.retire("rope")
    assert (status, body["message"]) == (200, "Retired rope. Its recordings are in the attic.")
    assert house.files("attic") == ["owl.wav", "rope.sentence.wav", "rope.wav"]
    assert "rope.wav" not in house.files("current")
    assert house.retire("owl") == (400, {"error": "owl is already in the attic."})


def test_retire_makes_the_attic_the_task_names(house):
    house.policy.write_text(HOUSE.replace("timeout: 30s", "timeout: 30s\n        attic_dir: spelling/old-words"), encoding="utf-8")
    assert house.retire("cat")[0] == 200
    assert sorted(child.name for child in (house.data / "spelling/old-words").iterdir()) == ["cat.wav"]


def test_a_retire_that_would_leave_nothing_to_ask_is_refused(house):
    house.policy.write_text(HOUSE.replace("revision_required: 1", "revision_required: 0"), encoding="utf-8")
    for word in ("rope", "cat"):
        assert house.retire(word)[0] == 200
    status, body = house.retire("dog")
    assert status == 400
    assert any("nothing to ask" in problem for problem in body["errors"])
    assert house.files("current") == ["dog.wav"]


@pytest.mark.parametrize("moved", ["rope", "cat"])
def test_a_clash_made_by_hand_refuses_every_save_and_retire_and_nothing_moves(house, moved):
    write_wav(house.data / "spelling/attic/rope.wav")
    status, body = house.retire(moved)
    assert status == 400
    assert any("rope.wav is also in current_dir" in problem for problem in body["errors"])
    status, body = house.save(moves={moved: "revision"})
    assert status == 400
    assert any("rope.wav is also in current_dir" in problem for problem in body["errors"])
    assert house.files("current") == ["cat.wav", "dog.wav", "rope.sentence.wav", "rope.wav"]
    assert house.files("attic") == ["owl.wav", "rope.wav"]


# The config history


def test_a_save_is_committed_as_the_parent_with_only_that_change(kept):
    status, body = kept.save(fields={"pass_cooldown": "4"})
    assert status == 200, body
    assert body["warnings"] == []
    log = kept.log()
    assert len(log) == 2
    assert log[0].startswith("ada <ada@daywarden.invalid> 2026-") or log[0].startswith("ada <ada@daywarden.invalid> 20")
    assert log[0].endswith(" ada: saved task spelling/spelling")
    shown = _git(kept.config, "show", "--format=", "HEAD")
    assert [line for line in shown.splitlines() if line[:1] in "+-" and line[:3] not in ("+++", "---")] == [
        "-      pass_cooldown: 1   # once a day",
        "+      pass_cooldown: 4   # once a day",
    ]
    assert _git(kept.config, "status", "--porcelain") == ""


def test_good_hand_edits_are_committed_first_then_the_save(kept):
    kept.policy.write_text(HOUSE.replace("max_skips: 3", "max_skips: 5"), encoding="utf-8")
    status, body = kept.save("worksheet/sums", fields={"max_passes": "2"})
    assert status == 200, body
    log = kept.log()
    assert log[0].endswith(" ada: saved task worksheet/sums")
    assert log[1].endswith(" hand edits found before a portal save")
    assert "max_skips: 5" in _git(kept.config, "show", "HEAD~1")
    assert kept.task().max_skips == 5
    assert kept.task("worksheet/sums").max_passes == 2


def test_broken_hand_edits_refuse_the_save_and_nothing_is_written_or_committed(kept):
    broken = HOUSE.replace("      group: younger\n      pass_cooldown: 0", "      group: nobody\n      pass_cooldown: 0")
    kept.policy.write_text(broken, encoding="utf-8")
    status, body = kept.save("worksheet/sums", fields={"max_passes": "2"})
    assert status == 400
    assert body["error"].startswith("The hand edits on the server do not pass dw check")
    assert any("unknown client group 'nobody'" in problem for problem in body["errors"])
    assert (kept.config / "extra.yaml").read_text(encoding="utf-8") == EXTRA
    assert len(kept.log()) == 1


def test_moving_and_retiring_words_make_no_commit(kept):
    assert kept.retire("rope")[0] == 200
    assert kept.save(moves={"cat": "revision"})[0] == 200
    assert len(kept.log()) == 1


def test_a_failed_commit_still_saves_and_applies_and_warns(kept):
    (kept.config / ".git" / "index.lock").write_text("", encoding="utf-8")
    from policy import history

    history.LOCK_WAIT_SECONDS = 0.2
    try:
        status, body = kept.save(fields={"pass_cooldown": "4"})
    finally:
        history.LOCK_WAIT_SECONDS = 5.0
    assert status == 200, body
    assert body["warnings"][0].startswith("This change is not in the config history")
    assert kept.task().pass_cooldown == 4


def test_without_a_history_of_its_own_a_save_works_and_commits_nothing(house):
    assert house.save(fields={"pass_cooldown": "4"})[0] == 200
    assert not (house.config / ".git").exists()
