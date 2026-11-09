"""S007.4: the parent portal's own tests, run with Vitest, and its type check.

make test installs the portal's npm packages first when Node is installed.
Without Node these are skipped and the Python tests still run.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

PORTAL = Path(__file__).resolve().parents[1] / "policy" / "portal"
BIN = PORTAL / "node_modules" / ".bin"

pytestmark = [
    pytest.mark.skipif(shutil.which("node") is None, reason="needs node to run the portal tests"),
    pytest.mark.skipif(not BIN.is_dir(), reason="the portal's npm packages are not installed; run make portal-deps"),
]


def _run(*command: str) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=PORTAL, capture_output=True, text=True, timeout=600, check=False)


def test_the_portal_tests_pass():
    done = _run(str(BIN / "vitest"), "run")
    assert done.returncode == 0, done.stdout[-6000:] + done.stderr[-3000:]


def test_the_portal_type_checks():
    done = _run(str(BIN / "tsc"), "--noEmit")
    assert done.returncode == 0, done.stdout[-6000:] + done.stderr[-3000:]
