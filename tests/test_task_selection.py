"""S003.2: pick a revision task, give it up, and count a parent check."""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy.accounts import Accounts  # noqa: E402
from policy.engine import decide  # noqa: E402
from policy.hierarchy import load  # noqa: E402
from policy.review import respond_parent_check  # noqa: E402
from policy.store import PolicyStore  # noqa: E402
from policy.task_page import MUST_FINISH, NOTHING, NOTHING_ELSE, respond_task  # noqa: E402
from policy.tasks import AttemptStore  # noqa: E402
from policy.usage import UsageStore  # noqa: E402

ZONE = ZoneInfo("America/Toronto")
YOUNGER = "192.0.2.40"
OLDER = "192.0.2.50"
SITE = "https://tasks.example/tasks/next"
YOUTUBE = "https://www.youtube.com/watch?v=abc"
PASSWORD = "s3cret-pass"


def _at(month: int, day: int, hour: int = 16, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=ZONE)


def _file(directory: Path, text: str) -> Path:
    path = directory / "policy.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _policy(text: str, directory: Path):
    loaded = load(_file(directory, text))
    assert loaded is not None
    return loaded


def _house(tasks: str, rules: str, *, sites: str = "") -> str:
    return f"""\
entry: gate
timezone: America/Toronto
hostname: tasks.example
port: 443
client_groups:
  younger:
    addresses: ["192.0.2.40"]
  older:
    addresses: ["192.0.2.50"]
{sites}
time_windows:
  afternoon:
    periods:
      - start: "15:00"
        end: "19:00"
tasks:
{tasks}
rule_sets:
{rules}
"""


AFTERNOON = """\
  gate:
    - condition: time_window
      window: afternoon
      when_true: { action: redirect, location: revision_task }
      when_false: { action: deny, message: "Closed." }
"""

ALLOW = """\
  gate:
    - condition: always
      when_true: { action: allow }
"""

TASKS_THEN_ALLOW = """\
  gate:
    - condition: tasks_required
      required: 1
      when_true: { action: allow }
      when_false: { action: redirect, location: revision_task }
"""


def _task(name: str, body: str) -> str:
    return f"  {name}:\n{body}"


def _open(now, path, policy, store, *, method="GET", cookie=None, ip=YOUNGER):
    return respond_task(
        policy,
        store,
        method=method,
        path=path,
        client_ip=ip,
        cookie=cookie,
        now=now,
    )


def _location(page) -> str | None:
    for name, value in page.headers:
        if name == "location":
            return value
    return None


def _set_cookie(page) -> str | None:
    for name, value in page.headers:
        if name == "set-cookie":
            return value.split(";", 1)[0]
    return None


def test_a_never_passed_task_is_chosen_over_one_passed_last_week(tmp_path):
    policy = _policy(
        _house(
            """\
  zeta:
    type: worksheet
    group: younger
    pass_cooldown: 0
  alpha:
    type: worksheet
    group: younger
    pass_cooldown: 0
""",
            AFTERNOON,
        ),
        tmp_path,
    )
    with AttemptStore(":memory:") as store:
        store.record("younger", "alpha", "pass", _at(10, 24))
        first = decide(
            policy, client_ip=YOUNGER, url=YOUTUBE, at=_at(10, 31), attempts=store
        )
        second = decide(
            policy, client_ip=YOUNGER, url=YOUTUBE, at=_at(10, 31, 16, 5), attempts=store
        )
    assert first.decision["location"] == "https://tasks.example/tasks/zeta"
    assert second.decision["location"] == "https://tasks.example/tasks/zeta"


def test_equal_candidates_rotate_in_name_order(tmp_path):
    policy = _policy(
        _house(
            """\
  beta:
    type: worksheet
    group: younger
    pass_cooldown: 0
  alpha:
    type: worksheet
    group: younger
    pass_cooldown: 0
""",
            AFTERNOON,
        ),
        tmp_path,
    )
    with AttemptStore(":memory:") as store:
        picks = [
            decide(policy, client_ip=YOUNGER, url=YOUTUBE, at=_at(10, 31), attempts=store).decision[
                "location"
            ]
            for _ in range(3)
        ]
    assert picks == [
        "https://tasks.example/tasks/alpha",
        "https://tasks.example/tasks/beta",
        "https://tasks.example/tasks/alpha",
    ]


def test_a_required_task_is_chosen_over_an_optional_one(tmp_path):
    policy = _policy(
        _house(
            """\
  optional:
    type: worksheet
    group: younger
    pass_cooldown: 0
  due:
    type: worksheet
    group: younger
    pass_cooldown: 0
    due_date: 2026-10-31
""",
            AFTERNOON,
        ),
        tmp_path,
    )
    with AttemptStore(":memory:") as store:
        trace = decide(policy, client_ip=YOUNGER, url=YOUTUBE, at=_at(10, 31), attempts=store)
    assert trace.decision == {
        "action": "redirect",
        "status": 302,
        "location": "https://tasks.example/tasks/due",
    }


def test_sixteen_hundred_redirects_to_the_chosen_task_on_the_task_site(tmp_path):
    policy = _policy(
        _house(
            """\
  spelling:
    type: spelling
    group: younger
    pass_cooldown: 0
""",
            """\
  gate:
    - condition: site_group
      group: tasks
      when_true: { action: allow }
    - condition: time_window
      window: afternoon
      when_true: { action: redirect, location: revision_task }
      when_false: { action: deny, message: "Closed." }
""",
            sites="""\
site_groups:
  tasks:
    priority: 10
    patterns: ["tasks.example"]
  entertainment:
    priority: 30
    patterns: ["*.youtube.com"]
""",
        ),
        tmp_path,
    )
    with AttemptStore(":memory:") as store:
        morning = decide(policy, client_ip=YOUNGER, url=YOUTUBE, at=_at(10, 31, 10), attempts=store)
        afternoon = decide(policy, client_ip=YOUNGER, url=YOUTUBE, at=_at(10, 31, 16), attempts=store)
        page = decide(
            policy,
            client_ip=YOUNGER,
            url=afternoon.decision["location"],
            at=_at(10, 31, 16),
            attempts=store,
        )
    assert morning.decision["action"] == "deny"
    assert afternoon.decision["status"] == 302
    assert urlsplit(afternoon.decision["location"]).hostname == "tasks.example"
    assert afternoon.decision["location"] == "https://tasks.example/tasks/spelling"
    assert page.decision == {"action": "allow"}


def test_an_optional_url_does_not_start_while_a_required_task_is_eligible(tmp_path):
    policy = _policy(
        _house(
            """\
  optional:
    type: worksheet
    group: younger
    pass_cooldown: 0
  due:
    type: worksheet
    group: younger
    pass_cooldown: 0
    due_date: 2026-10-31
""",
            ALLOW,
        ),
        tmp_path,
    )
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        trace = decide(
            policy,
            client_ip=YOUNGER,
            url="https://tasks.example/tasks/optional",
            at=now,
            attempts=store,
        )
        page = _open(now, "/tasks/optional", policy, store)
        assert store.in_progress("younger", "optional") is None
        assert store.attempts("younger", "optional") == ()
    assert trace.decision["location"] == "https://tasks.example/tasks/due"
    assert page.status == 302
    assert _location(page) == "https://tasks.example/tasks/due"


def test_a_parent_check_increases_todays_count_and_the_child_cannot_record_one(tmp_path):
    policy = _policy(
        _house(
            """\
  credit:
    type: parent_check
    group: younger
    pass_cooldown: 0
    available_from: 2020-01-01
    due_date: 2020-01-01
    max_skips: 0
    max_passes: 1
  spelling:
    type: spelling
    group: younger
    pass_cooldown: 0
""",
            TASKS_THEN_ALLOW,
        ),
        tmp_path,
    )
    now = _at(10, 31)
    with PolicyStore(":memory:") as saved:
        usage = UsageStore(connection=saved.connection)
        store = AttemptStore(connection=saved.connection)
        accounts = Accounts(saved.connection)
        accounts.set_password("ada", PASSWORD)
        before = decide(
            policy, client_ip=YOUNGER, url=YOUTUBE, at=now, ledger=usage, attempts=store
        )
        assert before.decision["location"] == "https://tasks.example/tasks/spelling"
        unsigned = respond_parent_check(
            accounts, cookie=None, form={"client": "younger"}, now=now, tasks=policy.tasks
        )
        assert "Enter your username and password." in unsigned.body
        child = _open(now, "/tasks/spelling", policy, store, method="POST")
        assert store.passes_on("younger", now.date()) == 0
        assert "pass" not in {row.outcome for row in store.attempts("younger")}
        key = accounts.login("ada", PASSWORD, now)
        recorded = respond_parent_check(
            accounts,
            cookie=key,
            form={"client": "younger", "outcome": "pass"},
            now=now,
            tasks=policy.tasks,
        )
        assert "younger" in recorded.body
        assert store.passes_on("younger", now.date()) == 1
        assert [row.task for row in store.attempts("younger") if row.outcome == "pass"] == ["credit"]
        after = decide(
            policy, client_ip=YOUNGER, url=YOUTUBE, at=now, ledger=usage, attempts=store
        )
        assert after.decision == {"action": "allow"}
        assert child.status == 200


def test_the_picker_never_returns_a_parent_check(tmp_path):
    policy = _policy(
        _house(
            """\
  credit:
    type: parent_check
    group: younger
    pass_cooldown: 0
    available_from: 2020-01-01
    due_date: 2026-10-31
    max_skips: 0
    max_passes: 3
""",
            AFTERNOON,
        ),
        tmp_path,
    )
    with AttemptStore(":memory:") as store:
        trace = decide(policy, client_ip=YOUNGER, url=YOUTUBE, at=_at(10, 31), attempts=store)
        page = _open(_at(10, 31), "/tasks/credit", policy, store)
        assert trace.decision["location"] == SITE
        assert page.status == 200
        assert NOTHING in page.body
        assert "credit" not in page.body
        assert store.attempts("younger") == ()


def test_a_task_at_its_pass_cap_is_not_offered(tmp_path):
    policy = _policy(
        _house(
            """\
  finished:
    type: spelling
    group: younger
    pass_cooldown: 21
    max_passes: 3
  fresh:
    type: spelling
    group: younger
    pass_cooldown: 0
""",
            AFTERNOON,
        ),
        tmp_path,
    )
    with AttemptStore(":memory:") as store:
        for day in (1, 2, 3):
            store.record("younger", "finished", "pass", _at(9, day))
        trace = decide(policy, client_ip=YOUNGER, url=YOUTUBE, at=_at(10, 31), attempts=store)
    assert trace.decision["location"] == "https://tasks.example/tasks/fresh"


def test_giving_up_an_optional_task_abandons_it_and_opens_another(tmp_path):
    policy = _policy(
        _house(
            """\
  alpha:
    type: spelling
    group: younger
    pass_cooldown: 0
  beta:
    type: spelling
    group: younger
    pass_cooldown: 0
""",
            ALLOW,
        ),
        tmp_path,
    )
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        opened = _open(now, "/tasks/alpha", policy, store)
        assert "Try a different task" in opened.body
        assert store.in_progress("younger", "alpha") is not None
        left = _open(now, "/tasks/alpha", policy, store, method="POST")
        assert store.passes_on("younger", now.date()) == 0
        assert store.attempts("younger", "alpha")[-1].outcome == "abandoned"
        assert left.status == 302
        assert _location(left) == "https://tasks.example/tasks/beta"
        followed = _open(now, "/tasks/beta", policy, store)
        assert followed.status == 200
        assert store.in_progress("younger", "beta") is not None


def test_giving_up_the_only_eligible_task_says_nothing_else_is_available(tmp_path):
    policy = _policy(
        _house(
            """\
  only:
    type: spelling
    group: younger
    pass_cooldown: 0
""",
            ALLOW,
        ),
        tmp_path,
    )
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        _open(now, "/tasks/only", policy, store)
        left = _open(now, "/tasks/only", policy, store, method="POST")
        assert left.status == 200
        assert NOTHING_ELSE in left.body
        assert _location(left) is None
        assert store.attempts("younger", "only")[-1].outcome == "abandoned"
        assert store.passes_on("younger", now.date()) == 0


def test_the_only_required_task_cannot_be_abandoned(tmp_path):
    policy = _policy(
        _house(
            """\
  due:
    type: spelling
    group: younger
    pass_cooldown: 0
    due_date: 2026-10-31
  optional:
    type: spelling
    group: younger
    pass_cooldown: 0
""",
            ALLOW,
        ),
        tmp_path,
    )
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        opened = _open(now, "/tasks/due", policy, store)
        attempt = store.in_progress("younger", "due")
        assert attempt is not None
        assert "Try a different task" in opened.body
        _open(now, "/tasks/due", policy, store)
        assert store.in_progress("younger", "due").id == attempt.id
        left = _open(
            now,
            "/tasks/due",
            policy,
            store,
            method="POST",
        )
        assert left.status == 200
        assert MUST_FINISH in left.body
        assert _location(left) is None
        assert store.in_progress("younger", "due").id == attempt.id
        assert store.in_progress("younger", "due").outcome == "in_progress"
        assert store.passes_on("younger", now.date()) == 0
        assert store.in_progress("younger", "optional") is None


def test_giving_up_one_required_task_opens_another_required_task(tmp_path):
    policy = _policy(
        _house(
            """\
  first:
    type: spelling
    group: younger
    pass_cooldown: 0
    due_date: 2026-10-31
  second:
    type: spelling
    group: younger
    pass_cooldown: 0
    due_date: 2026-10-31
  optional:
    type: spelling
    group: younger
    pass_cooldown: 0
""",
            ALLOW,
        ),
        tmp_path,
    )
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        _open(now, "/tasks/first", policy, store)
        left = _open(now, "/tasks/first", policy, store, method="POST")
        assert store.attempts("younger", "first")[-1].outcome == "abandoned"
        assert urlsplit(_location(left)).path == "/tasks/second"
        assert store.attempts("younger", "optional") == ()
        cookie = _set_cookie(left)
        _open(now, "/tasks/second", policy, store, cookie=cookie)
        again = _open(now, "/tasks/second", policy, store, method="POST", cookie=cookie)
        assert store.attempts("younger", "second")[-1].outcome == "abandoned"
        landed = urlsplit(_location(again)).path
        assert landed == "/tasks/first"
        assert store.attempts("younger", "optional") == ()
        assert store.passes_on("younger", now.date()) == 0


def test_three_skip_days_still_abandon_and_the_next_day_does_not(tmp_path):
    policy = _policy(
        _house(
            """\
  words:
    type: spelling
    group: younger
    pass_cooldown: 21
    max_skips: 3
""",
            ALLOW,
        ),
        tmp_path,
    )
    with AttemptStore(":memory:") as store:
        for day in (2, 3, 4):
            now = _at(11, day)
            _open(now, "/tasks/words", policy, store)
            left = _open(now, "/tasks/words", policy, store, method="POST")
            assert left.status == 200
            assert NOTHING_ELSE in left.body
            assert store.attempts("younger", "words")[-1].outcome == "abandoned"
            assert not store.is_required(policy.task("words"), "younger", now.date())
        locked = _at(11, 5)
        _open(locked, "/tasks/words", policy, store)
        refused = _open(locked, "/tasks/words", policy, store, method="POST")
        assert store.is_required(policy.task("words"), "younger", locked.date())
        assert refused.status == 200
        assert MUST_FINISH in refused.body
        assert store.in_progress("younger", "words") is not None
        assert store.in_progress("younger", "words").outcome == "in_progress"


def test_a_second_abandon_on_a_skip_day_does_not_add_a_skip(tmp_path):
    policy = _policy(
        _house(
            """\
  words:
    type: spelling
    group: younger
    pass_cooldown: 0
    max_skips: 3
""",
            ALLOW,
        ),
        tmp_path,
    )
    now = _at(11, 2)
    with AttemptStore(":memory:") as store:
        _open(now, "/tasks/words", policy, store)
        _open(now, "/tasks/words", policy, store, method="POST")
        _open(now, "/tasks/words", policy, store)
        _open(now, "/tasks/words", policy, store, method="POST")
        from policy.tasks import skip_days

        assert skip_days("words", "younger", store.attempts("younger"), before=now.date()) == frozenset()
        assert len(skip_days("words", "younger", store.attempts("younger"))) == 1


def test_a_required_task_in_its_failure_cooldown_is_not_offered(tmp_path):
    policy = _policy(
        _house(
            """\
  due:
    type: spelling
    group: younger
    pass_cooldown: 21
    failure_cooldown: 1
    due_date: 2026-10-31
  optional:
    type: spelling
    group: younger
    pass_cooldown: 0
""",
            AFTERNOON,
        ),
        tmp_path,
    )
    with AttemptStore(":memory:") as store:
        store.record("younger", "due", "failure", _at(10, 31, 9))
        trace = decide(policy, client_ip=YOUNGER, url=YOUTUBE, at=_at(10, 31), attempts=store)
        assert not store.is_eligible(policy.task("due"), "younger", _at(10, 31).date())
    assert trace.decision["location"] == "https://tasks.example/tasks/optional"


def test_a_task_available_tomorrow_is_not_offered_today(tmp_path):
    policy = _policy(
        _house(
            """\
  later:
    type: spelling
    group: younger
    pass_cooldown: 0
    available_from: 2026-11-01
  today:
    type: spelling
    group: younger
    pass_cooldown: 0
""",
            AFTERNOON,
        ),
        tmp_path,
    )
    with AttemptStore(":memory:") as store:
        trace = decide(policy, client_ip=YOUNGER, url=YOUTUBE, at=_at(10, 31), attempts=store)
    assert trace.decision["location"] == "https://tasks.example/tasks/today"


def test_nothing_eligible_is_a_page_and_not_a_redirect_loop(tmp_path):
    policy = _policy(
        _house(
            """\
  later:
    type: spelling
    group: younger
    pass_cooldown: 0
    available_from: 2026-11-01
""",
            AFTERNOON,
        ),
        tmp_path,
    )
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        youtube = decide(policy, client_ip=YOUNGER, url=YOUTUBE, at=now, attempts=store)
        follow = decide(policy, client_ip=YOUNGER, url=SITE, at=now, attempts=store)
        page = _open(now, "/tasks/next", policy, store)
    assert youtube.decision["location"] == SITE
    assert follow.decision == {"action": "allow"}
    assert page.status == 200
    assert NOTHING in page.body
    assert _location(page) is None


def test_a_pass_on_a_required_task_scores_one_and_clears_the_due_date(tmp_path):
    policy = _policy(
        _house(
            """\
  due:
    type: spelling
    group: younger
    pass_cooldown: 21
    due_date: 2026-10-31
""",
            TASKS_THEN_ALLOW,
        ),
        tmp_path,
    )
    now = _at(10, 31)
    with UsageStore(":memory:") as usage:
        store = AttemptStore(connection=usage.connection)
        assert store.is_required(policy.task("due"), "younger", now.date())
        started = store.begin("younger", "due", now)
        store.finish(started.id, "pass", now, detail={"answers": ["cat"]})
        assert store.passes_on("younger", now.date()) == 1
        assert not store.is_required(policy.task("due"), "younger", now.date())
        trace = decide(policy, client_ip=YOUNGER, url=YOUTUBE, at=now, ledger=usage, attempts=store)
    assert trace.decision == {"action": "allow"}


def test_an_older_child_does_not_resume_the_younger_attempt(tmp_path):
    policy = _policy(
        _house(
            """\
  shared:
    type: spelling
    groups: [younger, older]
    pass_cooldown: 0
""",
            ALLOW,
        ),
        tmp_path,
    )
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        _open(now, "/tasks/shared", policy, store)
        _open(now, "/tasks/shared", policy, store, ip=OLDER)
        assert store.in_progress("younger", "shared").id != store.in_progress("older", "shared").id


def test_a_task_named_next_does_not_replace_the_picker_page(tmp_path):
    policy = _policy(
        _house(
            """\
  next:
    type: spelling
    group: younger
    pass_cooldown: 0
""",
            AFTERNOON,
        ),
        tmp_path,
    )
    now = _at(10, 31)
    with AttemptStore(":memory:") as store:
        trace = decide(policy, client_ip=YOUNGER, url=YOUTUBE, at=now, attempts=store)
        entry = _open(now, "/tasks/next", policy, store)
        page = _open(now, "/tasks/work/next", policy, store)
        assert trace.decision["location"] == "https://tasks.example/tasks/work/next"
        assert entry.status == 302
        assert _location(entry) == "https://tasks.example/tasks/work/next"
        assert page.status == 200
        assert store.in_progress("younger", "next") is not None


def test_the_service_serves_the_task_and_counts_a_parent_check(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text(
        _house(
            """\
  due:
    type: spelling
    group: younger
    pass_cooldown: 0
    due_date: 2020-01-01
  optional:
    type: spelling
    group: younger
    pass_cooldown: 0
  credit:
    type: parent_check
    group: younger
    pass_cooldown: 0
""",
            TASKS_THEN_ALLOW,
        ),
        encoding="utf-8",
    )
    database = tmp_path / "policy.sqlite3"
    monkeypatch.setenv("POLICY_FILE", str(policy_file))
    monkeypatch.setenv("POLICY_DB", str(database))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    monkeypatch.setenv("DECISION_FILE", str(tmp_path / "decision.json"))
    monkeypatch.delenv("DECISION_STUB", raising=False)
    app = create_app()

    def call(method, path, *, body=b"", cookie=None, client=YOUNGER, scheme="http", content_type=None):
        messages = []
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            messages.append(message)

        headers = [(b"x-daywarden-client", client.encode())]
        if content_type:
            headers.append((b"content-type", content_type.encode()))
        if cookie:
            headers.append((b"cookie", cookie.encode()))
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": scheme,
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
            "client": ("172.17.0.2", 12345),
            "server": ("127.0.0.1", 80),
            "root_path": "",
        }
        asyncio.run(app(scope, receive, send))
        start = next(item for item in messages if item["type"] == "http.response.start")
        payload = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
        found: dict[str, list[str]] = {}
        for key, value in start["headers"]:
            found.setdefault(key.decode(), []).append(value.decode())
        return start["status"], payload.decode(), found

    status, body, headers = call("GET", "/tasks/optional")
    assert status == 302
    assert headers["location"] == ["https://tasks.example/tasks/due"]
    status, body, _headers = call("GET", "/tasks/due")
    assert status == 200
    assert "Try a different task" in body
    decision = json.dumps(
        {
            "client_ip": YOUNGER,
            "method": "GET",
            "url": YOUTUBE,
            "occurred_at": "2026-10-31T16:00:00-04:00",
        }
    ).encode()
    status, body, _headers = call(
        "POST", "/v1/decisions", body=decision, content_type="application/json"
    )
    assert status == 200
    assert json.loads(body)["location"].endswith("/tasks/due")
    with sqlite3_passes(database) as count:
        assert count == 0


def sqlite3_passes(database: Path):
    import sqlite3
    from contextlib import contextmanager

    @contextmanager
    def _read():
        with sqlite3.connect(database) as connection:
            yield connection.execute(
                "SELECT COUNT(*) FROM attempts WHERE outcome = 'pass'"
            ).fetchone()[0]

    return _read()
