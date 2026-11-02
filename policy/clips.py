"""Cut one spoken recording into separately named spelling clips.

The library half loads a recording, finds the stretches of speech in it,
cuts each one with faded guards, checks a clip name with the S005.1 rules,
and writes Ogg Opus clips. It never prompts, prints, or reads the terminal,
so a web page can drive it with the same defaults.

The command line half runs on the machine running Compose and asks for each
clip's name:

    bin/cut-clips take.m4a --out ~/daywarden/spelling/alphabet

It needs ffmpeg built with libopus, and pydub with audioop-lts from
``policy/requirements.txt``. The policy service does not import this module.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import warnings
from array import array
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from policy.sounds import MEDIA_TYPES
from policy.spelling import parse_clip_name, pool_problems

with warnings.catch_warnings():
    warnings.simplefilter("ignore", RuntimeWarning)
    try:
        from pydub import AudioSegment
    except ImportError:
        AudioSegment = None

RATE = 48_000
WIDTH = 2
FRAME_MS = 10
GUARD_MS = 100
MIN_SILENCE_MS = 700
SHORTEST_SILENCE_MS = 200
THRESHOLD_DB = 35.0
MIN_SPEECH_MS = 150
BITRATE = "32k"
EXTENSION = ".opus"
INSTALL = "pip install -r policy/requirements.txt"

_DEMUXERS = {
    "opus": "ogg",
    "oga": "ogg",
    "weba": "webm",
    "m4a": "mov",
    "mp4": "mov",
    "x-m4a": "mov",
    "mpeg": "mp3",
    "x-wav": "wav",
    "wave": "wav",
}
_BITRATE = re.compile(r"^[1-9][0-9]*k?$")


class ClipError(ValueError):
    """A recording could not be read, or a clip could not be written."""


class MissingTool(RuntimeError):
    """ffmpeg, libopus, or pydub is not installed."""


@dataclass(frozen=True)
class Span:
    """One stretch of speech in a recording, in milliseconds from its start."""

    start: int
    end: int

    @property
    def ms(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class Found:
    """The stretches of speech in a recording, and how many shorter sounds were ignored."""

    spans: tuple[Span, ...]
    ignored: int


def require_tools() -> None:
    """Raise ``MissingTool`` unless pydub and an ffmpeg that can encode libopus are installed."""
    if AudioSegment is None:
        raise MissingTool(f"pydub and audioop-lts are not installed: {INSTALL}")
    if shutil.which("ffmpeg") is None:
        raise MissingTool("ffmpeg is not on the PATH. Install ffmpeg built with libopus")
    try:
        listed = subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise MissingTool(f"ffmpeg did not run: {exc}") from exc
    if not re.search(r"^\s*A\S*\s+libopus\s", listed, re.MULTILINE):
        raise MissingTool("this ffmpeg cannot encode Opus. Install an ffmpeg built with libopus")


def load_recording(source: str | os.PathLike | bytes, format: str | None = None) -> AudioSegment:
    """Decode a recording from a file path or from bytes into mono, 48 kHz, 16-bit audio.

    ``format`` is an optional hint such as ``webm``, ``ogg``, or a MIME type
    like ``audio/webm;codecs=opus``. Without it, ffmpeg works the format out.
    """
    if isinstance(source, (bytes, bytearray, memoryview)):
        with tempfile.NamedTemporaryFile(prefix="daywarden-recording-") as handle:
            handle.write(source)
            handle.flush()
            return _decode(Path(handle.name), format, "the recording")
    path = Path(source)
    if not path.is_file():
        raise ClipError(f"{path}: no such file")
    return _decode(path, format, str(path))


def find_clips(
    audio: AudioSegment,
    *,
    min_silence: int = MIN_SILENCE_MS,
    threshold: float = THRESHOLD_DB,
    min_speech: int = MIN_SPEECH_MS,
) -> Found:
    """Return the stretches of speech in a recording.

    The recording is measured in 10 ms frames. A frame is sound when its RMS
    level is above ``threshold`` decibels below the loudest sample. Sound
    frames separated by less than ``min_silence`` ms belong to one stretch,
    and a stretch shorter than ``min_speech`` ms is counted as ignored.
    """
    if min_silence < SHORTEST_SILENCE_MS:
        raise ValueError(f"min_silence must be at least {SHORTEST_SILENCE_MS} ms")
    audio = _normal(audio)
    length = len(audio)
    peak = audio.max
    if peak == 0:
        return Found((), 0)
    floor = peak * 10 ** (-threshold / 20)
    stretches: list[list[int]] = []
    for start in range(0, length, FRAME_MS):
        end = min(start + FRAME_MS, length)
        if audio[start:end].rms <= floor:
            continue
        if stretches and start - stretches[-1][1] < min_silence:
            stretches[-1][1] = end
        else:
            stretches.append([start, end])
    kept = tuple(Span(start, end) for start, end in stretches if end - start >= min_speech)
    return Found(kept, len(stretches) - len(kept))


def cut_clip(audio: AudioSegment, span: Span, guard: int = GUARD_MS) -> AudioSegment:
    """Return a guard, the speech, and another guard, with the guards faded from and to zero.

    The guards come from the recording either side of the speech, padded with
    digital silence where the recording runs out, so each is ``guard`` ms long.
    """
    audio = _normal(audio)
    before = max(0, span.start - guard)
    after = min(len(audio), span.end + guard)
    lead = _silence(guard - (span.start - before)) + audio[before : span.start]
    tail = audio[span.end : after] + _silence(guard - (after - span.end))
    return _fade(lead, rising=True) + audio[span.start : span.end] + _fade(tail, rising=False)


def check_name(name: str) -> tuple[str, str, bool]:
    """Return the entry key, the spelling, and whether a clip name is a sentence clip.

    The name is the file name without ``.opus``. A name the S005.1 pool rules
    would refuse raises ``ValueError`` saying why.
    """
    if not name:
        raise ValueError("a clip needs a name")
    if Path(name).suffix.lower() in MEDIA_TYPES:
        raise ValueError(f"{name}: leave off the extension. Clips are written as <name>{EXTENSION}")
    parsed = parse_clip_name(name + EXTENSION, None)
    assert parsed is not None
    return parsed


def existing_clips(directory: str | os.PathLike, name: str) -> list[Path]:
    """Return the audio files in a directory that are already the clip for this name's entry.

    Case and extension are ignored, so ``Rope.mp3`` is returned for ``rope``.
    ``<name>.opus`` itself, when it exists, comes first.
    """
    key, _, sentence = check_name(name)
    try:
        with os.scandir(directory) as listing:
            children = [child for child in listing if not child.name.startswith(".") and child.is_file()]
    except FileNotFoundError:
        return []
    found = []
    for child in children:
        try:
            parsed = parse_clip_name(child.name, None)
        except ValueError:
            continue
        if parsed is not None and parsed[0].lower() == key.lower() and parsed[2] == sentence:
            found.append(Path(child.path))
    target = name + EXTENSION
    return sorted(found, key=lambda path: (path.name != target, path.name))


def write_clip(
    clip: AudioSegment,
    directory: str | os.PathLike,
    name: str,
    *,
    bitrate: str = BITRATE,
    replace: Iterable[str | os.PathLike] = (),
) -> Path:
    """Encode a clip as ``<name>.opus`` in a directory, creating the directory if needed.

    The clip is written to a hidden file and renamed into place, so a scan
    of the directory never sees half a clip. The files in ``replace``, such
    as an older ``rope.mp3``, are removed once the new clip is in place.
    """
    check_name(name)
    if not _BITRATE.fullmatch(bitrate):
        raise ValueError(f"{bitrate}: a bitrate is a number of bits per second, such as 32k")
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (name + EXTENSION)
    temporary = folder / f".{name}{EXTENSION}.{secrets.token_hex(4)}.part"
    try:
        _ffmpeg(
            [
                "-f", "s16le", "-ar", str(RATE), "-ac", "1", "-i", "pipe:0",
                "-c:a", "libopus", "-b:a", bitrate, "-f", "opus", "-y", str(temporary),
            ],
            target.name,
            stdin=_normal(clip).raw_data,
        )
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    for old in map(Path, replace):
        if old.exists() and not old.samefile(target):
            old.unlink()
    return target


def _decode(path: Path, format: str | None, label: str) -> AudioSegment:
    hint = [] if format is None else ["-f", _demuxer(format)]
    raw = _ffmpeg(
        [
            "-nostdin", *hint, "-i", str(path), "-map", "0:a:0",
            "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1",
        ],
        label,
    )
    whole_ms = len(raw) - len(raw) % (RATE // 1000 * WIDTH)
    if whole_ms == 0:
        raise ClipError(f"{label}: has no audio")
    return _segment(raw[:whole_ms])


def _demuxer(hint: str) -> str:
    text = hint.split(";", 1)[0].strip().lower().lstrip(".")
    text = text.removeprefix("audio/").removeprefix("video/")
    return _DEMUXERS.get(text, text)


def _ffmpeg(arguments: Sequence[str], label: str, *, stdin: bytes | None = None) -> bytes:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", *arguments]
    try:
        done = subprocess.run(command, input=stdin, capture_output=True)
    except OSError as exc:
        raise MissingTool(f"ffmpeg did not run: {exc}") from exc
    if done.returncode != 0:
        lines = done.stderr.decode(errors="replace").strip().splitlines()
        raise ClipError(f"{label}: ffmpeg failed: {lines[-1] if lines else f'exit status {done.returncode}'}")
    return done.stdout


def _pydub() -> type:
    if AudioSegment is None:
        raise MissingTool(f"pydub and audioop-lts are not installed: {INSTALL}")
    return AudioSegment


def _segment(raw: bytes) -> AudioSegment:
    return _pydub()(data=raw, sample_width=WIDTH, frame_rate=RATE, channels=1)


def _normal(audio: AudioSegment) -> AudioSegment:
    return audio.set_channels(1).set_sample_width(WIDTH).set_frame_rate(RATE)


def _silence(ms: int) -> AudioSegment:
    return _segment(b"\0" * (RATE // 1000 * WIDTH * ms))


def _fade(audio: AudioSegment, *, rising: bool) -> AudioSegment:
    """Scale the samples linearly so the first (rising) or last (falling) is exactly zero."""
    samples = array("h", audio.raw_data)
    if sys.byteorder == "big":
        samples.byteswap()
    last = len(samples) - 1
    for index in range(len(samples)):
        step = index if rising else last - index
        samples[index] = int(samples[index] * step / last) if last else 0
    if sys.byteorder == "big":
        samples.byteswap()
    return audio._spawn(samples.tobytes())


# Command line


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Cut a recording and ask for each clip's name. Return the exit status."""
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    stdin, out, err = stdin or sys.stdin, out or sys.stdout, err or sys.stderr
    try:
        require_tools()
        if args.play and shutil.which("ffplay") is None:
            raise MissingTool("--play needs ffplay, which comes with ffmpeg, on the PATH")
    except MissingTool as exc:
        print(f"cut-clips: {exc}", file=err)
        return 1
    try:
        audio = load_recording(args.recording)
        found = find_clips(audio, min_silence=args.min_silence, threshold=args.threshold, min_speech=args.min_speech)
    except ClipError as exc:
        print(f"cut-clips: {exc}", file=err)
        return 1
    except KeyboardInterrupt:
        print("\nStopped. Nothing was written.", file=out)
        return 130
    if args.list:
        _list(found, out)
        return 0
    return _name_clips(audio, found, args, stdin, out, err)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cut-clips",
        description=(
            "Cut one recording into spelling clips at the pauses between items, and ask for each clip's "
            "name. Each name writes <name>.opus. An empty name skips the clip. With --play, ? plays it again."
        ),
    )
    parser.add_argument("recording", help="the recording to cut, in any format ffmpeg reads")
    parser.add_argument("--out", type=Path, default=Path("."), metavar="DIR", help="where clips are written")
    parser.add_argument(
        "--min-silence",
        type=_at_least(SHORTEST_SILENCE_MS),
        default=MIN_SILENCE_MS,
        metavar="MS",
        help=f"a quiet stretch this long separates two clips (default {MIN_SILENCE_MS}, at least {SHORTEST_SILENCE_MS})",
    )
    parser.add_argument(
        "--threshold",
        type=_decibels,
        default=THRESHOLD_DB,
        metavar="DB",
        help=f"decibels below the loudest point that count as silence (default {THRESHOLD_DB:g})",
    )
    parser.add_argument(
        "--min-speech",
        type=_at_least(0),
        default=MIN_SPEECH_MS,
        metavar="MS",
        help=f"shorter sounds are ignored as noise (default {MIN_SPEECH_MS})",
    )
    parser.add_argument("--bitrate", type=_bitrate, default=BITRATE, metavar="RATE", help=f"Opus bitrate (default {BITRATE})")
    parser.add_argument("--play", action="store_true", help="play each clip with ffplay before asking for its name")
    parser.add_argument("--list", action="store_true", help="list the clips found and write nothing")
    return parser


def _at_least(smallest: int):
    def parse(text: str) -> int:
        try:
            value = int(text)
        except ValueError:
            value = smallest - 1
        if value < smallest:
            raise argparse.ArgumentTypeError(f"{text!r} is not a whole number of milliseconds, {smallest} or more")
        return value

    return parse


def _decibels(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        value = 0.0
    if not 0 < value < 200:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number of decibels above 0")
    return value


def _bitrate(text: str) -> str:
    if not _BITRATE.fullmatch(text):
        raise argparse.ArgumentTypeError(f"{text!r} is not a bitrate such as 32k")
    return text


def _list(found: Found, out: TextIO) -> None:
    for number, span in enumerate(found.spans, 1):
        print(f"{number:>3}  at {_clock(span.start)}  ({_seconds(span.ms)})", file=out)
    print(f"{_count(len(found.spans), 'clip')} found, {_count(found.ignored, 'short sound')} ignored", file=out)


def _name_clips(audio: AudioSegment, found: Found, args: argparse.Namespace, stdin: TextIO, out: TextIO, err: TextIO) -> int:
    total = len(found.spans)
    ignored = f" ({_count(found.ignored, 'short sound')} ignored)" if found.ignored else ""
    print(f"Found {_count(total, 'clip')} in {args.recording}{ignored}.", file=out)
    if not total:
        print("Try a smaller --threshold or --min-speech, and check them with --list.", file=out)
        return 0
    written = skipped = 0
    status = 0
    try:
        for number, span in enumerate(found.spans, 1):
            clip = cut_clip(audio, span)
            if args.play:
                _play(clip, err)
            if _name_one(clip, f"Clip {number} of {total} at {_clock(span.start)} ({_seconds(span.ms)}): ", args, stdin, out, err):
                written += 1
            else:
                skipped += 1
    except KeyboardInterrupt:
        print("\nStopped.", file=out)
        status = 130
    except EOFError:
        print("\nStopped at the end of the input.", file=out)
        status = 1
    except (ClipError, OSError) as exc:
        print(f"cut-clips: {exc}", file=err)
        status = 1
    left = total - written - skipped
    summary = f"Wrote {_count(written, 'clip')}, skipped {skipped}"
    print(summary + (f", {left} not named." if left else "."), file=out)
    _warn(args.out, err)
    return status


def _name_one(clip: AudioSegment, prompt: str, args: argparse.Namespace, stdin: TextIO, out: TextIO, err: TextIO) -> bool:
    """Ask for a clip's name until it is written (True) or skipped (False)."""
    while True:
        name = _ask(prompt, stdin, out).strip()
        if not name:
            return False
        if name == "?":
            _play(clip, err)
            continue
        try:
            check_name(name)
        except ValueError as exc:
            print(f"  {exc}", file=out)
            continue
        existing = existing_clips(args.out, name)
        if all(_replace(path, name, stdin, out) for path in existing):
            write_clip(clip, args.out, name, bitrate=args.bitrate, replace=existing)
            return True


def _replace(path: Path, name: str, stdin: TextIO, out: TextIO) -> bool:
    if path.name == name + EXTENSION:
        question = f"Replace {path.name}? [y/N] "
    else:
        question = f"{path.name} is already the clip for {name}. Replace it? [y/N] "
    return _ask(question, stdin, out).strip().lower() in ("y", "yes")


def _ask(prompt: str, stdin: TextIO, out: TextIO) -> str:
    if stdin is sys.stdin and out is sys.stdout and stdin.isatty():
        return input(prompt)
    out.write(prompt)
    out.flush()
    line = stdin.readline()
    if not line:
        raise EOFError
    out.write("\n")
    return line.rstrip("\r\n")


def _play(clip: AudioSegment, err: TextIO) -> None:
    if shutil.which("ffplay") is None:
        print("cut-clips: ffplay is not on the PATH, so the clip cannot be played", file=err)
        return
    wav = io.BytesIO()
    clip.export(wav, format="wav")
    subprocess.run(
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-i", "pipe:0"],
        input=wav.getvalue(),
        check=False,
    )


def _warn(directory: Path, err: TextIO) -> None:
    if not directory.is_dir():
        return
    try:
        problems = pool_problems(directory, str(directory))
    except OSError as exc:
        problems = [f"{directory}: {exc}"]
    for problem in problems:
        print(f"warning: {problem}", file=err)


def _clock(ms: int) -> str:
    minutes, rest = divmod(ms, 60_000)
    return f"{minutes}:{rest / 1000:05.2f}"


def _seconds(ms: int) -> str:
    return f"{ms / 1000:.2f} s"


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" + ("" if number == 1 else "s")


if __name__ == "__main__":
    sys.exit(main())
