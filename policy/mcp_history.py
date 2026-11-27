"""The MCP tools for the config history (S047): list, read, compare, and revert.

A revision is a short or full commit id, and ``current`` is the newest. The
read tools give what the Config History pages show. ``revert_config``
reverts through ``ConfigHistory.revert``, the path the portal's Revert takes,
so it has the same checks and refusals, keeps ``mcp.yaml``, and commits as
``ada via Claude Code: reverted to 3f2a9c1 (2026-11-17 20:15)``.

``config_history: read`` reads every file in the config directory, including
sections the agent has no other permission to read.
"""

from __future__ import annotations

from collections.abc import Mapping

from policy.config_history import NO_HISTORY, ConfigHistory, Unknown
from policy.mcp_tools import Sources, Tool, ToolProblem, Writer, _text
from policy.mcp_writes import _made, _with

KIND = "config_history"
_REVISION = {"type": "string", "description": "A revision's short or full id, or current for the newest."}
_FILE = {"type": "string", "description": "A file's path in the config directory, such as tasks.d/spelling.yaml."}


def _history(sources: Sources) -> ConfigHistory:
    history = sources.history
    if history is None or not history.kept:
        raise ToolProblem(NO_HISTORY)
    return history


def _limit(arguments: Mapping) -> int:
    value = arguments.get("limit", 50)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ToolProblem("limit must be a whole number of at least 1.")
    return value


def _shown(row: dict) -> dict:
    return {key: row[key] for key in ("id", "short", "time", "author", "message", "files")}


def _diff_files(files: list[dict]) -> list[dict]:
    return [{"path": item["path"], "status": item["status"], "diff": item["unified"]} for item in files]


def list_config_history(sources: Sources, arguments: Mapping) -> dict:
    history = _history(sources)
    before = _text(arguments, "before", required=False) or None
    file = _text(arguments, "file", required=False) or None
    try:
        rows = history.older(before, _limit(arguments), file)
    except Unknown as error:
        raise ToolProblem(str(error)) from error
    return {"revisions": [_shown(row) for row in rows], "times": history.times()}


def get_config_revision(sources: Sources, arguments: Mapping) -> dict:
    history = _history(sources)
    try:
        found = history.files(_text(arguments, "revision"), _text(arguments, "file", required=False) or None)
    except Unknown as error:
        raise ToolProblem(str(error)) from error
    return {"revision": _shown(found["revision"]), "files": found["files"]}


def diff_config_revisions(sources: Sources, arguments: Mapping) -> dict:
    history = _history(sources)
    revision = _text(arguments, "revision", required=False)
    start = _text(arguments, "from", required=False)
    try:
        if revision:
            if start:
                raise ToolProblem("Give revision, or from and to, not both.")
            found = history.revision(revision)
            return {"revision": _shown(found["revision"]), "files": _diff_files(found["diff"])}
        if not start:
            raise ToolProblem("Give from, or revision.")
        found = history.compare(start, _text(arguments, "to", required=False) or "current")
    except Unknown as error:
        raise ToolProblem(str(error)) from error
    return {"from": _shown(found["from"]), "to": _shown(found["to"]), "files": _diff_files(found["diff"])}


def revert_config(sources: Sources, arguments: Mapping, writer: Writer) -> dict:
    history = _history(sources)
    revision = _text(arguments, "revision")
    with _with(writer):
        answer = history.revert(revision, writer.parent)
    if answer.status == 404:
        raise ToolProblem(str(answer.body.get("error")))
    body = _made(answer)
    found: dict = {"message": body.get("message", ""), "warnings": [*body.get("renames", []), *body.get("warnings", [])]}
    if body.get("nothing"):
        found["nothing"] = True
    if writer.dry_run:
        found["dry_run"] = True
        found["files"] = _diff_files(body.get("diff", []))
    return found


HISTORY_TOOLS: tuple[Tool, ...] = (
    Tool(
        "list_config_history", KIND, "read",
        "The config directory's saved versions, newest first, each with its full and short id, household-local time, author, "
        "message, and the files it changed. before lists the versions older than that revision; file keeps only the versions that changed it.",
        list_config_history,
        {"limit": {"type": "integer", "minimum": 1, "description": "How many, 50 when left out."}, "before": _REVISION, "file": _FILE},
    ),
    Tool(
        "get_config_revision", KIND, "read",
        "A revision's details and the text of each file in the config directory as it was then, or of one file.",
        get_config_revision, {"revision": _REVISION, "file": _FILE}, ("revision",), lambda arguments: str(arguments.get("revision", "")),
    ),
    Tool(
        "diff_config_revisions", KIND, "read",
        "The unified diff of each file that differs from one revision to another, with whether it was added, changed, or removed. "
        "to is current when left out. Given revision in place of from, what that revision changed against the one before it.",
        diff_config_revisions, {"from": _REVISION, "to": _REVISION, "revision": _REVISION},
    ),
    Tool(
        "revert_config", KIND, "update",
        "Put every file in the config directory back as it was at a revision, as one new revision, as Revert on its page does. "
        "mcp.yaml is kept as it is now. The files are checked as dw check checks them first. "
        "A dry run answers with the diff and the warnings, such as renames made since, and changes nothing.",
        revert_config,
        {"revision": _REVISION, "dry_run": {"type": "boolean", "description": "Check and show the change without making it."}},
        ("revision",), lambda arguments: str(arguments.get("revision", "")), write=True,
    ),
)
