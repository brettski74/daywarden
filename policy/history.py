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
import shutil
import subprocess
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

LOCK_WAIT_SECONDS = 5.0
EMAIL_DOMAIN = "daywarden.invalid"


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

    def _wait_for_lock(self) -> None:
        lock = self.directory / ".git" / "index.lock"
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        while lock.exists() and time.monotonic() < deadline:
            time.sleep(0.1)

    def _git(self, arguments: list[str], author: str, when: datetime | None) -> str:
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
                capture_output=True,
                text=True,
                timeout=30,
                **_as_owner(self.directory / ".git"),
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise HistoryError(str(error)) from error
        if done.returncode != 0:
            raise HistoryError((done.stderr or done.stdout).strip() or f"git {arguments[0]} failed")
        return done.stdout


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
