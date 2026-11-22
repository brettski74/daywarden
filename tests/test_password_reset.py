"""S044.2: the Account page's password change, and resetting a password by email, through the portal's data addresses."""

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from asgi import call, session_cookie  # noqa: E402
from policy import mail as mail_module  # noqa: E402
from policy.accounts import REVIEWER, Accounts  # noqa: E402
from policy.mail import MailError  # noqa: E402
from policy.store import PolicyStore  # noqa: E402
from test_mcp_server import PASSWORD, activity, at, connect, mcp, service  # noqa: E402,F401 - service is the fixture

NOW = datetime(2026, 11, 20, 4, 0, tzinfo=timezone.utc)
SENT = "If that account has an email address, a link to reset its password is on its way. It works for 60 minutes."
SAVED = {
    "message": "Try signing in with your new password. If it does not work, learn more",
    "link": "learn more",
    "help": "/parent/password-help#reset",
}
NOT_CHANGED = {"error": "Your password was not changed. Learn more", "link": "Learn more", "help": "/parent/password-help#account"}
RULES_OFF = {"min_length": None, "history": None, "strength": None, "lines": []}
EMAIL = {
    "SMTP_HOST": "smtp.example.net",
    "SMTP_USERNAME": "daywarden@example.net",
    "SMTP_PASSWORD": "hunter2-secret",
    "MAIL_FROM": "Daywarden <daywarden@example.net>",
}


class Outbox:
    """The transport the service is given: it keeps each email, or fails each one while ``failing``."""

    def __init__(self):
        self.sent = []
        self.failing = False

    def send(self, message):
        if self.failing:
            raise MailError("The mail server at smtp.example.net:465 refused the email: 554 no")
        self.sent.append(message)

    def to(self, address):
        return [message for message in self.sent if message["To"] == address]

    def subjects(self):
        return [message["Subject"] for message in self.sent]


@pytest.fixture
def outbox(monkeypatch):
    found = Outbox()
    monkeypatch.setattr(mail_module, "transport_for", lambda settings: found)
    return found


@pytest.fixture
def app(service, monkeypatch, outbox):
    """The service with email on, Ada (admin, ada@example.net), Bee (admin, no address), and Nana (reviewer, nana@example.net)."""
    for name, value in EMAIL.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("PARENT_RESET_LIFETIME", raising=False)
    with PolicyStore(service.state.database) as store:
        accounts = Accounts(store.connection)
        accounts.update("ada", email="ada@example.net")
        accounts.add("bee", "admin", password=PASSWORD)
        accounts.add("nana", REVIEWER, email="nana@example.net", password=PASSWORD)
    made = service.state.remake()
    at(made, NOW)
    return made


def sign_in(app, username="ada", password=PASSWORD):
    status, body, headers = call(app, "POST", "/parent/api/login", json_body={"username": username, "password": password})
    return session_cookie(headers) if status == 200 else None


def signed_in(app, cookie) -> bool:
    return call(app, "GET", "/parent/api/session", cookie=cookie)[0] == 200


def change(app, cookie, current=PASSWORD, password="new-pass-1", again=None, **extra):
    status, body, _headers = call(
        app,
        "POST",
        "/parent/api/account/password",
        cookie=cookie,
        json_body={"current": current, "password": password, "again": password if again is None else again, **extra},
    )
    return status, json.loads(body)


def forgot(app, username, host="garden:8084"):
    status, body, headers = call(app, "POST", "/parent/api/password-reset", json_body={"username": username}, headers={"host": host})
    return status, json.loads(body), headers


def save(app, token, password="reset-pass-1", again=None):
    status, body, headers = call(
        app,
        "POST",
        "/parent/api/password-reset/save",
        json_body={"token": token, "password": password, "again": password if again is None else again},
    )
    return status, json.loads(body), headers


def link_in(message) -> str:
    return re.search(r"https://\S+", message.get_content()).group(0)


def token_in(message) -> str:
    return link_in(message).split("#", 1)[1]


def requested(app, outbox, username="ada", **where) -> str:
    """Ask for a reset link and return its token."""
    before = len(outbox.sent)
    status, body, _headers = forgot(app, username, **where)
    assert (status, body) == (200, {"message": SENT})
    assert len(outbox.sent) == before + 1
    return token_in(outbox.sent[-1])


# The Account page


def test_the_account_page_shows_the_username_role_and_address(app):
    status, body, _headers = call(app, "GET", "/parent/api/account", cookie=sign_in(app))
    assert (status, json.loads(body)) == (200, {"username": "ada", "role": "admin", "email": "ada@example.net", "rules": RULES_OFF})
    status, body, _headers = call(app, "GET", "/parent/api/account", cookie=sign_in(app, "bee"))
    assert json.loads(body) == {"username": "bee", "role": "admin", "email": None, "rules": RULES_OFF}
    status, body, _headers = call(app, "GET", "/parent/api/account", cookie=sign_in(app, "nana"))
    assert (status, json.loads(body)["role"]) == (200, REVIEWER)
    assert call(app, "GET", "/parent/api/account")[0] == 401


@pytest.mark.parametrize(
    ("sent", "problem"),
    [
        ({"current": "wrong-pass"}, NOT_CHANGED),
        ({"current": "x" * 201}, NOT_CHANGED),
        ({"current": None}, NOT_CHANGED),
        ({"password": ""}, {"error": "The new password is empty. Nothing was changed."}),
        ({"password": "x" * 201}, {"error": "The new password is longer than 200 characters. Nothing was changed."}),
        ({"again": "new-pass-2"}, {"error": "The two new passwords differ. Nothing was changed."}),
    ],
)
def test_a_refused_change_says_why_and_changes_nothing(app, outbox, sent, problem):
    cookie = sign_in(app)
    other = sign_in(app)
    assert change(app, cookie, **sent) == (400, problem)
    assert signed_in(app, cookie) and signed_in(app, other)
    assert sign_in(app, "ada", PASSWORD) is not None
    assert outbox.sent == []


def test_repeated_wrong_current_passwords_end_nothing(app):
    cookie = sign_in(app)
    for _ in range(5):
        assert change(app, cookie, current="guess")[0] == 400
    assert signed_in(app, cookie)
    assert sign_in(app, "ada", PASSWORD) is not None


def test_a_change_keeps_this_tab_ends_the_others_and_the_mcp_connections_and_sends_a_notice(app, outbox):
    cookie = sign_in(app)
    laptop = sign_in(app)
    bee = sign_in(app, "bee")
    _client, tokens = connect(app, cookie)
    assert mcp(app, tokens["access_token"], "tools/list")[0] == 200
    assert change(app, cookie) == (200, {"message": "Your password was changed."})
    assert signed_in(app, cookie)
    assert not signed_in(app, laptop)
    assert signed_in(app, bee)
    assert mcp(app, tokens["access_token"], "tools/list")[0] == 401
    assert "the parent's password was changed" in json.dumps(activity(app, cookie)[0])
    assert sign_in(app, "ada", PASSWORD) is None
    assert sign_in(app, "ada", "new-pass-1") is not None
    (notice,) = outbox.sent
    assert notice["To"] == "ada@example.net"
    assert notice["Subject"] == "Your Daywarden password was changed"
    text = notice.get_content()
    assert "changed on the Account page at 3:00 pm on Friday 20 November 2026 (Australia/Sydney)" in text
    assert "https://" not in text


def test_a_reviewer_changes_only_their_own_password(app, outbox):
    cookie = sign_in(app, "nana")
    assert change(app, cookie, username="ada") == (200, {"message": "Your password was changed."})
    assert sign_in(app, "nana", "new-pass-1") is not None
    assert sign_in(app, "ada", PASSWORD) is not None
    assert [message["To"] for message in outbox.sent] == ["nana@example.net"]


def test_a_change_with_no_address_or_a_failing_server_still_changes(app, outbox, capsys):
    assert change(app, sign_in(app, "bee"))[0] == 200
    assert outbox.sent == []
    outbox.failing = True
    assert change(app, sign_in(app))[0] == 200
    assert sign_in(app, "ada", "new-pass-1") is not None
    assert "the password-changed email for ada was not sent: The mail server at smtp.example.net:465 refused" in capsys.readouterr().out


# Forgot password


def test_the_forgot_page_says_whether_resetting_by_email_is_on(app, service, monkeypatch):
    status, body, _headers = call(app, "GET", "/parent/api/password-reset")
    assert (status, json.loads(body)) == (200, {"email": True, "lifetime": "60 minutes", "rules": RULES_OFF})
    monkeypatch.delenv("SMTP_HOST")
    off = service.state.remake()
    status, body, _headers = call(off, "GET", "/parent/api/password-reset")
    assert (status, json.loads(body)) == (200, {"email": False, "lifetime": "60 minutes", "rules": RULES_OFF})
    status, body, _headers = forgot(off, "ada")
    assert (status, body) == (404, {"error": "Resetting a password by email is not set up. Ask whoever runs Daywarden."})


def test_send_link_gives_the_same_answer_for_every_username_and_mails_only_the_accounts_own_address(app, outbox, capsys):
    for username in ("zed", "bee", "ada", "ada", "", "x" * 300):
        status, body, _headers = forgot(app, username)
        assert (status, body) == (200, {"message": SENT})
    (sent,) = outbox.sent
    assert sent["To"] == "ada@example.net"
    assert sent["Subject"] == "Reset your Daywarden password"
    text = sent.get_content()
    assert "ada" in text and "4:00 pm on Friday 20 November 2026 (Australia/Sydney)" in text
    assert "ignore this email, and nothing changes" in text
    # The second request for ada fell in the cooldown, and the log says so without the address.
    log = capsys.readouterr().out
    assert "password reset for ada skipped: a link was sent less than 5 minutes ago" in log
    assert "ada@example.net" not in log


def test_a_failing_mail_server_gives_the_same_answer_and_is_logged(app, outbox, capsys):
    outbox.failing = True
    status, body, _headers = forgot(app, "ada")
    assert (status, body) == (200, {"message": SENT})
    assert "the reset email for ada was not sent: The mail server" in capsys.readouterr().out


@pytest.mark.parametrize("path", ["/parent/api/password-reset", "/parent/api/password-reset/save"])
def test_the_answer_is_sent_before_the_token_is_looked_up_or_any_email_is_written(app, outbox, monkeypatch, path):
    import asyncio

    events = []
    token = requested(app, outbox) if path.endswith("save") else None
    for name in ("request_reset", "reset_target"):
        original = getattr(Accounts, name)
        monkeypatch.setattr(Accounts, name, lambda self, *args, _original=original, _name=name: (events.append(_name), _original(self, *args))[1])
    outbox.send = lambda message, _send=outbox.send: (events.append("email"), _send(message))
    body = json.dumps({"username": "ada", "token": token, "password": "reset-pass-1", "again": "reset-pass-1"}).encode()
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "https",
        "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
        "headers": [(b"content-type", b"application/json"), (b"host", b"garden:8084")],
        "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 8443),
    }
    received = []

    async def receive():
        if received:
            await asyncio.Event().wait()
        received.append(True)
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        if message["type"] == "http.response.body" and not message.get("more_body"):
            events.append("answer")

    asyncio.run(app(scope, receive, send))
    assert events[0] == "answer"
    assert events[1] in ("request_reset", "reset_target")
    assert "email" in events


@pytest.mark.parametrize(
    ("host", "named"),
    [
        ("garden:8084", "https://garden:8084/parent/reset#"),
        ("LOCALHOST:8084", "https://localhost:8084/parent/reset#"),
        ("evil.example", "https://garden:8084/parent/reset#"),
        ("evil.example:8084", "https://garden:8084/parent/reset#"),
        ("", "https://garden:8084/parent/reset#"),
    ],
)
def test_the_link_names_the_host_asked_for_only_when_it_is_a_parent_name(app, outbox, host, named):
    forgot(app, "ada", host=host)
    link = link_in(outbox.sent[-1])
    assert link.startswith(named)
    assert re.fullmatch(r"[0-9a-f]{64}", link.split("#", 1)[1])


def test_the_link_lifetime_follows_the_setting(service, monkeypatch, outbox):
    for name, value in EMAIL.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PARENT_RESET_LIFETIME", "15m")
    with PolicyStore(service.state.database) as store:
        Accounts(store.connection).update("ada", email="ada@example.net")
    app = service.state.remake()
    at(app, NOW)
    assert forgot(app, "ada")[1] == {"message": SENT.replace("60 minutes", "15 minutes")}
    token = token_in(outbox.sent[-1])
    at(app, NOW + timedelta(minutes=15, seconds=1))
    save(app, token)
    assert sign_in(app, "ada", "reset-pass-1") is None


# Reset password


def test_a_valid_link_sets_the_password_once_and_signs_nobody_in(app, outbox):
    cookie = sign_in(app)
    _client, tokens = connect(app, cookie)
    token = requested(app, outbox)
    status, body, headers = save(app, token)
    assert (status, body) == (200, SAVED)
    assert "set-cookie" not in headers
    assert not signed_in(app, cookie)
    assert mcp(app, tokens["access_token"], "tools/list")[0] == 401
    assert sign_in(app, "ada", PASSWORD) is None
    assert sign_in(app, "ada", "reset-pass-1") is not None
    assert "the parent's password was reset" in json.dumps(activity(app, sign_in(app, "ada", "reset-pass-1"))[0])
    notice = outbox.sent[-1]
    assert notice["Subject"] == "Your Daywarden password was changed"
    assert "reset with a link sent by email" in notice.get_content()
    # The same link again changes nothing.
    assert save(app, token, "another-pass")[:2] == (200, SAVED)
    assert sign_in(app, "ada", "reset-pass-1") is not None
    assert sign_in(app, "ada", "another-pass") is None


@pytest.mark.parametrize("token", ["", "nope", "0" * 64, None, 12])
def test_a_link_that_was_never_sent_gives_the_same_answer_and_changes_nothing(app, outbox, token):
    cookie = sign_in(app)
    requested(app, outbox)
    assert save(app, token)[:2] == (200, SAVED)
    assert signed_in(app, cookie)
    assert sign_in(app, "ada", PASSWORD) is not None


@pytest.mark.parametrize(
    ("sent", "problem"),
    [
        ({"password": ""}, "The new password is empty."),
        ({"password": "x" * 201}, "The new password is longer than 200 characters."),
        ({"password": "reset-pass-1", "again": "reset-pass-2"}, "The two new passwords differ."),
    ],
)
def test_a_password_that_cannot_be_set_is_refused_whether_or_not_the_link_is_valid(app, outbox, sent, problem):
    token = requested(app, outbox)
    for link in (token, "0" * 64):
        status, body, _headers = save(app, link, **sent)
        assert (status, body) == (400, {"error": problem})
    # The valid link was not used up by the refusal.
    assert save(app, token)[1] == SAVED
    assert sign_in(app, "ada", "reset-pass-1") is not None


def test_a_link_stops_working_after_the_lifetime(app, outbox):
    token = requested(app, outbox)
    at(app, NOW + timedelta(minutes=60))
    other = requested(app, outbox, "nana")
    at(app, NOW + timedelta(minutes=60, seconds=1))
    save(app, token)
    assert sign_in(app, "ada", PASSWORD) is not None
    assert save(app, other)[1] == SAVED
    assert sign_in(app, "nana", "reset-pass-1") is not None


def test_a_second_request_within_5_minutes_sends_nothing_and_a_later_one_replaces_the_link(app, outbox):
    first = requested(app, outbox)
    at(app, NOW + timedelta(minutes=4, seconds=59))
    assert forgot(app, "ada")[1] == {"message": SENT}
    assert len(outbox.sent) == 1
    at(app, NOW + timedelta(minutes=5))
    second = requested(app, outbox)
    assert second != first
    save(app, first)
    assert sign_in(app, "ada", PASSWORD) is not None
    save(app, second)
    assert sign_in(app, "ada", "reset-pass-1") is not None


def test_a_link_stops_working_after_a_change_on_the_account_page(app, outbox):
    token = requested(app, outbox)
    change(app, sign_in(app))
    save(app, token)
    assert sign_in(app, "ada", "new-pass-1") is not None


def test_a_link_stops_working_after_dw_account_sets_the_password_or_removes_the_account(app, outbox):
    ada = requested(app, outbox)
    nana = requested(app, outbox, "nana")
    with PolicyStore(app.state.database) as store:
        accounts = Accounts(store.connection)
        accounts.update("ada", password="host-pass")
        accounts.remove("nana")
    save(app, ada)
    save(app, nana)
    assert sign_in(app, "ada", "host-pass") is not None
    with PolicyStore(app.state.database) as store:
        Accounts(store.connection).add("nana", REVIEWER, email="nana@example.net")
    # A new account with the same name gets nothing from the old link.
    save(app, nana)
    assert sign_in(app, "nana", "reset-pass-1") is None


def test_a_first_password_chosen_by_reset_sends_no_notice(app, outbox):
    with PolicyStore(app.state.database) as store:
        Accounts(store.connection).add("cara", REVIEWER, email="cara@example.net")
    token = requested(app, outbox, "cara")
    save(app, token)
    assert sign_in(app, "cara", "reset-pass-1") is not None
    assert outbox.subjects() == ["Reset your Daywarden password"]


# What every one of these addresses does


OPEN = ("/parent/api/password-reset", "/parent/api/password-reset/save")
POSTS = ("/parent/api/account/password", *OPEN)


@pytest.mark.parametrize("address", POSTS)
def test_a_body_over_4_kb_is_refused_before_it_is_read(app, address):
    body = json.dumps({"username": "ada", "password": "x" * 5000}).encode()
    status, answer, _headers = call(app, "POST", address, body=body, content_type="application/json", cookie=sign_in(app))
    assert (status, json.loads(answer)) == (413, {"error": "The request is too large."})


@pytest.mark.parametrize("address", POSTS)
def test_a_form_or_plain_http_is_refused(app, address):
    assert call(app, "POST", address, body=b"username=ada", content_type="application/x-www-form-urlencoded")[0] == 415
    assert call(app, "POST", address, json_body={"username": "ada"}, scheme="http")[0] == 403
    assert call(app, "GET", "/parent/api/password-reset", scheme="http")[0] == 403


def test_with_no_parent_account_the_forgot_and_reset_addresses_say_the_portal_is_closed(service, monkeypatch, outbox):
    for name, value in EMAIL.items():
        monkeypatch.setenv(name, value)
    with PolicyStore(service.state.database) as store:
        store.connection.execute("PRAGMA foreign_keys = OFF")
        store.connection.execute("DELETE FROM parent_accounts")
        store.connection.commit()
    app = service.state.remake()
    closed = {"error": "The parent portal is closed until a parent account is added.", "closed": True}
    status, body, _headers = call(app, "GET", "/parent/api/password-reset")
    assert (status, json.loads(body)) == (403, closed)
    assert forgot(app, "ada")[:2] == (403, closed)
    assert save(app, "0" * 64)[:2] == (403, closed)


def test_portal_pages_send_no_referrer(app):
    status, _body, headers = call(app, "GET", "/parent/reset")
    assert status == 200
    assert headers["referrer-policy"] == ["no-referrer"]


def test_a_bad_email_setting_stops_the_service_naming_it(service, monkeypatch):
    from policy.app import create_app

    for name, value in {**EMAIL, "SMTP_SECURITY": "plain"}.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(SystemExit) as stopped:
        create_app()
    assert "SMTP_SECURITY" in str(stopped.value)
    monkeypatch.setenv("SMTP_SECURITY", "tls")
    monkeypatch.setenv("PARENT_RESET_LIFETIME", "0m")
    with pytest.raises(SystemExit) as stopped:
        create_app()
    assert "PARENT_RESET_LIFETIME" in str(stopped.value)


def test_the_service_log_says_email_is_on_without_the_password(service, monkeypatch, capsys):
    for name, value in EMAIL.items():
        monkeypatch.setenv(name, value)
    service.state.remake()
    log = capsys.readouterr().out
    assert "email is on: smtp.example.net:465 with tls as daywarden@example.net" in log
    assert "hunter2-secret" not in log
