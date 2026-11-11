"""The directories under the spelling directory that a spelling task's pull-downs choose from.

The spelling directory is ``spelling/`` in the data directory. Its
directories, at any depth, are listed relative to it, leaving out any whose
name, or a parent's name, starts with ``.``. A new one is made from the
parent portal by name, checked here only, so the page and the service never
disagree about what a name may be.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path

import yaml

from policy import spelling
from policy.owned import make_directory

SPELLING_DIR = "spelling"
FIELDS = ("current_dir", "revision_dir", "attic_dir", "alphabet_dir")
LONGEST_PART = 255
_PUNCTUATION = frozenset(" -_.")
_BARE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")

NO_NAME = "Give the directory a name."
SLASHES = "A name is one or more parts separated by single / characters, with no / at either end."
CHARACTERS = "A part of the name may only have letters, digits, spaces, -, _, and ."
DOT = "A part of the name may not start with a dot."
SPACE = "A part of the name may not start or end with a space."
TOO_LONG = f"A part of the name may be at most {LONGEST_PART} bytes."


class NameRefused(ValueError):
    """A new directory's name is not allowed, and why."""


def folders(root: Path) -> list[str]:
    """Return every directory under the spelling directory, relative to it, in name order."""
    top = root / SPELLING_DIR
    found: list[str] = []
    for here, names, _files in os.walk(top):
        names[:] = [name for name in names if not name.startswith(".")]
        base = Path(here).relative_to(top)
        found += [(base / name).as_posix() for name in names]
    return sorted(found, key=_order)


def _order(path: str) -> list[tuple[str, str]]:
    return [(part.casefold(), part) for part in path.split("/")]


def make(root: Path, name: object) -> str:
    """Make a directory under the spelling directory, with any missing parents, and return its path relative to it.

    A space at either end of the name is ignored. Parts that already exist,
    in any case, are used as the disk has them.
    """
    parts = _parts(name)
    here = root / SPELLING_DIR
    made: list[str] = []
    for index, part in enumerate(parts):
        existing = _entry(here, part)
        if existing is None:
            made += parts[index:]
            break
        made.append(existing.name)
        if not existing.is_dir():
            if index == len(parts) - 1:
                raise NameRefused(f"`{'/'.join(made)}` already exists.")
            raise NameRefused(f"`{'/'.join(made)}` is a file, so it cannot hold a directory.")
        here = existing
    else:
        raise NameRefused(f"`{'/'.join(made)}` already exists.")
    make_directory(root / SPELLING_DIR / Path(*made))
    return "/".join(made)


def _parts(name: object) -> list[str]:
    if not isinstance(name, str) or not name.strip():
        raise NameRefused(NO_NAME)
    parts = name.strip().split("/")
    if "" in parts:
        raise NameRefused(SLASHES)
    for part in parts:
        if any(not (character.isalnum() or character in _PUNCTUATION) for character in part):
            raise NameRefused(CHARACTERS)
        if part.startswith("."):
            raise NameRefused(DOT)
        if part != part.strip(" "):
            raise NameRefused(SPACE)
        if len(part.encode("utf-8")) > LONGEST_PART:
            raise NameRefused(TOO_LONG)
    return parts


def _entry(directory: Path, name: str) -> Path | None:
    """Return what is called ``name`` in a directory, compared without regard to case, or None."""
    wanted = name.casefold()
    try:
        with os.scandir(directory) as listing:
            for child in listing:
                if child.name.casefold() == wanted:
                    return Path(child.path)
    except OSError:
        return None
    return None


def saved(body: Mapping[str, str]) -> dict[str, str]:
    """Return each directory field's path from the data directory, as a body writes it or by default."""
    shown = {}
    for field in FIELDS:
        value = body.get(field, spelling._DIRECTORIES[field])
        try:
            shown[field] = spelling._directory(value, field)
        except ValueError:
            shown[field] = str(value).strip()
    return shown


def same_directory(chosen: Mapping[str, str]) -> tuple[str, str] | None:
    """Return the first two fields, in order, that name the same directory, or None."""
    seen: dict[str, str] = {}
    for field in FIELDS:
        path = chosen.get(field)
        if path is None:
            continue
        if path in seen:
            return seen[path], field
        seen[path] = field
    return None


def chosen(body: Mapping[str, str], asked: object) -> dict[str, str]:
    """Return the directories ``asked`` puts in place of a body's, checked, as paths from the data directory.

    ``asked`` maps any of the four fields to a path from the data directory.
    A path that is absolute or uses ``..``, or two fields on one directory,
    raises ``ValueError``.
    """
    directories = saved(body)
    if asked is None:
        return directories
    if not isinstance(asked, Mapping):
        raise ValueError("directories must map each directory field to its path")
    for field, value in asked.items():
        if field not in FIELDS:
            raise ValueError(f"{field} is not a spelling directory field")
        directories[field] = spelling._directory(value, field)
    same = same_directory(directories)
    if same is not None:
        raise ValueError(f"{same[0]} and {same[1]} are the same directory.")
    return directories


def written(path: str) -> str:
    """Return the YAML for a directory path: bare, such as ``spelling/year-3/revision``, unless it would read as anything else."""
    if _BARE.fullmatch(path) and yaml.safe_load(path) == path:
        return path
    return json.dumps(path, ensure_ascii=False)


def from_query(query: Mapping[str, str]) -> dict[str, str]:
    """Return the directory fields a query string names."""
    return {field: query[field] for field in FIELDS if field in query}
