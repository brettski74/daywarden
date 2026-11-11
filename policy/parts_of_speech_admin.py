"""The parts of speech area of a task page: the sentences as the page shows them, and the list a save writes.

The page is told each sentence's text, its own timeout, and its rows in the
order written, each row's words as positions in the sentence. A save sends
the sentences back in the same form, each with the place it had in the file,
or none for a new one. A sentence sent back as it was loaded keeps its text
in the file exactly. Every other sentence is written again from what the
page sent, with its row names tidied: a recognized part of speech becomes
the listed name, lower case and singular, and any other name is
lower-cased. Two rows that then share a name are written as one, in the
first one's place.

The list of recognized names is a portal convention, not a loader rule. A
hand-written file may use any name.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from policy.parts_of_speech import Word, entry_positions, split_words
from policy.task_edit import ListEdit, ListItem, WrittenTask

SETTINGS = ("timeout", "correct_answers_required")
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


@dataclass(frozen=True)
class Written:
    """One sentence as the file writes it, and its rows as positions in the sentence."""

    text: str
    timeout: str
    parts: tuple[tuple[str, tuple[int, ...]], ...]
    data: object


def page(written: WrittenTask) -> dict:
    """Return the parts of speech area of the task page."""
    sentences, problems = _read(written)
    return {
        "settings": {key: written.body.get(key, "") for key in SETTINGS},
        "sentences": [
            {
                "text": sentence.text,
                "timeout": sentence.timeout,
                "parts": [{"name": name, "words": list(words)} for name, words in sentence.parts],
            }
            for sentence in sentences
        ],
        "problems": problems,
    }


def sentences_edit(written: WrittenTask, asked: object) -> ListEdit | None:
    """Return the new ``sentences`` list a save asks for, or None when it is the list as written.

    Raises ``ValueError`` for a request the page would never send.
    """
    if asked is None:
        return None
    if not isinstance(asked, list):
        raise ValueError("sentences must be a list of sentences")
    originals, _problems = _read(written)
    items: list[ListItem] = []
    last = -1
    for number, sent in enumerate(asked, 1):
        origin, text, timeout, parts = _sent(sent, number, len(originals))
        if origin is not None:
            if origin <= last:
                raise ValueError("the sentences must keep their order")
            last = origin
            before = originals[origin]
            if (text, timeout, parts) == (before.text, before.timeout.strip(), before.parts):
                items.append(ListItem(origin, before.data, False))
                continue
        items.append(ListItem(origin, _data(text, timeout, parts), True))
    unchanged = all(not item.changed for item in items) and [item.origin for item in items] == list(range(len(originals)))
    return None if unchanged else ListEdit(tuple(items))


def _read(written: WrittenTask) -> tuple[list[Written], list[str]]:
    """Return each sentence the file lists, and why any entry in it could not be shown."""
    if "sentences" not in written.body_data:
        return [], []
    listed = written.body_data["sentences"]
    if not isinstance(listed, list):
        return [], ["sentences: must be a list of one or more sentences, each with sentence and parts"]
    sentences: list[Written] = []
    problems: list[str] = []
    for number, item in enumerate(listed, 1):
        where = f"sentences entry {number}"
        if not isinstance(item, Mapping):
            problems.append(f"{where}: must be a mapping with sentence and parts")
            sentences.append(Written("", "", (), item))
            continue
        text = item.get("sentence") if isinstance(item.get("sentence"), str) else ""
        timeout = "" if item.get("timeout") is None else str(item["timeout"])
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
        sentences.append(Written(text, timeout, tuple(parts), item))
    return sentences, problems


def _sent(sent: object, number: int, count: int) -> tuple[int | None, str, str, tuple[tuple[str, tuple[int, ...]], ...]]:
    where = f"sentence {number}"
    if not isinstance(sent, Mapping):
        raise ValueError(f"{where} must be a mapping")
    origin = sent.get("origin")
    if origin is not None and (isinstance(origin, bool) or not isinstance(origin, int) or not 0 <= origin < count):
        raise ValueError(f"{where} names no sentence in the file. Reload the page and make the change again.")
    text, timeout, rows = sent.get("text"), sent.get("timeout") or "", sent.get("parts")
    if not isinstance(text, str) or not isinstance(timeout, str) or not isinstance(rows, list):
        raise ValueError(f"{where} must have its text, its timeout, and a list of rows")
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
    return origin, text, timeout.strip(), tuple(parts)


def _data(text: str, timeout: str, parts: tuple[tuple[str, tuple[int, ...]], ...]) -> dict:
    """Return a sentence as a save writes it: tidied row names, rows that share one merged, words as entries."""
    words = split_words(text)
    rows: dict[str, list[int]] = {}
    for name, positions in parts:
        rows.setdefault(tidy(name), []).extend(positions)
    data: dict[str, object] = {
        "sentence": text,
        "parts": {name: [_entry(words[position]) for position in sorted(positions)] for name, positions in rows.items()},
    }
    if timeout:
        data["timeout"] = timeout
    return data


def _entry(word: Word) -> str:
    return word.text if word.occurrence == 1 else f"{word.text}[{word.occurrence}]"
