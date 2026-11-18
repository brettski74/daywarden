"""The capitalisation pool editor's data, and the capitalisation task page's.

A pool is a file in ``capitalisation_pools/`` (S040.1), edited on a pool page under
Asset Administration (S040.2) as a parts of speech pool is (S031.2), with no
rows of words to sort. The page is told each sentence's text and its own level
of difficulty. A save sends the sentences back in order, each with the place it
had in the file, or none for a new one. A sentence sent back as it was loaded
keeps its text in the file exactly. Any other is written again as plain text,
or as a mapping with ``level_of_difficulty`` when its own level differs from
the pool's.

The task page has the four settings and the pools it names, as a parts of
speech task page has, and no filter of parts.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from policy.capitalisation import has_capital, split_words
from policy.parts_of_speech_admin import LEVEL, SETTINGS, _names, level, pool_list, shown_level
from policy.sentence_pools import CAPITALISATION_DIR
from policy.task_edit import ListEdit, ListItem, WrittenTask, name_list

NO_CAPITAL = "The sentence has no capital letter, so there is nothing to click."
EMPTY = "The sentence is empty."
NO_POOLS = "Choose at least one pool."


def shown_sentences(listed: object) -> tuple[list[dict], list[str]]:
    """Return each sentence as the page shows it, and why any entry could not be shown."""
    if listed is None:
        return [], []
    if not isinstance(listed, list):
        return [], ["sentences: must be a list of sentences"]
    shown: list[dict] = []
    problems: list[str] = []
    for number, item in enumerate(listed, 1):
        text, own = _read(item)
        if text is None:
            problems.append(f"sentences entry {number}: must be a sentence, or a mapping with sentence and level_of_difficulty")
            text = ""
        shown.append({"text": text, LEVEL: own})
    return shown, problems


def _read(item: object) -> tuple[str | None, str]:
    if isinstance(item, str):
        return item, ""
    if isinstance(item, Mapping) and isinstance(item.get("sentence"), str):
        return item["sentence"], shown_level(item.get(LEVEL))
    return None, ""


def sentences_edit(listed: object, asked: object, pool_level: float) -> ListEdit | None:
    """Return the new ``sentences`` list a save asks for, or None when it is the list as written.

    ``pool_level`` is the pool's level of difficulty after the save, so a
    sentence at that level is written without its own. Raises ``ValueError``
    for a request the page would never send, a sentence with no capital, or a
    level of difficulty out of range.
    """
    if asked is None:
        return None
    if not isinstance(asked, list):
        raise ValueError("sentences must be a list of sentences")
    originals = listed if isinstance(listed, list) else []
    items: list[ListItem] = []
    last = -1
    for number, sent in enumerate(asked, 1):
        where = f"sentence {number}"
        if not isinstance(sent, Mapping):
            raise ValueError(f"{where} must be a mapping")
        origin, text, typed = sent.get("origin"), sent.get("text"), sent.get(LEVEL) or ""
        if origin is not None and (isinstance(origin, bool) or not isinstance(origin, int) or not 0 <= origin < len(originals)):
            raise ValueError(f"{where} names no sentence in the file. Reload the page and make the change again.")
        if not isinstance(text, str) or not isinstance(typed, str):
            raise ValueError(f"{where} must have its text and its level of difficulty")
        if origin is not None:
            if origin <= last:
                raise ValueError("the sentences must keep their order")
            last = origin
            before_text, before_level = _read(originals[origin])
            if (text, typed.strip()) == (before_text, before_level.strip()):
                items.append(ListItem(origin, originals[origin], False))
                continue
        words = split_words(text)
        if not words:
            raise ValueError(f"{where}: {EMPTY}")
        if not any(has_capital(word) for word in words):
            raise ValueError(f"{where}: {NO_CAPITAL}")
        own = level(typed, f"{where}: {LEVEL}")
        written = " ".join(words)
        data: object = written
        if own is not None and float(own) != float(pool_level):
            data = {"sentence": written, LEVEL: own}
        items.append(ListItem(origin, data, True))
    unchanged = all(not item.changed for item in items) and [item.origin for item in items] == list(range(len(originals)))
    return None if unchanged else ListEdit(tuple(items))


def _listed(written: WrittenTask) -> list[str]:
    found = written.body_data.get("pools")
    return [str(item).strip() for item in found] if isinstance(found, list) else []


def page(written: WrittenTask, root: Path) -> dict:
    """Return the capitalisation area of a task page: its settings, its pools, and the pools it could name."""
    return {
        "settings": {key: written.body.get(key, "") for key in SETTINGS},
        "pools": _listed(written),
        "available": [
            {"id": entry["id"], "name": entry["name"], "sentences": entry["sentences"]}
            for entry in pool_list(root, CAPITALISATION_DIR)
            if "problem" not in entry
        ],
    }


def list_changes(written: WrittenTask, request: Mapping) -> dict[str, object]:
    """Return the body change the page's pools ask for, as a ``rewrite_task`` change. A list as written is left as written."""
    pools = request.get("pools")
    if pools is None:
        return {}
    names = _names(pools, "pools")
    if not names:
        raise ValueError(NO_POOLS)
    if "" in names:
        raise ValueError("A pool name must not be empty.")
    return {"pools": name_list(names)} if names != _listed(written) else {}
