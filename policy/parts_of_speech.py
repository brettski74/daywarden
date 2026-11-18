"""Parts of speech quiz: sentence pools, the parts table, and the run.

A task of type ``parts_of_speech`` keeps its fields in ``body``. The body
names one or more sentence pools. Each pool is a YAML file under
``parts_of_speech_pools/`` beside the policy. Pools and sentences are checked
when the policy is loaded, so a typo fails the load, the error names the
task, the pool or sentence, the part, and the entry, and the previous policy
stays in force.

A word is a run of letters and digits. An apostrophe or a hyphen with a
letter or digit on both sides joins the runs either side into one word.
Everything else is punctuation, shown but never sorted. Words are compared
without regard to case, and ``’`` is the same as ``'``. An entry names a
word and, in square brackets, which of its occurrences: ``dry``,
``dry[2]``, or ``dry[2,3]``. Without brackets it is the first.

The parts keep the order and spelling they were written in. Each is a row
of the child's table. A task may set ``parts_of_speech`` to fix the rows for
every sentence in the run.

A run never asks the same sentence twice. Each new question is chosen
uniformly from the unseen runnable sentences. He has three tries per
sentence, worth 1, 0.5, and 0.25 points. The server judges every try and
fixes each sentence's deadline when it issues it. Pass and fail follow the
skip-counting model: points against ``correct_answers_required``, with
``minimum_questions`` and ``maximum_questions``.
"""

from __future__ import annotations

import json
import random
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from policy import sentence_pools
from policy.problems import Collector
from policy.quiz import (
    CORRECT,
    INCORRECT,
    NETWORK_ALLOWANCE_MS,
    TIMEOUT,
    QuizRecord,
    StaleQuestion,
    duration,
    is_whole,
    stamp,
)
from policy.tasks import FAILURE, PASS

PARTS_OF_SPEECH = "parts_of_speech"
LABEL = "Parts of speech"
WRONG = "wrong"
TRIES = 3
POINTS = (1, 0.5, 0.25)
DEFAULT_TIMEOUT = "90s"
LONGEST_PART = 20
DEFAULT_REQUIRED_CAP = 7

_BODY_KEYS = frozenset(
    {
        "pools",
        "timeout",
        "parts_of_speech",
        "correct_answers_required",
        "minimum_questions",
        "maximum_questions",
        "sentences",  # snapshotted runs only; refused on a policy body
    }
)
_SENTENCE_KEYS = frozenset({"sentence", "parts", "level_of_difficulty", "timeout"})
_JOINERS = frozenset("'\u2019-")
_ENTRY = re.compile(r"(?P<word>[^\[\]]*)\[(?P<numbers>[^\[\]]*)\]")
_NUMBER = re.compile(r"[0-9]+")
_BRACKETS = "the brackets hold occurrence numbers counted from 1, separated by commas, such as dry[2] or dry[2,3]"


@dataclass(frozen=True)
class Word:
    """One word of a sentence as written, and where it sits.

    ``start`` and ``end`` are character offsets into the sentence text.
    ``occurrence`` counts from 1 among the words of the sentence that
    compare the same.
    """

    text: str
    start: int
    end: int
    occurrence: int

    @property
    def key(self) -> str:
        return word_key(self.text)


@dataclass(frozen=True)
class Part:
    """One row of the table: its name, and the positions of the words that belong in it, in sentence order."""

    name: str
    words: tuple[int, ...]


@dataclass(frozen=True)
class Sentence:
    """A sentence, its words, its effective parts for the run, and its difficulty."""

    text: str
    words: tuple[Word, ...]
    parts: tuple[Part, ...]
    difficulty: float

    def part_of(self, position: int) -> str | None:
        """Return the name of the part the word at ``position`` belongs in, or None for a word in no row."""
        for part in self.parts:
            if position in part.words:
                return part.name
        return None


@dataclass(frozen=True)
class Settings:
    """One run's parts of speech settings. ``timeout`` is the body's, in milliseconds."""

    sentences: tuple[Sentence, ...]
    timeout: int
    required: int
    minimum_questions: int
    maximum_questions: int
    parts_filter: tuple[str, ...] | None = None
    pool_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class PoolKind:
    """What differs between task types that draw sentences from pools: the body's keys, folder, default timeout, and sentence check.

    ``parse_sentence`` takes a pool's raw sentence, the pool's level of
    difficulty, the task's parts filter (None when the kind has none), and
    where the sentence is, and raises ``ValueError`` for a bad one.
    """

    keys: frozenset[str]
    default_timeout: str
    folder: str
    parse_sentence: Callable[..., object]
    filtered: bool = True
    inline: bool = True
    unique: bool = False  # a sentence may not be in its pool twice


def word_key(text: str) -> str:
    """Return the form two words are compared by: case folded, with ``’`` as ``'``."""
    return unicodedata.normalize("NFC", text).replace("\u2019", "'").casefold()


def split_words(text: str) -> tuple[Word, ...]:
    """Return the words of ``text`` in order, each with its occurrence number."""
    found: list[Word] = []
    counts: dict[str, int] = {}
    position = 0
    length = len(text)
    while position < length:
        if not _letter(text[position]):
            position += 1
            continue
        start = position
        position += 1
        while position < length:
            char = text[position]
            if _letter(char):
                position += 1
            elif char in _JOINERS and position + 1 < length and _letter(text[position + 1]):
                position += 2
            else:
                break
        piece = text[start:position]
        key = word_key(piece)
        counts[key] = counts.get(key, 0) + 1
        found.append(Word(piece, start, position, counts[key]))
    return tuple(found)


def default_required(count: int) -> int:
    """Return min(7, 70% of ``count`` rounded up), at least 1 when ``count`` ≥ 1."""
    if count < 1:
        return 0
    return min(DEFAULT_REQUIRED_CAP, -(-7 * count // 10))


def parse_settings(body: Mapping, root: Path | None = None) -> Settings:
    """Check a parts of speech task body without reading pool files.

    Pool names and the field shape are checked. Counts that need the runnable
    size are only type-checked here; ``check_body`` finishes them against the
    pools. A snapshotted run body (pools plus resolved sentences) is parsed
    fully.
    """
    if not isinstance(body, Mapping):
        raise ValueError("body must be a mapping")
    if _is_snapshot(body):
        return _parse_snapshot(body)
    return _parse_fields(body, None, root, PARTS_KIND)


def check_body(body: Mapping, root: Path | None = None) -> Settings:
    """Check a parts of speech task body and its named pools, as the policy load does."""
    if not isinstance(body, Mapping):
        raise ValueError("body must be a mapping")
    if _is_snapshot(body):
        return _parse_snapshot(body)
    return _parse_fields(body, _resolve_pools(body, root), root, PARTS_KIND)


def _is_snapshot(body: Mapping) -> bool:
    """Return whether ``body`` is a run snapshot (pools plus resolved sentence positions).

    A hand-written or portal body that still has word-entry ``sentences`` beside
    ``pools`` is not a snapshot: those sentences are refused by ``check_body``.
    """
    if "pools" not in body:
        return False
    listed = body.get("sentences")
    if not isinstance(listed, list) or not listed:
        return False
    for item in listed:
        if not isinstance(item, Mapping):
            return False
        parts = item.get("parts")
        if not isinstance(parts, Mapping):
            return False
        for entries in parts.values():
            if not isinstance(entries, list):
                return False
            for entry in entries:
                if isinstance(entry, str):
                    return False
                if not is_whole(entry):
                    return False
    return True


def parse_pooled_fields(
    body: Mapping, pools: dict[str, sentence_pools.Pool] | None, root: Path | None, kind: PoolKind
) -> Settings:
    """Check a task body that names sentence pools, for ``kind``. Without ``pools`` only the fields are checked."""
    return _parse_fields(body, pools, root, kind)


def resolve_pools(body: Mapping, root: Path | None, kind: PoolKind) -> dict[str, sentence_pools.Pool]:
    """Load the pools a body names from ``kind``'s folder. A duplicate pool name anywhere in it is an error."""
    return _resolve_pools(body, root, kind)


def _parse_fields(
    body: Mapping, pools: dict[str, sentence_pools.Pool] | None, root: Path | None, kind: PoolKind
) -> Settings:
    fields = Collector()
    unknown = set(body) - kind.keys
    inline = kind.inline and "sentences" in body and not _is_snapshot(body)
    if inline and pools is not None:
        fields.add("sentences: use pools; inline sentences are no longer allowed")
        unknown.discard("sentences")
    elif inline:
        unknown.discard("sentences")
    for key in sorted(unknown):
        fields.add(f"{key}: unknown setting")

    timeout = fields.take(duration, body.get("timeout", kind.default_timeout), "timeout")
    names = body.get("pools")
    if "pools" not in body:
        if pools is not None or not inline:
            fields.add("pools: required; list one or more pool names")
        names = None
    elif not isinstance(names, list) or not names:
        fields.add("pools: must be a list of one or more pool names")
        names = None
    else:
        seen: set[str] = set()
        cleaned: list[str] = []
        for number, item in enumerate(names, 1):
            if not isinstance(item, str) or not item.strip():
                fields.add(f"pools entry {number}: must be a non-empty pool name")
                continue
            name = item.strip()
            if name.casefold() in {other.casefold() for other in seen}:
                fields.add(f"pools: {name!r} is listed more than once")
                continue
            seen.add(name)
            cleaned.append(name)
        names = cleaned or None

    parts_filter = None
    if kind.filtered and "parts_of_speech" in body:
        parts_filter = fields.take(_parts_filter, body["parts_of_speech"], "parts_of_speech")

    for field in ("correct_answers_required", "minimum_questions", "maximum_questions"):
        if field in body:
            fields.take(_count_value, body[field], field)

    if pools is None:
        # Field-only check: no pool directory. Finish shape errors and return a stub.
        fields.finish()
        assert timeout is not None
        size = 1
        required = body["correct_answers_required"] if "correct_answers_required" in body else default_required(size)
        least = body["minimum_questions"] if "minimum_questions" in body else required
        most = body["maximum_questions"] if "maximum_questions" in body else size
        return Settings(
            (),
            timeout,
            int(required),
            int(least),
            int(most),
            parts_filter,
            tuple(names or ()),
        )

    if names is None:
        fields.finish()
        raise AssertionError("unreachable")

    sentences: list[Sentence] = []
    for name in names:
        pool = pools.get(name)
        if pool is None:
            fields.add(f"pools: unknown pool {name!r}")
            continue
        if not pool.sentences:
            fields.add(f"pools: pool {name!r} has no sentences")
            continue
        first: dict[str, int] = {}
        for number, item in enumerate(pool.sentences, 1):
            where = f"pool {name!r} sentences entry {number}"
            sentence = fields.take(kind.parse_sentence, item, pool.difficulty, parts_filter, where)
            if sentence is None:
                continue
            if kind.unique:
                folded = sentence.text.casefold()
                if folded in first:
                    fields.add(f"{where}: sentence: {sentence.text!r} is the same as entry {first[folded]}")
                    continue
                first[folded] = number
            sentences.append(sentence)

    size = len(sentences)
    required = default_required(size) if size else 1
    if "correct_answers_required" in body:
        required = body["correct_answers_required"]
        if not is_whole(required) or size < 1 or not 1 <= required <= size:
            fields.add(
                f"correct_answers_required: must be a whole number from 1 to {max(size, 1)}, "
                "the number of runnable sentences"
            )
            required = default_required(size) if size else 1
    least = required
    if "minimum_questions" in body:
        least = body["minimum_questions"]
        if not is_whole(least) or size < 1 or not 1 <= least <= size:
            fields.add(f"minimum_questions: must be a whole number from 1 to {max(size, 1)}")
            least = required
    most = size if size else 1
    if "maximum_questions" in body:
        most = body["maximum_questions"]
        floor = max(least if is_whole(least) else 1, required if is_whole(required) else 1)
        if not is_whole(most) or size < 1 or not floor <= most <= size:
            fields.add(
                f"maximum_questions: must be a whole number from {floor} to {max(size, 1)}"
            )
            most = size if size else 1
    elif size:
        most = size

    if size and is_whole(required) and is_whole(least) and is_whole(most):
        if least > most:
            fields.add("minimum_questions: must be no more than maximum_questions")
        if required > most:
            fields.add("correct_answers_required: must be no more than maximum_questions, or he could never pass")

    fields.finish()
    assert timeout is not None
    return Settings(
        tuple(sentences),
        timeout,
        int(required),
        int(least),
        int(most),
        parts_filter,
        tuple(names),
    )


def _resolve_pools(body: Mapping, root: Path | None, kind: PoolKind | None = None) -> dict[str, sentence_pools.Pool]:
    folder = sentence_pools.POOLS_DIR if kind is None else kind.folder
    names = body.get("pools")
    if not isinstance(names, list):
        return {}
    wanted = [item.strip() for item in names if isinstance(item, str) and item.strip()]
    # Duplicate names across pool files are a load error even for unused pools.
    sentence_pools.index_names(root, folder)
    return sentence_pools.load_named(wanted, root, folder)


def _parse_snapshot(body: Mapping) -> Settings:
    fields = Collector()
    timeout = fields.take(duration, body.get("timeout", DEFAULT_TIMEOUT), "timeout")
    parts_filter = None
    if "parts_of_speech" in body:
        raw = body["parts_of_speech"]
        if isinstance(raw, list):
            parts_filter = tuple(str(item) for item in raw)
    listed = body.get("sentences")
    assert isinstance(listed, list)
    sentences = tuple(
        fields.take(_snapshot_sentence, item, f"sentences entry {number}")
        for number, item in enumerate(listed, 1)
    )
    size = len(sentences)
    required = body.get("correct_answers_required", default_required(size))
    least = body.get("minimum_questions", required)
    most = body.get("maximum_questions", size)
    for field, value in (
        ("correct_answers_required", required),
        ("minimum_questions", least),
        ("maximum_questions", most),
    ):
        if not is_whole(value) or (size and not 1 <= value <= size):
            fields.add(f"{field}: must be a whole number from 1 to {max(size, 1)}")
    pools = body.get("pools")
    pool_names = tuple(str(item) for item in pools) if isinstance(pools, list) else ()
    fields.finish()
    assert timeout is not None
    return Settings(sentences, timeout, int(required), int(least), int(most), parts_filter, pool_names)


def _snapshot_sentence(item: object, where: str) -> Sentence:
    if not isinstance(item, Mapping):
        raise ValueError(f"{where}: must be a mapping with sentence and parts")
    text = item.get("sentence")
    if not isinstance(text, str):
        raise ValueError(f"{where}: sentence: required")
    words = split_words(text)
    parts_table = item.get("parts")
    if not isinstance(parts_table, Mapping):
        raise ValueError(f"{where}: parts: required")
    parts = tuple(Part(str(name), tuple(int(at) for at in entries)) for name, entries in parts_table.items())
    difficulty = float(item.get("level_of_difficulty", sentence_pools.DEFAULT_DIFFICULTY))
    return Sentence(text, words, parts, difficulty)


def _count_value(value: object, field: str) -> int:
    if not is_whole(value) or value < 1:
        raise ValueError(f"{field}: must be a whole number from 1")
    return int(value)


def _parts_filter(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{where}: must be a list of one or more part names")
    names: dict[str, str] = {}
    result: list[str] = []
    for number, item in enumerate(value, 1):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{where} entry {number}: a part name must not be empty")
        name = item.strip()
        if len(name) > LONGEST_PART:
            raise ValueError(
                f"{where} entry {number}: a part name is at most {LONGEST_PART} characters, so the table stays narrow"
            )
        folded = name.casefold()
        if folded in names:
            raise ValueError(
                f"{where} entry {number}: {name!r} is the same as {names[folded]!r}; "
                "part names must differ by more than case"
            )
        names[folded] = name
        result.append(name)
    return tuple(result)


def check_pool_sentence(item: object, pool_difficulty: float, where: str) -> Sentence:
    """Check one sentence of a pool as the policy load does, with no parts filter."""
    return _sentence(item, pool_difficulty, where)


def _pool_sentence(
    item: object, pool_difficulty: float, parts_filter: tuple[str, ...] | None, where: str
) -> Sentence:
    parsed = _sentence(item, pool_difficulty, where)
    return _apply_filter(parsed, parts_filter)


PARTS_KIND = PoolKind(_BODY_KEYS, DEFAULT_TIMEOUT, sentence_pools.POOLS_DIR, _pool_sentence)


def _sentence(item: object, default_difficulty: float, where: str) -> Sentence:
    if not isinstance(item, Mapping):
        raise ValueError(f"{where}: must be a mapping with sentence and parts")
    unknown = sorted(set(item) - _SENTENCE_KEYS)
    if unknown:
        raise ValueError(f"{where}: {unknown[0]}: unknown setting")
    if "timeout" in item:
        raise ValueError(f"{where}: timeout: use level_of_difficulty; per-sentence timeout is no longer allowed")
    if "sentence" not in item:
        raise ValueError(f"{where}: sentence: required")
    text = item["sentence"]
    if not isinstance(text, str):
        raise ValueError(f"{where}: sentence: must be text")
    words = split_words(text)
    if not words:
        raise ValueError(f"{where}: sentence: must contain at least one word")
    difficulty = default_difficulty
    if "level_of_difficulty" in item:
        difficulty = sentence_pools.parse_difficulty(item["level_of_difficulty"], f"{where}: level_of_difficulty")
    if "parts" not in item:
        raise ValueError(f"{where}: parts: required")
    table = item["parts"]
    if not isinstance(table, Mapping) or not table:
        raise ValueError(
            f"{where}: parts: must map one or more part of speech names to lists of words, "
            "such as noun: [fox, dog]"
        )
    names: dict[str, str] = {}
    owners: dict[int, list[str]] = {}
    parts: list[Part] = []
    for written, entries in table.items():
        name = _part_name(written, names, where)
        here = f"{where}: parts.{name}"
        if not isinstance(entries, list):
            raise ValueError(
                f"{here}: must be a list of words, such as [fox, dog]; write [] for a row with nothing in it"
            )
        positions: list[int] = []
        for number, entry in enumerate(entries, 1):
            for position in _entry(entry, number, words, here):
                owners.setdefault(position, []).append(name)
                positions.append(position)
        parts.append(Part(name, tuple(sorted(set(positions)))))
    if not owners:
        raise ValueError(f"{where}: parts: list at least one word from the sentence")
    for position in sorted(owners):
        listing = owners[position]
        if len(listing) > 1:
            word = words[position]
            shown = json.dumps(f"{word.text}[{word.occurrence}]", ensure_ascii=False)
            distinct = list(dict.fromkeys(listing))
            if len(distinct) == 1:
                raise ValueError(
                    f"{where}: parts.{distinct[0]}: {shown} is listed more than once; "
                    "each word in the sentence may be listed once"
                )
            raise ValueError(
                f"{where}: parts: {shown} is listed under {_joined(distinct)}; "
                "each word in the sentence may be in only one part"
            )
    return Sentence(text, words, tuple(parts), difficulty)


def _apply_filter(sentence: Sentence, parts_filter: tuple[str, ...] | None) -> Sentence:
    if parts_filter is None:
        return sentence
    by_fold = {part.name.casefold(): part for part in sentence.parts}
    parts = []
    for name in parts_filter:
        found = by_fold.get(name.casefold())
        parts.append(Part(name, found.words if found is not None else ()))
    return Sentence(sentence.text, sentence.words, tuple(parts), sentence.difficulty)


def _part_name(written: object, seen: dict[str, str], where: str) -> str:
    if not isinstance(written, str) or not written.strip():
        raise ValueError(f"{where}: parts: a part name must not be empty")
    name = written.strip()
    if len(name) > LONGEST_PART:
        raise ValueError(
            f"{where}: parts.{name}: a part name is at most {LONGEST_PART} characters, so the table stays narrow"
        )
    folded = name.casefold()
    if folded in seen:
        raise ValueError(
            f"{where}: parts.{name}: the same name as {seen[folded]}; "
            "part names in one sentence must differ by more than case"
        )
    seen[folded] = name
    return name


def entry_positions(value: object, number: int, words: tuple[Word, ...], where: str) -> tuple[int, ...]:
    """Return the positions in the sentence that entry ``number`` of a part names. Raises ``ValueError``."""
    return _entry(value, number, words, where)


def _entry(value: object, number: int, words: tuple[Word, ...], where: str) -> tuple[int, ...]:
    """Return the positions in the sentence that one entry names."""
    if isinstance(value, (list, Mapping)):
        raise ValueError(f"{where}: entry {number} is not text; list each word on its own, such as [fox, dog]")
    if not isinstance(value, str):
        raise ValueError(
            f"{where}: entry {number} ({json.dumps(value, ensure_ascii=False)}) is not text; "
            "YAML reads an unquoted yes, no, on, off, or number as something else, "
            'so put the word in quotes, such as ["yes"]'
        )
    label = json.dumps(value, ensure_ascii=False)
    written = value.strip()
    if not written:
        raise ValueError(f"{where}: entry {number} is empty")
    if "[" in written or "]" in written:
        match = _ENTRY.fullmatch(written)
        if match is None:
            raise ValueError(
                f"{where}: {label}: write the occurrence numbers in one pair of square brackets after the word, "
                "such as dry[2] or dry[2,3]"
            )
        word = match["word"].strip()
        if not word:
            raise ValueError(f"{where}: {label}: name a word before the brackets, such as dry[2]")
        occurrences = _occurrences(match["numbers"], label, where)
    else:
        word, occurrences = written, (1,)
    shown = json.dumps(word, ensure_ascii=False)
    found = split_words(word)
    if len(found) != 1 or found[0].text != word:
        raise ValueError(
            f"{where}: {label}: {shown} is not a single word; list each word on its own, without punctuation"
        )
    key = word_key(word)
    positions = [index for index, item in enumerate(words) if item.key == key]
    if not positions:
        raise ValueError(f"{where}: {label}: {shown} is not in the sentence")
    for occurrence in occurrences:
        if occurrence > len(positions):
            raise ValueError(f"{where}: {label}: the sentence has only {len(positions)} of {shown}")
    return tuple(positions[occurrence - 1] for occurrence in occurrences)


def _occurrences(text: str, label: str, where: str) -> tuple[int, ...]:
    pieces = [piece.strip() for piece in text.split(",")]
    if any(not _NUMBER.fullmatch(piece) for piece in pieces):
        raise ValueError(f"{where}: {label}: {_BRACKETS}")
    numbers = [int(piece) for piece in pieces]
    if 0 in numbers:
        raise ValueError(f"{where}: {label}: occurrences are counted from 1, so 0 is not one")
    repeated = [value for index, value in enumerate(numbers) if value in numbers[:index]]
    if repeated:
        raise ValueError(f"{where}: {label}: occurrence {repeated[0]} is in the brackets more than once")
    return tuple(numbers)


def _letter(char: str) -> bool:
    return char.isalnum() or unicodedata.category(char).startswith("M")


def _joined(names: list[str]) -> str:
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{', '.join(names[:-1])}, and {names[-1]}"


def segments(text: str) -> list[dict]:
    """Return the sentence as pieces for the page: each word with its number, and the text between words."""
    pieces: list[dict] = []
    at = 0
    for number, word in enumerate(split_words(text)):
        if word.start > at:
            pieces.append({"text": text[at : word.start]})
        pieces.append({"text": word.text, "word": number})
        at = word.end
    if at < len(text):
        pieces.append({"text": text[at:]})
    return pieces


def format_points(points: float) -> str:
    """Return points as the page shows them: 5, 5.25, 5.5, or 5.75."""
    return f"{points:g}"


def snapshot_settings(settings: Settings, body: Mapping) -> dict:
    """Return the settings stored on a run: resolved sentences and targets."""
    timeout = body.get("timeout", DEFAULT_TIMEOUT)
    document: dict = {
        "timeout": timeout if isinstance(timeout, str) else DEFAULT_TIMEOUT,
        "pools": list(settings.pool_names),
        "correct_answers_required": settings.required,
        "minimum_questions": settings.minimum_questions,
        "maximum_questions": settings.maximum_questions,
        "sentences": [
            {
                "sentence": sentence.text,
                "level_of_difficulty": sentence.difficulty,
                "parts": {part.name: list(part.words) for part in sentence.parts},
            }
            for sentence in settings.sentences
        ],
    }
    if settings.parts_filter is not None:
        document["parts_of_speech"] = list(settings.parts_filter)
    elif "parts_of_speech" in body:
        document["parts_of_speech"] = body["parts_of_speech"]
    return document


@dataclass(frozen=True)
class Judged:
    """What the server decided about one try.

    ``outcome`` is ``wrong`` while the sentence is still waiting for another
    try. ``verdict`` is ``pass`` or ``failure`` when this try ends the run.
    """

    outcome: str
    attempt: int
    wrong: int
    missed: int
    question: Mapping
    verdict: str | None


class Session(QuizRecord):
    """The parts of speech record on one attempt."""

    def __init__(
        self, detail: Mapping, body: Mapping, rng: random.Random | None = None, root: Path | None = None
    ) -> None:
        super().__init__(detail, body)
        self.rng = rng or random.Random()
        self.root = root
        self._parsed: tuple[object, Settings] | None = None

    def parse(self, body: object) -> Settings:
        if not isinstance(body, Mapping):
            raise ValueError("body must be a mapping")
        if _is_snapshot(body):
            return _parse_snapshot(body)
        return check_body(body, self.root)

    @property
    def settings(self) -> Settings:
        stored = self.detail["settings"]
        if self._parsed is None or self._parsed[0] is not stored:
            self._parsed = (stored, self.parse(stored))
        return self._parsed[1]

    def snapshot(self, settings: Settings) -> dict:
        """Return the settings to store on a run that starts now."""
        return snapshot_settings(settings, self.body)

    def question_fields(self, sentence) -> dict:
        """Return what a question records of its sentence, beyond the sentence's text."""
        return {
            "parts": [part.name for part in sentence.parts],
            "words": [
                {"word": word.text, "part": sentence.part_of(position)}
                for position, word in enumerate(sentence.words)
            ],
        }

    def time_out(self, question: dict) -> None:
        question.update(outcome=TIMEOUT, correct_try=None, points=0)

    def _start_run(self, now: datetime) -> None:
        resolved = self.parse(self.body)
        super()._start_run(now)
        self.detail["settings"] = self.snapshot(resolved)
        self._parsed = None
        self.detail["runs"][-1]["asked"] = []

    @property
    def total(self) -> int:
        """Return how many sentences this run may ask at most."""
        return self.settings.maximum_questions

    def finished(self) -> list[dict]:
        """Return the finished sentences of the current run."""
        return [item for item in self.in_run() if item.get("outcome") is not None]

    @property
    def points(self) -> float:
        return sum(item.get("points") or 0 for item in self.finished())

    @property
    def number(self) -> int:
        """Return how many sentences of the current run are finished."""
        return len(self.finished())

    def remaining(self) -> list[int]:
        """Return the indexes of runnable sentences not yet asked in this run."""
        asked = set(self.detail["runs"][-1].get("asked") or [])
        return [index for index in range(len(self.settings.sentences)) if index not in asked]

    def verdict(self) -> str | None:
        """Return ``pass`` or ``failure`` once the current run has decided the attempt."""
        settings = self.settings
        done = self.number
        points = self.points
        if points >= settings.required and done >= settings.minimum_questions:
            return PASS
        # A sentence that is open now can still earn points, so it is not yet "asked and gone".
        left = len(self.remaining()) + (1 if self.pending is not None else 0)
        if done >= settings.maximum_questions or left == 0:
            return FAILURE
        room = min(left, settings.maximum_questions - done)
        if done >= settings.minimum_questions and points + room < settings.required:
            return FAILURE
        return None

    def visit(self, now: datetime) -> None:
        """Record a page load. The open sentence stays open until its deadline."""
        self.resume(now)
        pending = self.pending
        if pending is not None and self.late(pending, now):
            self.time_out(pending)
        self.touch(now)

    def late(self, question: Mapping, now: datetime) -> bool:
        """Return whether ``now`` is past the sentence's deadline, the network allowance included."""
        return self.taken_ms(question, now) > question["allowed_ms"] + NETWORK_ALLOWANCE_MS

    def left_ms(self, question: Mapping, now: datetime) -> int:
        """Return the time left for the page's timer, which runs out before the network allowance does."""
        return max(0, question["allowed_ms"] - self.taken_ms(question, now))

    def issue(self, now: datetime) -> dict:
        """Return the open sentence, or issue the next one chosen uniformly from those not yet asked."""
        self.visit(now)
        pending = self.pending
        if pending is not None:
            return pending
        if self.verdict() is not None:
            raise ValueError("this run is finished")
        remaining = self.remaining()
        if not remaining:
            raise ValueError("this run is finished")
        # Uniform among unseen; a later per-pool weight can replace this pick.
        index = remaining[self.rng.randrange(len(remaining))]
        self.detail["runs"][-1].setdefault("asked", []).append(index)
        sentence = self.settings.sentences[index]
        question = {
            "run": self.run,
            "index": index,
            "sentence": sentence.text,
            **self.question_fields(sentence),
            "tries": [],
            "outcome": None,
            "correct_try": None,
            "points": None,
            "allowed_ms": sentence_pools.allowed_ms(sentence.difficulty, self.settings.timeout),
            "issued": stamp(now),
        }
        self.questions.append(question)
        self.touch(now)
        return question

    NOTHING_TO_SUBMIT = "sort at least one word into the table before submitting"
    SAME_AS_LAST = "the table is the same as the last try"

    def read_try(self, sent: object, question: Mapping):
        """Check a try as sent and return what to store of it, and what it puts in place, to compare with other tries."""
        return _placements(sent, question)

    def stored_try(self, table) -> dict:
        return {"placements": table}

    def placed_in(self, recorded: Mapping):
        """Return what a recorded try put in place, as ``read_try`` returns it."""
        return _assignment(recorded["placements"])

    def score(self, question: Mapping, placed) -> tuple[list[int], list[int]]:
        """Return the positions of the words that are wrong in the try, and the ones that were missed."""
        expected = [item["part"] for item in question["words"]]
        wrong = sorted(position for position, part in placed.items() if expected[position] != part)
        missed = [position for position, part in enumerate(expected) if part is not None and position not in placed]
        return wrong, missed

    def answer(self, now: datetime, number: object, placements: object, *, expired: bool) -> Judged:
        """Judge a try the server received now.

        ``placements`` maps part names to the numbers of the words he sorted
        into each, in the order he dropped them. ``expired`` means the page's
        timer ran out and it sent the table as it stood. A try that arrives
        after the deadline is a timeout whatever it holds, and it is still
        recorded. An empty table, or the table of the last wrong try, is
        refused without using a try unless the timer sent it or it is late.
        """
        self.resume(now)
        pending = self.pending
        if pending is None or number != len(self.questions) - 1:
            raise StaleQuestion("that sentence is no longer waiting for an answer")
        table, placed = self.read_try(placements, pending)
        late = self.late(pending, now)
        tries = pending["tries"]
        if not late and not expired:
            if not placed:
                raise ValueError(self.NOTHING_TO_SUBMIT)
            if tries and self.placed_in(tries[-1]) == placed:
                raise ValueError(self.SAME_AS_LAST)
        wrong, missed = self.score(pending, placed)
        attempt = len(tries) + 1
        tries.append(
            {
                **self.stored_try(table),
                "wrong": len(wrong),
                "missed": len(missed),
                "wrong_words": wrong,
                "missed_words": missed,
                "expired": expired,
                "received_ms": self.taken_ms(pending, now),
            }
        )
        right = not wrong and not missed
        if late:
            outcome = TIMEOUT
        elif right:
            outcome = CORRECT
        elif expired:
            outcome = TIMEOUT
        elif attempt >= TRIES:
            outcome = INCORRECT
        else:
            outcome = WRONG
        if outcome != WRONG:
            pending.update(
                outcome=outcome,
                correct_try=attempt if outcome == CORRECT else None,
                points=POINTS[attempt - 1] if outcome == CORRECT else 0,
            )
        self.touch(now)
        verdict = None if outcome == WRONG else self.verdict()
        return Judged(outcome, attempt, len(wrong), len(missed), pending, verdict)


def _placements(sent: object, question: Mapping) -> tuple[dict[str, list[int]], dict[int, str]]:
    """Check a try's table and return it, and the part each sorted word is in."""
    if not isinstance(sent, Mapping):
        raise ValueError("a try maps part names to lists of word numbers")
    parts = question["parts"]
    count = len(question["words"])
    table: dict[str, list[int]] = {}
    placed: dict[int, str] = {}
    for name, numbers in sent.items():
        if name not in parts:
            raise ValueError(f"{name!r} is not a part in this sentence's table")
        if not isinstance(numbers, list):
            raise ValueError(f"{name!r} must list word numbers")
        for position in numbers:
            if not is_whole(position) or not 0 <= position < count:
                raise ValueError(f"word {position!r} is not in the sentence")
            if position in placed:
                raise ValueError(f"word {position} is sorted more than once")
            placed[position] = name
        table[name] = list(numbers)
    return table, placed


def _assignment(table: Mapping) -> dict[int, str]:
    return {position: name for name, numbers in table.items() for position in numbers}
