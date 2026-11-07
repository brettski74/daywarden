"""Parts of speech quiz: sentences, their words, and the parts table.

A task of type ``parts_of_speech`` keeps its fields in ``body``. The body
lists sentences, and each sentence maps part of speech names, chosen by the
parent, to words from that sentence. They are checked when the policy is
loaded, so a typo fails the load, the error names the sentence, the part,
and the entry, and the previous policy stays in force.

A word is a run of letters and digits. An apostrophe or a hyphen with a
letter or digit on both sides joins the runs either side into one word.
Everything else is punctuation, shown but never sorted. Words are compared
without regard to case, and ``’`` is the same as ``'``. An entry names a
word and, in square brackets, which of its occurrences: ``dry``,
``dry[2]``, or ``dry[2,3]``. Without brackets it is the first.

The parts keep the order and spelling they were written in. Each is a row
of the child's table.

A run asks every sentence once, in an order shuffled when the run starts.
He has three tries per sentence, worth 1, 0.5, and 0.25 points. The server
judges every try and fixes each sentence's deadline when it issues it. A
page load does not close the open sentence. Only its deadline, an expired
run, or a give-up does. The run ends after the last sentence, and its
points decide a pass or a failure.
"""

from __future__ import annotations

import json
import random
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

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

_BODY_KEYS = frozenset({"sentences", "timeout", "correct_answers_required"})
_SENTENCE_KEYS = frozenset({"sentence", "parts", "timeout"})
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
    """A sentence, its words in order, its parts in the order written, and its timeout in milliseconds."""

    text: str
    words: tuple[Word, ...]
    parts: tuple[Part, ...]
    timeout: int

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
    """Return 70% of ``count``, rounded up, in whole numbers so 10 gives 7."""
    return -(-7 * count // 10)


def parse_settings(body: Mapping) -> Settings:
    """Check a parts of speech task body and return its settings.

    Each field, and each sentence, is checked, and every problem is raised
    together as ``Problems``, a ``ValueError``. Each message starts with the
    field.
    """
    if not isinstance(body, Mapping):
        raise ValueError("body must be a mapping")
    fields = Collector()
    for key in sorted(set(body) - _BODY_KEYS):
        fields.add(f"{key}: unknown setting")
    timeout = fields.take(duration, body.get("timeout", DEFAULT_TIMEOUT), "timeout")
    listed = body.get("sentences")
    if "sentences" not in body:
        fields.add("sentences: required; list one or more sentences, each with sentence and parts")
    elif not isinstance(listed, list) or not listed:
        fields.add("sentences: must be a list of one or more sentences, each with sentence and parts")
    if not isinstance(listed, list) or not listed:
        fields.finish()
    sentences = tuple(
        fields.take(_sentence, item, timeout or 0, f"sentences entry {number}")
        for number, item in enumerate(listed, 1)
    )
    required = default_required(len(sentences))
    if "correct_answers_required" in body:
        required = body["correct_answers_required"]
        if not is_whole(required) or not 1 <= required <= len(sentences):
            fields.add(
                f"correct_answers_required: must be a whole number from 1 to {len(sentences)}, "
                "the number of sentences"
            )
    fields.finish()
    return Settings(sentences, timeout, required)


def _sentence(item: object, body_timeout: int, where: str) -> Sentence:
    if not isinstance(item, Mapping):
        raise ValueError(f"{where}: must be a mapping with sentence and parts")
    unknown = sorted(set(item) - _SENTENCE_KEYS)
    if unknown:
        raise ValueError(f"{where}: {unknown[0]}: unknown setting")
    if "sentence" not in item:
        raise ValueError(f"{where}: sentence: required")
    text = item["sentence"]
    if not isinstance(text, str):
        raise ValueError(f"{where}: sentence: must be text")
    words = split_words(text)
    if not words:
        raise ValueError(f"{where}: sentence: must contain at least one word")
    timeout = body_timeout if "timeout" not in item else duration(item["timeout"], f"{where}: timeout")
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
    return Sentence(text, words, tuple(parts), timeout)


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

    def __init__(self, detail: Mapping, body: Mapping, rng: random.Random | None = None) -> None:
        super().__init__(detail, body)
        self.rng = rng or random.Random()
        self._parsed: tuple[object, Settings] | None = None

    def parse(self, body: object) -> Settings:
        return parse_settings(body)

    @property
    def settings(self) -> Settings:
        stored = self.detail["settings"]
        if self._parsed is None or self._parsed[0] is not stored:
            self._parsed = (stored, self.parse(stored))
        return self._parsed[1]

    def time_out(self, question: dict) -> None:
        question.update(outcome=TIMEOUT, correct_try=None, points=0)

    def _start_run(self, now: datetime) -> None:
        super()._start_run(now)
        order = list(range(len(self.settings.sentences)))
        self.rng.shuffle(order)
        self.detail["runs"][-1]["order"] = order

    @property
    def total(self) -> int:
        """Return how many sentences the current run asks."""
        return len(self.detail["runs"][-1]["order"])

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

    def verdict(self) -> str | None:
        """Return ``pass`` or ``failure`` once every sentence of the current run is finished."""
        if self.number < self.total:
            return None
        return PASS if self.points >= self.settings.required else FAILURE

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
        """Return the open sentence, or issue the next one in the run's order and start its time now."""
        self.visit(now)
        pending = self.pending
        if pending is not None:
            return pending
        if self.verdict() is not None:
            raise ValueError("every sentence of this run is finished")
        index = self.detail["runs"][-1]["order"][self.number]
        sentence = self.settings.sentences[index]
        question = {
            "run": self.run,
            "index": index,
            "sentence": sentence.text,
            "parts": [part.name for part in sentence.parts],
            "words": [
                {"word": word.text, "part": sentence.part_of(position)}
                for position, word in enumerate(sentence.words)
            ],
            "tries": [],
            "outcome": None,
            "correct_try": None,
            "points": None,
            "allowed_ms": sentence.timeout,
            "issued": stamp(now),
        }
        self.questions.append(question)
        self.touch(now)
        return question

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
        table, placed = _placements(placements, pending)
        late = self.late(pending, now)
        tries = pending["tries"]
        if not late and not expired:
            if not placed:
                raise ValueError("sort at least one word into the table before submitting")
            if tries and _assignment(tries[-1]["placements"]) == placed:
                raise ValueError("the table is the same as the last try")
        expected = [item["part"] for item in pending["words"]]
        wrong = sorted(position for position, part in placed.items() if expected[position] != part)
        missed = [position for position, part in enumerate(expected) if part is not None and position not in placed]
        attempt = len(tries) + 1
        tries.append(
            {
                "placements": table,
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
