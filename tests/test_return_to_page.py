"""S015: back to the page he was sent away from once revision lets him in."""

import asyncio
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy.decisions import parse_request  # noqa: E402
from policy.engine import MemoryLedger  # noqa: E402
from policy.hierarchy import load  # noqa: E402
from policy.quiz_page import ending  # noqa: E402
from policy.returns import ReturnPages, is_page_load, way_back  # noqa: E402
from policy.tasks import AttemptStore  # noqa: E402

ZONE = ZoneInfo("America/Toronto")
YOUNGER = "192.0.2.40"
SIBLING = "192.0.2.41"
OLDER = "192.0.2.50"
VIDEO = "https://www.youtube.com/watch?v=abc123"
OTHER_VIDEO = "https://www.youtube.com/watch?v=def456"
PLAIN = "http://www.youtube.com/some/path?x=1"
EVENING = datetime(2026, 11, 2, 18, 0, tzinfo=ZONE)
SUMS = {
    "operation": "addition",
    "max_timeout": "10s",
    "min_timeout": "4s",
    "correct_answers_required": 1,
    "first": [{"value": 6, "weight": 1}],
    "operands": [{"value": 7, "weight": 1}],
}


def _house(*, required: int = 1, timed: bool = False) -> str:
    """Return the test policy. Only ``timed`` closes YouTube outside the evening, for tests that set the clock."""
    window = (
        """\
    - condition: time_window
      window: evening
      when_false: { action: deny, message: "YouTube is closed." }
"""
        if timed
        else ""
    )
    return f"""\
entry: gate
timezone: America/Toronto
hostname: tasks.example
port: 443
client_groups:
  younger:
    addresses: ["{YOUNGER}", "{SIBLING}"]
  older:
    addresses: ["{OLDER}"]
site_groups:
  entertainment:
    priority: 10
    patterns: [www.youtube.com]
  elsewhere:
    priority: 20
    patterns: [elsewhere.example]
  closed:
    priority: 30
    patterns: [closed.example]
time_windows:
  evening:
    periods:
      - start: "15:00"
        end: "21:00"
quotas:
  entertainment:
    time: 30m
    ruleset: meter
tasks:
  sums:
    type: arithmetic
    group: younger
    pass_cooldown: 0
    body: {json.dumps(SUMS)}
  older_sums:
    type: arithmetic
    group: older
    pass_cooldown: 0
    body: {json.dumps(SUMS)}
rule_sets:
  meter:
    - condition: site_group
      group: entertainment
      when_true: {{ action: continue }}
      when_false: {{ action: deny, message: "Not entertainment." }}
  gate:
    - condition: site_group
      group: elsewhere
      when_true: {{ action: redirect, location: "https://school.example/start" }}
    - condition: site_group
      group: closed
      when_true: {{ action: deny, message: "Closed." }}
    - condition: tasks_required
      required: {required}
      when_false: {{ action: redirect, location: revision_task }}
    - condition: site_group
      group: entertainment
      when_true: {{ action: evaluate, ruleset: entertainment }}
    - condition: always
      when_true: {{ action: allow }}
  entertainment:
{window}    - condition: time_remaining
      quota: entertainment
      when_true: {{ action: allow }}
      when_false: {{ action: deny, message: "Time is up for today." }}
"""


# Which requests are page loads


@pytest.mark.parametrize(
    ("method", "dest", "accept", "expected"),
    [
        ("GET", "document", None, True),
        ("get", "Document", "*/*", True),
        ("GET", "image", "text/html", False),
        ("GET", "script", None, False),
        ("GET", "empty", "text/html", False),
        ("GET", "iframe", "text/html", False),
        ("GET", None, "text/html,application/xhtml+xml,*/*;q=0.8", True),
        ("GET", None, "TEXT/HTML;q=0.9", True),
        ("GET", None, "*/*", False),
        ("GET", None, "application/json", False),
        ("GET", None, None, False),
        ("POST", "document", "text/html", False),
        ("HEAD", "document", "text/html", False),
        ("PUT", None, "text/html", False),
    ],
)
def test_only_a_get_that_opens_a_page_is_a_page_load(method, dest, accept, expected):
    assert is_page_load(method, dest, accept) is expected


def test_the_decision_request_carries_the_page_headers_when_the_proxy_sends_them():
    sent = {"client_ip": YOUNGER, "method": "GET", "url": VIDEO}
    plain = parse_request(sent)
    assert (plain.sec_fetch_dest, plain.accept) == (None, None)
    full = parse_request({**sent, "sec_fetch_dest": "document", "accept": "text/html"})
    assert (full.sec_fetch_dest, full.accept) == ("document", "text/html")
    with pytest.raises(ValueError, match="sec_fetch_dest"):
        parse_request({**sent, "sec_fetch_dest": 3})
    with pytest.raises(ValueError, match="accept"):
        parse_request({**sent, "accept": ["text/html"]})


# Remembering and recalling, on a clock the test sets


def _pages() -> ReturnPages:
    return ReturnPages(sqlite3.connect(":memory:"))


def test_a_page_remembered_before_the_household_day_ends_is_not_used_after_it(tmp_path):
    pages = _pages()
    pages.remember(YOUNGER, VIDEO, datetime(2026, 11, 2, 23, 50, tzinfo=ZONE))
    assert pages.recall(YOUNGER, datetime(2026, 11, 2, 23, 59, tzinfo=ZONE)) == VIDEO
    assert pages.recall(YOUNGER, datetime(2026, 11, 3, 0, 1, tzinfo=ZONE)) is None
    policy = load(_write(tmp_path, _house()))
    ledger = MemoryLedger()
    ledger.set_successes("younger", datetime(2026, 11, 3).date(), 1)
    assert way_back(policy, pages, ledger, YOUNGER, datetime(2026, 11, 3, 18, 0, tzinfo=ZONE)) is None


def test_each_address_keeps_only_its_own_last_page_and_a_new_address_starts_empty():
    pages = _pages()
    pages.remember(YOUNGER, VIDEO, EVENING)
    pages.remember(YOUNGER, OTHER_VIDEO, EVENING)
    pages.remember("::ffff:" + SIBLING, PLAIN, EVENING)
    assert pages.recall(YOUNGER, EVENING) == OTHER_VIDEO
    assert pages.recall(SIBLING, EVENING) == PLAIN
    assert pages.recall("192.0.2.42", EVENING) is None
    pages.forget(YOUNGER, VIDEO)
    assert pages.recall(YOUNGER, EVENING) == OTHER_VIDEO
    pages.forget(YOUNGER, OTHER_VIDEO)
    assert pages.recall(YOUNGER, EVENING) is None


def test_the_way_back_is_the_decision_the_proxy_would_make_now(tmp_path):
    policy = load(_write(tmp_path, _house(timed=True)))
    pages = _pages()
    pages.remember(YOUNGER, VIDEO, EVENING)
    ledger = MemoryLedger()
    assert way_back(policy, pages, ledger, YOUNGER, EVENING) is None
    ledger.set_successes("younger", EVENING.date(), 1)
    assert way_back(policy, pages, ledger, YOUNGER, EVENING) == VIDEO
    late = EVENING.replace(hour=21, minute=30)
    assert way_back(policy, pages, ledger, YOUNGER, late) is None
    ledger.set_ended_seconds("younger", "entertainment", EVENING.date(), 30 * 60)
    assert way_back(policy, pages, ledger, YOUNGER, EVENING) is None
    assert pages.recall(YOUNGER, EVENING) == VIDEO


def test_only_a_pass_asks_for_the_way_back(tmp_path):
    policy = load(_write(tmp_path, _house()))
    asked = []

    def back():
        asked.append(True)
        return VIDEO

    with AttemptStore(":memory:") as store:
        assert ending(policy, store, "younger", EVENING, "pass", back)["back"] == VIDEO
        assert ending(policy, store, "younger", EVENING, "failure", back)["back"] is None
        assert ending(policy, store, "younger", EVENING, "abandoned", back)["back"] is None
        assert ending(policy, store, "younger", EVENING, "pass", None)["back"] is None
    assert len(asked) == 1


# Through the service: the proxy's decisions, then a pass on the task page


class Service:
    """The policy service as the proxy and the child's browser reach it."""

    def __init__(self, directory: Path, monkeypatch, *, required: int = 1):
        from policy.app import create_app

        self.directory = directory
        self.policy_file = _write(directory, _house(required=required))
        monkeypatch.setenv("POLICY_FILE", str(self.policy_file))
        monkeypatch.setenv("POLICY_DB", str(directory / "policy.sqlite3"))
        monkeypatch.setenv("DECISION_LOG", str(directory / "decisions.jsonl"))
        monkeypatch.setenv("DECISION_FILE", str(directory / "decision.json"))
        monkeypatch.delenv("DECISION_STUB", raising=False)
        self._create = create_app
        self.app = create_app()

    def restart(self):
        self.app = self._create()

    def decide(self, url, *, client=YOUNGER, method="GET", dest="document", accept=None) -> dict:
        document = {"client_ip": client, "method": method, "url": url}
        if dest is not None:
            document["sec_fetch_dest"] = dest
        if accept is not None:
            document["accept"] = accept
        status, body = _call(self.app, "POST", "/v1/decisions", body=json.dumps(document).encode())
        assert status == 200, body
        return json.loads(body)

    def pass_task(self, *, client=YOUNGER, task="sums") -> dict:
        """Open the task in the browser and answer its one question."""
        path = f"/tasks/{task}"
        status, page = _call(self.app, "GET", path, client=client)
        assert status == 200, page
        for action in ("visit", "question"):
            status, body = _call(self.app, "POST", path, query=f"do={action}".encode(), client=client)
            assert status == 200, body
        question = json.loads(body)
        answer = json.dumps({"id": question["id"], "answer": "13", "expired": False}).encode()
        status, body = _call(self.app, "POST", path, query=b"do=answer", body=answer, client=client)
        assert status == 200, body
        result = json.loads(body)
        assert result["finished"] is True
        return result


@pytest.fixture
def service(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    return Service(tmp_path, monkeypatch)


def test_a_pass_sends_him_back_to_the_page_that_sent_him_to_revision(service):
    redirect = service.decide(VIDEO)
    assert redirect["action"] == "redirect"
    assert redirect["location"] == "https://tasks.example/tasks/sums"
    result = service.pass_task()
    assert result["back"] == VIDEO
    assert result["next"] == "https://tasks.example/tasks/next"


def test_the_last_blocked_page_load_replaces_the_one_before(service):
    service.decide(VIDEO)
    service.decide(OTHER_VIDEO)
    assert service.pass_task()["back"] == OTHER_VIDEO


def test_a_plain_http_page_with_an_html_accept_header_is_remembered_in_full(service):
    service.decide(PLAIN, dest=None, accept="text/html")
    assert service.pass_task()["back"] == PLAIN


@pytest.mark.parametrize(
    "request_fields",
    [
        {"method": "POST", "dest": None, "accept": "text/html"},
        {"method": "HEAD", "dest": "document"},
        {"dest": "image"},
        {"dest": "empty"},
        {"dest": None, "accept": "*/*"},
        {"dest": None},
    ],
)
def test_a_fetch_or_another_method_does_not_replace_the_page(service, request_fields):
    service.decide(VIDEO)
    blocked = service.decide("https://www.youtube.com/thumb.jpg", **request_fields)
    assert blocked["action"] == "redirect"
    assert service.pass_task()["back"] == VIDEO


def test_a_deny_or_a_redirect_written_in_the_policy_is_not_remembered(service):
    assert service.decide("https://elsewhere.example/page")["location"] == "https://school.example/start"
    assert service.decide("https://closed.example/page")["action"] == "deny"
    assert service.pass_task()["back"] is None


def test_a_deny_or_a_redirect_written_in_the_policy_keeps_the_earlier_page(service):
    service.decide(VIDEO)
    service.decide("https://elsewhere.example/page")
    service.decide("https://closed.example/page")
    assert service.pass_task()["back"] == VIDEO


def test_the_task_pages_themselves_are_never_remembered(service):
    service.decide(VIDEO)
    assert service.decide("https://tasks.example/tasks/next")["action"] == "redirect"
    assert service.decide("https://tasks.example/tasks/older_sums")["action"] == "redirect"
    assert service.pass_task()["back"] == VIDEO


def test_opening_the_task_picker_directly_is_not_remembered(service):
    service.decide("https://tasks.example/tasks/next")
    assert service.pass_task()["back"] is None


def test_without_a_remembered_page_well_done_is_unchanged(service):
    result = service.pass_task()
    assert result["back"] is None
    assert result["next"] == "https://tasks.example/tasks/next"


def test_an_allow_for_that_exact_url_forgets_it(service):
    service.decide(VIDEO)
    assert service.pass_task()["back"] == VIDEO
    assert service.decide(OTHER_VIDEO)["action"] == "allow"
    assert service.pass_task()["back"] == VIDEO
    assert service.decide(VIDEO)["action"] == "allow"
    assert service.pass_task()["back"] is None


def test_a_page_he_opens_himself_once_it_is_allowed_is_forgotten_too(service):
    service.decide(VIDEO)
    service.pass_task()
    assert service.decide(VIDEO, dest=None)["action"] == "allow"
    assert service.pass_task()["back"] is None


def test_two_computers_in_one_group_each_get_their_own_page_back(service):
    service.decide(VIDEO, client=YOUNGER)
    service.decide(OTHER_VIDEO, client=SIBLING)
    assert service.pass_task(client=YOUNGER)["back"] == VIDEO
    assert service.pass_task(client=SIBLING)["back"] == OTHER_VIDEO


def test_a_page_blocked_in_one_client_group_is_never_opened_in_another(service):
    service.decide(VIDEO, client=OLDER)
    assert service.pass_task(client=YOUNGER)["back"] is None
    assert service.pass_task(client=OLDER, task="older_sums")["back"] == VIDEO


def test_the_remembered_page_survives_a_restart_of_the_service(service):
    service.decide(VIDEO)
    service.restart()
    assert service.pass_task()["back"] == VIDEO


def test_a_pass_that_does_not_reach_tasks_required_keeps_him_on_revision(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    service = Service(tmp_path, monkeypatch, required=2)
    service.decide(VIDEO)
    first = service.pass_task()
    assert first["back"] is None
    assert first["next"] == "https://tasks.example/tasks/next"
    assert service.pass_task()["back"] == VIDEO


# Helpers


def _write(directory: Path, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "policy.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _call(app, method, path, *, query=b"", body=b"", client=YOUNGER):
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

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query,
        "headers": [(b"x-daywarden-client", client.encode()), (b"content-type", b"application/json")],
        "client": ("172.17.0.2", 12345),
        "server": ("127.0.0.1", 80),
        "root_path": "",
    }
    asyncio.run(app(scope, receive, send))
    start = next(item for item in messages if item["type"] == "http.response.start")
    payload = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
    return start["status"], payload.decode()
