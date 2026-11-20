"""Email from Daywarden (S044.2): its settings, the emails, and how they are sent.

Email is on when ``SMTP_HOST`` is set. Every setting is read once, at
startup, and a setting that is set but wrong stops the service, or
``dw-account``, with a message that names it. ``SMTP_PASSWORD`` is never
printed: it is kept out of ``MailSettings``'s repr and out of every message.

``Mailer`` writes the emails, as plain text from ``MAIL_FROM``, and hands each
one to a ``Transport``. ``SmtpTransport`` is the one way of sending: SMTP with
TLS from the first byte or STARTTLS, the server's certificate checked against
the system's trusted authorities and ``SMTP_HOST``. Nothing is ever sent in
plain text, and the username and password are sent only once the connection is
encrypted. Another way of sending, such as a provider's HTTP API, is another
class with a ``send`` method, chosen in ``transport_for``. ``Mailer`` does not
change.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import format_datetime, getaddresses, make_msgid
from typing import Protocol

from policy.accounts import positive_duration

TLS = "tls"
STARTTLS = "starttls"
SECURITIES = (TLS, STARTTLS)
DEFAULT_PORT = 465
DEFAULT_RESET_LIFETIME = timedelta(minutes=60)
OFF = "Email is off: SMTP_HOST is not set."
# Long enough for a slow server, short enough that dw-account does not hang.
TIMEOUT_SECONDS = 30

Environ = os._Environ[str] | dict[str, str]


class MailError(Exception):
    """An email that was not sent, and why, in words for the parent or the log."""


@dataclass(frozen=True)
class MailSettings:
    """The mail server and the sender, from ``SMTP_*`` and ``MAIL_FROM``."""

    host: str
    port: int = DEFAULT_PORT
    security: str = TLS
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    sender: str = ""

    def describe(self) -> str:
        """Say where email goes, for the service log. Never the password."""
        login = f" as {self.username}" if self.username else ""
        return f"email is on: {self.host}:{self.port} with {self.security}{login}, from {self.sender}"


def _value(environ: Environ, name: str) -> str | None:
    """Return a setting, or None when it is missing or empty. Compose passes an unset setting as empty."""
    value = environ.get(name)
    if value is None or value.strip() == "":
        return None
    return value.strip()


def mail_settings(environ: Environ) -> MailSettings | None:
    """Return the mail settings, or None when email is off.

    A setting that is set but wrong raises SystemExit naming it, whether or not
    email is on. MAIL_FROM is needed only when SMTP_HOST is set.
    """
    host = _value(environ, "SMTP_HOST")
    port_text = _value(environ, "SMTP_PORT")
    port = DEFAULT_PORT
    if port_text is not None:
        if not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
            raise SystemExit(f"SMTP_PORT must be a port number from 1 to 65535, such as 465 or 587, not {port_text}")
        port = int(port_text)
    security = (_value(environ, "SMTP_SECURITY") or TLS).lower()
    if security not in SECURITIES:
        raise SystemExit(
            f"SMTP_SECURITY must be tls, as on port 465, or starttls, as on port 587, not {environ.get('SMTP_SECURITY', '').strip()}. "
            "There is no setting for plain text."
        )
    username = _value(environ, "SMTP_USERNAME")
    # A password is taken as it is: spaces may be part of it.
    password = environ.get("SMTP_PASSWORD") or None
    if (username is None) != (password is None):
        missing, given = ("SMTP_PASSWORD", "SMTP_USERNAME") if password is None else ("SMTP_USERNAME", "SMTP_PASSWORD")
        raise SystemExit(f"{missing} is not set, but {given} is. Set both, or neither for a server that needs no sign-in.")
    sender = _value(environ, "MAIL_FROM")
    if sender is not None and sender_problem(sender):
        raise SystemExit(f"MAIL_FROM {sender_problem(sender)}")
    if host is None:
        return None
    if sender is None:
        raise SystemExit("MAIL_FROM is not set. Email is on because SMTP_HOST is set, and it needs a sender, such as Daywarden <daywarden@example.net>.")
    return MailSettings(host, port, security, username, password, sender)


def sender_problem(sender: str) -> str | None:
    """Return why sender is not one address, such as Daywarden <daywarden@example.net>, or None."""
    found = getaddresses([sender])
    if len(found) != 1 or "@" not in found[0][1] or any(char in found[0][1] for char in " <>"):
        return f"must be one address, such as Daywarden <daywarden@example.net>, not {sender}"
    return None


def reset_lifetime(environ: Environ) -> timedelta:
    """Return how long a reset link works, from PARENT_RESET_LIFETIME. 60 minutes when it is not set."""
    value = _value(environ, "PARENT_RESET_LIFETIME")
    if value is None:
        return DEFAULT_RESET_LIFETIME
    return timedelta(seconds=positive_duration(value, "PARENT_RESET_LIFETIME"))


def portal_address(name: str, port: int, path: str) -> str:
    """Return an address on the parent port for an email, such as https://garden:8084/parent/login."""
    host = f"[{name}]" if ":" in name else name
    return f"https://{host}:{port}{path}"


def span(lifetime: timedelta) -> str:
    """Say a lifetime in words, such as "60 minutes"."""
    seconds = int(lifetime.total_seconds())
    if seconds % 60:
        return f"{seconds} seconds" if seconds != 1 else "1 second"
    minutes = seconds // 60
    return f"{minutes} minutes" if minutes != 1 else "1 minute"


def moment(when: datetime) -> str:
    """Say a household-local time for an email, such as "3:45 pm on Friday 20 November 2026 (Australia/Sydney)"."""
    hour = when.hour % 12 or 12
    zone = getattr(when.tzinfo, "key", None) or when.tzname() or ""
    said = f"{hour}:{when.minute:02d} {'am' if when.hour < 12 else 'pm'} on {when:%A} {when.day} {when:%B %Y}"
    return f"{said} ({zone})" if zone else said


# Sending


class Transport(Protocol):
    """One way of sending an email. ``send`` returns once the server accepted it, or raises MailError."""

    def send(self, message: EmailMessage) -> None: ...


def default_context() -> ssl.SSLContext:
    """The system's trusted authorities, with the host name checked. Tests replace this with their own CA."""
    return ssl.create_default_context()


class SmtpTransport:
    """SMTP over TLS from the first byte, or upgraded with STARTTLS. Never plain text."""

    def __init__(self, settings: MailSettings, context: Callable[[], ssl.SSLContext] | None = None) -> None:
        self.settings = settings
        self.context = context

    def _connect(self) -> smtplib.SMTP:
        settings = self.settings
        context = (self.context or default_context)()
        if settings.security == TLS:
            return smtplib.SMTP_SSL(settings.host, settings.port, context=context, timeout=TIMEOUT_SECONDS)
        server = smtplib.SMTP(settings.host, settings.port, timeout=TIMEOUT_SECONDS)
        try:
            server.ehlo()
            if not server.has_extn("starttls"):
                raise MailError(
                    f"The mail server at {settings.host}:{settings.port} does not offer STARTTLS, so nothing was sent. "
                    "Check SMTP_PORT and SMTP_SECURITY."
                )
            server.starttls(context=context)
            server.ehlo()
        except BaseException:
            server.close()
            raise
        return server

    def send(self, message: EmailMessage) -> None:
        settings = self.settings
        where = f"{settings.host}:{settings.port}"
        try:
            server = self._connect()
            try:
                if settings.username is not None and settings.password is not None:
                    server.login(settings.username, settings.password)
                server.send_message(message)
            finally:
                try:
                    server.quit()
                except (smtplib.SMTPException, OSError):
                    server.close()
        except MailError:
            raise
        except ssl.SSLCertVerificationError as error:
            raise MailError(
                f"The mail server at {where} is not trusted, so nothing was sent: {error.verify_message or error.reason}."
            ) from None
        except smtplib.SMTPAuthenticationError as error:
            raise MailError(f"The mail server at {where} refused SMTP_USERNAME and SMTP_PASSWORD: {_said(error)}") from None
        except smtplib.SMTPRecipientsRefused as error:
            refusals = "; ".join(f"{_said(refusal)}" for refusal in _refusals(error))
            raise MailError(f"The mail server at {where} refused the address: {refusals}") from None
        except smtplib.SMTPResponseException as error:
            raise MailError(f"The mail server at {where} refused the email: {_said(error)}") from None
        except smtplib.SMTPServerDisconnected as error:
            raise MailError(f"The mail server at {where} closed the connection: {error}") from None
        except smtplib.SMTPException as error:
            raise MailError(f"The mail server at {where} refused the email: {error}") from None
        except ssl.SSLError as error:
            raise MailError(f"Could not make an encrypted connection to the mail server at {where}: {error.reason or error}") from None
        except OSError as error:
            raise MailError(f"Could not reach the mail server at {where}: {error.strerror or error}") from None


def _refusals(error: smtplib.SMTPRecipientsRefused) -> list[smtplib.SMTPResponseException]:
    return [smtplib.SMTPResponseException(code, text) for code, text in error.recipients.values()]


def _said(error: smtplib.SMTPResponseException) -> str:
    text = error.smtp_error.decode("utf-8", "replace") if isinstance(error.smtp_error, bytes) else str(error.smtp_error)
    return f"{error.smtp_code} {' '.join(text.split())}"


def transport_for(settings: MailSettings) -> Transport:
    """Return the way of sending the settings name. A new way, such as an HTTP API, is chosen here."""
    return SmtpTransport(settings)


# Writing


class Mailer:
    """Writes Daywarden's emails and sends each through one transport."""

    def __init__(self, settings: MailSettings, transport: Transport | None = None) -> None:
        self.settings = settings
        self.transport = transport if transport is not None else transport_for(settings)

    def _send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.settings.sender
        message["To"] = to
        message["Subject"] = subject
        message["Date"] = format_datetime(datetime.now().astimezone())
        message["Message-ID"] = make_msgid(domain=_domain(self.settings.sender))
        message.set_content(body)
        self.transport.send(message)

    def test(self, to: str, username: str) -> None:
        self._send(
            to,
            "Daywarden test email",
            f"This is a test email from Daywarden, sent to {username}'s address with dw-account test-email.\n\n"
            "Email is working. There is nothing to do.\n",
        )

    def welcome(self, to: str, username: str, role: str, sign_in: str) -> None:
        article = "an" if role == "admin" else "a"
        self._send(
            to,
            "Your Daywarden account",
            f"A Daywarden parent account has been made for you.\n\n"
            f"Username: {username}\n"
            f"Role: {article} {role}\n\n"
            f"To choose your password, open the sign-in screen:\n\n"
            f"{sign_in}\n\n"
            f"Press Forgot password and enter your username, {username}. A link for choosing your password will be "
            f"sent to this address.\n",
        )

    def reset(self, to: str, username: str, link: str, ends: str) -> None:
        self._send(
            to,
            "Reset your Daywarden password",
            f"Someone asked to reset the password of the Daywarden account {username}.\n\n"
            f"To choose a new password, open this link:\n\n"
            f"{link}\n\n"
            f"The link works once, and stops working at {ends}.\n\n"
            "If you did not ask for this, you can ignore this email, and nothing changes.\n",
        )

    def changed(self, to: str, username: str, how: str, when: str) -> None:
        self._send(
            to,
            "Your Daywarden password was changed",
            f"The password of the Daywarden account {username} was {how} at {when}.\n\n"
            "If you did not do this, tell whoever runs Daywarden.\n",
        )


# How a password changed, as the notice says it.
CHANGED_ON_PAGE = "changed on the Account page"
RESET_BY_EMAIL = "reset with a link sent by email"
SET_ON_HOST = "set on the server with dw-account update --password"


def _domain(sender: str) -> str | None:
    address = getaddresses([sender])[0][1]
    try:
        return Address(addr_spec=address).domain or None
    except (ValueError, IndexError):
        return None
