"""S035.4: spelling words across attempts, and a spelling attempt's page."""

import json
from datetime import datetime, timedelta

import pytest

from asgi import call, session_cookie
from policy.accounts import Accounts
from policy.review import attempt_report, words_report
from policy.store import PolicyStore
from policy.tasks import AttemptStore, Task, TaskKey

NOW = datetime(2026, 11, 18, 18, 0)
CLIENTS = ("younger", "older")
PASSWORD = "s3cret-pass"
YOUNGER = TaskKey("spelling", "spelling-younger")
OLDER = TaskKey("spelling", "spelling-older")


def _task(name: str, folder: str, groups=("younger",)) -> Task:
    body = {
        "current_dir": f"spelling/{folder}/current",
        "revision_dir": f"spelling/{folder}/revision",
        "attic_dir": f"spelling/{folder}/attic",
        "alphabet_dir": "spelling/alphabet",
    }
    return Task(name, "spelling", tuple(groups), 0, body=json.dumps(body))


TASKS = (_task("spelling-younger", "younger"),)


def _pools(root, folder: str = "younger", **pools):
    for pool, words in pools.items():
        directory = root / "spelling" / folder / pool
        directory.mkdir(parents=True, exist_ok=True)
        for word in words:
            (directory / f"{word}.mp3").write_bytes(b"")
            (directory / f"{word}.sentence.mp3").write_bytes(b"")


def _ask(key, outcome, answer=None, pool="current", run=1, replays=0, plays=0, ms=3000, requeued=False, issued=None):
    if answer is None and outcome == "correct":
        answer = key.split(".")[0]
    question = {
        "run": run,
        "key": key,
        "word": key.split(".")[0],
        "pool": pool,
        "word_replays": replays,
        "sentence_plays": plays,
        "answer": answer,
        "outcome": outcome,
        "requeued": requeued if outcome not in (None, "correct") else (False if outcome else None),
        "allowed_ms": 12_000,
        "received_ms": ms if outcome is not None else None,
    }
    if issued is not None:
        question["issued"] = issued.isoformat(timespec="milliseconds")
    return question


def _run(number=1, current=(), revision=(), **extra):
    return {
        "run": number,
        "started": "2026-11-18T16:00:00.000",
        "current_required": len(current),
        "revision_required": 1,
        "words": {
            "current": [{"key": key, "word": key.split(".")[0]} for key in current],
            "revision": [{"key": key, "word": key.split(".")[0]} for key in revision],
        },
        **extra,
    }


def _detail(*questions, runs=None, current=()):
    return {"settings": {}, "runs": runs or [_run(current=current)], "questions": list(questions)}


def _plant(store, days_ago, detail, key=YOUNGER, outcome="pass", **extra):
    started = NOW - timedelta(days=days_ago)
    return store.record("younger", key, outcome, started + timedelta(minutes=5), started_at=started, detail=detail, **extra)


def _words(store, root, query="", tasks=TASKS):
    pairs = [("client", "younger")] + [tuple(pair.split("=", 1)) for pair in query.split("&") if pair]
    return words_report(store, CLIENTS, now=NOW, tasks=tasks, pairs=pairs, root=root)


def _by_word(report):
    return {word["word"]: word for word in report["words"]["words"]}


# The words page


def test_each_word_is_right_first_time_right_after_a_miss_or_missed_in_each_attempt_and_counted_once_per_attempt(tmp_path):
    _pools(tmp_path, current=["necessary", "rope"])
    with AttemptStore(":memory:") as store:
        monday = datetime(2026, 11, 16, 16, 0)
        _plant(store, 2.1, _detail(
            _ask("necessary", "incorrect", "necesary", replays=2, plays=1, requeued=True, issued=monday),
            _ask("necessary", "incorrect", "neccessary", requeued=True, issued=monday),
            _ask("rope", "correct", ms=2000),
        ))
        _plant(store, 1.1, _detail(
            _ask("necessary", "timeout", "nec", requeued=True, issued=monday + timedelta(days=1)),
            _ask("necessary", "incorrect", "Necesary", requeued=False, issued=monday + timedelta(days=1)),
            _ask("rope", "correct", ms=4000),
        ))
        _plant(store, 0.1, _detail(
            _ask("necessary", "incorrect", "necesary", replays=1, requeued=True),
            _ask("necessary", "correct", ms=5000),
            _ask("rope", "correct", ms=3000),
        ))
        report = _words(store, tmp_path)
    words = _by_word(report)
    necessary = words["necessary"]
    assert (necessary["asked"], necessary["first_time"], necessary["after_miss"], necessary["missed"]) == (3, 0, 1, 2)
    assert (necessary["missed_percent"], necessary["timeouts"], necessary["median_ms"]) == (100, 1, 5000)
    # Four plays over six questions.
    assert necessary["replays_per_ask"] == 0.7
    assert necessary["last_missed"] == "Wednesday 18 November 2026"
    assert necessary["misspellings"] == [{"text": "necesary", "count": 3}, {"text": "neccessary", "count": 1}]
    assert [(each["result"], each["answers"]) for each in necessary["attempts"]] == [
        ("after_miss", ["necesary", "necessary"]),
        ("missed", ["timeout", "Necesary"]),
        ("missed", ["necesary", "neccessary"]),
    ]
    assert necessary["attempts"][0]["pools"] == ["current"]
    rope = words["rope"]
    assert (rope["asked"], rope["first_time"], rope["missed_percent"], rope["median_ms"], rope["last_missed"]) == (3, 3, 0, 3000, None)
    # Run and weight are all-time, as bin/word-stats gives them.
    assert necessary["all_time"] == {"run": 0, "weight": 4.25}
    assert rope["all_time"] == {"run": 3, "weight": 0.25}
    tiles = report["words"]["tiles"]
    # Three of six asks right first time.
    assert tiles == {"words_asked": 2, "right_first_time": 50, "words_missed": 1, "settled": 0}
    assert len(report["words"]["columns"]) == 3


def test_every_question_with_an_outcome_counts_in_every_run_and_kind_of_attempt(tmp_path):
    _pools(tmp_path, current=["rope"])
    with AttemptStore(":memory:") as store:
        runs = [_run(1, ["rope"], expired="2026-11-17T17:00:00.000"), _run(2, ["rope"], practice=[["current", "rope"]])]
        _plant(store, 1, _detail(_ask("rope", "incorrect", "roap", run=1), _ask("rope", "correct", run=2), runs=runs))
        _plant(store, 2, _detail(_ask("rope", "timeout")), outcome="abandoned")
        store.begin("younger", YOUNGER, NOW - timedelta(hours=1), detail=_detail(_ask("rope", "correct"), _ask("rope", None)))
        rope = _by_word(_words(store, tmp_path))["rope"]
    assert (rope["asked"], rope["after_miss"], rope["missed"], rope["first_time"]) == (3, 1, 1, 1)


def test_the_pool_filter_keeps_words_by_where_they_are_now_and_counts_every_ask_of_a_kept_word(tmp_path):
    _pools(tmp_path, current=["necessary"], revision=["rope"], attic=["cat"])
    with AttemptStore(":memory:") as store:
        # necessary was a revision word three weeks ago and is current now. rope was current last week and is revision now.
        _plant(store, 21, _detail(_ask("necessary", "incorrect", "necesary", pool="revision")))
        _plant(store, 7, _detail(_ask("rope", "correct"), _ask("cat", "correct", pool="revision"), _ask("gone", "correct")))
        _plant(store, 1, _detail(_ask("necessary", "correct")))
        current = _words(store, tmp_path, "pool=current")
        week = _words(store, tmp_path, "pool=current&range=past-week")
        everything = _words(store, tmp_path)
        none = _words(store, tmp_path, "pool=no_pool")
        nothing = _words(store, tmp_path, "pool=none")
    assert list(_by_word(current)) == ["necessary"]
    assert _by_word(current)["necessary"]["asked"] == 2
    assert [each["pools"] for each in _by_word(current)["necessary"]["attempts"]] == [["current"], ["revision"]]
    assert _by_word(week)["necessary"]["asked"] == 1
    assert {word: row["pools"] for word, row in _by_word(everything).items()} == {
        "cat": ["attic"], "gone": [], "necessary": ["current"], "rope": ["revision"],
    }
    assert list(_by_word(none)) == ["gone"]
    assert nothing["words"] is None
    assert nothing["message"] == "No spelling words for younger in this period."
    assert current["choices"] == {"task": ["spelling-younger"], "pool": ["current"]}


def test_the_task_filter_offers_the_groups_tasks_and_others_with_attempts_and_only_chosen_tasks_count(tmp_path):
    _pools(tmp_path, current=["rope"])
    _pools(tmp_path, "other", revision=["rope"])
    tasks = (*TASKS, _task("spelling-other", "other"))
    with AttemptStore(":memory:") as store:
        _plant(store, 1, _detail(_ask("rope", "correct")))
        _plant(store, 2, _detail(_ask("rope", "incorrect", "roap"), _ask("lost", "correct")), key=TaskKey("spelling", "old-list"))
        _plant(store, 3, _detail(_ask("rope", "correct")), key=OLDER)
        everything = _words(store, tmp_path, tasks=tasks)
        younger = _words(store, tmp_path, "task=spelling-younger", tasks=tasks)
        old = _words(store, tmp_path, "task=old-list", tasks=tasks)
        both = _words(store, tmp_path, "task=spelling-younger&task=spelling-other&pool=revision", tasks=tasks)
        none = _words(store, tmp_path, "task=none", tasks=tasks)
    assert everything["tasks_offered"] == [
        {"name": "spelling-younger", "in_policy": True},
        {"name": "spelling-other", "in_policy": True},
        {"name": "old-list", "in_policy": False},
        {"name": "spelling-older", "in_policy": False},
    ]
    assert _by_word(younger)["rope"]["asked"] == 1
    # A task not in the policy has no directories, so its words have no pool now unless a chosen task holds them.
    assert {word: row["pools"] for word, row in _by_word(old).items()} == {"lost": [], "rope": []}
    # Current for one task and Revision for the other: both, and either choice keeps it.
    assert _by_word(both)["rope"]["pools"] == ["current", "revision"]
    assert none["words"] is None and none["choices"]["task"] == []


def test_this_weeks_words_start_on_the_first_attempt_whose_run_asked_exactly_the_current_words_now(tmp_path):
    _pools(tmp_path, current=["necessary", "rope"])
    _pools(tmp_path, "other", current=["cat"])
    _pools(tmp_path, "third", current=["owl"])
    tasks = (*TASKS, _task("spelling-other", "other"), _task("spelling-third", "third"))
    with AttemptStore(":memory:") as store:
        _plant(store, 9, _detail(current=["old", "words"]))
        _plant(store, 3, _detail(current=["necessary"]))
        # Replace Current part way through: the second run asked this week's words.
        _plant(store, 2, _detail(runs=[_run(1, ["old", "words"]), _run(2, ["Rope", "necessary"])]))
        _plant(store, 1, _detail(current=["necessary", "rope"]))
        _plant(store, 5, _detail(current=["cat"]), key=TaskKey("spelling", "spelling-other"))
        found = _words(store, tmp_path, "task=spelling-younger", tasks=tasks)
        earlier = _words(store, tmp_path, "task=spelling-younger&task=spelling-other", tasks=tasks)
        never = _words(store, tmp_path, "task=spelling-third", tasks=tasks)
    assert found["this_week"] == {"from": "2026-11-16", "to": "2026-11-18"}
    assert earlier["this_week"]["from"] == "2026-11-13"
    assert never["this_week"] == {"from": "2026-11-18", "to": "2026-11-18"}


def test_the_words_page_says_why_it_has_nothing_to_show(tmp_path):
    with AttemptStore(":memory:") as store:
        assert words_report(store, CLIENTS, now=NOW, pairs=[], root=tmp_path)["message"] == "Choose a client group."
        assert words_report(store, CLIENTS, now=NOW, pairs=[("client", "nobody")], root=tmp_path)["message"] == "That client group is not in the household."
        assert _words(store, tmp_path)["message"] == "No spelling words for younger in this period."
        broken = _words(store, tmp_path, "range=custom&from=2026-11-20&to=2026-11-01")
    assert broken["message"] == "Fix the period to show the words."


# The spelling attempt page


def test_a_spelling_attempt_page_has_its_last_run_and_each_earlier_run_with_how_it_ended():
    runs = [
        _run(1, ["rope", "necessary"], ["cat"], expired="2026-11-18T15:00:00.000"),
        _run(2, ["rope", "necessary"], ["cat"], started="2026-11-18T16:00:00.000"),
        _run(3, ["rope", "necessary"], ["cat", "dog"], started="2026-11-18T16:20:00.000", practice=[["current", "rope"], ["revision", "cat"]]),
    ]
    runs[2]["revision_required"] = 1
    questions = [
        _ask("rope", "incorrect", "roap", run=1, requeued=True),
        _ask("cat", "timeout", run=2),
        _ask("necessary", "incorrect", "necesary", run=3, replays=2, plays=1, requeued=True),
        _ask("necessary", "correct", run=3, ms=4500),
        _ask("rope", "correct", run=3),
        _ask("cat", "correct", pool="revision", run=3),
        _ask("dog", None, pool="revision", run=3),
    ]
    with AttemptStore(":memory:") as store:
        attempt = _plant(store, 0, {"settings": {}, "runs": runs, "questions": questions})
        page = attempt_report(store, str(attempt.id), now=NOW)
    spelling = page["spelling"]
    last = spelling["last"]
    figures = last["figures"]
    assert (figures["current_points"], figures["current_required"], figures["revision_points"], figures["revision_required"]) == (2, 2, 1, 1)
    assert (figures["questions"], figures["wrong"], figures["timeouts"]) == (4, 1, 0)
    assert [each["word"] for each in last["practised"]] == ["rope", "cat"]
    rows = last["questions"]
    assert [(row["word"], row["pool_label"], row["answer"], row["outcome_label"], row["came_back"]) for row in rows] == [
        ("necessary", "Current", "necesary", "Wrong", True),
        ("necessary", "Current", "necessary", "Right", False),
        ("rope", "Current", "rope", "Right", False),
        ("cat", "Revision", "cat", "Right", False),
        ("dog", "Revision", "", "Not answered yet", None),
    ]
    assert (rows[0]["word_replays"], rows[0]["sentence_plays"], rows[1]["taken_ms"], rows[1]["allowed_ms"]) == (2, 1, 4500, 12_000)
    earlier = spelling["earlier"]
    assert [each["ended"]["how"] for each in earlier] == ["expired", "practice"]
    assert earlier[0]["ended"]["at"] == "Wednesday 18 November 2026, 15:00"
    assert earlier[1]["ended"]["at"] == "Wednesday 18 November 2026, 16:20"
    assert earlier[1]["figures"]["timeouts"] == 1 and earlier[1]["practised"] is None
    assert page["arithmetic"] is None


# The endpoint and the MCP tool


@pytest.fixture
def service(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    monkeypatch.setenv("DAYWARDEN_DATA_DIR", str(tmp_path / "data"))
    _pools(tmp_path / "data", current=["rope"])
    database = tmp_path / "policy.sqlite3"
    monkeypatch.setenv("POLICY_FILE", str(tmp_path / "missing.yaml"))
    monkeypatch.setenv("POLICY_DB", str(database))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    with PolicyStore(database) as saved:
        Accounts(saved.connection).set_password("ada", PASSWORD)
        recent = datetime.now() - timedelta(hours=2)
        AttemptStore(connection=saved.connection).record(
            "younger", YOUNGER, "pass", recent, started_at=recent, detail=_detail(_ask("rope", "incorrect", "roap"), _ask("rope", "correct"))
        )
    app = create_app()
    app.state.database = database
    return app


def test_words_are_sent_only_with_a_session(service):
    path = "/parent/api/attempts/words"
    status, body, _headers = call(service, "GET", path, query="client=younger")
    assert status == 401
    assert "roap" not in body
    _status, _body, headers = call(service, "POST", "/parent/api/login", json_body={"username": "ada", "password": PASSWORD})
    status, body, _headers = call(service, "GET", path, query="client=younger&range=past-week&word=rope", cookie=session_cookie(headers))
    assert status == 200
    word = json.loads(body)["words"]["words"][0]
    assert (word["word"], word["misspellings"]) == ("rope", [{"text": "roap", "count": 1}])
