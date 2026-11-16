"""S006.1 and S031.1: parts of speech sentence pools, their words, and the parts table."""

import sys
import textwrap
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy import sentence_pools  # noqa: E402
from policy.hierarchy import ConfigError, load  # noqa: E402
from policy.parts_of_speech import (  # noqa: E402
    check_body,
    default_required,
    parse_settings,
    snapshot_settings,
    split_words,
)
from policy.tasks import TaskKey  # noqa: E402

POOL = "Pool A"
KEY = TaskKey("parts_of_speech", "parts-of-speech-1")
BODY = "pools: [Pool A]\ntimeout: 45s\n"

# The pool file holds the sentences. The task body names the pool and sets the task timeout.
EXAMPLE = """\
sentences:
  - sentence: "The quick, brown fox jumped over the lazy dog."
    parts:
      noun: [fox, dog]
      verb: [jumped]
      adjective: [quick, brown, lazy]
  - sentence: "Dry the dishes with a dry towel."
    level_of_difficulty: 2
    parts:
      verb: ["dry[1]"]
      noun: [dishes, towel]
      adjective: ["dry[2]"]
"""

DRY = "Dry the dishes with a dry towel."

# A policy that still keeps its sentences inline, as before S031.1.
INLINE = """\
timeout: 45s
sentences:
  - sentence: "The quick, brown fox jumped over the lazy dog."
    parts:
      noun: [fox, dog]
      verb: [jumped]
      adjective: [quick, brown, lazy]
  - sentence: "Dry the dishes with a dry towel."
    timeout: 90s
    parts:
      verb: ["dry[1]"]
      noun: [dishes, towel]
      adjective: ["dry[2]"]
"""


def _house(body: str) -> str:
    return (
        "entry: open\n"
        "client_groups:\n"
        "  younger:\n"
        '    addresses: ["192.0.2.40"]\n'
        "tasks:\n"
        "  parts_of_speech:\n"
        "    parts-of-speech-1:\n"
        "      group: younger\n"
        "      pass_cooldown: 21\n"
        "      failure_cooldown: 1\n"
        "      body:\n"
        f"{textwrap.indent(body, '        ')}"
        "rule_sets:\n"
        "  open:\n"
        "    - condition: always\n"
        "      when_true: { action: allow }\n"
    )


def _pool(directory: Path, sentences: str = EXAMPLE, name: str = POOL, file: str = "pool-a", header: str = "") -> Path:
    """Write a pool file under ``parts_of_speech_pools`` and return its path."""
    folder = directory / sentence_pools.POOLS_DIR
    folder.mkdir(exist_ok=True)
    path = folder / f"{file}.yaml"
    path.write_text(f"name: {name}\n{header}{sentences}", encoding="utf-8")
    return path


def _write(directory: Path, pool: str | None = EXAMPLE, body: str = BODY) -> Path:
    """Write the pool (unless ``None``) and a policy whose task has ``body``."""
    if pool is not None:
        _pool(directory, pool)
    path = directory / "policy.yaml"
    path.write_text(_house(body), encoding="utf-8")
    return path


def _document(directory: Path, pool: str | None = EXAMPLE, body: str = BODY) -> dict:
    policy = load(_write(directory, pool, body))
    assert policy is not None
    return policy.task(KEY).document()


def _settings(directory: Path, pool: str = EXAMPLE, body: str = BODY):
    return check_body(_document(directory, pool, body), directory)


def _refused(directory: Path, pool: str | None = EXAMPLE, body: str = BODY) -> str:
    """Load a good policy, then a bad one over it. Return the message; the good policy must stay in force."""
    good = load(_write(directory, EXAMPLE, BODY))
    assert good is not None
    with pytest.raises(ConfigError) as raised:
        load(_write(directory, pool, body), previous=good)
    assert good.task(KEY).document()["pools"] == [POOL]
    message = str(raised.value)
    assert "task 'parts_of_speech/parts-of-speech-1': body." in message
    return message


def _one(sentence: str, parts: str, extra: str = "") -> str:
    return f'sentences:\n  - sentence: "{sentence}"\n{extra}    parts:\n' + textwrap.indent(parts, "      ")


def _many(count: int) -> str:
    return "sentences:\n" + "".join(
        f'  - sentence: "A fox {number}."\n    parts: {{noun: [fox]}}\n' for number in range(count)
    )


def _table(settings, index: int = 0) -> dict[str, list[str]]:
    sentence = settings.sentences[index]
    return {
        part.name: [f"{sentence.words[at].text}[{sentence.words[at].occurrence}]" for at in part.words]
        for part in sentence.parts
    }


# Words


def test_the_example_task_loads_with_its_words_and_pass_mark(tmp_path):
    settings = _settings(tmp_path)
    first, second = settings.sentences
    assert settings.pool_names == (POOL,)
    assert [word.text for word in first.words] == [
        "The", "quick", "brown", "fox", "jumped", "over", "the", "lazy", "dog",
    ]
    assert settings.required == 2
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
    assert 'sentences entry 1: parts: "Dry[1]" is listed under verb and adjective' in message
    message = _refused(tmp_path, _one(DRY, 'verb: [dry, "dry[1]"]\nnoun: [towel]\n'))
    assert 'sentences entry 1: parts.verb: "Dry[1]" is listed more than once' in message
    message = _refused(tmp_path, _one(DRY, 'verb: [dry]\nnoun: [dry]\nadjective: ["dry[1]"]\n'))
    assert "listed under verb, noun, and adjective" in message


def test_the_example_error_names_the_task_pool_sentence_part_and_entry(tmp_path):
    message = _refused(tmp_path, EXAMPLE.replace('adjective: ["dry[2]"]', 'adjective: ["dry[3]"]'))
    assert (
        "task 'parts_of_speech/parts-of-speech-1': body.pool 'Pool A' sentences entry 2: parts.adjective: "
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
    assert f"body.pool 'Pool A' sentences entry 1: parts.verb: {entry}: {says}" in message


def test_an_empty_entry_is_refused(tmp_path):
    message = _refused(tmp_path, _one(DRY, 'verb: [dry, ""]\n'))
    assert "sentences entry 1: parts.verb: entry 2 is empty" in message


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
    assert "sentences entry 1: parts.noun: " in message
    assert says in message


@pytest.mark.parametrize("entry", ["yes", "3", "on", "~"])
def test_an_entry_yaml_does_not_read_as_text_is_refused_with_a_hint_to_quote_it(tmp_path, entry):
    message = _refused(tmp_path, _one("Say yes 3 times on cue.", f"noun: [times, {entry}]\n"))
    assert "sentences entry 1: parts.noun: entry 2 (" in message
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
    ("pool", "says"),
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
def test_a_table_with_nothing_to_sort_is_refused(tmp_path, pool, says):
    message = _refused(tmp_path, pool)
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


def test_a_part_name_of_twenty_characters_is_allowed(tmp_path):
    name = "n" * 20
    settings = _settings(tmp_path, _one("A fox.", f"{name}: [fox]\n"))
    assert settings.sentences[0].parts[0].name == name
    _pool(tmp_path, _one("A fox.", '" ": [fox]\n'))
    with pytest.raises(ValueError, match="parts: a part name must not be empty"):
        check_body({"pools": [POOL]}, tmp_path)


# Timer: the task timeout times a sentence's level of difficulty is the time allowed


def _allowed(settings) -> list[int]:
    return [sentence_pools.allowed_ms(sentence.difficulty, settings.timeout) for sentence in settings.sentences]


def test_a_sentence_gets_the_task_timeout_times_its_level_of_difficulty(tmp_path):
    settings = _settings(tmp_path)
    assert settings.timeout == 45_000
    assert [sentence.difficulty for sentence in settings.sentences] == [1.0, 2.0]
    assert _allowed(settings) == [45_000, 90_000]


def test_the_task_timeout_defaults_to_ninety_seconds(tmp_path):
    settings = _settings(tmp_path, body="pools: [Pool A]\n")
    assert settings.timeout == 90_000
    assert _allowed(settings) == [90_000, 180_000]
    assert _allowed(_settings(tmp_path, body="pools: [Pool A]\ntimeout: 1m\n")) == [60_000, 120_000]


def test_the_pool_level_of_difficulty_is_the_default_for_its_sentences(tmp_path):
    pool = _one("A fox.", "noun: [fox]\n") + _one("A dog.", "noun: [dog]\n").replace("sentences:\n", "")
    pool = pool.replace('  - sentence: "A dog."\n', '  - sentence: "A dog."\n    level_of_difficulty: 1\n')
    _pool(tmp_path, pool, header="level_of_difficulty: 3\n")
    (tmp_path / "policy.yaml").write_text(_house(BODY), encoding="utf-8")
    policy = load(tmp_path / "policy.yaml")
    assert policy is not None
    settings = check_body(policy.task(KEY).document(), tmp_path)
    assert [sentence.difficulty for sentence in settings.sentences] == [3.0, 1.0]
    assert _allowed(settings) == [135_000, 45_000]


def test_the_allowed_time_is_rounded_up_to_whole_seconds():
    assert sentence_pools.allowed_ms(0.5, 45_000) == 23_000
    assert sentence_pools.allowed_ms(1.5, 45_000) == 68_000
    assert sentence_pools.allowed_ms(10, 90_000) == 900_000
    assert sentence_pools.allowed_ms(sentence_pools.DEFAULT_DIFFICULTY, 90_000) == 90_000


@pytest.mark.parametrize("value", ["0s", "45", "soon"])
def test_a_bad_task_timeout_is_refused(tmp_path, value):
    message = _refused(tmp_path, body=f"pools: [Pool A]\ntimeout: {value}\n")
    assert "body.timeout: must be" in message


def test_a_timeout_on_a_sentence_is_refused_in_favour_of_level_of_difficulty(tmp_path):
    message = _refused(tmp_path, EXAMPLE.replace("    level_of_difficulty: 2\n", "    timeout: 60s\n"))
    assert "pool 'Pool A' sentences entry 2: timeout: use level_of_difficulty" in message


@pytest.mark.parametrize("level", [0.5, 1, 2.5, 10])
def test_a_level_of_difficulty_from_one_half_to_ten_is_allowed(tmp_path, level):
    settings = _settings(tmp_path, EXAMPLE.replace("level_of_difficulty: 2", f"level_of_difficulty: {level}"))
    assert settings.sentences[1].difficulty == level
    _pool(tmp_path, EXAMPLE, header=f"level_of_difficulty: {level}\n")
    assert check_body({"pools": [POOL]}, tmp_path).sentences[0].difficulty == level


@pytest.mark.parametrize("level", ["0.4", "0", "-1", "10.5", "100", "hard", "true", "[2]"])
def test_a_level_of_difficulty_outside_the_bounds_is_refused_on_a_sentence_and_on_a_pool(tmp_path, level):
    on_sentence = _refused(tmp_path, EXAMPLE.replace("level_of_difficulty: 2", f"level_of_difficulty: {level}"))
    assert "pool 'Pool A' sentences entry 2: level_of_difficulty: must be a number from 0.5 through 10.0" in on_sentence
    _pool(tmp_path, EXAMPLE, header=f"level_of_difficulty: {level}\n")
    (tmp_path / "policy.yaml").write_text(_house(BODY), encoding="utf-8")
    with pytest.raises(ConfigError) as raised:
        load(tmp_path / "policy.yaml")
    assert "level_of_difficulty: must be a number from 0.5 through 10.0" in str(raised.value)


# Pass mark


@pytest.mark.parametrize(
    ("count", "required"),
    [(1, 1), (2, 2), (3, 3), (4, 3), (5, 4), (7, 5), (8, 6), (9, 7), (10, 7), (11, 7), (20, 7), (100, 7)],
)
def test_the_pass_mark_defaults_to_seventy_percent_rounded_up_and_at_most_seven(count, required):
    assert default_required(count) == required


def test_the_pass_mark_of_a_pool_follows_the_number_of_its_sentences(tmp_path):
    assert _settings(tmp_path, _many(5), "pools: [Pool A]\n").required == 4
    assert _settings(tmp_path, _many(12), "pools: [Pool A]\n").required == 7


def test_the_pass_mark_counts_the_sentences_of_every_pool_named(tmp_path):
    _pool(tmp_path, _many(5), name="Pool B", file="pool-b")
    settings = _settings(tmp_path, _many(5), "pools: [Pool A, Pool B]\n")
    assert len(settings.sentences) == 10
    assert (settings.required, settings.minimum_questions, settings.maximum_questions) == (7, 7, 10)
    assert settings.pool_names == ("Pool A", "Pool B")


def test_an_explicit_pass_mark_is_used(tmp_path):
    assert _settings(tmp_path, body=BODY + "correct_answers_required: 1\n").required == 1


@pytest.mark.parametrize("value", ["0", "-1", "2.5", "3", '"2"'])
def test_a_bad_pass_mark_is_refused(tmp_path, value):
    message = _refused(tmp_path, body=BODY + f"correct_answers_required: {value}\n")
    assert "body.correct_answers_required: must be a whole number from 1" in message


def test_a_pass_mark_beyond_the_runnable_sentences_names_the_count(tmp_path):
    message = _refused(tmp_path, body=BODY + "correct_answers_required: 3\n")
    assert "body.correct_answers_required: must be a whole number from 1 to 2, the number of runnable sentences" in message


# Minimum and maximum questions


def test_the_question_counts_default_to_the_pass_mark_and_the_number_of_sentences(tmp_path):
    settings = _settings(tmp_path, _many(10), "pools: [Pool A]\n")
    assert (settings.required, settings.minimum_questions, settings.maximum_questions) == (7, 7, 10)


def test_explicit_question_counts_are_used(tmp_path):
    body = BODY + "correct_answers_required: 2\nminimum_questions: 3\nmaximum_questions: 5\n"
    settings = _settings(tmp_path, _many(6), body)
    assert (settings.required, settings.minimum_questions, settings.maximum_questions) == (2, 3, 5)


@pytest.mark.parametrize(
    ("extra", "says"),
    [
        ("minimum_questions: 0\n", "body.minimum_questions: must be a whole number from 1"),
        ("minimum_questions: 2.5\n", "body.minimum_questions: must be a whole number from 1"),
        ("minimum_questions: 5\n", "body.minimum_questions: must be a whole number from 1 to 4"),
        ("maximum_questions: 0\n", "body.maximum_questions: must be a whole number from 1"),
        ("maximum_questions: 5\n", "body.maximum_questions: must be a whole number from 3 to 4"),
        ("maximum_questions: 2\n", "body.maximum_questions: must be a whole number from 3 to 4"),
        ("correct_answers_required: 2\nminimum_questions: 4\nmaximum_questions: 3\n", "body.maximum_questions: must be"),
    ],
)
def test_bad_question_counts_are_refused(tmp_path, extra, says):
    assert says in _refused(tmp_path, _many(4), "pools: [Pool A]\n" + extra)


def test_the_pass_mark_may_not_exceed_the_maximum_questions(tmp_path):
    message = _refused(tmp_path, _many(10), "pools: [Pool A]\ncorrect_answers_required: 5\nmaximum_questions: 4\n")
    assert "body.maximum_questions: must be a whole number from 5 to 10" in message


# Pools


def test_an_unknown_pool_is_refused_by_name(tmp_path):
    message = _refused(tmp_path, body="pools: [Pool A, Pool Z]\n")
    assert "body.pools: unknown pool 'Pool Z'" in message


def test_a_task_with_no_pool_directory_names_its_pool_as_unknown(tmp_path):
    message = _refused_without_pools(tmp_path, "pools: [Pool A]\n")
    assert "body.pools: unknown pool 'Pool A'" in message


def _refused_without_pools(directory: Path, body: str) -> str:
    with pytest.raises(ConfigError) as raised:
        load(_write(directory, None, body))
    return str(raised.value)


@pytest.mark.parametrize(
    ("body", "says"),
    [
        ("timeout: 45s\n", "body.pools: required; list one or more pool names"),
        ("pools: []\n", "body.pools: must be a list of one or more pool names"),
        ("pools: Pool A\n", "body.pools: must be a list of one or more pool names"),
        ("pools: [Pool A, ' ']\n", "body.pools entry 2: must be a non-empty pool name"),
        ("pools: [Pool A, 3]\n", "body.pools entry 2: must be a non-empty pool name"),
        ("pools: [Pool A, pool a]\n", "body.pools: 'pool a' is listed more than once"),
        ("pools: [Pool A, Pool A]\n", "body.pools: 'Pool A' is listed more than once"),
    ],
)
def test_the_pools_a_task_names_must_be_a_list_of_distinct_names(tmp_path, body, says):
    assert says in _refused(tmp_path, body=body)


def test_two_pool_files_with_the_same_name_are_refused_naming_both(tmp_path):
    first = _pool(tmp_path, file="pool-a")
    second = _pool(tmp_path, _many(2), file="pool-b")
    with pytest.raises(ConfigError) as raised:
        load(_write(tmp_path, None))
    message = str(raised.value)
    assert "pool 'Pool A' is defined in both" in message
    assert str(first) in message
    assert str(second) in message


def test_a_duplicate_name_is_refused_even_when_no_task_uses_the_pool(tmp_path):
    _pool(tmp_path, _many(2), name="Pool Q", file="pool-q")
    _pool(tmp_path, _many(2), name="Pool Q", file="pool-q2")
    with pytest.raises(ConfigError, match="pool 'Pool Q' is defined in both"):
        load(_write(tmp_path))


def test_a_pool_the_task_does_not_name_is_not_read(tmp_path):
    folder = tmp_path / sentence_pools.POOLS_DIR
    _pool(tmp_path, "sentences: []\n", name="Pool Unused", file="pool-unused")
    settings = _settings(tmp_path)
    assert len(settings.sentences) == 2
    assert (folder / "pool-unused.yaml").exists()


@pytest.mark.parametrize(
    ("pool", "says"),
    [
        ("sentences: []\n", "sentences: must be a list of one or more sentences"),
        ("sentences: The cat sat.\n", "sentences: must be a list of one or more sentences"),
        ("colour: blue\n" + EXAMPLE, "colour: unknown setting"),
        ("", "sentences: required"),
    ],
)
def test_a_bad_pool_file_is_refused(tmp_path, pool, says):
    assert says in _refused(tmp_path, pool)


def test_a_pool_file_without_a_name_is_refused(tmp_path):
    folder = tmp_path / sentence_pools.POOLS_DIR
    folder.mkdir()
    (folder / "nameless.yaml").write_text(EXAMPLE, encoding="utf-8")
    with pytest.raises(ConfigError, match="name: required"):
        load(_write(tmp_path, None))


@pytest.mark.parametrize(
    ("pool", "says"),
    [
        ("sentences:\n  - \"The cat sat.\"\n", "sentences entry 1: must be a mapping with sentence and parts"),
        ("sentences:\n  - parts: {noun: [cat]}\n", "sentences entry 1: sentence: required"),
        ('sentences:\n  - sentence: "The cat sat."\n', "sentences entry 1: parts: required"),
        (EXAMPLE.replace("    level_of_difficulty: 2\n", "    colour: blue\n"), "sentences entry 2: colour: unknown setting"),
    ],
)
def test_a_bad_sentence_in_a_pool_is_refused_naming_the_pool_and_entry(tmp_path, pool, says):
    assert f"body.pool 'Pool A' {says}" in _refused(tmp_path, pool)


def test_the_sentences_of_several_pools_run_together_in_the_order_named(tmp_path):
    _pool(tmp_path, _one("A dog barked.", "noun: [dog]\n"), name="Pool B", file="pool-b")
    settings = _settings(tmp_path, body="pools: [Pool B, Pool A]\ntimeout: 45s\n")
    assert [sentence.text for sentence in settings.sentences] == [
        "A dog barked.",
        "The quick, brown fox jumped over the lazy dog.",
        DRY,
    ]
    assert settings.pool_names == ("Pool B", "Pool A")


def test_pool_files_written_by_the_portal_helper_load(tmp_path):
    sentence_pools.write_pool(
        tmp_path / sentence_pools.POOLS_DIR,
        "written",
        "Written",
        [{"sentence": "The cat sat.", "parts": {"noun": ["cat"]}}],
        difficulty=2.5,
    )
    settings = _settings(tmp_path, None, "pools: [Written]\ntimeout: 40s\n")
    assert [sentence.difficulty for sentence in settings.sentences] == [2.5]
    assert _allowed(settings) == [100_000]


# Filtering the parts


def test_the_parts_of_speech_filter_fixes_the_rows_for_every_sentence(tmp_path):
    settings = _settings(tmp_path, body=BODY + "parts_of_speech: [verb, Noun, pronoun]\n")
    assert settings.parts_filter == ("verb", "Noun", "pronoun")
    assert _table(settings, 0) == {"verb": ["jumped[1]"], "Noun": ["fox[1]", "dog[1]"], "pronoun": []}
    assert _table(settings, 1) == {"verb": ["Dry[1]"], "Noun": ["dishes[1]", "towel[1]"], "pronoun": []}


def test_a_filter_drops_the_parts_it_does_not_name(tmp_path):
    settings = _settings(tmp_path, body=BODY + "parts_of_speech: [verb]\n")
    assert [part.name for part in settings.sentences[0].parts] == ["verb"]
    assert settings.sentences[0].part_of(1) is None  # quick was an adjective, now in no row


def test_without_a_filter_each_sentence_keeps_its_own_parts(tmp_path):
    settings = _settings(tmp_path)
    assert settings.parts_filter is None
    assert [part.name for part in settings.sentences[0].parts] == ["noun", "verb", "adjective"]


@pytest.mark.parametrize(
    ("value", "says"),
    [
        ("[]", "body.parts_of_speech: must be a list of one or more part names"),
        ("noun", "body.parts_of_speech: must be a list of one or more part names"),
        ('["noun", ""]', "body.parts_of_speech entry 2: a part name must not be empty"),
        ("[noun, Noun]", "body.parts_of_speech entry 2: 'Noun' is the same as 'noun'"),
        (f"[{'n' * 21}]", "body.parts_of_speech entry 1: a part name is at most 20 characters"),
    ],
)
def test_a_bad_parts_filter_is_refused(tmp_path, value, says):
    assert says in _refused(tmp_path, body=BODY + f"parts_of_speech: {value}\n")


# Fields


@pytest.mark.parametrize(
    ("extra", "says"),
    [
        ("colour: blue\n", "body.colour: unknown setting"),
        ("correct_answers_required: many\n", "body.correct_answers_required: must be a whole number"),
    ],
)
def test_unknown_and_malformed_body_fields_are_refused(tmp_path, extra, says):
    assert says in _refused(tmp_path, body=BODY + extra)


def test_field_checks_alone_do_not_read_the_pool_files():
    settings = parse_settings({"pools": ["No Such Pool"], "timeout": "30s", "correct_answers_required": 2})
    assert settings.pool_names == ("No Such Pool",)
    assert settings.timeout == 30_000
    assert settings.sentences == ()
    with pytest.raises(ValueError, match="pools: required"):
        parse_settings({"timeout": "30s"})
    with pytest.raises(ValueError, match="pools: must be a list of one or more pool names"):
        parse_settings({"pools": []})


def test_a_service_that_does_not_mount_the_data_loads_the_task_by_its_fields(tmp_path):
    path = _write(tmp_path, None, "pools: [Pool A]\ntimeout: 45s\n")
    policy = load(path, task_data=False)
    assert policy is not None
    assert policy.task(KEY).document()["pools"] == [POOL]


# Inline sentences: migration into pools


def test_inline_sentences_are_refused_by_the_body_check(tmp_path):
    body = yaml.safe_load(INLINE)
    with pytest.raises(ValueError, match="sentences: use pools; inline sentences are no longer allowed"):
        check_body(body, tmp_path)


def test_a_policy_with_inline_sentences_is_rewritten_into_a_pool_when_it_loads(tmp_path):
    path = _write(tmp_path, None, INLINE)
    policy = load(path)
    assert policy is not None

    text = path.read_text(encoding="utf-8")
    assert "sentences" not in text.replace("parts-of-speech-1 sentences", "")
    assert "pools:" in text
    assert "parts-of-speech-1 sentences" in text
    assert "timeout: 45s" in text

    files = sorted((tmp_path / sentence_pools.POOLS_DIR).glob("*.yaml"))
    assert [file.name for file in files] == ["parts-of-speech-1-sentences.yaml"]
    stored = yaml.safe_load(files[0].read_text(encoding="utf-8"))
    assert stored["name"] == "parts-of-speech-1 sentences"
    assert all("timeout" not in item for item in stored["sentences"])

    settings = check_body(policy.task(KEY).document(), tmp_path)
    assert settings.pool_names == ("parts-of-speech-1 sentences",)
    assert [sentence.text for sentence in settings.sentences] == [
        "The quick, brown fox jumped over the lazy dog.",
        DRY,
    ]
    assert _table(settings, 1) == {"verb": ["Dry[1]"], "noun": ["dishes[1]", "towel[1]"], "adjective": ["dry[2]"]}
    assert settings.required == 2


def test_a_sentence_timeout_migrates_to_its_ratio_to_the_task_timeout(tmp_path):
    policy = load(_write(tmp_path, None, INLINE))
    assert policy is not None
    settings = check_body(policy.task(KEY).document(), tmp_path)
    assert [sentence.difficulty for sentence in settings.sentences] == [1.0, 2.0]
    assert _allowed(settings) == [45_000, 90_000]


def test_migration_keeps_a_sentence_time_between_the_difficulty_bounds(tmp_path):
    body = INLINE.replace("timeout: 90s", "timeout: 1s")
    policy = load(_write(tmp_path, None, body))
    assert policy is not None
    settings = check_body(policy.task(KEY).document(), tmp_path)
    assert settings.sentences[1].difficulty == sentence_pools.MIN_DIFFICULTY


def test_loading_again_after_migration_changes_nothing(tmp_path):
    path = _write(tmp_path, None, INLINE)
    load(path)
    text = path.read_text(encoding="utf-8")
    pools = {file.name: file.read_text(encoding="utf-8") for file in (tmp_path / sentence_pools.POOLS_DIR).iterdir()}
    assert load(path) is not None
    assert path.read_text(encoding="utf-8") == text
    assert {file.name: file.read_text(encoding="utf-8") for file in (tmp_path / sentence_pools.POOLS_DIR).iterdir()} == pools


def test_the_migrated_pool_gets_a_new_name_when_the_obvious_one_is_taken(tmp_path):
    _pool(tmp_path, _many(1), name="parts-of-speech-1 sentences", file="taken")
    policy = load(_write(tmp_path, None, INLINE))
    assert policy is not None
    assert policy.task(KEY).document()["pools"] == ["parts-of-speech-1 sentences 2"]


def test_migration_reports_the_files_it_wrote(tmp_path):
    path = _write(tmp_path, None, INLINE)
    written = sentence_pools.migrate_policy(path)
    assert path in written
    assert tmp_path / sentence_pools.POOLS_DIR / "parts-of-speech-1-sentences.yaml" in written
    assert sentence_pools.migrate_policy(path) == []


def test_inline_sentences_that_were_wrong_still_fail_the_load_after_migration(tmp_path):
    bad = INLINE.replace("noun: [fox, dog]", "noun: [fox, cat]")
    with pytest.raises(ConfigError) as raised:
        load(_write(tmp_path, None, bad))
    message = str(raised.value)
    assert "task 'parts_of_speech/parts-of-speech-1': body.pool 'parts-of-speech-1 sentences'" in message
    assert '"cat" is not in the sentence' in message


# What a run keeps


def test_a_run_snapshot_keeps_the_resolved_sentences_and_their_difficulty(tmp_path):
    document = _document(tmp_path, body=BODY + "parts_of_speech: [noun, verb]\ncorrect_answers_required: 1\n")
    settings = check_body(document, tmp_path)
    snapshot = snapshot_settings(settings, document)
    assert snapshot["pools"] == [POOL]
    assert snapshot["parts_of_speech"] == ["noun", "verb"]
    assert [item["level_of_difficulty"] for item in snapshot["sentences"]] == [1.0, 2.0]

    again = check_body(snapshot)  # needs no pool files
    assert [sentence.text for sentence in again.sentences] == [sentence.text for sentence in settings.sentences]
    assert [sentence.difficulty for sentence in again.sentences] == [1.0, 2.0]
    assert _table(again, 1) == _table(settings, 1)
    assert (again.required, again.minimum_questions, again.maximum_questions) == (1, 1, 2)
    assert again.timeout == 45_000
