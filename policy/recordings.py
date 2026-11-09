"""Recordings made in the parent portal: uploaded takes and the pending clips cut from them.

The browser records a take with MediaRecorder and uploads it once, as Opus in
WebM or Ogg. The take is kept in a hidden directory under the data
directory, ``.recordings/<take>/take.webm`` or ``take.ogg``, so the pool
scans never see it and keeping a clip is a rename on the same file system.

Cutting a take uses the same library and defaults as ``bin/cut-clips``:
loudness normalization, finding the clips, faded guards, and Ogg Opus. The
clips are written beside the take as ``<cut>-<n>.opus``, where ``<cut>`` is
new for every cut, and each cut replaces the clips of the one before. So a
take can be cut again with other settings without uploading it again.

Nothing in a pool changes here. ``TaskAdmin.keep`` renames a kept clip into
its word's pool. A take left behind, because the parent closed the page, is
removed with its clips once it is a day old, when the service starts and
whenever another take is uploaded.
"""

from __future__ import annotations

import math
import os
import re
import secrets
import shutil
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from policy import clips, spelling
from policy.owned import make_directory, own_like

DIRECTORY = ".recordings"
LONGEST_TAKE_BYTES = 20 * 1024 * 1024
KEEP_SECONDS = 24 * 60 * 60
# The media types a take may be uploaded as, and the file extension each is kept with.
TAKE_TYPES = {"audio/webm": "webm", "audio/ogg": "ogg"}
FIELDS = ("min_silence", "threshold", "min_speech", "guard", "loudness")
TOO_LONG = "The recording is too long to upload. Record a shorter take."
GONE = "That recording is no longer on the service. Record it again."
_TAKE = re.compile(r"^[A-Za-z0-9_-]{16}$")
_CLIP = re.compile(r"^[0-9a-f]{6}-[1-9][0-9]*$")


class RecordingError(Exception):
    """A request about a recording that is refused, with the HTTP status to answer."""

    def __init__(self, status: int, message: str, errors: Mapping[str, str] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.errors = dict(errors or {})


@dataclass(frozen=True)
class CutSettings:
    """The Advanced settings of a cut, at the ``bin/cut-clips`` defaults."""

    min_silence: int = clips.MIN_SILENCE_MS
    threshold: float = clips.THRESHOLD_DB
    min_speech: int = clips.MIN_SPEECH_MS
    guard: int = clips.GUARD_MS
    loudness: float = clips.LOUDNESS_LUFS


def take_type(content_type: str) -> str | None:
    """Return the extension a take of this Content-Type is kept with, or None when it is not a take."""
    kind = content_type.split(";", 1)[0].strip().lower()
    return TAKE_TYPES.get(kind)


def cut_settings(values: object) -> CutSettings:
    """Check the Advanced settings sent with a cut. A missing field takes its default.

    Every problem is raised together, each under its field's name, with the
    same limits as the ``bin/cut-clips`` options.
    """
    if values is None:
        return CutSettings()
    if not isinstance(values, Mapping):
        raise RecordingError(400, "The settings must map each field to its value.")
    errors: dict[str, str] = {}
    found: dict[str, float] = {}
    rules = {
        "min_silence": (True, lambda value: value >= clips.SHORTEST_SILENCE_MS,
                        f"Minimum silence is a whole number of milliseconds, {clips.SHORTEST_SILENCE_MS} or more."),
        "threshold": (False, lambda value: 0 < value < 200, "Threshold is a number of decibels above 0 and below 200."),
        "min_speech": (True, lambda value: value >= 0, "Minimum speech is a whole number of milliseconds, 0 or more."),
        "guard": (True, lambda value: value >= clips.SHORTEST_GUARD_MS,
                  f"Guard is a whole number of milliseconds, {clips.SHORTEST_GUARD_MS} or more."),
        "loudness": (False, lambda value: clips.QUIETEST_LUFS <= value <= clips.LOUDEST_LUFS,
                     f"Loudness is from {clips.QUIETEST_LUFS:g} to {clips.LOUDEST_LUFS:g} LUFS."),
    }
    for key in sorted(set(values) - set(FIELDS)):
        errors[key] = f"{key} is not a setting of a cut."
    for key, (whole, allowed, message) in rules.items():
        if key not in values:
            continue
        value = _number(values[key], whole)
        if value is None or not allowed(value):
            errors[key] = message
        else:
            found[key] = value
    if errors:
        raise RecordingError(400, "Some of the Advanced settings are not allowed, so nothing was cut.", errors)
    return CutSettings(**{key: int(value) if rules[key][0] else float(value) for key, value in found.items()})


def _number(value: object, whole: bool) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip().replace("\u2212", "-")
        try:
            value = int(text) if whole else float(text)
        except ValueError:
            return None
    if isinstance(value, float) and whole:
        return value if value.is_integer() else None
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value


class Recordings:
    """The takes uploaded from the portal, and the clips of each one's latest cut."""

    def __init__(self, data_root: Callable[[], Path] = spelling.data_root, clock: Callable[[], float] = time.time) -> None:
        self.data_root = data_root
        self.clock = clock
        self._lock = threading.Lock()

    @property
    def root(self) -> Path:
        return self.data_root() / DIRECTORY

    def store(self, body: bytes, extension: str) -> str:
        """Keep an uploaded take and return its id. Takes older than a day are removed first."""
        if extension not in TAKE_TYPES.values():
            raise RecordingError(415, "Send a recording as audio/webm or audio/ogg.")
        if len(body) > LONGEST_TAKE_BYTES:
            raise RecordingError(413, TOO_LONG)
        if not body:
            raise RecordingError(400, "The recording is empty.")
        self.clean()
        make_directory(self.root)
        take = secrets.token_urlsafe(12)
        folder = self.root / take
        folder.mkdir()
        own_like(folder, self.root.stat())
        temporary = folder / f".take.{extension}.part"
        temporary.write_bytes(body)
        own_like(temporary, self.root.stat())
        os.replace(temporary, folder / f"take.{extension}")
        return take

    def cut(self, take: str, settings: CutSettings) -> dict:
        """Cut a take with these settings, replacing the clips of its last cut, and describe the clips."""
        folder = self._folder(take)
        recording = next((path for path in folder.glob("take.*") if path.suffix[1:] in TAKE_TYPES.values()), None)
        if recording is None:
            raise RecordingError(404, GONE)
        with self._lock:
            try:
                audio = clips.load_recording(recording, format=recording.suffix[1:])
                normalized = clips.normalize(audio, settings.loudness)
                found = clips.find_clips(
                    normalized.audio,
                    min_silence=settings.min_silence,
                    threshold=settings.threshold,
                    min_speech=settings.min_speech,
                )
                for old in folder.glob("*.opus"):
                    old.unlink()
                mark = secrets.token_hex(3)
                cut = []
                for number, span in enumerate(found.spans, 1):
                    ident = f"{mark}-{number}"
                    path = clips.encode_clip(clips.cut_clip(normalized.audio, span, settings.guard), folder / f"{ident}.opus")
                    own_like(path, folder.stat())
                    cut.append({"id": ident, "start": span.start, "ms": span.ms})
                os.utime(folder)
            except clips.MissingTool as error:
                raise RecordingError(500, f"The service cannot cut recordings: {error}") from error
            except clips.ClipError as error:
                raise RecordingError(400, f"The recording could not be cut: {error}") from error
            except OSError as error:
                raise RecordingError(404, GONE) from error
        return {"take": take, "clips": cut, "ignored": found.ignored, "loudness": clips.loudness_line(normalized)}

    def clip(self, take: str, clip: str) -> Path | None:
        """Return one clip of a take's latest cut, or None."""
        if not _TAKE.fullmatch(take) or not _CLIP.fullmatch(clip):
            return None
        path = self.root / take / f"{clip}.opus"
        return path if path.is_file() else None

    def discard(self, take: str) -> None:
        """Throw a take away with its clips. A take that is already gone is not an error."""
        if _TAKE.fullmatch(take):
            shutil.rmtree(self.root / take, ignore_errors=True)

    def clean(self) -> None:
        """Remove every take, with its clips, that has not been uploaded or cut for a day."""
        try:
            children = list(os.scandir(self.root))
        except OSError:
            return
        oldest = self.clock() - KEEP_SECONDS
        for child in children:
            try:
                if child.stat(follow_symlinks=False).st_mtime >= oldest:
                    continue
                if child.is_dir(follow_symlinks=False):
                    shutil.rmtree(child.path)
                else:
                    os.unlink(child.path)
            except OSError as error:
                print(f"could not remove the old recording {child.path}: {error}", flush=True)

    def _folder(self, take: object) -> Path:
        if not isinstance(take, str) or not _TAKE.fullmatch(take) or not (self.root / take).is_dir():
            raise RecordingError(404, GONE)
        return self.root / take
