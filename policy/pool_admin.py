"""Asset Administration's parts of speech pool pages: list, create, edit, rename, and delete a pool.

A pool is one file in ``parts_of_speech_pools/`` beside the root policy file
(S031.1). Its file name is a stable id, which is the pool page's address. Its
``name`` is what the parent sees and what tasks list under ``body.pools``.

Every change is checked and applied as a task page's save is, through
``TaskAdmin.change``: hand edits in the config directory are checked and
committed first, the whole policy is loaded with the changed files in place,
then the files are written, every service reloads, and the change is
committed in the config history as the signed-in parent. A pool that no task
names is not part of the policy load, so a save also checks the pool itself
as the load would.

Rename rewrites the pool's ``name`` and every ``parts_of_speech`` task that
lists it, in one change, so tasks keep using the pool. Delete is refused while
any task lists the pool.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from pathlib import Path

import yaml

from policy import sentence_pools
from policy.owned import make_directory, own_like
from policy.parts_of_speech import PARTS_OF_SPEECH, check_pool_sentence
from policy.parts_of_speech_admin import LEVEL, level, sentences_edit, shown_level, shown_sentences
from policy.task_admin import BROKEN, STALE, Answer, Step, TaskAdmin, replace_text
from policy.problems import problems_of
from policy.task_edit import EditError, add_root_entry_after, name_list, read_task, rewrite_root, rewrite_task, text_value
from policy.tasks import TaskKey

LONGEST_NAME = 60
NO_SENTENCES = "There are no sentences. Add at least one."
# The key a pool's change is logged under. No task has this type, so a change never asks about a due date.
_KIND = "parts_of_speech_pool"
_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def name_problem(name: str) -> str | None:
    """Return why a pool name cannot be used, before it is compared with the other pools, or None."""
    if not name.strip():
        return "Give the pool a name."
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in name):
        return "A pool name is one line of text."
    if len(name.strip()) > LONGEST_NAME:
        return f"A pool name is at most {LONGEST_NAME} characters."
    return None


def _version(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _missing(pool_id: str) -> Answer:
    return Answer(404, {"error": f"There is no parts of speech pool {pool_id}."})


class PoolAdmin:
    def __init__(self, tasks: TaskAdmin) -> None:
        self.tasks = tasks

    @property
    def directory(self) -> Path:
        return sentence_pools.pools_directory(self.tasks.policy_file.parent)

    # Reading

    def catalogue(self) -> dict:
        """Return every pool file, by name ignoring case: its id, name, level of difficulty, and how many sentences."""
        pools = []
        for path in sentence_pools.list_pool_files(self.tasks.policy_file.parent):
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
        return {"pools": pools}

    def page(self, pool_id: str) -> Answer:
        found = self._read(pool_id)
        if isinstance(found, Answer):
            return found
        path, text, data = found
        sentences, problems = shown_sentences(data.get("sentences"))
        return Answer(
            200,
            {
                "id": pool_id,
                "name": _name(data, path),
                "file": str(path),
                "version": _version(text),
                LEVEL: shown_level(data.get(LEVEL)),
                "sentences": sentences,
                "problems": problems,
                "tasks": [key.name for key in self._users(_name(data, path))],
            },
        )

    # Changing

    def create(self, request: Mapping, username: str) -> Answer:
        """Write a new, empty pool at the default level of difficulty, and return its id."""
        name = request.get("name")
        if not isinstance(name, str):
            return Answer(400, {"error": "Send the pool's name."})
        name = name.strip()
        refused = name_problem(name) or self._taken(name)
        if refused is not None:
            return Answer(400, {"error": refused})
        directory = self.directory
        pool_id = sentence_pools.pool_id(name, directory)
        path = directory / f"{pool_id}.yaml"
        text = f"name: {text_value(name)}\nsentences: []\n"
        steps = [Step(lambda: _write_new(path, text), lambda: path.unlink(missing_ok=True), f"{path} could not be written, so no pool was made")]
        answer = self.tasks.change(
            TaskKey(_KIND, pool_id), {path.resolve(): text}, [], steps, username,
            confirmed=True, moved=None, failed="", done=f"Made the pool {name}.",
            commit=f"made parts of speech pool {name}", paths=[path],
        )
        if answer.status == 200:
            answer.body["pool"] = {"id": pool_id, "name": name}
        return answer

    def save(self, pool_id: str, request: Mapping, username: str) -> Answer:
        found = self._read(pool_id)
        if isinstance(found, Answer):
            return found
        path, text, data = found
        if request.get("version") != _version(text):
            return Answer(409, {"error": STALE, "stale": True})
        name = _name(data, path)
        try:
            changes = _changes(data, request)
            added = changes.pop(LEVEL) if LEVEL not in data and changes.get(LEVEL) is not None else None
            new_text = rewrite_root(text, path, changes) if changes else text
            if added is not None:
                new_text = add_root_entry_after(new_text, path, "name", LEVEL, str(added))
        except (EditError, ValueError) as error:
            return Answer(400, {"error": str(error)})
        if new_text == text:
            return Answer(200, {"message": "Nothing has changed, so nothing was saved.", "warnings": []})
        problems = check_pool(path, new_text)
        if problems:
            return Answer(400, {"error": BROKEN, "errors": problems})
        steps = [Step(lambda: replace_text(path, new_text), lambda: replace_text(path, text), f"{path} could not be written, so nothing was saved")]
        return self.tasks.change(
            TaskKey(_KIND, pool_id), {path.resolve(): new_text}, [], steps, username,
            confirmed=True, moved=None, failed="", done=f"Saved {name}.",
            commit=f"saved parts of speech pool {name}", paths=[path],
        )

    def rename(self, pool_id: str, request: Mapping, username: str) -> Answer:
        """Change the pool's name, and the name in every task that lists it, as one change."""
        found = self._read(pool_id)
        if isinstance(found, Answer):
            return found
        path, text, data = found
        if request.get("version") != _version(text):
            return Answer(409, {"error": STALE, "stale": True})
        old = _name(data, path)
        name = request.get("name")
        if not isinstance(name, str):
            return Answer(400, {"error": "Send the pool's new name."})
        name = name.strip()
        refused = name_problem(name)
        if refused is not None:
            return Answer(400, {"error": refused})
        if name == old:
            return Answer(200, {"message": "The name has not changed, so nothing was saved.", "warnings": [], "pool": {"id": pool_id, "name": name}})
        refused = self._taken(name, own=path)
        if refused is not None:
            return Answer(400, {"error": refused})
        try:
            new_text = rewrite_root(text, path, {"name": text_value(name)})
            rewritten = self._renamed_in_tasks(old, name)
        except (EditError, OSError, UnicodeDecodeError) as error:
            return Answer(400, {"error": str(error)})
        files = {path: (text, new_text), **rewritten}
        steps = [
            Step(
                lambda file=file, after=after: replace_text(file, after),
                lambda file=file, before=before: replace_text(file, before),
                f"{file} could not be written, so nothing was renamed",
            )
            for file, (before, after) in files.items()
        ]
        users = self._users(old)
        done = f"Renamed {old} to {name}."
        if users:
            done += f" Changed the name in {', '.join(key.name for key in users)} too."
        answer = self.tasks.change(
            TaskKey(_KIND, pool_id), {file.resolve(): after for file, (_before, after) in files.items()}, [], steps, username,
            confirmed=True, moved=None, failed="", done=done,
            commit=f"renamed parts of speech pool {old} to {name}", paths=list(files),
        )
        if answer.status == 200:
            answer.body["pool"] = {"id": pool_id, "name": name}
        return answer

    def delete(self, pool_id: str, request: Mapping, username: str) -> Answer:
        """Remove the pool's file, unless a task lists it."""
        found = self._read(pool_id)
        if isinstance(found, Answer):
            return found
        path, text, data = found
        if request.get("version") != _version(text):
            return Answer(409, {"error": STALE, "stale": True})
        name = _name(data, path)
        users = self._users(name)
        if users:
            listed = ", ".join(key.name for key in users)
            return Answer(
                400,
                {"error": f"{name} cannot be deleted while {'a task uses' if len(users) == 1 else 'tasks use'} it: {listed}. "
                 "Take it out of those tasks first."},
            )
        status = path.stat()

        def put_back() -> None:
            path.write_text(text, encoding="utf-8")
            own_like(path, status)

        steps = [Step(path.unlink, put_back, f"{path} could not be removed, so nothing was deleted")]
        return self.tasks.change(
            TaskKey(_KIND, pool_id), {}, [], steps, username,
            confirmed=True, moved=None, failed="", done=f"Deleted {name}.",
            commit=f"deleted parts of speech pool {name}", paths=[path],
        )

    # Helpers

    def _read(self, pool_id: str) -> tuple[Path, str, Mapping] | Answer:
        if not _ID.fullmatch(pool_id):
            return _missing(pool_id)
        path = next((found for found in sentence_pools.list_pool_files(self.tasks.policy_file.parent) if found.stem == pool_id), None)
        if path is None:
            return _missing(pool_id)
        try:
            text = path.read_bytes().decode("utf-8")
            data = yaml.safe_load(text)
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
            return Answer(400, {"error": f"{path}: {error}"})
        if not isinstance(data, Mapping):
            return Answer(400, {"error": f"{path}: a pool file must be a mapping with name and sentences"})
        return path, text, data

    def _taken(self, name: str, own: Path | None = None) -> str | None:
        """Return why another pool already has this name, ignoring case, or None."""
        folded = name.casefold()
        for path in sentence_pools.list_pool_files(self.tasks.policy_file.parent):
            if own is not None and path == own:
                continue
            try:
                other = sentence_pools.peek_name(path)
            except ValueError:
                continue
            if other.casefold() == folded:
                return f"A pool named {other} already exists."
        return None

    def _users_by_file(self, name: str) -> dict[Path, list[TaskKey]]:
        """Return each file with a ``parts_of_speech`` task that lists the pool ``name``, and those tasks."""
        found: dict[Path, list[TaskKey]] = {}
        for key, path in sorted(self.tasks._files().items(), key=lambda item: item[0].name.casefold()):
            if key.type != PARTS_OF_SPEECH:
                continue
            try:
                written = read_task(path.read_bytes().decode("utf-8"), path, key)
            except (OSError, UnicodeDecodeError, EditError):
                continue
            pools = written.body_data.get("pools")
            if isinstance(pools, list) and any(isinstance(item, str) and item.strip() == name for item in pools):
                found.setdefault(path, []).append(key)
        return found

    def _users(self, name: str) -> list[TaskKey]:
        return [key for keys in self._users_by_file(name).values() for key in keys]

    def _renamed_in_tasks(self, old: str, name: str) -> dict[Path, tuple[str, str]]:
        """Return each task file's text before and after the pool ``old`` is renamed ``name`` in its tasks."""
        rewritten: dict[Path, tuple[str, str]] = {}
        for path, keys in self._users_by_file(old).items():
            before = path.read_bytes().decode("utf-8")
            after = before
            for key in keys:
                pools = read_task(after, path, key).body_data.get("pools")
                assert isinstance(pools, list)
                renamed = [name if isinstance(item, str) and item.strip() == old else item for item in pools]
                after = rewrite_task(after, path, key, {"body": {"pools": name_list([str(item) for item in renamed])}})
            rewritten[path] = (before, after)
        return rewritten


def _name(data: Mapping, path: Path) -> str:
    name = data.get("name")
    return name.strip() if isinstance(name, str) and name.strip() else path.stem


def _changes(data: Mapping, request: Mapping) -> dict[str, object]:
    """Return the pool's top-level fields whose value a save changes, as ``rewrite_root`` changes."""
    changes: dict[str, object] = {}
    typed = request.get(LEVEL)
    if typed is not None and not isinstance(typed, str):
        raise ValueError(f"{LEVEL} must be sent as text")
    written = data.get(LEVEL)
    if typed is not None:
        pool_level = level(typed, LEVEL)
    else:
        pool_level = written if isinstance(written, (int, float)) and not isinstance(written, bool) else None
    if typed is not None and (typed or "").strip() != shown_level(data.get(LEVEL)):
        changes[LEVEL] = None if pool_level is None or float(pool_level) == sentence_pools.DEFAULT_DIFFICULTY else shown_level(pool_level)
    asked = request.get("sentences")
    if asked is not None:
        if isinstance(asked, list) and not asked:
            raise ValueError(NO_SENTENCES)
        effective = sentence_pools.DEFAULT_DIFFICULTY if pool_level is None else float(pool_level)  # type: ignore[arg-type]
        edit = sentences_edit(data.get("sentences"), asked, effective)
        if edit is not None:
            changes["sentences"] = edit
    return changes


def check_pool(path: Path, text: str) -> list[str]:
    """Return why a pool file's text would not load if a task named it, or nothing."""
    token = sentence_pools.use_overrides({path.resolve(): text})
    try:
        pool = sentence_pools.load_pool(path)
    except ValueError as error:
        return list(problems_of(error))
    finally:
        sentence_pools.reset_overrides(token)
    problems = []
    for number, item in enumerate(pool.sentences, 1):
        try:
            check_pool_sentence(item, pool.difficulty, f"{path}: sentences entry {number}")
        except ValueError as error:
            problems.extend(problems_of(error))
    return problems


def _write_new(path: Path, text: str) -> None:
    """Write a new file, never over one already there, owned as its directory is."""
    make_directory(path.parent)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)
    own_like(path, path.parent.stat())

