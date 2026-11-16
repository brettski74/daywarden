"""S007.3 and S031.1: the parts of speech area of a task page, and saving its settings to the policy file.

Since S031.1 a task's sentences live in a pool file named by ``body.pools``. The portal's sentence editor is replaced
in S031.2 and S031.3, so these tests keep the helpers' own behaviour on a task that still lists inline ``sentences``
(``sentences_edit``, ``page``), and show that a save through the page keeps the settings working but cannot write
inline sentences back.
"""

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_task_admin import HOUSE, House, _git  # noqa: E402

from policy import check  # noqa: E402
from policy.parts_of_speech_admin import page, sentences_edit, tidy  # noqa: E402
from policy.sentence_pools import pools_directory, write_pool  # noqa: E402
from policy.task_edit import WrittenTask  # noqa: E402

FOX = "The quick, brown fox jumped over the lazy dog."
DRY = "Dry the dishes with a dry towel."
POOL = "words sentences"
SENTENCES = [
    {
        "sentence": FOX,
        "parts": {"noun": ["dog", "fox"], "verb": ["jumped"], "Adjectives": ["quick", "brown", "lazy"]},
    },
    {
        "sentence": DRY,
        "level_of_difficulty": 2,
        "parts": {"verb": ["dry[1]"], "noun": ["dishes", "towel"], "adjective": ["dry[2]"]},
    },
]
WORDS = """\
  parts_of_speech:
    words:
      group: younger
      pass_cooldown: 7
      body:
        timeout: 45s
        pools: [words sentences]
"""
TEXT = HOUSE + WORDS


def _write_pool(config: Path) -> None:
    write_pool(pools_directory(config), "words-sentences", POOL, SENTENCES)


@pytest.fixture
def house(tmp_path, monkeypatch):
    return House(tmp_path, monkeypatch, text=TEXT, before=_write_pool)


def _body(house) -> dict:
    return yaml.safe_load(house.policy.read_text(encoding="utf-8"))["tasks"]["parts_of_speech"]["words"]["body"]


def _inline(timeout: str | None = None, sentences: list | None = None) -> WrittenTask:
    """A task as a hand-written file with inline sentences would give it to the page helpers."""
    data: dict[str, object] = {"sentences": [dict(sentence) for sentence in (sentences or _OLD)]}
    body = {}
    if timeout:
        data["timeout"] = body["timeout"] = timeout
    return WrittenTask(fields={}, groups=(), body=body, body_data=data)


_OLD = [
    {
        "sentence": FOX,
        "parts": {"noun": ["dog", "fox"], "verb": ["jumped"], "Adjectives": ["quick", "brown", "lazy"]},
    },
    {
        "sentence": DRY,
        "timeout": "2m",
        "parts": {"verb": ["dry[1]"], "noun": ["dishes", "towel"], "adjective": ["dry[2]"]},
    },
]


def _shown(written: WrittenTask) -> list[dict]:
    """Return the sentences as the page has them, in the form a save sends them back."""
    return [{"origin": index, **sentence} for index, sentence in enumerate(page(written)["sentences"])]


# The page and a save of settings, for a task whose sentences are in a pool


def test_the_page_shows_the_settings_and_no_inline_sentences_for_a_task_with_pools(house):
    shown = house.page("parts_of_speech/words")["parts_of_speech"]
    assert shown == {"settings": {"timeout": "45s", "correct_answers_required": ""}, "sentences": [], "problems": []}
    assert "spelling" not in house.page("parts_of_speech/words")


def test_a_save_with_nothing_changed_writes_nothing(house):
    status, body = house.save("parts_of_speech/words", sentences=[], settings={"timeout": "45s"})
    assert (status, body["message"]) == (200, "Nothing has changed, so nothing was saved.")
    assert house.policy.read_text(encoding="utf-8") == TEXT


def test_settings_are_written_in_the_body_and_cleared_ones_lose_their_line(house):
    status, body = house.save("parts_of_speech/words", settings={"timeout": "", "correct_answers_required": "1"})
    assert status == 200, body
    assert house.policy.read_text(encoding="utf-8") == TEXT.replace("        timeout: 45s\n", "").replace(
        "        pools: [words sentences]\n", "        pools: [words sentences]\n        correct_answers_required: 1\n"
    )
    assert house.task("parts_of_speech/words").document()["correct_answers_required"] == 1
    assert _body(house)["pools"] == [POOL]


def test_more_correct_answers_than_sentences_is_refused_naming_the_field(house):
    status, body = house.save("parts_of_speech/words", settings={"correct_answers_required": "3"})
    assert status == 400
    assert any("correct_answers_required" in problem for problem in body["errors"])
    assert house.policy.read_text(encoding="utf-8") == TEXT


def test_a_save_that_writes_inline_sentences_is_refused_and_writes_nothing(house):
    """The old sentence editor cannot write back: the policy refuses sentences beside pools until S031.2 and S031.3."""
    sentence = {"origin": None, "text": "The cat sat.", "timeout": "", "parts": [{"name": "noun", "words": [1]}]}
    status, body = house.save("parts_of_speech/words", sentences=[sentence])
    assert status == 400
    assert body["error"] == "This save would leave the policy unable to load, so nothing was saved."
    assert body["errors"]
    assert house.policy.read_text(encoding="utf-8") == TEXT
    assert check.main(["--quiet"]) == 0


def test_a_settings_save_is_committed_as_the_parent(tmp_path, monkeypatch):
    kept = House(tmp_path, monkeypatch, history=True, text=TEXT, before=_write_pool)
    status, body = kept.save("parts_of_speech/words", settings={"timeout": "60s"})
    assert status == 200, body
    assert kept.log()[0].endswith(" ada: saved task parts_of_speech/words")
    assert _git(kept.config, "status", "--porcelain") == ""


def test_the_next_run_uses_the_saved_settings_and_the_pool(house):
    assert house.save("parts_of_speech/words", settings={"timeout": "60s"})[0] == 200
    document = house.task("parts_of_speech/words").document()
    assert (document["timeout"], document["pools"]) == ("60s", [POOL])


# The helpers on a task that still lists inline sentences


def test_the_page_helper_shows_each_inline_sentence_with_its_rows_in_order():
    assert page(_inline("45s")) == {
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


def test_sentences_sent_back_as_loaded_are_no_change():
    written = _inline()
    assert sentences_edit(written, _shown(written)) is None
    assert sentences_edit(written, None) is None


def test_only_the_changed_sentence_is_written_again_with_tidied_names_and_merged_rows():
    written = _inline()
    sentences = _shown(written)
    sentences[1]["parts"] = [
        {"name": "Verbs", "words": [0]},
        {"name": "Nouns", "words": [6]},
        {"name": "Subject", "words": []},
        {"name": "noun", "words": [2]},
        {"name": "Proper Nouns", "words": [5]},
    ]
    sentences[1]["timeout"] = ""
    edit = sentences_edit(written, sentences)
    assert [(item.origin, item.changed) for item in edit.items] == [(0, False), (1, True)]
    assert edit.items[0].data == _OLD[0]
    assert edit.items[1].data == {
        "sentence": DRY,
        "parts": {"verb": ["Dry"], "noun": ["dishes", "towel"], "subject": [], "proper noun": ["dry[2]"]},
    }


def test_a_new_sentence_is_added_at_the_end_and_a_deleted_one_is_dropped():
    written = _inline()
    sentences = _shown(written)[1:] + [
        {"origin": None, "text": "Yes, the cat sat on the mat.", "timeout": "30s", "parts": [
            {"name": "interjection", "words": [0]},
            {"name": "noun", "words": [2, 6]},
        ]},
    ]
    edit = sentences_edit(written, sentences)
    assert [(item.origin, item.changed) for item in edit.items] == [(1, False), (None, True)]
    assert edit.items[1].data == {
        "sentence": "Yes, the cat sat on the mat.",
        "parts": {"interjection": ["Yes"], "noun": ["cat", "mat"]},
        "timeout": "30s",
    }


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (lambda sentences: sentences.reverse(), "keep their order"),
        (lambda sentences: sentences[0].update(origin=7), "names no sentence in the file"),
        (lambda sentences: sentences[0]["parts"][0].update(words=[3, 99]), "word 99 is not in the sentence"),
        (lambda sentences: sentences[0]["parts"][1].update(words=[3]), "word 3 is in more than one row"),
    ],
)
def test_a_request_the_page_would_never_send_is_refused(change, says):
    written = _inline()
    sentences = _shown(written)
    change(sentences)
    with pytest.raises(ValueError, match=says):
        sentences_edit(written, sentences)


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


def test_a_hand_edit_since_the_page_opened_refuses_the_save(house):
    version = house.page("parts_of_speech/words")["version"]
    house.policy.write_text(TEXT.replace("timeout: 45s", "timeout: 3m"), encoding="utf-8")
    status, body = house.save("parts_of_speech/words", version=version, settings={"timeout": "60s"})
    assert status == 409
    assert "timeout: 3m" in house.policy.read_text(encoding="utf-8")
