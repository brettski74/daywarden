"""Spelling quiz: configuration, word pools, audio tokens, and the queue.

A task of type ``spelling`` keeps its fields in ``body``. Every field is
optional. The word pools are directories of audio files under
``DAYWARDEN_DATA_DIR``, named ``<word>.<ext>`` or ``<word>.<n>.<ext>``, with
an optional ``.sentence.`` clip beside each. They are checked when the
policy is loaded and scanned again whenever a run starts, so new recordings
arrive without a restart. Each run keeps a copy of its words, targets, and
queue on the attempt, so files changed during a run do not disturb it.

The browser never sees a word or its length. Audio URLs carry a fixed-length
token holding the scrambled entry key, which only the server reads back.
Runs, expiry, and resume are ``policy.quiz``'s.
"""

from __future__ import annotations

import base64
import os
import random
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

import mutagen

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
from policy.sounds import MEDIA_TYPES
from policy.tasks import PASS

SPELLING = "spelling"
LABEL = "Spelling"
CURRENT = "current"
REVISION = "revision"
POOLS = (CURRENT, REVISION)
WORD_CLIP = "word"
SENTENCE_CLIP = "sentence"
DATA_DIR_ENV = "DAYWARDEN_DATA_DIR"
DEFAULT_DATA_DIR = "/var/lib/daywarden/data"
LONGEST_KEY = 22
LONGEST_ANSWER = 40
TOKEN_BYTES = 24
TOKEN_LENGTH = 32
DEFAULT_REVISION_REQUIRED = 5

_DIRECTORIES = {
    "current_dir": "spelling/current",
    "revision_dir": "spelling/revision",
    "alphabet_dir": "spelling/alphabet",
}
_POOL_FIELDS = {CURRENT: "current_dir", REVISION: "revision_dir"}
_REQUIRED_FIELDS = {CURRENT: "current_required", REVISION: "revision_required"}
_BODY_KEYS = {*_DIRECTORIES, "timeout", "maximum_replays", "maximum_sentence_plays", *_REQUIRED_FIELDS.values()}
_WORD = re.compile(r"^[A-Za-z'-]+$")
_KEY = re.compile(r"^[A-Za-z'-]+(?:\.[1-9][0-9]*)?$")
_HOMOGRAPH = re.compile(r"^[1-9][0-9]*$")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{32}$")
_POOL_BIT = 0x80
PADDING_BYTES = tuple(value for value in range(256) if 3 <= value.bit_count() <= 5)
_PADDING = frozenset(PADDING_BYTES)


@dataclass(frozen=True)
class Settings:
    """One run's spelling settings. The timeout is milliseconds.

    The directories are relative to ``DAYWARDEN_DATA_DIR``. A required count
    of None is the default worked out from the pool. ``explicit`` names the
    directory fields the body wrote.
    """

    current_dir: str
    revision_dir: str
    alphabet_dir: str
    timeout: int
    maximum_replays: int
    maximum_sentence_plays: int
    current_required: int | None
    revision_required: int | None
    explicit: frozenset[str] = frozenset()

    def directory(self, pool: str) -> str:
        return self.current_dir if pool == CURRENT else self.revision_dir


@dataclass(frozen=True)
class Clip:
    """One audio file in a pool directory and how long it plays."""

    name: str
    ms: int

    @property
    def extension(self) -> str:
        return self.name.rsplit(".", 1)[1].lower()


@dataclass(frozen=True)
class Word:
    """One entry in a pool: ``read.1`` is spelled ``read``."""

    key: str
    word: str
    clip: Clip
    sentence: Clip | None

    def record(self) -> dict:
        return {
            "key": self.key,
            "word": self.word,
            "clip": self.clip.name,
            "clip_ms": self.clip.ms,
            "sentence": None if self.sentence is None else self.sentence.name,
            "sentence_ms": None if self.sentence is None else self.sentence.ms,
        }


@dataclass(frozen=True)
class Pools:
    """The words in both pools and how many of each must be spelled right."""

    current: tuple[Word, ...]
    revision: tuple[Word, ...]
    current_required: int
    revision_required: int


def data_root() -> Path:
    return Path(os.environ.get(DATA_DIR_ENV, DEFAULT_DATA_DIR))


def parse_settings(body: Mapping) -> Settings:
    """Check a spelling task body's fields and return its settings.

    The pool directories are not read here. A problem raises ``ValueError``
    whose message starts with the field.
    """
    if not isinstance(body, Mapping):
        raise ValueError("body must be a mapping")
    unknown = sorted(set(body) - _BODY_KEYS)
    if unknown:
        raise ValueError(f"{unknown[0]}: unknown setting")
    directories = {field: _directory(body.get(field, default), field) for field, default in _DIRECTORIES.items()}
    return Settings(
        **directories,
        timeout=duration(body.get("timeout", "30s"), "timeout"),
        maximum_replays=_count(body.get("maximum_replays", 3), "maximum_replays"),
        maximum_sentence_plays=_count(body.get("maximum_sentence_plays", 2), "maximum_sentence_plays"),
        current_required=None if "current_required" not in body else _count(body["current_required"], "current_required"),
        revision_required=None
        if "revision_required" not in body
        else _count(body["revision_required"], "revision_required"),
        explicit=frozenset(field for field in _DIRECTORIES if field in body),
    )


def check_body(body: Mapping, root: Path | None = None) -> Pools:
    """Check a spelling task body and its word pools, as the policy load does."""
    settings = parse_settings(body)
    root = data_root() if root is None else root
    pools = load_pools(settings, root)
    _LAST_GOOD[(settings, root)] = pools
    return pools


def load_pools(settings: Settings, root: Path | None = None) -> Pools:
    """Scan both pool directories and work out the targets.

    A default directory that does not exist is an empty pool. A directory
    the body names, or one whose pool has a target above zero, must exist.
    """
    root = data_root() if root is None else root
    found: dict[str, tuple[Word, ...]] = {}
    for pool in POOLS:
        field = _POOL_FIELDS[pool]
        directory = root / settings.directory(pool)
        if directory.is_dir():
            found[pool] = scan_pool(directory, field)
            continue
        wanted = getattr(settings, _REQUIRED_FIELDS[pool])
        if field in settings.explicit or (wanted is not None and wanted > 0):
            raise ValueError(f"{field}: {directory} is not a directory")
        found[pool] = ()
    current, revision = found[CURRENT], found[REVISION]
    seen = {word.key.lower() for word in current}
    for word in revision:
        if word.key.lower() in seen:
            raise ValueError(f"revision_dir: {word.key} is also in current_dir; a word belongs to one pool")
    m = len(current)
    n = m if settings.current_required is None else settings.current_required
    if n > m:
        raise ValueError(f"current_required: is {n}, but current_dir has only {m} word{'' if m == 1 else 's'}")
    x = min(DEFAULT_REVISION_REQUIRED, len(revision)) if settings.revision_required is None else settings.revision_required
    if x > len(revision):
        raise ValueError(
            f"revision_required: is {x}, but revision_dir has only {len(revision)} word{'' if len(revision) == 1 else 's'}"
        )
    if m == 0 and x == 0:
        raise ValueError("current_dir: has no words and revision_required is 0, so there is nothing to ask")
    return Pools(current, revision, n, x)


def scan_pool(directory: Path, field: str) -> tuple[Word, ...]:
    """Read one pool directory. Hidden files and files that are not audio are skipped."""
    words, problems = _scan_pool(directory, field)
    if problems:
        raise ValueError(problems[0])
    return words


def pool_problems(directory: Path, field: str) -> list[str]:
    """Return every reason a pool directory would fail to load, in the order ``scan_pool`` meets them."""
    return _scan_pool(directory, field)[1]


def _scan_pool(directory: Path, field: str) -> tuple[tuple[Word, ...], list[str]]:
    clips: dict[str, tuple[str, str, Clip]] = {}
    sentences: dict[str, Clip] = {}
    problems: list[str] = []
    with os.scandir(directory) as listing:
        children = sorted(listing, key=lambda child: child.name)
    for child in children:
        if child.name.startswith(".") or not child.is_file():
            continue
        try:
            parsed = parse_clip_name(child.name, field)
            if parsed is None:
                continue
            key, word, sentence = parsed
            clip = Clip(child.name, audio_ms(Path(child.path), child.stat(), field))
        except ValueError as exc:
            problems.append(str(exc))
            continue
        folded = key.lower()
        if sentence:
            if folded in sentences:
                problems.append(f"{field}: {sentences[folded].name} and {child.name} are both the sentence clip for {key}")
                continue
            sentences[folded] = clip
        else:
            if folded in clips:
                problems.append(f"{field}: {clips[folded][2].name} and {child.name} are both the word clip for {key}")
                continue
            clips[folded] = (key, word, clip)
    for folded, sentence in sentences.items():
        if folded not in clips:
            problems.append(f"{field}: {sentence.name} has no word clip beside it")
    words = tuple(Word(key, word, clip, sentences.get(folded)) for folded, (key, word, clip) in sorted(clips.items()))
    return words, problems


def parse_clip_name(name: str, field: str | None) -> tuple[str, str, bool] | None:
    """Return the entry key, the spelling, and whether a file is a sentence clip.

    A file without an audio extension is None. A badly formed audio file name
    raises ``ValueError``, whose message starts with ``field`` when one is given.
    """
    prefix = f"{field}: " if field else ""
    stem, dot, extension = name.rpartition(".")
    if not dot or "." + extension.lower() not in MEDIA_TYPES:
        return None
    parts = stem.split(".")
    sentence = len(parts) > 1 and parts[-1].lower() == SENTENCE_CLIP
    if sentence:
        parts = parts[:-1]
    if len(parts) == 2 and _HOMOGRAPH.fullmatch(parts[1]):
        word, key = parts[0], f"{parts[0]}.{parts[1]}"
    elif len(parts) == 1:
        word = key = parts[0]
    else:
        raise ValueError(
            f"{prefix}{name} is not <word>.<ext>, <word>.<n>.<ext>, <word>.sentence.<ext>, "
            "or <word>.<n>.sentence.<ext>"
        )
    if not _WORD.fullmatch(word):
        raise ValueError(f"{prefix}{name}: a word may only have the letters a to z, - and '")
    if len(key) > LONGEST_KEY:
        raise ValueError(f"{prefix}{name}: {key} is longer than {LONGEST_KEY} characters")
    return key, word, sentence


_LENGTHS: dict[tuple[str, int, int], int] = {}
_LAST_GOOD: dict[tuple[Settings, Path], Pools] = {}


def audio_ms(path: Path, status: os.stat_result, field: str) -> int:
    """Return how long a clip plays, read once per version of the file."""
    cached = (str(path), status.st_mtime_ns, status.st_size)
    if cached not in _LENGTHS:
        _LENGTHS[cached] = read_audio_ms(path, field)
    return _LENGTHS[cached]


def read_audio_ms(path: Path, field: str) -> int:
    try:
        audio = mutagen.File(path)
    except (mutagen.MutagenError, OSError):
        audio = None
    length = getattr(getattr(audio, "info", None), "length", None)
    if not length or length <= 0:
        raise ValueError(f"{field}: {path.name}: cannot read how long this recording is")
    return round(length * 1000)


def current_pools(settings: Settings, root: Path | None = None) -> Pools:
    """Scan the pools for a new run.

    A directory that has gone bad since the policy loaded keeps the last
    words that scanned cleanly for these settings, and the service logs why.
    """
    root = data_root() if root is None else root
    try:
        pools = load_pools(settings, root)
    except (ValueError, OSError) as exc:
        kept = _LAST_GOOD.get((settings, root))
        if kept is None:
            raise
        print(f"spelling words not reloaded, keeping the last good list: {exc}", flush=True)
        return kept
    _LAST_GOOD[(settings, root)] = pools
    return pools


# Audio tokens


def scramble(key: str, pool: str, rng: random.Random) -> bytes:
    """Return the 24-byte buffer that hides a pool and entry key.

    ``buffer[0]`` is the pool bit and the key length, the key follows, and
    random padding bytes fill the rest. Each of the first ``m`` bytes is
    XORed with a padding byte, read backwards from the end.
    """
    data = key.encode("ascii")
    if not 1 <= len(data) <= LONGEST_KEY:
        raise ValueError(f"an entry key is 1 to {LONGEST_KEY} characters")
    m = len(data) + 1
    n = TOKEN_BYTES - m
    buffer = bytearray(TOKEN_BYTES)
    buffer[0] = (_POOL_BIT if pool == REVISION else 0) | len(data)
    buffer[1:m] = data
    for index in range(m, TOKEN_BYTES):
        buffer[index] = rng.choice(PADDING_BYTES)
    for index in range(m):
        buffer[index] ^= buffer[TOKEN_BYTES - 1 - (index % n)]
    return bytes(buffer)


def descramble(buffer: bytes) -> tuple[str, str] | None:
    """Return the pool and entry key a scrambled buffer holds, or None when it is not one."""
    if len(buffer) != TOKEN_BYTES:
        return None
    header = buffer[0] ^ buffer[-1]
    length = header & 0x7F
    if not 1 <= length <= LONGEST_KEY:
        return None
    m = length + 1
    n = TOKEN_BYTES - m
    if any(value not in _PADDING for value in buffer[m:]):
        return None
    data = bytes(buffer[index] ^ buffer[TOKEN_BYTES - 1 - (index % n)] for index in range(1, m))
    try:
        key = data.decode("ascii")
    except UnicodeDecodeError:
        return None
    if not _KEY.fullmatch(key):
        return None
    return (REVISION if header & _POOL_BIT else CURRENT), key


def token(key: str, pool: str, rng: random.Random) -> str:
    return base64.urlsafe_b64encode(scramble(key, pool, rng)).decode("ascii")


def untoken(text: str) -> tuple[str, str] | None:
    if not _TOKEN.fullmatch(text):
        return None
    return descramble(base64.urlsafe_b64decode(text))


def media_name(key: str, pool: str, clip: Clip, *, sentence: bool, rng: random.Random) -> str:
    """Return the file name an audio URL ends with: ``<token>.<ext>`` or ``<token>.sentence.<ext>``."""
    middle = "." + SENTENCE_CLIP if sentence else ""
    return f"{token(key, pool, rng)}{middle}.{clip.extension}"


def read_media_name(name: str) -> tuple[str, str, bool, str] | None:
    """Return the pool, entry key, whether it is the sentence, and the extension in an audio file name."""
    parts = name[TOKEN_LENGTH:].split(".")
    if parts[0] != "" or len(parts) not in (2, 3) or (len(parts) == 3 and parts[1] != SENTENCE_CLIP):
        return None
    extension = parts[-1].lower()
    if "." + extension not in MEDIA_TYPES:
        return None
    found = untoken(name[:TOKEN_LENGTH])
    if found is None:
        return None
    pool, key = found
    return pool, key, len(parts) == 3, extension


def find_clip(settings: Settings, pool: str, key: str, *, sentence: bool, extension: str, root: Path | None = None) -> Path | None:
    """Return the audio file in the pool's directory for that entry, or None."""
    root = data_root() if root is None else root
    wanted = (f"{key}.{SENTENCE_CLIP}.{extension}" if sentence else f"{key}.{extension}").lower()
    try:
        with os.scandir(root / settings.directory(pool)) as listing:
            for child in listing:
                if child.name.lower() == wanted and not child.name.startswith(".") and child.is_file():
                    return Path(child.path)
    except OSError:
        return None
    return None


# The quiz


@dataclass(frozen=True)
class Judged:
    """What the server decided about one answer.

    ``word`` is the spelling to show, given only when a missed word will not
    come back in this run. ``verdict`` is ``pass`` when this answer ends the
    attempt.
    """

    outcome: str
    question: Mapping
    word: str | None
    verdict: str | None


class Session(QuizRecord):
    """The spelling record on one attempt."""

    def __init__(self, detail: Mapping, body: Mapping, rng: random.Random | None = None, root: Path | None = None) -> None:
        super().__init__(detail, body)
        self.rng = rng or random.Random()
        self.root = root

    def parse(self, body: object) -> Settings:
        return parse_settings(body)

    def time_out(self, question: dict) -> None:
        self._close(question, None, TIMEOUT, None)

    def _start_run(self, now: datetime) -> None:
        super()._start_run(now)
        pools = current_pools(self.settings, self.root)
        chosen = self.rng.sample(pools.revision, pools.revision_required)
        queue = [[CURRENT, word.key] for word in pools.current] + [[REVISION, word.key] for word in chosen]
        self.rng.shuffle(queue)
        self.detail["runs"][-1].update(
            current_total=len(pools.current),
            current_required=pools.current_required,
            revision_required=pools.revision_required,
            words={
                CURRENT: [word.record() for word in pools.current],
                REVISION: [word.record() for word in pools.revision],
            },
            queue=queue,
        )

    @property
    def current_run(self) -> dict:
        return self.detail["runs"][-1]

    def scores(self) -> dict[str, int]:
        """Return the words spelled right in the current run, by pool."""
        counts = dict.fromkeys(POOLS, 0)
        for item in self.in_run():
            if item.get("outcome") == CORRECT:
                counts[item["pool"]] += 1
        return counts

    def progress(self) -> dict:
        run = self.current_run
        scores = self.scores()
        return {
            "current": scores[CURRENT],
            "current_required": run["current_required"],
            "revision": scores[REVISION],
            "revision_required": run["revision_required"],
        }

    def verdict(self) -> str | None:
        """Return ``pass`` once every current word is asked and both targets are met."""
        if not self.detail["runs"]:
            return None
        run = self.current_run
        scores = self.scores()
        if scores[CURRENT] < run["current_required"] or scores[REVISION] < run["revision_required"]:
            return None
        asked = {item["key"] for item in self.in_run() if item["pool"] == CURRENT and item.get("outcome") is not None}
        if any(word["key"] not in asked for word in run["words"][CURRENT]):
            return None
        return PASS

    def word(self, pool: str, key: str) -> dict:
        for word in self.current_run["words"][pool]:
            if word["key"] == key:
                return word
        raise KeyError(key)

    def issue(self, now: datetime) -> dict:
        """Issue the word at the front of the queue and start its time now."""
        self.resume(now)
        self.close_pending()
        queue = self.current_run["queue"]
        if not queue:
            raise ValueError("no words are left to ask")
        pool, key = queue.pop(0)
        word = self.word(pool, key)
        timeout = self.settings.timeout
        question = {
            "run": self.run,
            "key": key,
            "word": word["word"],
            "pool": pool,
            "sentence": word["sentence"] is not None,
            "word_replays": 0,
            "sentence_plays": 0,
            "answer": None,
            "outcome": None,
            "requeued": None,
            "timeout_ms": timeout,
            "allowed_ms": word["clip_ms"] + timeout,
            "received_ms": None,
            "issued": stamp(now),
        }
        self.questions.append(question)
        self.touch(now)
        return question

    def replay(self, now: datetime, number: object, clip: object) -> dict:
        """Record a replay of the word or sentence and give the question that clip's length again.

        A replay past the configured maximum, of a sentence the word does not
        have, or after the question's time is up is refused.
        """
        self.resume(now)
        pending = self.pending
        if pending is None or number != len(self.questions) - 1:
            raise StaleQuestion("that question is no longer waiting for an answer")
        if clip not in (WORD_CLIP, SENTENCE_CLIP):
            raise ValueError("clip must be word or sentence")
        if self.taken_ms(pending, now) > pending["allowed_ms"] + NETWORK_ALLOWANCE_MS:
            raise ValueError("the time for this question is up")
        settings = self.settings
        word = self.word(pending["pool"], pending["key"])
        if clip == WORD_CLIP:
            field, limit, length = "word_replays", settings.maximum_replays, word["clip_ms"]
        else:
            if word["sentence"] is None:
                raise ValueError("this word has no sentence clip")
            field, limit, length = "sentence_plays", settings.maximum_sentence_plays, word["sentence_ms"]
        if pending[field] >= limit:
            raise ValueError(f"no more {clip} plays are allowed on this question")
        pending[field] += 1
        pending["allowed_ms"] += length
        self.touch(now)
        return dict(pending)

    def answer(self, now: datetime, number: object, text: object, *, expired: bool) -> Judged:
        """Judge a spelling the server received now.

        ``expired`` means the browser's timer ran out and it sent whatever was
        in the box. Then the right spelling is correct and anything else is a
        timeout. An answer that arrives after the time allowed plus the
        network allowance is a timeout whatever it says, and it is still
        recorded.
        """
        self.resume(now)
        pending = self.pending
        if pending is None or number != len(self.questions) - 1:
            raise StaleQuestion("that question is no longer waiting for an answer")
        received = _received(text)
        if received is None and not expired:
            raise ValueError("an empty answer is not submitted")
        taken = self.taken_ms(pending, now)
        if taken > pending["allowed_ms"] + NETWORK_ALLOWANCE_MS:
            outcome = TIMEOUT
        elif received is not None and received.lower() == pending["word"].lower():
            outcome = CORRECT
        elif expired or received is None:
            outcome = TIMEOUT
        else:
            outcome = INCORRECT
        self._close(pending, received, outcome, taken)
        self.touch(now)
        shown = pending["word"] if outcome != CORRECT and not pending["requeued"] else None
        return Judged(outcome, dict(pending), shown, self.verdict())

    def _close(self, question: dict, received: str | None, outcome: str, taken: int | None) -> None:
        question.update(answer=received, outcome=outcome, received_ms=taken)
        missed = outcome != CORRECT and question.get("run") == self.run and bool(self.detail["runs"])
        question["requeued"] = self._requeue(question) if missed else False

    def _requeue(self, question: Mapping) -> bool:
        """Apply the re-queue rule for a missed word and return whether that same word comes back."""
        run = self.current_run
        queue = run["queue"]
        scores = self.scores()
        key = question["key"]
        if question["pool"] == CURRENT:
            if scores[CURRENT] < run["current_required"]:
                queue.append([CURRENT, key])
                return True
            return False
        if scores[REVISION] >= run["revision_required"]:
            return False
        waiting = {entry for pool, entry in queue if pool == REVISION}
        right = {
            item["key"] for item in self.in_run() if item["pool"] == REVISION and item.get("outcome") == CORRECT
        }
        others = [
            word["key"]
            for word in run["words"][REVISION]
            if word["key"] != key and word["key"] not in waiting and word["key"] not in right
        ]
        if others:
            queue.append([REVISION, self.rng.choice(others)])
            return False
        queue.append([REVISION, key])
        return True


def missed_words(detail: Mapping) -> list[str]:
    """Return each word missed anywhere in the attempt once, in the order he first missed it."""
    seen: set[str] = set()
    words: list[str] = []
    for item in detail.get("questions", ()):
        if item.get("outcome") in (INCORRECT, TIMEOUT) and "word" in item:
            folded = item["word"].lower()
            if folded not in seen:
                seen.add(folded)
                words.append(item["word"])
    return words


def _directory(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}: must be a directory path under {DATA_DIR_ENV}")
    path = PurePosixPath(value.strip())
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field}: must be a relative path that stays under {DATA_DIR_ENV}, without ..")
    return str(path)


def _count(value: object, field: str) -> int:
    if not is_whole(value) or value < 0:
        raise ValueError(f"{field}: must be a whole number, 0 or more")
    return value


def _received(text: object) -> str | None:
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)
    text = text.strip()[:LONGEST_ANSWER]
    return text or None
