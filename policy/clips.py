"""Cut spoken recordings into separately named spelling clips.

The library half loads a recording, normalizes its loudness, finds the
stretches of speech in it, cuts each one with faded guards, checks a clip
name with the S005.1 rules, and writes Ogg Opus clips. It never prompts,
prints, or reads the terminal, so a web page can drive it with the same
defaults.

The command line half runs on the machine running Compose. It cuts each
recording given to it in turn, with the same settings, and asks for each
clip's name:

    bin/cut-clips take.m4a --out ~/daywarden/spelling/alphabet
    bin/cut-clips words-1.m4a words-2.m4a --out ~/daywarden/spelling/current

It needs ffmpeg built with libopus, and pydub with audioop-lts from
``policy/requirements.txt``. The policy service cuts the parent portal's
browser recordings with the library half, through ``policy.recordings``.
"""

from __future__ import annotations

import argparse
import io
import json
import math
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
SHORTEST_GUARD_MS = 10
MIN_SILENCE_MS = 700
SHORTEST_SILENCE_MS = 200
THRESHOLD_DB = 35.0
CONTRAST_DB = 15.0
MIN_SPEECH_MS = 150
LOUDNESS_LUFS = -18.0
QUIETEST_LUFS = -40.0
LOUDEST_LUFS = -10.0
PEAK_DB = -1.0
BITRATE = "32k"
EXTENSION = ".opus"
REPLACE_CHOICES = "[y]es/[N]o/[a]lways/ne[v]er"
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


@dataclass(frozen=True)
class Loudness:
    """EBU R128 integrated loudness in LUFS and true peak in dBTP.

    Both are ``-inf`` for silence. ``integrated`` is also ``-inf`` for audio
    shorter than the 400 ms that one loudness measurement needs.
    """

    integrated: float
    peak: float

    @property
    def measured(self) -> bool:
        return math.isfinite(self.integrated)


@dataclass(frozen=True)
class Normalized:
    """A recording after loudness normalization, with its loudness before and after."""

    audio: AudioSegment
    before: Loudness
    after: Loudness
    gain: float
    limited: bool


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


def measure_loudness(audio: AudioSegment) -> Loudness:
    """Return the perceived loudness of a recording, measured as EBU R128 by ffmpeg.

    A mono recording is measured as dual mono, as it sounds when played
    through both speakers, so it matches a stereo recording at the same level.
    """
    report = _ffmpeg(
        [
            "-nostdin", "-nostats", "-f", "s16le", "-ar", str(RATE), "-ac", "1", "-i", "pipe:0",
            "-af", "loudnorm=print_format=json:dual_mono=true", "-f", "null", "-",
        ],
        "the loudness measurement",
        stdin=_normal(audio).raw_data,
        log=True,
    ).decode(errors="replace")
    try:
        values = json.loads(report[report.rindex("{") : report.rindex("}") + 1])
        return Loudness(float(values["input_i"]), float(values["input_tp"]))
    except (ValueError, KeyError) as exc:
        raise ClipError(f"the loudness measurement: ffmpeg did not report it: {exc}") from exc


def normalize(audio: AudioSegment, target: float = LOUDNESS_LUFS, *, peak: float = PEAK_DB) -> Normalized:
    """Bring a whole recording to a perceived loudness of ``target`` LUFS.

    One gain is applied to the whole recording, so items keep their loudness
    relative to each other and the pauses stay as quiet relative to the
    speech. Where that gain would take a peak above ``peak`` dBFS, a limiter
    holds back just those peaks rather than lowering the gain. A recording
    too quiet or too short to measure is returned unchanged.
    """
    if not QUIETEST_LUFS <= target <= LOUDEST_LUFS:
        raise ValueError(f"target must be from {QUIETEST_LUFS:g} to {LOUDEST_LUFS:g} LUFS")
    audio = _normal(audio)
    before = measure_loudness(audio)
    if not before.measured:
        return Normalized(audio, before, before, 0.0, False)
    gain = target - before.integrated
    limited = before.peak + gain > peak
    chain = f"volume={gain:.4f}dB"
    if limited:
        chain += f",alimiter=limit={10 ** (peak / 20):.6f}:level=false:latency=true"
    raw = _ffmpeg(
        [
            "-nostdin", "-f", "s16le", "-ar", str(RATE), "-ac", "1", "-i", "pipe:0", "-af", chain,
            "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1",
        ],
        "the loudness normalization",
        stdin=audio.raw_data,
    )
    louder = _segment(raw[: len(audio.raw_data)])
    return Normalized(louder, before, measure_loudness(louder), gain, limited)


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

    A recording whose loudest frame is less than ``CONTRAST_DB`` above its
    quietest tenth of frames is only room noise, however loud, and has no
    clips.
    """
    if min_silence < SHORTEST_SILENCE_MS:
        raise ValueError(f"min_silence must be at least {SHORTEST_SILENCE_MS} ms")
    audio = _normal(audio)
    length = len(audio)
    peak = audio.max
    if peak == 0:
        return Found((), 0)
    floor = peak * 10 ** (-threshold / 20)
    frames = [(start, min(start + FRAME_MS, length)) for start in range(0, length, FRAME_MS)]
    levels = [audio[start:end].rms for start, end in frames]
    quiet = sorted(levels)[len(levels) // 10]
    if max(levels) < quiet * 10 ** (CONTRAST_DB / 20):
        return Found((), 0)
    stretches: list[list[int]] = []
    for (start, end), level in zip(frames, levels):
        if level <= floor:
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
    Each fade lasts the whole guard and never reaches into the speech.
    """
    if guard < SHORTEST_GUARD_MS:
        raise ValueError(f"guard must be at least {SHORTEST_GUARD_MS} ms")
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
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    target = encode_clip(clip, folder / (name + EXTENSION), bitrate=bitrate)
    for old in map(Path, replace):
        if old.exists() and not old.samefile(target):
            old.unlink()
    return target


def encode_clip(clip: AudioSegment, target: str | os.PathLike, *, bitrate: str = BITRATE) -> Path:
    """Encode a clip as Ogg Opus at ``target``, through a hidden file renamed into place. The name is not checked."""
    if not _BITRATE.fullmatch(bitrate):
        raise ValueError(f"{bitrate}: a bitrate is a number of bits per second, such as 32k")
    target = Path(target)
    temporary = target.with_name(f".{target.name}.{secrets.token_hex(4)}.part")
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


def _ffmpeg(arguments: Sequence[str], label: str, *, stdin: bytes | None = None, log: bool = False) -> bytes:
    """Run ffmpeg and return what it writes to stdout or, with ``log``, its informational log."""
    command = ["ffmpeg", "-hide_banner", "-loglevel", "info" if log else "error", *arguments]
    try:
        done = subprocess.run(command, input=stdin, capture_output=True)
    except OSError as exc:
        raise MissingTool(f"ffmpeg did not run: {exc}") from exc
    if done.returncode != 0:
        lines = done.stderr.decode(errors="replace").strip().splitlines()
        raise ClipError(f"{label}: ffmpeg failed: {lines[-1] if lines else f'exit status {done.returncode}'}")
    return done.stderr if log else done.stdout


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
    """Cut each recording in turn and ask for each clip's name. Return the exit status."""
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    stdin, out, err = stdin or sys.stdin, out or sys.stdout, err or sys.stderr
    try:
        require_tools()
        if args.play and shutil.which("ffplay") is None:
            raise MissingTool("--play needs ffplay, which comes with ffmpeg, on the PATH")
    except MissingTool as exc:
        print(f"cut-clips: {exc}", file=err)
        return 1
    missing = [path for path in args.recordings if not Path(path).is_file()]
    for path in missing:
        print(f"cut-clips: {path}: no such file", file=err)
    if missing:
        return 1
    args.replacing = None
    count = len(args.recordings)
    written = skipped = status = 0
    for number, recording in enumerate(args.recordings, 1):
        if count > 1:
            if number > 1:
                print(file=out)
            print(f"Recording {number} of {count}: {recording}", file=out)
        tally = _cut(recording, args, stdin, out, err)
        written, skipped, status = written + tally.written, skipped + tally.skipped, max(status, tally.status)
        if tally.stopped:
            if number < count:
                print(f"{_count(count - number, 'recording')} not cut.", file=out)
            break
    if args.list:
        return status
    if count > 1:
        print(f"\nAltogether: wrote {_count(written, 'clip')} from {_count(count, 'recording')}, skipped {skipped}.", file=out)
    _warn(args.out, err)
    return status


@dataclass(frozen=True)
class _Tally:
    written: int = 0
    skipped: int = 0
    status: int = 0
    stopped: bool = False


def _cut(recording: str, args: argparse.Namespace, stdin: TextIO, out: TextIO, err: TextIO) -> _Tally:
    """Normalize, find, and list or name the clips of one recording."""
    try:
        audio = load_recording(recording)
        if not args.no_normalize:
            normalized = normalize(audio, args.loudness)
            print(loudness_line(normalized), file=out)
            audio = normalized.audio
        found = find_clips(audio, min_silence=args.min_silence, threshold=args.threshold, min_speech=args.min_speech)
    except ClipError as exc:
        print(f"cut-clips: {exc}", file=err)
        return _Tally(status=1)
    except KeyboardInterrupt:
        print(f"\nStopped before any clip of {recording} was written.", file=out)
        return _Tally(status=130, stopped=True)
    if args.list:
        _list(found, out)
        return _Tally()
    return _name_clips(recording, audio, found, args, stdin, out, err)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cut-clips",
        description=(
            "Bring each recording to an even loudness, cut it into spelling clips at the pauses between items, "
            "and ask for each clip's name. Recordings are cut one after another with the same settings. "
            "Each name writes <name>.opus. An empty name skips the clip. With --play, ? plays it again."
        ),
    )
    parser.add_argument(
        "recordings", nargs="+", metavar="recording", help="a recording to cut, in any format ffmpeg reads"
    )
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
    parser.add_argument(
        "--guard",
        type=_at_least(SHORTEST_GUARD_MS),
        default=GUARD_MS,
        metavar="MS",
        help=(
            "recording kept either side of each clip's speech, faded in before it and out after it "
            f"(default {GUARD_MS}, at least {SHORTEST_GUARD_MS})"
        ),
    )
    parser.add_argument(
        "--loudness",
        type=_lufs,
        default=LOUDNESS_LUFS,
        metavar="LUFS",
        help=(
            "perceived loudness the whole recording is brought to before it is cut, with peaks above "
            f"{PEAK_DB:g} dBFS limited (default {LOUDNESS_LUFS:g}, from {QUIETEST_LUFS:g} to {LOUDEST_LUFS:g})"
        ),
    )
    parser.add_argument("--no-normalize", action="store_true", help="cut the recording at the loudness it was recorded")
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


def _lufs(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        value = math.nan
    if not QUIETEST_LUFS <= value <= LOUDEST_LUFS:
        raise argparse.ArgumentTypeError(f"{text!r} is not a loudness from {QUIETEST_LUFS:g} to {LOUDEST_LUFS:g} LUFS")
    return value


def _bitrate(text: str) -> str:
    if not _BITRATE.fullmatch(text):
        raise argparse.ArgumentTypeError(f"{text!r} is not a bitrate such as 32k")
    return text


def loudness_line(normalized: Normalized) -> str:
    if not normalized.before.measured:
        return "Loudness could not be measured (silent, or shorter than 0.4 s), so the recording is left as it is."
    verb = "raised" if normalized.gain >= 0 else "lowered"
    line = (
        f"Loudness {normalized.before.integrated:.1f} LUFS, {verb} {abs(normalized.gain):.1f} dB "
        f"to {normalized.after.integrated:.1f} LUFS"
    )
    return line + (f", with peaks limited to {PEAK_DB:g} dBFS." if normalized.limited else ".")


def _list(found: Found, out: TextIO) -> None:
    for number, span in enumerate(found.spans, 1):
        print(f"{number:>3}  at {_clock(span.start)}  ({_seconds(span.ms)})", file=out)
    print(f"{_count(len(found.spans), 'clip')} found, {_count(found.ignored, 'short sound')} ignored", file=out)


def _name_clips(
    recording: str, audio: AudioSegment, found: Found, args: argparse.Namespace, stdin: TextIO, out: TextIO, err: TextIO
) -> _Tally:
    total = len(found.spans)
    ignored = f" ({_count(found.ignored, 'short sound')} ignored)" if found.ignored else ""
    print(f"Found {_count(total, 'clip')} in {recording}{ignored}.", file=out)
    if not total:
        print("Try a smaller --threshold or --min-speech, and check them with --list.", file=out)
        return _Tally()
    written = skipped = 0
    status = 0
    stopped = False
    try:
        for number, span in enumerate(found.spans, 1):
            clip = cut_clip(audio, span, args.guard)
            if args.play:
                _play(clip, err)
            if _name_one(clip, f"Clip {number} of {total} at {_clock(span.start)} ({_seconds(span.ms)}): ", args, stdin, out, err):
                written += 1
            else:
                skipped += 1
    except KeyboardInterrupt:
        print("\nStopped.", file=out)
        status, stopped = 130, True
    except EOFError:
        print("\nStopped at the end of the input.", file=out)
        status, stopped = 1, True
    except (ClipError, OSError) as exc:
        print(f"cut-clips: {exc}", file=err)
        status = 1
    left = total - written - skipped
    summary = f"Wrote {_count(written, 'clip')}, skipped {skipped}"
    print(summary + (f", {left} not named." if left else "."), file=out)
    return _Tally(written, skipped, status, stopped)


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
        if all(_replace(path, name, args, stdin, out) for path in existing):
            write_clip(clip, args.out, name, bitrate=args.bitrate, replace=existing)
            return True


def _replace(path: Path, name: str, args: argparse.Namespace, stdin: TextIO, out: TextIO) -> bool:
    """Ask whether to replace an existing clip, unless always or never was answered earlier in the run."""
    if args.replacing is not None:
        print(f"  {'Replacing' if args.replacing else 'Keeping'} {path.name}.", file=out)
        return args.replacing
    if path.name == name + EXTENSION:
        question = f"Replace {path.name}?"
    else:
        question = f"{path.name} is already the clip for {name}. Replace it?"
    answer = _ask(f"{question} {REPLACE_CHOICES} ", stdin, out).strip().lower()
    if answer in ("a", "always"):
        args.replacing = True
    elif answer in ("v", "never"):
        args.replacing = False
    return answer in ("y", "yes", "a", "always")


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
