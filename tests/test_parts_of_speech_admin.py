"""S007.3: the parts of speech area of a task page, and saving its sentences to the policy file."""

import random
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_task_admin import HOUSE, House, _git  # noqa: E402

from policy import check  # noqa: E402
from policy.parts_of_speech import Session  # noqa: E402
from policy.parts_of_speech_admin import tidy  # noqa: E402

ZONE = ZoneInfo("America/Toronto")
FOX = "The quick, brown fox jumped over the lazy dog."
DRY = "Dry the dishes with a dry towel."
WORDS = """\
  words:
    type: parts_of_speech
    group: younger
    pass_cooldown: 7
    body:
      timeout: 45s
      sentences:
        # The fox, as the README has it.
        - sentence: "The quick, brown fox jumped over the lazy dog."
          parts:
            noun: [dog, fox]   # out of order on purpose
            verb: [jumped]
            Adjectives: [quick, brown, lazy]
        - sentence: Dry the dishes with a dry towel.
          timeout: 2m
          parts:
            verb: ["dry[1]"]
            noun: [dishes, towel]
            adjective: ["dry[2]"]
"""
TEXT = HOUSE + WORDS


@pytest.fixture
def house(tmp_path, monkeypatch):
    return House(tmp_path, monkeypatch, text=TEXT)


def _shown(house) -> list[dict]:
    """Return the sentences as the page has them, in the form a save sends them back."""
    sentences = house.page("words")["parts_of_speech"]["sentences"]
    return [{"origin": index, **sentence} for index, sentence in enumerate(sentences)]


def _body(house) -> dict:
    return yaml.safe_load(house.policy.read_text(encoding="utf-8"))["tasks"]["words"]["body"]


def test_the_page_shows_the_settings_and_each_sentence_with_its_rows_in_order(house):
    page = house.page("words")
    assert page["parts_of_speech"] == {
        "settings": {"timeout": "45s", "correct_answers_required": ""},
        "sentences": [
            {
                "text": FOX,
                "timeout": "",
                "parts": [
                    {"name": "noun", "words": [3, 8]},
                    {"name": "verb", "words": [4]},
                    {"name": "Adjectives", "words": [1, 2, 7]},
                ],
            },
            {
                "text": DRY,
                "timeout": "2m",
                "parts": [
                    {"name": "verb", "words": [0]},
                    {"name": "noun", "words": [2, 6]},
                    {"name": "adjective", "words": [5]},
                ],
            },
        ],
        "problems": [],
    }
    assert "spelling" not in page


def test_a_save_with_nothing_changed_writes_nothing(house):
    status, body = house.save("words", sentences=_shown(house), settings={"timeout": "45s"})
    assert (status, body["message"]) == (200, "Nothing has changed, so nothing was saved.")
    assert house.policy.read_text(encoding="utf-8") == TEXT


def test_settings_are_written_in_the_body_and_cleared_ones_lose_their_line(house):
    status, body = house.save("words", settings={"timeout": "", "correct_answers_required": "1"})
    assert status == 200, body
    assert house.policy.read_text(encoding="utf-8") == TEXT.replace("      timeout: 45s\n", "").replace(
        "            adjective: [\"dry[2]\"]\n", "            adjective: [\"dry[2]\"]\n      correct_answers_required: 1\n"
    )
    assert house.task("words").document()["correct_answers_required"] == 1


def test_more_correct_answers_than_sentences_is_refused_naming_the_field(house):
    status, body = house.save("words", settings={"correct_answers_required": "3"})
    assert status == 400
    assert any("correct_answers_required" in problem for problem in body["errors"])
    assert house.policy.read_text(encoding="utf-8") == TEXT


def test_only_the_changed_sentence_is_written_again_with_tidied_names_and_merged_rows(house):
    sentences = _shown(house)
    sentences[1]["parts"] = [
        {"name": "Verbs", "words": [0]},
        {"name": "Nouns", "words": [6]},
        {"name": "Subject", "words": []},
        {"name": "noun", "words": [2]},
        {"name": "Proper Nouns", "words": [5]},
    ]
    sentences[1]["timeout"] = ""
    status, body = house.save("words", sentences=sentences)
    assert status == 200, body
    text = house.policy.read_text(encoding="utf-8")
    assert text == TEXT.replace(
        '        - sentence: Dry the dishes with a dry towel.\n          timeout: 2m\n          parts:\n'
        '            verb: ["dry[1]"]\n            noun: [dishes, towel]\n            adjective: ["dry[2]"]\n',
        "        - sentence: Dry the dishes with a dry towel.\n          parts:\n"
        '            verb: [Dry]\n            noun: [dishes, towel]\n            subject: []\n            proper noun: ["dry[2]"]\n',
    )
    shown = house.page("words")["parts_of_speech"]["sentences"][1]["parts"]
    assert [part["name"] for part in shown] == ["verb", "noun", "subject", "proper noun"]


def test_a_new_sentence_is_added_at_the_end_and_a_deleted_one_loses_its_lines(house):
    sentences = _shown(house)[1:] + [
        {"origin": None, "text": "Yes, the cat sat on the mat.", "timeout": "30s", "parts": [
            {"name": "interjection", "words": [0]},
            {"name": "noun", "words": [2, 6]},
        ]},
    ]
    status, body = house.save("words", sentences=sentences)
    assert status == 200, body
    text = house.policy.read_text(encoding="utf-8")
    assert FOX not in text
    assert "# The fox, as the README has it." in text
    assert text.endswith(
        '            adjective: ["dry[2]"]\n'
        "        - sentence: Yes, the cat sat on the mat.\n"
        "          parts:\n"
        '            interjection: ["Yes"]\n'
        "            noun: [cat, mat]\n"
        "          timeout: 30s\n"
    )
    assert [sentence["sentence"] for sentence in _body(house)["sentences"]] == [DRY, "Yes, the cat sat on the mat."]
    assert check.main(["--quiet"]) == 0


def test_a_sentence_the_policy_would_refuse_is_named_and_nothing_is_written(house):
    sentences = _shown(house)
    sentences[0]["timeout"] = "soon"
    status, body = house.save("words", sentences=sentences)
    assert status == 400
    assert any("sentences entry 1: timeout" in problem for problem in body["errors"]), body
    assert house.policy.read_text(encoding="utf-8") == TEXT


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (lambda sentences: sentences.reverse(), "keep their order"),
        (lambda sentences: sentences[0].update(origin=7), "names no sentence in the file"),
        (lambda sentences: sentences[0]["parts"][0].update(words=[3, 99]), "word 99 is not in the sentence"),
        (lambda sentences: sentences[0]["parts"][1].update(words=[3]), "word 3 is in more than one row"),
    ],
)
def test_a_request_the_page_would_never_send_is_refused(house, change, says):
    sentences = _shown(house)
    change(sentences)
    status, body = house.save("words", sentences=sentences)
    assert status == 400
    assert says in body["error"]
    assert house.policy.read_text(encoding="utf-8") == TEXT


@pytest.mark.parametrize(
    ("typed", "written"),
    [
        ("Nouns", "noun"),
        ("VERB", "verb"),
        ("  proper nouns ", "proper noun"),
        ("Interjections", "interjection"),
        ("Subject", "subject"),
        ("Doing words", "doing words"),
        ("Nounss", "nounss"),
    ],
)
def test_row_names_are_tidied(typed, written):
    assert tidy(typed) == written


def test_the_next_run_asks_the_saved_sentences_and_a_run_in_progress_keeps_its_own(house):
    started = datetime(2026, 11, 9, 16, 0, tzinfo=ZONE)
    running = Session({}, house.task("words").document(), random.Random(1))
    running.issue(started)
    sentences = _shown(house)
    sentences[0]["parts"] = [{"name": "noun", "words": [3]}, {"name": "verb", "words": [4]}]
    assert house.save("words", sentences=sentences)[0] == 200
    later = Session(running.detail, house.task("words").document(), random.Random(1))
    assert [sentence.text for sentence in later.settings.sentences] == [FOX, DRY]
    assert [part.name for part in later.settings.sentences[0].parts] == ["noun", "verb", "Adjectives"]
    fresh = Session({}, house.task("words").document(), random.Random(1))
    fresh.issue(started)
    assert [(part.name, part.words) for part in fresh.settings.sentences[0].parts] == [("noun", (3,)), ("verb", (4,))]


def test_a_sentences_save_is_committed_as_the_parent(tmp_path, monkeypatch):
    kept = House(tmp_path, monkeypatch, history=True, text=TEXT)
    status, body = kept.save("words", sentences=_shown(kept)[:1])
    assert status == 200, body
    assert kept.log()[0].endswith(" ada: saved task words")
    assert _git(kept.config, "status", "--porcelain") == ""


def test_a_hand_edit_since_the_page_opened_refuses_the_save(house):
    version = house.page("words")["version"]
    sentences = _shown(house)[:1]
    house.policy.write_text(TEXT.replace("timeout: 2m", "timeout: 3m"), encoding="utf-8")
    status, body = house.save("words", version=version, sentences=sentences)
    assert status == 409
    assert "timeout: 3m" in house.policy.read_text(encoding="utf-8")
