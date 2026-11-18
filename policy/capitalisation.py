"""Capitalisation quiz: sentence pools and the run.

A task of type ``capitalisation`` keeps its fields in ``body``. The body names
one or more pools. Each pool is a YAML file under ``capitalisation_pools/``
beside the policy, stored, named, and loaded as a parts of speech pool is.
Pools and sentences are checked when the policy is loaded.

A word is a run of characters between spaces, punctuation included. A word has
a capital when any of its letters is upper case. The page shows the sentence in
lower case and he clicks the words that need a capital. He has three tries per
sentence, worth 1, 0.5, and 0.25 points. A try is right when the words he
clicked are exactly the words that have a capital in the pool, compared by
position. The run, its timer, and its end conditions are the parts of speech
ones, in ``policy.parts_of_speech``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from policy import parts_of_speech, sentence_pools
from policy.parts_of_speech import Judged, PoolKind, Settings
from policy.quiz import is_whole

CAPITALISATION = "capitalisation"
LABEL = "Capitalisation"
DEFAULT_TIMEOUT = "60s"

_BODY_KEYS = frozenset(
    {
        "pools",
        "timeout",
        "correct_answers_required",
        "minimum_questions",
        "maximum_questions",
    }
)
_SENTENCE_KEYS = frozenset({"sentence", "level_of_difficulty"})


@dataclass(frozen=True)
class Sentence:
    """A sentence as the pool spells it, and its difficulty."""

    text: str
    difficulty: float

    @property
    def words(self) -> tuple[str, ...]:
        return split_words(self.text)

    @property
    def capitals(self) -> tuple[int, ...]:
        """Return the positions of the words that have a capital."""
        return tuple(position for position, word in enumerate(self.words) if has_capital(word))


def split_words(text: str) -> tuple[str, ...]:
    """Return the words of ``text``: the runs of characters between spaces."""
    return tuple(text.split())


def has_capital(word: str) -> bool:
    return any(char.isupper() for char in word)


def has_letter(word: str) -> bool:
    return any(char.isalpha() for char in word)


def clicked_form(word: str) -> str:
    """Return a word as it shows once clicked: as the pool spells it, or with only its first letter capitalised."""
    if has_capital(word):
        return word
    for at, char in enumerate(word):
        if char.isalpha():
            return word[:at] + char.upper() + word[at + 1 :]
    return word


def _pool_sentence(item: object, pool_difficulty: float, _filter: object, where: str) -> Sentence:
    if isinstance(item, str):
        text, difficulty = item, pool_difficulty
    elif isinstance(item, Mapping):
        unknown = sorted(set(item) - _SENTENCE_KEYS)
        if unknown:
            raise ValueError(f"{where}: {unknown[0]}: unknown setting")
        if "sentence" not in item:
            raise ValueError(f"{where}: sentence: required")
        text = item["sentence"]
        difficulty = pool_difficulty
        if "level_of_difficulty" in item:
            difficulty = sentence_pools.parse_difficulty(item["level_of_difficulty"], f"{where}: level_of_difficulty")
    else:
        raise ValueError(f"{where}: must be a sentence, or a mapping with sentence and level_of_difficulty")
    if not isinstance(text, str):
        raise ValueError(f"{where}: sentence: must be text")
    words = split_words(text)
    if not words:
        raise ValueError(f"{where}: sentence: must not be empty")
    if not any(has_capital(word) for word in words):
        raise ValueError(f"{where}: sentence: {text.strip()!r} has no capital letter, so there is nothing to click")
    return Sentence(" ".join(words), difficulty)


KIND = PoolKind(
    _BODY_KEYS,
    DEFAULT_TIMEOUT,
    sentence_pools.CAPITALISATION_DIR,
    _pool_sentence,
    filtered=False,
    inline=False,
    unique=True,
)


def parse_settings(body: Mapping, root: Path | None = None) -> Settings:
    """Check a capitalisation task body without reading pool files."""
    if not isinstance(body, Mapping):
        raise ValueError("body must be a mapping")
    return parts_of_speech.parse_pooled_fields(body, None, root, KIND)


def check_body(body: Mapping, root: Path | None = None) -> Settings:
    """Check a capitalisation task body and its named pools, as the policy load does."""
    if not isinstance(body, Mapping):
        raise ValueError("body must be a mapping")
    return parts_of_speech.parse_pooled_fields(body, parts_of_speech.resolve_pools(body, root, KIND), root, KIND)


def _parse_snapshot(body: Mapping) -> Settings:
    """Parse the settings a run stored: the task's fields with the resolved sentences."""
    listed = body["sentences"]
    sentences = tuple(
        Sentence(str(item["sentence"]), float(item.get("level_of_difficulty", sentence_pools.DEFAULT_DIFFICULTY)))
        for item in listed
        if isinstance(item, Mapping) and isinstance(item.get("sentence"), str)
    )
    if not sentences or len(sentences) != len(listed):
        raise ValueError("sentences: a run needs its sentences")
    size = len(sentences)
    timeout = parts_of_speech.duration(body.get("timeout", DEFAULT_TIMEOUT), "timeout")
    required = body.get("correct_answers_required", parts_of_speech.default_required(size))
    least = body.get("minimum_questions", required)
    most = body.get("maximum_questions", size)
    for field, value in (("correct_answers_required", required), ("minimum_questions", least), ("maximum_questions", most)):
        if not is_whole(value) or not 1 <= value <= size:
            raise ValueError(f"{field}: must be a whole number from 1 to {size}")
    pools = body.get("pools")
    names = tuple(str(item) for item in pools) if isinstance(pools, list) else ()
    return Settings(sentences, timeout, int(required), int(least), int(most), None, names)


class Session(parts_of_speech.Session):
    """The capitalisation record on one attempt."""

    NOTHING_TO_SUBMIT = "click at least one word before submitting"
    SAME_AS_LAST = "the clicked words are the same as the last try"

    def parse(self, body: object) -> Settings:
        if not isinstance(body, Mapping):
            raise ValueError("body must be a mapping")
        if "sentences" in body:
            return _parse_snapshot(body)
        return check_body(body, self.root)

    def snapshot(self, settings: Settings) -> dict:
        timeout = self.body.get("timeout", DEFAULT_TIMEOUT)
        return {
            "timeout": timeout if isinstance(timeout, str) else DEFAULT_TIMEOUT,
            "pools": list(settings.pool_names),
            "correct_answers_required": settings.required,
            "minimum_questions": settings.minimum_questions,
            "maximum_questions": settings.maximum_questions,
            "sentences": [
                {"sentence": sentence.text, "level_of_difficulty": sentence.difficulty}
                for sentence in settings.sentences
            ],
        }

    def question_fields(self, sentence) -> dict:
        return {"words": [{"word": word, "capital": has_capital(word)} for word in sentence.words]}

    def read_try(self, sent: object, question: Mapping):
        """Check the numbers of the words he clicked, and return them in order along with the set of them."""
        if not isinstance(sent, list):
            raise ValueError("a try lists the numbers of the clicked words")
        count = len(question["words"])
        clicked: list[int] = []
        for position in sent:
            if not is_whole(position) or not 0 <= position < count:
                raise ValueError(f"word {position!r} is not in the sentence")
            if position in clicked:
                raise ValueError(f"word {position} is clicked more than once")
            clicked.append(position)
        return clicked, frozenset(clicked)

    def stored_try(self, table) -> dict:
        return {"clicks": table}

    def placed_in(self, recorded: Mapping):
        return frozenset(recorded["clicks"])

    def score(self, question: Mapping, placed) -> tuple[list[int], list[int]]:
        capital = [item["capital"] for item in question["words"]]
        wrong = sorted(position for position in placed if not capital[position])
        missed = [position for position, needs in enumerate(capital) if needs and position not in placed]
        return wrong, missed


def answer(question: Mapping) -> list[dict]:
    """Return every word of a finished sentence as the pool spells it, and its colour.

    His clicks are the last try's, or none when the sentence closed without one.
    """
    tries = question["tries"]
    return marked(question, tries[-1]["clicks"] if tries else ())


def marked(question: Mapping, clicks) -> list[dict]:
    """Return every word of a sentence as the pool spells it, with the colour it takes when ``clicks`` are the words clicked.

    A word with a capital that he clicked is blue. A word he clicked that has
    no capital, and a word with a capital he did not click, are red. Every
    other word is black.
    """
    clicked = set(clicks)
    shown = []
    for position, word in enumerate(question["words"]):
        here = position in clicked
        if word["capital"]:
            colour = "blue" if here else "red"
        else:
            colour = "red" if here else "black"
        shown.append({"word": word["word"], "colour": colour})
    return shown


def sentence_words(question: Mapping) -> list[dict]:
    """Return the words for the page: lower case, whether it has a letter to click, and what clicking it shows."""
    return [
        {"text": item["word"].lower(), "click": has_letter(item["word"]), "shown": clicked_form(item["word"])}
        for item in question["words"]
    ]


__all__ = [
    "CAPITALISATION",
    "LABEL",
    "Judged",
    "Session",
    "Sentence",
    "answer",
    "marked",
    "check_body",
    "parse_settings",
    "sentence_words",
]
