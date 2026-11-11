"""Shared test setup.

Many tests use a spelling task with no body as a stand-in task.
A spelling body is checked against its word and letter directories when
the policy loads, so the whole session gets a data directory with one
current word and the alphabet.
It is set before any fixture runs, so the Docker Compose stacks mount it
instead of the household's own directory.
"""

import json
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent / "page_harness.js"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node to run the page script")


def run_page(page: str, replies: dict, **options) -> list[dict]:
    """Run a quiz page's script in ``page_harness.js`` and return the events it saw."""
    run = subprocess.run(
        ["node", str(HARNESS)],
        input=json.dumps({"html": page, "replies": replies, "clip_ms": 0, **options}),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(run.stdout)


def merge_task_types(text: str) -> str:
    """Return the body of a ``tasks:`` section with every block of one type merged into one.

    ``text`` is task types at an indent of two, each with its tasks under it,
    so tests can join the text of several tasks of the same type.
    """
    blocks: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.splitlines(keepends=True):
        if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":"):
            current = blocks.setdefault(line, [])
        elif current is not None:
            current.append(line)
        elif line.strip():
            raise ValueError(f"a task line comes before its type: {line!r}")
    return "".join(header + "".join(lines) for header, lines in blocks.items())


def write_wav(path: Path, milliseconds: int = 500, rate: int = 8000) -> Path:
    """Write a silent mono WAV file that plays for ``milliseconds``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(1)
        audio.setframerate(rate)
        audio.writeframes(b"\x80" * (rate * milliseconds // 1000))
    return path


def write_alphabet(directory: Path, milliseconds: int = 300) -> None:
    """Record every letter, ``dash``, and ``apostrophe`` as ``<name>.wav`` in ``directory``."""
    for name in [*"abcdefghijklmnopqrstuvwxyz", "dash", "apostrophe"]:
        write_wav(directory / f"{name}.wav", milliseconds)


@pytest.fixture(scope="session", autouse=True)
def default_data_dir(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("daywarden")
    write_wav(root / "spelling" / "current" / "cat.wav")
    write_alphabet(root / "spelling" / "alphabet")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DAYWARDEN_DATA_DIR", str(root))
        yield root
