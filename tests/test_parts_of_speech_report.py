"""S035.3: parts of speech confusions across attempts, and a parts of speech attempt's page."""

import json
from datetime import datetime, timedelta

import pytest
import yaml

from asgi import call, session_cookie
from policy.review import attempt_report, confusions_report
from policy.parts_of_speech_report import pair_placements, word_asks
from policy.tasks import AttemptStore, Task, TaskKey

NOW = datetime(2026, 11, 18, 18, 0)
CLIENTS = ("younger", "older")
PARTS = TaskKey("parts_of_speech", "pos-younger")
FILTER = ["noun", "verb", "adjective"]
QUICKLY = "The dog ran quickly."
DRY = "Dry the dishes with a dry towel."


def _task(name="pos-younger", groups=("younger",)) -> Task:
    return Task(name, "parts_of_speech", tuple(groups), 0, body=json.dumps({"pools": ["Basic"], "parts_of_speech": FILTER}))


TASKS = (_task(),)


def _pool(root, sentences, name="Basic", pool_id="basic"):
    directory = root / "parts_of_speech_pools"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{pool_id}.yaml").write_text(yaml.safe_dump({"name": name, "sentences": sentences}), encoding="utf-8")


POOL = [
    {"sentence": QUICKLY, "parts": {"noun": ["dog"], "verb": ["ran"], "adverb": ["quickly"], "determiner": ["The"]}},
    {"sentence": DRY, "parts": {"verb": ["Dry"], "noun": ["dishes", "towel"], "adjective": ["dry[2]"]}},
]


def _words(text, parts):
    from policy.parts_of_speech import split_words

    return [{"word": word.text, "part": parts.get(position)} for position, word in enumerate(split_words(text))]


def _try(placements, ms=5000, expired=False):
    return {"placements": placements, "expired": expired, "received_ms": ms}


def _question(text, parts, tries, outcome, rows=FILTER, run=1, correct_try=None, points=None, issued=None):
    if points is None:
        points = {1: 1, 2: 0.5, 3: 0.25}.get(correct_try, 0) if outcome == "correct" else (0 if outcome else None)
    question = {
        "run": run,
        "index": 0,
        "sentence": text,
        "parts": list(rows),
        "words": _words(text, parts),
        "tries": tries,
        "outcome": outcome,
        "correct_try": correct_try,
        "points": points,
        "allowed_ms": 90_000,
    }
    if issued is not None:
        question["issued"] = issued.isoformat(timespec="milliseconds")
    return question


# The quiz records the filtered parts only: quickly and The are in no part.
QUICKLY_PARTS = {1: "noun", 2: "verb"}
DRY_PARTS = {0: "verb", 2: "noun", 5: "adjective", 6: "noun"}


def _quickly(*tries, outcome="correct", correct_try=None, **extra):
    return _question(QUICKLY, QUICKLY_PARTS, list(tries), outcome, correct_try=correct_try, **extra)


def _detail(*questions, runs=None, filtered=True, pools=("Basic",)):
    settings = {"pools": list(pools), "correct_answers_required": 7, "maximum_questions": 10, "sentences": []}
    if filtered:
        settings["parts_of_speech"] = FILTER
    return {"settings": settings, "runs": runs or [{"run": 1, "started": "2026-11-18T16:00:00.000"}], "questions": list(questions)}


def _plant(store, days_ago, detail, key=PARTS, outcome="pass", **extra):
    started = NOW - timedelta(days=days_ago)
    return store.record("younger", key, outcome, started + timedelta(minutes=5), started_at=started, detail=detail, **extra)


def _report(store, root, query="", tasks=TASKS):
    pairs = [("client", "younger")] + [tuple(pair.split("=", 1)) for pair in query.split("&") if pair]
    return confusions_report(store, CLIENTS, now=NOW, tasks=tasks, pairs=pairs, root=root)


def _grid(report):
    data = report["confusions"]
    columns = [column["part"] for column in data["columns"]]
    return {row["part"]: dict(zip(columns, row["cells"])) for row in data["rows"]}


def _rights(report):
    return {row["part"]: row["right"] for row in report["confusions"]["rows"]}


# The confusions page


def test_an_adverb_the_filter_hid_belongs_in_the_part_its_pool_gives_it_and_every_try_counts(tmp_path):
    _pool(tmp_path, POOL)
    with AttemptStore(":memory:") as store:
        _plant(store, 1, _detail(_quickly(
            _try({"noun": [1], "verb": [2], "adjective": [3]}),
            _try({"noun": [1], "verb": [2]}),
            correct_try=2,
        )))
        report = _report(store, tmp_path)
    grid = _grid(report)
    assert [column["part"] for column in report["confusions"]["columns"]] == ["adjective", "noun", "verb", "left_out"]
    assert [row["part"] for row in report["confusions"]["rows"]] == ["adverb", "determiner", "noun", "verb"]
    assert grid["adverb"] == {"adjective": 1, "noun": 0, "verb": 0, "left_out": 1}
    assert grid["noun"]["noun"] == 2 and grid["verb"]["verb"] == 2 and grid["determiner"]["left_out"] == 2
    # Adverb and determiner were never rows, so they are not asked.
    assert _rights(report) == {"adverb": None, "determiner": None, "noun": 100, "verb": 100}
    assert report["pools_offered"] == [{"id": "basic", "name": "Basic"}, {"id": "no_pool", "name": "None"}]


def test_a_sentence_edited_or_gone_from_its_pool_keeps_the_hidden_word_in_no_part(tmp_path):
    _pool(tmp_path, [{"sentence": "The dog ran very quickly.", "parts": {"adverb": ["very", "quickly"]}}])
    with AttemptStore(":memory:") as store:
        _plant(store, 1, _detail(_quickly(_try({"noun": [1], "verb": [2], "adjective": [3]}), outcome="incorrect")))
        report = _report(store, tmp_path)
    grid = _grid(report)
    assert set(grid) == {"noun", "verb", "no_part"}
    assert grid["no_part"] == {"adjective": 1, "noun": 0, "verb": 0, "left_out": 1}
    assert _rights(report)["no_part"] == 50
    assert report["pools_offered"] == [{"id": "no_pool", "name": "None"}]


def test_parts_are_grouped_ignoring_case_and_right_counts_only_tries_whose_table_had_the_row(tmp_path):
    _pool(tmp_path, POOL)
    with AttemptStore(":memory:") as store:
        # One task asks with Adverb as a row, the other without it.
        with_adverb = _question(QUICKLY, {1: "Noun", 2: "verb", 3: "Adverb"}, [_try({"Noun": [1], "verb": [2], "Adverb": [3]})], "correct",
                                rows=["Noun", "verb", "Adverb"], correct_try=1)
        detail = _detail(with_adverb)
        detail["settings"]["parts_of_speech"] = ["Noun", "verb", "Adverb"]
        _plant(store, 2, detail)
        _plant(store, 1, _detail(_quickly(_try({"noun": [1], "verb": [2]}), correct_try=1)))
        report = _report(store, tmp_path)
    grid = _grid(report)
    assert grid["adverb"]["adverb"] == 1 and grid["adverb"]["left_out"] == 1
    assert grid["noun"]["noun"] == 2
    # Leaving adverb out when it was not a row says nothing, so Right is 1 of 1.
    assert _rights(report)["adverb"] == 100


def test_a_timer_try_counts_with_its_unsorted_words_left_out_and_a_timeout_with_no_try_counts_nothing(tmp_path):
    _pool(tmp_path, POOL)
    with AttemptStore(":memory:") as store:
        _plant(store, 1, _detail(
            _quickly(_try({"noun": [1]}, expired=True), outcome="timeout"),
            _question(DRY, DRY_PARTS, [], "timeout"),
        ), outcome="failure")
        report = _report(store, tmp_path)
    grid = _grid(report)
    assert grid["verb"] == {"noun": 0, "left_out": 1}
    assert set(grid) == {"adverb", "determiner", "noun", "verb"}
    assert len(report["confusions"]["asks"]) == 1


def test_expired_runs_and_abandoned_and_in_progress_attempts_all_count(tmp_path):
    _pool(tmp_path, POOL)
    one = _try({"noun": [1], "verb": [2], "adjective": [3]})
    with AttemptStore(":memory:") as store:
        runs = [{"run": 1, "started": "x", "expired": "2026-11-17T16:10:00.000"}, {"run": 2, "started": "y"}]
        _plant(store, 1, _detail(_quickly(one, outcome="incorrect", run=1), _quickly(one, outcome="incorrect", run=2), runs=runs), outcome="failure")
        _plant(store, 2, _detail(_quickly(one, outcome="incorrect")), outcome="abandoned")
        # Still open: the sentence's first try counts.
        started = NOW - timedelta(hours=1)
        store.begin("younger", PARTS, started, detail=_detail(_quickly(one, outcome=None)))
        report = _report(store, tmp_path)
    assert _grid(report)["adverb"]["adjective"] == 4


def test_the_try_filter_keeps_only_the_chosen_tries(tmp_path):
    _pool(tmp_path, POOL)
    with AttemptStore(":memory:") as store:
        _plant(store, 1, _detail(_quickly(
            _try({"noun": [1], "verb": [2], "adjective": [3]}),
            _try({"noun": [1], "verb": [2]}),
            correct_try=2,
        )))
        first = _report(store, tmp_path, "try=1")
        second = _report(store, tmp_path, "try=2&try=3")
        nothing = _report(store, tmp_path, "try=none")
    assert _grid(first)["adverb"] == {"adjective": 1, "noun": 0, "verb": 0, "left_out": 0}
    assert first["choices"]["try"] == [1]
    assert _grid(second)["adverb"] == {"noun": 0, "verb": 0, "left_out": 1}
    assert nothing["confusions"] is None
    assert nothing["message"] == "No parts of speech sentences for younger in this period."


def test_the_pool_filter_keeps_sentences_by_their_pool_now(tmp_path):
    _pool(tmp_path, POOL)
    _pool(tmp_path, [{"sentence": DRY, "parts": {"verb": ["Dry"]}}], name="Kitchen", pool_id="kitchen")
    with AttemptStore(":memory:") as store:
        _plant(store, 2, _detail(_quickly(_try({"noun": [1], "verb": [2]}), correct_try=1)))
        _plant(store, 1, _detail(_question("A cat sat.", {1: "noun", 2: "verb"}, [_try({"noun": [1], "verb": [2]})], "correct", correct_try=1)))
        everything = _report(store, tmp_path)
        basic = _report(store, tmp_path, "pool=basic")
        none = _report(store, tmp_path, "pool=no_pool")
    assert everything["pools_offered"] == [{"id": "basic", "name": "Basic"}, {"id": "no_pool", "name": "None"}]
    assert everything["choices"]["pool"] == ["basic", "no_pool"]
    assert _grid(everything)["noun"]["noun"] == 2
    assert _grid(basic)["noun"]["noun"] == 1 and "adverb" in _grid(basic)
    assert _grid(none)["noun"]["noun"] == 1 and "adverb" not in _grid(none)
    # The offered pools stay whatever is chosen.
    assert basic["pools_offered"] == everything["pools_offered"]


def test_the_task_filter_offers_the_groups_tasks_and_others_with_attempts(tmp_path):
    _pool(tmp_path, POOL)
    other = TaskKey("parts_of_speech", "pos-gone")
    with AttemptStore(":memory:") as store:
        _plant(store, 2, _detail(_quickly(_try({"noun": [1], "verb": [2]}), correct_try=1)))
        _plant(store, 1, _detail(_quickly(_try({"noun": [1], "verb": [2], "adjective": [3]}), outcome="incorrect")), key=other)
        report = _report(store, tmp_path)
        only = _report(store, tmp_path, "task=pos-gone&task=nope")
    assert report["tasks_offered"] == [{"name": "pos-younger", "in_policy": True}, {"name": "pos-gone", "in_policy": False}]
    assert _grid(report)["adverb"]["adjective"] == 1
    assert only["choices"]["task"] == ["pos-gone"]
    assert _grid(only)["noun"]["noun"] == 1
    assert "nope is not a parts of speech task here, so it is left out." in only["notes"]


def test_the_word_list_has_a_row_for_each_folded_word_and_part_sorted_by_right(tmp_path):
    _pool(tmp_path, POOL)
    monday = datetime(2026, 11, 16, 16, 0)
    with AttemptStore(":memory:") as store:
        _plant(store, 2, _detail(_question(DRY, DRY_PARTS, [
            _try({"verb": [0], "noun": [2, 6], "adjective": [5]}),
        ], "correct", correct_try=1)))
        _plant(store, 1, _detail(_question(DRY, DRY_PARTS, [
            _try({"adjective": [0], "noun": [2, 6], "verb": [5]}),
            _try({"adjective": [0], "noun": [2, 6], "verb": [5], "verb ": []}),
            _try({"verb": [0], "noun": [2], "adjective": [5]}),
        ], "correct", correct_try=3, issued=monday)))
        report = _report(store, tmp_path)
    words = {row["id"]: row for row in report["confusions"]["words"]}
    verb, adjective = words["dry|verb"], words["dry|adjective"]
    assert (verb["sentences"], verb["placements"], verb["right"]) == (2, 4, 50)
    assert verb["instead"] == {"part": "adjective", "label": "adjective", "count": 2}
    assert verb["last_misplaced"] == "Monday 16 November 2026"
    assert (adjective["right"], adjective["instead"]["part"]) == (50, "verb")
    assert words["towel|noun"]["instead"] == {"part": "left_out", "label": "left out", "count": 1}
    assert words["the|no_part"]["right"] == 100 and words["the|no_part"]["instead"] is None
    order = [row["id"] for row in report["confusions"]["words"]]
    assert order.index("dry|verb") < order.index("towel|noun") < order.index("the|no_part")
    # A chosen word lists each sentence that asked it, newest first, with where he put it each time.
    data = report["confusions"]
    asks = word_asks(data, verb)
    assert [ask["placed"] for ask in asks] == [["adjective", "adjective", "verb"], ["verb"]]
    assert asks[0]["sentence"] == "[Dry] the dishes with a dry towel."


def test_a_chosen_pair_lists_its_placements_newest_first_with_the_try(tmp_path):
    _pool(tmp_path, POOL)
    with AttemptStore(":memory:") as store:
        _plant(store, 2, _detail(_quickly(_try({"noun": [1], "verb": [2], "adjective": [3]}), outcome="incorrect")))
        _plant(store, 1, _detail(_quickly(_try({"noun": [1], "verb": [2]}), _try({"noun": [1], "verb": [2], "adjective": [3]}), outcome="incorrect")))
        report = _report(store, tmp_path)
    found = pair_placements(report["confusions"], "adverb", "adjective")
    assert [(each["try"], each["sentence"]) for each in found] == [(2, "The dog ran [quickly]."), (1, "The dog ran [quickly].")]
    assert found[0]["started"].startswith("Tuesday 17 November 2026")


def test_the_confusions_page_says_why_it_has_nothing_to_show(tmp_path):
    with AttemptStore(":memory:") as store:
        assert _report(store, tmp_path)["message"] == "No parts of speech sentences for younger in this period."
        assert confusions_report(store, CLIENTS, now=NOW, pairs=[])["message"] == "Choose a client group."
        assert _report(store, tmp_path, "range=custom&from=2026-02-31&to=2026-03-01")["message"] == "Fix the period to show the confusions."


# A parts of speech attempt's page


def test_a_parts_of_speech_attempt_page_judges_each_word_as_the_quiz_did(tmp_path):
    _pool(tmp_path, POOL)
    runs = [{"run": 1, "started": "a", "expired": "2026-11-17T16:10:00.000"}, {"run": 2, "started": "b"}]
    with AttemptStore(":memory:") as store:
        attempt = _plant(store, 1, _detail(
            _quickly(_try({"noun": [1]}, expired=True), outcome="timeout", run=1),
            _quickly(_try({"noun": [1], "verb": [2], "adjective": [3]}, ms=4000), _try({"noun": [1], "verb": [2]}, ms=9000), correct_try=2, run=2),
            _question(DRY, DRY_PARTS, [_try({"verb": [0], "noun": [2, 6], "adjective": [5]}, ms=6000)], "correct", correct_try=1, run=2),
            _question(DRY, DRY_PARTS, [], "timeout", run=2),
            runs=runs,
        ))
        found = attempt_report(store, str(attempt.id), now=NOW, root=tmp_path)["parts_of_speech"]
    last = found["last"]
    assert last["figures"]["points"] == 1.5 and last["figures"]["pass_mark"] == 7 and last["figures"]["maximum"] == 10
    assert last["right_on_try"] == [1, 1, 0]
    first, dry, gone = last["sentences"]
    assert (first["points"], first["taken_ms"], first["allowed_ms"]) == (0.5, 9000, 90_000)
    marks = first["tries"][0]["words"]
    # The quiz recorded quickly in no part, so the page keeps that, but its link names the pool's part.
    assert marks[3] == {"label": "adjective", "right": False, "belongs": "no part", "link": "adverb"}
    assert marks[0] == {"label": None, "right": True, "belongs": "no part", "link": "determiner"}
    assert first["tries"][1]["words"][3]["label"] is None and first["tries"][1]["words"][3]["right"]
    assert [mark["label"] for mark in dry["tries"][0]["words"]] == ["verb", None, "noun", None, None, "adjective", "noun"]
    assert gone["no_try"] and gone["tries"] == []
    expired = found["expired"][0]
    assert expired["expired"].startswith("Tuesday 17 November 2026")
    assert expired["sentences"][0]["tries"][0]["timer"]
    assert expired["sentences"][0]["tries"][0]["words"][2] == {"label": "left out", "right": False, "belongs": "verb", "link": "verb"}


# The endpoint


@pytest.fixture
def service(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from policy.accounts import Accounts
    from policy.app import create_app
    from policy.store import PolicyStore

    _pool(tmp_path, POOL)
    database = tmp_path / "policy.sqlite3"
    monkeypatch.setenv("DAYWARDEN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("POLICY_FILE", str(tmp_path / "missing.yaml"))
    monkeypatch.setenv("POLICY_DB", str(database))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    with PolicyStore(database) as saved:
        Accounts(saved.connection).set_password("ada", "s3cret-pass")
        recent = datetime.now() - timedelta(hours=2)
        AttemptStore(connection=saved.connection).record(
            "younger", PARTS, "failure", recent, started_at=recent,
            detail=_detail(_quickly(_try({"noun": [1], "verb": [2], "adjective": [3]}), outcome="incorrect")),
        )
    app = create_app()
    app.state.database = database
    return app


def test_confusions_are_sent_only_with_a_session_and_read_the_pools_beside_the_policy(service):
    path = "/parent/api/attempts/parts-of-speech"
    status, body, _headers = call(service, "GET", path, query="client=younger")
    assert status == 401
    assert "quickly" not in body
    _status, _body, headers = call(service, "POST", "/parent/api/login", json_body={"username": "ada", "password": "s3cret-pass"})
    cookie = session_cookie(headers)
    status, body, _headers = call(service, "GET", path, query="client=younger&range=past-week", cookie=cookie)
    assert status == 200
    found = json.loads(body)["confusions"]
    assert {row["part"]: row["cells"] for row in found["rows"]}["adverb"][0] == 1
    status, body, _headers = call(service, "GET", "/parent/api/attempts/1", cookie=cookie)
    words = json.loads(body)["parts_of_speech"]["last"]["sentences"][0]["tries"][0]["words"]
    assert words[3]["link"] == "adverb"
