"""S033: spelling word figures, weighted revision words, and word-stats."""

import io
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_spelling import START, _house, _words, _write, data  # noqa: E402,F401

from policy import maintenance  # noqa: E402
from policy.spelling import CURRENT, REVISION, Session  # noqa: E402
from policy.spelling_words import Figures, weight  # noqa: E402
from policy.tasks import AttemptStore, TaskKey  # noqa: E402

SPELLING = TaskKey("spelling", "words")
YOUNGER = "younger"


def _ask(store, group, outcomes, *, when=START, finish=True):
    """Store one spelling attempt whose questions had these ``(key, outcome)`` answers."""
    detail = {"questions": [{"key": key, "outcome": outcome, "pool": REVISION} for key, outcome in outcomes]}
    if finish:
        return store.record(group, SPELLING, "failure", when, started_at=when, detail=detail)
    attempt = store.begin(group, SPELLING, when)
    return store.save(attempt.id, detail)


def _figures(store, group=YOUNGER, key=None):
    found = store.words.figures(group)
    return found if key is None else found[key]


@pytest.mark.parametrize(
    ("attempts", "run", "expected"),
    [
        (0, 0, 1.0),
        (10, 10, 1 / 11),
        (10, 0, 4 + 1 / 11),
        (10, 1, 2 + 1 / 11),
        (10, 2, 1 + 1 / 11),
        (10, 4, 0.25 + 1 / 11),
        (10, 5, 1 / 11),
        (100, 0, 4 + 1 / 101),
        (1, 0, 4.5),
        (3, 3, 1 / 4),
    ],
)
def test_the_weight_follows_the_formula_and_table(attempts, run, expected):
    assert weight(attempts, run) == pytest.approx(expected)
    assert Figures(attempts, attempts, 0, run).weight == pytest.approx(expected)


def test_the_figures_follow_the_counting_rules():
    with AttemptStore() as store:
        _ask(store, YOUNGER, [("Rope", "correct"), ("rope", "incorrect"), ("rope", "correct"), ("cat", "correct")])
        _ask(store, YOUNGER, [("rope", "correct"), ("cat", "timeout"), ("read.1", "correct")])
        _ask(store, YOUNGER, [("rope", "correct"), ("cat", "correct")])
        assert _figures(store, key="rope") == Figures(attempts=3, correct=2, incorrect=1, run=2)
        assert _figures(store, key="cat") == Figures(attempts=3, correct=2, incorrect=1, run=1)
        assert _figures(store, key="read.1") == Figures(1, 1, 0, 1)
        assert "read.2" not in _figures(store)


def test_another_client_group_has_its_own_figures():
    with AttemptStore() as store:
        _ask(store, "younger", [("rope", "incorrect")])
        _ask(store, "older", [("rope", "correct")])
        assert _figures(store, "younger", "rope").incorrect == 1
        assert _figures(store, "older", "rope") == Figures(1, 1, 0, 1)


def test_a_word_in_two_tasks_has_one_set_of_figures():
    with AttemptStore() as store:
        for name in ("one", "two"):
            detail = {"questions": [{"key": "rope", "outcome": "correct"}]}
            store.record(YOUNGER, TaskKey("spelling", name), "pass", START, detail=detail)
        assert _figures(store, key="rope").attempts == 2


def test_saving_again_counts_nothing_twice_and_a_later_miss_turns_correct_into_incorrect():
    with AttemptStore() as store:
        attempt = _ask(store, YOUNGER, [("rope", "correct")], finish=False)
        store.save(attempt.id, attempt.detail)
        assert _figures(store, key="rope") == Figures(1, 1, 0, 1)
        detail = {"questions": [{"key": "rope", "outcome": "correct"}, {"key": "rope", "outcome": "timeout"}]}
        store.save(attempt.id, detail)
        store.finish(attempt.id, "abandoned", START + timedelta(minutes=1), detail=detail)
        assert _figures(store, key="rope") == Figures(1, 0, 1, 0)


def test_a_question_still_showing_is_not_counted_until_it_is_answered():
    with AttemptStore() as store:
        attempt = _ask(store, YOUNGER, [("rope", None)], finish=False)
        assert _figures(store) == {}
        store.save(attempt.id, {"questions": [{"key": "rope", "outcome": "incorrect"}]})
        assert _figures(store, key="rope").incorrect == 1


def test_giving_up_and_coming_back_to_the_attempt_counts_words_once():
    with AttemptStore() as store:
        attempt = _ask(store, YOUNGER, [("rope", "correct")], finish=False)
        store.finish(attempt.id, "abandoned", START + timedelta(minutes=1), detail=attempt.detail)
        back = store.open(YOUNGER, SPELLING, START + timedelta(minutes=2), task_set="required", reopen_within=timedelta(hours=1))
        assert back.id == attempt.id
        detail = {"questions": [*attempt.detail["questions"], {"key": "cat", "outcome": "correct"}, {"key": "rope", "outcome": "correct"}]}
        store.save(back.id, detail)
        assert _figures(store, key="rope").attempts == 1
        assert _figures(store, key="cat").attempts == 1


def test_other_task_types_are_not_counted():
    with AttemptStore() as store:
        store.record(YOUNGER, TaskKey("arithmetic", "sums"), "pass", START, detail={"questions": [{"key": "x", "outcome": "correct"}]})
        assert _figures(store) == {}


def test_removing_attempts_keeps_the_figures_and_a_reused_id_is_a_new_task():
    with AttemptStore() as store:
        first = _ask(store, YOUNGER, [("rope", "incorrect")])
        store.remove([first.id])
        assert _figures(store, key="rope") == Figures(1, 0, 1, 0)
        second = _ask(store, YOUNGER, [("rope", "correct")], when=START + timedelta(days=1))
        assert second.id == first.id
        assert _figures(store, key="rope") == Figures(2, 1, 1, 1)


def test_the_first_start_builds_figures_from_stored_attempts_in_start_order_and_only_once(tmp_path):
    path = tmp_path / "policy.sqlite3"
    with AttemptStore(path) as store:
        # Stored out of start order, as when an older attempt has the higher id.
        _ask(store, YOUNGER, [("rope", "correct")], when=START + timedelta(days=1))
        _ask(store, YOUNGER, [("rope", "incorrect")], when=START)
    with sqlite3.connect(path) as raw:
        for table in ("spelling_word_tasks", "spelling_word_meta"):
            raw.execute(f"DROP TABLE {table}")
    for _ in range(2):
        with AttemptStore(path) as store:
            assert _figures(store, key="rope") == Figures(2, 1, 1, 1)


def _lookup(figures):
    return lambda keys: {key: figures[key] for key in keys if key in figures}


def _revision_session(data, seed, figures, required=1):
    _words(data, "spelling/current", "rope")
    _words(data, "spelling/revision", "alpha", "bravo", "charlie", "delta", "echo")
    session = Session({}, {"revision_required": required}, random.Random(seed), figures=_lookup(figures))
    session.visit(START)
    return session


def test_a_word_missed_on_its_last_task_is_picked_far_more_often(data):
    figures = {key: Figures(10, 10, 0, 10) for key in ("alpha", "bravo", "charlie", "delta")}
    figures["echo"] = Figures(10, 9, 1, 0)
    picks = []
    for seed in range(400):
        queue = _revision_session(data, seed, figures).current_run["queue"]
        picks += [key for pool, key in queue if pool == REVISION]
    assert 0.5 < picks.count("echo") / len(picks) < 0.9


def test_revision_words_he_has_never_missed_are_picked_about_equally_and_a_new_word_catches_up(data):
    figures = {key: Figures(20, 20, 0, 20) for key in ("alpha", "bravo", "charlie", "delta")}
    picks = []
    for seed in range(600):
        queue = _revision_session(data, seed, figures, required=2).current_run["queue"]
        picks += [key for pool, key in queue if pool == REVISION]
    # echo has no figures yet, so it is asked far more than the others.
    assert picks.count("echo") > 2 * picks.count("alpha")
    even = {key: Figures(20, 20, 0, 20) for key in ("alpha", "bravo", "charlie", "delta", "echo")}
    picks = []
    for seed in range(600):
        queue = _revision_session(data, seed, even, required=2).current_run["queue"]
        picks += [key for pool, key in queue if pool == REVISION]
    counts = [picks.count(key) for key in ("alpha", "bravo", "charlie", "delta", "echo")]
    assert max(counts) < 1.3 * min(counts)


def test_the_words_of_a_run_are_not_repeated_and_every_current_word_is_still_asked(data):
    figures = {"alpha": Figures(1, 0, 1, 0)}
    queue = _revision_session(data, 3, figures, required=5).current_run["queue"]
    assert sorted(key for pool, key in queue if pool == REVISION) == ["alpha", "bravo", "charlie", "delta", "echo"]
    assert [key for pool, key in queue if pool == CURRENT] == ["rope"]


def test_a_replacement_after_a_miss_is_weighted_among_words_not_waiting_or_right(data):
    figures = {key: Figures(10, 10, 0, 10) for key in ("alpha", "bravo", "charlie", "delta", "echo")}
    figures["delta"] = Figures(10, 9, 1, 0)
    picked = []
    for seed in range(1500):
        # One revision word waits, so delta, whose weight dwarfs the rest, is rarely drawn into the opening queue.
        session = _revision_session(data, seed, figures, required=1)
        run = session.current_run
        first = next(key for pool, key in run["queue"] if pool == REVISION)
        while session.pending is None or session.pending["key"] != first:
            session.issue(START)
        waiting = {key for pool, key in run["queue"] if pool == REVISION}
        eligible = "delta" not in waiting and first != "delta"
        session.answer(START, len(session.questions) - 1, "zzz", expired=False)
        added = [key for pool, key in run["queue"] if pool == REVISION and key not in waiting]
        assert len(added) == 1 and added[0] != first and added[0] not in waiting
        if eligible:
            picked.append(added[0])
    assert len(picked) > 30
    assert picked.count("delta") > 0.8 * len(picked)


def _stats(argv):
    out = io.StringIO()
    code = maintenance.main(["word-stats", *argv], now=datetime(2026, 11, 16), out=out)
    return code, out.getvalue()


@pytest.fixture
def household(tmp_path, data, monkeypatch):
    _words(data, "spelling/current", "rope")
    _words(data, "spelling/revision", "alpha", "bravo")
    _words(data, "elsewhere", "bravo", "other")
    policy = _write(tmp_path / "etc", _house({}))
    database = tmp_path / "policy.sqlite3"
    monkeypatch.setenv("POLICY_FILE", str(policy))
    monkeypatch.setenv("POLICY_DB", str(database))
    with AttemptStore(database) as store:
        _ask(store, "younger", [("rope", "correct"), ("alpha", "incorrect"), ("gone", "correct")])
        _ask(store, "younger", [("alpha", "correct"), ("bravo", "correct"), ("other", "correct")])
        _ask(store, "older", [("alpha", "correct")])
    return database


def _rows(text):
    return [line.split() for line in text.splitlines()[1:]]


def test_word_stats_lists_every_group_and_word_with_figures_and_weights(household):
    code, text = _stats([])
    assert code == 0
    assert text.splitlines()[0].split() == ["client", "group", "word", "attempts", "correct", "incorrect", "run", "weight"]
    rows = {(row[0], row[1]): row[2:] for row in _rows(text)}
    assert rows[("younger", "alpha")] == ["2", "1", "1", "1", "2.333"]
    assert rows[("older", "alpha")] == ["1", "1", "0", "1", "0.500"]
    assert ("younger", "gone") in rows


def test_word_stats_filters_by_client_and_word(household):
    code, text = _stats(["--client", "older"])
    assert [row[:2] for row in _rows(text)] == [["older", "alpha"]]
    code, text = _stats(["--word", "BRAVO", "--word", "rope"])
    assert sorted(row[1] for row in _rows(text)) == ["bravo", "rope"]


def test_word_stats_filters_by_pool_directory_and_task(household):
    _, text = _stats(["--pool", "spelling/revision"])
    assert sorted({row[1] for row in _rows(text)}) == ["alpha", "bravo"]
    # A word nobody has been asked is listed too, for each client group, with the weight of a new word.
    rows = {(row[0], row[1]): row[2:] for row in _rows(text)}
    assert rows[("older", "bravo")] == ["0", "0", "0", "0", "1.000"]
    assert rows[("younger", "bravo")][0] == "1"
    _, text = _stats(["--pool", "spelling/revision", "--pool", "elsewhere"])
    assert sorted({row[1] for row in _rows(text)}) == ["alpha", "bravo", "other"]
    _, text = _stats(["--task", "words"])
    assert sorted({row[1] for row in _rows(text)}) == ["alpha", "bravo", "rope"]
    _, text = _stats(["--task", "words", "--client", "younger", "--word", "never"])
    assert text == "no word figures match\n"
    _, text = _stats(["--task", "words", "--pool", "elsewhere"])
    assert sorted({row[1] for row in _rows(text)}) == ["bravo"]


@pytest.mark.parametrize(
    ("argv", "named"),
    [(["--pool", "spelling/nowhere"], "spelling/nowhere"), (["--task", "nothing"], "nothing"), (["--task", "words", "--pool", "nowhere"], "nowhere")],
)
def test_word_stats_names_a_missing_pool_or_task_and_lists_nothing(household, argv, named, capsys):
    code, text = _stats(argv)
    assert code == 1 and text == ""
    assert named in capsys.readouterr().err


def test_word_stats_sorts_by_each_term_in_turn_and_in_reverse(household):
    _, text = _stats(["--pool", "spelling/revision", "--sort", "weight-"])
    weights = [float(row[-1]) for row in _rows(text)]
    assert weights == sorted(weights, reverse=True)
    _, text = _stats(["--pool", "spelling/revision", "--sort", "word-", "--sort", "client"])
    assert [row[:2] for row in _rows(text)] == [["older", "bravo"], ["younger", "bravo"], ["older", "alpha"], ["younger", "alpha"]]
    _, text = _stats(["--pool", "spelling/revision", "--sort", "client-", "--sort=-attempts"])
    assert [row[:3] for row in _rows(text)][:2] == [["younger", "alpha", "2"], ["younger", "bravo", "1"]]


def test_word_stats_rejects_an_unknown_sort_column(household, capsys):
    with pytest.raises(SystemExit):
        _stats(["--sort", "size"])
    assert "size" in capsys.readouterr().err
