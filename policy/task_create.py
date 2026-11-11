"""Creating a task and renaming one from the parent portal.

A new task's page starts with only its name and type. Locking them in checks
the name and writes nothing, and returns the page a task with an empty body
would have. The next save writes the task to its own new file in ``tasks.d``
beside the root policy file, named by ``policy.task_names``. The directory is
made when it is missing, and added to the root file's ``include`` list when
the root file does not include it.

A rename changes only the task's key in its file. A task alone in a file in
``tasks.d`` also has its file renamed to the new name's file name. Its stored
attempts, and a spelling task's new week's setup, move to the new name in
the same change. Each step is taken back when a later one fails.
"""

from __future__ import annotations

import os
import shlex
from collections.abc import Mapping
from pathlib import Path

from policy.arithmetic import ARITHMETIC
from policy.owned import make_directory, own_like
from policy.parts_of_speech import PARTS_OF_SPEECH
from policy.skip_counting import SKIP_COUNTING
from policy.spelling import SPELLING
from policy.task_admin import (
    COMMON_FIELDS,
    STALE,
    Answer,
    Step,
    TaskAdmin,
    _changes,
    _Clash,
    _moved_words,
    _version,
    replace_text,
)
from policy.task_edit import EditError, WrittenTask, add_include, included, new_task_text, rename_task
from policy.task_names import free_file, name_problem
from policy.tasks import TaskKey
from policy.week import Weeks

TASKS_DIR = "tasks.d"
# A parent check is only how a parent records credit for work done outside daywarden, so it is never made here.
NEW_TYPES = (ARITHMETIC, PARTS_OF_SPEECH, SKIP_COUNTING, SPELLING)
CHOOSE_TYPE = "Choose the task's type."
_EMPTY = WrittenTask({}, (), {})
_WRITTEN_ORDER = ("group", "groups", *COMMON_FIELDS, "body")


class TaskChanges:
    def __init__(self, tasks: TaskAdmin, weeks: Weeks) -> None:
        self.tasks = tasks
        self.weeks = weeks

    @property
    def directory(self) -> Path:
        return self.tasks.policy_file.parent / TASKS_DIR

    # Creating

    def blank(self) -> dict:
        """Return what a new task's page needs before its name and type are locked in."""
        return {
            "types": list(NEW_TYPES),
            "clients": list(self.tasks.clients()),
            "fields": dict.fromkeys(COMMON_FIELDS, ""),
            "today": self.tasks.today().isoformat(),
        }

    def lock(self, request: Mapping) -> Answer:
        """Check a new task's name and type, and return its page with an empty body. Nothing is written."""
        key = _new_key(request)
        if isinstance(key, Answer):
            return key
        refused = self.taken(key)
        if refused is not None:
            return Answer(400, {"error": refused})
        return Answer(200, self.tasks.page_body(key, free_file(self.directory, key.name), "", _EMPTY))

    def create(self, request: Mapping, username: str) -> Answer:
        """Write a new task to its own file in ``tasks.d``, checked and applied as a task page's save is."""
        key = _new_key(request)
        if isinstance(key, Answer):
            return key
        refused = self.taken(key)
        if refused is not None:
            return Answer(400, {"error": refused})
        listed = None
        try:
            changes = _changes(key.type, _EMPTY, request)
            moves, moved = [], []
            if key.type == SPELLING:
                settings, listed = self.tasks.chosen_settings(key.type, _EMPTY, request.get("directories"))
                moves, moved = self.tasks._moves(settings, request.get("moves") or {})
        except _Clash:
            return self.tasks.with_words(self.tasks._clash(), listed)
        except (EditError, ValueError) as error:
            return Answer(400, {"error": str(error)})
        text = new_task_text(key, {field: changes[field] for field in _WRITTEN_ORDER if field in changes})
        directory = self.directory
        path = free_file(directory, key.name)
        root = self.tasks.policy_file
        try:
            root_text = root.read_bytes().decode("utf-8")
            adds_include = not self._includes(root_text)
            new_root = add_include(root_text, root, TASKS_DIR) if adds_include else root_text
        except (OSError, UnicodeDecodeError, EditError) as error:
            return Answer(400, {"error": str(error)})
        overrides = {directory.resolve() / path.name: text, root.resolve(): new_root}
        steps = []
        if not directory.is_dir():
            steps.append(Step(lambda: make_directory(directory), directory.rmdir, f"{directory} could not be made, so nothing was saved"))
        steps.append(Step(lambda: create_text(path, text), lambda: path.unlink(missing_ok=True), f"{path} could not be written, so nothing was saved"))
        if adds_include:
            steps.append(
                Step(lambda: replace_text(root, new_root), lambda: replace_text(root, root_text), f"{root} could not be written, so nothing was saved")
            )
        answer = self.tasks.change(
            key, overrides, moves, steps, username,
            confirmed=True, moved=_moved_words(moved) if moved else None, failed="The words could not be moved, so nothing was saved",
            done=f"Created {key.name} in {path}.", commit=f"created task {key}", paths=[path, root] if adds_include else [path],
        )
        if answer.status == 200:
            answer.body["task"] = {"type": key.type, "name": key.name}
        return self.tasks.with_words(answer, listed)

    def _includes(self, root_text: str) -> bool:
        base = self.tasks.policy_file.parent
        wanted = self.directory.resolve()
        return any((base / raw).resolve() == wanted for raw in included(root_text, self.tasks.policy_file))

    # Renaming

    def rename(self, key: TaskKey, request: Mapping, username: str) -> Answer:
        """Rename a task in its file, with its file in ``tasks.d``, its attempts, and its new week's setup."""
        found = self.tasks._read(key)
        if isinstance(found, Answer):
            return found
        path, text, _written = found
        if request.get("version") != _version(text):
            return Answer(409, {"error": STALE, "stale": True})
        name = request.get("name")
        if not isinstance(name, str):
            return Answer(400, {"error": "Send the task's new name."})
        problem = name_problem(name)
        if problem is not None:
            return Answer(400, {"error": problem})
        if name == key.name:
            return Answer(200, {"message": "The name has not changed, so nothing was saved.", "warnings": [], "task": key._asdict()})
        new = TaskKey(key.type, name)
        refused = self.taken(new, own=key)
        if refused is not None:
            return Answer(400, {"error": refused})
        try:
            new_text = rename_task(text, path, key, name)
        except EditError as error:
            return Answer(400, {"error": str(error)})
        target = path
        if path.parent == self.directory.resolve() and list(self.tasks._files().values()).count(path) == 1:
            target = free_file(path.parent, name, own=path)
        steps = [
            Step(lambda: replace_text(path, new_text), lambda: replace_text(path, text), f"{path} could not be written, so nothing was renamed")
        ]
        if target != path:
            steps.append(Step(lambda: rename_file(path, target), lambda: rename_file(target, path), f"{path} could not be renamed, so nothing was renamed"))
        if key.type == SPELLING and self.weeks.folder(key.name).exists():
            setup, moved_to = self.weeks.folder(key.name), self.weeks.folder(name)
            steps.append(
                Step(
                    lambda: rename_file(setup, moved_to),
                    lambda: rename_file(moved_to, setup),
                    "The new week's setup could not be moved, so nothing was renamed",
                )
            )
        steps.append(
            Step(
                lambda: self.tasks.attempts.rename(key, new),
                lambda: self.tasks.attempts.rename(new, key),
                "The stored attempts could not be moved, so nothing was renamed",
            )
        )
        answer = self.tasks.change(
            new, {path: new_text}, [], steps, username,
            confirmed=True, moved=None, failed="", done=f"Renamed {key.name} to {name}.",
            commit=f"renamed task {key} to {new}", paths=[path, target] if target != path else [path],
        )
        if answer.status == 200:
            answer.body["task"] = new._asdict()
        return answer

    # Names

    def taken(self, key: TaskKey, own: TaskKey | None = None) -> str | None:
        """Return why a name cannot be used for a task of this type, or None. Case is ignored."""
        folded = key.name.casefold()
        for other in sorted(self.tasks.keys()):
            if other.type == key.type and other.name.casefold() == folded and other != own:
                article = "An" if key.type[:1] in "aeiou" else "A"
                return f"{article} {key.type} task named {other.name} already exists."
        for stored in sorted(self.tasks.attempts.names(key.type)):
            if stored.casefold() == folded and (own is None or stored != own.name):
                return (
                    f"Attempts are still stored under {TaskKey(key.type, stored)}, from a task no longer in the policy. "
                    "Choose another name, or remove them with "
                    f"`bin/rm-attempts --task {shlex.quote(stored)} --type {key.type}`."
                )
        return None


def _new_key(request: Mapping) -> TaskKey | Answer:
    kind, name = request.get("type"), request.get("name")
    if kind not in NEW_TYPES:
        return Answer(400, {"error": CHOOSE_TYPE})
    if not isinstance(name, str):
        return Answer(400, {"error": "Send the task's name."})
    problem = name_problem(name)
    if problem is not None:
        return Answer(400, {"error": problem})
    return TaskKey(kind, name)


def create_text(path: Path, text: str) -> None:
    """Write a new file in one step, owned like its directory. A file already there is never replaced."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.saving")
    try:
        with temporary.open("x", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        own_like(temporary, path.parent.stat())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def rename_file(source: Path, target: Path) -> None:
    """Rename a file or a directory, never over anything already there."""
    if target.exists():
        raise FileExistsError(f"{target} is already there")
    os.rename(source, target)
