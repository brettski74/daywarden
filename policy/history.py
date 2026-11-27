"""Commits to the config history from the decisions service.

S023.1 keeps the config directory in a local git repository, and ``dw``
commits each change it applies. A parent portal save commits here, the same
way: the user's global and system git config are ignored, nothing is
written to any git config, and the author and committer are set for each
command, as the parent's username at ``daywarden.invalid``. The commit time
is the household's.

The service runs as root in its container, so git runs as the owner of the
repository. Everything it writes in ``.git`` stays owned by the host user,
and git does not refuse a repository owned by someone else.

A config directory with no ``.git`` of its own, such as ``config/`` in a
clone of the daywarden repository, has no history here, and nothing is
committed.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

LOCK_WAIT_SECONDS = 5.0
EMAIL_DOMAIN = "daywarden.invalid"
# A revision as a page address or an agent names it: a short or full commit id.
_REVISION = re.compile(r"[0-9a-f]{4,40}\Z")
_RECORD, _FIELD = "\x1e", "\x1f"
_LOG_FORMAT = f"--format={_RECORD}%H{_FIELD}%h{_FIELD}%an{_FIELD}%at{_FIELD}%B{_FIELD}"


@dataclass(frozen=True)
class Commit:
    """One commit in the config history: its ids, author, time as seconds since the epoch, message, and the files it changed."""

    id: str
    short: str
    author: str
    at: int
    message: str
    files: tuple[str, ...]


class HistoryError(Exception):
    """git could not do what was asked. The message is git's own reason."""


def stamp(when: datetime) -> str:
    """Return a commit message's time, such as ``2026-11-08 21:15 -0500``."""
    return when.strftime("%Y-%m-%d %H:%M %z")


class History:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @property
    def kept(self) -> bool:
        """True when the config directory has a history of its own."""
        return (self.directory / ".git").exists()

    def changed(self) -> list[str]:
        """Return each file in the config directory that differs from the last commit."""
        listing = self._git(["status", "--porcelain", "-z", "--untracked-files=all"], "", None)
        names = []
        entries = listing.split("\0")
        index = 0
        while index < len(entries):
            entry = entries[index]
            index += 1
            if not entry:
                continue
            names.append(entry[3:])
            if entry[0] in "RC":
                index += 1
        return names

    def commit(self, message: str, author: str, when: datetime, paths: Sequence[str] | None = None) -> bool:
        """Commit ``paths``, or every change when it is None. Return False when there was nothing to commit."""
        self._wait_for_lock()
        self._git(["add", "--all", "--", *(paths or ["."])], author, when)
        try:
            self._git(["diff", "--cached", "--quiet"], author, when)
            return False
        except HistoryError:
            pass
        self._git(["commit", "--quiet", "-m", message], author, when)
        return True

    # Reading

    def head(self) -> str | None:
        """Return the newest commit's full id, or None when there is none."""
        return self.resolve("HEAD")

    def resolve(self, revision: str) -> str | None:
        """Return the full id of a commit named by a short or full id, or ``HEAD``, or None when there is no such commit."""
        name = revision.strip().lower() if revision != "HEAD" else revision
        if name != "HEAD" and not _REVISION.match(name):
            return None
        try:
            found = self._git(["rev-parse", "--verify", "--quiet", f"{name}^{{commit}}"], "", None).strip()
        except HistoryError:
            return None
        return found or None

    def log(self, start: str = "HEAD", *, skip: int = 0, limit: int | None = None, file: str | None = None) -> list[Commit]:
        """Return the commits from ``start`` back, newest first, each with every file it changed.

        With ``file``, only the commits that changed it, which may be a file since removed.
        """
        arguments = ["log", "-z", "--name-only", "--no-renames", "--full-diff", _LOG_FORMAT, f"--skip={skip}"]
        if limit is not None:
            arguments.append(f"--max-count={limit}")
        arguments += [start, "--"]
        if file:
            arguments.append(f":(literal){file}")
        return _commits(self._git(arguments, "", None))

    def count(self, file: str | None = None) -> int:
        """Return how many commits there are, or how many changed ``file``."""
        arguments = ["rev-list", "--count", "HEAD", "--"]
        if file:
            arguments.append(f":(literal){file}")
        return int(self._git(arguments, "", None).strip() or 0)

    def parent(self, commit: str) -> str | None:
        """Return a commit's first parent, or None for the first commit."""
        parents = self._git(["rev-list", "--parents", "-n", "1", commit], "", None).split()
        return parents[1] if len(parents) > 1 else None

    def subjects(self, older: str, newer: str) -> list[str]:
        """Return the first line of each commit after ``older`` up to ``newer``, oldest first."""
        listing = self._git(["log", "--reverse", "--format=%s", f"{older}..{newer}"], "", None)
        return listing.splitlines()

    def tree(self, commit: str) -> dict[str, bytes]:
        """Return every file in a commit, by its path in the config directory, with its contents."""
        listing = self._git(["ls-tree", "-r", "-z", "--full-tree", commit], "", None)
        blobs: list[tuple[str, str]] = []
        for entry in listing.split("\0"):
            if not entry:
                continue
            info, path = entry.split("\t", 1)
            _mode, kind, blob = info.split()
            if kind == "blob":
                blobs.append((path, blob))
        if not blobs:
            return {}
        out = self._run(["cat-file", "--batch"], "", None, ("\n".join(blob for _path, blob in blobs) + "\n").encode())
        files: dict[str, bytes] = {}
        at = 0
        for path, _blob in blobs:
            end = out.index(b"\n", at)
            size = int(out[at:end].split()[2])
            files[path] = out[end + 1 : end + 1 + size]
            at = end + 1 + size + 1
        return files

    def _wait_for_lock(self) -> None:
        lock = self.directory / ".git" / "index.lock"
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        while lock.exists() and time.monotonic() < deadline:
            time.sleep(0.1)

    def _git(self, arguments: list[str], author: str, when: datetime | None) -> str:
        return self._run(arguments, author, when).decode("utf-8", errors="replace")

    def _run(self, arguments: list[str], author: str, when: datetime | None, given: bytes | None = None) -> bytes:
        git = shutil.which("git")
        if git is None:
            raise HistoryError("git is not installed in the decisions service")
        name = author or "daywarden"
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.directory),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": f"{name}@{EMAIL_DOMAIN}",
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": f"{name}@{EMAIL_DOMAIN}",
        }
        if when is not None:
            env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when.isoformat(timespec="seconds")
        try:
            done = subprocess.run(
                [git, "-C", str(self.directory), "-c", "core.quotePath=false", *arguments],
                env=env,
                input=given,
                capture_output=True,
                timeout=30,
                **_as_owner(self.directory / ".git"),
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise HistoryError(str(error)) from error
        if done.returncode != 0:
            reason = (done.stderr or done.stdout).decode("utf-8", errors="replace").strip()
            raise HistoryError(reason or f"git {arguments[0]} failed")
        return done.stdout


def _commits(listing: str) -> list[Commit]:
    """Return the commits in ``git log -z --name-only`` output written with ``_LOG_FORMAT``."""
    found = []
    for record in listing.split(_RECORD):
        if not record:
            continue
        full, short, author, at, message, names = record.split(_FIELD, 5)
        files = tuple(name for name in names.strip("\0\n").split("\0") if name)
        found.append(Commit(full, short, author, int(at), message.strip(), files))
    return found


def _as_owner(path: Path) -> dict:
    """Return the subprocess arguments that run as the owner of ``path``, when this process is root."""
    if os.geteuid() != 0:
        return {}
    try:
        status = path.stat()
    except OSError:
        return {}
    if status.st_uid == 0:
        return {}
    return {"user": status.st_uid, "group": status.st_gid, "extra_groups": []}
