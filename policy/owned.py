"""Files the decisions service writes into the host's config and data directories.

The decisions service runs as root in its container. Every file and
directory it writes keeps the owner of what it replaces, or takes the owner
of the directory it is made in, so the host user can still edit, move, and
commit them without sudo.
"""

from __future__ import annotations

import os
from pathlib import Path


def make_directory(directory: Path) -> None:
    """Create a directory and any missing parents, each owned like the directory it is made in."""
    if directory.is_dir():
        return
    make_directory(directory.parent)
    directory.mkdir()
    own_like(directory, directory.parent.stat())


def own_like(path: Path, status: os.stat_result) -> None:
    """Give a path the owner in ``status``, when running as root and that owner is not root."""
    if os.geteuid() == 0 and (status.st_uid, status.st_gid) != (0, 0):
        os.chown(path, status.st_uid, status.st_gid)
