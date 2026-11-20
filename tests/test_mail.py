"""S044.2: the email settings, the SMTP transport, and the emails, against a local server."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

pytest.importorskip("aiosmtpd")

from mailserver import PASSWORD, USERNAME, MailServer, TestCA  # noqa: E402
from policy.mail import (  # noqa: E402
    MailError,
    Mailer,
    MailSettings,
    SmtpTransport,
    mail_settings,
    moment,
    reset_lifetime,
    span,
)

ON = {"SMTP_HOST": "smtp.forwardemail.net", "MAIL_FROM": "Daywarden <daywarden@example.net>"}


@pytest.fixture(scope="module")
def ca(tmp_path_factory):
    return TestCA(tmp_path_factory.mktemp("ca"))


def settings(server: MailServer, security: str, **changes) -> MailSettings:
    found = {
        "host": "localhost",
        "port": server.port,
        "security": security,
        "username": USERNAME,
        "password": PASSWORD,
        "sender": "Daywarden <daywarden@example.net>",
    }
    found.update(changes)
    return MailSettings(**found)


# Settings


def test_email_is_off_without_smtp_host_and_on_with_it_using_the_defaults():
    assert mail_settings({}) is None
    assert mail_settings({"SMTP_HOST": "", "SMTP_PORT": "", "MAIL_FROM": ""}) is None
    found = mail_settings(ON)
    assert (found.host, found.port, found.security, found.username, found.password) == ("smtp.forwardemail.net", 465, "tls", None, None)
    found = mail_settings({**ON, "SMTP_PORT": "587", "SMTP_SECURITY": "STARTTLS", "SMTP_USERNAME": "a@b.net", "SMTP_PASSWORD": "pw x"})
    assert (found.port, found.security, found.username, found.password) == (587, "starttls", "a@b.net", "pw x")


def test_the_password_is_not_in_the_settings_repr_or_the_log_line():
    found = mail_settings({**ON, "SMTP_USERNAME": "a@b.net", "SMTP_PASSWORD": "hunter2-secret"})
    assert "hunter2-secret" not in repr(found)
    assert "hunter2-secret" not in found.describe()
    assert found.describe() == "email is on: smtp.forwardemail.net:465 with tls as a@b.net, from Daywarden <daywarden@example.net>"


@pytest.mark.parametrize(
    ("environ", "named"),
    [
        ({"SMTP_HOST": "smtp.example.net"}, "MAIL_FROM"),
        ({**ON, "SMTP_SECURITY": "plain"}, "SMTP_SECURITY"),
        ({"SMTP_SECURITY": "plain"}, "SMTP_SECURITY"),
        ({**ON, "SMTP_PORT": "abc"}, "SMTP_PORT"),
        ({**ON, "SMTP_PORT": "70000"}, "SMTP_PORT"),
        ({**ON, "SMTP_USERNAME": "a@b.net"}, "SMTP_PASSWORD"),
        ({**ON, "SMTP_PASSWORD": "hunter2-secret"}, "SMTP_USERNAME"),
        ({**ON, "MAIL_FROM": "not an address"}, "MAIL_FROM"),
    ],
)
def test_a_setting_that_is_set_but_wrong_stops_with_a_message_naming_it(environ, named):
    with pytest.raises(SystemExit) as stopped:
        mail_settings(environ)
    assert str(stopped.value).startswith(named)
    assert "hunter2-secret" not in str(stopped.value)


def test_the_reset_lifetime_defaults_to_60_minutes_and_must_be_positive():
    assert reset_lifetime({}) == timedelta(minutes=60)
    assert reset_lifetime({"PARENT_RESET_LIFETIME": "2h"}) == timedelta(hours=2)
    for bad in ("0m", "soon", "-5m"):
        with pytest.raises(SystemExit) as stopped:
            reset_lifetime({"PARENT_RESET_LIFETIME": bad})
        assert str(stopped.value).startswith("PARENT_RESET_LIFETIME")
    assert span(timedelta(minutes=60)) == "60 minutes"
    assert span(timedelta(minutes=1)) == "1 minute"
    assert span(timedelta(seconds=90)) == "90 seconds"


def test_a_household_time_names_its_zone():
    when = datetime(2026, 11, 20, 4, 45, tzinfo=timezone.utc).astimezone(ZoneInfo("Australia/Sydney"))
    assert moment(when) == "3:45 pm on Friday 20 November 2026 (Australia/Sydney)"


# Sending


@pytest.mark.parametrize("security", ["tls", "starttls"])
def test_an_email_is_sent_encrypted_with_the_username_and_password(ca, security):
    with MailServer(ca, security) as server:
        mailer = Mailer(settings(server, security), SmtpTransport(settings(server, security), ca.client_context))
        mailer.test("ada@example.net", "ada")
    assert server.logins == [(USERNAME, PASSWORD)]
    (sent,) = server.messages
    assert sent["Subject"] == "Daywarden test email"
    assert sent["From"] == "Daywarden <daywarden@example.net>"
    assert sent["To"] == "ada@example.net"
    assert sent.get_content_type() == "text/plain"
    assert "dw-account test-email" in sent.get_content()


def test_a_server_that_offers_no_starttls_gets_nothing_and_no_password(ca):
    with MailServer(ca, "plain") as server:
        transport = SmtpTransport(settings(server, "starttls"), ca.client_context)
        with pytest.raises(MailError) as failed:
            Mailer(settings(server, "starttls"), transport).test("ada@example.net", "ada")
    assert "does not offer STARTTLS, so nothing was sent" in str(failed.value)
    assert server.logins == [] and server.messages == []


@pytest.mark.parametrize("security", ["tls", "starttls"])
def test_a_certificate_that_does_not_match_smtp_host_gets_nothing_and_no_password(tmp_path, security):
    elsewhere = TestCA(tmp_path / "elsewhere", ("mail.elsewhere.example",))
    with MailServer(elsewhere, security) as server:
        transport = SmtpTransport(settings(server, security), elsewhere.client_context)
        with pytest.raises(MailError) as failed:
            Mailer(settings(server, security), transport).test("ada@example.net", "ada")
    assert "is not trusted, so nothing was sent" in str(failed.value)
    assert "localhost" in str(failed.value)
    assert server.logins == [] and server.messages == []


def test_a_certificate_from_an_authority_the_system_does_not_trust_gets_nothing(ca, tmp_path):
    other = TestCA(tmp_path / "other")
    with MailServer(ca, "tls") as server:
        with pytest.raises(MailError) as failed:
            Mailer(settings(server, "tls"), SmtpTransport(settings(server, "tls"), other.client_context)).test("a@b.net", "ada")
    assert "is not trusted" in str(failed.value)
    assert server.logins == []


def test_refusals_are_said_without_the_password(ca):
    with MailServer(ca, "tls", refuse_to="nobody@example.net") as server:
        wrong = settings(server, "tls", password="wrong-secret-value")
        with pytest.raises(MailError) as failed:
            Mailer(wrong, SmtpTransport(wrong, ca.client_context)).test("ada@example.net", "ada")
        assert "refused SMTP_USERNAME and SMTP_PASSWORD: 535" in str(failed.value)
        assert "wrong-secret-value" not in str(failed.value)
        right = settings(server, "tls")
        with pytest.raises(MailError) as failed:
            Mailer(right, SmtpTransport(right, ca.client_context)).test("nobody@example.net", "ada")
        assert "refused the address: 550 5.1.1 No such mailbox here" in str(failed.value)


def test_a_server_that_cannot_be_reached_is_said(ca):
    from mailserver import free_port

    closed = MailSettings("localhost", free_port(), "tls", None, None, "d@example.net")
    with pytest.raises(MailError) as failed:
        Mailer(closed, SmtpTransport(closed, ca.client_context)).test("ada@example.net", "ada")
    assert str(failed.value).startswith(f"Could not reach the mail server at localhost:{closed.port}")


class Recorder:
    """A transport that keeps what it is given. Another way of sending needs only this method."""

    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)


def test_the_emails_are_written_without_knowing_how_they_are_sent():
    transport = Recorder()
    mailer = Mailer(mail_settings(ON), transport)
    mailer.welcome("nana@example.net", "nana", "reviewer", "https://garden:8084/parent/login")
    mailer.reset("nana@example.net", "nana", "https://garden:8084/parent/reset#abc", "4:45 pm on Friday 20 November 2026 (UTC)")
    mailer.changed("nana@example.net", "nana", "changed on the Account page", "3:45 pm on Friday 20 November 2026 (UTC)")
    welcome, reset, changed = transport.sent
    assert welcome["Subject"] == "Your Daywarden account"
    text = welcome.get_content()
    assert "Username: nana" in text and "Role: a reviewer" in text
    assert "https://garden:8084/parent/login" in text and "Forgot password" in text and "reset#" not in text
    assert reset["Subject"] == "Reset your Daywarden password"
    text = reset.get_content()
    assert "nana" in text and "https://garden:8084/parent/reset#abc" in text
    assert "4:45 pm on Friday 20 November 2026 (UTC)" in text and "ignore this email, and nothing changes" in text
    assert changed["Subject"] == "Your Daywarden password was changed"
    text = changed.get_content()
    assert "changed on the Account page at 3:45 pm" in text and "tell whoever runs Daywarden" in text and "https://" not in text
    assert all(message.get_content_type() == "text/plain" for message in transport.sent)
