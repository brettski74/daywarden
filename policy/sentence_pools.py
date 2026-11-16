"""Parts-of-speech sentence pools on disk under the config directory.

Each pool is a YAML file in ``parts_of_speech_pools/`` beside the root
policy file. The file name is a stable id. The pool's user-visible ``name``
is what tasks list under ``body.pools``. Only pools a task names are attached
to the running policy; the directory can still be listed for the portal.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

import yaml

from policy.owned import make_directory, own_like
from policy.problems import Collector
from policy.quiz import duration
from policy.tasks import TaskKey

POOLS_DIR = "parts_of_speech_pools"
DEFAULT_DIFFICULTY = 1.0
MIN_DIFFICULTY = 0.5
MAX_DIFFICULTY = 10.0

_CONFIG_ROOT: ContextVar[Path | None] = ContextVar("sentence_pools_config_root", default=None)
_POOL_KEYS = frozenset({"name", "level_of_difficulty", "sentences"})
_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class Pool:
    """One named pool of sentences as loaded from a file."""

    id: str
    path: Path
    name: str
    difficulty: float
    sentences: tuple[object, ...]  # raw sentence mappings; parts_of_speech parses them


def config_root(root: Path | None = None) -> Path:
    """Return the config directory that holds ``parts_of_speech_pools``."""
    if root is not None:
        return root
    found = _CONFIG_ROOT.get()
    if found is not None:
        return found
    return Path(os.environ.get("POLICY_FILE", "/etc/daywarden/policy.yaml")).parent


def pools_directory(root: Path | None = None) -> Path:
    return config_root(root) / POOLS_DIR


def use_config_root(root: Path):
    """Bind the config directory for pool loads during a policy load."""
    return _CONFIG_ROOT.set(root)


def reset_config_root(token) -> None:
    _CONFIG_ROOT.reset(token)


def list_pool_files(root: Path | None = None) -> list[Path]:
    """Return every pool YAML file, in name order. Missing directory is empty."""
    directory = pools_directory(root)
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in {".yaml", ".yml"} and not path.name.startswith(".")
    )


def index_names(root: Path | None = None) -> dict[str, Path]:
    """Return each pool's user-visible name to its file.

    Two pools with the same name raise ``ValueError`` naming both places.
    """
    names: dict[str, Path] = {}
    for path in list_pool_files(root):
        name = peek_name(path)
        if name in names:
            raise ValueError(
                f"parts of speech pool {name!r} is defined in both {names[name]} and {path}"
            )
        names[name] = path
    return names


def peek_name(path: Path) -> str:
    """Return the user-visible name in ``path``, or raise ``ValueError``."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"{path}: could not be read: {error}") from error
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ValueError(f"{path}: {error}") from error
    if not isinstance(data, Mapping):
        raise ValueError(f"{path}: a pool file must be a mapping with name and sentences")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{path}: name: required; a non-empty user-visible name")
    return name.strip()


def load_pool(path: Path) -> Pool:
    """Load and check one pool file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"{path}: could not be read: {error}") from error
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ValueError(f"{path}: {error}") from error
    if not isinstance(data, Mapping):
        raise ValueError(f"{path}: a pool file must be a mapping with name and sentences")
    fields = Collector()
    for key in sorted(set(data) - _POOL_KEYS):
        fields.add(f"{path}: {key}: unknown setting")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        fields.add(f"{path}: name: required; a non-empty user-visible name")
        name = ""
    else:
        name = name.strip()
    difficulty = DEFAULT_DIFFICULTY
    if "level_of_difficulty" in data:
        difficulty = fields.take(parse_difficulty, data["level_of_difficulty"], f"{path}: level_of_difficulty")
        if difficulty is None:
            difficulty = DEFAULT_DIFFICULTY
    listed = data.get("sentences")
    if "sentences" not in data:
        fields.add(f"{path}: sentences: required; list one or more sentences")
    elif not isinstance(listed, list) or not listed:
        fields.add(f"{path}: sentences: must be a list of one or more sentences")
    fields.finish()
    assert isinstance(listed, list) and listed
    return Pool(path.stem, path, name, difficulty, tuple(listed))


def load_named(names: Sequence[str], root: Path | None = None) -> dict[str, Pool]:
    """Load each named pool once. Unknown names are omitted; the caller reports them."""
    try:
        by_name = index_names(root)
    except ValueError:
        raise
    found: dict[str, Pool] = {}
    for name in names:
        if name in found:
            continue
        path = by_name.get(name)
        if path is None:
            continue
        found[name] = load_pool(path)
    return found


def parse_difficulty(value: object, where: str) -> float:
    """Return a level of difficulty from 0.5 through 10."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where}: must be a number from {MIN_DIFFICULTY} through {MAX_DIFFICULTY}")
    level = float(value)
    if not MIN_DIFFICULTY <= level <= MAX_DIFFICULTY:
        raise ValueError(f"{where}: must be a number from {MIN_DIFFICULTY} through {MAX_DIFFICULTY}")
    return level


def clamp_difficulty(value: float) -> float:
    return max(MIN_DIFFICULTY, min(MAX_DIFFICULTY, value))


def unique_name(wanted: str, taken: set[str]) -> str:
    """Return ``wanted``, or ``wanted 2``, ``wanted 3``, … when taken."""
    if wanted not in taken:
        return wanted
    number = 2
    while f"{wanted} {number}" in taken:
        number += 1
    return f"{wanted} {number}"


def pool_id(name: str, directory: Path) -> str:
    """Return a new stable file id derived from ``name``."""
    base = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "pool"
    if not _ID.fullmatch(base):
        base = "pool"
    candidate = base
    number = 2
    while (directory / f"{candidate}.yaml").exists():
        candidate = f"{base}-{number}"
        number += 1
    return candidate


def write_pool(directory: Path, pool_id: str, name: str, sentences: list[dict], *, difficulty: float | None = None) -> Path:
    """Write a new pool file and return its path."""
    make_directory(directory)
    path = directory / f"{pool_id}.yaml"
    document: dict[str, object] = {"name": name}
    if difficulty is not None and difficulty != DEFAULT_DIFFICULTY:
        document["level_of_difficulty"] = difficulty
    document["sentences"] = sentences
    text = yaml.safe_dump(document, sort_keys=False, allow_unicode=True, default_flow_style=False)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    own_like(temporary, directory.stat())
    temporary.replace(path)
    own_like(path, directory.stat())
    return path


def migrate_policy(policy_path: Path) -> list[Path]:
    """Rewrite every parts-of-speech task that still has inline ``sentences``.

    Creates one pool per such task under ``parts_of_speech_pools/``, sets the
    task's ``pools``, and removes ``sentences``. Returns every path written.
    """
    from policy.task_edit import EditError, rewrite_task

    # Scan without parsing quiz bodies: those still hold inline sentences until we rewrite.
    written: list[Path] = []
    by_file: dict[Path, list[TaskKey]] = {}
    for key, path in _scan_task_files(policy_path).items():
        if key.type == "parts_of_speech":
            by_file.setdefault(path, []).append(key)
    if not by_file:
        return written

    root = policy_path.parent
    directory = pools_directory(root)
    try:
        taken = set(index_names(root))
    except ValueError:
        taken = set()
    # Also collect names we are about to create in this pass.
    pending_names: set[str] = set()

    for path, task_keys in sorted(by_file.items(), key=lambda item: str(item[0])):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        new_text = text
        file_changed = False
        for key in sorted(task_keys, key=lambda item: item.name):
            body = _task_body(new_text, path, key)
            if body is None or "sentences" not in body:
                continue
            sentences = body.get("sentences")
            if not isinstance(sentences, list) or not sentences:
                continue
            task_timeout = _task_timeout_ms(body)
            converted = [_migrate_sentence(item, task_timeout) for item in sentences]
            wanted = f"{key.name} sentences"
            name = unique_name(wanted, taken | pending_names)
            pending_names.add(name)
            pool_key = pool_id(name, directory)
            write_pool(directory, pool_key, name, converted)
            written.append(directory / f"{pool_key}.yaml")
            try:
                new_text = rewrite_task(
                    new_text,
                    path,
                    key,
                    {"body": {"sentences": None, "pools": [name]}},
                )
            except EditError:
                continue
            file_changed = True
            taken.add(name)
        if file_changed and new_text != text:
            _replace(path, new_text)
            written.append(path)
    return written


def _migrate_sentence(item: object, task_timeout_ms: int) -> dict:
    """Return a pool sentence mapping, converting a per-sentence timeout to difficulty."""
    if not isinstance(item, Mapping):
        return {"sentence": "", "parts": {}}
    result = {key: value for key, value in item.items() if key != "timeout"}
    if "timeout" not in item:
        return result
    try:
        sentence_ms = duration(item["timeout"], "timeout")
    except ValueError:
        return result
    if task_timeout_ms <= 0:
        return result
    level = clamp_difficulty(sentence_ms / task_timeout_ms)
    if level != DEFAULT_DIFFICULTY:
        result["level_of_difficulty"] = level if level != int(level) else int(level)
    return result


def _task_timeout_ms(body: Mapping) -> int:
    try:
        return duration(body.get("timeout", "90s"), "timeout")
    except ValueError:
        return 90_000


def _task_body(text: str, path: Path, key: TaskKey) -> dict | None:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(data, Mapping):
        return None
    tasks = data.get("tasks")
    if not isinstance(tasks, Mapping):
        return None
    types = tasks.get(key.type)
    if not isinstance(types, Mapping):
        return None
    task = types.get(key.name)
    if not isinstance(task, Mapping):
        return None
    body = task.get("body")
    return body if isinstance(body, Mapping) else None


def _scan_task_files(policy_path: Path) -> dict[TaskKey, Path]:
    """Best-effort map of tasks to files when the normal scan cannot run."""
    found: dict[TaskKey, Path] = {}
    for path in _included_files(policy_path):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, Mapping):
            continue
        tasks = data.get("tasks")
        if not isinstance(tasks, Mapping):
            continue
        for kind, names in tasks.items():
            if not isinstance(names, Mapping):
                continue
            for name in names:
                if isinstance(name, str):
                    found[TaskKey(str(kind), name)] = path
    return found


def _included_files(policy_path: Path) -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []

    def walk(path: Path) -> None:
        try:
            canonical = path.resolve()
        except OSError:
            return
        if canonical in seen or not path.is_file():
            return
        seen.add(canonical)
        ordered.append(path)
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            return
        if not isinstance(data, Mapping):
            return
        include = data.get("include")
        if not isinstance(include, list):
            return
        for entry in include:
            if not isinstance(entry, str):
                continue
            target = (path.parent / entry).resolve() if not Path(entry).is_absolute() else Path(entry)
            if target.is_dir():
                for child in sorted(target.glob("*.yaml")) + sorted(target.glob("*.yml")):
                    walk(child)
            else:
                walk(target)

    walk(policy_path)
    return ordered


def _replace(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    try:
        status = path.stat()
    except OSError:
        status = path.parent.stat()
    own_like(temporary, status)
    temporary.replace(path)
    own_like(path, status)


def allowed_ms(difficulty: float, task_timeout_ms: int) -> int:
    """Return the sentence time: ceil(difficulty × task timeout) as whole seconds, in ms."""
    seconds = math.ceil(difficulty * task_timeout_ms / 1000)
    return max(1, seconds) * 1000
