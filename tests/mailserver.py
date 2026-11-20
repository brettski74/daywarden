"""A local SMTP server for the email tests, with its own CA, so nothing leaves the machine.

``MailServer`` runs aiosmtpd on a free port on 127.0.0.1 in one of three ways:
``tls`` (TLS from the first byte, as on port 465), ``starttls`` (as on port
587), or ``plain``, a server that offers no STARTTLS at all. It keeps each
message it accepts and each sign-in it was sent. ``client_context`` trusts only
the test CA, as the system's trusted authorities would trust a real server.
"""

from __future__ import annotations

import socket
import ssl
from datetime import datetime, timedelta, timezone
from email import message_from_bytes, policy
from email.message import EmailMessage
from ipaddress import IPv4Address
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

USERNAME = "daywarden@example.net"
PASSWORD = "app-password-7Q2x"


def _name(common: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common)])


class TestCA:
    """A CA and a server certificate it signed for some names."""

    __test__ = False

    def __init__(self, directory: Path, names: tuple[str, ...] = ("localhost", "127.0.0.1")) -> None:
        now = datetime.now(timezone.utc)
        ca_key = ec.generate_private_key(ec.SECP256R1())
        ca = (
            x509.CertificateBuilder()
            .subject_name(_name("Daywarden test CA"))
            .issuer_name(_name("Daywarden test CA"))
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=2))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        key = ec.generate_private_key(ec.SECP256R1())
        alternatives = [
            x509.IPAddress(IPv4Address(name)) if name.replace(".", "").isdigit() else x509.DNSName(name) for name in names
        ]
        server = (
            x509.CertificateBuilder()
            .subject_name(_name(names[0]))
            .issuer_name(ca.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=2))
            .add_extension(x509.SubjectAlternativeName(alternatives), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        directory.mkdir(parents=True, exist_ok=True)
        self.ca_file = directory / "ca.pem"
        self.ca_file.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
        self.cert_file = directory / "server.pem"
        self.cert_file.write_bytes(server.public_bytes(serialization.Encoding.PEM))
        self.key_file = directory / "server-key.pem"
        self.key_file.write_bytes(
            key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        )

    def server_context(self) -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert_file, self.key_file)
        return context

    def client_context(self) -> ssl.SSLContext:
        """What ``ssl.create_default_context()`` gives, trusting the test CA instead of the system's."""
        return ssl.create_default_context(cafile=str(self.ca_file))


def free_port() -> int:
    with socket.socket() as found:
        found.bind(("127.0.0.1", 0))
        return found.getsockname()[1]


class MailServer:
    """aiosmtpd on 127.0.0.1, as a context manager. ``messages`` and ``logins`` fill as clients send."""

    def __init__(self, ca: TestCA, mode: str = "tls", *, refuse_to: str | None = None) -> None:
        from aiosmtpd.controller import Controller
        from aiosmtpd.smtp import AuthResult, LoginPassword

        self.messages: list[EmailMessage] = []
        self.logins: list[tuple[str, str]] = []
        self.port = free_port()
        outer = self

        class Handler:
            async def handle_RCPT(self, server, session, envelope, address, options):
                if refuse_to is not None and address == refuse_to:
                    return "550 5.1.1 No such mailbox here"
                envelope.rcpt_tos.append(address)
                return "250 OK"

            async def handle_DATA(self, server, session, envelope):
                outer.messages.append(message_from_bytes(envelope.original_content, policy=policy.default))
                return "250 Message accepted for delivery"

        def authenticator(server, session, envelope, mechanism, data):
            if not isinstance(data, LoginPassword):
                return AuthResult(success=False, handled=False)
            username, password = data.login.decode(), data.password.decode()
            outer.logins.append((username, password))
            # handled=False lets aiosmtpd send the 535 itself.
            return AuthResult(success=username == USERNAME and password == PASSWORD, handled=False)

        options = {
            "authenticator": authenticator,
            # A sign-in over plain text is refused by the server too, as a real one would.
            "auth_require_tls": True,
            "auth_exclude_mechanism": ["CRAM-MD5", "LOGIN"],
        }
        if mode == "tls":
            options["ssl_context"] = ca.server_context()
            # aiosmtpd counts only STARTTLS as TLS for auth_require_tls. This connection is TLS from the first byte.
            options["auth_require_tls"] = False
        elif mode == "starttls":
            options["tls_context"] = ca.server_context()
            options["require_starttls"] = True
        elif mode != "plain":
            raise ValueError(mode)
        self.controller = Controller(Handler(), hostname="127.0.0.1", port=self.port, server_hostname="localhost", **options)

    def __enter__(self) -> "MailServer":
        self.controller.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.controller.stop()
