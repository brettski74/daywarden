"""Parts of speech confusions across attempts (S035.3), and one parts of speech attempt's runs.

A placement is where he put one word on one try: the row he dropped it in,
or left out. Each try gives one placement for every word of its sentence.

A word belongs in the part its attempt recorded for it. With a
``parts_of_speech`` filter, the attempt recorded a word from any other part
as in no part. For such a word the sentence is looked up by its text among
the pools the run stored, as the pools are now. When it is there with the
same words, the word belongs in the part the pool gives it. Otherwise it
stays in no part. The pool that lookup finds a sentence in is its pool now,
or None. Parts are compared with case folded.

A part's Right counts only placements in sentences whose table had that part
as a row. No part's right placement is left out, so all of its placements
count. A part never a row in the counted tries is not asked.

The attempt page keeps the quiz's judgement: a word is right when it was put
in the part the attempt recorded, or left out when that part is none.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from policy import sentence_pools
from policy.attempt_figures import figures
from policy.attempt_trends import NONE, Period, View, chosen
from policy.parts_of_speech import PARTS_OF_SPEECH, TRIES, check_pool_sentence, segments, word_key
from policy.quiz import CORRECT, INCORRECT, TIMEOUT
from policy.report import format_day
from policy.tasks import Attempt

# The address's values for no part, left out, and a sentence in none of its run's pools.
NO_PART = "no_part"
LEFT_OUT = "left_out"
NO_POOL = "no_pool"
NO_PART_LABEL = "no part"
LEFT_OUT_LABEL = "left out"
NO_POOL_LABEL = "None"
TRY_CHOICES = tuple(range(1, TRIES + 1))
TRY_LABELS = {1: "1st", 2: "2nd", 3: "3rd"}
OUTCOMES = {CORRECT: "Correct", INCORRECT: "Incorrect", TIMEOUT: "Timed out"}


@dataclass(frozen=True)
class Choices:
    """The confusions page's own filters. ``pools`` None means every pool now offered."""

    pools: tuple[str, ...] | None = None
    tries: tuple[int, ...] = TRY_CHOICES


def read_choices(pairs: Iterable[tuple[str, str]]) -> tuple[Choices, list[str]]:
    """Read the Pool and Try filters from a page address. Missing, everything is chosen. ``none`` alone chooses nothing."""
    found: dict[str, list[str]] = {}
    for key, value in pairs:
        if key in ("pool", "try"):
            found.setdefault(key, []).append(value.strip())
    notes: list[str] = []
    pools = None
    if "pool" in found:
        pools = tuple(dict.fromkeys(value for value in found["pool"] if value and value != NONE))
    tries = TRY_CHOICES
    if "try" in found:
        picked = set(found["try"])
        words = {str(number) for number in TRY_CHOICES}
        notes += [f"{value} is not a try, so it is left out." for value in sorted(picked - words - {NONE, ""})]
        tries = tuple(number for number in TRY_CHOICES if str(number) in picked)
    return Choices(pools, tries), notes


@dataclass(frozen=True)
class Found:
    """Where a sentence is in the pools now: the pool's id and name, and each word's part there, folded."""

    pool: str
    name: str
    parts: tuple[str | None, ...]


class PoolLookup:
    """Finds a stored sentence in the parts of speech pools as they are now. Each pool file is read once."""

    def __init__(self, root: Path | None) -> None:
        self.root = root
        self._index: dict[str, Path] | None = None
        self._pools: dict[str, tuple[str, dict[str, list[tuple[tuple[str, ...], tuple[str | None, ...]]]]] | None] = {}

    def _named(self, name: str):
        if name in self._pools:
            return self._pools[name]
        if self._index is None:
            try:
                self._index = sentence_pools.index_names(self.root)
            except ValueError:
                self._index = {}
        path = self._index.get(name)
        loaded = None
        if path is not None:
            try:
                pool = sentence_pools.load_pool(path)
            except ValueError:
                pool = None
            if pool is not None:
                texts: dict[str, list] = {}
                for number, raw in enumerate(pool.sentences, 1):
                    try:
                        sentence = check_pool_sentence(raw, pool.difficulty, f"sentences entry {number}")
                    except (ValueError, TypeError):
                        continue
                    parts = tuple(_fold(sentence.part_of(position)) for position in range(len(sentence.words)))
                    texts.setdefault(sentence.text, []).append((tuple(word.text for word in sentence.words), parts))
                loaded = (pool.id, texts)
        self._pools[name] = loaded
        return loaded

    def find(self, pool_names: Sequence[str], text: str, words: Sequence[str]) -> Found | None:
        """Return the first of the run's pools that holds ``text`` with the same words, or None."""
        for name in pool_names:
            loaded = self._named(name)
            if loaded is None:
                continue
            pool_id, texts = loaded
            for found_words, parts in texts.get(text, ()):
                if found_words == tuple(words):
                    return Found(pool_id, name, parts)
        return None


def _fold(part: object) -> str | None:
    return part.casefold() if isinstance(part, str) and part.strip() else None


@dataclass
class Ask:
    """One counted sentence: its attempt, text, each word's part, the rows offered, and where each word went on each try."""

    ref: int
    attempt: Attempt
    text: str
    words: list[str]
    belongs: list[str | None]
    rows: set[str]
    tries: list[list[str | None]]
    timer: list[bool]
    pool: str | None
    pool_name: str | None
    day: date


@dataclass
class Placement:
    ask: Ask
    position: int
    number: int  # the try, from 1

    @property
    def belongs(self) -> str | None:
        return self.ask.belongs[self.position]

    @property
    def put(self) -> str | None:
        return self.ask.tries[self.number - 1][self.position]

    @property
    def asked(self) -> bool:
        """Whether this placement counts toward its part's Right: the part was a row, or it is no part."""
        return self.belongs is None or self.belongs in self.ask.rows

    @property
    def right(self) -> bool:
        return self.put == self.belongs

    @property
    def wrong(self) -> bool:
        """Put somewhere other than its part. Leaving out a part that was not a row is not wrong."""
        return not self.right and (self.put is not None or self.asked)


@dataclass
class Labels:
    """Each folded part's spelling: the one seen most often."""

    seen: Counter[tuple[str, str]] = field(default_factory=Counter)

    def add(self, name: object) -> None:
        if isinstance(name, str) and name.strip():
            self.seen[(name.casefold(), name)] += 1

    def of(self, part: str | None) -> str:
        if part is None:
            return NO_PART_LABEL
        spellings = [(count, name) for (folded, name), count in self.seen.items() if folded == part]
        if not spellings:
            return part
        return sorted(spellings, key=lambda item: (-item[0], item[1]))[0][1]


def asks_of(
    attempts: Sequence[Attempt],
    view: View,
    period: Period,
    today: date,
    task_names: Iterable[str],
    lookup: PoolLookup,
    labels: Labels,
) -> list[Ask]:
    """Return every sentence with at least one try in the chosen parts of speech attempts, oldest first."""
    names = set(task_names)
    found: list[Ask] = []
    for attempt in sorted(attempts, key=lambda each: (_wall(each.started_at), each.id)):
        if attempt.task_type != PARTS_OF_SPEECH or attempt.task not in names or not chosen(attempt, view, period, today):
            continue
        detail = attempt.detail if isinstance(attempt.detail, Mapping) else {}
        settings = detail.get("settings") if isinstance(detail.get("settings"), Mapping) else {}
        filtered = isinstance(settings.get("parts_of_speech"), list)
        pool_names = [str(name) for name in settings.get("pools", []) if isinstance(name, str)] if isinstance(settings.get("pools"), list) else []
        questions = detail.get("questions")
        for question in questions if isinstance(questions, list) else ():
            ask = _ask(len(found), attempt, question, filtered, pool_names, lookup, labels)
            if ask is not None:
                found.append(ask)
    return found


def belongs_in(question: Mapping, filtered: bool, found: Found | None) -> list[str | None]:
    """Each word's part, folded: the recorded one, or for a word the filter hid, the pool's now."""
    words = question.get("words") if isinstance(question.get("words"), list) else []
    shown = []
    for position, item in enumerate(words):
        part = _fold(item.get("part")) if isinstance(item, Mapping) else None
        if part is None and filtered and found is not None and position < len(found.parts):
            part = found.parts[position]
        shown.append(part)
    return shown


def _ask(ref, attempt, question, filtered, pool_names, lookup, labels) -> Ask | None:
    if not isinstance(question, Mapping):
        return None
    tries = [each for each in question.get("tries", []) if isinstance(each, Mapping)] if isinstance(question.get("tries"), list) else []
    words = [str(item.get("word", "")) for item in question.get("words", []) if isinstance(item, Mapping)] if isinstance(question.get("words"), list) else []
    text = question.get("sentence") if isinstance(question.get("sentence"), str) else " ".join(words)
    if not tries or not words:
        return None
    found = lookup.find(pool_names, text, words)
    for item in question["words"]:
        if isinstance(item, Mapping):
            labels.add(item.get("part"))
    rows = question.get("parts") if isinstance(question.get("parts"), list) else []
    for name in rows:
        labels.add(name)
    placed = [_put(each, len(words)) for each in tries]
    return Ask(
        ref=ref,
        attempt=attempt,
        text=text,
        words=words,
        belongs=belongs_in(question, filtered, found),
        rows={folded for folded in (_fold(name) for name in rows) if folded is not None},
        tries=placed,
        timer=[each.get("expired") is True for each in tries],
        pool=None if found is None else found.pool,
        pool_name=None if found is None else found.name,
        day=_issued_day(question, attempt.started_at),
    )


def _put(sent: Mapping, count: int) -> list[str | None]:
    """Where a try put each word, folded, or None for left out."""
    table = sent.get("placements") if isinstance(sent.get("placements"), Mapping) else {}
    shown: list[str | None] = [None] * count
    for name, numbers in table.items():
        for position in numbers if isinstance(numbers, list) else ():
            if isinstance(position, int) and 0 <= position < count:
                shown[position] = _fold(name)
    return shown


def offered_pools(asks: Sequence[Ask]) -> list[dict]:
    """The Pool filter's choices: each pool now of the counted sentences by name, then None."""
    named = sorted({(ask.pool, ask.pool_name) for ask in asks if ask.pool is not None}, key=lambda item: (item[1] or "", item[0]))
    return [{"id": pool, "name": name} for pool, name in named] + [{"id": NO_POOL, "name": NO_POOL_LABEL}]


def confusions(asks: Sequence[Ask], choices: Choices, labels: Labels, started: Callable[[Attempt], str]) -> dict:
    """Return the grid, its rows' Right, the word list, and the sentences, over the asks and tries chosen.

    Each word has the asks of it, as ``[ask, position]``. Each ask has its
    sentence in pieces, its attempt, its words' parts, and where each word
    went on each chosen try, so a chosen pair's or word's placements are found
    from the asks.
    """
    kept = [ask for ask in asks if choices.pools is None or (ask.pool or NO_POOL) in choices.pools]
    placements = [
        Placement(ask, position, number)
        for ask in kept
        for number in range(1, len(ask.tries) + 1)
        if number in choices.tries
        for position in range(len(ask.words))
    ]
    order = lambda part: (part is None, labels.of(part).casefold(), part or "")  # noqa: E731
    rows = sorted({each.belongs for each in placements}, key=order)
    columns = sorted({each.put for each in placements}, key=order)
    counts = Counter((each.belongs, each.put) for each in placements)
    grid_rows = []
    for part in rows:
        mine = [each for each in placements if each.belongs == part]
        grid_rows.append(
            {
                "part": _value(part, NO_PART),
                "label": labels.of(part),
                "placements": len(mine),
                "right": _right(mine),
                "cells": [counts[(part, put)] for put in columns],
            }
        )
    used = {each.ask.ref for each in placements}
    return {
        "columns": [{"part": _value(put, LEFT_OUT), "label": LEFT_OUT_LABEL if put is None else labels.of(put)} for put in columns],
        "rows": grid_rows,
        "words": _words(placements, labels),
        "asks": {str(ask.ref): _ask_json(ask, choices.tries, labels, started) for ask in kept if ask.ref in used},
    }


def _value(part: str | None, empty: str) -> str:
    return empty if part is None else part


def _right(placements: Sequence[Placement]) -> int | None:
    """The share of the placements asked of their part that were right, as a whole percentage, or None when none were."""
    asked = [each for each in placements if each.asked]
    return _percent(sum(1 for each in asked if each.right), len(asked)) if asked else None


def _words(placements: Sequence[Placement], labels: Labels) -> list[dict]:
    by_word: dict[tuple[str, str | None], list[Placement]] = {}
    for each in placements:
        by_word.setdefault((word_key(each.ask.words[each.position]), each.belongs), []).append(each)
    shown = []
    for (word, part), mine in by_word.items():
        wrong = [each for each in mine if each.wrong]
        instead = Counter(each.put for each in wrong)
        top = sorted(instead.items(), key=lambda item: (-item[1], item[0] is None, labels.of(item[0]) if item[0] else ""))[:1]
        last = max((each.ask.day for each in wrong), default=None)
        asks = list(dict.fromkeys((each.ask.ref, each.position) for each in mine))
        shown.append(
            {
                "id": f"{word}|{_value(part, NO_PART)}",
                "word": word,
                "part": _value(part, NO_PART),
                "part_label": labels.of(part),
                "sentences": len(asks),
                "placements": len(mine),
                "right": _right(mine),
                "instead": (
                    {"part": _value(top[0][0], LEFT_OUT), "label": LEFT_OUT_LABEL if top[0][0] is None else labels.of(top[0][0]), "count": top[0][1]}
                    if top
                    else None
                ),
                "last_misplaced": None if last is None else format_day(last),
                "last_misplaced_day": None if last is None else last.isoformat(),
                "asks": [[ref, position] for ref, position in reversed(asks)],
            }
        )
    return sort_words(shown)


def sort_words(words: list[dict]) -> list[dict]:
    """The list's first order: Right, smallest first, with not asked last, then Placements, largest first, then the word."""
    return sorted(words, key=lambda row: (row["right"] is None, row["right"] or 0, -row["placements"], row["word"], row["part_label"]))


def _ask_json(ask: Ask, tries: Sequence[int], labels: Labels, started: Callable[[Attempt], str]) -> dict:
    return {
        "attempt": ask.attempt.id,
        "started": started(ask.attempt),
        "day": _wall(ask.attempt.started_at).date().isoformat(),
        "task": ask.attempt.task,
        "pieces": segments(ask.text),
        "belongs": [_value(part, NO_PART) for part in ask.belongs],
        # Every try, so a chosen word shows where he put it each time. ``kept`` says which tries the Try filter chose.
        "tries": [[_value(put, LEFT_OUT) for put in placed] for placed in ask.tries],
        "kept": [number for number in range(1, len(ask.tries) + 1) if number in tries],
        "labels": {part: labels.of(part) for part in {*filter(None, ask.belongs), *(put for placed in ask.tries for put in placed if put)}},
    }


def pair_placements(data: Mapping, belongs: str, put: str) -> list[dict]:
    """The placements of one cell, newest first: each sentence with the word marked, its attempt, and the try."""
    found = []
    for ref, ask in sorted(data["asks"].items(), key=lambda item: -int(item[0])):
        for number in ask["kept"]:
            for position, (part, placed) in enumerate(zip(ask["belongs"], ask["tries"][number - 1])):
                if part == belongs and placed == put:
                    found.append({**_where(ask), "sentence": _marked(ask, position), "try": number})
    return found


def word_asks(data: Mapping, word: Mapping) -> list[dict]:
    """The sentences that asked a word in its part, newest first, with where he put it on each try."""
    found = []
    for ref, position in word["asks"]:
        ask = data["asks"][str(ref)]
        found.append({**_where(ask), "sentence": _marked(ask, position), "placed": [put_label(ask, placed[position]) for placed in ask["tries"]]})
    return found


def put_label(ask: Mapping, put: str) -> str:
    return LEFT_OUT_LABEL if put == LEFT_OUT else ask["labels"].get(put, put)


def _where(ask: Mapping) -> dict:
    return {"attempt": ask["attempt"], "started": ask["started"], "task": ask["task"]}


def _marked(ask: Mapping, position: int) -> str:
    """The sentence with one word in square brackets, as the tool gives it."""
    return "".join(f"[{piece['text']}]" if piece.get("word") == position else piece["text"] for piece in ask["pieces"])


def no_sentences(client: str) -> str:
    return f"No parts of speech sentences for {client} in this period."


# A parts of speech attempt's page.


def parts_of_speech_runs(attempt: Attempt, stamp: Callable[[str], str], root: Path | None = None) -> dict | None:
    """Return a parts of speech attempt's runs for its page: the last run, then each expired run in order.

    Each run has its figures, as S035.1 works them out, with the sentences
    right on each try, and its sentences in order, each with every try
    judged as the quiz judged it. None when the attempt holds no parts of
    speech record. ``root`` is where the pools are, which only the words'
    links to the confusions page use.
    """
    detail = attempt.detail if isinstance(attempt.detail, Mapping) else {}
    questions, runs = detail.get("questions"), detail.get("runs")
    if attempt.task_type != PARTS_OF_SPEECH or not isinstance(questions, list) or not isinstance(runs, list):
        return None
    settings = detail.get("settings") if isinstance(detail.get("settings"), Mapping) else {}
    filtered = isinstance(settings.get("parts_of_speech"), list)
    pool_names = [str(name) for name in settings.get("pools", []) if isinstance(name, str)] if isinstance(settings.get("pools"), list) else []
    lookup = PoolLookup(root)
    shown = []
    for run in runs:
        if not isinstance(run, Mapping):
            continue
        number = run.get("run")
        mine = [item for item in questions if isinstance(item, Mapping) and item.get("run") == number]
        found = figures(PARTS_OF_SPEECH, detail, number)
        expired = run.get("expired")
        by_try = Counter(item.get("correct_try") for item in mine if item.get("outcome") == CORRECT)
        shown.append(
            {
                "run": number,
                "expired": stamp(expired) if isinstance(expired, str) else None,
                "figures": None if found is None else found.as_json(),
                "right_on_try": [by_try[each] for each in TRY_CHOICES],
                "sentences": [_sentence(item, filtered, pool_names, lookup) for item in mine],
            }
        )
    if not shown:
        return None
    return {"last": shown[-1], "expired": shown[:-1]}


def _sentence(question: Mapping, filtered: bool, pool_names: Sequence[str], lookup: PoolLookup) -> dict:
    words = [item for item in question.get("words", []) if isinstance(item, Mapping)] if isinstance(question.get("words"), list) else []
    texts = [str(item.get("word", "")) for item in words]
    text = question.get("sentence") if isinstance(question.get("sentence"), str) else " ".join(texts)
    expected = [item.get("part") if isinstance(item.get("part"), str) else None for item in words]
    # The links name the part the confusions page puts the word in, which may come from the pool now.
    linked = belongs_in(question, filtered, lookup.find(pool_names, text, texts))
    tries = [each for each in question.get("tries", []) if isinstance(each, Mapping)] if isinstance(question.get("tries"), list) else []
    outcome = question.get("outcome")
    tries_shown = []
    for sent in tries:
        table = sent.get("placements") if isinstance(sent.get("placements"), Mapping) else {}
        placed = {position: name for name, numbers in table.items() for position in (numbers if isinstance(numbers, list) else ()) if isinstance(position, int)}
        marks = []
        for position, part in enumerate(expected):
            put = placed.get(position)
            if put is not None:
                right = put == part
                label = put
            elif part is not None:
                right, label = False, LEFT_OUT_LABEL
            else:
                right, label = True, None
            marks.append(
                {
                    "label": label,
                    "right": right,
                    "belongs": part or NO_PART_LABEL,
                    "link": linked[position] or NO_PART if position < len(linked) else NO_PART,
                }
            )
        tries_shown.append({"words": marks, "timer": sent.get("expired") is True, "taken_ms": _ms(sent.get("received_ms"))})
    return {
        "text": text,
        "pieces": segments(text),
        "words": [word_key(each) for each in texts],
        "outcome": outcome if outcome in OUTCOMES else None,
        "outcome_label": OUTCOMES.get(outcome, "Not answered yet"),
        "points": question.get("points") if isinstance(question.get("points"), (int, float)) and not isinstance(question.get("points"), bool) else 0,
        "taken_ms": _taken(question, tries),
        "allowed_ms": _ms(question.get("allowed_ms")),
        "no_try": outcome == TIMEOUT and not tries,
        "tries": tries_shown,
    }


def _taken(question: Mapping, tries: Sequence[Mapping]) -> int | None:
    if question.get("outcome") is None:
        return None
    if question.get("outcome") == TIMEOUT:
        return _ms(question.get("allowed_ms"))
    return _ms(tries[-1].get("received_ms")) if tries else None


def _issued_day(question: Mapping, fallback: datetime) -> date:
    issued = question.get("issued")
    if isinstance(issued, str):
        try:
            return datetime.fromisoformat(issued).replace(tzinfo=None).date()
        except ValueError:
            pass
    return _wall(fallback).date()


def _percent(part: int, whole: int) -> int | None:
    return math.floor(100 * part / whole + 0.5) if whole else None


def _ms(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, round(value))


def _wall(moment: datetime) -> datetime:
    return moment.replace(tzinfo=None, microsecond=0)
