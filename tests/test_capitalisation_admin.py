"""S040.2: capitalisation pool pages and the capitalisation task page, through the portal's data endpoints."""

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
from policy.sentence_pools import CAPITALISATION_DIR, POOLS_DIR, pools_directory, write_pool  # noqa: E402

API = "/parent/api/capitalisation-pools"
TASKS = """\
  capitalisation:
    caps:
      group: younger
      body:
        pools: [Places]
    more caps:
      group: younger
      body:
        pools: [Other, Places]
"""


def _pools(config: Path) -> None:
    directory = pools_directory(config, CAPITALISATION_DIR)
    write_pool(directory, "places", "Places", ["Anna flew to Paris.", {"sentence": "We saw NASA in July.", "level_of_difficulty": 2}])
    write_pool(directory, "other", "Other", ["Bob ran."])
    write_pool(pools_directory(config, POOLS_DIR), "nouns", "Nouns", [{"sentence": "The cat sat.", "parts": {"noun": ["cat"]}}])


class Caps(House):
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

    def text(self, pool_id: str) -> str:
        return (pools_directory(self.config, CAPITALISATION_DIR) / f"{pool_id}.yaml").read_text(encoding="utf-8")


@pytest.fixture
def house(tmp_path, monkeypatch):
    return Caps(tmp_path, monkeypatch, text=HOUSE + TASKS, before=_pools)


@pytest.fixture
def kept(tmp_path, monkeypatch):
    return Caps(tmp_path, monkeypatch, history=True, text=HOUSE + TASKS, before=_pools)


def _sent(page: dict) -> list[dict]:
    return [{"origin": index, **sentence} for index, sentence in enumerate(page["sentences"])]


def test_the_data_addresses_answer_401_without_a_session(house):
    for method, path in (("GET", API), ("GET", f"{API}/places"), ("POST", API), ("POST", f"{API}/places"),
                         ("POST", f"{API}/places/rename"), ("POST", f"{API}/places/delete")):
        status, _body, headers = call(house.app, method, path, json_body={} if method == "POST" else None, cookie=None)
        assert status == 401
        assert "location" not in headers


def test_the_list_is_the_capitalisation_pools_only(house):
    status, body = house.get(API)
    assert status == 200
    assert [(pool["id"], pool["sentences"]) for pool in body["pools"]] == [("other", 1), ("places", 2)]


def test_the_page_shows_each_sentence_and_its_own_level(house):
    page = house.pool("places")
    assert page["sentences"] == [
        {"text": "Anna flew to Paris.", "level_of_difficulty": ""},
        {"text": "We saw NASA in July.", "level_of_difficulty": "2"},
    ]
    assert page["tasks"] == ["caps", "more caps"]
    assert house.get(f"{API}/nouns")[0] == 404  # a parts of speech pool has no page here


def test_a_save_with_nothing_changed_writes_nothing(house):
    before = house.text("places")
    status, body = house.save_pool("places", sentences=_sent(house.pool("places")))
    assert status == 200 and "Nothing has changed" in body["message"]
    assert house.text("places") == before


def test_a_new_sentence_with_no_level_of_its_own_is_written_as_a_plain_string(kept):
    page = kept.pool("places")
    sentences = _sent(page) + [{"origin": None, "text": "  Cara   sat  in Rome. ", "level_of_difficulty": ""}, {"origin": None, "text": "Dan met Eve.", "level_of_difficulty": "3"}]
    status, body = kept.save_pool("places", sentences=sentences)
    assert status == 200, body
    written = yaml.safe_load(kept.text("places"))["sentences"]
    assert written[:2] == ["Anna flew to Paris.", {"sentence": "We saw NASA in July.", "level_of_difficulty": 2}]
    assert written[2:] == ["Cara sat in Rome.", {"sentence": "Dan met Eve.", "level_of_difficulty": 3}]
    assert "Anna flew to Paris.\n" in kept.text("places")  # an unchanged sentence keeps its text
    assert kept.log()[0].endswith(" ada: saved capitalisation pool Places")
    assert check.main(["--quiet"]) == 0


def test_a_sentence_at_the_pools_own_level_is_written_without_one(house):
    sentences = _sent(house.pool("places"))
    sentences[1]["level_of_difficulty"] = "1"
    status, body = house.save_pool("places", sentences=sentences)
    assert status == 200, body
    assert yaml.safe_load(house.text("places"))["sentences"][1] == "We saw NASA in July."


@pytest.mark.parametrize(
    ("text", "level", "says"),
    [
        ("   ", "", "The sentence is empty."),
        ("no capitals here", "", "The sentence has no capital letter, so there is nothing to click."),
        ("Anna ran.", "11", "level_of_difficulty"),
    ],
)
def test_a_bad_sentence_is_refused_and_nothing_is_written(house, text, level, says):
    before = house.text("places")
    sentences = _sent(house.pool("places")) + [{"origin": None, "text": text, "level_of_difficulty": level}]
    status, body = house.save_pool("places", sentences=sentences)
    assert status == 400 and says in body["error"]
    assert house.text("places") == before


def test_a_sentence_twice_in_the_pool_is_refused(house):
    sentences = _sent(house.pool("places")) + [{"origin": None, "text": "anna flew to paris. B", "level_of_difficulty": ""}]
    assert house.save_pool("places", sentences=sentences)[0] == 200  # different words
    sentences = _sent(house.pool("places")) + [{"origin": None, "text": "ANNA  flew to Paris.", "level_of_difficulty": ""}]
    status, body = house.save_pool("places", sentences=sentences)
    assert status == 400 and "is the same as entry 1" in "\n".join(body["errors"])


def test_a_hand_edit_since_the_page_opened_refuses_the_save(house):
    version = house.pool("places")["version"]
    path = pools_directory(house.config, CAPITALISATION_DIR) / "places.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
    status, body = house.save_pool("places", version=version, sentences=_sent(house.pool("places")))
    assert status == 409 and body["stale"] is True


def test_create_makes_an_empty_pool_named_in_the_capitalisation_folder(kept):
    status, body = kept.post(API, {"name": "Year 3"})
    assert status == 200, body
    assert body["pool"] == {"id": "year-3", "name": "Year 3"}
    assert kept.text("year-3") == "name: Year 3\nsentences: []\n"
    assert not (pools_directory(kept.config, POOLS_DIR) / "year-3.yaml").exists()
    assert kept.log()[0].endswith(" ada: made capitalisation pool Year 3")


def test_rename_changes_only_capitalisation_tasks_that_list_it(kept):
    status, body = kept.post(f"{API}/places/rename", {"name": "Towns", "version": kept.pool("places")["version"]})
    assert status == 200, body
    tasks = yaml.safe_load(kept.policy.read_text(encoding="utf-8"))["tasks"]["capitalisation"]
    assert tasks["caps"]["body"]["pools"] == ["Towns"]
    assert tasks["more caps"]["body"]["pools"] == ["Other", "Towns"]
    assert check.main(["--quiet"]) == 0


def test_delete_is_refused_while_a_task_names_the_pool_and_allowed_after(house):
    status, body = house.post(f"{API}/places/delete", {"version": house.pool("places")["version"]})
    assert status == 400 and "caps" in body["error"]
    write_pool(pools_directory(house.config, CAPITALISATION_DIR), "spare", "Spare", ["Go Home."])
    assert house.post(f"{API}/spare/delete", {"version": house.pool("spare")["version"]})[0] == 200


# The task page


def test_the_task_page_has_settings_and_pools_and_no_filter(house):
    page = house.page("capitalisation/caps")
    assert page["capitalisation"]["pools"] == ["Places"]
    assert page["capitalisation"]["settings"] == {"timeout": "", "correct_answers_required": "", "minimum_questions": "", "maximum_questions": ""}
    assert [pool["name"] for pool in page["capitalisation"]["available"]] == ["Other", "Places"]
    assert "parts_of_speech" not in page


def test_a_task_page_save_writes_the_settings_and_pools(house):
    status, body = house.save("capitalisation/caps", settings={"timeout": "45s"}, pools=["Other", "Places"])
    assert status == 200, body
    task = yaml.safe_load(house.policy.read_text(encoding="utf-8"))["tasks"]["capitalisation"]["caps"]["body"]
    assert task == {"pools": ["Other", "Places"], "timeout": "45s"}
    assert house.save("capitalisation/caps", pools=[])[0] == 400
    assert house.save("capitalisation/caps", sentences=[])[0] == 400


def test_a_new_capitalisation_task_can_be_made(house):
    status, body, _headers = call(house.app, "GET", "/parent/api/new-task", cookie=house.cookie)
    assert "capitalisation" in json.loads(body)["types"]
    status, body = house.post("/parent/api/new-task", {"type": "capitalisation", "name": "fresh", "settings": {}, "pools": ["Places"], "fields": {}, "groups": ["younger"]})
    assert status == 200, body
    assert house.page("capitalisation/fresh")["capitalisation"]["pools"] == ["Places"]
