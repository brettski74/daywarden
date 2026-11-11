"""S023.3: recording a word or sentence in the parent portal, cutting it on the service, and keeping clips."""

import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from asgi import call  # noqa: E402
from test_clips import THREE, _audio, _write_wav  # noqa: E402
from test_task_admin import House  # noqa: E402
from policy import clips, portal, recordings, spelling  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg makes and cuts the recordings")
WORD_AND_SENTENCE = (500, 400, 900, 1200, 900)


@pytest.fixture
def house(tmp_path, monkeypatch):
    return House(tmp_path, monkeypatch)


def _take(tmp_path: Path, *parts: int, container: str = "ogg") -> bytes:
    """Tones separated by silence, encoded with Opus as a browser's MediaRecorder would send them."""
    source = _write_wav(tmp_path / "take-source.wav", _audio(*parts)[0])
    target = tmp_path / f"take.{container}"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-i", str(source), "-c:a", "libopus", "-f", container, str(target)], check=True
    )
    return target.read_bytes()


def _upload(house: House, body: bytes, content_type: str = "audio/ogg;codecs=opus", cookie: str | None = "") -> tuple[int, dict]:
    status, text, _headers = call(
        house.app, "POST", "/parent/api/recordings", body=body, content_type=content_type,
        cookie=house.cookie if cookie == "" else cookie,
    )
    return status, json.loads(text)


def _post(house: House, path: str, body: dict) -> tuple[int, dict]:
    status, text, _headers = call(house.app, "POST", path, json_body=body, cookie=house.cookie)
    return status, json.loads(text)


def _cut(house: House, take: str, **settings) -> tuple[int, dict]:
    return _post(house, f"/parent/api/recordings/{take}/cut", {"settings": settings})


def _keep(house: House, take: str, key: str, **kept: str) -> tuple[int, dict]:
    return _post(house, "/parent/api/tasks/spelling/spelling/recordings", {"take": take, "word": key, "clips": kept})


def _pending(house: House) -> list[str]:
    folder = house.data / recordings.DIRECTORY
    return sorted(str(path.relative_to(folder)) for path in folder.rglob("*") if path.is_file()) if folder.is_dir() else []


def _recorded(house: House, tmp_path: Path, parts=WORD_AND_SENTENCE) -> tuple[str, list[dict]]:
    status, uploaded = _upload(house, _take(tmp_path, *parts))
    assert status == 200, uploaded
    status, cut = _cut(house, uploaded["take"])
    assert status == 200, cut
    return uploaded["take"], cut["clips"]


# Uploading


@pytest.mark.parametrize(
    "content_type",
    ["multipart/form-data; boundary=x", "application/x-www-form-urlencoded", "text/plain", "application/json", "audio/mpeg", ""],
)
def test_only_an_audio_webm_or_ogg_body_is_taken_as_a_recording(house, content_type):
    status, body = _upload(house, b"OggS" + b"\0" * 100, content_type)
    assert status == 415
    assert body == {"error": "Send a recording as audio/webm or audio/ogg."}
    assert _pending(house) == []


@pytest.mark.parametrize("content_type", ["audio/webm", "audio/webm;codecs=opus", "audio/ogg", "audio/ogg; codecs=opus"])
def test_a_webm_or_ogg_recording_is_kept_as_pending_and_answers_its_id(house, content_type):
    status, body = _upload(house, b"recorded audio", content_type)
    assert status == 200, body
    extension = "webm" if "webm" in content_type else "ogg"
    assert _pending(house) == [f"{body['take']}/take.{extension}"]
    assert (house.data / recordings.DIRECTORY / body["take"] / f"take.{extension}").read_bytes() == b"recorded audio"
    assert house.files("current") == ["cat.wav", "dog.wav", "rope.sentence.wav", "rope.wav"]


def test_without_a_session_an_upload_is_refused_with_401_and_nothing_is_kept(house):
    status, body = _upload(house, b"recorded audio", cookie=None)
    assert status == 401
    assert "take" not in body
    assert _pending(house) == []


def test_an_upload_over_the_limit_is_refused_with_413_before_it_is_kept(house, monkeypatch):
    monkeypatch.setattr(portal, "LONGEST_TAKE_BYTES", 1000)
    status, body = _upload(house, b"x" * 1001)
    assert status == 413
    assert body == {"error": recordings.TOO_LONG}
    assert _pending(house) == []
    assert _upload(house, b"x" * 1000)[0] == 200


def test_only_https_can_upload(house):
    status, _text, _headers = call(
        house.app, "POST", "/parent/api/recordings", body=b"audio", content_type="audio/ogg", cookie=house.cookie, scheme="http"
    )
    assert status == 403
    assert _pending(house) == []


# Cutting


@needs_ffmpeg
@pytest.mark.parametrize("container", ["ogg", "webm"])
def test_a_take_is_cut_into_pending_clips_that_play_and_no_pool_changes(house, tmp_path, container):
    status, uploaded = _upload(house, _take(tmp_path, *THREE, container=container), f"audio/{container};codecs=opus")
    assert status == 200
    status, cut = _cut(house, uploaded["take"])
    assert status == 200, cut
    assert len(cut["clips"]) == 3
    for clip, start in zip(cut["clips"], (500, 1800, 3450)):
        assert abs(clip["start"] - start) <= 30
    assert cut["loudness"].startswith("Loudness ")
    status, audio, headers = call(house.app, "GET", f"/parent/api/recordings/{uploaded['take']}/{cut['clips'][0]['id']}.opus", cookie=house.cookie)
    assert status == 200
    assert headers["content-type"] == ["audio/ogg"]
    assert headers["cache-control"] == ["private, no-store"]
    assert house.files("current") == ["cat.wav", "dog.wav", "rope.sentence.wav", "rope.wav"]


@needs_ffmpeg
def test_cutting_again_with_other_settings_reuses_the_take_and_replaces_the_clips(house, tmp_path):
    take, first = _recorded(house, tmp_path, THREE)
    assert len(first) == 3
    status, merged = _cut(house, take, min_silence=1100)
    assert status == 200, merged
    assert len(merged["clips"]) == 1
    status, quieter = _cut(house, take, threshold="120", loudness="-30", guard=10, min_speech=0)
    assert status == 200, quieter
    assert len(quieter["clips"]) == 3
    for clip in first:
        assert call(house.app, "GET", f"/parent/api/recordings/{take}/{clip['id']}.opus", cookie=house.cookie)[0] == 404
    assert len([name for name in _pending(house) if name.endswith(".opus")]) == 3


@needs_ffmpeg
def test_a_silent_take_has_no_clips(house, tmp_path):
    take, found = _recorded(house, tmp_path, (3000,))
    assert found == []
    assert house.files("current") == ["cat.wav", "dog.wav", "rope.sentence.wav", "rope.wav"]


def test_settings_outside_the_cut_clips_limits_are_each_refused_under_their_field(house):
    _status, uploaded = _upload(house, b"recorded audio")
    status, body = _cut(house, uploaded["take"], min_silence=150, threshold=0, min_speech=-1, guard="9", loudness="-5", speed=2)
    assert status == 400
    assert set(body["errors"]) == {"min_silence", "threshold", "min_speech", "guard", "loudness", "speed"}
    assert body["errors"]["loudness"] == "Loudness is from -40 to -10 LUFS."
    assert _cut(house, uploaded["take"], threshold=200)[1]["errors"] == {"threshold": "Threshold is a number of decibels above 0 and below 200."}
    assert _cut(house, uploaded["take"], min_silence="700.5")[1]["errors"].keys() == {"min_silence"}


def test_the_settings_accept_text_and_numbers_and_default_what_is_left_out():
    assert recordings.cut_settings({}) == recordings.CutSettings(700, 35.0, 150, 100, -18.0)
    assert recordings.cut_settings({"threshold": "120", "loudness": "\u221240", "min_silence": 200.0, "guard": "10"}) == (
        recordings.CutSettings(200, 120.0, 150, 10, -40.0)
    )


def test_a_take_that_is_gone_cannot_be_cut(house):
    status, body = _cut(house, "A" * 16)
    assert status == 404
    assert body["error"] == recordings.GONE
    assert _cut(house, "../../etc")[0] == 404


def test_a_take_that_is_not_audio_reports_why_it_could_not_be_cut(house):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg reads the recording")
    _status, uploaded = _upload(house, b"this is not audio at all")
    status, body = _cut(house, uploaded["take"])
    assert status == 400
    assert body["error"].startswith("The recording could not be cut: ")


# Keeping


@needs_ffmpeg
def test_keeping_the_word_replaces_its_old_clip_in_any_format_and_throws_the_take_away(house, tmp_path):
    take, found = _recorded(house, tmp_path, THREE)
    status, body = _keep(house, take, "rope", word=found[1]["id"])
    assert status == 200, body
    assert body["message"] == "Saved the new word recording of rope."
    assert house.files("current") == ["cat.wav", "dog.wav", "rope.opus", "rope.sentence.wav"]
    assert clips.load_recording(house.data / "spelling/current/rope.opus").duration_seconds == pytest.approx(0.85, abs=0.03)
    assert _pending(house) == []
    page = house.page()["spelling"]["words"]
    assert {"key": "rope", "word": "rope", "pool": "current", "clip": "rope.opus", "sentence": "rope.sentence.wav"} in page


@needs_ffmpeg
def test_keeping_both_writes_the_word_and_sentence_clips(house, tmp_path):
    take, found = _recorded(house, tmp_path)
    assert len(found) == 2
    status, body = _keep(house, take, "rope", word=found[0]["id"], sentence=found[1]["id"])
    assert status == 200, body
    assert body["message"] == "Saved the new word and sentence recordings of rope."
    assert house.files("current") == ["cat.wav", "dog.wav", "rope.opus", "rope.sentence.opus"]


@needs_ffmpeg
def test_a_sentence_can_be_added_to_a_word_that_has_none(house, tmp_path):
    take, found = _recorded(house, tmp_path, (500, 1200, 500))
    status, body = _keep(house, take, "cat", sentence=found[0]["id"])
    assert status == 200, body
    assert house.files("current") == ["cat.sentence.opus", "cat.wav", "dog.wav", "rope.sentence.wav", "rope.wav"]
    cat = next(word for word in house.page()["spelling"]["words"] if word["key"] == "cat")
    assert cat["sentence"] == "cat.sentence.opus"


@needs_ffmpeg
@pytest.mark.parametrize("word, pool", [("fish", "revision"), ("owl", "attic")])
def test_a_revision_or_attic_word_is_written_into_its_own_pool(house, tmp_path, word, pool):
    take, found = _recorded(house, tmp_path, (500, 400, 500))
    assert _keep(house, take, word, word=found[0]["id"])[0] == 200
    assert house.files(pool) == [f"{word}.opus"]
    assert house.files("current") == ["cat.wav", "dog.wav", "rope.sentence.wav", "rope.wav"]


@needs_ffmpeg
def test_discarding_a_take_leaves_every_pool_as_it_was(house, tmp_path):
    take, _found = _recorded(house, tmp_path)
    before = {pool: house.files(pool) for pool in spelling.ALL_POOLS}
    assert _post(house, f"/parent/api/recordings/{take}/discard", {}) == (200, {"discarded": True})
    assert _pending(house) == []
    assert {pool: house.files(pool) for pool in spelling.ALL_POOLS} == before


@needs_ffmpeg
def test_a_keep_naming_a_clip_that_is_gone_or_a_word_that_is_not_there_writes_nothing(house, tmp_path):
    take, found = _recorded(house, tmp_path)
    assert _keep(house, take, "rope", word="abcdef-9") == (404, {"error": recordings.GONE})
    status, body = _keep(house, take, "moon", word=found[0]["id"])
    assert status == 400
    assert "There is no word moon" in body["error"]
    assert _keep(house, take, "rope", word=found[0]["id"], sentence=found[0]["id"])[0] == 400
    assert _keep(house, take, "rope")[0] == 400
    assert house.files("current") == ["cat.wav", "dog.wav", "rope.sentence.wav", "rope.wav"]
    assert len(_pending(house)) == 3


def test_a_keep_on_a_task_that_is_not_spelling_is_refused(house):
    status, body = _post(house, "/parent/api/tasks/worksheet/sums/recordings", {"take": "A" * 16, "word": "rope", "clips": {"word": "abcdef-1"}})
    assert status == 400
    assert "not a spelling task" in body["error"]


def test_every_recording_address_refuses_without_a_session_and_never_redirects(house):
    for method, path in [
        ("POST", "/parent/api/recordings/AAAAAAAAAAAAAAAA/cut"),
        ("POST", "/parent/api/recordings/AAAAAAAAAAAAAAAA/discard"),
        ("POST", "/parent/api/tasks/spelling/spelling/recordings"),
        ("GET", "/parent/api/recordings/AAAAAAAAAAAAAAAA/abcdef-1.opus"),
    ]:
        status, _body, headers = call(house.app, method, path, json_body={} if method == "POST" else None)
        assert status == 401, path
        assert "location" not in headers
    for path in ("/parent/api/recordings/AAAAAAAAAAAAAAAA/cut", "/parent/api/tasks/spelling/spelling/recordings"):
        assert call(house.app, "POST", path, body=b"{}", content_type="text/plain", cookie=house.cookie)[0] == 415


@needs_ffmpeg
def test_a_kept_clip_is_normalized_and_encoded_as_cut_clips_writes_it(house, tmp_path):
    raw = _take(tmp_path, *THREE)
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "take.ogg").write_bytes(raw)
    clips.main([str(tmp_path / "out" / "take.ogg"), "--out", str(tmp_path / "out")], stdin=io.StringIO("\none\n\n"), out=io.StringIO(), err=io.StringIO())
    status, uploaded = _upload(house, raw)
    _status, cut = _cut(house, uploaded["take"])
    assert _keep(house, uploaded["take"], "dog", word=cut["clips"][1]["id"])[0] == 200
    tool = clips.measure_loudness(clips.load_recording(tmp_path / "out" / "one.opus"))
    ours = clips.measure_loudness(clips.load_recording(house.data / "spelling/current/dog.opus"))
    assert ours.integrated == pytest.approx(tool.integrated, abs=0.1)
    assert ours.peak == pytest.approx(tool.peak, abs=0.1)


# Cleaning up


def test_takes_older_than_a_day_are_removed_at_start_and_at_the_next_upload(house, tmp_path, monkeypatch):
    from policy.app import create_app

    folder = house.data / recordings.DIRECTORY
    for name in ("old-take-aaaaaaa", "new-take-bbbbbbb"):
        (folder / name).mkdir(parents=True)
        (folder / name / "take.ogg").write_bytes(b"audio")
    day_and_a_bit = time.time() - recordings.KEEP_SECONDS - 60
    os.utime(folder / "old-take-aaaaaaa", (day_and_a_bit, day_and_a_bit))
    create_app()
    assert sorted(child.name for child in folder.iterdir()) == ["new-take-bbbbbbb"]

    os.utime(folder / "new-take-bbbbbbb", (day_and_a_bit, day_and_a_bit))
    _status, uploaded = _upload(house, b"recorded audio")
    assert sorted(child.name for child in folder.iterdir()) == [uploaded["take"]]


# The quiz


def test_a_run_that_started_with_an_older_format_plays_the_re_recorded_clip(tmp_path):
    from conftest import write_wav

    settings = spelling.parse_settings({})
    write_wav(tmp_path / "spelling/current/rope.opus")
    write_wav(tmp_path / "spelling/current/rope.sentence.wav")
    found = spelling.find_clip(settings, spelling.CURRENT, "rope", sentence=False, extension="mp3", root=tmp_path)
    assert found == tmp_path / "spelling/current/rope.opus"
    sentence = spelling.find_clip(settings, spelling.CURRENT, "rope", sentence=True, extension="opus", root=tmp_path)
    assert sentence == tmp_path / "spelling/current/rope.sentence.wav"
    assert spelling.find_clip(settings, spelling.CURRENT, "cat", sentence=False, extension="mp3", root=tmp_path) is None
