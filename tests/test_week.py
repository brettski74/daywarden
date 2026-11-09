"""S023.4: setting up the new week's spelling words, recording them, and applying the list."""

import json
import os
import secrets
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from asgi import call  # noqa: E402
from conftest import write_wav  # noqa: E402
from test_task_admin import HOUSE, House  # noqa: E402
from policy import recordings, spelling, week  # noqa: E402

BEFORE = {
    "current": ["cat.wav", "dog.wav", "rope.sentence.wav", "rope.wav"],
    "revision": ["fish.wav"],
    "attic": ["owl.wav"],
}


@pytest.fixture
def house(tmp_path, monkeypatch):
    return House(tmp_path, monkeypatch)


@pytest.fixture
def kept(tmp_path, monkeypatch):
    return House(tmp_path, monkeypatch, history=True)


def _post(house: House, path: str, body: dict) -> tuple[int, dict]:
    status, text, _headers = call(house.app, "POST", f"/parent/api/tasks/spelling/week{path}", json_body=body, cookie=house.cookie)
    return status, json.loads(text)


def _page(house: House) -> dict:
    status, body = house.get("/parent/api/tasks/spelling/week")
    assert status == 200, body
    return body


def _words(house: House) -> dict[str, dict]:
    return {word["key"]: word for word in _page(house)["words"]}


def _save(house: House, add: str = "", rows: list[dict] | None = None) -> tuple[int, dict]:
    return _post(house, "", {"rows": rows or [], "add": add})


def _rows(house: House) -> list[dict]:
    return [{"from": word["key"], "key": word["key"], "sentence": word["sentence"]} for word in _page(house)["words"]]


def _take(house: House, count: int) -> tuple[str, list[str]]:
    """A take already cut into ``count`` clips, as the recording dialog leaves it."""
    take = secrets.token_urlsafe(12)
    for number in range(1, count + 1):
        write_wav(house.data / recordings.DIRECTORY / take / f"abcdef-{number}.opus", 400 + number * 100)
    return take, [f"abcdef-{number}" for number in range(1, count + 1)]


def _keep(house: House, *kept: tuple[str, str]) -> tuple[int, dict]:
    """Keep one clip for each (word, kind)."""
    take, clips = _take(house, len(kept))
    return _post(house, "/recordings", {"take": take, "clips": [{"word": key, "kind": kind, "clip": clip} for (key, kind), clip in zip(kept, clips)]})


def _pools(house: House) -> dict[str, list[str]]:
    return {pool: house.files(pool) for pool in spelling.ALL_POOLS}


def _setup(house: House) -> list[str]:
    folder = house.data / week.DIRECTORY / "spelling"
    return sorted(str(path.relative_to(folder)) for path in folder.rglob("*") if path.is_file()) if folder.is_dir() else []


def _apply(house: House, **body) -> tuple[int, dict]:
    return _post(house, "/apply", body)


# Entering the list


def test_a_new_setup_is_empty_and_the_pools_are_untouched(house):
    page = _page(house)
    assert page["words"] == []
    assert page["targets"] == {"current_required": "", "revision_required": "1"}
    assert page["current"] == 3


def test_checking_the_list_shows_where_each_word_is_and_its_clips(house):
    status, body = _save(house, "frog\n  toad  \n\nnewt\nrope\nfish\nOWL\n")
    assert status == 200, body
    assert body["message"] == "Saved the week's list of 6 words."
    words = _page(house)["words"]
    assert [(word["key"], word["pool"], word["clip"], word["sentence_clip"]) for word in words] == [
        ("frog", None, None, None),
        ("toad", None, None, None),
        ("newt", None, None, None),
        ("rope", "current", "rope.wav", "rope.sentence.wav"),
        ("fish", "revision", "fish.wav", None),
        ("owl", "attic", "owl.wav", None),
    ]
    assert _page(house)["needs"] == ["frog", "toad", "newt"]
    assert _pools(house) == BEFORE


def test_a_word_with_an_apostrophe_or_a_number_is_accepted(house):
    assert _save(house, "don't\nread.1\nwell-known")[0] == 200
    assert list(_words(house)) == ["don't", "read.1", "well-known"]


def test_words_that_are_not_words_or_are_listed_twice_are_refused_naming_the_line(house):
    status, body = _save(house, "frog\nrope2, two words\nFrog\nabcdefghijklmnopqrstuvw\nrope.sentence - cat;dog")
    assert status == 400
    assert body["error"] == week.REFUSED
    assert body["errors"] == [
        f'Line 2, "rope2": {week.NOT_A_WORD}.',
        'Line 3, "Frog": frog is already on the list.',
        'Line 4, "abcdefghijklmnopqrstuvw": it is longer than 22 characters.',
        f'Line 5, "rope.sentence": {week.NOT_A_WORD}.',
        f'Line 5, "-": {week.NOT_A_WORD}.',
        f'Line 5, "cat;dog": {week.NOT_A_WORD}.',
    ]
    assert _page(house)["words"] == []


def test_a_list_pasted_from_a_class_posting_splits_on_commas_and_loses_its_brackets(house):
    status, body = _save(house, "(frog, toad,newt,\n  rope ,,, \n\tdon\u2019t)")
    assert status == 200, body
    assert list(_words(house)) == ["frog", "toad", "newt", "rope", "don't"]


@pytest.mark.parametrize(
    ("text", "words"),
    [
        ("(rope, cat, dog)", ["rope", "cat", "dog"]),
        ("rope,,,\n cat", ["rope", "cat"]),
        ('"rope cat dog."', ["rope", "cat", "dog"]),
        ("1. rope", ["rope"]),
        ("(rope, read.1)", ["rope", "read.1"]),
        ("rope read.12.)", ["rope", "read.12"]),
        ("- 'tis well-known'", ["tis", "well-known"]),
        ("rope (cat) dog", ["rope", "(cat)", "dog"]),
        ("1. rope 2. cat", ["rope", "2.", "cat"]),
        ("  ,,( ) \n", []),
        ("", []),
    ],
)
def test_pasted_text_splits_on_commas_and_whitespace_and_is_trimmed_only_at_its_ends(text, words):
    assert [word for _line, word in week.split_words(text)] == words


def test_each_pasted_word_knows_its_line():
    assert week.split_words("(rope, cat\n\ndog,\nfish)") == [(1, "rope"), (1, "cat"), (3, "dog"), (4, "fish")]


def test_a_new_plain_word_beside_a_numbered_one_is_refused(house):
    status, body = _save(house, "lead\nlead.1")
    assert status == 400
    assert body["errors"] == ["lead and lead.1 are both on the list. Give lead a number too."]


def test_a_plain_word_with_numbered_meanings_in_the_pools_asks_which(house):
    write_wav(house.data / "spelling/revision/read.1.wav")
    write_wav(house.data / "spelling/attic/read.2.wav")
    assert _save(house, "read")[0] == 200
    page = _page(house)
    assert page["ambiguous"] == ["read"]
    word = page["words"][0]
    assert word["choices"] == [{"key": "read.1", "pool": "revision"}, {"key": "read.2", "pool": "attic"}]
    assert word["new_key"] == "read.3"
    _keep(house, ("read", "word"))
    status, body = _apply(house)
    assert status == 400
    assert body["error"] == "Choose which meaning of read belongs to the week, so nothing was applied."
    assert _save(house, rows=[{"from": "read", "key": "read.1", "sentence": ""}], add="read.2")[0] == 200
    assert _page(house)["ambiguous"] == []


def test_the_sentence_text_and_kept_clips_follow_an_edited_word_and_a_removed_word_drops_its_clips(house):
    _save(house, "read\nfrog")
    assert _keep(house, ("read", "word"), ("frog", "word"))[0] == 200
    frog_clip = _words(house)["frog"]["kept"]["word"]
    status, body = _save(house, rows=[{"from": "read", "key": "read.1", "sentence": "  I  read a   book. "}])
    assert status == 200, body
    words = _words(house)
    assert list(words) == ["read.1"]
    assert words["read.1"]["sentence"] == "I read a book."
    assert words["read.1"]["kept"]["word"] is not None
    assert frog_clip not in _setup(house)
    assert len([name for name in _setup(house) if name.endswith(".opus")]) == 1


def test_an_empty_list_is_no_setup(house):
    _save(house, "frog")
    assert _setup(house) == ["state.json"]
    assert _save(house)[1]["message"] == "The week's list is empty."
    assert _setup(house) == []


# Keeping clips


def test_kept_clips_stay_pending_and_the_pools_do_not_change(house):
    _save(house, "frog\nrope")
    status, body = _keep(house, ("frog", "word"), ("frog", "sentence"), ("rope", "word"))
    assert status == 200, body
    assert body["message"] == "Kept 3 clips for the new week. They go into the pools on Apply."
    words = _words(house)
    assert words["frog"]["kept"]["word"] and words["frog"]["kept"]["sentence"] and words["rope"]["kept"]["word"]
    assert _pools(house) == BEFORE
    assert len([name for name in _setup(house) if name.endswith(".opus")]) == 3
    assert not any((house.data / recordings.DIRECTORY).iterdir())


def test_keeping_a_clip_again_replaces_the_older_pending_one(house):
    _save(house, "frog")
    _keep(house, ("frog", "word"))
    first = _words(house)["frog"]["kept"]["word"]
    _keep(house, ("frog", "word"))
    second = _words(house)["frog"]["kept"]["word"]
    assert first != second
    assert [name for name in _setup(house) if name.endswith(".opus")] == [second]


def test_a_keep_for_a_word_not_on_the_list_or_a_clip_that_is_gone_keeps_nothing(house):
    _save(house, "frog")
    status, body = _keep(house, ("moon", "word"))
    assert status == 400
    assert "moon is not on the week's list" in body["error"]
    status, body = _post(house, "/recordings", {"take": "A" * 16, "clips": [{"word": "frog", "kind": "word", "clip": "abcdef-1"}]})
    assert (status, body) == (404, {"error": recordings.GONE})
    assert _words(house)["frog"]["kept"] == {"word": None, "sentence": None}


def test_a_pending_clip_plays_and_nothing_else_is_served(house):
    _save(house, "frog")
    _keep(house, ("frog", "word"))
    clip = _words(house)["frog"]["kept"]["word"]
    status, body, headers = call(house.app, "GET", f"/parent/api/tasks/spelling/week/clips/{clip}", cookie=house.cookie)
    assert status == 200
    assert headers["content-type"] == ["audio/ogg"]
    assert body.startswith("RIFF")
    for path in (f"/parent/api/tasks/spelling/week/clips/{week.STATE}", "/parent/api/tasks/sums/week/clips/" + clip, "/parent/api/tasks/spelling/week/clips/..%2Fstate.json"):
        assert call(house.app, "GET", path, cookie=house.cookie)[0] == 404, path


def test_every_week_address_needs_a_session_and_a_json_post(house):
    for method, path in [
        ("GET", "/parent/api/tasks/spelling/week"),
        ("POST", "/parent/api/tasks/spelling/week"),
        ("POST", "/parent/api/tasks/spelling/week/recordings"),
        ("POST", "/parent/api/tasks/spelling/week/cancel"),
        ("POST", "/parent/api/tasks/spelling/week/apply"),
        ("GET", "/parent/api/tasks/spelling/week/clips/abcdef01.opus"),
    ]:
        status, _body, headers = call(house.app, method, path, json_body={} if method == "POST" else None)
        assert status == 401, path
        assert "location" not in headers
        if method == "POST":
            assert call(house.app, "POST", path, body=b"add=frog", content_type="application/x-www-form-urlencoded", cookie=house.cookie)[0] == 415


def test_a_task_that_is_not_spelling_has_no_week(house):
    status, body = house.get("/parent/api/tasks/sums/week")
    assert status == 400
    assert "not a spelling task" in body["error"]


# Applying


def test_apply_is_refused_while_a_new_word_has_no_word_clip_and_names_it(house):
    _save(house, "frog\ntoad\nrope")
    _keep(house, ("frog", "sentence"))
    status, body = _apply(house)
    assert status == 400
    assert body["error"] == "These words still need a word clip, so nothing was applied: frog, toad."
    assert _pools(house) == BEFORE


def test_apply_makes_the_list_current_and_sends_last_week_to_revision(house):
    _save(house, "frog\nrope\nfish\nowl")
    rows = _rows(house)
    rows[0]["sentence"] = "The frog jumped."
    _save(house, rows=rows)
    _keep(house, ("frog", "word"), ("rope", "word"))
    status, body = _apply(house)
    assert status == 200, body
    assert body["message"] == "Applied the new week: 4 words are current, and 2 went to revision."
    assert _pools(house) == {
        "current": ["fish.wav", "frog.opus", "owl.wav", "rope.opus", "rope.sentence.wav"],
        "revision": ["cat.wav", "dog.wav"],
        "attic": [],
    }
    assert _setup(house) == []
    assert _page(house)["words"] == []
    pools = spelling.current_pools(spelling.parse_settings({"revision_required": 1}), house.data)
    assert [word.key for word in pools.current] == ["fish", "frog", "owl", "rope"]
    assert "frog jumped" not in house.policy.read_text(encoding="utf-8")
    assert not any("frog jumped" in path.read_bytes().decode("latin-1") for path in house.data.rglob("*") if path.is_file())


def test_a_new_sentence_replaces_the_old_one_of_a_current_word_in_any_format(house):
    _save(house, "rope\ncat")
    _keep(house, ("rope", "sentence"))
    assert _apply(house)[0] == 200
    assert house.files("current") == ["cat.wav", "rope.sentence.opus", "rope.wav"]
    assert house.files("revision") == ["dog.wav", "fish.wav"]


def test_a_new_numbered_meaning_gives_the_existing_plain_word_the_next_number(house):
    _save(house, "read.1\ncat\ndog")
    write_wav(house.data / "spelling/current/read.wav")
    write_wav(house.data / "spelling/current/read.sentence.wav")
    page = _page(house)
    assert page["needs"] == ["read.1"]
    assert page["words"][0]["renames"] == {"from": "read", "to": "read.2"}
    assert page["words"][1]["renames"] is None
    _keep(house, ("read.1", "word"))
    status, body = _apply(house)
    assert status == 200, body
    assert body["message"].endswith("The existing read is now read.2.")
    assert "read.1.opus" in house.files("current")
    assert "read.2.wav" in house.files("revision") and "read.2.sentence.wav" in house.files("revision")
    assert not any(name.startswith("read.") and name.count(".") == 1 for name in house.files("revision"))


def test_a_listed_plain_word_that_takes_a_number_stays_current_under_it(house):
    write_wav(house.data / "spelling/revision/lead.wav")
    _save(house, "lead\nlead.1\ncat")
    assert _words(house)["lead"]["becomes"] == "lead.2"
    _keep(house, ("lead.1", "word"), ("lead", "sentence"))
    assert _apply(house)[0] == 200
    assert house.files("current") == ["cat.wav", "lead.1.opus", "lead.2.sentence.opus", "lead.2.wav"]


def test_a_list_shorter_than_the_target_is_refused_until_the_target_is_lowered_in_the_same_step(kept):
    kept.policy.write_text(HOUSE.replace("timeout: 30s", "timeout: 30s\n      current_required: 3"), encoding="utf-8")
    _save(kept, "cat\ndog")
    status, body = _apply(kept)
    assert status == 400
    assert any("current_required" in problem and "only 2" in problem for problem in body["errors"])
    assert _pools(kept) == BEFORE
    assert _setup(kept) == ["state.json"]
    page = _page(kept)
    status, body = _apply(kept, version=page["version"], settings={"current_required": "2", "revision_required": "1"})
    assert status == 200, body
    assert body["message"].startswith("Saved spelling.")
    assert kept.task().document()["current_required"] == 2
    assert kept.files("current") == ["cat.wav", "dog.wav"]
    assert kept.log()[0].endswith(" ada: saved task spelling")


def test_a_target_change_on_a_file_edited_since_the_page_opened_is_refused(house):
    _save(house, "cat\ndog")
    version = _page(house)["version"]
    house.policy.write_text(HOUSE.replace("max_skips: 3", "max_skips: 4"), encoding="utf-8")
    status, body = _apply(house, version=version, settings={"current_required": "2"})
    assert status == 409
    assert _pools(house) == BEFORE


def test_a_failed_move_partway_moves_everything_back_and_keeps_the_setup(house, monkeypatch):
    _save(house, "frog\nrope")
    _keep(house, ("frog", "word"), ("rope", "word"))
    setup = _setup(house)
    real = os.rename
    calls = {"count": 0}

    def failing(source, target):
        calls["count"] += 1
        if calls["count"] == 3:
            raise OSError("disk trouble")
        real(source, target)

    monkeypatch.setattr(os, "rename", failing)
    status, body = _apply(house)
    assert status == 500
    assert body["error"].startswith("The new week could not be applied, and every file was moved back")
    assert _pools(house) == BEFORE
    assert _setup(house) == setup


def test_cancel_throws_the_setup_away_and_the_pools_stay_as_they_were(house):
    _save(house, "frog\nrope")
    _keep(house, ("frog", "word"), ("rope", "word"))
    status, body = _post(house, "/cancel", {})
    assert status == 200
    assert body["message"] == "Threw away the new week's setup. The pools have not changed."
    assert _setup(house) == []
    assert _pools(house) == BEFORE
    assert _page(house)["words"] == []


def test_an_empty_list_cannot_be_applied(house):
    status, body = _apply(house)
    assert (status, body["error"]) == (400, "There are no words on the week's list, so nothing was applied.")
