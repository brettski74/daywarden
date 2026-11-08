"""S008.2: a request is classified once, then nested rule sets decide it."""

import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy.engine import (  # noqa: E402
    MemoryLedger,
    decide,
    evaluate,
    log_fields,
    matches,
)
from policy.hierarchy import ConfigError, SiteGroup, load  # noqa: E402

SYDNEY = ZoneInfo("Australia/Sydney")
OPEN_POLICY = """\
entry: entry
rule_sets:
  entry:
    - condition: always
      when_true: { action: allow }
"""
PLACEHOLDER = "https://tasks.example/tasks/next"
NO_RULE = "No rule granted access."
BEDTIME = {"action": "deny", "status": 403, "message": "It's bedtime."}
CLOSED = {"action": "deny", "status": 403, "message": "YouTube is closed for today."}
REDIRECT = {"action": "redirect", "status": 302, "location": PLACEHOLDER}
TIME_UP = {"action": "deny", "status": 403, "message": "Time is up for today."}
ALLOW = {"action": "allow"}
WEDNESDAY = date(2026, 10, 21)
YOUTUBE = "https://www.youtube.com/watch?v=abc"

WEDNESDAY_POLICY = """\
entry: younger
timezone: Australia/Sydney
hostname: tasks.example
port: 443

client_groups:
  younger:
    addresses: ["192.0.2.40"]

site_groups:
  entertainment:
    priority: 30
    patterns:
      - "*.youtube.com"

time_windows:
  bedtime:
    periods:
      - start: "00:00"
        end: "07:00"
        days: monday-thursday
  school:
    periods:
      - start: "07:00"
        end: "15:00"
        days: monday-thursday
  evening:
    periods:
      - start: "15:00"
        end: "19:00"
        days: monday-thursday

quotas:
  entertainment:
    time: 2h
    ruleset: meter

rule_sets:
  meter:
    - condition: always
      when_true: { action: deny, message: "Not used for access." }

  younger:
    - condition: client_group
      group: younger
      when_true: { action: evaluate, ruleset: entertainment_hours }

  entertainment_hours:
    - condition: time_window
      window: bedtime
      when_true: { action: deny, message: "It's bedtime." }
    - condition: time_window
      window: school
      when_true: { action: redirect, location: revision_task }
    - condition: time_window
      window: evening
      when_true: { action: evaluate, ruleset: entertainment_evening }
      when_false: { action: deny, message: "YouTube is closed for today." }

  entertainment_evening:
    - condition: tasks_required
      required: 2
      when_false: { action: redirect, location: revision_task }
    - condition: time_remaining
      quota: entertainment
      when_true: { action: allow }
      when_false: { action: deny, message: "Time is up for today." }
"""


def _file(directory: Path, text: str) -> Path:
    path = directory / "policy.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _load(directory: Path, text: str):
    loaded = load(_file(directory, text))
    assert loaded is not None
    return loaded


def _at(day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=SYDNEY)


def _span(directory: Path, start: str, end: str, day: str | None):
    constraint = "" if day is None else f"\n        day: {day}"
    return _load(
        directory,
        f"""\
entry: entry
time_windows:
  span:
    periods:
      - start: "{start}"
        end: "{end}"{constraint}
rule_sets:
  entry:
    - condition: time_window
      window: span
      when_true: {{ action: allow }}
      when_false: {{ action: deny, message: "Outside." }}
""",
    )


def _allows(policy, at: datetime) -> bool:
    trace = decide(policy, client_ip="192.0.2.10", url="https://example.com/", at=at)
    return trace.decision == ALLOW


def test_a_site_group_does_not_own_a_rule_list():
    assert "rules" not in SiteGroup.__dataclass_fields__


def test_windows_include_the_start_and_exclude_the_end(tmp_path):
    friday = _span(tmp_path, "14:00", "14:00", "friday")
    assert _allows(friday, _at(23, 14, 0))
    assert _allows(friday, _at(23, 18, 0))
    assert not _allows(friday, _at(24, 14, 0))
    assert not _allows(friday, _at(22, 18, 0))

    plus = _span(tmp_path, "14:00", "14:00+1", "friday")
    assert _allows(plus, _at(24, 18, 0))
    assert not _allows(plus, _at(25, 14, 0))

    night = _span(tmp_path, "22:00", "07:00", "saturday")
    assert _allows(night, _at(24, 23, 30))
    assert _allows(night, _at(25, 6, 30))
    assert not _allows(night, _at(24, 6, 30))

    ordinary = _span(tmp_path, "15:00", "19:00", None)
    assert _allows(ordinary, _at(21, 15, 0))
    assert not _allows(ordinary, _at(21, 19, 0))


def test_the_lower_priority_number_is_the_only_site_group_a_rule_sees(tmp_path):
    policy = _load(
        tmp_path,
        """\
entry: sites
site_groups:
  wide:
    priority: 20
    patterns: ["*.youtube.com"]
  narrow:
    priority: 5
    patterns: ["www.youtube.com"]
rule_sets:
  sites:
    - condition: site_group
      group: wide
      when_true: { action: deny, message: "Wide." }
    - condition: site_group
      group: narrow
      when_true: { action: allow }
    - condition: site_group
      group: default
      when_true: { action: deny, message: "Default site." }
""",
    )
    page = "https://www.youtube.com/watch?v=abc"
    narrow = decide(policy, client_ip="192.0.2.10", url=page, at=_at(21, 16, 0))
    assert narrow.decision == ALLOW
    assert narrow.site_group == "narrow"
    folded = decide(
        policy,
        client_ip="192.0.2.10",
        url="https://WWW.YouTube.com/watch#frag",
        at=_at(21, 16, 0),
    )
    assert folded.site_group == "narrow"
    wide = decide(policy, client_ip="192.0.2.10", url="https://music.youtube.com/", at=_at(21, 16, 0))
    assert wide.decision["message"] == "Wide."
    assert wide.site_group == "wide"
    missed = decide(policy, client_ip="192.0.2.10", url="https://example.org/", at=_at(21, 16, 0))
    assert missed.decision["message"] == "Default site."
    assert missed.site_group == "default"


def test_an_address_in_no_client_group_is_default_and_is_not_granted_access(tmp_path):
    policy = _load(
        tmp_path,
        """\
entry: household
client_groups:
  younger:
    addresses: ["192.0.2.40"]
rule_sets:
  household:
    - condition: client_group
      group: younger
      when_true: { action: allow }
""",
    )
    allowed = decide(policy, client_ip="192.0.2.40", url="https://example.com/", at=_at(21, 16, 0))
    assert allowed.decision == ALLOW
    assert allowed.client_group == "younger"
    mapped = decide(
        policy,
        client_ip="::ffff:192.0.2.40",
        url="https://example.com/",
        at=_at(21, 16, 0),
    )
    assert mapped.client_group == "younger"
    refused = decide(policy, client_ip="192.0.2.99", url="https://example.com/", at=_at(21, 16, 0))
    assert refused.decision == {"action": "deny", "status": 403, "message": NO_RULE}
    assert refused.client_group == "default"
    assert refused.continued is True
    assert log_fields(refused)["rule_set"] is None
    assert log_fields(refused)["rule_index"] is None
    assert log_fields(refused)["continued"] is True


def test_evaluate_substitutes_the_child_and_a_cycle_fails_the_load(tmp_path):
    policy = _load(
        tmp_path,
        """\
entry: household
site_groups:
  school:
    priority: 10
    patterns: ["classroom.google.com"]
rule_sets:
  allow_school:
    - condition: site_group
      group: school
      when_true: { action: allow }
  closed:
    - condition: always
      when_true: { action: deny, message: "Closed." }
  household:
    - condition: always
      when_true: { action: evaluate, ruleset: allow_school }
    - condition: site_group
      group: school
      when_true: { action: deny, message: "Should not run after allow." }
    - condition: always
      when_true: { action: evaluate, ruleset: closed }
    - condition: always
      when_true: { action: allow }
""",
    )
    school = decide(
        policy,
        client_ip="192.0.2.10",
        url="https://classroom.google.com/u/0/h",
        at=_at(21, 10, 0),
    )
    assert school.decision == ALLOW
    assert school.rule_set == "allow_school"
    assert school.rule_index == 1
    other = decide(policy, client_ip="192.0.2.10", url="https://example.org/", at=_at(21, 10, 0))
    assert other.decision == {"action": "deny", "status": 403, "message": "Closed."}
    assert other.rule_set == "closed"
    assert other.rule_index == 1
    with pytest.raises(ConfigError, match="evaluate cycle"):
        _load(
            tmp_path,
            """\
entry: a
rule_sets:
  a:
    - condition: always
      when_true: { action: evaluate, ruleset: a }
""",
        )


def test_an_inline_list_is_logged_by_the_path_of_the_rule_that_contains_it(tmp_path):
    policy = _load(
        tmp_path,
        """\
entry: entry
rule_sets:
  entry:
    - condition: always
      when_true:
        action: evaluate
        rules:
          - condition: always
            when_true: { action: continue }
          - condition: always
            when_true: { action: deny, message: "Nested." }
""",
    )
    trace = decide(policy, client_ip="192.0.2.10", url="https://example.com/", at=_at(21, 10, 0))
    assert trace.decision["message"] == "Nested."
    assert log_fields(trace)["rule_set"] == "entry rule 1 when_true"
    assert log_fields(trace)["rule_index"] == 2
    assert log_fields(trace)["client_group"] == "default"
    assert log_fields(trace)["site_group"] == "default"


def test_the_wednesday_entertainment_schedule(tmp_path):
    policy = _load(tmp_path, WEDNESDAY_POLICY)
    ip = "192.0.2.40"

    def run(hour: int, minute: int, ledger=None):
        return decide(policy, client_ip=ip, url=YOUTUBE, at=_at(21, hour, minute), ledger=ledger)

    bedtime = run(6, 30)
    assert bedtime.decision == BEDTIME
    assert log_fields(bedtime) == {
        "client_group": "younger",
        "site_group": "entertainment",
        "rule_set": "entertainment_hours",
        "rule_index": 1,
        "continued": False,
        "decision": BEDTIME,
    }
    assert run(10, 0).decision == REDIRECT
    assert run(16, 0).decision == REDIRECT
    assert run(16, 0).rule_set == "entertainment_evening"
    assert run(20, 0).decision == CLOSED

    done = MemoryLedger()
    done.set_successes("younger", WEDNESDAY, 2)
    allowed = run(16, 0, done)
    assert allowed.decision == ALLOW
    assert allowed.rule_set == "entertainment_evening"
    assert allowed.rule_index == 2

    short = MemoryLedger()
    short.set_successes("younger", WEDNESDAY, 1)
    assert run(16, 0, short).decision == REDIRECT
    yesterday = MemoryLedger()
    yesterday.set_successes("younger", date(2026, 10, 20), 2)
    assert run(16, 0, yesterday).decision == REDIRECT
    sibling = MemoryLedger()
    sibling.set_successes("older", WEDNESDAY, 2)
    assert run(16, 0, sibling).decision == REDIRECT

    # The quota's grace is five minutes. Exactly two hours is not under the limit.
    full = MemoryLedger()
    full.set_successes("younger", WEDNESDAY, 2)
    full.set_ended_seconds("younger", "entertainment", WEDNESDAY, 2 * 60 * 60)
    stopped = run(16, 0, full)
    assert stopped.decision == TIME_UP
    assert stopped.rule_set == "entertainment_evening"
    assert stopped.rule_index == 2

    ready = MemoryLedger()
    ready.set_successes("younger", WEDNESDAY, 2)
    assert run(14, 59, ready).decision == REDIRECT
    assert run(15, 0, ready).decision == ALLOW
    assert run(19, 0, ready).decision == CLOSED


def test_a_missing_byte_limit_takes_the_false_branch(tmp_path):
    omitted = _load(
        tmp_path,
        """\
entry: check
quotas:
  open:
    time: 1h
    ruleset: meter
rule_sets:
  meter:
    - condition: always
      when_true: { action: continue }
  check:
    - condition: volume_remaining
      quota: open
      when_true: { action: allow }
      when_false: { action: deny, message: "No bytes left." }
""",
    )
    none = decide(omitted, client_ip="192.0.2.10", url="https://example.com/", at=_at(21, 16, 0))
    assert none.decision == {"action": "deny", "status": 403, "message": "No bytes left."}
    stored = MemoryLedger()
    stored.set_stored_bytes("default", "open", WEDNESDAY, 0)
    still = decide(
        omitted,
        client_ip="192.0.2.10",
        url="https://example.com/",
        at=_at(21, 16, 0),
        ledger=stored,
    )
    assert still.decision["message"] == "No bytes left."

    capped = _load(
        tmp_path,
        """\
entry: check
quotas:
  capped:
    time: 1h
    bytes: 720b
    ruleset: meter
rule_sets:
  meter:
    - condition: always
      when_true: { action: continue }
  check:
    - condition: volume_remaining
      quota: capped
      when_true: { action: allow }
      when_false: { action: deny, message: "No bytes left." }
""",
    )
    under = decide(capped, client_ip="192.0.2.10", url="https://example.com/", at=_at(21, 16, 0))
    assert under.decision == ALLOW
    full = MemoryLedger()
    full.set_stored_bytes("default", "capped", WEDNESDAY, 720)
    blocked = decide(
        capped,
        client_ip="192.0.2.10",
        url="https://example.com/",
        at=_at(21, 16, 0),
        ledger=full,
    )
    assert blocked.decision["message"] == "No bytes left."

    timeless = _load(
        tmp_path,
        """\
entry: check
quotas:
  timeless:
    bytes: 720b
    ruleset: meter
rule_sets:
  meter:
    - condition: always
      when_true: { action: continue }
  check:
    - condition: time_remaining
      quota: timeless
      when_true: { action: allow }
      when_false: { action: deny, message: "No time left." }
""",
    )
    no_time = decide(timeless, client_ip="192.0.2.10", url="https://example.com/", at=_at(21, 16, 0))
    assert no_time.decision["message"] == "No time left."


def test_revision_task_is_replaced_before_the_answer_is_returned(tmp_path, monkeypatch):
    monkeypatch.setenv("POLICY_PORT", "8090")
    monkeypatch.setenv("MACHINE_HOSTNAME", str(tmp_path / "no-such-hostname"))
    policy = _load(
        tmp_path,
        """\
entry: entry
hostname: tasks.example
port: 443
rule_sets:
  entry:
    - condition: always
      when_true: { action: redirect, location: revision_task }
""",
    )
    trace = decide(policy, client_ip="192.0.2.10", url="https://example.com/", at=_at(21, 10, 0))
    assert trace.decision == REDIRECT
    unset = _load(
        tmp_path,
        """\
entry: entry
rule_sets:
  entry:
    - condition: always
      when_true: { action: redirect, location: revision_task }
""",
    )
    monkeypatch.setattr("policy.selection.socket.gethostname", lambda: "lounge")
    named = decide(unset, client_ip="192.0.2.10", url="https://example.com/", at=_at(21, 10, 0))
    assert named.decision == {
        "action": "redirect",
        "status": 302,
        "location": "https://lounge:8090/tasks/next",
    }


def test_a_top_level_continue_is_a_deny_and_evaluate_keeps_the_continue(tmp_path):
    policy = _load(
        tmp_path,
        """\
entry: open
rule_sets:
  open:
    - condition: always
      when_true: { action: continue }
""",
    )
    trace = decide(policy, client_ip="192.0.2.10", url="https://example.com/", at=_at(21, 12, 0))
    assert trace.decision == {"action": "deny", "status": 403, "message": NO_RULE}
    assert trace.continued is True
    raw = evaluate(
        policy,
        policy.rule_set("open"),
        client_group="default",
        site_group="default",
        at=_at(21, 12, 0),
        rule_set="open",
    )
    assert raw.decision == {"action": "continue"}
    assert raw.continued is False


def _post_decision(app, document: dict) -> tuple[int, bytes]:
    """POST /v1/decisions through the ASGI app, without an HTTP client library."""
    import asyncio

    messages: list[dict] = []
    body = json.dumps(document).encode()
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/decisions",
        "raw_path": b"/v1/decisions",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 80),
        "root_path": "",
    }
    asyncio.run(app(scope, receive, send))
    status = next(item["status"] for item in messages if item["type"] == "http.response.start")
    payload = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
    return status, payload


def test_a_required_count_of_zero_passes_for_the_default_client_group(tmp_path):
    policy = _load(
        tmp_path,
        """\
entry: entry
rule_sets:
  entry:
    - condition: tasks_required
      required: 0
      when_true: { action: allow }
      when_false: { action: deny, message: "Still working." }
""",
    )
    trace = decide(policy, client_ip="192.0.2.99", url="https://example.com/", at=_at(21, 16, 0))
    assert trace.decision == ALLOW
    assert trace.client_group == "default"


def test_a_yaml_policy_is_decided_by_the_rule_set(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    policy = tmp_path / "policy.yaml"
    policy.write_text(
        """\
entry: entry
timezone: Australia/Sydney
rule_sets:
  entry:
    - condition: always
      when_true: { action: deny, message: "From the rule set." }
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("POLICY_FILE", str(policy))
    monkeypatch.setenv("POLICY_DB", str(tmp_path / "policy.sqlite3"))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    monkeypatch.delenv("PARENT_PASSWORD", raising=False)
    status, body = _post_decision(
        create_app(),
        {
            "client_ip": "192.0.2.40",
            "method": "GET",
            "url": "https://example.org/",
            "occurred_at": "2026-10-21T00:00:00+00:00",
        },
    )
    assert status == 200
    assert json.loads(body) == {"action": "deny", "status": 403, "message": "From the rule set."}
    logged = json.loads((tmp_path / "decisions.jsonl").read_text(encoding="utf-8"))
    assert logged["client_group"] == "default"
    assert logged["site_group"] == "default"
    assert logged["rule_set"] == "entry"
    assert logged["rule_index"] == 1
    assert logged["continued"] is False
    assert logged["decision"]["message"] == "From the rule set."
    assert logged["local_time"] == "2026-10-21T11:00:00+11:00"


DECISION_LINE_POLICY = """\
entry: household
timezone: Australia/Sydney
client_groups:
  kids:
    addresses: ["192.0.2.40"]
site_groups:
  video:
    priority: 10
    patterns: ["*.youtube.com"]
  games:
    priority: 20
    patterns: ["games.example"]
  news:
    priority: 30
    patterns: ["news.example"]
rule_sets:
  household:
    - condition: site_group
      group: video
      when_true: { action: deny, message: "No video." }
    - condition: site_group
      group: games
      when_true: { action: redirect, location: "https://garden:8084/tasks/next?return=abc" }
    - condition: site_group
      group: news
      when_true: { action: allow }
"""


@pytest.mark.parametrize(
    ("url", "line", "decision"),
    [
        (
            YOUTUBE,
            f"decision deny GET {YOUTUBE} (video) for kids at 2026-10-21T11:00:00+11:00 by household rule 1",
            {"action": "deny", "status": 403, "message": "No video."},
        ),
        (
            "https://games.example/play",
            "decision redirect GET https://games.example/play (games) for kids at 2026-10-21T11:00:00+11:00 "
            "by household rule 2 to https://garden:8084/tasks/next?return=abc",
            {"action": "redirect", "status": 302, "location": "https://garden:8084/tasks/next?return=abc"},
        ),
        (
            "https://news.example/",
            "decision allow GET https://news.example/ (news) for kids at 2026-10-21T11:00:00+11:00 by household rule 3",
            ALLOW,
        ),
        (
            "https://elsewhere.example/",
            "decision deny GET https://elsewhere.example/ (default) for kids at 2026-10-21T11:00:00+11:00 by no rule",
            {"action": "deny", "status": 403, "message": NO_RULE},
        ),
    ],
)
def test_the_decision_line_says_what_was_decided_and_where_a_redirect_sends_the_browser(
    tmp_path, monkeypatch, capsys, url, line, decision
):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    policy = tmp_path / "policy.yaml"
    policy.write_text(DECISION_LINE_POLICY, encoding="utf-8")
    monkeypatch.setenv("POLICY_FILE", str(policy))
    monkeypatch.setenv("POLICY_DB", str(tmp_path / "policy.sqlite3"))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    app = create_app()
    capsys.readouterr()
    status, body = _post_decision(
        app,
        {"client_ip": "192.0.2.40", "method": "GET", "url": url, "occurred_at": "2026-10-21T00:00:00+00:00"},
    )
    assert status == 200
    assert json.loads(body) == decision
    assert capsys.readouterr().out.splitlines() == [line]
    logged = json.loads((tmp_path / "decisions.jsonl").read_text(encoding="utf-8"))
    assert logged["decision"] == decision


@pytest.mark.parametrize(
    "document",
    [
        [],
        {"method": "GET", "url": "http://x/"},
        {"client_ip": "younger-child.lan", "method": "GET", "url": "http://x/"},
        {"client_ip": "192.0.2.40", "method": "", "url": "http://x/"},
        {"client_ip": "192.0.2.40", "method": "GET"},
        {"client_ip": "192.0.2.40", "method": "GET", "url": "http://x/", "occurred_at": "yesterday"},
        {"client_ip": "192.0.2.40", "method": "GET", "url": "http://x/", "occurred_at": 12},
        {"client_ip": "192.0.2.40", "method": "GET", "url": "http://x/", "flow_id": ""},
    ],
)
def test_a_malformed_decision_request_is_refused_and_logged_without_a_decision(tmp_path, monkeypatch, document):
    pytest.importorskip("fastapi")
    from policy.app import create_app

    policy = tmp_path / "policy.yaml"
    policy.write_text(OPEN_POLICY, encoding="utf-8")
    monkeypatch.setenv("POLICY_FILE", str(policy))
    monkeypatch.setenv("POLICY_DB", str(tmp_path / "policy.sqlite3"))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    status, _body = _post_decision(create_app(), document)
    assert status == 400
    logged = json.loads((tmp_path / "decisions.jsonl").read_text(encoding="utf-8"))
    assert logged == {"request": document, "decision": None}


@pytest.mark.parametrize("name", ["policy.json", "policy.conf", "policy"])
def test_a_policy_file_that_is_not_yaml_stops_both_services_and_is_named(tmp_path, monkeypatch, name):
    pytest.importorskip("fastapi")
    from policy import observations
    from policy.app import create_app

    policy = tmp_path / name
    policy.write_text(OPEN_POLICY, encoding="utf-8")
    monkeypatch.setenv("POLICY_FILE", str(policy))
    monkeypatch.setenv("POLICY_DB", str(tmp_path / "policy.sqlite3"))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    with pytest.raises(ConfigError, match=f"{name}: the policy must be YAML"):
        create_app()
    with pytest.raises(ConfigError, match=f"{name}: the policy must be YAML"):
        observations._load_policy(policy)
    missing = tmp_path / "missing.json"
    monkeypatch.setenv("POLICY_FILE", str(missing))
    with pytest.raises(ConfigError, match="missing.json: the policy must be YAML"):
        create_app()
    with pytest.raises(ConfigError, match="missing.json: the policy must be YAML"):
        observations._load_policy(missing)
    assert not (tmp_path / "policy.sqlite3").exists()


@pytest.mark.parametrize("name", ["policy.yaml", "policy.YML"])
def test_a_yaml_policy_file_loads_in_both_services(tmp_path, monkeypatch, name):
    pytest.importorskip("fastapi")
    from policy import observations
    from policy.app import create_app

    policy = tmp_path / name
    policy.write_text(OPEN_POLICY, encoding="utf-8")
    monkeypatch.setenv("POLICY_FILE", str(policy))
    monkeypatch.setenv("POLICY_DB", str(tmp_path / "policy.sqlite3"))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    status, body = _post_decision(
        create_app(),
        {"client_ip": "192.0.2.40", "method": "GET", "url": "https://example.org/"},
    )
    assert (status, json.loads(body)) == (200, ALLOW)
    assert observations._load_policy(policy).entry == "entry"


@pytest.mark.parametrize(
    ("pattern", "url"),
    [
        ("https://classroom.google.com/*", "https://classroom.google.com/u/0/h"),
        ("classroom.google.com", "https://classroom.google.com/u/0/h"),
        ("*.youtube.com", "https://www.youtube.com/watch?v=abc#t=10"),
        ("youtu.be", "https://youtu.be/abc"),
        ("*.youtube.com", "https://WWW.YouTube.COM/watch"),
        ("*.YOUTUBE.com", "https://www.youtube.com/watch"),
        ("HTTPS://Classroom.Google.com/*", "https://classroom.google.com/c/xyz"),
        ("https://*.google.com/*/edit", "https://docs.google.com/document/d/1/edit"),
        ("youtu.?e", "https://youtu.be/abc"),
        ("www.youtube.com", "https://www.youtube.com:8443/watch"),
        ("www.youtube.com", "https://www.youtube.com./watch"),
        ("https://www.youtube.com/watch?v=abc", "https://www.youtube.com/watch?v=abc#t=10"),
        ("https://www.youtube.com*", "https://www.youtube.com/a/b/c?d=e"),
        ("*://classroom.google.com/*", "http://classroom.google.com/x/y"),
    ],
)
def test_a_site_group_pattern_matches(pattern, url):
    assert matches(pattern, url)


@pytest.mark.parametrize(
    ("pattern", "url"),
    [
        ("*.googlevideo.com", "https://www.youtube.com/watch?v=abc"),
        ("*.youtube.com", "https://youtube.com/watch"),
        ("youtube.com", "https://www.youtube.com/watch"),
        ("youtube.com", "https://example.org/youtube.com"),
        ("https://www.youtube.com/watch?v=abc#t=10", "https://www.youtube.com/watch?v=abc#t=10"),
        ("*#t=10", "https://www.youtube.com/watch?v=abc#t=10"),
        ("https://classroom.google.com/*", "http://classroom.google.com/u/0/h"),
        ("youtu.?e", "https://youtu.bbe/abc"),
        ("classroom.google.com", "https://evil.test/?classroom.google.com"),
        ("example.org", "http://[bad/"),
    ],
)
def test_a_site_group_pattern_does_not_match(pattern, url):
    assert not matches(pattern, url)
