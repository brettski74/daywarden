"""The parent portal's task pages: read a task, save changes to it, and move its spelling words.

A task page shows how the policy file writes the task, and the spelling
words in the data directory. A save rewrites only that task, in whichever
file defines it, with ``policy.task_edit``. Before anything is written, the
whole policy is checked with the changed file and with the words already in
their new pools, exactly as ``dw check`` would load it. A policy that would
not load is refused, and nothing changes.

A save that is checked is then made in this order: hand edits found in the
config directory are committed as their own version, the words move, the
file is written, every service reloads it as ``dw reload`` would, and the
file is committed in the config history as the signed-in parent.

Retire moves a word's recordings into the attic at once. Nothing is ever
deleted, except that a kept recording replaces the word's old clip of that
kind. Moving a word, retiring one, or keeping a recording changes only the
data directory, so none of them reloads the policy or commits anything.

The decisions service runs as root in its container. Every file and
directory it writes keeps the owner of what it replaces, or takes the owner
of the directory it is made in, so the host user can still edit, move, and
commit them without sudo.
"""

from __future__ import annotations

import errno
import hashlib
import os
import shutil
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from policy import clips, spelling
from policy.check import load_required
from policy.hierarchy import ConfigError, Policy, task_files
from policy.history import History, HistoryError, stamp
from policy.owned import make_directory, own_like
from policy.recordings import GONE, Recordings
from policy.task_edit import EditError, WrittenTask, name_list, read_task, rewrite_task, scalar
from policy.tasks import PARENT_CHECK, AttemptStore, stored_passes

COMMON_FIELDS = ("pass_cooldown", "failure_cooldown", "max_skips", "max_passes", "available_from", "due_date")
# A parent check is never required, so these do not apply to it.
NOT_FOR_PARENT_CHECK = frozenset({"available_from", "due_date", "max_skips", "max_passes"})
SPELLING_SETTINGS = (
    "timeout",
    "maximum_replays",
    "maximum_sentence_plays",
    "current_required",
    "revision_required",
    "letter_pause",
    "word_pause",
)
SPELLING_DIRECTORIES = ("current_dir", "revision_dir", "attic_dir", "alphabet_dir")
STALE = (
    "The policy file has changed on the server since this page was opened. "
    "Reload the page and make the change again."
)
BROKEN = "This save would leave the policy unable to load, so nothing was saved."
HAND_EDITS_BROKEN = (
    "The hand edits on the server do not pass dw check, so nothing was saved. "
    "Fix the files on the server, then save again."
)


@dataclass(frozen=True)
class Answer:
    """What the portal sends back: a status and a JSON body."""

    status: int
    body: dict


@dataclass
class Reloads:
    """How a save applies the policy: the decisions service in this process, then the others by socket."""

    decisions: Callable[[], dict]
    others: Mapping[str, Callable[[], dict]] = field(default_factory=dict)


class TaskAdmin:
    def __init__(
        self,
        policy_file: Path,
        *,
        policy: Callable[[], Policy | None],
        now: Callable[[], datetime],
        attempts: AttemptStore,
        reloads: Reloads,
        clients: Callable[[], Sequence[str]],
        data_root: Callable[[], Path] = spelling.data_root,
        recordings: Recordings | None = None,
    ) -> None:
        self.policy_file = policy_file
        self.policy = policy
        self.now = now
        self.attempts = attempts
        self.reloads = reloads
        self.clients = clients
        self.data_root = data_root
        self.recordings = recordings if recordings is not None else Recordings(data_root)

    @property
    def history(self) -> History:
        return History(self.policy_file.parent)

    def names(self) -> list[str]:
        """Return every task the policy files define, in name order."""
        return sorted(self._files())

    def page(self, name: str) -> Answer:
        found = self._read(name)
        if isinstance(found, Answer):
            return found
        path, text, written = found
        kind = written.fields.get("type", "")
        fields = {key: written.fields.get(key, "") for key in COMMON_FIELDS}
        if kind == PARENT_CHECK:
            fields = {key: value for key, value in fields.items() if key not in NOT_FOR_PARENT_CHECK}
        clients = list(self.clients())
        clients += [group for group in written.groups if group not in clients]
        body = {
            "name": name,
            "type": kind,
            "file": str(path),
            "version": _version(text),
            "groups": list(written.groups),
            "clients": clients,
            "fields": fields,
        }
        if kind == spelling.SPELLING:
            body["spelling"] = self._spelling_page(written)
        return Answer(200, body)

    def save(self, name: str, request: Mapping, username: str) -> Answer:
        found = self._read(name)
        if isinstance(found, Answer):
            return found
        path, text, written = found
        if request.get("version") != _version(text):
            return Answer(409, {"error": STALE, "stale": True})
        try:
            changes = _changes(written, request)
            settings = _settings(written)
            moves, moved = self._moves(settings, request.get("moves") or {})
            new_text = rewrite_task(text, path, name, changes) if changes else text
        except _Clash:
            return self._clash()
        except (EditError, ValueError) as error:
            return Answer(400, {"error": str(error)})
        if new_text == text and not moves:
            return Answer(200, {"message": "Nothing has changed, so nothing was saved.", "warnings": []})
        return self.write(
            name, path, text, new_text, moves, username,
            confirmed=bool(request.get("confirmed")), moved=_moved_words(moved) if moved else None,
        )

    def write(
        self,
        name: str,
        path: Path,
        text: str,
        new_text: str,
        moves: list[tuple[Path, Path]],
        username: str,
        *,
        confirmed: bool,
        moved: str | None,
        failed: str = "The words could not be moved, so nothing was saved",
        moved_all: Callable[[], None] | None = None,
    ) -> Answer:
        """Check and make a save: the task's new text and the planned file moves, as one change.

        Hand edits in the config directory are checked and committed first.
        The whole policy is loaded with the new text and the files already
        moved, and refused when it would not load. Then the files move, the
        text is written, every service reloads, and the save is committed.
        When a move or the write fails, the moves already made are reversed.
        ``moved_all`` runs once every file has moved and the text is written.
        """
        history = self.history
        try:
            hand = history.changed() if history.kept else []
        except HistoryError as error:
            print(f"task {name}: the config history could not be read: {error}", flush=True)
            hand = []
        if hand:
            problems = self._problems()
            if problems:
                return Answer(400, {"error": HAND_EDITS_BROKEN, "errors": problems})
        refused = self._check(moves, {path: new_text})
        if refused is not None:
            return refused
        checked = self._checked
        task = None if checked is None else checked.task(name)
        if task is not None and task.due_date is not None and not confirmed:
            passed = [group for group in task.groups if stored_passes(name, group, self.attempts.history(group))]
            if passed:
                return Answer(409, {"confirm": _due_warning(name, passed), "groups": passed})
        warnings: list[str] = []
        when = self.now()
        if hand:
            self._commit(f"{stamp(when)} hand edits found before a portal save", username, when, None, warnings)
        try:
            done = move_files(moves)
        except OSError as error:
            return Answer(500, {"error": f"{failed}: {error}"})
        if new_text != text:
            try:
                replace_text(path, new_text)
            except OSError as error:
                undo_moves(done)
                return Answer(500, {"error": f"{path} could not be written, so nothing was saved: {error}"})
        if moved_all is not None:
            moved_all()
        parts = []
        if new_text != text or hand:
            applied = self._reload(warnings)
            if applied is not None:
                return applied
            parts.append(f"Saved {name}. The decisions, observations, and autoconfig services are using it.")
        if moved:
            parts.append(moved)
        if new_text != text:
            relative = _within(path, self.policy_file.parent)
            if relative is not None and history.kept:
                self._commit(f"{stamp(when)} {username}: saved task {name}", username, when, [relative], warnings)
        return Answer(200, {"message": " ".join(parts), "warnings": warnings})

    def retire(self, name: str, key: object) -> Answer:
        found = self._read(name)
        if isinstance(found, Answer):
            return found
        _path, _text, written = found
        if not isinstance(key, str) or not key:
            return Answer(400, {"error": "Name the word to retire."})
        try:
            settings = _settings(written)
            moves, moved = self._moves(settings, {key: spelling.ATTIC}, retiring=True)
        except _Clash:
            return self._clash()
        except ValueError as error:
            return Answer(400, {"error": str(error)})
        if not moves:
            return Answer(400, {"error": f"{key} is already in the attic."})
        refused = self._check(moves, {})
        if refused is not None:
            return refused
        try:
            move_files(moves)
        except OSError as error:
            return Answer(500, {"error": f"{key} could not be retired: {error}"})
        return Answer(200, {"message": f"Retired {moved[0][0]}. Its recordings are in the attic.", "warnings": []})

    def keep(self, name: str, request: Mapping) -> Answer:
        """Write the kept clips of a take as a word's new recordings, in the word's own pool directory.

        ``request`` names the take, the word's entry key, and the clip kept for
        each kind, ``word`` and ``sentence``. Each replaces the word's old clip
        of that kind, whatever its format. The take is thrown away afterwards.
        """
        found = self._read(name)
        if isinstance(found, Answer):
            return found
        written = found[2]
        if written.fields.get("type") != spelling.SPELLING:
            return Answer(400, {"error": f"{name} is not a spelling task, so it has no recordings."})
        take, key, kept = request.get("take"), request.get("word"), request.get("clips")
        if not isinstance(take, str) or not isinstance(key, str) or not isinstance(kept, Mapping):
            return Answer(400, {"error": "Name the take, the word, and the clip kept for each kind."})
        unknown = set(kept) - {spelling.WORD_CLIP, spelling.SENTENCE_CLIP}
        if unknown or not kept or len(set(map(str, kept.values()))) != len(kept):
            return Answer(400, {"error": "Keep a word clip, a sentence clip, or both, each a different clip."})
        sources = {kind: self.recordings.clip(take, clip) if isinstance(clip, str) else None for kind, clip in kept.items()}
        if any(source is None for source in sources.values()):
            return Answer(404, {"error": GONE})
        try:
            settings = _settings(written)
            entries, _problems = spelling.pool_entries(settings, self.data_root())
        except (ValueError, OSError) as error:
            return Answer(400, {"error": str(error)})
        pools = [entry["pool"] for entry in entries if entry["key"].lower() == key.lower()]
        if len(pools) > 1:
            return self._clash()
        if not pools:
            return Answer(400, {"error": f"There is no word {key} in this task's pools. Reload the page to see them again."})
        entry = next(entry for entry in entries if entry["key"].lower() == key.lower())
        directory = self.data_root() / settings.directory(pools[0])
        try:
            for kind in (spelling.WORD_CLIP, spelling.SENTENCE_CLIP):
                if kind in sources:
                    place_clip(sources[kind], directory, entry["key"] + ("" if kind == spelling.WORD_CLIP else ".sentence"))
        except OSError as error:
            return Answer(500, {"error": f"The recording of {entry['key']} could not be written: {error}"})
        self.recordings.discard(take)
        what = " and ".join(kind for kind in (spelling.WORD_CLIP, spelling.SENTENCE_CLIP) if kind in sources)
        return Answer(200, {"message": f"Saved the new {what} recording{'s' if len(sources) > 1 else ''} of {entry['key']}.", "warnings": []})

    def audio(self, name: str, pool: str, file_name: str) -> Path | None:
        """Return a recording in one of a spelling task's pools, or None."""
        found = self._read(name)
        if isinstance(found, Answer) or found[2].fields.get("type") != spelling.SPELLING:
            return None
        if pool not in spelling.ALL_POOLS or "/" in file_name or file_name.startswith("."):
            return None
        try:
            settings = _settings(found[2])
        except ValueError:
            return None
        candidate = self.data_root() / settings.directory(pool) / file_name
        return candidate if candidate.is_file() else None

    # Reading

    def _files(self) -> dict[str, Path]:
        try:
            return task_files(self.policy_file)
        except ConfigError:
            return {}

    def _read(self, name: str) -> tuple[Path, str, WrittenTask] | Answer:
        path = self._files().get(name)
        if path is None:
            return Answer(404, {"error": f"There is no task named {name}."})
        try:
            text = path.read_bytes().decode("utf-8")
            return path, text, read_task(text, path, name)
        except (OSError, UnicodeDecodeError, EditError) as error:
            return Answer(400, {"error": str(error)})

    def _spelling_page(self, written: WrittenTask) -> dict:
        directories = {key: written.body.get(key, spelling._DIRECTORIES[key]) for key in SPELLING_DIRECTORIES}
        page = {
            "settings": {key: written.body.get(key, "") for key in SPELLING_SETTINGS},
            "directories": directories,
            "words": [],
            "problems": [],
        }
        try:
            entries, problems = spelling.pool_entries(_settings(written), self.data_root())
        except (ValueError, OSError) as error:
            page["problems"] = [str(error)]
            return page
        page["words"] = entries
        page["problems"] = problems
        return page

    # Checking

    def _problems(self, overrides: Mapping[Path, str] | None = None) -> list[str]:
        """Return why the policy on disk, with any overrides and the planned moves, would not load."""
        self._checked = None
        try:
            self._checked = load_required(
                self.policy_file, self.policy(), warn=lambda _message: None, overrides=overrides or {}
            )
        except ConfigError as error:
            return list(error.problems)
        return []

    def _check(self, moves: list[tuple[Path, Path]], overrides: Mapping[Path, str]) -> Answer | None:
        """Refuse a save or a retire that would leave the policy unable to load.

        A target is free when it is missing, or when an earlier move in the
        same plan takes the file there away.
        """
        cleared: set[Path] = set()
        taken = None
        for source, target in moves:
            if taken is None and target.exists() and target not in cleared:
                taken = target
            cleared.add(source)
        if taken is not None:
            problems = self._problems()
            problems = problems or [f"{taken} is already there, and a recording is never replaced."]
            return Answer(400, {"error": BROKEN, "errors": problems})
        with spelling.planned_moves(moves):
            problems = self._problems(overrides)
        if problems:
            return Answer(400, {"error": BROKEN, "errors": problems})
        return None

    _checked: Policy | None = None

    def _clash(self) -> Answer:
        problems = self._problems() or ["A word is in more than one pool. A word belongs to one pool."]
        return Answer(400, {"error": BROKEN, "errors": problems})

    def _moves(
        self, settings: spelling.Settings, wanted: object, *, retiring: bool = False
    ) -> tuple[list[tuple[Path, Path]], list[tuple[str, str]]]:
        """Return the files to move for each word whose pool changes, and each word's key and new pool.

        Only Retire moves a word into the attic, so that it always asks first.
        """
        if not isinstance(wanted, Mapping):
            raise ValueError("moves must map each word to its new pool")
        root = self.data_root()
        entries, _problems = spelling.pool_entries(settings, root)
        pools: dict[str, str] = {}
        for entry in entries:
            if entry["key"] in pools:
                raise _Clash()
            pools[entry["key"]] = entry["pool"]
        moves: list[tuple[Path, Path]] = []
        moved: list[tuple[str, str]] = []
        for key, pool in wanted.items():
            if pool not in spelling.ALL_POOLS:
                raise ValueError(f"{pool!r} is not a pool. The pools are current, revision, and attic.")
            if key not in pools:
                raise ValueError(f"There is no word {key} in this task's pools. Reload the page to see them again.")
            if pools[key] == pool:
                continue
            if pool == spelling.ATTIC and not retiring:
                raise ValueError(f"{key} can only go to the attic with Retire, which asks first. Nothing was saved.")
            target = root / settings.directory(pool)
            for source in spelling.entry_files(settings, pools[key], key, root):
                moves.append((source, target / source.name))
            moved.append((key, pool))
        return moves, moved

    # Applying

    def _reload(self, warnings: list[str]) -> Answer | None:
        answer = self.reloads.decisions()
        if not answer.get("reloaded"):
            return Answer(
                500,
                {
                    "error": "The file was saved, but the decisions service did not reload it, and keeps the policy it had.",
                    "errors": list(answer.get("errors", [])),
                },
            )
        warnings += answer.get("warnings", [])
        for service, ask in self.reloads.others.items():
            try:
                other = ask()
            except (OSError, ValueError) as error:
                other = {"reloaded": False, "errors": [str(error)]}
            if not other.get("reloaded"):
                reason = "; ".join(other.get("errors", [])) or "no reason given"
                warnings.append(f"The {service} service did not reload and keeps the policy it had: {reason}")
                print(f"{service} did not reload after a portal save: {reason}", flush=True)
        return None

    def _commit(self, message: str, username: str, when: datetime, paths: list[str] | None, warnings: list[str]) -> None:
        try:
            self.history.commit(message, username, when, paths)
        except HistoryError as error:
            print(f"the portal save is not in the config history: {error}", flush=True)
            warnings.append(f"This change is not in the config history, because git could not commit it: {error}")


class _Clash(Exception):
    """A word is in more than one of the task's pools on disk."""


def _version(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _changes(written: WrittenTask, request: Mapping) -> dict[str, object]:
    """Return the fields whose text differs from the file, as ``rewrite_task`` changes."""
    changes: dict[str, object] = {}
    allowed = COMMON_FIELDS
    if written.fields.get("type") == PARENT_CHECK:
        allowed = tuple(key for key in COMMON_FIELDS if key not in NOT_FOR_PARENT_CHECK)
    _diff(changes, written.fields, request.get("fields"), allowed)
    groups = request.get("groups")
    if groups is not None:
        if not isinstance(groups, list) or not all(isinstance(group, str) and group.strip() for group in groups):
            raise ValueError("groups must be a list of client group names")
        groups = [group.strip() for group in groups]
        if tuple(groups) != written.groups:
            if written.group_key == "group" and len(groups) == 1:
                changes["group"] = scalar(groups[0], name=True)
            else:
                changes["group"] = None
                changes["groups"] = name_list(groups)
    if written.fields.get("type") == spelling.SPELLING:
        body: dict[str, object] = {}
        _diff(body, written.body, request.get("settings"), SPELLING_SETTINGS)
        if body:
            changes["body"] = body
    return changes


def _diff(changes: dict[str, object], written: Mapping[str, str], asked: object, allowed: Sequence[str]) -> None:
    if asked is None:
        return
    if not isinstance(asked, Mapping):
        raise ValueError("fields must map each field to its text")
    for key, value in asked.items():
        if key not in allowed:
            raise ValueError(f"{key} cannot be changed from the parent pages")
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{key} must be sent as text")
        text = (value or "").strip()
        if text == written.get(key, "").strip():
            continue
        changes[key] = scalar(text) if text else None


def _settings(written: WrittenTask) -> spelling.Settings:
    """Return the spelling directories the file sets, with the defaults for the rest."""
    return spelling.parse_settings({key: written.body[key] for key in SPELLING_DIRECTORIES if key in written.body})


def _due_warning(name: str, groups: list[str]) -> str:
    named = groups[0] if len(groups) == 1 else ", ".join(groups[:-1]) + f" and {groups[-1]}"
    return (
        f"{named} already {'has' if len(groups) == 1 else 'have'} a pass for {name}. "
        f"Saving does not ask {'it' if len(groups) == 1 else 'them'} to do the task again."
    )


def _moved_words(moved: list[tuple[str, str]]) -> str:
    if len(moved) == 1:
        key, pool = moved[0]
        return f"Moved {key} to {pool}."
    return f"Moved {len(moved)} words."


def _within(path: Path, directory: Path) -> str | None:
    try:
        return str(path.resolve().relative_to(directory.resolve()))
    except ValueError:
        return None


# Files


def replace_text(path: Path, text: str) -> None:
    """Replace a file's text in one step, keeping its owner and mode."""
    status = path.stat()
    temporary = path.with_name(f".{path.name}.{os.getpid()}.saving")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, stat.S_IMODE(status.st_mode))
        own_like(temporary, status)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def move_files(moves: Sequence[tuple[Path, Path]]) -> list[tuple[Path, Path]]:
    """Rename each file into its new directory, never over another. If one fails, the ones before it move back."""
    done: list[tuple[Path, Path]] = []
    try:
        for source, target in moves:
            make_directory(target.parent)
            if target.exists():
                raise FileExistsError(f"{target} is already there")
            os.rename(source, target)
            done.append((source, target))
    except OSError:
        undo_moves(done)
        raise
    return done


def place_clip(source: Path, directory: Path, name: str) -> Path:
    """Rename a pending clip into place as ``<name>.opus``, then remove the entry's older clips of that kind.

    The new clip takes the owner of the clip it replaces, or of the directory.
    Where the pending clip is on another file system, it is copied to a hidden
    file beside its target first, so a scan never sees half a clip.
    """
    make_directory(directory)
    old = clips.existing_clips(directory, name)
    target = directory / (name + clips.EXTENSION)
    owner = (old[0] if old else directory).stat()
    try:
        os.replace(source, target)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        temporary = directory / f".{target.name}.{os.getpid()}.part"
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        source.unlink()
    own_like(target, owner)
    for path in old:
        if path.exists() and not path.samefile(target):
            path.unlink()
    return target


def undo_moves(done: Sequence[tuple[Path, Path]]) -> None:
    for source, target in reversed(done):
        try:
            os.rename(target, source)
        except OSError as error:
            print(f"could not move {target} back to {source}: {error}", flush=True)
