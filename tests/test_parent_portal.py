"""S007.4: the parent portal shell, its data addresses, and the old parent addresses."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from asgi import call, session_cookie  # noqa: E402
from policy.accounts import Accounts  # noqa: E402
from policy.portal import safe_next  # noqa: E402
from policy.store import PolicyStore  # noqa: E402

PASSWORD = "s3cret-pass"
INDEX = '<!DOCTYPE html><html><head><title>Daywarden</title></head><body><div id="root"></div></body></html>'
HOUSE = """\
timezone: Australia/Sydney
entry: entry
client_groups:
  younger:
    addresses: ["192.0.2.40"]
rule_sets:
  entry:
    - condition: always
      when_true: { action: allow }
"""


@pytest.mark.parametrize(
    ("asked", "opened"),
    [
        ("/parent/attempts?client=younger", "/parent/attempts?client=younger"),
        ("/parent/attempts/42", "/parent/attempts/42"),
        ("/parent/usage?view=quota&quota=youtube", "/parent/usage?view=quota&quota=youtube"),
        ("/parent/nothing-here", "/parent/nothing-here"),
        ("/parent/", "/parent/"),
        ("/parent", "/parent/"),
        ("", "/parent/"),
        (None, "/parent/"),
        (42, "/parent/"),
        ("https://example.com/", "/parent/"),
        ("//example.com/parent/attempts", "/parent/"),
        ("/\\example.com", "/parent/"),
        ("https://garden/parent/attempts", "/parent/"),
        ("javascript:alert(1)", "/parent/"),
        ("/parent/api/attempts", "/parent/"),
        ("/parent/api", "/parent/"),
        ("/parent/api/attempts?client=younger", "/parent/"),
        ("/parent/%61pi/attempts", "/parent/"),
        ("/parent/assets/index-abc123.js", "/parent/"),
        ("/parent/favicon.png", "/parent/"),
        ("/parent/logo.webp", "/parent/"),
        ("/parent/login", "/parent/"),
        ("/parent/login?next=/parent/usage", "/parent/"),
        ("/parent/../usage", "/parent/"),
        ("/parent/attempts/%2e%2e/api/session", "/parent/"),
        ("/parent//api/session", "/parent/"),
        ("/usage", "/parent/"),
        ("/parent/attempts\n", "/parent/"),
    ],
)
def test_sign_in_returns_only_to_a_portal_page(asked, opened):
    assert safe_next(asked) == opened


@pytest.fixture
def portal(tmp_path, monkeypatch):
    """The decisions app with an account and a stand-in portal build."""
    pytest.importorskip("fastapi")
    from policy.app import create_app

    built = tmp_path / "dist"
    (built / "assets").mkdir(parents=True)
    (built / "index.html").write_text(INDEX, encoding="utf-8")
    (built / "assets" / "index-abc123.js").write_text("console.log('portal')", encoding="utf-8")
    (built / "favicon.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    policy = tmp_path / "policy.yaml"
    policy.write_text(HOUSE, encoding="utf-8")
    database = tmp_path / "policy.sqlite3"
    monkeypatch.setenv("POLICY_FILE", str(policy))
    monkeypatch.setenv("POLICY_DB", str(database))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    monkeypatch.setenv("PORTAL_DIR", str(built))
    with PolicyStore(database) as store:
        Accounts(store.connection).set_password("ada", PASSWORD)
    app = create_app()
    app.state.database = database
    return app


def _sign_in(app, **body):
    return call(app, "POST", "/parent/api/login", json_body={"username": "ada", "password": PASSWORD, **body})


def test_sign_in_answers_with_the_checked_return_address(portal):
    for asked, opened in (
        ("/parent/attempts?client=younger", "/parent/attempts?client=younger"),
        ("/parent/api/attempts", "/parent/"),
        ("https://example.com/", "/parent/"),
        (None, "/parent/"),
    ):
        status, body, _headers = _sign_in(portal, next=asked)
        assert status == 200
        assert json.loads(body) == {"next": opened}


def test_sign_out_ends_the_session_on_the_service(portal):
    _status, _body, headers = _sign_in(portal)
    cookie = session_cookie(headers)
    _status, _body, other = _sign_in(portal)
    other_cookie = session_cookie(other)
    assert call(portal, "GET", "/parent/api/session", cookie=cookie)[0] == 200

    status, _body, _headers = call(portal, "POST", "/parent/api/logout", body=b"", content_type="text/plain", cookie=cookie)
    assert status == 415
    assert call(portal, "GET", "/parent/api/session", cookie=cookie)[0] == 200

    status, body, headers = call(portal, "POST", "/parent/api/logout", json_body={}, cookie=cookie)
    assert (status, json.loads(body)) == (200, {"signed_out": True})
    cleared = headers["set-cookie"][0]
    assert cleared.startswith("parent_session=;")
    assert "Max-Age=0" in cleared
    assert call(portal, "GET", "/parent/api/session", cookie=cookie)[0] == 401
    assert call(portal, "GET", "/parent/api/attempts", query="client=younger", cookie=cookie)[0] == 401
    assert call(portal, "GET", "/parent/api/session", cookie=other_cookie)[0] == 200
    with sqlite3.connect(portal.state.database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM parent_sessions").fetchone()[0] == 1

    status, _body, _headers = call(portal, "POST", "/parent/api/logout", json_body={})
    assert status == 200


def test_every_portal_page_address_returns_the_shell_without_a_session(portal):
    for path in ("/parent/", "/parent/attempts", "/parent/attempts/42", "/parent/usage", "/parent/login", "/parent/nothing-here"):
        status, body, headers = call(portal, "GET", path, query="client=younger")
        assert status == 200, path
        assert body == INDEX
        assert headers["cache-control"] == ["no-store"]
        assert headers["content-type"][0].startswith("text/html")


def test_built_files_are_served_and_hashed_assets_may_be_cached(portal):
    status, body, headers = call(portal, "GET", "/parent/assets/index-abc123.js")
    assert status == 200
    assert body == "console.log('portal')"
    assert "immutable" in headers["cache-control"][0]
    status, _body, headers = call(portal, "GET", "/parent/favicon.png")
    assert status == 200
    assert headers["content-type"] == ["image/png"]
    status, body, _headers = call(portal, "GET", "/parent/assets/missing.js")
    assert status == 404
    assert body != INDEX
    status, body, _headers = call(portal, "GET", "/parent/../policy.yaml")
    assert (status, body) == (200, INDEX)


def test_an_unknown_data_address_is_json_not_the_portal_page(portal):
    cookie = session_cookie(_sign_in(portal)[2])
    for method in ("GET", "POST"):
        status, body, headers = call(portal, method, "/parent/api/nothing-here", cookie=cookie)
        assert status == 404
        assert json.loads(body) == {"error": "Not found."}
        assert headers["content-type"] == ["application/json"]
    status, body, _headers = call(portal, "GET", "/parent/api/attempts/999999", cookie=cookie)
    assert (status, json.loads(body)) == (404, {"error": "That attempt is not stored."})
    status, body, _headers = call(portal, "GET", "/parent/api/attempts/999999")
    assert status == 401
    assert "stored" not in body


def test_the_old_addresses_and_the_root_redirect_to_the_portal(portal):
    for path, query, location in (
        ("/usage", "view=client&client=younger", "/parent/usage/minutes"),
        ("/usage", "", "/parent/usage/minutes"),
        ("/attempts", "client=younger", "/parent/attempts?client=younger"),
        ("/attempts/7", "", "/parent/attempts/7"),
        ("/", "", "/parent/"),
        ("/parent", "", "/parent/"),
    ):
        status, body, headers = call(portal, "GET", path, query=query)
        assert 300 <= status < 400, path
        assert headers["location"] == [location]
        assert "younger" not in body


def test_the_old_parent_check_post_records_nothing(portal):
    cookie = session_cookie(_sign_in(portal)[2])
    for path in ("/attempts/parent-check", "/usage", "/attempts"):
        status, _body, headers = call(
            portal,
            "POST",
            path,
            body=b"client=younger",
            content_type="application/x-www-form-urlencoded",
            cookie=cookie,
        )
        assert status == 405, path
        assert "set-cookie" not in headers
    with sqlite3.connect(portal.state.database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM parent_checks").fetchone()[0] == 0


def test_a_missing_build_says_so_instead_of_a_blank_page(portal, tmp_path):
    (tmp_path / "dist" / "index.html").unlink()
    status, body, _headers = call(portal, "GET", "/parent/attempts")
    assert status == 503
    assert "not built" in body
