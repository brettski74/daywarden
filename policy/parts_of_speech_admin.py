"""The parts of speech sentence editor's data: the sentences as the page shows them, and the list a save writes.

Sentences live in pool files (S031.1) and are edited on a pool's page under
Asset Administration (S031.2). The page is told each sentence's text, its own
level of difficulty, and its rows in the order written, each row's words as
positions in the sentence. A save sends the sentences back in the same form,
each with the place it had in the file, or none for a new one. A sentence
sent back as it was loaded keeps its text in the file exactly. Every other
sentence is written again from what the page sent, with its row names tidied:
a recognized part of speech becomes the listed name, lower case and singular,
and any other name is lower-cased. Two rows that then share a name are
written as one, in the first one's place. A sentence's level of difficulty is
written only when it differs from the pool's.

The list of recognized names is a portal convention, not a loader rule. A
hand-written file may use any name.

A parts of speech task page (S031.3) shows the task's own settings, the pools it
names and every pool available to name, and its filter of part names. A save
writes ``pools`` and ``parts_of_speech`` only when the page's list differs from
the file's, so a list left alone keeps its text exactly. A filter that is
written has every name tidied as a row name is.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from policy import sentence_pools
from policy.parts_of_speech import Word, entry_positions, split_words
from policy.sentence_pools import parse_difficulty
from policy.task_edit import ListEdit, ListItem, WrittenTask, name_list

SETTINGS = ("timeout", "correct_answers_required", "minimum_questions", "maximum_questions")
NO_POOLS = "Choose at least one pool."
RECOGNIZED = (
    "noun",
    "proper noun",
    "pronoun",
    "verb",
    "participle",
    "gerund",
    "infinitive",
    "adjective",
    "adverb",
    "article",
    "determiner",
    "preposition",
    "conjunction",
    "interjection",
)
LEVEL = "level_of_difficulty"


def recognized(name: str) -> str | None:
    """Return the listed part of speech a name stands for, ignoring case, spaces at the ends, and a plural ``s``."""
    folded = name.strip().lower()
    for listed in RECOGNIZED:
        if folded in (listed, listed + "s"):
            return listed
    return None


def tidy(name: str) -> str:
    """Return a row name as a save writes it."""
    return recognized(name) or name.strip().lower()


def shown_level(value: object) -> str:
    """Return a level of difficulty as the page shows it: ``2`` rather than ``2.0``."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def level(text: str, where: str) -> int | float | None:
    """Return the level of difficulty typed on the page, or None when it is empty.

    Raises ``ValueError`` naming ``where`` for text that is not a number from 0.5 through 10.
    """
    typed = text.strip()
    if not typed:
        return None
    try:
        number = float(typed)
    except ValueError:
        number = math.nan
    if not math.isfinite(number):
        raise ValueError(f"{where}: must be a number from 0.5 through 10")
    parse_difficulty(number, where)
    return int(number) if number.is_integer() else number


def pool_list(root: Path, folder: str = sentence_pools.POOLS_DIR) -> list[dict]:
    """Return every pool file, by name ignoring case: its id, name, level of difficulty, and how many sentences."""
    pools = []
    for path in sentence_pools.list_pool_files(root, folder):
        entry: dict[str, object] = {"id": path.stem, "name": path.stem, LEVEL: "", "sentences": 0}
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
            entry["problem"] = str(error)
            pools.append(entry)
            continue
        if not isinstance(data, Mapping):
            entry["problem"] = "The file is not a mapping with name and sentences."
            pools.append(entry)
            continue
        name = data.get("name")
        if isinstance(name, str) and name.strip():
            entry["name"] = name.strip()
        entry[LEVEL] = shown_level(data.get(LEVEL))
        listed = data.get("sentences")
        entry["sentences"] = len(listed) if isinstance(listed, list) else 0
        pools.append(entry)
    pools.sort(key=lambda entry: (str(entry["name"]).casefold(), str(entry["name"]), str(entry["id"])))
    return pools


def _listed(written: WrittenTask, key: str) -> list[str]:
    """Return the names the file lists under ``key``, as text, or none when it is not a list."""
    found = written.body_data.get(key)
    return [str(item).strip() for item in found] if isinstance(found, list) else []


def page(written: WrittenTask, root: Path) -> dict:
    """Return the parts of speech area of a task page: its settings, its pools and filter, and the pools it could name."""
    return {
        "settings": {key: written.body.get(key, "") for key in SETTINGS},
        "pools": _listed(written, "pools"),
        "filter": _listed(written, "parts_of_speech"),
        "available": [
            {"id": entry["id"], "name": entry["name"], "sentences": entry["sentences"]}
            for entry in pool_list(root)
            if "problem" not in entry
        ],
    }


def _names(asked: object, field: str) -> list[str]:
    if not isinstance(asked, list) or not all(isinstance(name, str) for name in asked):
        raise ValueError(f"{field} must be a list of names")
    return [name.strip() for name in asked]


def list_changes(written: WrittenTask, request: Mapping) -> dict[str, object]:
    """Return the body changes the page's pools and filter ask for, as ``rewrite_task`` changes.

    A list that is the same as the file's is left as written. An empty filter
    removes ``parts_of_speech``, so each sentence uses its own parts.
    """
    changes: dict[str, object] = {}
    pools = request.get("pools")
    if pools is not None:
        names = _names(pools, "pools")
        if not names:
            raise ValueError(NO_POOLS)
        if "" in names:
            raise ValueError("A pool name must not be empty.")
        if names != _listed(written, "pools"):
            changes["pools"] = name_list(names)
    asked = request.get("parts_of_speech")
    if asked is not None:
        names = _names(asked, "parts_of_speech")
        if names != _listed(written, "parts_of_speech"):
            if "" in names:
                raise ValueError("A part of speech name must not be empty.")
            changes["parts_of_speech"] = name_list([tidy(name) for name in names]) if names else None
    return changes


@dataclass(frozen=True)
class Written:
    """One sentence as the file writes it, and its rows as positions in the sentence."""

    text: str
    level: str
    parts: tuple[tuple[str, tuple[int, ...]], ...]
    data: object


Parts = tuple[tuple[str, tuple[int, ...]], ...]


def shown_sentences(listed: object) -> tuple[list[dict], list[str]]:
    """Return each sentence as the page shows it, and why any entry could not be shown."""
    sentences, problems = read_sentences(listed)
    return [
        {
            "text": sentence.text,
            LEVEL: sentence.level,
            "parts": [{"name": name, "words": list(words)} for name, words in sentence.parts],
        }
        for sentence in sentences
    ], problems


def sentences_edit(listed: object, asked: object, pool_level: float) -> ListEdit | None:
    """Return the new ``sentences`` list a save asks for, or None when it is the list as written.

    ``listed`` is the list as the file holds it. ``pool_level`` is the pool's
    level of difficulty after the save, so a sentence at that level is written
    without its own. Raises ``ValueError`` for a request the page would never
    send, or a level of difficulty out of range.
    """
    if asked is None:
        return None
    if not isinstance(asked, list):
        raise ValueError("sentences must be a list of sentences")
    originals, _problems = read_sentences(listed)
    items: list[ListItem] = []
    last = -1
    for number, sent in enumerate(asked, 1):
        origin, text, typed, parts = _sent(sent, number, len(originals))
        if origin is not None:
            if origin <= last:
                raise ValueError("the sentences must keep their order")
            last = origin
            before = originals[origin]
            if (text, typed, parts) == (before.text, before.level.strip(), before.parts):
                items.append(ListItem(origin, before.data, False))
                continue
        items.append(ListItem(origin, _data(text, level(typed, f"sentence {number}: {LEVEL}"), pool_level, parts), True))
    unchanged = all(not item.changed for item in items) and [item.origin for item in items] == list(range(len(originals)))
    return None if unchanged else ListEdit(tuple(items))


def read_sentences(listed: object) -> tuple[list[Written], list[str]]:
    """Return each sentence a ``sentences`` list holds, and why any entry in it could not be shown."""
    if listed is None:
        return [], []
    if not isinstance(listed, list):
        return [], ["sentences: must be a list of sentences, each with sentence and parts"]
    sentences: list[Written] = []
    problems: list[str] = []
    for number, item in enumerate(listed, 1):
        where = f"sentences entry {number}"
        if not isinstance(item, Mapping):
            problems.append(f"{where}: must be a mapping with sentence and parts")
            sentences.append(Written("", "", (), item))
            continue
        text = item.get("sentence") if isinstance(item.get("sentence"), str) else ""
        words = split_words(text)
        table = item.get("parts") if isinstance(item.get("parts"), Mapping) else {}
        taken: set[int] = set()
        parts: list[tuple[str, tuple[int, ...]]] = []
        for name, entries in table.items():
            positions: list[int] = []
            for entry_number, entry in enumerate(entries if isinstance(entries, list) else [], 1):
                try:
                    found = entry_positions(entry, entry_number, words, f"{where}: parts.{name}")
                except ValueError as error:
                    problems.append(str(error))
                    continue
                positions += [position for position in found if position not in taken]
                taken.update(found)
            parts.append((str(name), tuple(sorted(set(positions)))))
        sentences.append(Written(text, shown_level(item.get(LEVEL)), tuple(parts), item))
    return sentences, problems


def _sent(sent: object, number: int, count: int) -> tuple[int | None, str, str, Parts]:
    where = f"sentence {number}"
    if not isinstance(sent, Mapping):
        raise ValueError(f"{where} must be a mapping")
    origin = sent.get("origin")
    if origin is not None and (isinstance(origin, bool) or not isinstance(origin, int) or not 0 <= origin < count):
        raise ValueError(f"{where} names no sentence in the file. Reload the page and make the change again.")
    text, typed, rows = sent.get("text"), sent.get(LEVEL) or "", sent.get("parts")
    if not isinstance(text, str) or not isinstance(typed, str) or not isinstance(rows, list):
        raise ValueError(f"{where} must have its text, its level of difficulty, and a list of rows")
    words = len(split_words(text))
    placed: set[int] = set()
    parts: list[tuple[str, tuple[int, ...]]] = []
    for row in rows:
        name, positions = (row.get("name"), row.get("words")) if isinstance(row, Mapping) else (None, None)
        if not isinstance(name, str) or not isinstance(positions, list):
            raise ValueError(f"{where}: each row must have a name and a list of words")
        for position in positions:
            if isinstance(position, bool) or not isinstance(position, int) or not 0 <= position < words:
                raise ValueError(f"{where}: word {position!r} is not in the sentence")
            if position in placed:
                raise ValueError(f"{where}: word {position} is in more than one row")
            placed.add(position)
        parts.append((name, tuple(sorted(positions))))
    return origin, text, typed.strip(), tuple(parts)


def _data(text: str, own: int | float | None, pool_level: float, parts: Parts) -> dict:
    """Return a sentence as a save writes it: tidied row names, rows that share one merged, words as entries.

    Its own level of difficulty is written only when it differs from the pool's.
    """
    words = split_words(text)
    rows: dict[str, list[int]] = {}
    for name, positions in parts:
        rows.setdefault(tidy(name), []).extend(positions)
    data: dict[str, object] = {"sentence": text}
    if own is not None and float(own) != float(pool_level):
        data[LEVEL] = own
    data["parts"] = {name: [_entry(words[position]) for position in sorted(positions)] for name, positions in rows.items()}
    return data


def _entry(word: Word) -> str:
    return word.text if word.occurrence == 1 else f"{word.text}[{word.occurrence}]"
