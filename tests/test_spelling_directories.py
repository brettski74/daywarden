"""S028: choosing a spelling task's directories, making new ones, and filling them from the setup page."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from asgi import call  # noqa: E402
from conftest import write_wav  # noqa: E402
from test_task_admin import HOUSE, House  # noqa: E402
from test_week import _keep, _take  # noqa: E402
from policy import spelling_directories, week  # noqa: E402

TASK = "/parent/api/tasks/spelling/spelling"
WEEK = f"{TASK}/week"


@pytest.fixture
def house(tmp_path, monkeypatch):
    return House(tmp_path, monkeypatch)


@pytest.fixture
def kept(tmp_path, monkeypatch):
    return House(tmp_path, monkeypatch, history=True)


def _post(house: House, path: str, body: dict) -> tuple[int, dict]:
    status, text, _headers = call(house.app, "POST", path, json_body=body, cookie=house.cookie)
    return status, json.loads(text)


def _make(house: House, name: str, path: str = f"{TASK}/directories") -> tuple[int, dict]:
    return _post(house, path, {"name": name})


def _words_in(house: House, folder: str, *names: str) -> None:
    for name in names:
        write_wav(house.data / "spelling" / folder / f"{name}.wav")


def _get(house: House, path: str, query: str = "") -> tuple[int, str]:
    status, body, _headers = call(house.app, "GET", path, query=query, cookie=house.cookie)
    return status, body


def _week(house: House, query: str = "") -> dict:
    status, body = _get(house, WEEK, query)
    assert status == 200, body
    return json.loads(body)


def _check(house: House, add: str, mode: str, directories: dict | None = None) -> tuple[int, dict]:
    return _post(house, WEEK, {"rows": [], "add": add, "mode": mode, **({"directories": directories} if directories else {})})


def _files(house: House, folder: str) -> list[str]:
    directory = house.data / "spelling" / folder
    return sorted(child.name for child in directory.iterdir()) if directory.is_dir() else []


# The pull-downs' directories


def test_the_page_lists_every_directory_under_spelling_in_name_order_without_hidden_ones(house):
    for folder in ("year-3/current", "Year-4", ".trash/old", "year-3/.backup"):
        (house.data / "spelling" / folder).mkdir(parents=True)
    (house.data / "spelling" / "notes.txt").write_text("not a directory", encoding="utf-8")
    spelling_page = house.page()["spelling"]
    assert spelling_page["folders"] == ["alphabet", "attic", "current", "revision", "year-3", "year-3/current", "Year-4"]
    assert spelling_page["directories"] == {
        "current_dir": "spelling/current",
        "revision_dir": "spelling/revision",
        "attic_dir": "spelling/attic",
        "alphabet_dir": "spelling/alphabet",
    }


def test_a_directory_set_by_hand_is_shown_as_its_path_from_the_data_directory(house):
    house.policy.write_text(HOUSE.replace("timeout: 30s", "timeout: 30s\n        attic_dir: spelling/old-words/"), encoding="utf-8")
    assert house.page()["spelling"]["directories"]["attic_dir"] == "spelling/old-words"


# Making a directory


def test_a_new_directory_is_made_at_once_with_its_parents_and_listed(kept):
    status, body = _make(kept, "  year-3/current ")
    assert status == 200, body
    assert body["directory"] == "year-3/current"
    assert (kept.data / "spelling/year-3/current").is_dir()
    assert "year-3" in body["folders"] and "year-3/current" in body["folders"]
    assert "year-3/current" in kept.page()["spelling"]["folders"]
    assert len(kept.log()) == 1
    assert kept.policy.read_text(encoding="utf-8") == HOUSE


def test_a_new_directory_inside_an_existing_one_keeps_its_name_as_the_disk_has_it(house):
    (house.data / "spelling/Year-3").mkdir()
    status, body = _make(house, "year-3/revision")
    assert (status, body["directory"]) == (200, "Year-3/revision")
    assert (house.data / "spelling/Year-3/revision").is_dir()


@pytest.mark.parametrize(
    ("name", "error"),
    [
        ("", spelling_directories.NO_NAME),
        ("   ", spelling_directories.NO_NAME),
        ("/year-3", spelling_directories.SLASHES),
        ("year-3/", spelling_directories.SLASHES),
        ("year-3//current", spelling_directories.SLASHES),
        ("year-3/cur*ent", spelling_directories.CHARACTERS),
        ("..", spelling_directories.DOT),
        ("year-3/.hidden", spelling_directories.DOT),
        ("year 3 /current", spelling_directories.SPACE),
        ("year-3/ current", spelling_directories.SPACE),
        ("x" * 256, spelling_directories.TOO_LONG),
        ("Current", "`current` already exists."),
        ("NOTES.txt", "`notes.txt` already exists."),
        ("notes.txt/words", "`notes.txt` is a file, so it cannot hold a directory."),
    ],
)
def test_a_name_the_rules_refuse_says_why_and_makes_nothing(house, name, error):
    (house.data / "spelling/notes.txt").write_text("", encoding="utf-8")
    before = spelling_directories.folders(house.data)
    assert _make(house, name) == (400, {"error": error})
    assert spelling_directories.folders(house.data) == before


def test_a_name_may_have_letters_of_any_language_digits_spaces_and_dots(house):
    status, body = _make(house, "année 3/term.2")
    assert (status, body["directory"]) == (200, "année 3/term.2")


def test_a_new_task_can_make_a_directory_and_another_type_of_task_cannot(house):
    assert _make(house, "year-5", "/parent/api/new-task/directories")[0] == 200
    assert (house.data / "spelling/year-5").is_dir()
    status, body = _make(house, "year-6", "/parent/api/tasks/worksheet/sums/directories")
    assert status == 400 and "not a spelling task" in body["error"]


def test_making_a_directory_needs_a_session_and_a_json_post(house):
    for path in (f"{TASK}/directories", "/parent/api/new-task/directories"):
        status, _body, headers = call(house.app, "POST", path, json_body={"name": "year-3"})
        assert status == 401 and "location" not in headers
        assert call(house.app, "POST", path, body=b"name=year-3", content_type="application/x-www-form-urlencoded", cookie=house.cookie)[0] == 415
    assert not (house.data / "spelling/year-3").exists()


# Saving the directories


def test_saving_writes_a_changed_directory_and_removes_one_set_back_to_its_default(kept):
    _words_in(kept, "year-3/revision", "newt")
    status, body = kept.save(directories={"revision_dir": "spelling/year-3/revision"})
    assert status == 200, body
    assert "        revision_dir: spelling/year-3/revision\n" in kept.policy.read_text(encoding="utf-8")
    assert kept.task().document()["revision_dir"] == "spelling/year-3/revision"
    assert kept.log()[0].endswith(" ada: saved task spelling/spelling")
    assert {word["key"]: word["pool"] for word in kept.page()["spelling"]["words"]}["newt"] == "revision"
    status, body = kept.save(directories={"revision_dir": "spelling/revision"})
    assert status == 200, body
    assert "revision_dir" not in kept.policy.read_text(encoding="utf-8")


def test_a_directory_with_a_space_is_written_quoted(house):
    _words_in(house, "year 3", "fish")
    (house.data / "spelling/revision/fish.wav").unlink()
    assert house.save(directories={"revision_dir": "spelling/year 3"})[0] == 200
    assert '        revision_dir: "spelling/year 3"\n' in house.policy.read_text(encoding="utf-8")


def test_choosing_the_saved_directory_again_changes_nothing(house):
    assert house.save(directories={"current_dir": "spelling/current"})[1]["message"] == "Nothing has changed, so nothing was saved."


def test_two_fields_on_one_directory_are_refused(house):
    status, body = house.save(directories={"revision_dir": "spelling/current"})
    assert (status, body) == (400, {"error": "current_dir and revision_dir are the same directory."})
    assert house.policy.read_text(encoding="utf-8") == HOUSE


def test_two_new_empty_pools_are_refused_with_their_empty_word_lists(house):
    for name in ("year-4/current", "year-4/revision"):
        assert _make(house, name)[0] == 200
    status, body = house.save(directories={"current_dir": "spelling/year-4/current", "revision_dir": "spelling/year-4/revision"})
    assert status == 400
    assert any("revision_required" in problem for problem in body["errors"])
    assert [(word["key"], word["pool"]) for word in body["spelling"]["words"]] == [("owl", "attic")]
    assert house.policy.read_text(encoding="utf-8") == HOUSE


def test_a_refused_directory_change_lists_the_words_in_the_new_directories_and_saves_a_pool_change_with_them(house):
    house.policy.write_text(HOUSE.replace("revision_required: 1", "revision_required: 2"), encoding="utf-8")
    _words_in(house, "year-3/current", "frog", "toad")
    _words_in(house, "year-3/revision", "newt")
    directories = {"current_dir": "spelling/year-3/current", "revision_dir": "spelling/year-3/revision"}
    status, body = house.save(directories=directories)
    assert status == 400
    assert any("revision_required" in problem for problem in body["errors"])
    shown = {word["key"]: word["pool"] for word in body["spelling"]["words"]}
    assert shown == {"frog": "current", "toad": "current", "newt": "revision", "owl": "attic"}
    status, body = house.save(directories=directories, moves={"toad": "revision"})
    assert status == 200, body
    assert _files(house, "year-3/revision") == ["newt.wav", "toad.wav"]
    assert house.task().document()["current_dir"] == "spelling/year-3/current"


def test_a_refused_save_without_a_directory_change_carries_no_word_list(house):
    status, body = house.save(fields={"max_passes": "-1"})
    assert status == 400 and "spelling" not in body


def test_the_recordings_play_from_directories_the_page_has_not_saved(house):
    _words_in(house, "year-3", "frog")
    status, body = _get(house, f"{TASK}/audio/current/frog.wav", "current_dir=spelling%2Fyear-3")
    assert status == 200 and body.startswith("RIFF")
    assert _get(house, f"{TASK}/audio/current/frog.wav")[0] == 404
    assert _get(house, f"{TASK}/audio/current/frog.wav", "current_dir=..%2Fspelling%2Fyear-3")[0] == 404
    assert _get(house, "/parent/api/new-task/audio/current/frog.wav", "current_dir=spelling%2Fyear-3")[0] == 200


# The setup's modes


def test_add_to_current_moves_listed_words_in_and_leaves_the_rest(house):
    _words_in(house, "revision", "newt")
    assert _check(house, "frog\nfish\ncat", week.ADD_CURRENT)[0] == 200
    _keep(house, ("frog", "word"))
    status, body = _post(house, f"{WEEK}/apply", {"mode": week.ADD_CURRENT})
    assert status == 200, body
    assert body["message"] == "Added 3 words to current, 1 of them moved from revision."
    assert _files(house, "current") == ["cat.wav", "dog.wav", "fish.wav", "frog.opus", "rope.sentence.wav", "rope.wav"]
    assert _files(house, "revision") == ["newt.wav"]
    assert _files(house, "attic") == ["owl.wav"]


def test_add_to_revision_moves_a_listed_current_word_there_and_writes_new_clips_there(house):
    assert _check(house, "frog\nrope\nowl", week.ADD_REVISION)[0] == 200
    _keep(house, ("frog", "word"), ("rope", "sentence"))
    status, body = _post(house, f"{WEEK}/apply", {"mode": week.ADD_REVISION})
    assert status == 200, body
    assert body["message"] == "Added 3 words to revision, 1 of them moved from current and 1 from the attic."
    assert _files(house, "revision") == ["fish.wav", "frog.opus", "owl.wav", "rope.sentence.opus", "rope.wav"]
    assert _files(house, "current") == ["cat.wav", "dog.wav"]


def test_adding_only_new_words_says_so_plainly(house):
    _check(house, "frog", week.ADD_REVISION)
    _keep(house, ("frog", "word"))
    assert _post(house, f"{WEEK}/apply", {})[1]["message"] == "Added 1 word to revision."


def test_the_task_page_names_the_setup_in_progress(house):
    assert house.page()["spelling"]["setup"] is None
    _check(house, "frog\ntoad", week.ADD_REVISION)
    assert house.page()["spelling"]["setup"] == {"mode": week.ADD_REVISION, "count": 2}


def test_another_mode_shows_the_setup_in_progress_and_cannot_change_it(house):
    _check(house, "frog\ntoad", week.REPLACE_CURRENT)
    page = _week(house, "mode=add-revision")
    assert (page["mode"], page["setup"], page["words"]) == ("add-revision", {"mode": "replace-current", "count": 2}, [])
    assert _check(house, "newt", week.ADD_REVISION) == (409, {"error": week.OTHER_SETUP})
    assert _post(house, f"{WEEK}/apply", {"mode": week.ADD_REVISION}) == (409, {"error": week.OTHER_SETUP})
    take, clips = _take(house, 1)
    status, _body = _post(house, f"{WEEK}/recordings", {"mode": week.ADD_REVISION, "take": take, "clips": [{"word": "frog", "kind": "word", "clip": clips[0]}]})
    assert status == 409
    assert [word["key"] for word in _week(house, "mode=replace-current")["words"]] == ["frog", "toad"]
    assert _get(house, WEEK, "mode=sideways")[0] == 404


def test_a_setup_kept_before_modes_is_replace_current(house):
    folder = house.data / week.DIRECTORY / "spelling"
    folder.mkdir(parents=True)
    (folder / week.STATE).write_text(json.dumps({"words": [{"key": "cat", "sentence": "", "clips": {}}]}), encoding="utf-8")
    assert house.page()["spelling"]["setup"] == {"mode": week.REPLACE_CURRENT, "count": 1}
    status, body = _post(house, f"{WEEK}/apply", {})
    assert status == 200, body
    assert body["message"] == "Applied the new week: 1 word is current, and 2 went to revision."


# Setting up words in new directories


def test_a_setup_started_with_new_directories_keeps_them_and_works_against_them(house):
    _words_in(house, "year-4/current", "lion")
    page = _week(house, "mode=replace-current&current_dir=spelling%2Fyear-4%2Fcurrent")
    assert page["directories"]["current_dir"] == "spelling/year-4/current"
    assert page["saved_directories"]["current_dir"] == "spelling/current"
    assert page["current"] == 1
    assert _check(house, "rope\nlion", week.REPLACE_CURRENT, {"current_dir": "spelling/year-4/current"})[0] == 200
    words = {word["key"]: word["pool"] for word in _week(house, "mode=replace-current")["words"]}
    assert words == {"rope": None, "lion": "current"}
    later = _week(house, "mode=replace-current&current_dir=spelling%2Felsewhere")
    assert later["directories"]["current_dir"] == "spelling/year-4/current"


def test_apply_writes_the_setups_directories_with_the_words_in_one_commit(kept):
    for name in ("year-4/current", "year-4/revision"):
        _make(kept, name)
    directories = {"current_dir": "spelling/year-4/current", "revision_dir": "spelling/year-4/revision"}
    assert _check(kept, "frog\ntoad", week.ADD_CURRENT, directories)[0] == 200
    _keep(kept, ("frog", "word"), ("toad", "word"))
    page = _week(kept)
    status, body = _post(kept, f"{WEEK}/apply", {"mode": week.ADD_CURRENT, "version": page["version"]})
    assert status == 400
    assert any("revision_required" in problem for problem in body["errors"])
    assert _files(kept, "year-4/current") == []
    status, body = _post(kept, f"{WEEK}/apply", {"mode": week.ADD_CURRENT, "version": page["version"], "settings": {"revision_required": "0"}})
    assert status == 200, body
    assert body["message"].startswith("Saved spelling.") and body["message"].endswith("Added 2 words to current.")
    assert _files(kept, "year-4/current") == ["frog.opus", "toad.opus"]
    document = kept.task().document()
    assert (document["current_dir"], document["revision_dir"], document["revision_required"]) == (
        "spelling/year-4/current",
        "spelling/year-4/revision",
        0,
    )
    assert len(kept.log()) == 2
    assert _files(kept, "current") == ["cat.wav", "dog.wav", "rope.sentence.wav", "rope.wav"]


def test_a_new_task_fills_its_new_directories_with_two_setups_and_then_saves(kept):
    new = "/parent/api/tasks/spelling/More Spelling/week"
    directories = {"current_dir": "spelling/more/current", "revision_dir": "spelling/more/revision", "attic_dir": "spelling/more/attic"}
    for name in ("more/current", "more/revision"):
        assert _make(kept, name, "/parent/api/new-task/directories")[0] == 200
    created = {"type": "spelling", "name": "More Spelling", "groups": ["younger"], "settings": {"revision_required": "1"}, "directories": directories}
    status, body = _post(kept, "/parent/api/new-task", created)
    assert status == 400 and body["spelling"]["words"] == []

    page = json.loads(_get(kept, new, "mode=add-current&current_dir=spelling%2Fmore%2Fcurrent")[1])
    assert (page["written"], page["file"], page["directories"]["current_dir"]) == (False, "", "spelling/more/current")
    for mode, word, folder in ((week.ADD_CURRENT, "frog", "more/current"), (week.ADD_REVISION, "newt", "more/revision")):
        status, body = _post(kept, new, {"rows": [], "add": word, "mode": mode, "directories": directories})
        assert status == 200, body
        take, clips = _take(kept, 1)
        assert _post(kept, f"{new}/recordings", {"mode": mode, "take": take, "clips": [{"word": word, "kind": "word", "clip": clips[0]}]})[0] == 200
        pending = json.loads(_get(kept, new, f"mode={mode}")[1])["words"][0]["kept"]["word"]
        assert _get(kept, f"{new}/clips/{pending}")[0] == 200
        status, body = _post(kept, f"{new}/apply", {"mode": mode})
        assert status == 200, body
        assert body["message"] == f"Added 1 word to {'current' if mode == week.ADD_CURRENT else 'revision'}. Save the new task to use them."
        assert _files(kept, folder) == [f"{word}.opus"]
    assert len(kept.log()) == 1
    assert not (kept.config / "tasks.d").exists()

    status, body = _post(kept, "/parent/api/new-task", created)
    assert status == 200, body
    assert kept.task("spelling/More Spelling").document()["current_dir"] == "spelling/more/current"


def test_a_setup_for_a_task_that_is_not_written_needs_a_name_a_task_could_have(house):
    status, body = _post(house, "/parent/api/tasks/spelling/ spaced/week", {"rows": [], "add": "frog"})
    assert status == 400 and "space" in body["error"]
    assert _post(house, "/parent/api/tasks/worksheet/nothing/week", {"rows": [], "add": "frog"})[0] == 404


def test_cancel_leaves_the_tasks_directories_as_the_file_has_them(house):
    _make(house, "year-4")
    _check(house, "frog", week.ADD_CURRENT, {"current_dir": "spelling/year-4"})
    assert _post(house, f"{WEEK}/cancel", {})[0] == 200
    assert house.policy.read_text(encoding="utf-8") == HOUSE
    assert house.page()["spelling"]["setup"] is None


def test_a_setup_refuses_directories_that_leave_the_data_directory_or_share_one(house):
    assert _check(house, "frog", week.ADD_CURRENT, {"current_dir": "/etc"})[0] == 400
    assert _check(house, "frog", week.ADD_CURRENT, {"revision_dir": "spelling/current"}) == (
        400,
        {"error": "current_dir and revision_dir are the same directory."},
    )
    assert _get(house, WEEK, "current_dir=..%2Fconfig")[0] == 400
