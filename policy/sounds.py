"""Sound effects for quiz outcomes.

Each outcome has a directory under ``policy/static/sounds``. The audio files
in it are that outcome's set, and one is chosen at random every time the
outcome plays. Any other file, such as an attribution note, is not a sound.
The sets are read when the service starts, so a new file arrives with the
next image build.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

SOUND_DIR = Path(__file__).resolve().parent / "static" / "sounds"
SOUND_PATH = "/static/sounds/"
SETS = ("correct", "incorrect", "timeout")
MEDIA_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".m4a": "audio/mp4",
}


@dataclass(frozen=True)
class SoundSets:
    """The audio file names in each outcome's directory, sorted by name.

    With no ``root`` every set is empty and no outcome plays a sound.
    """

    root: Path | None = None
    files: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def choose(self, outcome: str, rng: random.Random | None = None) -> str | None:
        """Return the URL of one file from this outcome's set, or None when it is empty."""
        names = self.files.get(outcome, ())
        if not names:
            return None
        return url(outcome, (rng or random).choice(names))

    def urls(self) -> tuple[str, ...]:
        """Return every sound URL, so a page can fetch them before they play."""
        return tuple(url(outcome, name) for outcome in SETS for name in self.files.get(outcome, ()))

    def path(self, outcome: str, name: str) -> Path | None:
        """Return the file behind a sound URL, or None when it is not in that set."""
        if self.root is None or name not in self.files.get(outcome, ()):
            return None
        return self.root / outcome / name


def load_sounds(
    root: Path = SOUND_DIR,
    warn: Callable[[str], None] = lambda message: print(message, flush=True),
) -> SoundSets:
    """Read the three sets. An empty or missing set is a warning, not an error."""
    files: dict[str, tuple[str, ...]] = {}
    for outcome in SETS:
        directory = root / outcome
        try:
            children = list(directory.iterdir())
        except OSError:
            children = []
        names = tuple(
            sorted(
                child.name
                for child in children
                if child.is_file() and not child.name.startswith(".") and is_audio(child.name)
            )
        )
        if not names:
            warn(f"sound set {outcome} has no audio files in {directory}; that outcome plays no sound")
        files[outcome] = names
    return SoundSets(root, files)


def is_audio(name: str) -> bool:
    return Path(name).suffix.lower() in MEDIA_TYPES


def media_type(name: str) -> str:
    return MEDIA_TYPES[Path(name).suffix.lower()]


def url(outcome: str, name: str) -> str:
    return SOUND_PATH + outcome + "/" + quote(name, safe="")
