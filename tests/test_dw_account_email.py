"""S044.2: dw-account test-email, the welcome email, and the notice from update --password, against a local mail server.

The command runs as it does in the decisions container, trusting the system's
authorities. SSL_CERT_FILE makes the test CA the system's one authority.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

pytest.importorskip("aiosmtpd")

from mailserver import PASSWORD as SMTP_PASSWORD, USERNAME as SMTP_USERNAME, MailServer, TestCA  # noqa: E402
from test_dw_account import PASSWORD, database, dw_account, listing, signs_in  # noqa: E402,F401 - database is the fixture


@pytest.fixture(scope="module")
def ca(tmp_path_factory):
    return TestCA(tmp_path_factory.mktemp("ca"))


def email_on(ca: TestCA, server: MailServer, security: str = "tls", **changes) -> dict:
    return {
        "SSL_CERT_FILE": str(ca.ca_file),
        "SMTP_HOST": "localhost",
        "SMTP_PORT": str(server.port),
        "SMTP_SECURITY": security,
        "SMTP_USERNAME": SMTP_USERNAME,
        "SMTP_PASSWORD": SMTP_PASSWORD,
        "MAIL_FROM": "Daywarden <daywarden@example.net>",
        "PARENT_NAMES": "garden,localhost",
        "POLICY_PORT": "8084",
        "POLICY_FILE": "/nonexistent/policy.yaml",
        **changes,
    }


def said(done) -> str:
    return done.stdout + done.stderr


# test-email


@pytest.mark.parametrize("security", ["tls", "starttls"])
def test_test_email_is_accepted_over_either_kind_of_tls(ca, database, security):
    assert dw_account(database, "update", "--email", "ada@example.net", "ada").returncode == 0
    with MailServer(ca, security) as server:
        done = dw_account(database, "test-email", "ada", env=email_on(ca, server, security))
    assert done.returncode == 0, done.stderr
    assert done.stdout == "The mail server accepted a test email to ada@example.net.\n"
    (sent,) = server.messages
    assert sent["To"] == "ada@example.net" and sent["Subject"] == "Daywarden test email"
    assert server.logins == [(SMTP_USERNAME, SMTP_PASSWORD)]
    assert SMTP_PASSWORD not in said(done)


def test_test_email_says_why_nothing_was_sent(ca, database, tmp_path):
    done = dw_account(database, "test-email", "ada")
    assert (done.returncode, done.stderr) == (1, "Email is off: SMTP_HOST is not set. Nothing was sent.\n")
    with MailServer(ca, "tls") as server:
        env = email_on(ca, server)
        done = dw_account(database, "test-email", "ada", env=env)
        assert done.returncode == 1
        assert done.stderr == "ada has no email address. Add one with dw-account update --email ADDRESS ada.\n"
        done = dw_account(database, "test-email", "zed", env=env)
        assert done.returncode == 1
        assert "There is no parent account zed." in done.stderr
        assert dw_account(database, "update", "--email", "ada@example.net", "ada").returncode == 0
        done = dw_account(database, "test-email", "ada", env={**env, "SMTP_PASSWORD": "wrong-secret-value"})
        assert done.returncode == 1
        assert "refused SMTP_USERNAME and SMTP_PASSWORD: 535" in done.stderr
        assert "wrong-secret-value" not in said(done)
    elsewhere = TestCA(tmp_path / "elsewhere", ("mail.elsewhere.example",))
    with MailServer(elsewhere, "starttls") as server:
        done = dw_account(database, "test-email", "ada", env=email_on(elsewhere, server, "starttls"))
    assert done.returncode == 1
    assert "The test email to ada@example.net was not sent. The mail server at localhost" in done.stderr
    assert "is not trusted, so nothing was sent" in done.stderr
    assert server.logins == [] and server.messages == []
    with MailServer(ca, "plain") as server:
        done = dw_account(database, "test-email", "ada", env=email_on(ca, server, "starttls"))
    assert done.returncode == 1
    assert "does not offer STARTTLS, so nothing was sent" in done.stderr
    assert server.logins == []


def test_a_wrong_email_setting_stops_the_command_naming_it(database):
    done = dw_account(database, "test-email", "ada", env={"SMTP_HOST": "localhost", "MAIL_FROM": "d@example.net", "SMTP_SECURITY": "plain"})
    assert done.returncode == 1
    assert done.stderr.startswith("SMTP_SECURITY must be tls")


def test_help_describes_test_email(database):
    shown = dw_account(database, "help")
    assert "test-email USERNAME" in shown.stdout
    assert dw_account(database, "test-email", "--help").returncode == 0


# The welcome email


def test_add_with_an_address_and_no_password_sends_a_welcome_email(ca, database):
    with MailServer(ca, "tls") as server:
        done = dw_account(database, "add", "--email", "nana@example.net", "nana", env=email_on(ca, server))
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == [
        "nana is added, as a reviewer, with the email address nana@example.net.",
        "A welcome email was sent to nana@example.net. It tells nana to choose a password with Forgot password.",
    ]
    (sent,) = server.messages
    assert sent["Subject"] == "Your Daywarden account"
    assert sent["From"] == "Daywarden <daywarden@example.net>"
    text = sent.get_content()
    assert "Username: nana" in text and "Role: a reviewer" in text
    assert "https://garden:8084/parent/login" in text and "Forgot password" in text
    assert "reset" not in text.lower().replace("forgot password", "")


def test_add_with_a_password_sends_no_welcome_email(ca, database):
    with MailServer(ca, "tls") as server:
        done = dw_account(database, "add", "--email", "nana@example.net", "--password", "nana", stdin="nana-pass\n", env=email_on(ca, server))
    assert done.returncode == 0, done.stderr
    assert "welcome" not in done.stdout
    assert server.messages == []


def test_a_welcome_email_that_fails_still_adds_the_account(ca, database):
    with MailServer(ca, "tls", refuse_to="nana@example.net") as server:
        done = dw_account(database, "add", "--email", "nana@example.net", "nana", env=email_on(ca, server))
    assert done.returncode == 1
    assert "nana is added" in done.stdout
    assert "No welcome email was sent to nana@example.net. The mail server at localhost" in done.stderr
    assert "550 5.1.1 No such mailbox here" in done.stderr
    assert "dw-account update --password nana sets one now." in done.stderr
    assert listing(database)[-1] == "nana reviewer nana@example.net no password"


# The notice


def test_update_password_emails_a_notice_and_a_failure_still_sets_it(ca, database):
    assert dw_account(database, "update", "--email", "ada@example.net", "ada").returncode == 0
    with MailServer(ca, "tls") as server:
        done = dw_account(database, "update", "--password", "ada", stdin="host-pass-1\n", env=email_on(ca, server))
    assert done.returncode == 0, done.stderr
    assert "ada was emailed that the password changed." in done.stdout
    (sent,) = server.messages
    assert sent["Subject"] == "Your Daywarden password was changed"
    assert "set on the server with dw-account update --password at " in sent.get_content()
    with MailServer(ca, "tls", refuse_to="ada@example.net") as server:
        done = dw_account(database, "update", "--password", "ada", stdin="host-pass-2\n", env=email_on(ca, server))
    assert done.returncode == 0
    assert "The password-changed email to ada@example.net was not sent." in done.stderr
    assert signs_in(database, "ada", "host-pass-2")
