"""S005.1 and S005.2: the spelling quiz, its word pools, audio tokens, queue, timing, and practice mode."""

import asyncio
import html
import json
import random
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from conftest import merge_task_types, write_alphabet, write_wav  # noqa: E402

from policy import spelling  # noqa: E402
from policy.child_page import PRACTICE_LINE  # noqa: E402
from policy.hierarchy import ConfigError, load  # noqa: E402
from policy.quiz import EXPIRY, NETWORK_ALLOWANCE_MS  # noqa: E402
from policy.review import attempt_report  # noqa: E402
from policy.sounds import load_sounds  # noqa: E402
from policy.spelling import (  # noqa: E402
    CURRENT,
    PADDING_BYTES,
    PLAY_ALLOWANCE_MS,
    REVISION,
    Session,
    check_body,
    descramble,
    parse_settings,
    practice_plan,
    read_media_name,
    scramble,
    token,
    untoken,
)
from policy.store import PolicyStore  # noqa: E402
from policy.task_page import MUST_FINISH, respond_task, task_media  # noqa: E402
from policy.tasks import AttemptStore, TaskKey  # noqa: E402

ZONE = ZoneInfo("America/Toronto")
YOUNGER = "192.0.2.40"
START = datetime(2026, 11, 2, 16, 0, tzinfo=ZONE)
WORD_MS = 800
SENTENCE_MS = 2000
LETTER_MS = 300
TIMEOUT_MS = 30_000


@pytest.fixture
def data(tmp_path, monkeypatch) -> Path:
    """A data directory with the alphabet and no words, that the service reads words from."""
    root = tmp_path / "daywarden"
    write_alphabet(root / "spelling/alphabet", LETTER_MS)
    monkeypatch.setenv("DAYWARDEN_DATA_DIR", str(root))
    return root


@pytest.fixture
def any_length(monkeypatch):
    """Let files that are not real audio load as one-second recordings."""
    monkeypatch.setattr(spelling, "read_audio_ms", lambda path, field: 1000)


def _words(root: Path, folder: str, *names: str, sentences=(), ms: int = WORD_MS) -> None:
    """Record each word in ``folder``, plus a ``.sentence.`` clip for the ones in ``sentences``."""
    for name in names:
        write_wav(root / folder / f"{name}.wav", ms)
        if name in sentences:
            write_wav(root / folder / f"{name}.sentence.wav", SENTENCE_MS)


def _files(root: Path, folder: str, *names: str) -> None:
    """Create files by exact name. Use with ``any_length`` for formats other than WAV."""
    (root / folder).mkdir(parents=True, exist_ok=True)
    for name in names:
        if name.lower().endswith(".wav"):
            write_wav(root / folder / name)
        else:
            (root / folder / name).write_bytes(b"audio")


def _house(body: dict, *, rules: str | None = None, sites: str = "", extra: str = "", due: str | None = None) -> str:
    rules = rules or """\
  gate:
    - condition: always
      when_true: { action: allow }
"""
    due_line = f"      due_date: {due}\n" if due else ""
    tasks = (
        f"  spelling:\n    words:\n      group: younger\n      pass_cooldown: 0\n"
        f"{due_line}      body: {json.dumps(body)}\n{extra}"
    )
    return f"""\
entry: gate
timezone: America/Toronto
hostname: tasks.example
port: 443
client_groups:
  younger:
    addresses: ["{YOUNGER}"]
{sites}tasks:
{merge_task_types(tasks)}rule_sets:
{rules}"""


def _write(directory: Path, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "policy.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _policy(directory: Path, body: dict, **house):
    loaded = load(_write(directory, _house(body, **house)))
    assert loaded is not None
    return loaded


def _session(body: dict | None = None, seed: int = 0) -> Session:
    session = Session({}, body or {}, random.Random(seed))
    session.visit(START)
    return session


def _answer_pending(session: Session, now: datetime, right: bool, *, expired: bool = False):
    pending = session.pending
    text = pending["word"] if right else "zzz"
    return session.answer(now, len(session.questions) - 1, text, expired=expired)


# Configuration and directory loading


def test_a_body_with_no_fields_uses_the_defaults(data):
    _words(data, "spelling/current", "rope", "cat", "dog")
    _words(data, "spelling/revision", *[f"word{letter}" for letter in "abcdefg"])
    settings = parse_settings({})
    assert (settings.current_dir, settings.revision_dir, settings.alphabet_dir) == (
        "spelling/current",
        "spelling/revision",
        "spelling/alphabet",
    )
    assert settings.timeout == TIMEOUT_MS
    assert (settings.maximum_replays, settings.maximum_sentence_plays) == (3, 2)
    assert (settings.letter_pause, settings.word_pause) == (0, 300)
    pools = check_body({})
    assert len(pools.current) == 3
    assert pools.current_required == 3
    assert len(pools.revision) == 7
    assert pools.revision_required == 5


def test_the_revision_target_defaults_to_the_whole_pool_when_it_has_fewer_than_five(data):
    _words(data, "spelling/current", "rope")
    _words(data, "spelling/revision", "cat", "dog")
    assert check_body({}).revision_required == 2


@pytest.mark.parametrize(("current", "revision"), [(3, 40), (40, 0), (0, 4)])
def test_either_pool_can_be_any_size(data, current, revision):
    _words(data, "spelling/current", *[f"current{chr(97 + n // 26)}{chr(97 + n % 26)}" for n in range(current)])
    _words(data, "spelling/revision", *[f"revision{chr(97 + n // 26)}{chr(97 + n % 26)}" for n in range(revision)])
    if current == 0:
        (data / "spelling/current").mkdir(parents=True, exist_ok=True)
    pools = check_body({})
    assert (len(pools.current), len(pools.revision)) == (current, revision)
    assert pools.revision_required == min(5, revision)


def test_every_supported_audio_format_loads_and_other_files_are_ignored(data, any_length):
    _files(
        data,
        "spelling/current",
        "one.mp3",
        "two.wav",
        "three.ogg",
        "four.opus",
        "five.M4A",
        "notes.txt",
        ".hidden.mp3",
        "list.md",
    )
    (data / "spelling/current/folder.mp3").mkdir()
    assert sorted(word.key for word in check_body({}).current) == ["five", "four", "one", "three", "two"]


def test_real_recordings_report_how_long_they_play(data):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg makes the sample recordings")
    folder = data / "spelling/current"
    folder.mkdir(parents=True)
    for name, codec in {"one.mp3": "libmp3lame", "two.ogg": "libvorbis", "three.opus": "libopus", "four.m4a": "aac"}.items():
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1.5", "-c:a", codec, str(folder / name)],
            check=True,
        )
    write_wav(folder / "five.wav", 1500)
    lengths = {word.key: word.clip.ms for word in check_body({}).current}
    assert set(lengths) == {"one", "two", "three", "four", "five"}
    for key, ms in lengths.items():
        assert abs(ms - 1500) <= 100, key


def test_a_sentence_clip_pairs_with_its_word_whatever_its_format_or_case(data, any_length):
    _files(data, "spelling/current", "Rope.opus", "rope.SENTENCE.mp3", "cat.wav")
    words = {word.key: word for word in check_body({}).current}
    assert set(words) == {"Rope", "cat"}
    assert words["Rope"].word == "Rope"
    assert words["Rope"].sentence.name == "rope.SENTENCE.mp3"
    assert words["cat"].sentence is None


def test_homographs_are_separate_entries_spelled_the_same(data):
    _words(data, "spelling/current", "read.1", "read.2", sentences={"read.1", "read.2"})
    words = check_body({}).current
    assert [(word.key, word.word, word.sentence is not None) for word in words] == [
        ("read.1", "read", True),
        ("read.2", "read", True),
    ]


def test_words_may_have_dashes_and_apostrophes(data):
    _words(data, "spelling/current", "don't", "well-known")
    assert sorted(word.word for word in check_body({}).current) == ["don't", "well-known"]


def test_directories_can_be_set_per_task(data):
    _words(data, "spelling/younger/current", "rope")
    _words(data, "spelling/younger/old", "cat")
    pools = check_body({"current_dir": "spelling/younger/current", "revision_dir": "spelling/younger/old"})
    assert [word.key for word in pools.current] == ["rope"]
    assert [word.key for word in pools.revision] == ["cat"]


@pytest.mark.parametrize(
    ("body", "current", "revision", "expected"),
    [
        ({}, ["rope.opus", "rope.mp3"], [], ["body.current_dir", "rope.mp3", "rope.opus"]),
        ({}, ["rope.wav", "rope.sentence.mp3", "rope.sentence.ogg"], [], ["body.current_dir", "rope.sentence.ogg"]),
        ({}, ["cat.wav", "rope.sentence.opus"], [], ["body.current_dir", "rope.sentence.opus"]),
        ({}, ["Rope.wav"], ["rope.wav"], ["body.revision_dir", "rope"]),
        ({}, ["read.1.wav"], ["READ.1.mp3"], ["body.revision_dir", "READ.1"]),
        ({}, ["rope1.wav"], [], ["body.current_dir", "rope1.wav"]),
        ({}, ["supercalifragilisticexp.wav"], [], ["body.current_dir", "supercalifragilisticexp.wav"]),
        ({}, ["rope.extra.wav"], [], ["body.current_dir", "rope.extra.wav"]),
        ({}, ["rope.0.wav"], [], ["body.current_dir", "rope.0.wav"]),
        ({}, ["rope.sentence.1.wav"], [], ["body.current_dir", "rope.sentence.1.wav"]),
        ({}, [], [], ["body.current_dir", "nothing to ask"]),
        ({"current_dir": "../etc"}, ["rope.wav"], [], ["body.current_dir", ".."]),
        ({"current_dir": "/etc"}, ["rope.wav"], [], ["body.current_dir"]),
        ({"current_dir": "spelling/missing"}, ["rope.wav"], [], ["body.current_dir", "not a directory"]),
        ({"current_dir": 5}, ["rope.wav"], [], ["body.current_dir"]),
        ({"revision_required": 2}, ["rope.wav"], None, ["body.revision_dir", "not a directory"]),
        ({"maximum_replays": -1}, ["rope.wav"], [], ["body.maximum_replays"]),
        ({"maximum_sentence_plays": 1.5}, ["rope.wav"], [], ["body.maximum_sentence_plays"]),
        ({"current_required": 4}, ["rope.wav", "cat.wav", "dog.wav"], [], ["body.current_required", "only 3"]),
        ({"current_required": -1}, ["rope.wav"], [], ["body.current_required"]),
        ({"revision_required": 3}, ["rope.wav"], ["cat.wav", "dog.wav"], ["body.revision_required", "only 2"]),
        ({"current_required": 0, "revision_required": 0}, [], ["cat.wav"], ["body.current_dir", "nothing to ask"]),
        ({"timeout": 30}, ["rope.wav"], [], ["body.timeout"]),
        ({"timeout": "0s"}, ["rope.wav"], [], ["body.timeout"]),
        ({"letter_pause": 0}, ["rope.wav"], [], ["body.letter_pause", "bare number"]),
        ({"word_pause": "-1ms"}, ["rope.wav"], [], ["body.word_pause"]),
        ({"word_pause": "soon"}, ["rope.wav"], [], ["body.word_pause"]),
        ({"colour": "blue"}, ["rope.wav"], [], ["body.colour"]),
    ],
)
def test_bad_configuration_fails_the_load_and_keeps_the_previous_policy(
    tmp_path, data, any_length, body, current, revision, expected
):
    _words(data, "spelling/current", "good")
    good = _policy(tmp_path / "good", {})
    shutil.rmtree(data / "spelling")
    _files(data, "spelling/current", *current)
    if revision is not None:
        _files(data, "spelling/revision", *revision)
    path = _write(tmp_path / "bad", _house(body))
    with pytest.raises(ConfigError) as raised:
        load(path, previous=good)
    message = str(raised.value)
    assert "'spelling/words'" in message
    for fragment in expected:
        assert fragment in message
    assert good.task(TaskKey("spelling", "words")).document() == {}


@pytest.mark.parametrize(
    ("first", "second", "field", "other"),
    [
        ("current", "revision", "revision_dir", "current_dir"),
        ("current", "attic", "attic_dir", "current_dir"),
        ("revision", "attic", "attic_dir", "revision_dir"),
    ],
)
def test_a_word_in_two_pools_fails_the_load_naming_the_task_the_field_and_both_files(
    tmp_path, data, first, second, field, other
):
    _words(data, "spelling/current", "cat")
    good = _policy(tmp_path / "good", {})
    _words(data, f"spelling/{first}", "rope")
    _files(data, f"spelling/{second}", "Rope.wav")
    with pytest.raises(ConfigError) as raised:
        load(_write(tmp_path / "bad", _house({})), previous=good)
    assert f"task 'spelling/words': body.{field}: Rope.wav is also in {other} as rope.wav; a word belongs to one pool" in str(
        raised.value
    )


def test_the_same_entry_in_the_attic_fails_the_load_with_the_file_named_once(tmp_path, data):
    _words(data, "spelling/current", "rope", "cat")
    _words(data, "spelling/attic", "rope")
    with pytest.raises(ConfigError, match=r"body\.attic_dir: rope\.wav is also in current_dir; a word belongs to one pool"):
        _policy(tmp_path, {})


def test_homographs_may_be_in_different_pools(data):
    _words(data, "spelling/current", "read.1")
    _words(data, "spelling/attic", "read.2")
    assert [word.key for word in check_body({}).current] == ["read.1"]


def test_the_attic_may_be_missing_and_its_words_are_never_asked(tmp_path, data):
    _words(data, "spelling/current", "rope")
    pools = check_body({"attic_dir": "spelling/old-words"})
    assert [word.key for word in pools.current] == ["rope"]
    _words(data, "spelling/old-words", "owl")
    pools = check_body({"attic_dir": "spelling/old-words"})
    assert [word.key for word in (*pools.current, *pools.revision)] == ["rope"]


@pytest.mark.parametrize(
    ("body", "files", "expected"),
    [
        ({"attic_dir": "/var/words"}, [], "body.attic_dir: must be a relative path"),
        ({"attic_dir": "spelling/../../etc"}, [], "body.attic_dir: must be a relative path"),
        ({}, ["rope two.opus"], "body.attic_dir: rope two.opus"),
    ],
)
def test_a_bad_attic_fails_the_load_as_the_other_pools_do(tmp_path, data, any_length, body, files, expected):
    _words(data, "spelling/current", "cat")
    _files(data, "spelling/attic", *files)
    with pytest.raises(ConfigError) as raised:
        _policy(tmp_path, body)
    assert expected in str(raised.value)


def test_a_load_without_task_data_skips_the_pools_but_still_checks_the_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYWARDEN_DATA_DIR", str(tmp_path / "not-mounted"))
    body = {"timeout": "30s", "revision_required": 10}
    path = _write(tmp_path / "policy", _house(body))
    with pytest.raises(ConfigError, match="body.revision_dir"):
        load(path)
    loaded = load(path, task_data=False)
    assert loaded is not None
    assert loaded.task(TaskKey("spelling", "words")).document() == body
    bad = _write(tmp_path / "bad", _house({"colour": "blue"}))
    with pytest.raises(ConfigError, match="body.colour"):
        load(bad, task_data=False)


def test_the_observations_service_loads_a_spelling_policy_without_the_data_directory(tmp_path, monkeypatch):
    from policy import observations

    monkeypatch.setenv("DAYWARDEN_DATA_DIR", str(tmp_path / "not-mounted"))
    path = _write(tmp_path / "policy", _house({"revision_required": 10}))
    policy = observations._load_policy(path)
    assert policy is not None
    assert policy.task(TaskKey("spelling", "words")).document() == {"revision_required": 10}


def test_pool_problems_lists_every_problem_in_a_directory_and_scan_pool_raises_the_first(data, any_length):
    folder = data / "spelling/current"
    _files(data, "spelling/current", "cat.wav", "rope.opus", "rope.mp3", "dog.sentence.wav", "rope1.wav", "notes.txt")
    problems = spelling.pool_problems(folder, "words")
    assert problems == [
        "words: rope.mp3 and rope.opus are both the word clip for rope",
        "words: rope1.wav: a word may only have the letters a to z, - and '",
        "words: dog.sentence.wav has no word clip beside it",
    ]
    with pytest.raises(ValueError) as raised:
        spelling.scan_pool(folder, "words")
    assert str(raised.value) == problems[0]
    for name in ("rope.mp3", "rope1.wav", "dog.sentence.wav"):
        (folder / name).unlink()
    assert spelling.pool_problems(folder, "words") == []


def test_unchanged_recordings_are_not_read_again_and_changed_ones_are(data, monkeypatch):
    _words(data, "spelling/current", "rope", "cat")
    real = spelling.read_audio_ms
    reads = []

    def counting(path, field):
        if path.parent.name == "current":
            reads.append(path.name)
        return real(path, field)

    monkeypatch.setattr(spelling, "read_audio_ms", counting)
    check_body({})
    assert sorted(reads) == ["cat.wav", "rope.wav"]
    reads.clear()
    check_body({})
    assert reads == []
    write_wav(data / "spelling/current/rope.wav", 1200)
    pools = check_body({})
    assert reads == ["rope.wav"]
    assert {word.key: word.clip.ms for word in pools.current}["rope"] == 1200


def test_a_new_recording_arrives_with_the_next_run_and_not_during_one(data):
    _words(data, "spelling/current", "rope")
    session = _session()
    assert [word["key"] for word in session.current_run["words"][CURRENT]] == ["rope"]
    _words(data, "spelling/current", "cat")
    session.visit(START + timedelta(minutes=30))
    assert session.current_run["current_total"] == 1
    session.visit(START + timedelta(hours=2))
    assert len(session.detail["runs"]) == 2
    assert session.current_run["current_total"] == 2
    assert sorted(key for _pool, key in session.current_run["queue"]) == ["cat", "rope"]


def test_a_pool_broken_after_the_load_keeps_the_last_good_words(data):
    _words(data, "spelling/current", "rope", "cat")
    check_body({})
    _files(data, "spelling/current", "rope.mp3")
    session = _session()
    assert session.current_run["current_total"] == 2


# Audio tokens


@pytest.mark.parametrize("length", range(1, 23))
@pytest.mark.parametrize("pool", [CURRENT, REVISION])
def test_the_scrambled_buffer_hides_every_character_and_reads_back(length, pool):
    rng = random.Random(length)
    for trial in range(40):
        key = "".join(rng.choice("abcdefghijklmnopqrstuvwxyzABCZ-'") for _ in range(length))
        buffer = scramble(key, pool, rng)
        m = length + 1
        assert len(buffer) == 24
        assert all(value in PADDING_BYTES for value in buffer[m:])
        header = (0x80 if pool == REVISION else 0) | length
        assert buffer[0] != header
        for position, character in enumerate(key.encode("ascii"), start=1):
            assert buffer[position] != character
        assert descramble(buffer) == (pool, key)
        text = token(key, pool, rng)
        assert len(text) == 32
        assert set(text) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
        assert untoken(text) == (pool, key)


def test_homograph_keys_read_back_with_their_number():
    rng = random.Random(3)
    assert untoken(token("read.2", CURRENT, rng)) == (CURRENT, "read.2")


def test_the_padding_alphabet_has_182_bytes_with_three_to_five_bits_set():
    assert len(PADDING_BYTES) == 182
    assert all(3 <= value.bit_count() <= 5 for value in PADDING_BYTES)


def test_a_damaged_or_invented_token_reads_as_nothing():
    rng = random.Random(9)
    good = bytearray(scramble("rope", CURRENT, rng))
    assert descramble(bytes(good[:23])) is None
    bad_padding = bytearray(good)
    bad_padding[10] = 0xFF
    assert descramble(bytes(bad_padding)) is None
    assert descramble(bytes(24)) is None
    assert untoken("not-a-token") is None
    assert untoken("A" * 31 + "=") is None
    assert read_media_name(token("rope", CURRENT, rng) + ".txt") is None
    assert read_media_name(token("rope", CURRENT, rng) + ".words.wav") is None
    assert read_media_name(token("rope", REVISION, rng) + ".sentence.MP3") == (REVISION, "rope", True, "mp3")


# Queue and drawing rules


def test_the_opening_queue_is_every_current_word_and_a_random_draw_of_revision_words(data):
    _words(data, "spelling/current", "rope", "cat", "dog", "fish")
    _words(data, "spelling/revision", *[f"old{letter}" for letter in "abcdefghij"])
    queues = []
    for seed in range(30):
        queue = _session({"revision_required": 3}, seed).current_run["queue"]
        current = sorted(key for pool, key in queue if pool == CURRENT)
        revision = [key for pool, key in queue if pool == REVISION]
        assert current == ["cat", "dog", "fish", "rope"]
        assert len(revision) == len(set(revision)) == 3
        queues.append(tuple(map(tuple, queue)))
    assert len(set(queues)) > 20
    assert _session({"revision_required": 3}, 7).current_run["queue"] == _session(
        {"revision_required": 3}, 7
    ).current_run["queue"]
    seen = {key for queue in queues for pool, key in queue if pool == REVISION}
    assert len(seen) == 10


def test_a_right_spelling_ignores_case_and_spaces_and_scores_only_its_pool(data):
    _words(data, "spelling/current", "rope")
    _words(data, "spelling/revision", "Cat")
    session = _session()
    expected = {CURRENT: 0, REVISION: 0}
    for _ in range(2):
        question = session.issue(START)
        typed = "  " + question["word"].swapcase() + " "
        judged = session.answer(START + timedelta(seconds=3), len(session.questions) - 1, typed, expired=False)
        assert judged.outcome == "correct"
        expected[question["pool"]] += 1
        assert session.scores() == expected


def test_a_missed_current_word_goes_to_the_back_while_the_target_is_short(data):
    _words(data, "spelling/current", "rope", "cat", "dog")
    session = _session({"current_required": 2})
    question = session.issue(START)
    judged = _answer_pending(session, START + timedelta(seconds=2), right=False)
    assert judged.outcome == "incorrect"
    assert judged.question["requeued"] is True
    assert judged.word is None
    assert session.current_run["queue"][-1] == [CURRENT, question["key"]]
    session.issue(START + timedelta(seconds=5))
    timed_out = _answer_pending(session, START + timedelta(seconds=40), right=True)
    assert timed_out.outcome == "timeout"
    assert timed_out.question["requeued"] is True


def test_once_the_current_target_is_met_a_missed_word_is_shown_and_not_asked_again(data):
    _words(data, "spelling/current", "rope", "cat", "dog")
    session = _session({"current_required": 1})
    session.issue(START)
    _answer_pending(session, START + timedelta(seconds=2), right=True)
    question = session.issue(START + timedelta(seconds=5))
    judged = _answer_pending(session, START + timedelta(seconds=7), right=False)
    assert judged.question["requeued"] is False
    assert judged.word == question["word"]
    assert [CURRENT, question["key"]] not in session.current_run["queue"]
    session.issue(START + timedelta(seconds=10))
    judged = _answer_pending(session, START + timedelta(seconds=12), right=False)
    assert judged.verdict == "pass"


def test_a_missed_revision_word_is_replaced_by_another_not_yet_right_or_waiting(data):
    _words(data, "spelling/current", "rope")
    _words(data, "spelling/revision", "cat", "dog", "fish", "bird")
    session = _session({"current_required": 0, "revision_required": 2}, seed=4)
    run = session.current_run
    run["queue"] = [[REVISION, "cat"], [REVISION, "dog"], [CURRENT, "rope"]]
    session.issue(START)
    _answer_pending(session, START + timedelta(seconds=2), right=True)
    session.issue(START + timedelta(seconds=5))
    judged = _answer_pending(session, START + timedelta(seconds=7), right=False)
    assert judged.question["requeued"] is False
    assert judged.word == "dog"
    added = run["queue"][-1]
    assert added[0] == REVISION
    assert added[1] in {"fish", "bird"}


def test_with_no_other_revision_word_the_missed_one_comes_back_unseen(data):
    _words(data, "spelling/current", "rope")
    _words(data, "spelling/revision", "cat")
    session = _session({"current_required": 0, "revision_required": 1})
    run = session.current_run
    run["queue"] = [[REVISION, "cat"], [CURRENT, "rope"]]
    session.issue(START)
    judged = _answer_pending(session, START + timedelta(seconds=2), right=False)
    assert judged.question["requeued"] is True
    assert judged.word is None
    assert run["queue"] == [[CURRENT, "rope"], [REVISION, "cat"]]


def test_a_missed_revision_word_after_the_revision_target_is_not_replaced(data):
    _words(data, "spelling/current", "rope")
    _words(data, "spelling/revision", "cat", "dog", "fish")
    session = _session({"revision_required": 1})
    run = session.current_run
    run["queue"] = [[REVISION, "cat"], [REVISION, "dog"], [CURRENT, "rope"]]
    session.issue(START)
    _answer_pending(session, START + timedelta(seconds=2), right=True)
    session.issue(START + timedelta(seconds=5))
    judged = _answer_pending(session, START + timedelta(seconds=7), right=False)
    assert judged.question["requeued"] is False
    assert judged.word == "dog"
    assert run["queue"] == [[CURRENT, "rope"]]


def test_seven_of_ten_still_asks_the_last_three_current_words(data):
    current = ["ant", "bee", "cow", "dog", "eel", "fox", "gnu", "hen", "ibis", "jay"]
    _words(data, "spelling/current", *current)
    _words(data, "spelling/revision", "old")
    session = _session({"current_required": 7, "revision_required": 1})
    session.current_run["queue"] = [[REVISION, "old"]] + [[CURRENT, key] for key in current]
    now = START
    verdicts = []
    for _ in range(11):
        session.issue(now)
        now += timedelta(seconds=2)
        verdicts.append(_answer_pending(session, now, right=True).verdict)
        now += timedelta(seconds=2)
    assert session.scores() == {CURRENT: 10, REVISION: 1}
    assert verdicts == [None] * 10 + ["pass"]
    asked = [question["key"] for question in session.questions]
    assert asked == ["old", *current]


def test_the_attempt_never_runs_out_of_words_before_it_passes(data):
    _words(data, "spelling/current", "ant", "bee", "cow", "dog")
    _words(data, "spelling/revision", "eel", "fox", "gnu")
    rng = random.Random(11)
    for seed in range(25):
        session = _session({"current_required": 3, "revision_required": 2}, seed)
        now = START
        verdict = None
        for _ in range(200):
            session.issue(now)
            now += timedelta(seconds=1)
            verdict = _answer_pending(session, now, right=rng.random() < 0.4).verdict
            if verdict:
                break
        assert verdict == "pass"


# Server timing and replays


def test_the_server_allows_the_word_clip_its_play_allowance_and_the_timeout_plus_the_network_allowance(data):
    _words(data, "spelling/current", "rope", "cat")
    session = _session()
    question = session.issue(START)
    assert question["allowed_ms"] == WORD_MS + PLAY_ALLOWANCE_MS + TIMEOUT_MS
    edge = START + timedelta(milliseconds=WORD_MS + PLAY_ALLOWANCE_MS + TIMEOUT_MS + NETWORK_ALLOWANCE_MS)
    assert _answer_pending(session, edge, right=True).outcome == "correct"
    later = edge + timedelta(seconds=5)
    session.issue(later)
    late = later + timedelta(milliseconds=WORD_MS + PLAY_ALLOWANCE_MS + TIMEOUT_MS + NETWORK_ALLOWANCE_MS + 1)
    judged = _answer_pending(session, late, right=True)
    assert judged.outcome == "timeout"
    assert judged.question["answer"] is not None


def test_a_right_spelling_sent_when_the_timer_runs_out_counts_despite_the_wait_for_the_word_to_play(data):
    """Fetching and starting the clip, and both requests, put the browser's timer about 1.3 s behind the server."""
    _words(data, "spelling/current", "rope", "cat")
    session = _session()
    session.issue(START)
    sent = START + timedelta(milliseconds=WORD_MS + TIMEOUT_MS + 1_300)
    assert _answer_pending(session, sent, right=True, expired=True).outcome == "correct"


def test_each_replay_brings_its_own_play_allowance(data):
    _words(data, "spelling/current", "rope", sentences={"rope"})
    session = _session({"maximum_replays": 2, "maximum_sentence_plays": 1})
    session.issue(START)
    number = len(session.questions) - 1
    lag = timedelta(milliseconds=1_300)
    at = START + timedelta(milliseconds=WORD_MS) + lag + timedelta(seconds=5)
    for clip, length in (("word", WORD_MS), ("word", WORD_MS), ("sentence", SENTENCE_MS)):
        session.replay(at, number, clip)
        at += timedelta(milliseconds=length) + lag + timedelta(seconds=5)
    sent = at + timedelta(milliseconds=TIMEOUT_MS - 4 * 5_000)
    assert _answer_pending(session, sent, right=True, expired=True).outcome == "correct"


def test_each_replay_extends_the_deadline_by_that_clip_up_to_its_limit(data):
    _words(data, "spelling/current", "rope", sentences={"rope"})
    session = _session({"maximum_replays": 2, "maximum_sentence_plays": 1})
    session.issue(START)
    number = len(session.questions) - 1
    session.replay(START + timedelta(seconds=2), number, "word")
    session.replay(START + timedelta(seconds=4), number, "word")
    with pytest.raises(ValueError, match="no more word plays"):
        session.replay(START + timedelta(seconds=5), number, "word")
    session.replay(START + timedelta(seconds=6), number, "sentence")
    with pytest.raises(ValueError, match="no more sentence plays"):
        session.replay(START + timedelta(seconds=7), number, "sentence")
    pending = session.pending
    assert (pending["word_replays"], pending["sentence_plays"]) == (2, 1)
    assert pending["allowed_ms"] == WORD_MS * 3 + SENTENCE_MS + 4 * PLAY_ALLOWANCE_MS + TIMEOUT_MS
    in_time = START + timedelta(milliseconds=pending["allowed_ms"] + NETWORK_ALLOWANCE_MS)
    assert _answer_pending(session, in_time, right=True).outcome == "correct"


@pytest.mark.parametrize(
    ("body", "sentences", "clip", "message"),
    [
        ({}, set(), "sentence", "no sentence clip"),
        ({"maximum_replays": 0}, set(), "word", "no more word plays"),
        ({"maximum_sentence_plays": 0}, {"rope"}, "sentence", "no more sentence plays"),
        ({}, set(), "music", "clip must be"),
    ],
)
def test_a_replay_that_is_not_allowed_is_refused_without_more_time(data, body, sentences, clip, message):
    _words(data, "spelling/current", "rope", sentences=sentences)
    session = _session(body)
    session.issue(START)
    with pytest.raises(ValueError, match=message):
        session.replay(START + timedelta(seconds=1), 0, clip)
    assert session.pending["allowed_ms"] == WORD_MS + PLAY_ALLOWANCE_MS + TIMEOUT_MS


def test_a_replay_after_the_time_is_up_is_refused(data):
    _words(data, "spelling/current", "rope")
    session = _session()
    session.issue(START)
    with pytest.raises(ValueError, match="time for this question is up"):
        session.replay(START + timedelta(seconds=40), 0, "word")


@pytest.mark.parametrize(("typed", "outcome"), [("right", "correct"), ("wrong", "timeout"), ("", "timeout")])
def test_when_the_timer_runs_out_the_box_is_judged(data, typed, outcome):
    _words(data, "spelling/current", "rope", "cat")
    session = _session()
    question = session.issue(START)
    text = {"right": question["word"], "wrong": "zzz", "": ""}[typed]
    judged = session.answer(START + timedelta(seconds=30), 0, text, expired=True)
    assert judged.outcome == outcome
    assert judged.question["answer"] == (text or None)


def test_an_empty_box_is_not_an_answer_unless_the_timer_ran_out(data):
    _words(data, "spelling/current", "rope")
    session = _session()
    session.issue(START)
    with pytest.raises(ValueError, match="empty"):
        session.answer(START + timedelta(seconds=3), 0, "   ", expired=False)
    assert session.pending is not None


# The page and its requests


class Quiz:
    """One child working through the words task, on a clock the test sets."""

    def __init__(self, directory: Path, body: dict | None = None, *, extra: str = "", due=None, rules=None, sites=""):
        self.policy = _policy(directory / "policy", body or {}, extra=extra, due=due, rules=rules, sites=sites)
        self.saved = PolicyStore(":memory:")
        self.store = AttemptStore(connection=self.saved.connection)
        self.sounds = load_sounds(_sound_dir(directory / "sounds"), warn=lambda message: None)
        self.back = None
        self.now = START

    def _respond(self, now, method, query=None, body=b""):
        return respond_task(
            self.policy,
            self.store,
            method=method,
            path="/tasks/spelling/words",
            client_ip=YOUNGER,
            now=now,
            query=query,
            body=body,
            sounds=self.sounds,
            back=self.back,
        )

    def open(self, now):
        self.now = now
        page = self._respond(now, "GET")
        status, payload = self.post(now, "visit", {})
        assert status == 200, payload
        return page

    def give_up(self, now):
        return self._respond(now, "POST")

    def post(self, now, action, payload):
        page = self._respond(now, "POST", {"do": action}, json.dumps(payload).encode())
        assert ("content-type", "application/json") in page.headers
        return page.status, json.loads(page.body)

    def ask(self, now) -> dict:
        status, payload = self.post(now, "question", {})
        assert status == 200, payload
        return payload

    def answer(self, now, number, text, *, expired=False) -> dict:
        status, payload = self.post(now, "answer", {"id": number, "answer": text, "expired": expired})
        assert status == 200, payload
        return payload

    def attempt(self):
        return self.store.attempts("younger", TaskKey("spelling", "words"))[-1]

    def detail(self):
        return self.attempt().detail

    def question(self) -> dict:
        return self.detail()["questions"][-1]

    def expected(self) -> str:
        return self.question()["word"]

    def spell(self, right: bool, *, seconds: float = 3) -> dict:
        """Ask the next word and spell it right or wrong."""
        question = self.ask(self.now)
        self.now += timedelta(seconds=seconds)
        result = self.answer(self.now, question["id"], self.expected() if right else "zzz")
        self.now += timedelta(seconds=3)
        return result


def _sound_dir(root: Path) -> Path:
    for outcome, names in {"correct": ["a.mp3"], "incorrect": ["x.m4a"], "timeout": ["bell.opus"]}.items():
        (root / outcome).mkdir(parents=True, exist_ok=True)
        for name in names:
            (root / outcome / name).write_bytes(b"sound")
    return root


def test_the_start_screen_shows_both_targets(tmp_path, data):
    _words(data, "spelling/current", "rope", "cat", "dog")
    _words(data, "spelling/revision", "old", "new")
    quiz = Quiz(tmp_path, {"current_required": 2})
    page = quiz.open(START)
    assert "Current: 0 / 2 \u00b7 Revision: 0 / 2" in page.body
    assert "Repeat word" in page.body
    assert "Use in a sentence" in page.body


def test_a_question_carries_audio_urls_and_never_the_word_or_its_length(tmp_path, data):
    _words(data, "spelling/current", "extemporaneously", sentences={"extemporaneously"})
    quiz = Quiz(tmp_path)
    quiz.open(START)
    question = quiz.ask(START)
    assert "extemporaneously" not in json.dumps(question).lower()
    assert set(question) == {
        "id",
        "word_url",
        "word_ms",
        "sentence_url",
        "sentence_ms",
        "timeout_ms",
        "maximum_replays",
        "maximum_sentence_plays",
        "current",
        "current_required",
        "revision",
        "revision_required",
        "finished",
    }
    word_name = question["word_url"].rsplit("/", 1)[1]
    sentence_name = question["sentence_url"].rsplit("/", 1)[1]
    assert question["word_url"].startswith("/tasks/spelling/words/audio/")
    assert len(word_name) == len("x" * 32 + ".wav")
    assert sentence_name.endswith(".sentence.wav") and len(sentence_name) == 32 + len(".sentence.wav")
    assert read_media_name(word_name) == (CURRENT, "extemporaneously", False, "wav")
    assert question["word_ms"] == WORD_MS
    assert question["sentence_ms"] == SENTENCE_MS
    assert question["timeout_ms"] == TIMEOUT_MS
    assert (question["maximum_replays"], question["maximum_sentence_plays"]) == (3, 2)


def test_a_word_without_a_sentence_has_no_sentence_url(tmp_path, data):
    _words(data, "spelling/current", "rope")
    quiz = Quiz(tmp_path)
    quiz.open(START)
    assert quiz.ask(START)["sentence_url"] is None


def test_replays_through_the_page_extend_the_time_and_stop_at_the_limit(tmp_path, data):
    _words(data, "spelling/current", "rope", sentences={"rope"})
    quiz = Quiz(tmp_path, {"maximum_replays": 1})
    quiz.open(START)
    question = quiz.ask(START)
    status, payload = quiz.post(START + timedelta(seconds=2), "replay", {"id": question["id"], "clip": "word"})
    assert (status, payload) == (200, {"word_replays": 1, "sentence_plays": 0})
    status, payload = quiz.post(START + timedelta(seconds=3), "replay", {"id": question["id"], "clip": "word"})
    assert status == 400
    assert quiz.question()["allowed_ms"] == WORD_MS * 2 + 2 * PLAY_ALLOWANCE_MS + TIMEOUT_MS
    status, _payload = quiz.post(START + timedelta(seconds=4), "replay", {"id": question["id"] + 5, "clip": "word"})
    assert status == 409


def test_wrong_and_timeout_feedback_show_the_word_only_when_it_will_not_come_back(tmp_path, data):
    _words(data, "spelling/current", "rope", "cat", "dog")
    quiz = Quiz(tmp_path, {"current_required": 1})
    quiz.open(START)
    first = quiz.spell(False)
    assert first["outcome"] == "incorrect"
    assert first["word"] is None
    assert first["sound"].startswith("/static/sounds/incorrect/")
    assert quiz.spell(True)["outcome"] == "correct"
    question = quiz.ask(quiz.now)
    result = quiz.answer(quiz.now + timedelta(seconds=30), question["id"], "", expired=True)
    assert result["outcome"] == "timeout"
    assert result["sound"].startswith("/static/sounds/timeout/")
    assert result["word"] == quiz.expected()
    assert result["result"] == "pass"


def test_passing_reports_each_missed_word_once_and_counts_the_pass(tmp_path, data):
    _words(data, "spelling/current", "read.1", "read.2", "cat")
    quiz = Quiz(tmp_path)
    quiz.open(START)
    results = []
    for _ in range(30):
        right = len(quiz.detail().get("questions", [])) >= 3
        results.append(quiz.spell(right))
        if results[-1]["finished"]:
            break
    last = results[-1]
    assert last["result"] == "pass"
    assert last["sound"].startswith("/static/sounds/correct/")
    assert sorted(last["missed"]) == ["cat", "read"]
    assert quiz.attempt().outcome == "pass"
    assert quiz.store.passes_on("younger", START.date()) == 1


BACK = "https://www.youtube.com/watch?v=abc123"


def test_a_pass_carries_the_page_to_go_back_to(tmp_path, data):
    _words(data, "spelling/current", "rope")
    quiz = Quiz(tmp_path)
    quiz.back = lambda: BACK
    quiz.open(START)
    first = quiz.spell(False)
    assert (first["finished"], first["back"]) == (False, None)
    for _ in range(5):
        last = quiz.spell(True)
        if last["finished"]:
            break
    assert (last["result"], last["back"], last["missed"]) == ("pass", BACK, ["rope"])


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to run the page script")
@pytest.mark.parametrize(
    ("missed", "steps", "gone"),
    [
        ([], [{"wait": 10_000}], [(5000, BACK)]),
        (["rope"], [{"wait": 10_000}, {"click": "missed-continue"}, {"wait": 10_000}], [(15_000, BACK)]),
        (["rope"], [{"wait": 10_000}, {"key": ["missed-continue", "Enter"]}, {"wait": 10_000}], [(15_000, BACK)]),
    ],
    ids=["clean pass", "continue", "enter on continue"],
)
def test_the_countdown_starts_when_well_done_shows(tmp_path, data, missed, steps, gone):
    _words(data, "spelling/current", "rope")
    page = Quiz(tmp_path).open(START).body
    progress = {"current": 1, "current_required": 1, "revision": 0, "revision_required": 0}
    replies = {"visit": [{**progress, "finished": True, "result": "pass", "next": None, "back": BACK, "missed": missed}]}
    events = _harness(page, replies, steps=steps)
    assert [(event["at"], event["what"]) for event in events if event["kind"] == "navigate"] == gone


def test_a_clean_pass_has_no_missed_words(tmp_path, data):
    _words(data, "spelling/current", "rope")
    quiz = Quiz(tmp_path)
    quiz.open(START)
    result = quiz.spell(True)
    assert result["finished"] is True
    assert result["missed"] == []


def test_reloading_closes_the_open_question_as_a_timeout_and_puts_it_back(tmp_path, data):
    _words(data, "spelling/current", "rope", "cat")
    quiz = Quiz(tmp_path)
    quiz.open(START)
    question = quiz.ask(START)
    key = quiz.question()["key"]
    page = quiz.open(START + timedelta(seconds=5))
    stored = quiz.detail()["questions"][question["id"]]
    assert stored["outcome"] == "timeout"
    assert stored["requeued"] is True
    assert quiz.detail()["runs"][-1]["queue"][-1] == [CURRENT, key]
    assert len(quiz.detail()["runs"]) == 1
    assert "Current: 0 / 2" in page.body


def test_giving_up_shows_the_missed_words_including_the_one_left_showing(tmp_path, data):
    _words(data, "spelling/current", "rope", "cat", "dog")
    other = """\
  arithmetic:
    sums:
      group: younger
      pass_cooldown: 0
      body: { operation: addition, max_timeout: 10s, min_timeout: 4s, correct_answers_required: 2, operands: [{ value: 1, weight: 1 }] }
"""
    quiz = Quiz(tmp_path, extra=other)
    quiz.open(START)
    quiz.spell(False)
    missed = quiz.expected()
    quiz.ask(quiz.now)
    showing = quiz.expected()
    page = quiz.give_up(quiz.now + timedelta(seconds=2))
    assert page.status == 200
    assert quiz.attempt().outcome == "abandoned"
    assert "Words to practise" in page.body
    assert f"<li>{missed}</li>" in page.body
    assert f"<li>{showing}</li>" in page.body
    assert 'const next = "https://tasks.example/tasks/choose";' in page.body
    assert '<html lang="en" data-palette="practice">' not in page.body


def test_the_missed_words_after_giving_up_practice_keep_the_practice_palette_and_line(tmp_path, data):
    _words(data, "spelling/current", "rope", "cat", "dog")
    quiz = Quiz(tmp_path)
    quiz.store.record("younger", TaskKey("spelling", "words"), "pass", START - timedelta(hours=2))
    quiz.open(START)
    assert quiz.attempt().task_set == "practice"
    quiz.spell(False)
    page = quiz.give_up(quiz.now + timedelta(seconds=2))
    assert "Words to practise" in page.body
    assert '<html lang="en" data-palette="practice">' in page.body
    assert html.escape(PRACTICE_LINE) in page.body
    assert '<link rel="icon" type="image/png" href="/favicon.png">' in page.body


def test_giving_up_with_nothing_missed_goes_straight_to_the_selector(tmp_path, data):
    _words(data, "spelling/current", "rope", "cat")
    quiz = Quiz(tmp_path)
    quiz.open(START)
    page = quiz.give_up(START + timedelta(seconds=2))
    assert quiz.attempt().outcome == "abandoned"
    assert "Words to practise" not in page.body
    assert page.status == 302
    assert ("location", "https://tasks.example/tasks/choose") in page.headers


def test_a_required_spelling_task_keeps_its_progress_when_he_tries_to_give_up(tmp_path, data):
    _words(data, "spelling/current", "rope", "cat")
    quiz = Quiz(tmp_path, due="2026-11-01")
    quiz.open(START)
    quiz.spell(True)
    quiz.ask(quiz.now)
    page = quiz.give_up(quiz.now + timedelta(seconds=2))
    assert MUST_FINISH in page.body
    assert "Current: 1 / 2" in page.body
    assert quiz.attempt().outcome == "in_progress"
    assert quiz.question()["outcome"] == "timeout"


def test_each_question_is_stored_in_full_and_shown_in_the_attempt_view(tmp_path, data):
    _words(data, "spelling/current", "rope", sentences={"rope"})
    quiz = Quiz(tmp_path)
    quiz.open(START)
    question = quiz.ask(START)
    quiz.post(START + timedelta(seconds=1), "replay", {"id": question["id"], "clip": "sentence"})
    quiz.answer(START + timedelta(milliseconds=4_250), question["id"], " Rope ")
    stored = quiz.question()
    assert stored == {
        "run": 1,
        "key": "rope",
        "word": "rope",
        "pool": "current",
        "sentence": True,
        "word_replays": 0,
        "sentence_plays": 1,
        "answer": "Rope",
        "outcome": "correct",
        "requeued": False,
        "timeout_ms": TIMEOUT_MS,
        "allowed_ms": WORD_MS + SENTENCE_MS + 2 * PLAY_ALLOWANCE_MS + TIMEOUT_MS,
        "received_ms": 4_250,
        "issued": "2026-11-02T16:00:00.000-05:00",
    }
    run = quiz.detail()["runs"][0]
    assert (run["current_total"], run["current_required"], run["revision_required"]) == (1, 1, 0)
    page = json.dumps(attempt_report(quiz.store, str(quiz.attempt().id), now=START))
    assert "sentence_plays" in page
    assert "requeued" in page
    assert "4250" in page


# Audio through the proxy and the service


def test_word_audio_is_served_for_a_task_passed_today_but_not_for_another_groups_task(tmp_path, data):
    _words(data, "spelling/current", "rope")
    other = """\
  spelling:
    theirs:
      group: default
      pass_cooldown: 0
"""
    quiz = Quiz(tmp_path, extra=other)
    quiz.store.record("younger", TaskKey("spelling", "words"), "pass", START - timedelta(hours=1))
    assert not quiz.store.task_sets(quiz.policy.tasks, "younger", START.date()).available
    name = token("rope", CURRENT, random.Random(1)) + ".wav"
    found = task_media(quiz.policy, quiz.store, path=f"/tasks/spelling/words/audio/{name}", client_ip=YOUNGER, now=START)
    assert found is not None and found.name.startswith("rope")
    elsewhere = task_media(quiz.policy, quiz.store, path=f"/tasks/spelling/theirs/audio/{name}", client_ip=YOUNGER, now=START)
    assert elsewhere is None


@pytest.mark.parametrize("pool", ["revision", "attic"])
def test_a_word_moved_or_retired_during_a_run_still_plays_for_the_rest_of_it(tmp_path, data, pool):
    _words(data, "spelling/current", "rope", sentences={"rope"})
    quiz = Quiz(tmp_path)
    quiz.open(START)
    question = quiz.ask(START)
    for name in ("rope.wav", "rope.sentence.wav"):
        target = data / "spelling" / pool / name
        target.parent.mkdir(parents=True, exist_ok=True)
        (data / "spelling/current" / name).rename(target)
    for url in (question["word_url"], question["sentence_url"]):
        found = task_media(quiz.policy, quiz.store, path=url, client_ip=YOUNGER, now=START)
        assert found is not None and found.parent == data / "spelling" / pool


def test_a_run_keeps_playing_its_words_after_the_task_points_at_other_directories_and_the_next_run_asks_the_new_ones(tmp_path, data):
    _words(data, "spelling/current", "rope", sentences={"rope"})
    _words(data, "spelling/year-3/current", "frog")
    quiz = Quiz(tmp_path)
    quiz.open(START)
    question = quiz.ask(START)
    quiz.policy = _policy(tmp_path / "moved", {"current_dir": "spelling/year-3/current"})
    for url in (question["word_url"], question["sentence_url"]):
        found = task_media(quiz.policy, quiz.store, path=url, client_ip=YOUNGER, now=START)
        assert found is not None and found.parent == data / "spelling/current"
    later = START + EXPIRY + timedelta(minutes=1)
    quiz.open(later)
    assert len(quiz.detail()["runs"]) == 2
    quiz.ask(later)
    assert quiz.expected() == "frog"


def test_the_service_serves_word_audio_by_token_only(tmp_path, data, monkeypatch):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    _words(data, "spelling/current", "rope", sentences={"rope"})
    policy_file = _write(tmp_path, _house({}))
    monkeypatch.setenv("POLICY_FILE", str(policy_file))
    monkeypatch.setenv("POLICY_DB", str(tmp_path / "policy.sqlite3"))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    monkeypatch.setenv("SOUND_DIR", str(_sound_dir(tmp_path / "sounds")))
    app = create_app()

    status, _headers, body = _call(app, "GET", "/tasks/spelling/words")
    assert status == 200
    assert b"Spelling" in body
    assert _call(app, "POST", "/tasks/spelling/words", query=b"do=visit", body=b"{}")[0] == 200
    status, _headers, body = _call(app, "POST", "/tasks/spelling/words", query=b"do=question", body=b"{}")
    question = json.loads(body)
    status, headers, body = _call(app, "GET", question["word_url"])
    assert status == 200
    assert headers["content-type"].startswith("audio/wav")
    assert body == (data / "spelling/current/rope.wav").read_bytes()
    status, _headers, body = _call(app, "GET", question["sentence_url"])
    assert status == 200
    assert body == (data / "spelling/current/rope.sentence.wav").read_bytes()
    # A word re-recorded in another format during the run still plays (S023.3).
    status, _headers, body = _call(app, "GET", question["word_url"].replace(".wav", ".mp3"))
    assert status == 200
    assert body == (data / "spelling/current/rope.wav").read_bytes()
    assert _call(app, "GET", "/tasks/spelling/words/audio/rope.wav")[0] == 404
    missing = token("cat", CURRENT, random.Random(2))
    assert _call(app, "GET", f"/tasks/spelling/words/audio/{missing}.wav")[0] == 404
    replay = json.dumps({"id": question["id"], "clip": "word"}).encode()
    assert _call(app, "POST", "/tasks/spelling/words", query=b"do=replay", body=replay)[0] == 200
    answer = json.dumps({"id": question["id"], "answer": "rope", "expired": False}).encode()
    status, _headers, body = _call(app, "POST", "/tasks/spelling/words", query=b"do=answer", body=answer)
    assert json.loads(body)["outcome"] == "correct"


def test_the_page_never_holds_a_word(tmp_path, data):
    _words(data, "spelling/current", "quokka")
    quiz = Quiz(tmp_path)
    assert "quokka" not in quiz.open(START).body


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to run the page script")
@pytest.mark.parametrize("outcome", ["correct", "incorrect", "timeout"])
def test_the_next_word_waits_four_seconds_after_the_feedback_sound(tmp_path, data, outcome):
    """The feedback sound can run for several seconds, so the next word must not start over it."""
    _words(data, "spelling/current", "rope", "cat", "dog")
    quiz = Quiz(tmp_path, {"current_required": 3})
    page = quiz.open(START).body
    _status, visit = quiz.post(START, "visit", {})
    first = quiz.ask(START)
    right = outcome == "correct"
    result = quiz.answer(START + timedelta(seconds=2), first["id"], quiz.expected() if right else "zzz", expired=outcome == "timeout")
    assert result["outcome"] == outcome and result["sound"] and not result["finished"]
    second = quiz.ask(START + timedelta(seconds=6))
    replies = {"visit": [visit], "question": [first, second], "answer": [result]}
    events = _harness(page, replies, clip_ms=WORD_MS, run_ms=10_000)
    plays = [event for event in events if event["kind"] == "play"]
    sound = next(event["at"] for event in plays if event["what"] == result["sound"])
    word = next(event["at"] for event in plays if event["what"] == second["word_url"])
    assert word - sound >= 4000
    assert [event["what"] for event in events if event["kind"] == "post"] == ["visit", "question", "answer", "question"]


def _harness(page: str, replies: dict, **options) -> list[dict]:
    """Run the page's script in ``tests/page_harness.js`` and return what it saw."""
    run = subprocess.run(
        ["node", str(ROOT / "tests" / "page_harness.js")],
        input=json.dumps({"html": page, "replies": replies, **options}),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(run.stdout)


# Practice mode (S005.2)


@pytest.mark.parametrize(
    ("current", "revision", "remove", "add", "expected"),
    [
        (["rope"], [], ["q.wav"], [], ["no clip for q"]),
        (["rope"], [], ["b.wav", "x.wav"], [], ["no clip for b, x"]),
        (["well-known"], [], ["dash.wav"], [], ["no clip for dash"]),
        (["rope"], ["don't"], ["apostrophe.wav"], [], ["no clip for apostrophe"]),
        (["rope"], [], [], ["A.mp3"], ["a.wav", "A.mp3", "both the clip for a"]),
        (["rope"], [], [], ["dash.ogg"], ["dash.ogg", "dash.wav"]),
        (["rope"], [], ["*"], [], ["not a directory"]),
    ],
)
def test_the_alphabet_is_checked_when_the_policy_loads(tmp_path, data, any_length, current, revision, remove, add, expected):
    _words(data, "spelling/current", *current)
    _words(data, "spelling/revision", *revision)
    good = _policy(tmp_path / "good", {})
    alphabet = data / "spelling/alphabet"
    if remove == ["*"]:
        shutil.rmtree(alphabet)
    for name in remove if remove != ["*"] else []:
        (alphabet / name).unlink()
    if add:
        _files(data, "spelling/alphabet", *add)
    with pytest.raises(ConfigError) as raised:
        load(_write(tmp_path / "bad", _house({})), previous=good)
    message = str(raised.value)
    assert "'spelling/words'" in message and "body.alphabet_dir" in message
    for fragment in expected:
        assert fragment in message


def test_dash_and_apostrophe_clips_are_needed_only_when_a_word_uses_them(tmp_path, data):
    _words(data, "spelling/current", "rope")
    _words(data, "spelling/revision", "cat")
    alphabet = data / "spelling/alphabet"
    (alphabet / "dash.wav").unlink()
    (alphabet / "apostrophe.wav").unlink()
    (alphabet / "a.wav").rename(alphabet / "A.WAV")
    write_wav(alphabet / "hello.wav")
    (alphabet / "notes.txt").write_text("letters", encoding="utf-8")
    assert sorted(check_body({}).alphabet) == list("abcdefghijklmnopqrstuvwxyz")


def test_the_alphabet_directory_can_be_set_per_task(data):
    _words(data, "spelling/current", "rope")
    shutil.move(data / "spelling/alphabet", data / "letters")
    with pytest.raises(ValueError, match="alphabet_dir"):
        check_body({})
    assert check_body({"alphabet_dir": "letters"}).alphabet["r"].name == "r.wav"


def test_practice_says_the_word_before_and_after_each_of_three_spellings():
    word, letter = 500, 250
    spelled = [("w", word), ("o", letter), ("r", letter), ("d", letter), ("word", word)]
    assert practice_plan("word", letter, word) == [("word", 0), *spelled, *spelled, *spelled]
    plan = practice_plan("Don't-go", 0, 300)
    assert [clip for clip, _pause in plan[1:9]] == ["d", "o", "n", "apostrophe", "t", "dash", "g", "o"]
    assert [clip for clip, _pause in plan].count("word") == 4
    assert len(plan) == 1 + 3 * (len("Don't-go") + 1)


def test_practice_starts_a_new_run_on_the_attempt_and_keeps_the_earlier_answers(data):
    _words(data, "spelling/current", "rope", "cat", "dog")
    session = _session({"current_required": 2})
    session.issue(START)
    _answer_pending(session, START + timedelta(seconds=2), right=True)
    session.issue(START + timedelta(seconds=5))
    _answer_pending(session, START + timedelta(seconds=7), right=False)
    session.issue(START + timedelta(seconds=10))
    earlier = [dict(item) for item in session.questions[:2]]
    session.practice(START + timedelta(seconds=12))
    assert session.questions[:2] == earlier
    assert session.questions[2]["outcome"] == "timeout"
    assert len(session.detail["runs"]) == 2
    assert session.progress() == {"current": 0, "current_required": 2, "revision": 0, "revision_required": 0}
    assert sorted(key for _pool, key in session.current_run["queue"]) == ["cat", "dog", "rope"]
    assert session.verdict() is None


def test_practice_walks_every_current_word_and_each_missed_revision_word_once(data):
    _words(data, "spelling/current", "rope", "cat", "dog")
    _words(data, "spelling/revision", "ant", "bee", "cow", "eel", "fox")
    orders = set()
    for seed in range(12):
        session = _session({"current_required": 0, "revision_required": 3}, seed)
        session.current_run["queue"] = [[REVISION, key] for key in ("ant", "ant", "bee", "cow")]
        now = START
        for right in (False, False, True):
            session.issue(now)
            now += timedelta(seconds=2)
            _answer_pending(session, now, right=right)
        session.issue(now)
        chosen, _alphabet = session.practice(now + timedelta(seconds=2))
        assert sorted(map(tuple, chosen)) == sorted(
            [(CURRENT, "cat"), (CURRENT, "dog"), (CURRENT, "rope"), (REVISION, "ant"), (REVISION, "cow")]
        )
        assert session.current_run["practice"] == chosen
        orders.add(tuple(map(tuple, chosen)))
    assert len(orders) > 6


@pytest.mark.parametrize(
    ("body", "letter", "word"),
    [({}, 0, 300), ({"letter_pause": "150ms", "word_pause": "1s"}, 150, 1000), ({"word_pause": "0s"}, 0, 0)],
)
def test_practice_through_the_page_plays_the_word_and_its_letters_with_the_task_pauses(tmp_path, data, body, letter, word):
    _words(data, "spelling/current", "don't")
    quiz = Quiz(tmp_path, body)
    quiz.open(START)
    status, reply = quiz.post(START, "practice", {})
    assert status == 200
    assert (reply["current"], reply["revision"], reply["finished"]) == (0, 0, False)
    [practised] = reply["practice"]
    assert practised["word"] == "don't"
    plan = practice_plan("don't", letter, word)
    pauses = [step["pause"] for step in practised["steps"]]
    assert pauses == [pause for _clip, pause in plan]
    assert pauses[1:3] == [word, letter]
    for step, (clip, _pause) in zip(practised["steps"], plan):
        if clip == "word":
            assert read_media_name(step["url"].rsplit("/", 1)[1]) == (CURRENT, "don't", False, "wav")
            assert step["ms"] == WORD_MS
        else:
            assert step["url"] == f"/tasks/spelling/words/audio/alphabet.{clip}.wav"
            assert step["ms"] == LETTER_MS


def test_practice_is_allowed_on_a_required_task_and_keeps_the_attempt_in_progress(tmp_path, data):
    _words(data, "spelling/current", "rope", "cat")
    quiz = Quiz(tmp_path, due="2026-11-01")
    quiz.open(START)
    quiz.spell(True)
    quiz.spell(False)
    quiz.ask(quiz.now)
    status, reply = quiz.post(quiz.now + timedelta(seconds=2), "practice", {})
    assert status == 200
    assert (reply["current"], reply["current_required"]) == (0, 2)
    [attempt] = quiz.store.attempts("younger", TaskKey("spelling", "words"))
    assert attempt.outcome == "in_progress"
    assert [item["outcome"] for item in attempt.detail["questions"]] == ["correct", "incorrect", "timeout"]
    assert len(attempt.detail["runs"]) == 2
    page = quiz.open(quiz.now + timedelta(minutes=1))
    assert "Current: 0 / 2" in page.body
    assert quiz.attempt().id == attempt.id


def test_closing_a_question_for_practice_never_passes_and_the_new_run_can(tmp_path, data):
    _words(data, "spelling/current", "rope", "cat")
    quiz = Quiz(tmp_path, {"current_required": 1})
    quiz.open(START)
    quiz.spell(True)
    quiz.ask(quiz.now)
    quiz.post(quiz.now + timedelta(seconds=2), "practice", {})
    assert quiz.attempt().outcome == "in_progress"
    assert quiz.store.passes_on("younger", START.date()) == 0
    quiz.now += timedelta(seconds=30)
    results = [quiz.spell(True), quiz.spell(True)]
    assert [result["finished"] for result in results] == [False, True]
    assert quiz.attempt().outcome == "pass"
    assert quiz.store.passes_on("younger", START.date()) == 1


def test_practice_with_no_attempt_in_progress_asks_the_page_to_reload(tmp_path, data):
    _words(data, "spelling/current", "rope")
    quiz = Quiz(tmp_path)
    quiz.open(START)
    quiz.spell(True)
    status, payload = quiz.post(quiz.now, "practice", {})
    assert (status, payload) == (409, {"reload": True})


def test_the_service_serves_letter_clips_for_practice(tmp_path, data, monkeypatch):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    _words(data, "spelling/current", "rope")
    write_wav(data / "spelling/alphabet/R.wav", 400)
    (data / "spelling/alphabet/r.wav").unlink()
    policy_file = _write(tmp_path, _house({}))
    monkeypatch.setenv("POLICY_FILE", str(policy_file))
    monkeypatch.setenv("POLICY_DB", str(tmp_path / "policy.sqlite3"))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    monkeypatch.setenv("SOUND_DIR", str(_sound_dir(tmp_path / "sounds")))
    app = create_app()

    assert _call(app, "GET", "/tasks/spelling/words")[0] == 200
    status, _headers, body = _call(app, "POST", "/tasks/spelling/words", query=b"do=practice", body=b"{}")
    assert status == 200
    steps = json.loads(body)["practice"][0]["steps"]
    assert steps[1]["url"] == "/tasks/spelling/words/audio/alphabet.R.wav"
    for step in steps:
        status, headers, _body = _call(app, "GET", step["url"])
        assert status == 200
        assert headers["content-type"].startswith("audio/wav")
    assert _call(app, "GET", "/tasks/spelling/words/audio/alphabet.r.wav")[2] == (data / "spelling/alphabet/R.wav").read_bytes()
    for name in ("alphabet.zz.wav", "alphabet.a.txt", "alphabet.wav", "alphabet..wav", "alphabet.hello.wav"):
        assert _call(app, "GET", f"/tasks/spelling/words/audio/{name}")[0] == 404, name


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to run the page script")
def test_the_practice_screen_shows_each_word_and_waits_for_its_sequence(tmp_path, data):
    _words(data, "spelling/current", "ox", "cat")
    quiz = Quiz(tmp_path)
    page = quiz.open(START).body
    _status, visit = quiz.post(START, "visit", {})
    first = quiz.ask(START)
    _status, practice = quiz.post(START + timedelta(seconds=3), "practice", {})
    after = quiz.ask(START + timedelta(minutes=1))
    words = practice["practice"]
    clip = 100
    durations = [sum(step["pause"] for step in word["steps"]) + clip * len(word["steps"]) for word in words]
    watched = ["practise", "practice-word", "practice-prompt", "practice-next", "practice-confirm", "progress", "ask"]
    steps = [
        {"click": "start-button", "wait": clip},
        {"key": ["answer", "Enter"]},
        {"snap": watched, "label": "asking"},
        {"click": "practice-ask"},
        {"snap": watched, "label": "confirming"},
        {"click": "practice-yes"},
        {"snap": watched, "label": "first word", "wait": durations[0] - 1},
        {"key": ["practice-next", "Enter"]},
        {"snap": watched, "label": "still playing", "wait": 1},
        {"snap": watched, "label": "first word done"},
        {"key": ["practice-next", "Enter"]},
        {"snap": watched, "label": "second word", "wait": durations[1]},
        {"snap": watched, "label": "second word done"},
        {"click": "practice-next"},
        {"snap": watched, "label": "quiz"},
    ]
    replies = {"visit": [visit], "question": [first, after], "practice": [practice]}
    events = _harness(page, replies, clip_ms=clip, steps=steps)
    snaps = {event["what"]: event["elements"] for event in events if event["kind"] == "snap"}
    posts = [event["what"] for event in events if event["kind"] == "post"]
    assert posts == ["visit", "question", "practice", "question"]

    assert snaps["asking"]["practice-confirm"]["hidden"] is True
    assert snaps["asking"]["practise"]["hidden"] is True
    assert snaps["confirming"]["practice-confirm"]["hidden"] is False
    first_word = snaps["first word"]
    assert first_word["practise"]["hidden"] is False and first_word["ask"]["hidden"] is True
    assert first_word["practice-confirm"]["hidden"] is True
    assert first_word["practice-word"]["text"] == words[0]["word"]
    assert first_word["progress"]["text"] == "Practice: 1 of 2"
    assert first_word["practice-next"]["text"] == "Next"
    for label in ("first word", "still playing"):
        assert snaps[label]["practice-next"]["disabled"] is True
        assert snaps[label]["practice-prompt"]["hidden"] is True
        assert snaps[label]["practice-word"]["text"] == words[0]["word"]
    done = snaps["first word done"]
    assert done["practice-word"]["text"] == words[0]["word"]
    assert done["practice-next"]["disabled"] is False and done["practice-next"]["focused"] is True
    assert done["practice-prompt"]["hidden"] is False

    second = snaps["second word"]
    assert second["practice-word"]["text"] == words[1]["word"]
    assert second["progress"]["text"] == "Practice: 2 of 2"
    assert second["practice-next"]["text"] == "Start quiz"
    assert second["practice-next"]["disabled"] is True
    assert snaps["second word done"]["practice-next"]["disabled"] is False
    assert snaps["quiz"]["practise"]["hidden"] is True and snaps["quiz"]["ask"]["hidden"] is False

    plays = [event for event in events if event["kind"] == "play"]
    practised = plays[1 : 1 + len(words[0]["steps"]) + len(words[1]["steps"])]
    expected = words[0]["steps"] + words[1]["steps"]
    assert [play["what"] for play in practised] == [step["url"] for step in expected]
    gaps = [later["at"] - earlier["at"] - clip for earlier, later in zip(practised, practised[1:])]
    assert gaps[: len(words[0]["steps"]) - 1] == [step["pause"] for step in words[0]["steps"][1:]]
    assert gaps[len(words[0]["steps"]) :] == [step["pause"] for step in words[1]["steps"][1:]]
    assert plays[-1]["what"] == after["word_url"]


def _call(app, method, path, *, query=b"", body=b""):
    messages = []
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            await asyncio.Future()
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query,
        "headers": [(b"x-daywarden-client", YOUNGER.encode()), (b"content-type", b"application/json")],
        "client": ("172.17.0.2", 12345),
        "server": ("127.0.0.1", 80),
        "root_path": "",
    }
    asyncio.run(app(scope, receive, send))
    start = next(item for item in messages if item["type"] == "http.response.start")
    payload = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
    headers = {key.decode(): value.decode() for key, value in start["headers"]}
    return start["status"], headers, payload
