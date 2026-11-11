"""The rules for a task's name, and the file in ``tasks.d`` a new or renamed task is written to.

A name is checked when the parent portal creates or renames a task. A task's
file name comes from its name: lower-cased, with accented letters folded to
ASCII, ASCII letters, digits, and ``-`` kept, and every run of anything else
written as one ``_``. When that name is used in the directory, with either
``.yaml`` or ``.yml``, ``.2``, ``.3``, and so on is added before ``.yaml``.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

LONGEST_NAME = 40
EXTENSION = ".yaml"
_EXTENSIONS = (".yaml", ".yml")
# Letters that Unicode decomposition does not reduce to ASCII.
_FOLDS = str.maketrans(
    {"ß": "ss", "æ": "ae", "ø": "o", "ł": "l", "đ": "d", "ð": "d", "þ": "th", "œ": "oe", "ı": "i", "ħ": "h", "ŀ": "l"}
)
_OTHER = re.compile(r"[^a-z0-9-]+")


def name_problem(name: str) -> str | None:
    """Return why a task name cannot be used, or None."""
    if name == "":
        return "Give the task a name."
    if name != name.strip():
        return "A name has no space at either end."
    if len(name) > LONGEST_NAME:
        return f"A name is at most {LONGEST_NAME} characters."
    if "/" in name:
        return "A name cannot hold a /, because the task's address could not."
    return None


def file_stem(name: str) -> str:
    """Return the file name a task's name gives, without its extension, such as ``cafe_sums`` for ``Café Sums``."""
    folded = unicodedata.normalize("NFKD", name.lower().translate(_FOLDS))
    plain = "".join(char for char in folded if not unicodedata.combining(char))
    return _OTHER.sub("_", plain)


def free_file(directory: Path, name: str, own: Path | None = None) -> Path:
    """Return the first file for ``name`` that no other file in ``directory`` uses.

    ``own`` is the task's own file, which is never a clash. When the name
    comes out as that file, with either extension, that file is returned.
    """
    stem = file_stem(name)
    own_base = None if own is None else _base(own.name)
    used = set()
    if directory.is_dir():
        used = {_base(child.name) for child in directory.iterdir() if _base(child.name) != own_base}
    number = 1
    while True:
        base = stem if number == 1 else f"{stem}.{number}"
        if base not in used:
            return own if own is not None and base == own_base else directory / (base + EXTENSION)
        number += 1


def _base(file_name: str) -> str | None:
    lowered = file_name.lower()
    for extension in _EXTENSIONS:
        if lowered.endswith(extension):
            return lowered[: -len(extension)]
    return None
