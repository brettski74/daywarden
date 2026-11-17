"""S007.3, S031.1, and S031.2: the parts of speech area of a task page, and the sentence editor's helpers.

Since S031.1 a task's sentences live in a pool file named by ``body.pools``, and since S031.2 they are edited on the
pool's page (``tests/test_pool_admin.py``). The task page keeps the task's own settings. These tests cover that page,
and the helpers that turn the editor's sentences into a pool's ``sentences`` list.
"""

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_task_admin import HOUSE, House, _git  # noqa: E402

from policy import check  # noqa: E402
from policy.parts_of_speech_admin import sentences_edit, shown_sentences, tidy  # noqa: E402
from policy.sentence_pools import pools_directory, write_pool  # noqa: E402

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


def _shown(listed: list) -> list[dict]:
    """Return the sentences as the page has them, in the form a save sends them back."""
    return [{"origin": index, **sentence} for index, sentence in enumerate(shown_sentences(listed)[0])]


# The page and a save of settings, for a task whose sentences are in a pool


def test_the_page_shows_the_settings_and_no_inline_sentences_for_a_task_with_pools(house):
    shown = house.page("parts_of_speech/words")["parts_of_speech"]
    assert shown == {
        "settings": {"timeout": "45s", "correct_answers_required": "", "minimum_questions": "", "maximum_questions": ""},
        "pools": [POOL],
        "filter": [],
        "available": [{"id": "words-sentences", "name": POOL, "sentences": 2}],
    }
    assert "spelling" not in house.page("parts_of_speech/words")


def test_a_save_with_nothing_changed_writes_nothing(house):
    status, body = house.save("parts_of_speech/words", settings={"timeout": "45s"})
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


def test_a_task_save_that_sends_sentences_is_refused_and_writes_nothing(house):
    """Sentences are edited on a pool's page, so the task page never sends them."""
    sentence = {"origin": None, "text": "The cat sat.", "level_of_difficulty": "", "parts": [{"name": "noun", "words": [1]}]}
    status, body = house.save("parts_of_speech/words", sentences=[sentence])
    assert status == 400
    assert "Asset Administration" in body["error"]
    assert house.policy.read_text(encoding="utf-8") == TEXT
    assert check.main(["--quiet"]) == 0


def test_a_settings_save_is_committed_as_the_parent(tmp_path, monkeypatch):
    kept = House(tmp_path, monkeypatch, history=True, text=TEXT, before=_write_pool)
    status, body = kept.save("parts_of_speech/words", settings={"timeout": "60s"})
    assert status == 200, body
    assert kept.log()[0].endswith(" ada: saved task parts_of_speech/words")
    assert _git(kept.config, "status", "--porcelain") == ""


def _more_pools(config: Path) -> None:
    _write_pool(config)
    write_pool(pools_directory(config), "spare", "Spare", SENTENCES[:1])


@pytest.fixture
def spare(tmp_path, monkeypatch):
    return House(tmp_path, monkeypatch, text=TEXT, before=_more_pools)


def test_the_page_lists_pools_no_task_names_yet(spare):
    shown = spare.page("parts_of_speech/words")["parts_of_speech"]
    assert [entry["name"] for entry in shown["available"]] == ["Spare", POOL]
    assert shown["pools"] == [POOL]


def test_pools_filter_and_question_counts_are_written_in_the_body(spare):
    status, body = spare.save(
        "parts_of_speech/words",
        settings={"minimum_questions": "2", "maximum_questions": "3", "correct_answers_required": "1"},
        pools=[POOL, "Spare"],
        parts_of_speech=["Nouns", "verb"],
    )
    assert status == 200, body
    written = _body(spare)
    assert written["pools"] == [POOL, "Spare"]
    assert written["parts_of_speech"] == ["noun", "verb"]
    assert (written["minimum_questions"], written["maximum_questions"]) == (2, 3)
    task = spare.task("parts_of_speech/words")
    assert task.document()["parts_of_speech"] == ["noun", "verb"]


def test_an_empty_filter_removes_it_and_a_filter_left_alone_keeps_its_text(spare):
    assert spare.save("parts_of_speech/words", parts_of_speech=["Noun", "verb"])[0] == 200
    assert _body(spare)["parts_of_speech"] == ["noun", "verb"]
    text = spare.policy.read_text(encoding="utf-8")
    status, body = spare.save("parts_of_speech/words", parts_of_speech=["noun", "verb"], settings={"timeout": "50s"})
    assert status == 200, body
    assert "timeout: 50s" in spare.policy.read_text(encoding="utf-8")
    assert _body(spare)["parts_of_speech"] == ["noun", "verb"]
    assert spare.save("parts_of_speech/words", parts_of_speech=[])[0] == 200
    assert "parts_of_speech" not in _body(spare)
    assert text != spare.policy.read_text(encoding="utf-8")


def test_a_save_with_no_pools_is_refused_and_writes_nothing(spare):
    status, body = spare.save("parts_of_speech/words", pools=[])
    assert status == 400
    assert "at least one pool" in body["error"]
    assert spare.policy.read_text(encoding="utf-8") == TEXT


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"pools": ["Nowhere"]}, "pools"),
        ({"parts_of_speech": ["noun", "Noun"]}, "parts_of_speech"),
        ({"parts_of_speech": ["a" * 21]}, "parts_of_speech"),
        ({"settings": {"maximum_questions": "5"}}, "maximum_questions"),
        ({"settings": {"minimum_questions": "9"}}, "minimum_questions"),
    ],
)
def test_a_value_the_load_would_refuse_writes_nothing_and_says_why(spare, changes, field):
    status, body = spare.save("parts_of_speech/words", **changes)
    assert status == 400
    assert any(field in problem for problem in body["errors"]), body
    assert spare.policy.read_text(encoding="utf-8") == TEXT


def test_the_next_run_uses_the_saved_settings_and_the_pool(house):
    assert house.save("parts_of_speech/words", settings={"timeout": "60s"})[0] == 200
    document = house.task("parts_of_speech/words").document()
    assert (document["timeout"], document["pools"]) == ("60s", [POOL])


# The sentence editor's helpers, on a pool's sentences list


def test_each_sentence_is_shown_with_its_level_and_rows_in_order():
    assert shown_sentences(SENTENCES) == (
        [
            {
                "text": FOX,
                "level_of_difficulty": "",
                "parts": [
                    {"name": "noun", "words": [3, 8]},
                    {"name": "verb", "words": [4]},
                    {"name": "Adjectives", "words": [1, 2, 7]},
                ],
            },
            {
                "text": DRY,
                "level_of_difficulty": "2",
                "parts": [
                    {"name": "verb", "words": [0]},
                    {"name": "noun", "words": [2, 6]},
                    {"name": "adjective", "words": [5]},
                ],
            },
        ],
        [],
    )


def test_a_word_the_sentence_does_not_have_is_a_problem_shown_on_the_page():
    listed = [{"sentence": "The cat sat.", "parts": {"noun": ["dog"]}}]
    sentences, problems = shown_sentences(listed)
    assert sentences[0]["parts"] == [{"name": "noun", "words": []}]
    assert problems and "dog" in problems[0]


def test_sentences_sent_back_as_loaded_are_no_change():
    assert sentences_edit(SENTENCES, _shown(SENTENCES), 1.0) is None
    assert sentences_edit(SENTENCES, None, 1.0) is None


def test_only_the_changed_sentence_is_written_again_with_tidied_names_and_merged_rows():
    sentences = _shown(SENTENCES)
    sentences[1]["parts"] = [
        {"name": "Verbs", "words": [0]},
        {"name": "Nouns", "words": [6]},
        {"name": "Subject", "words": []},
        {"name": "noun", "words": [2]},
        {"name": "Proper Nouns", "words": [5]},
    ]
    sentences[1]["level_of_difficulty"] = ""
    edit = sentences_edit(SENTENCES, sentences, 1.0)
    assert [(item.origin, item.changed) for item in edit.items] == [(0, False), (1, True)]
    assert edit.items[0].data == SENTENCES[0]
    assert edit.items[1].data == {
        "sentence": DRY,
        "parts": {"verb": ["Dry"], "noun": ["dishes", "towel"], "subject": [], "proper noun": ["dry[2]"]},
    }


def test_a_new_sentence_is_added_at_the_end_and_a_deleted_one_is_dropped():
    sentences = _shown(SENTENCES)[1:] + [
        {"origin": None, "text": "Yes, the cat sat on the mat.", "level_of_difficulty": "0.5", "parts": [
            {"name": "interjection", "words": [0]},
            {"name": "noun", "words": [2, 6]},
        ]},
    ]
    edit = sentences_edit(SENTENCES, sentences, 1.0)
    assert [(item.origin, item.changed) for item in edit.items] == [(1, False), (None, True)]
    assert edit.items[1].data == {
        "sentence": "Yes, the cat sat on the mat.",
        "level_of_difficulty": 0.5,
        "parts": {"interjection": ["Yes"], "noun": ["cat", "mat"]},
    }


def test_a_sentence_at_the_pools_level_is_written_without_its_own():
    sentences = _shown(SENTENCES)
    sentences[0]["level_of_difficulty"] = "2"
    edit = sentences_edit(SENTENCES, sentences, 2.0)
    assert "level_of_difficulty" not in edit.items[0].data


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
    sentences = _shown(SENTENCES)
    change(sentences)
    with pytest.raises(ValueError, match=says):
        sentences_edit(SENTENCES, sentences, 1.0)


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
