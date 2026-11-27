"""S047: the config history in the portal and through the MCP tools: list, compare, and revert."""

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from asgi import call  # noqa: E402
from test_mcp_server import activity, call_tool, connect, sign_in, tool_answer, tool_names  # noqa: E402
from test_mcp_writes import HOUSE, TIMES, git  # noqa: E402

from policy.accounts import Accounts  # noqa: E402
from policy.store import PolicyStore  # noqa: E402

PASSWORD = "s3cret-pass"
API = "/parent/api/settings/history"
MCP_FILE = """\
enabled: true
permissions:
  tasks: [create, read, update, delete]
  config_history: [read, update]
"""
STAMPED = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}\Z")

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


@pytest.fixture
def house(tmp_path, monkeypatch):
    """The decisions app with a config directory whose history has one commit, and an agent connected as ada."""
    pytest.importorskip("mcp")
    from policy.app import create_app

    built = tmp_path / "dist"
    built.mkdir()
    (built / "index.html").write_text("<!DOCTYPE html><title>Daywarden</title>", encoding="utf-8")
    config = tmp_path / "config"
    (config / "tasks.d").mkdir(parents=True)
    (config / "policy.yaml").write_text(HOUSE, encoding="utf-8")
    (config / "tasks.d" / "times-6.yaml").write_text(TIMES, encoding="utf-8")
    (config / "mcp.yaml").write_text(MCP_FILE, encoding="utf-8")
    git(config, "init", "-q")
    git(config, "add", "-A")
    git(config, "commit", "-qm", "2026-11-17 20:15 -0500 t: install.sh")
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
    cookie = sign_in(app)
    _client, tokens = connect(app, cookie)
    return House(app, config, database, tokens["access_token"], cookie)


class House:
    def __init__(self, app, config: Path, database: Path, access: str, cookie: str) -> None:
        self.app, self.config, self.database, self.access, self.cookie = app, config, database, access, cookie

    def get(self, path: str, query: str = "", cookie: str | None = "default") -> tuple[int, dict]:
        status, body, _headers = call(self.app, "GET", path, query=query, cookie=self.cookie if cookie == "default" else cookie)
        return status, json.loads(body)

    def post(self, path: str, body: dict, cookie: str | None = "default") -> tuple[int, dict]:
        status, text, _headers = call(self.app, "POST", path, json_body=body, cookie=self.cookie if cookie == "default" else cookie)
        return status, json.loads(text)

    def listing(self, query: str = "") -> dict:
        status, body = self.get(API, query)
        assert status == 200, body
        return body

    def head(self) -> str:
        return git(self.config, "rev-parse", "HEAD").strip()

    def subjects(self) -> list[str]:
        return git(self.config, "log", "--format=%s").splitlines()

    def files(self) -> dict[str, str]:
        return {
            str(path.relative_to(self.config)): path.read_text(encoding="utf-8")
            for path in sorted(self.config.rglob("*"))
            if path.is_file() and ".git" not in path.parts
        }

    def save_task(self, cooldown: str) -> None:
        status, body = self.get("/parent/api/tasks/arithmetic/times-6")
        assert status == 200, body
        status, body = self.post(
            "/parent/api/tasks/arithmetic/times-6", {"version": body["version"], "fields": {"pass_cooldown": cooldown}}
        )
        assert status == 200, body

    def rename_group(self, old: str, new: str) -> None:
        status, page = self.get("/parent/api/policy/client-groups")
        assert status == 200, page
        status, body = self.post("/parent/api/policy/client-groups/rename", {"version": page["version"], "name": old, "to": new})
        assert status == 200, body

    def hand_commit(self, relative: str, text: str | None, message: str = "by hand") -> str:
        path = self.config / relative
        if text is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        git(self.config, "add", "-A")
        git(self.config, "commit", "-qm", message)
        return self.head()

    def preview(self, revision: str) -> dict:
        status, body = self.get(f"{API}/revisions/{revision}/revert")
        assert status == 200, body
        return body

    def revert(self, revision: str, head: str | None = None) -> tuple[int, dict]:
        return self.post(f"{API}/revisions/{revision}/revert", {"head": head or self.head()})

    def tool(self, name: str, arguments: dict) -> dict:
        return tool_answer(self.app, self.access, name, arguments)

    def refused(self, name: str, arguments: dict) -> str:
        result = call_tool(self.app, self.access, name, arguments)
        assert result["isError"] is True, result
        return result["content"][0]["text"]


def _first(house: House) -> str:
    return git(house.config, "rev-list", "--max-parents=0", "HEAD").strip()


# The list


def test_a_portal_save_is_the_top_row_with_who_what_and_the_file(house):
    house.save_task("2")
    top, first = house.listing()["revisions"]
    assert (top["author"], top["what"], top["files"]) == ("ada", "saved task arithmetic/times-6", ["tasks.d/times-6.yaml"])
    assert STAMPED.match(top["time"])
    assert (first["author"], first["what"]) == ("t", "install.sh")
    assert sorted(first["files"]) == ["mcp.yaml", "policy.yaml", "tasks.d/times-6.yaml"]


def test_what_drops_the_time_and_user_but_keeps_an_agents_name_and_a_hand_message_whole(house):
    from policy.config_history import what

    assert what("2026-11-17 20:15 -0500 ada via Claude Code: saved task arithmetic/times-7", "ada") == "via Claude Code: saved task arithmetic/times-7"
    assert what("2026-11-17 20:15 -0500 brett: saved task spelling", "brett") == "saved task spelling"
    assert what("fixed the bedtime by hand", "brett") == "fixed the bedtime by hand"
    assert what("2026-11-17 20:15 -0500 hand edits found before a portal save", "ada") == "hand edits found before a portal save"


def test_the_list_is_fifty_to_a_page_newest_first(house):
    for number in range(55):
        house.hand_commit("notes.txt", f"{number}\n", f"note {number}")
    first = house.listing()
    assert (first["page"], first["pages"], first["total"], len(first["revisions"])) == (1, 2, 56, 50)
    assert first["revisions"][0]["what"] == "note 54"
    second = house.listing("page=2")
    assert [row["what"] for row in second["revisions"]] == ["note 4", "note 3", "note 2", "note 1", "note 0", "install.sh"]
    assert house.listing("page=9")["page"] == 2


def test_filtering_on_a_file_keeps_its_revisions_even_once_it_is_removed(house):
    house.hand_commit("tasks.d/extra.yaml", "tasks: {}\n", "added extra")
    house.save_task("3")
    house.hand_commit("tasks.d/extra.yaml", None, "removed extra")
    shown = house.listing("file=tasks.d/extra.yaml")
    assert shown["file"] == "tasks.d/extra.yaml"
    assert [row["what"] for row in shown["revisions"]] == ["removed extra", "added extra"]


def test_uncommitted_hand_edits_are_named_above_the_list(house):
    assert house.listing()["hand_edits"] == []
    (house.config / "policy.yaml").write_text(HOUSE + "# edited\n", encoding="utf-8")
    (house.config / "tasks.d" / "new.yaml").write_text("tasks: {}\n", encoding="utf-8")
    assert sorted(house.listing()["hand_edits"]) == ["policy.yaml", "tasks.d/new.yaml"]


def test_with_no_history_the_list_says_so_and_nothing_else_is_offered(house):
    shutil.rmtree(house.config / ".git")
    assert house.listing() == {"kept": False}
    assert house.get(f"{API}/revisions/abcd")[0] == 404
    assert house.get(f"{API}/compare", "from=abcd&to=abcd")[0] == 404
    assert house.get(f"{API}/revisions/abcd/revert")[0] == 404
    assert house.revert("abcd", "abcd")[0] == 404
    for name, arguments in (
        ("list_config_history", {}),
        ("get_config_revision", {"revision": "current"}),
        ("diff_config_revisions", {"from": "current"}),
        ("revert_config", {"revision": "abcd"}),
    ):
        assert "no config history" in house.refused(name, arguments)


# Revision pages and comparing


def test_the_first_revision_shows_every_file_added_and_a_short_or_full_id_opens_it(house):
    first = _first(house)
    status, page = house.get(f"{API}/revisions/{first[:7]}")
    assert status == 200
    assert page["revision"]["id"] == first
    assert page["before"] is None
    assert [(item["path"], item["status"]) for item in page["diff"]] == [
        ("mcp.yaml", "added"), ("policy.yaml", "added"), ("tasks.d/times-6.yaml", "added"),
    ]
    assert all(line["kind"] == "+" for item in page["diff"] for hunk in item["hunks"] for line in hunk["lines"])
    assert house.get(f"{API}/revisions/{first}")[1]["revision"]["id"] == first
    for unknown in ("0000000", "nothex", "--all"):
        assert house.get(f"{API}/revisions/{unknown}")[0] == 404


def test_a_revision_shows_what_it_changed_with_three_lines_of_context(house):
    house.save_task("5")
    status, page = house.get(f"{API}/revisions/{house.head()}")
    assert status == 200 and page["newest"] is True
    (changed,) = page["diff"]
    assert (changed["path"], changed["status"]) == ("tasks.d/times-6.yaml", "changed")
    (hunk,) = changed["hunks"]
    kinds = [line["kind"] for line in hunk["lines"]]
    assert kinds == [" ", " ", " ", "-", "+", " ", " ", " "]
    assert [line["text"] for line in hunk["lines"] if line["kind"] != " "] == ["      pass_cooldown: 1", "      pass_cooldown: 5"]
    assert "-      pass_cooldown: 1\n+      pass_cooldown: 5\n" in changed["unified"]


def test_compare_shows_the_diff_in_its_direction_and_nothing_for_the_same_files(house):
    first = _first(house)
    house.save_task("4")
    status, page = house.get(f"{API}/compare", f"from={first}&to={house.head()}")
    assert status == 200
    assert page["from"]["id"] == first and page["to"]["author"] == "ada"
    (changed,) = page["diff"]
    assert [line["text"] for hunk in changed["hunks"] for line in hunk["lines"] if line["kind"] == "+"] == ["      pass_cooldown: 4"]
    back = house.get(f"{API}/compare", f"from={house.head()}&to={first}")[1]
    assert [line["text"] for hunk in back["diff"][0]["hunks"] for line in hunk["lines"] if line["kind"] == "+"] == ["      pass_cooldown: 1"]
    assert house.get(f"{API}/compare", f"from={first}&to={first}")[1]["diff"] == []
    assert house.get(f"{API}/compare", f"from={first}&to=0000000")[0] == 404


# Revert


def test_revert_puts_every_file_back_but_mcp_yaml_and_commits_one_new_revision(house):
    first = _first(house)
    before = house.files()
    house.save_task("7")
    house.hand_commit("tasks.d/later.yaml", "tasks: {}\n", "added later")
    house.hand_commit("mcp.yaml", MCP_FILE + "activity_days: 30\n", "mcp by hand")
    house.hand_commit("policy.yaml", None, "removed policy")
    house.hand_commit("policy.yaml", HOUSE.replace("192.0.2.40", "192.0.2.50"), "policy back")
    preview = house.preview(first[:7])
    assert preview["head"] == house.head() and preview["nothing"] is False
    assert {item["path"]: item["status"] for item in preview["diff"]} == {
        "policy.yaml": "changed", "tasks.d/later.yaml": "removed", "tasks.d/times-6.yaml": "changed",
    }
    assert "mcp.yaml" in preview["mcp"]
    count = len(house.subjects())

    status, body = house.revert(first[:7], preview["head"])
    assert status == 200, body
    after = house.files()
    assert after["mcp.yaml"] == MCP_FILE + "activity_days: 30\n"
    assert {name: text for name, text in after.items() if name != "mcp.yaml"} == {name: text for name, text in before.items() if name != "mcp.yaml"}
    subjects = house.subjects()
    assert len(subjects) == count + 1
    assert re.fullmatch(rf"\d{{4}}-\d\d-\d\d \d\d:\d\d [+-]\d{{4}} ada: reverted to {first[:7]} \(\d{{4}}-\d\d-\d\d \d\d:\d\d\)", subjects[0])
    assert git(house.config, "status", "--porcelain") == ""
    status, compared = house.get(f"{API}/compare", f"from={first}&to={house.head()}")
    assert [item["path"] for item in compared["diff"]] == ["mcp.yaml"]
    # The services use the reverted policy.
    assert house.app.state.holder.loaded.policy.client_groups[0].ips == ("192.0.2.40",)


def test_a_revert_can_itself_be_reverted(house):
    first = _first(house)
    house.save_task("8")
    saved = house.head()
    changed = house.files()
    assert house.revert(first)[0] == 200
    status, body = house.revert(saved)
    assert status == 200, body
    assert house.files() == changed


def test_a_revert_that_fails_the_check_writes_and_commits_nothing(house):
    broken = TIMES.replace("group: younger", "group: nobody")
    old = house.hand_commit("tasks.d/times-6.yaml", broken, "broken by hand")
    house.hand_commit("tasks.d/times-6.yaml", TIMES, "fixed by hand")
    before, subjects = house.files(), house.subjects()
    status, body = house.revert(old)
    assert status == 400
    assert body["error"].startswith("The files of this version do not pass dw check")
    assert any("nobody" in problem and str(house.config) in problem for problem in body["errors"])
    assert house.files() == before and house.subjects() == subjects


def test_a_spelling_task_whose_directory_is_gone_is_refused(house, tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "spelling" / "week-1").mkdir(parents=True)
    monkeypatch.setenv("DAYWARDEN_DATA_DIR", str(data))
    spelling = "tasks:\n  spelling:\n    spelling:\n      group: younger\n      body:\n        current_dir: spelling/week-1\n"
    old = house.hand_commit("tasks.d/spelling.yaml", spelling, "spelling by hand")
    house.hand_commit("tasks.d/spelling.yaml", None, "spelling removed")
    assert house.preview(old)["diff"]
    (data / "spelling" / "week-1").rmdir()
    status, body = house.revert(old)
    assert status == 400, body
    assert any("week-1" in problem for problem in body["errors"])
    assert not (house.config / "tasks.d" / "spelling.yaml").exists()


def test_hand_edits_are_committed_first_and_broken_ones_refuse_the_revert(house):
    first = _first(house)
    house.save_task("6")
    (house.config / "policy.yaml").write_text(HOUSE.replace("younger:", "younger:\n    # a note"), encoding="utf-8")
    status, body = house.revert(first)
    assert status == 200, body
    assert house.subjects()[1].endswith("hand edits found before a portal save")
    assert house.subjects()[0].endswith(f"ada: reverted to {first[:7]} ({house.listing()['revisions'][-1]['time']})")

    house.save_task("9")
    (house.config / "policy.yaml").write_text(HOUSE.replace("entry: entry", "entry: nowhere"), encoding="utf-8")
    subjects = house.subjects()
    status, body = house.revert(first)
    assert status == 400
    assert body["error"].startswith("The hand edits on the server do not pass dw check")
    assert house.subjects() == subjects


def test_a_revert_opened_before_another_save_is_refused(house):
    first = _first(house)
    opened = house.preview(first)["head"]
    house.save_task("2")
    before, subjects = house.files(), house.subjects()
    status, body = house.revert(first, opened)
    assert status == 409 and body["stale"] is True
    assert "changed" in body["error"]
    assert house.files() == before and house.subjects() == subjects


def test_a_revision_with_nothing_but_mcp_yaml_changed_reverts_nothing(house):
    first = _first(house)
    house.hand_commit("mcp.yaml", MCP_FILE + "activity_days: 30\n", "mcp by hand")
    assert house.preview(first)["nothing"] is True
    subjects = house.subjects()
    status, body = house.revert(first)
    assert status == 200 and body["nothing"] is True
    assert "nothing was reverted" in body["message"]
    assert house.subjects() == subjects


def test_the_newest_revision_cannot_be_reverted_to(house):
    status, body = house.revert(house.head())
    assert status == 400 and "newest" in body["error"]


def test_renames_crossed_are_listed_and_the_rows_stay_under_the_new_name(house):
    first = _first(house)
    house.rename_group("younger", "kids")
    house.save_task("3")
    house.rename_group("kids", "little")
    renames = house.preview(first)["renames"]
    assert renames == [
        "Client group younger was renamed to kids after this version. Attempts and usage recorded under kids stay under kids.",
        "Client group kids was renamed to little after this version. Attempts and usage recorded under little stay under little.",
    ]
    status, body = house.revert(first)
    assert status == 200, body
    assert body["renames"] == renames


def test_a_failed_commit_leaves_the_revert_applied_with_a_warning(house, monkeypatch):
    from policy.history import History, HistoryError

    first = _first(house)
    house.save_task("4")

    def refuse(*_args, **_kwargs):
        raise HistoryError("the disk is full")

    monkeypatch.setattr(History, "commit", refuse)
    status, body = house.revert(first)
    assert status == 200, body
    assert any("not in the config history" in warning for warning in body["warnings"])
    assert "pass_cooldown: 1" in (house.config / "tasks.d" / "times-6.yaml").read_text(encoding="utf-8")


# Access


def test_the_pages_need_a_session_and_the_revert_needs_json(house):
    first = _first(house)
    for path, query in ((API, ""), (f"{API}/revisions/{first}", ""), (f"{API}/compare", f"from={first}&to={first}")):
        status, body = house.get(path, query, cookie=None)
        assert status == 401, body
    assert house.post(f"{API}/revisions/{first}/revert", {"head": house.head()}, cookie=None)[0] == 401
    status, _body, _headers = call(
        house.app, "POST", f"{API}/revisions/{first}/revert", body=b"head=x", content_type="application/x-www-form-urlencoded", cookie=house.cookie
    )
    assert status == 415


def test_a_reviewer_is_refused_every_history_address(house):
    with PolicyStore(house.database) as store:
        Accounts(store.connection).set_password("nana", PASSWORD, "reviewer")
    _status, _body, headers = call(house.app, "POST", "/parent/api/login", json_body={"username": "nana", "password": PASSWORD})
    nana = next(value.split(";", 1)[0] for value in headers["set-cookie"])
    first = _first(house)
    for path in (API, f"{API}/revisions/{first}", f"{API}/revisions/{first}/revert"):
        status, body = house.get(path, cookie=nana)
        assert status == 403 and body["admins_only"] is True
    status, body = house.post(f"{API}/revisions/{first}/revert", {"head": house.head()}, cookie=nana)
    assert status == 403 and body["admins_only"] is True


# The MCP tools


def test_the_tools_list_read_and_diff_the_history(house):
    first = _first(house)
    house.save_task("5")
    assert {"list_config_history", "get_config_revision", "diff_config_revisions", "revert_config"} <= set(tool_names(house.app, house.access))
    listed = house.tool("list_config_history", {})["revisions"]
    assert [row["author"] for row in listed] == ["ada", "t"]
    assert listed[0]["short"] == listed[0]["id"][: len(listed[0]["short"])]
    assert set(listed[0]) == {"id", "short", "time", "author", "message", "files"}
    assert [row["id"] for row in house.tool("list_config_history", {"before": listed[0]["short"]})["revisions"]] == [first]
    assert len(house.tool("list_config_history", {"limit": 1})["revisions"]) == 1
    assert [row["id"] for row in house.tool("list_config_history", {"file": "mcp.yaml"})["revisions"]] == [first]

    got = house.tool("get_config_revision", {"revision": first[:7]})
    assert got["files"]["tasks.d/times-6.yaml"] == TIMES
    assert list(house.tool("get_config_revision", {"revision": "current", "file": "policy.yaml"})["files"]) == ["policy.yaml"]
    assert "There is no file nope.yaml" in house.refused("get_config_revision", {"revision": "current", "file": "nope.yaml"})
    assert "There is no revision 0000000" in house.refused("get_config_revision", {"revision": "0000000"})

    (changed,) = house.tool("diff_config_revisions", {"from": first})["files"]
    assert changed["status"] == "changed" and "+      pass_cooldown: 5" in changed["diff"]
    (same,) = house.tool("diff_config_revisions", {"revision": "current"})["files"]
    assert same == changed
    added = house.tool("diff_config_revisions", {"revision": first})["files"]
    assert {item["status"] for item in added} == {"added"}


def test_revert_config_dry_runs_then_reverts_naming_the_agent(house):
    first = _first(house)
    house.save_task("5")
    before, subjects = house.files(), house.subjects()
    dry = house.tool("revert_config", {"revision": first[:7], "dry_run": True})
    assert dry["dry_run"] is True
    (changed,) = dry["files"]
    assert changed["path"] == "tasks.d/times-6.yaml" and "+      pass_cooldown: 1" in changed["diff"]
    assert house.files() == before and house.subjects() == subjects
    assert activity(house.app, house.cookie)[0]["outcome"] == "checked"

    done = house.tool("revert_config", {"revision": first[:7]})
    assert done["message"].startswith(f"Reverted to {first[:7]}")
    assert re.search(rf" ada via Claude Code: reverted to {first[:7]} \(", house.subjects()[0])
    entry = activity(house.app, house.cookie)[0]
    assert (entry["tool"], entry["target"], entry["outcome"]) == ("revert_config", first[:7], "done")


def test_revert_config_refuses_as_the_portal_does(house):
    broken = TIMES.replace("group: younger", "group: nobody")
    old = house.hand_commit("tasks.d/times-6.yaml", broken, "broken by hand")
    house.hand_commit("tasks.d/times-6.yaml", TIMES, "fixed by hand")
    text = house.refused("revert_config", {"revision": old})
    assert "do not pass dw check" in text and "nobody" in text
    assert activity(house.app, house.cookie)[0]["outcome"] == "refused"


def test_config_history_needs_its_permission(house):
    (house.config / "mcp.yaml").write_text(MCP_FILE.replace("config_history: [read, update]", "config_history: [read]"), encoding="utf-8")
    status, body, _headers = call(house.app, "POST", "/v1/reload", scheme="http")
    assert status == 200, body
    names = set(tool_names(house.app, house.access))
    assert "list_config_history" in names and "revert_config" not in names
    assert house.refused("revert_config", {"revision": "current"}) == "This needs config_history: update."
