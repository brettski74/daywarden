"""S006.1: parts of speech sentences, their words, and the parts table in the policy file."""

import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy.hierarchy import ConfigError, load  # noqa: E402
from policy.parts_of_speech import default_required, parse_settings, split_words  # noqa: E402

EXAMPLE = """\
timeout: 45s
sentences:
  - sentence: "The quick, brown fox jumped over the lazy dog."
    parts:
      noun: [fox, dog]
      verb: [jumped]
      adjective: [quick, brown, lazy]
  - sentence: "Dry the dishes with a dry towel."
    timeout: 60s
    parts:
      verb: ["dry[1]"]
      noun: [dishes, towel]
      adjective: ["dry[2]"]
"""

DRY = "Dry the dishes with a dry towel."


def _house(body: str) -> str:
    return (
        "entry: open\n"
        "client_groups:\n"
        "  younger:\n"
        '    addresses: ["192.0.2.40"]\n'
        "tasks:\n"
        "  parts-of-speech-1:\n"
        "    type: parts_of_speech\n"
        "    group: younger\n"
        "    pass_cooldown: 21\n"
        "    failure_cooldown: 1\n"
        "    body:\n"
        f"{textwrap.indent(body, '      ')}"
        "rule_sets:\n"
        "  open:\n"
        "    - condition: always\n"
        "      when_true: { action: allow }\n"
    )


def _write(directory: Path, body: str) -> Path:
    path = directory / "policy.yaml"
    path.write_text(_house(body), encoding="utf-8")
    return path


def _settings(directory: Path, body: str):
    policy = load(_write(directory, body))
    assert policy is not None
    return parse_settings(policy.task("parts-of-speech-1").document())


def _refused(directory: Path, body: str) -> str:
    good = load(_write(directory, EXAMPLE))
    with pytest.raises(ConfigError) as raised:
        load(_write(directory, body), previous=good)
    assert good.task("parts-of-speech-1").document()["sentences"][0]["parts"]["noun"] == ["fox", "dog"]
    message = str(raised.value)
    assert "task 'parts-of-speech-1': body." in message
    return message


def _one(sentence: str, parts: str, extra: str = "") -> str:
    return f'sentences:\n  - sentence: "{sentence}"\n{extra}    parts:\n' + textwrap.indent(parts, "      ")


def _table(settings, index: int = 0) -> dict[str, list[str]]:
    sentence = settings.sentences[index]
    return {
        part.name: [f"{sentence.words[at].text}[{sentence.words[at].occurrence}]" for at in part.words]
        for part in sentence.parts
    }


# Words


def test_the_example_task_loads_with_its_words_pass_mark_and_timeouts(tmp_path):
    settings = _settings(tmp_path, EXAMPLE)
    first, second = settings.sentences
    assert [word.text for word in first.words] == [
        "The", "quick", "brown", "fox", "jumped", "over", "the", "lazy", "dog",
    ]
    assert settings.required == 2
    assert (first.timeout, second.timeout) == (45_000, 60_000)
    assert first.part_of(3) == "noun"
    assert first.part_of(5) is None
    assert _table(settings, 1) == {"verb": ["Dry[1]"], "noun": ["dishes[1]", "towel[1]"], "adjective": ["dry[2]"]}


def test_punctuation_and_spaces_are_not_words():
    sentence = "The quick, brown fox jumped over the lazy dog."
    words = split_words(sentence)
    assert [word.text for word in words][:4] == ["The", "quick", "brown", "fox"]
    assert all(sentence[word.start : word.end] == word.text for word in words)
    assert [word.text for word in split_words("the dogs' bowls")] == ["the", "dogs", "bowls"]
    assert [word.text for word in split_words("'Quick' -- he said.")] == ["Quick", "he", "said"]


@pytest.mark.parametrize("word", ["don't", "don\u2019t", "o'clock", "well-known", "caf\u00e9", "cafe\u0301", "2nd"])
def test_an_apostrophe_or_hyphen_inside_a_word_keeps_it_one_word(word):
    assert [found.text for found in split_words(f"It is {word}.")] == ["It", "is", word]


def test_words_that_differ_only_in_case_or_apostrophe_are_occurrences_of_one_word():
    words = split_words("Don't dry it; don\u2019t DRY it, dry it.")
    assert [(word.text, word.occurrence) for word in words] == [
        ("Don't", 1), ("dry", 1), ("it", 1), ("don\u2019t", 2), ("DRY", 2), ("it", 2), ("dry", 3), ("it", 3),
    ]


# Entries and occurrences


@pytest.mark.parametrize("verb", ['["dry[1]"]', "[dry]", "[ Dry ]", "\n  - dry[1]"])
def test_an_entry_without_brackets_is_the_first_occurrence(tmp_path, verb):
    settings = _settings(tmp_path, _one(DRY, f'verb: {verb}\nadjective: ["dry[2]"]\n'))
    assert _table(settings) == {"verb": ["Dry[1]"], "adjective": ["dry[2]"]}


@pytest.mark.parametrize("entry", ['"the[1,2]"', '"the[2, 1]"', '" the [ 1 , 2 ] "'])
def test_one_entry_may_list_several_occurrences(tmp_path, entry):
    settings = _settings(tmp_path, _one("The cat sat on the mat.", f"article: [{entry}]\n"))
    assert _table(settings) == {"article": ["The[1]", "the[2]"]}


def test_one_occurrence_in_two_parts_is_refused_naming_both(tmp_path):
    message = _refused(tmp_path, _one(DRY, 'verb: [dry]\nadjective: ["dry[1]"]\n'))
    assert 'body.sentences entry 1: parts: "Dry[1]" is listed under verb and adjective' in message
    message = _refused(tmp_path, _one(DRY, 'verb: [dry, "dry[1]"]\nnoun: [towel]\n'))
    assert 'sentences entry 1: parts.verb: "Dry[1]" is listed more than once' in message
    message = _refused(tmp_path, _one(DRY, 'verb: [dry]\nnoun: [dry]\nadjective: ["dry[1]"]\n'))
    assert "listed under verb, noun, and adjective" in message


def test_the_example_error_names_the_task_sentence_part_and_entry(tmp_path):
    body = EXAMPLE.replace('adjective: ["dry[2]"]', 'adjective: ["dry[3]"]')
    message = _refused(tmp_path, body)
    assert (
        "task 'parts-of-speech-1': body.sentences entry 2: parts.adjective: "
        '"dry[3]": the sentence has only 2 of "dry"'
    ) in message


@pytest.mark.parametrize(
    ("entry", "says"),
    [
        ('"dry[1,1]"', "occurrence 1 is in the brackets more than once"),
        ('"dry[0]"', "occurrences are counted from 1"),
        ('"dry[]"', "the brackets hold occurrence numbers"),
        ('"dry[a]"', "the brackets hold occurrence numbers"),
        ('"dry[1.5]"', "the brackets hold occurrence numbers"),
        ('"dry[1-2]"', "the brackets hold occurrence numbers"),
        ('"dry[1,]"', "the brackets hold occurrence numbers"),
        ('"dry[1"', "write the occurrence numbers in one pair of square brackets"),
        ('"dry]1["', "write the occurrence numbers in one pair of square brackets"),
        ('"dry[1][2]"', "write the occurrence numbers in one pair of square brackets"),
        ('"[1]"', "name a word before the brackets"),
    ],
)
def test_malformed_occurrences_are_refused(tmp_path, entry, says):
    message = _refused(tmp_path, _one(DRY, f"verb: [{entry}]\n"))
    assert f"body.sentences entry 1: parts.verb: {entry}: {says}" in message


def test_an_empty_entry_is_refused(tmp_path):
    assert "body.sentences entry 1: parts.verb: entry 2 is empty" in _refused(tmp_path, _one(DRY, 'verb: [dry, ""]\n'))


def test_entries_match_without_regard_to_case_or_apostrophe(tmp_path):
    parts = "noun: [fox]\nverb: [\"don't\", feed]\nadjective: [well-known]\n"
    settings = _settings(tmp_path, _one("Don\u2019t feed the well-known FOX.", parts))
    assert _table(settings) == {
        "noun": ["FOX[1]"],
        "verb": ["Don\u2019t[1]", "feed[1]"],
        "adjective": ["well-known[1]"],
    }


@pytest.mark.parametrize(
    ("entry", "says"),
    [
        ('"fox,"', '"fox," is not a single word'),
        ('"ice cream"', '"ice cream" is not a single word'),
        ('"-"', '"-" is not a single word'),
        ("cat", '"cat" is not in the sentence'),
        ("[cat]", "entry 2 is not text; list each word on its own"),
    ],
)
def test_an_entry_must_be_one_word_from_the_sentence(tmp_path, entry, says):
    message = _refused(tmp_path, _one("The fox ate ice cream.", f"noun: [fox, {entry}]\n"))
    assert "body.sentences entry 1: parts.noun: " in message
    assert says in message


@pytest.mark.parametrize("entry", ["yes", "3", "on", "~"])
def test_an_entry_yaml_does_not_read_as_text_is_refused_with_a_hint_to_quote_it(tmp_path, entry):
    message = _refused(tmp_path, _one("Say yes 3 times on cue.", f"noun: [times, {entry}]\n"))
    assert "body.sentences entry 1: parts.noun: entry 2 (" in message
    assert "is not text" in message
    assert "put the word in quotes" in message


def test_a_quoted_yes_or_number_is_a_word(tmp_path):
    settings = _settings(tmp_path, _one("Say yes 3 times.", 'adverb: ["yes"]\nnumber: ["3"]\n'))
    assert _table(settings) == {"adverb": ["yes[1]"], "number": ["3[1]"]}


# The parts table


def test_words_may_be_left_out_and_a_part_may_be_empty(tmp_path):
    settings = _settings(tmp_path, _one("The cat sat on the mat.", "noun: [cat, mat]\nadverb: []\n"))
    assert _table(settings) == {"noun": ["cat[1]", "mat[1]"], "adverb": []}
    assert [settings.sentences[0].part_of(position) for position in range(6)] == [
        None, "noun", None, None, None, "noun",
    ]


@pytest.mark.parametrize(
    ("body", "says"),
    [
        (_one("The cat sat.", "noun: []\nverb: []\n"), "sentences entry 1: parts: list at least one word"),
        ('sentences:\n  - sentence: "The cat sat."\n    parts: {}\n', "sentences entry 1: parts: must map one or more"),
        ('sentences:\n  - sentence: "The cat sat."\n    parts: [cat]\n', "sentences entry 1: parts: must map"),
        (_one("... !", "noun: [cat]\n"), "sentences entry 1: sentence: must contain at least one word"),
        ('sentences:\n  - sentence: 42\n    parts: {noun: ["42"]}\n', "sentences entry 1: sentence: must be text"),
        (_one("The cat sat.", "adverb:\nnoun: [cat]\n"), "parts.adverb: must be a list of words"),
        (_one("The cat sat.", "noun: cat\n"), "parts.noun: must be a list of words"),
    ],
)
def test_a_table_with_nothing_to_sort_is_refused(tmp_path, body, says):
    message = _refused(tmp_path, body)
    assert says in message
    if "adverb" in says:
        assert "write []" in message


def test_part_names_keep_the_order_and_spelling_they_were_written_in(tmp_path):
    settings = _settings(
        tmp_path, _one("The quick fox ran.", "Doing words: [ran]\nproper noun: []\nnoun: [fox]\nAdjective: [quick]\n")
    )
    assert [part.name for part in settings.sentences[0].parts] == ["Doing words", "proper noun", "noun", "Adjective"]


@pytest.mark.parametrize(
    ("parts", "says"),
    [
        ('"": [fox]\n', "must not be empty"),
        ('"   ": [fox]\n', "must not be empty"),
        ("a very long part name: [fox]\n", "parts.a very long part name: a part name is at most 20 characters"),
        ("noun: [fox]\nNoun: [dog]\n", "parts.Noun: the same name as noun"),
    ],
)
def test_a_bad_part_name_is_refused(tmp_path, parts, says):
    with pytest.raises(ConfigError) as raised:
        load(_write(tmp_path, _one("The fox and the dog.", parts)))
    assert says in str(raised.value)


def test_a_part_name_of_twenty_characters_is_allowed():
    name = "n" * 20
    settings = parse_settings({"sentences": [{"sentence": "A fox.", "parts": {name: ["fox"]}}]})
    assert settings.sentences[0].parts[0].name == name
    with pytest.raises(ValueError, match="parts: a part name must not be empty"):
        parse_settings({"sentences": [{"sentence": "A fox.", "parts": {" ": ["fox"]}}]})


# Timer and pass mark


def test_each_sentence_gets_the_body_timeout_unless_it_sets_its_own(tmp_path):
    defaulted = _settings(tmp_path, EXAMPLE.replace("timeout: 45s\n", "").replace("    timeout: 60s\n", ""))
    assert defaulted.timeout == 90_000
    assert [sentence.timeout for sentence in defaulted.sentences] == [90_000, 90_000]
    longer = _settings(tmp_path, EXAMPLE.replace("timeout: 45s\n", "timeout: 1m\n"))
    assert [sentence.timeout for sentence in longer.sentences] == [60_000, 60_000]
    mixed = _settings(tmp_path, EXAMPLE.replace("timeout: 45s", "timeout: 30s").replace("timeout: 60s", "timeout: 90s"))
    assert [sentence.timeout for sentence in mixed.sentences] == [30_000, 90_000]


@pytest.mark.parametrize("value", ["0s", "45", "soon"])
def test_a_bad_timeout_is_refused_on_the_body_and_on_a_sentence(tmp_path, value):
    on_body = _refused(tmp_path, EXAMPLE.replace("timeout: 45s", f"timeout: {value}"))
    assert "body.timeout: must be" in on_body
    on_sentence = _refused(tmp_path, EXAMPLE.replace("timeout: 60s", f"timeout: {value}"))
    assert "body.sentences entry 2: timeout: must be" in on_sentence


@pytest.mark.parametrize(("count", "required"), [(10, 7), (5, 4), (3, 3), (1, 1), (2, 2), (20, 14), (7, 5)])
def test_the_pass_mark_defaults_to_seventy_percent_rounded_up(count, required):
    assert default_required(count) == required
    sentences = [{"sentence": "A fox.", "parts": {"noun": ["fox"]}}] * count
    assert parse_settings({"sentences": sentences}).required == required


def test_an_explicit_pass_mark_is_used(tmp_path):
    assert _settings(tmp_path, EXAMPLE + "correct_answers_required: 1\n").required == 1


@pytest.mark.parametrize("value", ["0", "-1", "2.5", "3", '"2"'])
def test_a_bad_pass_mark_is_refused(tmp_path, value):
    message = _refused(tmp_path, EXAMPLE + f"correct_answers_required: {value}\n")
    assert "body.correct_answers_required: must be a whole number from 1 to 2, the number of sentences" in message


# Fields


@pytest.mark.parametrize(
    ("body", "says"),
    [
        (EXAMPLE + "colour: blue\n", "body.colour: unknown setting"),
        (EXAMPLE.replace("    timeout: 60s\n", "    colour: blue\n"), "body.sentences entry 2: colour: unknown setting"),
        ("timeout: 45s\n", "body.sentences: required"),
        ("sentences: []\n", "body.sentences: must be a list of one or more sentences"),
        ("sentences: The cat sat.\n", "body.sentences: must be a list of one or more sentences"),
        ('sentences:\n  - "The cat sat."\n', "body.sentences entry 1: must be a mapping with sentence and parts"),
        ("sentences:\n  - parts: {noun: [cat]}\n", "body.sentences entry 1: sentence: required"),
        ('sentences:\n  - sentence: "The cat sat."\n', "body.sentences entry 1: parts: required"),
    ],
)
def test_missing_and_unknown_fields_are_refused(tmp_path, body, says):
    assert says in _refused(tmp_path, body)
