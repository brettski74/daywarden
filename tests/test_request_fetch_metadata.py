"""S030.4: Fetch Metadata on request rows, the Fetch levels, and hiding redirect hops."""

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
from policy.usage import UsageStore, is_document  # noqa: E402
from test_usage_requests import AT, HOUSE, YOUNGER, _list, _load  # noqa: E402

SYDNEY = ZoneInfo("Australia/Sydney")
PAGE = "https://www.example.com/"
IMAGE = "https://www.example.com/a.png"


def _record(usage: UsageStore, flow_id: str, url: str = PAGE, *, at: datetime = AT, **kwargs) -> None:
    usage.record_request(
        flow_id,
        started_at=at,
        client_ip=YOUNGER,
        client_group="younger",
        site_group="youtube",
        method=kwargs.pop("method", "GET"),
        url=url,
        outcome=kwargs.pop("outcome", "allowed"),
        status=kwargs.pop("status", None),
        **kwargs,
    )


def _ids(data: dict) -> set[str]:
    return {row["id"] for row in data["rows"]}


def _typed(usage, flow_id, url=PAGE, **kwargs):
    """A page typed in Firefox's address bar."""
    _record(
        usage,
        flow_id,
        url,
        sec_fetch_dest="document",
        sec_fetch_mode="navigate",
        sec_fetch_site="none",
        sec_fetch_user="?1",
        accept="text/html,application/xhtml+xml",
        **kwargs,
    )


def test_the_addon_headers_are_optional_strings():
    base = {"client_ip": YOUNGER, "method": "GET", "url": PAGE}
    parsed = parse_request(
        {
            **base,
            "sec_fetch_dest": "image",
            "sec_fetch_mode": "no-cors",
            "sec_fetch_site": "cross-site",
            "sec_fetch_user": "?1",
            "sec_purpose": "prefetch",
        }
    )
    assert (parsed.sec_fetch_dest, parsed.sec_fetch_mode, parsed.sec_fetch_site) == ("image", "no-cors", "cross-site")
    assert (parsed.sec_fetch_user, parsed.sec_purpose) == ("?1", "prefetch")
    bare = parse_request(base)
    assert bare.sec_fetch_mode is None and bare.sec_purpose is None
    with pytest.raises(ValueError, match="sec_fetch_site"):
        parse_request({**base, "sec_fetch_site": 3})


@pytest.mark.parametrize(
    ("method", "dest", "purpose", "accept", "expected"),
    [
        ("GET", "document", None, None, True),
        ("POST", "document", None, None, True),
        ("GET", "Document", None, None, True),
        ("GET", "document", "prefetch", None, False),
        ("GET", "document", "prefetch;prerender", None, False),
        ("GET", "document", "prefetch;anonymous-client-ip", None, False),
        ("GET", "image", None, "text/html", False),
        ("GET", "iframe", None, "text/html", False),
        ("GET", "empty", None, None, False),
        ("GET", None, None, "text/html,application/xhtml+xml;q=0.9", True),
        ("GET", None, None, "*/*", False),
        ("GET", None, None, None, False),
        ("POST", None, None, "text/html", False),
    ],
)
def test_the_documents_rule(method, dest, purpose, accept, expected):
    assert is_document(method, dest, purpose, accept) is expected


def test_the_five_headers_are_listed_as_sent_and_blank_when_not_sent(tmp_path):
    policy = _load(tmp_path)
    usage = UsageStore()
    _record(usage, "img", IMAGE, sec_fetch_dest="image", sec_fetch_mode="no-cors", sec_fetch_site="cross-site")
    _record(usage, "plain", "http://www.example.com/")
    rows = {row["id"]: row for row in _list(policy, usage, "range=past-week")["rows"]}
    image = rows["img"]
    assert (image["dest"], image["mode"], image["fetch_site"], image["user"], image["purpose"]) == (
        "image",
        "no-cors",
        "cross-site",
        "",
        "",
    )
    plain = rows["plain"]
    assert [plain[key] for key in ("dest", "mode", "fetch_site", "user", "purpose")] == [""] * 5


def test_the_levels_choose_documents_and_user_activated_documents(tmp_path):
    policy = _load(tmp_path)
    usage = UsageStore()
    _typed(usage, "typed")
    _record(usage, "img", IMAGE, sec_fetch_dest="image", sec_fetch_mode="no-cors", sec_fetch_site="same-origin")
    _record(usage, "script", "https://cdn.example/app.js", sec_fetch_dest="script")
    for dest in ("iframe", "empty", "style", "font"):
        _record(usage, dest, f"https://ads.example/{dest}", sec_fetch_dest=dest)
    # A page a script moved to on its own: a document with no Sec-Fetch-User.
    _record(usage, "scripted", "https://www.example.com/next", sec_fetch_dest="document", sec_fetch_mode="navigate")
    _record(usage, "prefetch", "https://www.example.com/later", sec_fetch_dest="document", sec_purpose="prefetch;prerender")
    _record(usage, "http-page", "http://allowed.example/", accept="text/html")
    _record(usage, "http-any", "http://allowed.example/x", accept="*/*")

    everything = _list(policy, usage, "range=past-week")
    assert everything["fetch"] == "all"
    assert everything["total"] == 11
    documents = _list(policy, usage, "range=past-week&fetch=documents")
    assert _ids(documents) == {"typed", "scripted", "http-page"}
    user = _list(policy, usage, "range=past-week&fetch=user")
    assert _ids(user) == {"typed"}


def test_refused_requests_follow_the_same_rule(tmp_path):
    policy = _load(tmp_path)
    usage = UsageStore()
    _typed(usage, "denied-page", "https://blocked.example/", outcome="denied", status=403)
    _typed(usage, "redirected-page", "https://elsewhere.example/", outcome="redirected", status=302)
    _record(usage, "denied-img", "https://blocked.example/a.png", outcome="denied", status=403, sec_fetch_dest="image")
    documents = _list(policy, usage, "range=past-week&fetch=documents")
    assert _ids(documents) == {"denied-page", "redirected-page"}


def test_redirect_hops_are_hidden_unless_shown(tmp_path):
    policy = _load(tmp_path)
    usage = UsageStore()
    _typed(usage, "hop", "https://www.google.com/url?q=x", status=302)
    _typed(usage, "landed", "https://news.example/story", status=200)
    _typed(usage, "running", "https://news.example/slow")
    _typed(usage, "policy", "https://blocked.example/", outcome="redirected", status=302)
    hidden = _list(policy, usage, "range=past-week&fetch=documents")
    assert hidden["hide_hops"] is True
    assert _ids(hidden) == {"landed", "running", "policy"}
    shown = _list(policy, usage, "range=past-week&fetch=user&hops=show")
    assert shown["hide_hops"] is False
    assert _ids(shown) == {"hop", "landed", "running", "policy"}
    # Every request lists hops whatever the address says.
    everything = _list(policy, usage, "range=past-week&fetch=all")
    assert everything["hide_hops"] is False
    assert "hop" in _ids(everything)


def test_an_unknown_level_lists_every_request_and_says_so(tmp_path):
    policy = _load(tmp_path)
    usage = UsageStore()
    _record(usage, "img", IMAGE, sec_fetch_dest="image")
    data = _list(policy, usage, "range=past-week&fetch=pages")
    assert data["fetch"] == "all"
    assert data["total"] == 1
    assert "pages is not a Fetch level, so every request is listed." in data["notes"]


def test_the_level_narrows_a_host_drill_down(tmp_path):
    policy = _load(tmp_path)
    usage = UsageStore()
    _typed(usage, "page")
    _record(usage, "img", IMAGE, sec_fetch_dest="image")
    data = _list(policy, usage, "by=client&range=past-week&line=younger&host=www.example.com&exact=1&fetch=documents")
    assert _ids(data) == {"page"}


def test_the_new_columns_sort_with_blank_cells_first_ascending(tmp_path):
    policy = _load(tmp_path)
    usage = UsageStore()
    _record(usage, "blank", "http://www.example.com/")
    _record(usage, "script", "https://www.example.com/a.js", sec_fetch_dest="script")
    _typed(usage, "doc")
    _record(usage, "img", IMAGE, sec_fetch_dest="image")
    ascending = _list(policy, usage, "range=past-week&sort=dest&dir=asc")
    assert [row["id"] for row in ascending["rows"]] == ["blank", "doc", "img", "script"]
    descending = _list(policy, usage, "range=past-week&sort=dest&dir=desc")
    assert [row["id"] for row in descending["rows"]] == ["script", "img", "doc", "blank"]
    for key in ("mode", "fetch_site", "user", "purpose"):
        assert _list(policy, usage, f"range=past-week&sort={key}&dir=asc")["sort"] == key


def test_an_earlier_requests_table_gains_the_columns_on_start(tmp_path):
    database = tmp_path / "policy.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE requests (
            flow_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            client_ip TEXT NOT NULL,
            client_group TEXT NOT NULL,
            site_group TEXT NOT NULL,
            method TEXT NOT NULL,
            host TEXT NOT NULL,
            path TEXT NOT NULL,
            query TEXT NOT NULL,
            url TEXT NOT NULL,
            status INTEGER,
            content_type TEXT,
            bytes_down INTEGER NOT NULL DEFAULT 0,
            bytes_up INTEGER NOT NULL DEFAULT 0,
            outcome TEXT NOT NULL
        );
        """
    )
    started = AT.isoformat(timespec="seconds")
    connection.execute(
        "INSERT INTO requests VALUES ('old', ?, ?, ?, 'younger', 'youtube', 'GET', 'www.example.com', "
        "'https://www.example.com/', '', 'https://www.example.com/', 200, 'text/html', 10, 0, 'allowed')",
        (started, started, YOUNGER),
    )
    connection.commit()
    connection.close()

    policy = _load(tmp_path)
    usage = UsageStore(database)
    # A second store on the same file, as the other service opens it, finds the columns already there.
    UsageStore(database).close()
    _typed(usage, "new")
    everything = _list(policy, usage, "range=past-week")
    rows = {row["id"]: row for row in everything["rows"]}
    assert [rows["old"][key] for key in ("dest", "mode", "fetch_site", "user", "purpose")] == [""] * 5
    assert rows["new"]["dest"] == "document"
    assert _ids(_list(policy, usage, "range=past-week&fetch=documents")) == {"new"}
    usage.close()


def test_decisions_store_the_headers_the_addon_sent(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from asgi import call
    from policy.app import create_app

    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(HOUSE, encoding="utf-8")
    database = tmp_path / "policy.sqlite3"
    monkeypatch.setenv("POLICY_FILE", str(policy_path))
    monkeypatch.setenv("POLICY_DB", str(database))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    UsageStore(database).close()
    app = create_app()
    when = datetime.now(SYDNEY).replace(tzinfo=None) - timedelta(minutes=1)
    for flow_id, extra in (
        (
            "typed",
            {
                "sec_fetch_dest": "document",
                "sec_fetch_mode": "navigate",
                "sec_fetch_site": "none",
                "sec_fetch_user": "?1",
                "accept": "text/html",
            },
        ),
        ("prefetch", {"sec_fetch_dest": "document", "sec_purpose": "prefetch;prerender"}),
        ("curl", {"accept": "*/*"}),
    ):
        status, body, _headers = call(
            app,
            "POST",
            "/v1/decisions",
            json_body={
                "client_ip": YOUNGER,
                "method": "GET",
                "url": PAGE,
                "occurred_at": when.replace(tzinfo=SYDNEY).isoformat(),
                "flow_id": flow_id,
                **extra,
            },
        )
        assert status == 200, body
        assert json.loads(body)["action"] == "allow"
    usage = UsageStore(database)
    now = datetime.now(SYDNEY).replace(tzinfo=None)
    rows = {row["id"]: row for row in _list(load_policy(policy_path), usage, "range=past-week", now=now)["rows"]}
    typed = rows["typed"]
    assert (typed["dest"], typed["mode"], typed["fetch_site"], typed["user"]) == ("document", "navigate", "none", "?1")
    assert rows["prefetch"]["purpose"] == "prefetch;prerender"
    assert _ids(_list(load_policy(policy_path), usage, "range=past-week&fetch=documents", now=now)) == {"typed"}
    usage.close()


def load_policy(path: Path):
    from policy.hierarchy import load

    return load(path)
