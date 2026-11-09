"""Setting up a new week's spelling words from the parent portal.

The parent types the week's words, records them, and applies the list. Until
Apply, the setup in progress is kept on the service, one for each spelling
task, in ``.weeks/<task>/`` under the data directory: ``state.json`` holds
the list, the sentence text typed for each word, and the clips kept for it,
and the kept clips sit beside it. The pool scans never look there, and Apply
is a set of renames on one file system.

Apply, in one step, moves every current word that is not on the list into
revision, moves each listed revision or attic word into current, writes each
kept clip into current in place of the word's older clip of that kind, and
gives an existing plain word a number when the list adds a new numbered
meaning of it. An older clip is first moved aside into the setup, so every
step is a rename and a failure partway moves everything back. The setup,
with the older clips, is removed once Apply has gone through.

The sentence text is only a prompt for the speaker. It is never written into
a pool or a policy file.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from policy import spelling
from policy.owned import make_directory, own_like
from policy.recordings import GONE
from policy.task_admin import STALE, Answer, TaskAdmin, _changes, _settings, _version
from policy.task_edit import EditError, rewrite_task

DIRECTORY = ".weeks"
STATE = "state.json"
REPLACED = "replaced"
LONGEST_SENTENCE = 300
TARGETS = ("current_required", "revision_required")
KINDS = (spelling.WORD_CLIP, spelling.SENTENCE_CLIP)
NOT_A_WORD = "use only the letters a to z, - and ', with an optional .<n> such as read.1"
REFUSED = "Some of the words are not allowed, so the list was not saved."
_KEY = re.compile(r"^([A-Za-z'-]*[A-Za-z][A-Za-z'-]*)(?:\.([1-9][0-9]*))?$")
_LETTER = re.compile(r"[A-Za-z]")
_WORD_TEXT = re.compile(r"[^\s,]+")
_NUMBERED_END = re.compile(r"[A-Za-z]\.[1-9][0-9]*$")
# Curly apostrophes and Unicode hyphens, as pasted from a document or a web page, are the plain ones.
_LOOKALIKES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u02bc": "'", "\u2010": "-", "\u2011": "-"})
_CLIP = re.compile(r"^[0-9a-f]{8}\.opus$")
_PLAIN_TASK = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass
class Row:
    """One word on the week's list: its entry key, its sentence text, and the clip kept for each kind."""

    key: str
    sentence: str = ""
    clips: dict[str, str] = field(default_factory=dict)

    def record(self) -> dict:
        return {"key": self.key, "sentence": self.sentence, "clips": dict(self.clips)}


@dataclass(frozen=True)
class Plan:
    """How the week's list stands against the task's pools."""

    entries: dict[str, dict]
    renames: dict[str, str]
    # For each listed word that gives an existing plain word a number: that word's key and its new key.
    renamed_by: dict[str, tuple[str, str]]
    ambiguous: dict[str, list[dict]]
    suggested: dict[str, str]
    needs: list[str]


def split_key(key: str) -> tuple[str, int | None]:
    """Return a key's spelling and its homograph number, if it has one."""
    found = _KEY.fullmatch(key)
    if found is None:
        return key, None
    return found.group(1), int(found.group(2)) if found.group(2) else None


def split_words(text: str) -> list[tuple[int, str]]:
    """Return each word in pasted text, with the line it is on.

    Any run of commas and whitespace separates two words, so a list copied
    from an email or a class posting, such as ``(rope, cat, dog)``, splits
    as it is. Anything that is not a letter is trimmed from the start and the
    end of the whole text, such as the brackets around that list, except a
    homograph number such as ``read.1`` at the very end. Nothing else is
    trimmed, so a stray character between words is left for the parent to see.
    """
    text = text.translate(_LOOKALIKES)
    first = _LETTER.search(text)
    if first is None:
        return []
    start, end = first.start(), len(text)
    while not _LETTER.fullmatch(text[end - 1]) and not _NUMBERED_END.search(text, start, end):
        end -= 1
    return [(text.count("\n", 0, found.start()) + 1, found.group()) for found in _WORD_TEXT.finditer(text, start, end)]


def key_problem(key: str) -> str | None:
    """Return why a key cannot be a word on the list, with the same rule as the pools, or None."""
    if not _KEY.fullmatch(key):
        return NOT_A_WORD
    if len(key) > spelling.LONGEST_KEY:
        return f"it is longer than {spelling.LONGEST_KEY} characters"
    return None


def plan(rows: list[Row], entries: list[dict]) -> Plan:
    """Work out where each listed word is now, which plain words take a number, and which words are unclear.

    A plain word in the pools takes the next free number when the list adds
    a new numbered meaning of it, such as ``read.1`` beside an existing
    ``read``. A plain word on the list that is new, where the pools have
    numbered meanings of it, is unclear until the parent picks which.
    """
    existing = {entry["key"].lower(): entry for entry in entries}
    listed = {row.key.lower() for row in rows}
    numbers: dict[str, set[int]] = {}
    for key in [*existing, *listed]:
        word, number = split_key(key)
        if number is not None:
            numbers.setdefault(word.lower(), set()).add(number)

    def next_number(word: str) -> int:
        used = numbers.setdefault(word.lower(), set())
        number = 1
        while number in used:
            number += 1
        used.add(number)
        return number

    renames: dict[str, str] = {}
    renamed_by: dict[str, tuple[str, str]] = {}
    for row in rows:
        word, number = split_key(row.key)
        plain = existing.get(word.lower())
        if number is None or row.key.lower() in existing or plain is None or plain["key"].lower() in renames:
            continue
        renames[plain["key"].lower()] = f"{plain['word']}.{next_number(word)}"
        renamed_by[row.key.lower()] = (plain["key"], renames[plain["key"].lower()])
    ambiguous: dict[str, list[dict]] = {}
    suggested: dict[str, str] = {}
    for row in rows:
        word, number = split_key(row.key)
        if number is not None or row.key.lower() in existing:
            continue
        choices = [entry for key, entry in sorted(existing.items()) if split_key(key)[0] == word.lower() and split_key(key)[1]]
        if choices:
            ambiguous[row.key.lower()] = choices
            suggested[row.key.lower()] = f"{word}.{next_number(word)}"
    needs = [row.key for row in rows if row.key.lower() not in existing and spelling.WORD_CLIP not in row.clips]
    return Plan(existing, renames, renamed_by, ambiguous, suggested, needs)


class Weeks:
    """The new week's setup in progress for each spelling task."""

    def __init__(self, tasks: TaskAdmin) -> None:
        self.tasks = tasks

    def folder(self, name: str) -> Path:
        plain = name if _PLAIN_TASK.fullmatch(name) else "task-" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
        return self.tasks.data_root() / DIRECTORY / plain

    # Answers

    def page(self, name: str) -> Answer:
        found = self._task(name)
        if isinstance(found, Answer):
            return found
        path, text, written, settings = found
        rows = self._rows(name)
        body: dict = {
            "name": name,
            "version": _version(text),
            "file": str(path),
            "targets": {key: written.body.get(key, "") for key in TARGETS},
            "words": [],
            "needs": [],
            "ambiguous": [],
            "current": 0,
            "problems": [],
        }
        try:
            entries, problems = spelling.pool_entries(settings, self.tasks.data_root())
        except OSError as error:
            entries, problems = [], [str(error)]
        body["problems"] = problems
        body["current"] = sum(1 for entry in entries if entry["pool"] == spelling.CURRENT)
        planned = plan(rows, entries)
        for row in rows:
            folded = row.key.lower()
            entry = planned.entries.get(folded)
            body["words"].append(
                {
                    "key": row.key,
                    "word": split_key(row.key)[0],
                    "pool": None if entry is None else entry["pool"],
                    "becomes": planned.renames.get(folded),
                    "renames": None if folded not in planned.renamed_by else dict(zip(("from", "to"), planned.renamed_by[folded])),
                    "clip": None if entry is None else entry["clip"],
                    "sentence_clip": None if entry is None else entry["sentence"],
                    "kept": {kind: row.clips.get(kind) for kind in KINDS},
                    "sentence": row.sentence,
                    "choices": [
                        {"key": choice["key"], "pool": choice["pool"]} for choice in planned.ambiguous.get(folded, [])
                    ],
                    "new_key": planned.suggested.get(folded),
                }
            )
        body["needs"] = planned.needs
        body["ambiguous"] = [row.key for row in rows if row.key.lower() in planned.ambiguous]
        return Answer(200, body)

    def save(self, name: str, request: Mapping) -> Answer:
        """Check and keep the week's list and its sentence text. Nothing in a pool changes.

        ``request`` has ``rows``, the list as it is on the page, each naming
        the key it was saved as in ``from`` so its sentence and kept clips
        follow an edit, and ``add``, more words typed or pasted, split by
        ``split_words``.
        """
        found = self._task(name)
        if isinstance(found, Answer):
            return found
        _path, _text, _written, settings = found
        asked, added = request.get("rows", []), request.get("add", "")
        if not isinstance(asked, list) or not all(isinstance(row, Mapping) for row in asked) or not isinstance(added, str):
            return Answer(400, {"error": "Send the list as rows, each with its key and sentence, and the added words as text."})
        old = {row.key.lower(): row for row in self._rows(name)}
        try:
            entries, _problems = spelling.pool_entries(settings, self.tasks.data_root())
        except OSError as error:
            return Answer(400, {"error": str(error)})
        existing = {entry["key"].lower(): entry["key"] for entry in entries}
        errors: list[str] = []
        rows: list[Row] = []
        seen: dict[str, str] = {}

        def take(text: str, where: str) -> str | None:
            key = text.strip().translate(_LOOKALIKES)
            problem = key_problem(key)
            if problem is not None:
                errors.append(f'{where}"{key}": {problem}.')
                return None
            if key.lower() in seen:
                errors.append(f'{where}"{key}": {seen[key.lower()]} is already on the list.')
                return None
            seen[key.lower()] = key
            return existing.get(key.lower(), key)

        for row in asked:
            text, sentence, before = row.get("key"), row.get("sentence", ""), row.get("from")
            if not isinstance(text, str) or not isinstance(sentence, str) or not (before is None or isinstance(before, str)):
                return Answer(400, {"error": "Each row has a key, a sentence, and the key it was saved as."})
            key = take(text, "")
            sentence = " ".join(sentence.split())
            if len(sentence) > LONGEST_SENTENCE:
                errors.append(f"The sentence for {text.strip()} is longer than {LONGEST_SENTENCE} characters.")
            if key is None:
                continue
            carried = old.pop(before.lower(), None) if before else None
            rows.append(Row(key, sentence, dict(carried.clips) if carried else {}))
        for number, text in split_words(added):
            key = take(text, f"Line {number}, ")
            if key is not None:
                rows.append(Row(key))
        errors += _mixed(rows, existing)
        if errors:
            return Answer(400, {"error": REFUSED, "errors": errors})
        dropped = [clip for row in old.values() for clip in row.clips.values()]
        self._store(name, rows)
        for clip in dropped:
            (self.folder(name) / clip).unlink(missing_ok=True)
        count = len(rows)
        message = f"Saved the week's list of {count} word{'' if count == 1 else 's'}." if rows else "The week's list is empty."
        return Answer(200, {"message": message, "warnings": []})

    def keep(self, name: str, request: Mapping) -> Answer:
        """Keep clips from a take as pending recordings of words on the list, replacing older pending ones.

        ``request`` names the take and lists each clip kept with its word and kind.
        """
        found = self._task(name)
        if isinstance(found, Answer):
            return found
        take, kept = request.get("take"), request.get("clips")
        if not isinstance(take, str) or not isinstance(kept, list) or not kept:
            return Answer(400, {"error": "Name the take and each clip kept, with its word and kind."})
        rows = self._rows(name)
        by_key = {row.key.lower(): row for row in rows}
        wanted: list[tuple[Row, str, Path]] = []
        pairs: set[tuple[str, str]] = set()
        clips: set[str] = set()
        for each in kept:
            if not isinstance(each, Mapping):
                return Answer(400, {"error": "Each clip kept names its word, its kind, and the clip."})
            key, kind, clip = each.get("word"), each.get("kind"), each.get("clip")
            if not isinstance(key, str) or kind not in KINDS or not isinstance(clip, str):
                return Answer(400, {"error": "Each clip kept names its word, its kind (word or sentence), and the clip."})
            row = by_key.get(key.lower())
            if row is None:
                return Answer(400, {"error": f"{key} is not on the week's list. Reload the page to see it again."})
            if (row.key.lower(), kind) in pairs or clip in clips:
                return Answer(400, {"error": "Keep each clip once, and one clip of each kind for a word."})
            pairs.add((row.key.lower(), kind))
            clips.add(clip)
            source = self.tasks.recordings.clip(take, clip)
            if source is None:
                return Answer(404, {"error": GONE})
            wanted.append((row, kind, source))
        folder = self.folder(name)
        replaced: list[str] = []
        try:
            make_directory(folder)
            for row, kind, source in wanted:
                target = folder / f"{secrets.token_hex(4)}.opus"
                os.replace(source, target)
                own_like(target, folder.stat())
                if kind in row.clips:
                    replaced.append(row.clips[kind])
                row.clips[kind] = target.name
            self._store(name, rows)
        except OSError as error:
            return Answer(500, {"error": f"The kept clips could not be kept: {error}"})
        for clip in replaced:
            (folder / clip).unlink(missing_ok=True)
        self.tasks.recordings.discard(take)
        count = len(wanted)
        return Answer(
            200,
            {"message": f"Kept {count} clip{'' if count == 1 else 's'} for the new week. They go into the pools on Apply.", "warnings": []},
        )

    def clip(self, name: str, file_name: str) -> Path | None:
        """Return a pending clip of the task's setup, or None."""
        if not _CLIP.fullmatch(file_name) or name not in self.tasks.names():
            return None
        path = self.folder(name) / file_name
        return path if path.is_file() else None

    def cancel(self, name: str) -> Answer:
        found = self._task(name)
        if isinstance(found, Answer):
            return found
        shutil.rmtree(self.folder(name), ignore_errors=True)
        return Answer(200, {"message": "Threw away the new week's setup. The pools have not changed.", "warnings": []})

    def apply(self, name: str, request: Mapping, username: str) -> Answer:
        """Make the week's list the current pool, as one change that is checked first.

        ``request`` may change ``current_required`` and ``revision_required``
        in the same step, naming the version of the policy file it saw.
        """
        found = self._task(name)
        if isinstance(found, Answer):
            return found
        path, text, written, settings = found
        rows = self._rows(name)
        if not rows:
            return Answer(400, {"error": "There are no words on the week's list, so nothing was applied."})
        root = self.tasks.data_root()
        try:
            entries, _problems = spelling.pool_entries(settings, root)
        except OSError as error:
            return Answer(400, {"error": str(error)})
        if len({entry["key"].lower() for entry in entries}) != len(entries):
            return self.tasks._clash()
        planned = plan(rows, entries)
        if planned.ambiguous:
            unclear = ", ".join(row.key for row in rows if row.key.lower() in planned.ambiguous)
            return Answer(400, {"error": f"Choose which meaning of {unclear} belongs to the week, so nothing was applied."})
        if planned.needs:
            return Answer(400, {"error": f"These words still need a word clip, so nothing was applied: {', '.join(planned.needs)}."})
        new_text = text
        targets = request.get("settings")
        if targets is not None:
            if not isinstance(targets, Mapping) or set(targets) - set(TARGETS):
                return Answer(400, {"error": "Only current_required and revision_required can be changed with Apply."})
            try:
                changes = _changes(written, {"settings": dict(targets)})
                if changes:
                    if request.get("version") != _version(text):
                        return Answer(409, {"error": STALE, "stale": True})
                    new_text = rewrite_task(text, path, name, changes)
            except (EditError, ValueError) as error:
                return Answer(400, {"error": str(error)})
        moves, summary = self._moves(name, settings, rows, entries, planned)
        folder = self.folder(name)
        return self.tasks.write(
            name, path, text, new_text, moves, username,
            confirmed=True, moved=summary, failed="The new week could not be applied, and every file was moved back",
            moved_all=lambda: shutil.rmtree(folder, ignore_errors=True),
        )

    # Applying

    def _moves(
        self, name: str, settings: spelling.Settings, rows: list[Row], entries: list[dict], planned: Plan
    ) -> tuple[list[tuple[Path, Path]], str]:
        """Return the renames that apply the week, in an order where no target is taken, and what they do."""
        root = self.tasks.data_root()
        folder = self.folder(name)
        listed = {row.key.lower(): row for row in rows}
        aside: list[tuple[Path, Path]] = []
        between: list[tuple[Path, Path]] = []
        into: list[tuple[Path, Path]] = []
        to_revision = 0
        for entry in entries:
            key, pool = entry["key"], entry["pool"]
            row = listed.get(key.lower())
            if row is not None:
                target_pool = spelling.CURRENT
            elif pool == spelling.CURRENT:
                target_pool = spelling.REVISION
                to_revision += 1
            else:
                target_pool = pool
            new_key = planned.renames.get(key.lower(), key)
            target = root / settings.directory(target_pool)
            for source in spelling.entry_files(settings, pool, key, root):
                parsed = spelling.parse_clip_name(source.name, None)
                kind = spelling.SENTENCE_CLIP if parsed is not None and parsed[2] else spelling.WORD_CLIP
                if row is not None and kind in row.clips:
                    aside.append((source, folder / REPLACED / f"{len(aside)}-{source.name}"))
                elif target_pool != pool or new_key != key:
                    between.append((source, target / (new_key + source.name[len(key):])))
        current = root / settings.directory(spelling.CURRENT)
        for row in rows:
            final = planned.renames.get(row.key.lower(), row.key)
            for kind in KINDS:
                if kind in row.clips:
                    suffix = "" if kind == spelling.WORD_CLIP else ".sentence"
                    into.append((folder / row.clips[kind], current / f"{final}{suffix}.opus"))
        count = len(rows)
        parts = [
            f"Applied the new week: {count} word{' is' if count == 1 else 's are'} current, "
            f"and {to_revision} went to revision."
        ]
        parts += [f"The existing {old_key} is now {new_key}." for old_key, new_key in _renamed(entries, planned)]
        return aside + between + into, " ".join(parts)

    # Reading and writing the setup

    def _task(self, name: str) -> tuple[Path, str, object, spelling.Settings] | Answer:
        found = self.tasks._read(name)
        if isinstance(found, Answer):
            return found
        path, text, written = found
        if written.fields.get("type") != spelling.SPELLING:
            return Answer(400, {"error": f"{name} is not a spelling task, so it has no week's words."})
        try:
            settings = _settings(written)
        except ValueError as error:
            return Answer(400, {"error": str(error)})
        return path, text, written, settings

    def _rows(self, name: str) -> list[Row]:
        try:
            stored = json.loads((self.folder(name) / STATE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        rows = []
        for each in stored.get("words", []) if isinstance(stored, dict) else []:
            try:
                clips = {kind: clip for kind, clip in each.get("clips", {}).items() if kind in KINDS and _CLIP.fullmatch(clip)}
                rows.append(Row(str(each["key"]), str(each.get("sentence", "")), clips))
            except (AttributeError, KeyError, TypeError):
                continue
        return rows

    def _store(self, name: str, rows: list[Row]) -> None:
        """Keep the list in one step. An empty list, with no clips kept, is no setup at all."""
        folder = self.folder(name)
        if not rows:
            shutil.rmtree(folder, ignore_errors=True)
            return
        make_directory(folder)
        temporary = folder / f".{STATE}.{os.getpid()}.part"
        try:
            temporary.write_text(json.dumps({"words": [row.record() for row in rows]}, indent=2) + "\n", encoding="utf-8")
            own_like(temporary, folder.stat())
            os.replace(temporary, folder / STATE)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise


def _mixed(rows: list[Row], existing: Mapping[str, str]) -> list[str]:
    """Refuse a new plain word listed beside a numbered meaning of it, such as read and read.1."""
    numbered = {split_key(row.key)[0].lower(): row.key for row in rows if split_key(row.key)[1] is not None}
    return [
        f"{row.key} and {numbered[row.key.lower()]} are both on the list. Give {row.key} a number too."
        for row in rows
        if split_key(row.key)[1] is None and row.key.lower() in numbered and row.key.lower() not in existing
    ]


def _renamed(entries: list[dict], planned: Plan) -> list[tuple[str, str]]:
    return [(entry["key"], planned.renames[entry["key"].lower()]) for entry in entries if entry["key"].lower() in planned.renames]
