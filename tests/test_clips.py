"""S005.3, S005.7, S005.8: normalizing a spoken recording and cutting it into named, faded spelling clips."""

import io
import math
import os
import random
import re
import shutil
import subprocess
import sys
import wave
from array import array
from pathlib import Path

import pytest
from pydub import AudioSegment

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from conftest import write_wav  # noqa: E402

from policy import clips  # noqa: E402
from policy.clips import (  # noqa: E402
    ClipError,
    MissingTool,
    Span,
    check_name,
    cut_clip,
    existing_clips,
    find_clips,
    load_recording,
    main,
    measure_loudness,
    normalize,
    write_clip,
)

RATE = 48_000
TONE = 16_000
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg makes and reads the recordings")


def _audio(*parts: int, scale: float = 1.0, frequency: float = 440.0) -> tuple[AudioSegment, list[tuple[int, int]]]:
    """Alternate silence and tone, in ms, starting with silence. Return the audio and each tone's span.

    The silence holds faint noise, as a room does.
    """
    rng = random.Random(0)
    samples = array("h")
    tones = []
    at = 0
    for index, ms in enumerate(parts):
        count = RATE * ms // 1000
        if index % 2:
            tones.append((at, at + ms))
            samples.extend(round(scale * TONE * math.sin(2 * math.pi * frequency * n / RATE)) for n in range(count))
        else:
            samples.extend(round(scale * rng.uniform(-8, 8)) for _ in range(count))
        at += ms
    return AudioSegment(data=samples.tobytes(), sample_width=2, frame_rate=RATE, channels=1), tones


def _samples(audio: AudioSegment) -> array:
    return array("h", audio.raw_data)


def _rms(values) -> float:
    return math.sqrt(sum(value * value for value in values) / len(values))


def _db(louder, quieter) -> float:
    return 20 * math.log10(_rms(louder) / _rms(quieter))


def _write_wav(path: Path, audio: AudioSegment) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(audio.channels)
        handle.setsampwidth(audio.sample_width)
        handle.setframerate(audio.frame_rate)
        handle.writeframes(audio.raw_data)
    return path


def _convert(source: Path, target: Path, *options: str) -> Path:
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(source), *options, str(target)], check=True)
    return target


THREE = (500, 400, 900, 650, 1000, 300, 600)


@pytest.fixture
def take(tmp_path) -> Path:
    """A recording of three tones, as a WAV file in its own directory."""
    (tmp_path / "recording").mkdir()
    return _write_wav(tmp_path / "recording" / "take.wav", _audio(*THREE)[0])


def _run(*argv: str, answers: str = "") -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    status = main(list(argv), stdin=io.StringIO(answers), out=out, err=err)
    return status, out.getvalue(), err.getvalue()


# Finding clips


def test_each_tone_is_one_clip_that_starts_and_ends_within_10_ms_of_it():
    audio, tones = _audio(503, 400, 901, 657, 1000, 300, 600)
    found = find_clips(audio)
    assert len(found.spans) == 3
    assert found.ignored == 0
    for span, (start, end) in zip(found.spans, tones):
        assert abs(span.start - start) <= 10
        assert abs(span.end - end) <= 10


def test_a_short_gap_stays_inside_one_clip_unless_min_silence_is_shorter():
    audio, _ = _audio(500, 400, 300, 400, 800)
    assert len(find_clips(audio).spans) == 1
    assert len(find_clips(audio, min_silence=200).spans) == 2


def test_min_silence_cannot_be_below_200_ms():
    with pytest.raises(ValueError):
        find_clips(_audio(500, 400, 500)[0], min_silence=150)


def test_a_sound_shorter_than_min_speech_is_ignored_and_counted():
    audio, tones = _audio(500, 400, 900, 50, 900, 400, 500)
    found = find_clips(audio)
    assert [(span.start // 10, span.end // 10) for span in found.spans] == [
        (tones[0][0] // 10, tones[0][1] // 10),
        (tones[2][0] // 10, tones[2][1] // 10),
    ]
    assert found.ignored == 1
    assert len(find_clips(audio, min_speech=40).spans) == 3


def test_silence_is_measured_from_the_loudest_point_so_a_quieter_take_gives_the_same_clips():
    loud, _ = _audio(*THREE)
    quiet, _ = _audio(*THREE, scale=0.1)
    assert quiet.max < loud.max / 9
    assert find_clips(quiet) == find_clips(loud)


def test_a_silent_recording_has_no_clips():
    audio = AudioSegment(data=b"\0" * RATE * 2, sample_width=2, frame_rate=RATE, channels=1)
    assert find_clips(audio).spans == ()


# Loudness


@needs_ffmpeg
def test_quiet_and_loud_takes_are_brought_to_the_same_perceived_loudness():
    for scale in (0.02, 0.3, 1.0):
        audio, _ = _audio(*THREE, scale=scale)
        normalized = normalize(audio)
        assert abs(normalized.after.integrated + 18) <= 0.5
        assert normalized.gain == pytest.approx(-18 - normalized.before.integrated)
        assert not normalized.limited
    louder = normalize(_audio(*THREE)[0], -12)
    assert abs(louder.after.integrated + 12) <= 0.5


@needs_ffmpeg
def test_one_gain_covers_the_whole_recording_so_items_keep_their_relative_loudness_and_the_same_clips():
    audio = _audio(500, 600, 900)[0] + _audio(0, 600, 500, scale=0.25)[0]
    normalized = normalize(audio)
    loud, quiet = _samples(audio[500:1100]), _samples(audio[2000:2600])
    new_loud, new_quiet = _samples(normalized.audio[500:1100]), _samples(normalized.audio[2000:2600])
    assert abs(_db(new_loud, new_quiet) - _db(loud, quiet)) <= 0.1
    assert abs(_db(new_loud, loud) - normalized.gain) <= 0.1
    assert len(normalized.audio) == len(audio)
    assert find_clips(normalized.audio) == find_clips(audio)


@needs_ffmpeg
def test_a_peak_the_gain_would_clip_is_limited_rather_than_the_loudness_lowered():
    samples = _samples(_audio(500, 2000, 500, scale=0.05)[0])
    samples[RATE] = 30000
    audio = AudioSegment(data=samples.tobytes(), sample_width=2, frame_rate=RATE, channels=1)
    normalized = normalize(audio)
    assert normalized.limited
    assert normalized.before.peak > -1.5
    assert normalized.gain > 10
    assert abs(normalized.after.integrated + 18) <= 0.5
    assert normalized.audio.max <= 32767 * 10 ** (-1 / 20) + 2
    tone = slice(RATE * 2, RATE * 2 + RATE // 2)
    assert abs(_db(_samples(normalized.audio)[tone], samples[tone]) - normalized.gain) <= 0.1


@needs_ffmpeg
@pytest.mark.parametrize(
    "audio",
    [
        AudioSegment(data=b"\0" * RATE * 4, sample_width=2, frame_rate=RATE, channels=1),
        _audio(0, 300)[0],
    ],
    ids=["silent", "shorter-than-400-ms"],
)
def test_a_recording_too_quiet_or_short_to_measure_is_left_as_it_is(audio):
    assert not measure_loudness(audio).measured
    normalized = normalize(audio)
    assert not normalized.before.measured
    assert normalized.gain == 0
    assert normalized.audio.raw_data == audio.raw_data


@pytest.mark.parametrize("target", [-41, -9, -3])
def test_a_target_loudness_out_of_range_is_refused(target):
    with pytest.raises(ValueError, match="from -40 to -10 LUFS"):
        normalize(_audio(500, 400, 500)[0], target)


# Cutting clips


@pytest.mark.parametrize("guard", [10, 50, 100, 250])
@pytest.mark.parametrize("parts", [THREE, (30, 400, 900, 400, 40), (0, 400, 900, 400, 0)])
def test_each_clip_is_a_guard_the_speech_and_a_guard_even_at_the_edges(parts, guard):
    audio, tones = _audio(*parts)
    found = find_clips(audio)
    assert len(found.spans) == len(tones)
    for span in found.spans:
        clip = cut_clip(audio, span, guard)
        assert abs(len(clip) - (span.ms + 2 * guard)) <= 1
        samples = _samples(clip)
        assert samples[0] == 0 and samples[-1] == 0


@pytest.mark.parametrize("guard_ms", [10, 50, 100, 250])
@pytest.mark.parametrize("span", [Span(500, 1500), Span(40, 1500), Span(500, 1980)])
def test_the_guards_fade_from_and_to_zero_over_their_whole_length_and_the_speech_is_untouched(span, guard_ms):
    audio, _ = _audio(0, 2000, frequency=1000)
    clip = cut_clip(audio, span, guard_ms)
    samples = _samples(clip)
    guard = RATE * guard_ms // 1000
    speech = _samples(audio[span.start : span.end])
    assert len(samples) == guard * 2 + len(speech)
    assert samples[0] == 0 and samples[-1] == 0
    assert samples[guard:-guard] == speech
    lead, tail = samples[:guard], samples[-guard:]
    quarter = guard // 4
    lead_levels = [_rms(lead[n * quarter : (n + 1) * quarter]) for n in range(4)]
    tail_levels = [_rms(tail[n * quarter : (n + 1) * quarter]) for n in range(4)]
    padded_lead = span.start < guard_ms
    padded_tail = len(audio) - span.end < guard_ms
    if not padded_lead:
        assert lead_levels == sorted(lead_levels) and lead_levels[0] < lead_levels[-1]
    if not padded_tail:
        assert tail_levels == sorted(tail_levels, reverse=True) and tail_levels[0] > tail_levels[-1]
    if padded_lead:
        assert set(lead[: (guard_ms - span.start) * RATE // 1000]) == {0}
    if padded_tail:
        assert set(tail[(len(audio) - span.end) * RATE // 1000 :]) == {0}


def test_the_default_guard_is_100_ms():
    audio, _ = _audio(0, 2000)
    assert len(cut_clip(audio, Span(500, 1500))) == 1200


@pytest.mark.parametrize("guard", [9, 0, -5])
def test_a_guard_shorter_than_10_ms_is_refused(guard):
    audio, _ = _audio(0, 2000)
    with pytest.raises(ValueError, match="at least 10 ms"):
        cut_clip(audio, Span(500, 1500), guard)


@needs_ffmpeg
def test_a_written_clip_is_libopus_ogg_mono_48k_and_decodes_to_the_same_length(tmp_path):
    audio, _ = _audio(*THREE)
    span = find_clips(audio).spans[1]
    clip = cut_clip(audio, span)
    path = write_clip(clip, tmp_path / "new" / "words", "rope")
    assert path == tmp_path / "new" / "words" / "rope.opus"
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=format_name:stream=codec_name,sample_rate,channels:stream_tags=encoder",
            "-of", "default=noprint_wrappers=1", str(path),
        ],
        capture_output=True, text=True, check=True,
    ).stdout.lower()
    assert "codec_name=opus" in probe
    assert "sample_rate=48000" in probe
    assert "channels=1" in probe
    assert "format_name=ogg" in probe
    assert "libopus" in probe
    decoded = load_recording(path)
    assert abs(len(decoded) - len(clip)) <= 10
    edge = RATE * 5 // 1000
    samples = _samples(decoded)
    quiet = 32768 * 10 ** (-50 / 20)
    assert max(abs(value) for value in samples[:edge]) < quiet
    assert max(abs(value) for value in samples[-edge:]) < quiet


# Loading recordings


@needs_ffmpeg
@pytest.mark.parametrize(
    ("name", "options"),
    [
        ("mono.wav", ["-ac", "1"]),
        ("stereo.wav", ["-ac", "2"]),
        ("mono.mp3", ["-ac", "1", "-c:a", "libmp3lame"]),
        ("stereo.mp3", ["-ac", "2", "-c:a", "libmp3lame"]),
        ("mono.m4a", ["-ac", "1", "-c:a", "aac"]),
        ("stereo.m4a", ["-ac", "2", "-c:a", "aac", "-ar", "44100"]),
        ("mono.opus", ["-ac", "1", "-c:a", "libopus"]),
        ("stereo.opus", ["-ac", "2", "-c:a", "libopus"]),
    ],
)
def test_every_format_mono_or_stereo_gives_the_same_clips(take, tmp_path, name, options):
    expected = len(find_clips(load_recording(take)).spans)
    assert expected == 3
    audio = load_recording(_convert(take, tmp_path / name, *options))
    assert (audio.channels, audio.frame_rate, audio.sample_width) == (1, RATE, 2)
    assert len(find_clips(audio).spans) == expected


@needs_ffmpeg
@pytest.mark.parametrize(
    ("name", "hint"),
    [("take.webm", "webm"), ("take.webm", "audio/webm;codecs=opus"), ("take.ogg", "ogg"), ("take.ogg", None)],
)
def test_a_recording_loads_from_bytes_with_an_optional_format_hint(take, tmp_path, name, hint):
    data = _convert(take, tmp_path / name, "-c:a", "libopus").read_bytes()
    assert len(find_clips(load_recording(data, hint)).spans) == 3


@needs_ffmpeg
def test_a_file_that_is_not_audio_is_refused(tmp_path):
    with pytest.raises(ClipError, match="missing.wav"):
        load_recording(tmp_path / "missing.wav")
    (tmp_path / "notes.txt").write_text("not audio", encoding="utf-8")
    with pytest.raises(ClipError, match="ffmpeg failed"):
        load_recording(tmp_path / "notes.txt")


# Names


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a", ("a", "a", False)),
        ("dash", ("dash", "dash", False)),
        ("apostrophe", ("apostrophe", "apostrophe", False)),
        ("don't", ("don't", "don't", False)),
        ("read.2", ("read.2", "read", False)),
        ("read.2.sentence", ("read.2", "read", True)),
        ("rope.sentence", ("rope", "rope", True)),
    ],
)
def test_names_the_pool_accepts_are_accepted(name, expected):
    assert check_name(name) == expected


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("rope!", "letters a to z"),
        ("rope.0", "is not <word>"),
        ("rope.sentence.1", "is not <word>"),
        ("supercalifragilisticexp", "longer than 22"),
        ("rope.opus", "leave off the extension"),
        ("../rope", "is not <word>"),
        ("", "needs a name"),
    ],
)
def test_names_the_pool_would_refuse_are_explained(name, reason):
    with pytest.raises(ValueError, match=reason.replace(".", r"\.")):
        check_name(name)


def test_existing_clips_for_an_entry_ignore_case_and_extension(tmp_path):
    for name in ("Rope.wav", "rope.opus", "rope.sentence.mp3", "ropes.opus", ".rope.mp3", "rope!.mp3", "notes.txt"):
        (tmp_path / name).write_bytes(b"x")
    assert [path.name for path in existing_clips(tmp_path, "rope")] == ["rope.opus", "Rope.wav"]
    assert [path.name for path in existing_clips(tmp_path, "ROPE.sentence")] == ["rope.sentence.mp3"]
    assert existing_clips(tmp_path / "missing", "rope") == []


# Writing


@needs_ffmpeg
def test_writing_with_replace_leaves_only_the_new_clip(tmp_path):
    write_wav(tmp_path / "rope.mp3")
    write_wav(tmp_path / "Rope.opus")
    audio, _ = _audio(*THREE)
    clip = cut_clip(audio, find_clips(audio).spans[0])
    write_clip(clip, tmp_path, "rope", replace=existing_clips(tmp_path, "rope"))
    assert sorted(path.name for path in tmp_path.iterdir()) == ["rope.opus"]


def test_an_interrupted_write_leaves_no_temporary_file(tmp_path, monkeypatch):
    def interrupted(arguments, label, *, stdin=None):
        Path(arguments[-1]).write_bytes(b"half a clip")
        raise KeyboardInterrupt

    monkeypatch.setattr(clips, "_ffmpeg", interrupted)
    with pytest.raises(KeyboardInterrupt):
        write_clip(_audio(100, 400, 100)[0], tmp_path, "rope")
    assert list(tmp_path.iterdir()) == []


# The command line


@needs_ffmpeg
def test_the_tool_counts_the_clips_then_asks_for_each_name_in_order(take, tmp_path):
    out_dir = tmp_path / "spelling" / "alphabet"
    status, out, err = _run(str(take), "--out", str(out_dir), answers="a\n\ndash\n")
    assert status == 0, err
    lines = out.splitlines()
    assert lines[0].startswith("Loudness ")
    assert lines[1] == f"Found 3 clips in {take}."
    assert [line for line in lines if line.startswith("Clip")] == [
        "Clip 1 of 3 at 0:00.50 (0.40 s): ",
        "Clip 2 of 3 at 0:01.80 (0.65 s): ",
        "Clip 3 of 3 at 0:03.45 (0.30 s): ",
    ]
    assert "Wrote 2 clips, skipped 1." in lines
    assert sorted(path.name for path in out_dir.iterdir()) == ["a.opus", "dash.opus"]
    assert err == ""
    assert "Recording 1" not in out and "Altogether" not in out


@pytest.fixture
def pair(take) -> Path:
    """A second recording, of two tones, beside ``take``."""
    return _write_wav(take.parent / "two.wav", _audio(500, 400, 900, 400, 500)[0])


@needs_ffmpeg
def test_each_recording_is_cut_in_turn_with_the_same_settings(take, pair, tmp_path):
    words = tmp_path / "words"
    status, out, err = _run(str(take), str(pair), "--out", str(words), "--guard", "30", answers="a\nb\n\nc\nd\n")
    assert status == 0, err
    lines = out.splitlines()
    first, second = lines.index(f"Recording 1 of 2: {take}"), lines.index(f"Recording 2 of 2: {pair}")
    assert first == 0 and lines[second - 1] == ""
    assert lines[first + 2] == f"Found 3 clips in {take}."
    assert lines[second + 2] == f"Found 2 clips in {pair}."
    assert lines[-1] == "Altogether: wrote 4 clips from 2 recordings, skipped 1."
    assert sorted(path.name for path in words.iterdir()) == ["a.opus", "b.opus", "c.opus", "d.opus"]
    span = find_clips(load_recording(pair)).spans[1]
    assert abs(len(load_recording(words / "d.opus")) - (span.ms + 60)) <= 10


@needs_ffmpeg
def test_list_lists_each_recording_under_its_own_heading_and_writes_nothing(take, pair, tmp_path):
    out_dir = tmp_path / "out"
    status, out, _ = _run(str(take), str(pair), "--out", str(out_dir), "--list")
    assert status == 0
    lines = out.splitlines()
    assert [line for line in lines if line.startswith("Recording")] == [f"Recording 1 of 2: {take}", f"Recording 2 of 2: {pair}"]
    assert [line for line in lines if line.endswith("ignored")] == ["3 clips found, 0 short sounds ignored", "2 clips found, 0 short sounds ignored"]
    assert "Altogether" not in out
    assert not out_dir.exists()


@needs_ffmpeg
def test_a_missing_recording_stops_the_tool_before_anything_is_cut(take, tmp_path):
    status, out, err = _run(str(take), str(tmp_path / "missing.wav"), str(tmp_path / "gone.m4a"), "--out", str(tmp_path / "out"))
    assert status == 1
    assert err.splitlines() == [f"cut-clips: {tmp_path / 'missing.wav'}: no such file", f"cut-clips: {tmp_path / 'gone.m4a'}: no such file"]
    assert out == ""
    assert not (tmp_path / "out").exists()


@needs_ffmpeg
def test_a_recording_that_cannot_be_read_is_reported_and_the_others_are_still_cut(take, pair, tmp_path):
    notes = tmp_path / "notes.txt"
    notes.write_text("not audio", encoding="utf-8")
    words = tmp_path / "words"
    status, out, err = _run(str(take), str(notes), str(pair), "--out", str(words), answers="a\n\n\nb\n\n")
    assert status == 1
    assert f"cut-clips: {notes}: ffmpeg failed" in err
    assert f"Recording 3 of 3: {pair}" in out
    assert "Altogether: wrote 2 clips from 3 recordings, skipped 3." in out
    assert sorted(path.name for path in words.iterdir()) == ["a.opus", "b.opus"]


@needs_ffmpeg
def test_end_of_input_stops_the_whole_run_and_says_how_many_recordings_were_not_cut(take, pair, tmp_path):
    words = tmp_path / "words"
    status, out, _ = _run(str(take), str(pair), str(take), "--out", str(words), answers="a\n")
    assert status == 1
    assert "Wrote 1 clip, skipped 0, 2 not named." in out
    assert "2 recordings not cut." in out
    assert "Recording 2 of 3" not in out
    assert [path.name for path in words.iterdir()] == ["a.opus"]


@needs_ffmpeg
def test_pool_warnings_wait_until_the_last_recording_is_cut(take, pair, tmp_path):
    words = tmp_path / "words"
    status, _, err = _run(str(take), str(pair), "--out", str(words), answers="rope.sentence\n\n\nrope\n\n")
    assert status == 0
    assert err == ""
    _, _, err = _run(str(take), str(pair), "--out", str(tmp_path / "other"), answers="cat.sentence\n\n\ndog\n\n")
    assert err.count("cat.sentence.opus has no word clip beside it") == 1


@needs_ffmpeg
def test_a_name_the_pool_would_refuse_is_explained_and_asked_again(take, tmp_path):
    status, out, _ = _run(str(take), "--out", str(tmp_path), answers="rope!\nrope.0\nrope\n\n\n")
    assert status == 0
    assert out.count("Clip 1 of 3") == 3
    assert "rope!.opus: a word may only have the letters a to z" in out
    assert "rope.0.opus is not <word>" in out
    assert sorted(path.name for path in tmp_path.iterdir() if path.suffix == ".opus") == ["rope.opus"]


@needs_ffmpeg
def test_an_existing_clip_is_replaced_only_after_asking(take, tmp_path):
    write_wav(tmp_path / "rope.opus")
    before = (tmp_path / "rope.opus").read_bytes()
    status, out, _ = _run(str(take), "--out", str(tmp_path), answers="rope\nn\n\nrope\ny\n\n")
    assert status == 0
    assert out.count("Replace rope.opus? [y]es/[N]o/[a]lways/ne[v]er ") == 2
    assert out.count("Clip 1 of 3") == 2
    assert "Wrote 1 clip, skipped 2." in out
    assert (tmp_path / "rope.opus").read_bytes() != before


@needs_ffmpeg
def test_a_clip_for_the_same_entry_in_another_format_is_replaced_only_after_asking(take, tmp_path):
    words = tmp_path / "words"
    write_wav(words / "Rope.wav")
    status, out, _ = _run(str(take), "--out", str(words), answers="rope\nn\nrope\nyes\n\n\n")
    assert status == 0
    assert out.count("Rope.wav is already the clip for rope. Replace it? [y]es/[N]o/[a]lways/ne[v]er ") == 2
    assert sorted(path.name for path in words.iterdir()) == ["rope.opus"]


@needs_ffmpeg
@pytest.mark.parametrize("always", ["a", "always", "A"])
def test_always_replaces_every_later_clip_without_asking(take, tmp_path, always):
    for name in ("a", "b", "c"):
        write_wav(tmp_path / f"{name}.opus")
    before = (tmp_path / "a.opus").read_bytes()
    status, out, _ = _run(str(take), "--out", str(tmp_path), answers=f"a\n{always}\nb\nc\n")
    assert status == 0
    assert out.count(clips.REPLACE_CHOICES) == 1
    assert "  Replacing b.opus." in out and "  Replacing c.opus." in out
    assert "Wrote 3 clips, skipped 0." in out
    assert all((tmp_path / f"{name}.opus").read_bytes() != before for name in ("a", "b", "c"))


@needs_ffmpeg
@pytest.mark.parametrize("never", ["v", "never", "NEVER"])
def test_never_keeps_every_later_existing_clip_and_asks_for_another_name(take, tmp_path, never):
    for name in ("a", "b"):
        write_wav(tmp_path / f"{name}.opus")
    before = (tmp_path / "a.opus").read_bytes()
    status, out, _ = _run(str(take), "--out", str(tmp_path), answers=f"a\n{never}\n\nb\n\nc\n")
    assert status == 0
    assert out.count(clips.REPLACE_CHOICES) == 1
    assert "  Keeping b.opus." in out
    assert out.count("Clip 2 of 3") == 2
    assert "Wrote 1 clip, skipped 2." in out
    assert (tmp_path / "a.opus").read_bytes() == before and (tmp_path / "b.opus").read_bytes() == before
    assert (tmp_path / "c.opus").exists()


@needs_ffmpeg
def test_always_lasts_into_later_recordings_and_covers_clips_in_other_formats(take, pair, tmp_path):
    words = tmp_path / "words"
    write_wav(words / "Rope.wav")
    write_wav(words / "dash.mp3")
    status, out, _ = _run(str(take), str(pair), "--out", str(words), answers="rope\nalways\n\n\ndash\n\n")
    assert status == 0
    assert out.count(clips.REPLACE_CHOICES) == 1
    assert "  Replacing dash.mp3." in out
    assert sorted(path.name for path in words.iterdir()) == ["dash.opus", "rope.opus"]


@needs_ffmpeg
def test_end_of_input_keeps_the_clips_written_and_leaves_no_temporary_file(take, tmp_path):
    words = tmp_path / "words"
    status, out, _ = _run(str(take), "--out", str(words), answers="a\n")
    assert status == 1
    assert "Wrote 1 clip, skipped 0, 2 not named." in out
    assert [path.name for path in words.iterdir()] == ["a.opus"]


@needs_ffmpeg
def test_ctrl_c_at_a_prompt_keeps_the_clips_written(take, tmp_path):
    class Interrupting(io.StringIO):
        def readline(self, *args):
            line = super().readline(*args)
            if not line:
                raise KeyboardInterrupt
            return line

    words = tmp_path / "words"
    out = io.StringIO()
    status = main([str(take), "--out", str(words)], stdin=Interrupting("a\nb\n"), out=out, err=io.StringIO())
    assert status == 130
    assert "Stopped." in out.getvalue()
    assert sorted(path.name for path in words.iterdir()) == ["a.opus", "b.opus"]


@needs_ffmpeg
def test_the_summary_warns_about_pool_rules_the_directory_now_breaks(take, tmp_path):
    status, _, err = _run(str(take), "--out", str(tmp_path), answers="rope.sentence\n\n\n")
    assert status == 0
    assert f"warning: {tmp_path}: rope.sentence.opus has no word clip beside it" in err


@needs_ffmpeg
def test_list_shows_the_clips_and_short_sounds_and_writes_nothing(tmp_path):
    recording = _write_wav(tmp_path / "take.wav", _audio(500, 400, 900, 50, 900, 400, 500)[0])
    out_dir = tmp_path / "out"
    status, out, _ = _run(str(recording), "--out", str(out_dir), "--list")
    assert status == 0
    assert out.splitlines()[1:] == [
        "  1  at 0:00.50  (0.40 s)",
        "  2  at 0:02.75  (0.40 s)",
        "2 clips found, 1 short sound ignored",
    ]
    assert not out_dir.exists()


@needs_ffmpeg
def test_list_follows_the_detection_options(take):
    _, out, _ = _run(str(take), "--list", "--min-speech", "350")
    assert out.splitlines()[-1] == "2 clips found, 1 short sound ignored"


@needs_ffmpeg
def test_play_plays_each_clip_before_its_prompt_and_a_question_mark_replays_it(take, tmp_path, monkeypatch):
    fake = tmp_path / "fake-bin"
    fake.mkdir()
    log = tmp_path / "played"
    (fake / "ffplay").write_text(f'#!/usr/bin/env bash\nwc -c >> "{log}"\n', encoding="utf-8")
    (fake / "ffplay").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}:{os.environ['PATH']}")
    status, _, _ = _run(str(take), "--out", str(tmp_path / "out"), "--play", answers="?\na\n\n\n")
    assert status == 0
    sizes = [int(line) for line in log.read_text(encoding="utf-8").split()]
    assert len(sizes) == 4
    assert sizes[0] == sizes[1] != sizes[2]


def test_without_ffmpeg_the_tool_stops_before_reading_the_recording(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    status, _, err = _run(str(tmp_path / "missing.wav"))
    assert status == 1
    assert "ffmpeg is not on the PATH" in err
    assert "missing.wav" not in err


def test_an_ffmpeg_without_libopus_stops_the_tool_before_reading_the_recording(tmp_path, monkeypatch):
    fake = tmp_path / "fake-bin"
    fake.mkdir()
    (fake / "ffmpeg").write_text(
        "#!/usr/bin/env bash\nprintf ' A....D aac   AAC\\n A....D opus  Opus\\n'\n", encoding="utf-8"
    )
    (fake / "ffmpeg").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}:{os.environ['PATH']}")
    status, _, err = _run(str(tmp_path / "missing.wav"))
    assert status == 1
    assert "cannot encode Opus" in err
    assert "missing.wav" not in err


def test_without_pydub_the_tool_names_the_requirements_file(tmp_path, monkeypatch):
    monkeypatch.setattr(clips, "AudioSegment", None)
    with pytest.raises(MissingTool, match="pip install -r policy/requirements.txt"):
        clips.require_tools()
    status, _, err = _run(str(tmp_path / "missing.wav"))
    assert status == 1
    assert "pip install -r policy/requirements.txt" in err


@needs_ffmpeg
@pytest.mark.parametrize(("option", "guard"), [([], 100), (["--guard", "30"], 30), (["--guard", "10"], 10)])
def test_guard_sets_the_guard_and_fade_either_side_of_each_written_clip(take, tmp_path, option, guard):
    status, _, err = _run(str(take), "--out", str(tmp_path), *option, answers="\nrope\n\n")
    assert status == 0, err
    audio = load_recording(take)
    span = find_clips(audio).spans[1]
    decoded = load_recording(tmp_path / "rope.opus")
    assert abs(len(decoded) - (span.ms + 2 * guard)) <= 10


@needs_ffmpeg
@pytest.mark.parametrize(("option", "target"), [([], -18), (["--loudness", "-24"], -24), (["--no-normalize"], None)])
def test_written_clips_carry_the_gain_that_normalized_the_whole_recording(take, tmp_path, option, target):
    status, out, err = _run(str(take), "--out", str(tmp_path), *option, answers="\nrope\n\n")
    assert status == 0, err
    audio = load_recording(take)
    gain = 0.0 if target is None else normalize(audio, target).gain
    assert out.startswith("Loudness ") == (target is not None)
    span = find_clips(audio).spans[1]
    decoded = _samples(load_recording(tmp_path / "rope.opus"))
    middle = RATE * (clips.GUARD_MS + 100) // 1000
    source = _samples(audio[span.start + 100 : span.end - 100])
    assert abs(_db(decoded[middle:-middle], source) - gain) <= 0.5


@needs_ffmpeg
def test_the_loudness_line_reports_the_measured_loudness_the_gain_and_any_limiting(tmp_path):
    quiet = _write_wav(tmp_path / "quiet.wav", _audio(*THREE, scale=0.1)[0])
    _, out, _ = _run(str(quiet), "--list")
    assert re.fullmatch(r"Loudness -29\.\d LUFS, raised 1[01]\.\d dB to -1[78]\.\d LUFS\.", out.splitlines()[0])
    loud = _write_wav(tmp_path / "loud.wav", _audio(*THREE)[0])
    _, out, _ = _run(str(loud), "--list", "--loudness", "-10")
    assert re.fullmatch(r"Loudness -9\.\d LUFS, lowered 0\.\d dB to -(9|10)\.\d LUFS\.", out.splitlines()[0])
    samples = _samples(_audio(500, 2000, 500, scale=0.05)[0])
    samples[RATE] = 30000
    spiky = _write_wav(tmp_path / "spiky.wav", AudioSegment(data=samples.tobytes(), sample_width=2, frame_rate=RATE, channels=1))
    _, out, _ = _run(str(spiky), "--list")
    assert out.splitlines()[0].endswith(", with peaks limited to -1 dBFS.")
    silent = _write_wav(tmp_path / "silent.wav", AudioSegment(data=b"\0" * RATE * 2, sample_width=2, frame_rate=RATE, channels=1))
    _, out, _ = _run(str(silent), "--list")
    assert out.splitlines()[0] == "Loudness could not be measured (silent, or shorter than 0.4 s), so the recording is left as it is."


@pytest.mark.parametrize(
    "option",
    [
        ["--min-silence", "150"], ["--threshold", "-3"], ["--bitrate", "fast"], ["--guard", "9"], ["--guard", "fifty"],
        ["--loudness", "-41"], ["--loudness", "-9"], ["--loudness", "loud"],
    ],
)
def test_out_of_range_options_are_refused(option, capsys):
    with pytest.raises(SystemExit):
        main(["take.wav", *option])
    assert option[0] in capsys.readouterr().err


@needs_ffmpeg
def test_cut_clips_works_through_a_symlink_from_another_directory(take, tmp_path):
    fake = tmp_path / "fake-bin"
    fake.mkdir()
    (fake / "cut-clips").symlink_to(ROOT / "bin" / "cut-clips")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    shutil.copy(take, elsewhere / "take.wav")
    env = {**os.environ, "PATH": f"{fake}:{os.environ['PATH']}", "PYTHON": sys.executable}
    env.pop("PYTHONPATH", None)
    done = subprocess.run(
        ["cut-clips", "take.wav", "--out", "words"],
        cwd=elsewhere,
        env=env,
        input="rope\n\n\n",
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert "Found 3 clips in take.wav." in done.stdout
    assert [path.name for path in (elsewhere / "words").iterdir()] == ["rope.opus"]
