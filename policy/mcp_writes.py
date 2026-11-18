"""The MCP write tools for tasks and parts of speech sentence pools (S036.2).

Each tool turns its arguments into the request the portal page sends, and
saves through the same code the page saves through: ``TaskAdmin.save``,
``TaskChanges``, and ``PoolAdmin``. So a write is checked as a portal save
is, applied with a reload, and committed in the config history. While a tool
runs, ``task_admin.acting`` names the agent, so the commit reads such as
``ada via Claude Code: saved task arithmetic/times-7``, and a ``dry_run``
stops after the checks with a diff of what would change.

The agent never holds a page's version. A tool reads the version on disk
just before it saves, so a change made in the portal a moment earlier is
kept, as between two portal tabs.

A successful write answers with the thing written as its read tool shows it
now. A refused write raises ``WriteRefused`` with every reason the page
would give.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from policy import spelling, spelling_directories
from policy.arithmetic import ARITHMETIC
from policy.mcp_tools import (
    Sources,
    Tool,
    ToolProblem,
    WriteFailed,
    WriteRefused,
    Writer,
    _key_target,
    _pools,
    _tasks,
    _text,
    get_sentence_pool,
    get_task,
)
from policy.number_lists_admin import ARITHMETIC_SETTINGS, ARITHMETIC_TABLES, SKIP_COUNTING_SETTINGS, SKIP_COUNTING_TABLES
from policy.parts_of_speech import PARTS_OF_SPEECH, entry_positions, split_words
from policy.parts_of_speech_admin import LEVEL, pool_list
from policy.parts_of_speech_admin import SETTINGS as PARTS_OF_SPEECH_SETTINGS
from policy.skip_counting import SKIP_COUNTING
from policy.task_admin import COMMON_FIELDS, NOT_FOR_PARENT_CHECK, SPELLING_SETTINGS, Agent, Answer, acting
from policy.task_create import NEW_TYPES, TaskChanges
from policy.task_edit import WrittenTask
from policy.tasks import PARENT_CHECK, TaskKey

WORDS_REFUSED = "A spelling task's words are set in the portal, where they are recorded."
CONFIRM = "Call again with confirmed: true once the parent agrees."
_EMPTY = WrittenTask({}, (), {})


def _changes(sources: Sources) -> TaskChanges:
    if sources.changes is None:
        raise ToolProblem("Tasks cannot be changed here.")
    return sources.changes


def _made(answer: Answer) -> dict:
    """Return a page's answer to a save, or raise the refusal it gives."""
    body = answer.body
    if answer.status == 200:
        return body
    if "confirm" in body:
        raise WriteRefused([f"{body['confirm']} {CONFIRM}"])
    error = str(body.get("error", "The change was refused."))
    reasons = [str(reason) for reason in body.get("errors") or []]
    if answer.status >= 500:
        raise WriteFailed([error, *reasons])
    raise WriteRefused(reasons or [error], heading=error)


def _answer(body: dict, writer: Writer, shown: Callable[[], dict]) -> dict:
    """Return a write's answer: what the page said, and the thing written now, or what a dry run would change."""
    found: dict = {"message": body.get("message", ""), "warnings": list(body.get("warnings", []))}
    if writer.dry_run:
        found["dry_run"] = True
        found["changes"] = body.get("changes", "")
        if body.get("moves"):
            found["moves"] = body["moves"]
        return found
    found.update(shown())
    return found


def _with(writer: Writer):
    return acting(Agent(writer.agent, writer.dry_run))


# Task settings


def _setting_text(value: object, name: str) -> str | None:
    """Return a setting as the page's text box holds it. None clears the setting."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
    raise ValueError(f"{name} must be text, a number, true or false, or null to clear it.")


def _rows(value: object, name: str) -> object:
    """Return a weighted list as the page's rows. A row may be written as the file writes it, with ``value``."""
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list of rows, such as [{{\"from\": 2, \"to\": 12, \"weight\": 1}}].")
    rows = []
    for row in value:
        if isinstance(row, Mapping) and "value" in row:
            row = {("from" if key == "value" else key): item for key, item in row.items()}
        rows.append(row)
    return rows


def _names(value: object, name: str) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of names.")
    return value


def _settings_of(kind: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Return a type's own settings, its weighted lists, and its other named fields."""
    if kind == spelling.SPELLING:
        return SPELLING_SETTINGS, (), spelling_directories.FIELDS
    if kind == PARTS_OF_SPEECH:
        return PARTS_OF_SPEECH_SETTINGS, (), ("pools", "parts_of_speech")
    if kind == SKIP_COUNTING:
        return SKIP_COUNTING_SETTINGS, tuple(table.field for table in SKIP_COUNTING_TABLES), ()
    if kind == ARITHMETIC:
        return ARITHMETIC_SETTINGS, tuple(table.field for table in ARITHMETIC_TABLES), ()
    return (), (), ()


def task_request(sources: Sources, kind: str, settings: object) -> dict:
    """Return the request a task page sends for ``settings``, naming only the fields they name.

    Raises ``WriteRefused`` listing every setting that cannot be used.
    """
    if settings is None:
        return {}
    if not isinstance(settings, Mapping):
        raise WriteRefused(["settings must map each setting to its value, such as {\"pass_cooldown\": \"2d\"}."])
    common = tuple(name for name in COMMON_FIELDS if kind != PARENT_CHECK or name not in NOT_FOR_PARENT_CHECK)
    own, tables, others = _settings_of(kind)
    request: dict = {}
    reasons: list[str] = []
    for name, value in settings.items():
        try:
            if name == "words" and kind == spelling.SPELLING:
                raise ValueError(WORDS_REFUSED)
            if name == "groups":
                request["groups"] = _names(value, name)
            elif name in common:
                request.setdefault("fields", {})[name] = _setting_text(value, name)
            elif name in own:
                request.setdefault("settings", {})[name] = _setting_text(value, name)
            elif name in tables:
                request.setdefault("lists", {})[name] = _rows(value, name)
            elif name in spelling_directories.FIELDS and kind == spelling.SPELLING:
                request.setdefault("directories", {})[name] = _directory(sources, name, value)
            elif name == "pools" and kind == PARTS_OF_SPEECH:
                request["pools"] = _pool_names(sources, value)
            elif name == "parts_of_speech" and kind == PARTS_OF_SPEECH:
                request["parts_of_speech"] = _names(value, name)
            else:
                known = ", ".join(("groups", *common, *own, *tables, *others))
                raise ValueError(f"{name} is not a setting of a {kind} task. Its settings are {known}.")
        except ValueError as error:
            reasons.append(str(error))
    if reasons:
        raise WriteRefused(reasons, heading="The task was not changed." if len(reasons) > 1 else None)
    return request


def _directory(sources: Sources, name: str, value: object) -> str:
    """Return an existing directory for a spelling task's directory field. Directories are made in the portal."""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a path from the data directory, such as spelling/current.")
    path = spelling._directory(value, name)
    if not (_tasks(sources).data_root() / path).is_dir():
        raise ValueError(f"{name}: {path} is not an existing directory. A new directory is made in the portal.")
    return path


def _pool_names(sources: Sources, value: object) -> list[str]:
    """Return the names of the pools a parts of speech task chooses by id."""
    ids = _names(value, "pools")
    found = {entry["id"]: entry["name"] for entry in pool_list(_tasks(sources).policy_file.parent) if "problem" not in entry}
    unknown = [pool for pool in ids if pool not in found]
    if unknown:
        listed = ", ".join(sorted(found)) or "none yet"
        raise ValueError(f"{', '.join(unknown)} {'is not a pool id' if len(unknown) == 1 else 'are not pool ids'}. The pools are {listed}.")
    return [found[pool] for pool in ids]


def _confirmed(arguments: Mapping) -> bool:
    return arguments.get("confirmed") is True


def _shown_task(sources: Sources, key: TaskKey):
    return lambda: {"task": get_task(sources, {"type": key.type, "name": key.name})}


# Task tools


def create_task(sources: Sources, arguments: Mapping, writer: Writer) -> dict:
    kind = _text(arguments, "type")
    name = _text(arguments, "name")
    if kind not in NEW_TYPES:
        raise WriteRefused([f"{kind} is not a type a task can be made with. The types are {', '.join(NEW_TYPES)}."])
    request = {"type": kind, "name": name, **task_request(sources, kind, arguments.get("settings"))}
    with _with(writer):
        body = _made(_changes(sources).create(request, writer.parent))
    return _answer(body, writer, _shown_task(sources, TaskKey(kind, name)))


def update_task(sources: Sources, arguments: Mapping, writer: Writer) -> dict:
    key = TaskKey(_text(arguments, "type"), _text(arguments, "name"))
    tasks = _tasks(sources)
    page = _made(tasks.page(key))
    request = task_request(sources, key.type, arguments.get("settings"))
    request.update(version=page["version"], confirmed=_confirmed(arguments))
    with _with(writer):
        body = _made(tasks.save(key, request, writer.parent))
    return _answer(body, writer, _shown_task(sources, key))


def rename_task(sources: Sources, arguments: Mapping, writer: Writer) -> dict:
    key = TaskKey(_text(arguments, "type"), _text(arguments, "name"))
    page = _made(_tasks(sources).page(key))
    new_name = arguments.get("new_name")
    with _with(writer):
        body = _made(_changes(sources).rename(key, {"version": page["version"], "name": new_name}, writer.parent))
    return _answer(body, writer, _shown_task(sources, TaskKey(key.type, str(new_name))))


def retire_task(sources: Sources, arguments: Mapping, writer: Writer) -> dict:
    key = TaskKey(_text(arguments, "type"), _text(arguments, "name"))
    with _with(writer):
        body = _made(_changes(sources).retire(key, writer.parent))
    return _answer(body, writer, lambda: {"retired": {"type": key.type, "name": key.name}})


# Sentence pools


def _page_sentence(item: object, number: int) -> dict:
    """Return a sentence written as the pool file writes it, such as ``{"sentence": ..., "parts": {"noun": ["cat"]}}``, as the page sends it."""
    where = f"sentence {number}"
    if not isinstance(item, Mapping):
        raise ValueError(f"{where} must be a mapping with sentence and parts.")
    unknown = sorted(str(key) for key in set(item) - {"sentence", "parts", LEVEL})
    if unknown:
        raise ValueError(f"{where}: {unknown[0]} is not part of a sentence. A sentence has sentence, parts, and {LEVEL}.")
    text = item.get("sentence")
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{where} needs its sentence text.")
    where = f"{where} ({text.strip()})"
    parts = item.get("parts")
    if not isinstance(parts, Mapping) or not parts:
        raise ValueError(f"{where}: parts must map each part of speech to its words, such as {{\"noun\": [\"cat\"]}}.")
    words = split_words(text)
    rows = []
    for name, entries in parts.items():
        listed = [entries] if isinstance(entries, str) else entries
        if not isinstance(listed, list):
            raise ValueError(f"{where}: parts.{name} must be a list of words.")
        positions: list[int] = []
        for entry_number, entry in enumerate(listed, 1):
            positions += entry_positions(entry, entry_number, words, f"{where}: parts.{name}")
        rows.append({"name": str(name), "words": sorted(set(positions))})
    level = item.get(LEVEL)
    return {"text": text, LEVEL: "" if level is None else str(level), "parts": rows}


def page_sentences(listed: object, name: str) -> list[dict]:
    """Return sentences in the pool file's form as the page sends them. Raises ``WriteRefused`` with every problem."""
    if not isinstance(listed, list):
        raise WriteRefused([f"{name} must be a list of sentences, each with sentence and parts."])
    sentences, reasons = [], []
    for number, item in enumerate(listed, 1):
        try:
            sentences.append(_page_sentence(item, number))
        except ValueError as error:
            reasons.append(str(error))
    if reasons:
        raise WriteRefused(reasons, heading="The pool was not changed." if len(reasons) > 1 else None)
    return sentences


def _level(arguments: Mapping) -> dict:
    value = arguments.get(LEVEL)
    if value is None:
        return {}
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise WriteRefused([f"{LEVEL} must be a number from 0.5 through 10."])
    return {LEVEL: str(value)}


def _shown_pool(sources: Sources, pool_id: str):
    return lambda: {"pool": get_sentence_pool(sources, {"id": pool_id})}


def create_sentence_pool(sources: Sources, arguments: Mapping, writer: Writer) -> dict:
    request = {"name": _text(arguments, "name"), "sentences": page_sentences(arguments.get("sentences"), "sentences"), **_level(arguments)}
    with _with(writer):
        body = _made(_pools(sources).create(request, writer.parent))
    pool_id = body.get("pool", {}).get("id", "")
    return _answer(body, writer, _shown_pool(sources, pool_id))


def update_sentence_pool(sources: Sources, arguments: Mapping, writer: Writer) -> dict:
    pool_id = _text(arguments, "id")
    pools = _pools(sources)
    page = _made(pools.page(pool_id))
    added = page_sentences(arguments.get("add") or [], "add")
    removing = arguments.get("remove") or []
    if not isinstance(removing, list) or not all(isinstance(text, str) for text in removing):
        raise WriteRefused(["remove must be a list of sentences, each its exact text."])
    texts = [sentence["text"] for sentence in page["sentences"]]
    missing = [text for text in removing if text not in texts]
    if missing:
        raise WriteRefused([f"No sentence in {page['name']} reads exactly: {text}" for text in missing])
    kept = [{**sentence, "origin": origin} for origin, sentence in enumerate(page["sentences"]) if sentence["text"] not in removing]
    request = {"version": page["version"], "sentences": kept + added, **_level(arguments)}
    with _with(writer):
        body = _made(pools.save(pool_id, request, writer.parent))
    return _answer(body, writer, _shown_pool(sources, pool_id))


def rename_sentence_pool(sources: Sources, arguments: Mapping, writer: Writer) -> dict:
    pool_id = _text(arguments, "id")
    pools = _pools(sources)
    page = _made(pools.page(pool_id))
    with _with(writer):
        body = _made(pools.rename(pool_id, {"version": page["version"], "name": arguments.get("name")}, writer.parent))
    return _answer(body, writer, _shown_pool(sources, pool_id))


def delete_sentence_pool(sources: Sources, arguments: Mapping, writer: Writer) -> dict:
    pool_id = _text(arguments, "id")
    pools = _pools(sources)
    page = _made(pools.page(pool_id))
    with _with(writer):
        body = _made(pools.delete(pool_id, {"version": page["version"]}, writer.parent))
    return _answer(body, writer, lambda: {"deleted": {"id": pool_id, "name": page["name"]}})


# The tools

_DRY_RUN = {
    "dry_run": {
        "type": "boolean",
        "description": "true to check the change and see what it would change, without writing anything.",
    }
}
_TASK_KEY = {
    "type": {"type": "string", "description": "The task's type, such as arithmetic."},
    "name": {"type": "string", "description": "The task's name, such as times-7."},
}
_SETTINGS = {
    "type": "object",
    "description": (
        "The task's settings by name, as get_task shows them: groups, pass_cooldown, failure_cooldown, max_skips, "
        "max_passes, available_from, due_date, and the type's own, such as operation, max_timeout, min_timeout, "
        "correct_answers_required, operands, and first for arithmetic. A weighted list is rows such as "
        "{\"from\": 2, \"to\": 12, \"weight\": 1} or {\"value\": 7, \"weight\": 1}. A parts of speech task's pools are "
        "pool ids from list_sentence_pools. A spelling task's directories are existing paths from the data directory. "
        "null clears a setting."
    ),
}
_CONFIRMED = {
    "confirmed": {
        "type": "boolean",
        "description": "true once the parent agrees to save a task with a due date that a client group has already passed.",
    }
}
_SENTENCES = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "sentence": {"type": "string"},
            "parts": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "string"}}},
            LEVEL: {"type": ["number", "string"]},
        },
        "required": ["sentence", "parts"],
    },
    "description": (
        "Sentences as the pool file writes them, such as {\"sentence\": \"The cat sat.\", \"parts\": {\"noun\": [\"cat\"], "
        "\"verb\": [\"sat\"]}}. A word that appears twice is named with its occurrence, such as the[2]."
    ),
}
_POOL_LEVEL = {LEVEL: {"type": ["number", "string"], "description": "The pool's level of difficulty, 0.5 through 10."}}
_POOL_ID = {"id": {"type": "string", "description": "The pool's id, from list_sentence_pools."}}


def _pool_target(arguments: Mapping) -> str:
    return str(arguments.get("id") or arguments.get("name") or "")


WRITE_TOOLS: tuple[Tool, ...] = (
    Tool(
        "create_task", "tasks", "create",
        "Make a task, as the new task page does: arithmetic, parts_of_speech, skip_counting, or spelling. "
        "A spelling task's words are set in the portal.",
        create_task, {**_TASK_KEY, "settings": _SETTINGS, **_DRY_RUN}, ("type", "name"), _key_target, write=True,
    ),
    Tool(
        "update_task", "tasks", "update",
        "Change only the settings named, as a save on the task's page does. A spelling task's words are set in the portal.",
        update_task, {**_TASK_KEY, "settings": _SETTINGS, **_CONFIRMED, **_DRY_RUN}, ("type", "name", "settings"), _key_target, write=True,
    ),
    Tool(
        "rename_task", "tasks", "update", "Rename a task, as on its page. Its attempts follow it.",
        rename_task, {**_TASK_KEY, "new_name": {"type": "string"}, **_DRY_RUN}, ("type", "name", "new_name"), _key_target, write=True,
    ),
    Tool(
        "retire_task", "tasks", "delete", "Take a task out of the policy. Its attempts are kept.",
        retire_task, {**_TASK_KEY, **_DRY_RUN}, ("type", "name"), _key_target, write=True,
    ),
    Tool(
        "create_sentence_pool", "sentence_pools", "create",
        "Make a parts of speech sentence pool, listed under Parts of Speech Pools.",
        create_sentence_pool, {"name": {"type": "string"}, "sentences": _SENTENCES, **_POOL_LEVEL, **_DRY_RUN},
        ("name", "sentences"), _pool_target, write=True,
    ),
    Tool(
        "update_sentence_pool", "sentence_pools", "update",
        "Add and remove a pool's sentences together. A sentence is removed by its exact text, and changed by removing it and adding the new one.",
        update_sentence_pool,
        {**_POOL_ID, "add": _SENTENCES, "remove": {"type": "array", "items": {"type": "string"}}, **_POOL_LEVEL, **_DRY_RUN},
        ("id",), _pool_target, write=True,
    ),
    Tool(
        "rename_sentence_pool", "sentence_pools", "update", "Rename a pool, and the name in each task that uses it, as its page does.",
        rename_sentence_pool, {**_POOL_ID, "name": {"type": "string"}, **_DRY_RUN}, ("id", "name"), _pool_target, write=True,
    ),
    Tool(
        "delete_sentence_pool", "sentence_pools", "delete", "Delete a pool, as its page does. Refused while a task uses it.",
        delete_sentence_pool, {**_POOL_ID, **_DRY_RUN}, ("id",), _pool_target, write=True,
    ),
)
