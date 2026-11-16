"""S031.2: Asset Administration's parts of speech pool pages, through the portal's data endpoints."""

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from asgi import call  # noqa: E402
from test_task_admin import HOUSE, House, _git  # noqa: E402

from policy import check  # noqa: E402
from policy.parts_of_speech import check_body  # noqa: E402
from policy.sentence_pools import pools_directory, write_pool  # noqa: E402

API = "/parent/api/parts-of-speech-pools"
FOX = "The quick, brown fox jumped over the lazy dog."
DRY = "Dry the dishes with a dry towel."
POOL = "words sentences"
SENTENCES = [
    {"sentence": FOX, "parts": {"noun": ["dog", "fox"], "verb": ["jumped"], "Adjectives": ["quick", "brown", "lazy"]}},
    {"sentence": DRY, "level_of_difficulty": 2, "parts": {"verb": ["dry[1]"], "noun": ["dishes", "towel"], "adjective": ["dry[2]"]}},
]
TASKS = """\
  parts_of_speech:
    words:
      group: younger
      body:
        timeout: 60s
        pools: [words sentences]
    more words:
      group: younger
      body:
        pools: [other, words sentences]
"""
TEXT = HOUSE + TASKS


def _pools(config: Path) -> None:
    directory = pools_directory(config)
    write_pool(directory, "words-sentences", POOL, SENTENCES)
    write_pool(directory, "other", "other", [{"sentence": "The cat sat.", "parts": {"noun": ["cat"]}}])


class Pools(House):
    def pools(self) -> list[dict]:
        status, body = self.get(API)
        assert status == 200, body
        return body["pools"]

    def pool(self, pool_id: str) -> dict:
        status, body = self.get(f"{API}/{pool_id}")
        assert status == 200, body
        return body

    def post(self, path: str, body: dict) -> tuple[int, dict]:
        status, answer, _headers = call(self.app, "POST", path, json_body=body, cookie=self.cookie)
        return status, json.loads(answer)

    def save_pool(self, pool_id: str, **changes) -> tuple[int, dict]:
        changes.setdefault("version", self.pool(pool_id)["version"])
        return self.post(f"{API}/{pool_id}", changes)

    def file(self, pool_id: str) -> Path:
        return pools_directory(self.config) / f"{pool_id}.yaml"

    def text(self, pool_id: str) -> str:
        return self.file(pool_id).read_text(encoding="utf-8")


@pytest.fixture
def house(tmp_path, monkeypatch):
    return Pools(tmp_path, monkeypatch, text=TEXT, before=_pools)


@pytest.fixture
def kept(tmp_path, monkeypatch):
    return Pools(tmp_path, monkeypatch, history=True, text=TEXT, before=_pools)


def _sent(page: dict) -> list[dict]:
    """The sentences as the page has them, in the form a save sends them back."""
    return [{"origin": index, **sentence} for index, sentence in enumerate(page["sentences"])]


# Sessions


def test_the_data_addresses_answer_401_without_a_session_and_never_redirect(house):
    for method, path in (("GET", API), ("GET", f"{API}/other"), ("POST", API), ("POST", f"{API}/other"),
                         ("POST", f"{API}/other/rename"), ("POST", f"{API}/other/delete")):
        status, body, headers = call(house.app, method, path, json_body={} if method == "POST" else None, cookie=None)
        assert status == 401, (method, path)
        assert "location" not in headers


def test_a_change_must_be_sent_as_json(house):
    status, _body, _headers = call(house.app, "POST", API, body=b"name=x", content_type="application/x-www-form-urlencoded", cookie=house.cookie)
    assert status == 415


# The list


def test_the_list_shows_every_pool_by_name_with_its_difficulty_and_sentence_count(house):
    write_pool(pools_directory(house.config), "unused", "Year 3 basics", [{"sentence": "Go.", "parts": {"verb": ["Go"]}}], difficulty=1.5)
    assert house.pools() == [
        {"id": "other", "name": "other", "level_of_difficulty": "", "sentences": 1},
        {"id": "words-sentences", "name": POOL, "level_of_difficulty": "", "sentences": 2},
        {"id": "unused", "name": "Year 3 basics", "level_of_difficulty": "1.5", "sentences": 1},
    ]


# Creating


def test_create_makes_an_empty_pool_at_once_and_it_is_listed(kept):
    status, body = kept.post(API, {"name": "  Year 3 basics "})
    assert status == 200, body
    assert body["pool"] == {"id": "year-3-basics", "name": "Year 3 basics"}
    assert kept.text("year-3-basics") == "name: Year 3 basics\nsentences: []\n"
    assert {"id": "year-3-basics", "name": "Year 3 basics", "level_of_difficulty": "", "sentences": 0} in kept.pools()
    assert kept.log()[0].endswith(" ada: made parts of speech pool Year 3 basics")
    assert check.main(["--quiet"]) == 0


@pytest.mark.parametrize(("name", "says"), [("WORDS Sentences", "A pool named words sentences already exists."), ("  ", "Give the pool a name."), ("a\nb", "one line")])
def test_create_refuses_a_name_that_clashes_or_is_empty(house, name, says):
    before = sorted(path.name for path in pools_directory(house.config).iterdir())
    status, body = house.post(API, {"name": name})
    assert status == 400
    assert says in body["error"]
    assert sorted(path.name for path in pools_directory(house.config).iterdir()) == before


def test_a_new_pool_named_by_a_hand_written_task_must_have_sentences_before_the_check_passes(house):
    """S031.1's empty-pool rule still holds: a task may name the new pool only once it has sentences."""
    assert house.post(API, {"name": "Year 3 basics"})[0] == 200
    house.policy.write_text(TEXT.replace("pools: [other, words sentences]", "pools: [Year 3 basics]"), encoding="utf-8")
    assert check.main(["--quiet"]) != 0
    sentence = {"origin": None, "text": "The cat sat.", "level_of_difficulty": "", "parts": [{"name": "noun", "words": [1]}, {"name": "verb", "words": [2]}]}
    house.policy.write_text(TEXT, encoding="utf-8")
    status, body = house.save_pool("year-3-basics", level_of_difficulty="", sentences=[sentence])
    assert status == 200, body
    house.policy.write_text(TEXT.replace("pools: [other, words sentences]", "pools: [Year 3 basics]"), encoding="utf-8")
    assert check.main(["--quiet"]) == 0


# The page


def test_the_page_shows_the_name_difficulty_and_each_sentence_with_its_rows(house):
    page = house.pool("words-sentences")
    assert (page["name"], page["level_of_difficulty"], page["problems"]) == (POOL, "", [])
    assert page["tasks"] == ["more words", "words"]
    assert page["sentences"] == [
        {"text": FOX, "level_of_difficulty": "", "parts": [
            {"name": "noun", "words": [3, 8]}, {"name": "verb", "words": [4]}, {"name": "Adjectives", "words": [1, 2, 7]},
        ]},
        {"text": DRY, "level_of_difficulty": "2", "parts": [
            {"name": "verb", "words": [0]}, {"name": "noun", "words": [2, 6]}, {"name": "adjective", "words": [5]},
        ]},
    ]


@pytest.mark.parametrize("pool_id", ["nothing", "../policy", "Other"])
def test_an_unknown_pool_is_404(house, pool_id):
    assert house.get(f"{API}/{pool_id}")[0] == 404


# Saving


def test_a_save_with_nothing_changed_writes_nothing(house):
    before = house.text("words-sentences")
    page = house.pool("words-sentences")
    status, body = house.save_pool("words-sentences", level_of_difficulty="", sentences=_sent(page))
    assert (status, body["message"]) == (200, "Nothing has changed, so nothing was saved.")
    assert house.text("words-sentences") == before


def test_only_the_changed_sentence_is_written_again_with_tidied_names(kept):
    before = kept.text("words-sentences")
    sentences = _sent(kept.pool("words-sentences"))
    sentences[1]["parts"] = [
        {"name": "Verbs", "words": [0]},
        {"name": "Nouns", "words": [6]},
        {"name": "noun", "words": [2]},
        {"name": "Proper Nouns", "words": [5]},
    ]
    status, body = kept.save_pool("words-sentences", sentences=sentences)
    assert status == 200, body
    after = kept.text("words-sentences")
    first = before[: before.index("- sentence: Dry")]
    assert after.startswith(first)
    assert yaml.safe_load(after)["sentences"][1] == {
        "sentence": DRY,
        "level_of_difficulty": 2,
        "parts": {"verb": ["Dry"], "noun": ["dishes", "towel"], "proper noun": ["dry[2]"]},
    }
    assert kept.log()[0].endswith(" ada: saved parts of speech pool words sentences")
    assert _git(kept.config, "status", "--porcelain") == ""


def test_a_new_sentence_is_added_and_a_deleted_one_removed(house):
    sentences = _sent(house.pool("words-sentences"))[1:] + [
        {"origin": None, "text": "Yes, the cat sat on the mat.", "level_of_difficulty": "", "parts": [
            {"name": "interjection", "words": [0]}, {"name": "noun", "words": [2, 6]},
        ]},
    ]
    status, body = house.save_pool("words-sentences", sentences=sentences)
    assert status == 200, body
    written = yaml.safe_load(house.text("words-sentences"))["sentences"]
    assert [sentence["sentence"] for sentence in written] == [DRY, "Yes, the cat sat on the mat."]
    assert written[1] == {"sentence": "Yes, the cat sat on the mat.", "parts": {"interjection": ["Yes"], "noun": ["cat", "mat"]}}


def test_difficulty_is_written_only_when_it_differs_from_the_default_or_the_pool(house):
    sentences = _sent(house.pool("words-sentences"))
    sentences[0]["level_of_difficulty"] = "1.5"
    sentences[1]["level_of_difficulty"] = "3"
    sentences.append({"origin": None, "text": "Go now.", "level_of_difficulty": "1.5", "parts": [{"name": "verb", "words": [0]}]})
    status, body = house.save_pool("words-sentences", level_of_difficulty="1.5", sentences=sentences)
    assert status == 200, body
    assert house.text("words-sentences").startswith(f"name: {POOL}\nlevel_of_difficulty: 1.5\nsentences:\n")
    written = yaml.safe_load(house.text("words-sentences"))
    assert written["level_of_difficulty"] == 1.5
    assert "level_of_difficulty" not in written["sentences"][0]
    assert written["sentences"][1]["level_of_difficulty"] == 3
    assert "level_of_difficulty" not in written["sentences"][2]

    status, body = house.save_pool("words-sentences", level_of_difficulty="1")
    assert status == 200, body
    assert "level_of_difficulty" not in yaml.safe_load(house.text("words-sentences"))


@pytest.mark.parametrize("typed", ["0.4", "10.5", "abc", "nan"])
def test_a_difficulty_out_of_range_is_refused_and_nothing_is_written(house, typed):
    before = house.text("words-sentences")
    status, body = house.save_pool("words-sentences", level_of_difficulty=typed)
    assert status == 400
    assert "level_of_difficulty" in body["error"]
    sentences = _sent(house.pool("words-sentences"))
    sentences[0]["level_of_difficulty"] = typed
    status, body = house.save_pool("words-sentences", sentences=sentences)
    assert status == 400
    assert "sentence 1: level_of_difficulty" in body["error"]
    assert house.text("words-sentences") == before


def test_no_sentences_is_refused(house):
    status, body = house.save_pool("words-sentences", sentences=[])
    assert (status, body["error"]) == (400, "There are no sentences. Add at least one.")


def test_a_save_that_leaves_a_task_unable_to_load_is_refused(house):
    """A task asking for more correct answers than the pool would hold is checked with the new pool in place."""
    house.policy.write_text(TEXT.replace("        timeout: 60s\n", "        correct_answers_required: 3\n").replace("pools: [other, words sentences]", "pools: [other]"), encoding="utf-8")
    assert check.main(["--quiet"]) != 0  # 3 required from 2 sentences
    house.policy.write_text(TEXT.replace("        timeout: 60s\n", "        correct_answers_required: 2\n"), encoding="utf-8")
    before = house.text("words-sentences")
    sentences = _sent(house.pool("words-sentences"))[:1]
    status, body = house.save_pool("words-sentences", sentences=sentences)
    assert status == 400
    assert any("correct_answers_required" in problem for problem in body["errors"])
    assert house.text("words-sentences") == before


def test_an_unused_pool_is_checked_as_the_load_would(house):
    sentences = _sent(house.pool("other")) + [{"origin": None, "text": "!!", "level_of_difficulty": "", "parts": [{"name": "noun", "words": []}]}]
    status, body = house.save_pool("other", sentences=sentences)
    assert status == 400
    assert any("at least one word" in problem for problem in body["errors"])


def test_a_hand_edit_since_the_page_opened_refuses_the_save(house):
    version = house.pool("other")["version"]
    house.file("other").write_text(house.text("other").replace("The cat sat.", "The dog sat."), encoding="utf-8")
    status, body = house.save_pool("other", version=version, level_of_difficulty="2")
    assert status == 409
    assert "The dog sat." in house.text("other")


def test_the_next_run_uses_the_saved_difficulty(house):
    status, body = house.save_pool("words-sentences", level_of_difficulty="1.5")
    assert status == 200, body
    settings = check_body(house.task("parts_of_speech/words").document(), house.config)
    assert sorted(sentence.difficulty for sentence in settings.sentences) == [1.5, 2.0]


# Renaming


def test_rename_changes_the_name_and_every_task_that_lists_it(kept):
    status, body = kept.post(f"{API}/words-sentences/rename", {"name": "Year 3 basics", "version": kept.pool("words-sentences")["version"]})
    assert status == 200, body
    assert body["pool"] == {"id": "words-sentences", "name": "Year 3 basics"}
    assert body["message"].startswith("Renamed words sentences to Year 3 basics. Changed the name in more words, words too.")
    assert yaml.safe_load(kept.text("words-sentences"))["name"] == "Year 3 basics"
    tasks = yaml.safe_load(kept.policy.read_text(encoding="utf-8"))["tasks"]["parts_of_speech"]
    assert tasks["words"]["body"]["pools"] == ["Year 3 basics"]
    assert tasks["more words"]["body"]["pools"] == ["other", "Year 3 basics"]
    assert kept.task("parts_of_speech/words").document()["pools"] == ["Year 3 basics"]
    assert check.main(["--quiet"]) == 0
    assert kept.log()[0].endswith(" ada: renamed parts of speech pool words sentences to Year 3 basics")
    assert _git(kept.config, "status", "--porcelain") == ""


def test_rename_refuses_a_name_another_pool_has(house):
    status, body = house.post(f"{API}/words-sentences/rename", {"name": "OTHER", "version": house.pool("words-sentences")["version"]})
    assert (status, body["error"]) == (400, "A pool named other already exists.")
    assert yaml.safe_load(house.text("words-sentences"))["name"] == POOL


# Deleting


def test_delete_is_refused_while_a_task_lists_the_pool(house):
    status, body = house.post(f"{API}/other/delete", {"version": house.pool("other")["version"]})
    assert status == 400
    assert "more words" in body["error"]
    assert house.file("other").exists()


def test_delete_removes_an_unused_pool(kept):
    write_pool(pools_directory(kept.config), "spare", "spare", [{"sentence": "Go.", "parts": {"verb": ["Go"]}}])
    _git(kept.config, "add", "--all")
    _git(kept.config, "commit", "--quiet", "-m", "spare")
    status, body = kept.post(f"{API}/spare/delete", {"version": kept.pool("spare")["version"]})
    assert status == 200, body
    assert not kept.file("spare").exists()
    assert "spare" not in [pool["id"] for pool in kept.pools()]
    assert kept.log()[0].endswith(" ada: deleted parts of speech pool spare")
    assert _git(kept.config, "status", "--porcelain") == ""
