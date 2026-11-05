"""Shared test setup.

Many tests use a ``type: spelling`` task with no body as a stand-in task.
A spelling body is checked against its word and letter directories when
the policy loads, so the whole session gets a data directory with one
current word and the alphabet.
It is set before any fixture runs, so the Docker Compose stacks mount it
instead of the household's own directory.
"""

import wave
from pathlib import Path

import pytest


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
