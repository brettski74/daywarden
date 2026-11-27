"""Config History (S047): every saved version of the config directory, compared, and reverted to.

A revision is one commit in the config history from S023.1. The portal's
Config History pages and the ``config_history`` MCP tools read it through
``ConfigHistory``, and both revert through ``ConfigHistory.revert``.

Reverting never rewrites history. The old revision's files, with
``mcp.yaml`` as it is now, are written into a staging copy of the config
directory and checked there as ``dw check`` checks them, before anything is
written. Then ``TaskAdmin.change`` makes it as it makes every portal save:
hand edits committed first as their own revision, each file written or
removed with a way back, every service reloaded, and one new commit on top
of the newest revision. Nothing runs ``git reset`` or ``git revert``, or
moves a branch.

``mcp.yaml`` is kept so that a revert never widens or narrows what an agent
may do. Renames made in the portal since the revision are found from the
commit messages, which the portal writes as ``renamed <kind> <old> to <new>``.
The rows stored under a new name are not moved back.

The data directory is not in the history, so spelling words, recordings,
attempts, and usage are never reverted.
"""

from __future__ import annotations

import difflib
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Mapping
from datetime import datetime, tzinfo
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import Response

from policy import mcp_settings
from policy.check import load_required
from policy.hierarchy import ConfigError
from policy.history import Commit, History, HistoryError
from policy.owned import make_directory, own_like
from policy.portal import PortalGate, json_answer, json_body
from policy.task_admin import Answer, Step, TaskAdmin

PAGE_SIZE = 50
CONTEXT_LINES = 3
CURRENT = "current"
ADDED, CHANGED, REMOVED = "added", "changed", "removed"
NO_HISTORY = "The config directory has no history of its own, so there is no config history."
CHANGED_MEANWHILE = (
    "The configuration changed after this dialog was opened, so nothing was reverted. "
    "Look at this version again, then revert."
)
NOTHING = "This version is the same as the newest one, apart from the MCP settings, so nothing was reverted."
NEWEST = "This is the newest version, so there is nothing to revert to."
MCP_KEPT = "The MCP settings in mcp.yaml are kept as they are now. They are changed on the MCP Server page."
REFUSED = "The files of this version do not pass dw check, so nothing was reverted."
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} [+-]\d{4} ")
_RENAMED = re.compile(
    r"renamed (?P<kind>client group|site group|time window|quota|rule set|task|parts of speech pool|capitalisation pool) "
    r"(?P<old>.+) to (?P<new>.+)\Z"
)
# What a rename leaves under the new name, as the rows rename_history.py and the task rename move.
_KEPT_UNDER = {
    "client group": "Attempts and usage recorded under {new} stay under {new}.",
    "site group": "Usage recorded under {new} stays under {new}.",
    "quota": "Usage recorded under {new} stays under {new}.",
    "task": "Attempts recorded under {new} stay under {new}.",
}


class Unknown(LookupError):
    """A revision or a file that the history does not have. The message names it."""


class ConfigHistory:
    def __init__(self, tasks: TaskAdmin) -> None:
        self.tasks = tasks
        self._trees: dict[str, dict[str, bytes]] = {}

    @property
    def directory(self) -> Path:
        return self.tasks.policy_file.parent

    @property
    def history(self) -> History:
        return History(self.directory)

    @property
    def kept(self) -> bool:
        return self.history.kept

    def zone(self) -> tzinfo | None:
        return self.tasks.now().tzinfo

    # Reading

    def row(self, commit: Commit) -> dict:
        """Return a revision as the list and the tools show it: ids, household-local time, author, what was done, files."""
        return {
            "id": commit.id,
            "short": commit.short,
            "time": self.when(commit),
            "author": commit.author,
            "what": what(commit.message.splitlines()[0] if commit.message else "", commit.author),
            "message": commit.message,
            "files": list(commit.files),
        }

    def when(self, commit: Commit) -> str:
        return datetime.fromtimestamp(commit.at, self.zone()).strftime("%Y-%m-%d %H:%M")

    def listing(self, page: int = 1, file: str | None = None) -> dict:
        """Return one page of revisions, newest first, and the hand edits waiting to be committed."""
        if not self.kept:
            return {"kept": False}
        history = self.history
        has_commits = history.head() is not None
        total = history.count(file) if has_commits else 0
        pages = max(1, -(-total // PAGE_SIZE))
        page = min(max(1, page), pages)
        commits = history.log(skip=(page - 1) * PAGE_SIZE, limit=PAGE_SIZE, file=file) if has_commits else []
        try:
            hand = history.changed()
        except HistoryError:
            hand = []
        return {
            "kept": True,
            "revisions": [self.row(commit) for commit in commits],
            "page": page,
            "pages": pages,
            "total": total,
            "file": file or None,
            "hand_edits": hand,
            "times": self.times(),
        }

    def times(self) -> str:
        zone = self.zone()
        return f"Times are in {getattr(zone, 'key', None) or (zone.tzname(None) if zone else 'local time')}."

    def older(self, before: str | None, limit: int, file: str | None) -> list[dict]:
        """Return up to ``limit`` revisions, newest first, from the one before ``before``, or from the newest."""
        history = self.history
        if history.head() is None:
            return []
        start = "HEAD" if before is None else self.resolve(before)
        commits = history.log(start, limit=limit + (0 if before is None else 1), file=file)
        if before is not None and commits and commits[0].id == start:
            commits = commits[1:]
        return [self.row(commit) for commit in commits[:limit]]

    def resolve(self, revision: str) -> str:
        """Return a revision's full id from a short or full id, or ``current`` for the newest. Raise ``Unknown`` otherwise."""
        history = self.history
        found = history.head() if revision.strip().lower() == CURRENT else history.resolve(revision)
        if found is None:
            raise Unknown(f"There is no revision {revision} in the config history.")
        return found

    def commit(self, revision: str) -> Commit:
        full = self.resolve(revision)
        (found,) = self.history.log(full, limit=1)
        return found

    def tree(self, commit: str | None) -> dict[str, bytes]:
        """Return every file of a revision, or nothing for None, the revision before the first."""
        if commit is None:
            return {}
        if commit not in self._trees:
            if len(self._trees) > 32:
                self._trees.clear()
            self._trees[commit] = self.history.tree(commit)
        return self._trees[commit]

    def revision(self, revision: str) -> dict:
        """Return a revision's details and what it changed against the revision before it."""
        commit = self.commit(revision)
        before = self.history.parent(commit.id)
        head = self.history.head()
        return {
            "revision": self.row(commit),
            "newest": commit.id == head,
            "head": head,
            "before": before,
            "diff": diff(self.tree(before), self.tree(commit.id)),
        }

    def compare(self, older: str, newer: str) -> dict:
        """Return the diff from one revision to another, in that direction."""
        start, end = self.commit(older), self.commit(newer)
        return {
            "from": self.row(start),
            "to": self.row(end),
            "diff": diff(self.tree(start.id), self.tree(end.id)),
        }

    def files(self, revision: str, file: str | None = None) -> dict:
        """Return a revision's details and the text of each of its files then, or of the one file named."""
        commit = self.commit(revision)
        tree = self.tree(commit.id)
        if file is not None and file not in tree:
            raise Unknown(f"There is no file {file} in revision {commit.short}.")
        chosen = {file: tree[file]} if file is not None else tree
        return {"revision": self.row(commit), "files": {path: _text(data) for path, data in chosen.items()}}

    # Reverting

    def preview(self, revision: str) -> dict:
        """Return what reverting to a revision would change from the newest revision, and the renames it crosses."""
        commit = self.commit(revision)
        head = self.history.head()
        newest = self.tree(head)
        target = self.tree(commit.id)
        changes = diff(_without_mcp(newest), _without_mcp(target))
        return {
            "revision": self.row(commit),
            "head": head,
            "newest": commit.id == head,
            "diff": changes,
            "nothing": not changes,
            "renames": self.renames(commit.id, head),
            "mcp": MCP_KEPT,
        }

    def renames(self, older: str, newer: str | None) -> list[str]:
        """Return a sentence for each rename made in the portal after ``older``, up to ``newer``."""
        if newer is None or older == newer:
            return []
        found = []
        for subject in self.history.subjects(older, newer):
            rest = _STAMP.sub("", subject, count=1)
            _who, colon, done = rest.partition(": ")
            matched = _RENAMED.match(done if colon else rest)
            if matched is None:
                continue
            kind, old, new = matched["kind"], matched["old"], matched["new"]
            if kind == "task":
                old, new = old.split("/", 1)[-1], new.split("/", 1)[-1]
            sentence = f"{kind[0].upper()}{kind[1:]} {old} was renamed to {new} after this version."
            if kind in _KEPT_UNDER:
                sentence += " " + _KEPT_UNDER[kind].format(new=new)
            found.append(sentence)
        return found

    def revert(self, revision: str, username: str, *, expected: str | None = None) -> Answer:
        """Put every file back as it was at ``revision``, except mcp.yaml, as one new commit.

        ``expected`` is the newest revision the portal's dialog was opened on.
        When something was committed since, nothing is written.
        """
        if not self.kept:
            return Answer(404, {"error": NO_HISTORY})
        try:
            commit = self.commit(revision)
        except Unknown as error:
            return Answer(404, {"error": str(error)})
        head = self.history.head()
        if expected is not None and expected != head:
            return Answer(409, {"error": CHANGED_MEANWHILE, "stale": True})
        if commit.id == head:
            return Answer(400, {"error": NEWEST})
        mcp = self.tasks.policy_file.with_name(mcp_settings.FILE_NAME).name
        target = _without_mcp(self.tree(commit.id), mcp)
        try:
            hand = self.history.changed()
        except HistoryError:
            hand = []
        present = (set(self.tree(head)) | set(hand)) - {mcp}
        writes: dict[Path, bytes] = {}
        for relative, data in target.items():
            path = self.directory / relative
            if _read(path) != data:
                writes[path] = data
        removes = [self.directory / relative for relative in sorted(present - set(target)) if (self.directory / relative).is_file()]
        if not writes and not removes:
            return Answer(200, {"message": NOTHING, "nothing": True, "warnings": []})
        renames = self.renames(commit.id, head)
        label = f"{commit.short} ({self.when(commit)})"
        steps = [_write_step(path, data) for path, data in writes.items()] + [_remove_step(path) for path in removes]
        answer = self.tasks.change(
            None,
            {path: _text(data) for path, data in writes.items()},
            [],
            steps,
            username,
            confirmed=True,
            moved=None,
            failed="",
            done=f"Reverted to {label}.",
            commit=f"reverted to {label}",
            paths=[*writes, *removes],
            removed=removes,
            check=lambda: self._staged_check(target, mcp),
        )
        answer.body["renames"] = renames
        if answer.body.get("dry_run"):
            before = {str(path.relative_to(self.directory)): _read(path) for path in [*writes, *removes]}
            after = {str(path.relative_to(self.directory)): data for path, data in writes.items()}
            answer.body["diff"] = diff({path: data for path, data in before.items() if data is not None}, after)
        return answer

    def _staged_check(self, target: Mapping[str, bytes], mcp: str) -> Answer | None:
        """Check the reverted files in a staging copy of the config directory, as ``dw check`` would load them."""
        with tempfile.TemporaryDirectory(prefix="daywarden-revert-") as staging:
            root = Path(staging)
            for relative, data in target.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            current = self.directory / mcp
            if current.is_file():
                shutil.copyfile(current, root / mcp)
            policy = root / self.tasks.policy_file.name
            try:
                if not policy.is_file():
                    raise ConfigError(f"{policy}: the policy file does not exist")
                load_required(policy, self.tasks.policy(), warn=lambda _message: None)
            except ConfigError as error:
                shown = [problem.replace(str(root), str(self.directory)) for problem in error.problems]
                return Answer(400, {"error": REFUSED, "errors": shown})
        return None


def what(subject: str, author: str) -> str:
    """Return a commit message without its leading time and ``<user>: ``, such as ``via Claude Code: saved task x``.

    A message in any other form is returned whole.
    """
    stamp = _STAMP.match(subject)
    if stamp is None:
        return subject
    rest = subject[stamp.end() :]
    if author and rest.startswith(author + ": "):
        return rest[len(author) + 2 :]
    if author and rest.startswith(author + " via "):
        return rest[len(author) + 1 :]
    if ": " not in rest:
        return rest
    return subject


def diff(before: Mapping[str, bytes], after: Mapping[str, bytes]) -> list[dict]:
    """Return each file that differs between two sets of files, in path order, with its changed parts and three lines of context."""
    found = []
    for path in sorted(set(before) | set(after)):
        old, new = before.get(path), after.get(path)
        if old == new:
            continue
        status = ADDED if old is None else REMOVED if new is None else CHANGED
        found.append(file_diff(path, status, old or b"", new or b""))
    return found


def file_diff(path: str, status: str, old: bytes, new: bytes) -> dict:
    """Return one file's diff: its hunks of lines, each marked ``+``, ``-``, or `` ``, and its unified diff text."""
    try:
        old_text, new_text = old.decode("utf-8"), new.decode("utf-8")
    except UnicodeDecodeError:
        return {"path": path, "status": status, "binary": True, "hunks": [], "unified": f"Binary file {path} differs\n"}
    lines = list(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile="/dev/null" if status == ADDED else f"a/{path}",
            tofile="/dev/null" if status == REMOVED else f"b/{path}",
            n=CONTEXT_LINES,
        )
    )
    hunks: list[dict] = []
    old_line = new_line = 0
    for line in lines[2:]:
        if line.startswith("@@"):
            numbers = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            old_line, new_line = (int(numbers[1]), int(numbers[2])) if numbers else (0, 0)
            hunks.append({"header": line.rstrip("\n"), "lines": []})
            continue
        kind, text = line[0], line[1:].rstrip("\n")
        entry = {"kind": kind, "text": text, "old": None, "new": None}
        if kind in " -":
            entry["old"] = old_line
            old_line += 1
        if kind in " +":
            entry["new"] = new_line
            new_line += 1
        hunks[-1]["lines"].append(entry)
    unified = "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines)
    return {"path": path, "status": status, "binary": False, "hunks": hunks, "unified": unified}


def _without_mcp(files: Mapping[str, bytes], mcp: str = mcp_settings.FILE_NAME) -> dict[str, bytes]:
    return {path: data for path, data in files.items() if path != mcp}


def _text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def put_bytes(path: Path, data: bytes) -> None:
    """Write a file in one step. It keeps the owner and mode of the file it replaces, or takes the owner of its directory."""
    make_directory(path.parent)
    try:
        status = path.stat()
        mode = stat.S_IMODE(status.st_mode)
    except FileNotFoundError:
        status, mode = path.parent.stat(), 0o644
    temporary = path.with_name(f".{path.name}.{os.getpid()}.reverting")
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        own_like(temporary, status)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _write_step(path: Path, data: bytes) -> Step:
    before = _read(path)
    return Step(
        lambda: put_bytes(path, data),
        (lambda: put_bytes(path, before)) if before is not None else (lambda: path.unlink(missing_ok=True)),
        f"{path} could not be written, so nothing was reverted",
    )


def _remove_step(path: Path) -> Step:
    before = _read(path) or b""
    return Step(lambda: path.unlink(), lambda: put_bytes(path, before), f"{path} could not be removed, so nothing was reverted")


# The portal's data addresses


def _page_number(value: str | None) -> int:
    try:
        return max(1, int(value or "1"))
    except ValueError:
        return 1


def install_config_history(app: FastAPI, *, gate: PortalGate, history: ConfigHistory) -> None:
    """Add Config History's data addresses under /parent/api/settings/history. Each is admin-only."""

    def missing(error: str = NO_HISTORY) -> Response:
        return json_answer(404, {"error": error})

    @app.get("/parent/api/settings/history")
    async def history_list(request: Request) -> Response:
        _parent, refused = gate.parent(request)
        if refused is not None:
            return refused
        file = request.query_params.get("file") or None
        return json_answer(200, history.listing(_page_number(request.query_params.get("page")), file))

    @app.get("/parent/api/settings/history/compare")
    async def history_compare(request: Request) -> Response:
        _parent, refused = gate.parent(request)
        if refused is not None:
            return refused
        if not history.kept:
            return missing()
        start, end = request.query_params.get("from"), request.query_params.get("to")
        if not start or not end:
            return json_answer(400, {"error": "Choose a From and a To revision to compare."})
        try:
            return json_answer(200, history.compare(start, end))
        except Unknown as error:
            return missing(str(error))

    @app.get("/parent/api/settings/history/revisions/{revision}")
    async def history_revision(request: Request, revision: str) -> Response:
        _parent, refused = gate.parent(request)
        if refused is not None:
            return refused
        if not history.kept:
            return missing()
        try:
            return json_answer(200, history.revision(revision))
        except Unknown as error:
            return missing(str(error))

    @app.get("/parent/api/settings/history/revisions/{revision}/revert")
    async def history_preview(request: Request, revision: str) -> Response:
        _parent, refused = gate.parent(request)
        if refused is not None:
            return refused
        if not history.kept:
            return missing()
        try:
            return json_answer(200, history.preview(revision))
        except Unknown as error:
            return missing(str(error))

    @app.post("/parent/api/settings/history/revisions/{revision}/revert")
    async def history_revert(request: Request, revision: str) -> Response:
        body, parent, refused = await gate.acting_parent(request)
        if refused is not None or parent is None:
            return refused
        expected = body.get("head")
        if not isinstance(expected, str) or not expected:
            return json_answer(400, {"error": "Send the newest revision the dialog was opened on, as head."})
        answer = history.revert(revision, parent.username, expected=expected)
        return json_answer(answer.status, answer.body)

