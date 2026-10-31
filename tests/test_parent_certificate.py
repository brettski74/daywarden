"""S007.1: the parent certificate is signed by the household CA."""

import socket
import ssl
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from policy.parent_tls import ensure_certificate, require_names

ISSUED = datetime(2026, 10, 1, tzinfo=timezone.utc)
NAMES = ("reports.home", "192.0.2.10")


def _write_ca(directory: Path, common: str = "mitmproxy") -> x509.Certificate:
    directory.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common)])
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    pem = cert.public_bytes(serialization.Encoding.PEM) + key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    (directory / "mitmproxy-ca.pem").write_bytes(pem)
    (directory / "mitmproxy-ca-cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert


def _leaf(directory: Path) -> x509.Certificate:
    return x509.load_pem_x509_certificate((directory / "parent-cert.pem").read_bytes())


def _names(cert: x509.Certificate) -> tuple[set[str], set[str]]:
    alternative = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    dns = {item.lower() for item in alternative.get_values_for_type(x509.DNSName)}
    ips = {item.compressed for item in alternative.get_values_for_type(x509.IPAddress)}
    return dns, ips


def test_an_empty_name_list_is_a_startup_error():
    with pytest.raises(SystemExit):
        require_names(None)
    with pytest.raises(SystemExit):
        require_names("  ,  ")
    with pytest.raises(SystemExit):
        require_names("https://reports.home")
    assert require_names("reports.home, 192.0.2.10") == ("reports.home", "192.0.2.10")


def test_a_new_certificate_is_signed_by_the_ca_for_30_days(tmp_path):
    ca_dir = tmp_path / "ca"
    policy = tmp_path / "policy.yaml"
    policy.write_text("timezone: Australia/Sydney\n", encoding="utf-8")
    ca_cert = _write_ca(ca_dir)
    key_path, cert_path = ensure_certificate(ca_dir, NAMES, ISSUED)
    assert key_path.parent == ca_dir
    assert cert_path.parent == ca_dir
    assert (key_path.stat().st_mode & 0o777) == 0o600
    assert b"PRIVATE KEY" in key_path.read_bytes()
    assert b"PRIVATE KEY" not in cert_path.read_bytes()
    assert policy.read_text(encoding="utf-8") == "timezone: Australia/Sydney\n"
    cert = _leaf(ca_dir)
    assert cert.not_valid_before_utc == ISSUED
    assert cert.not_valid_after_utc == ISSUED + timedelta(days=30)
    assert _names(cert) == ({"reports.home"}, {"192.0.2.10"})
    ca_cert.public_key().verify(
        cert.signature,
        cert.tbs_certificate_bytes,
        padding.PKCS1v15(),
        cert.signature_hash_algorithm,
    )


def test_a_restart_keeps_the_certificate_until_it_is_inside_three_days(tmp_path):
    ca_dir = tmp_path / "ca"
    _write_ca(ca_dir)
    ensure_certificate(ca_dir, NAMES, ISSUED)
    first_cert = (ca_dir / "parent-cert.pem").read_bytes()
    first_key = (ca_dir / "parent-key.pem").read_bytes()
    keep_at = ISSUED + timedelta(days=27) - timedelta(seconds=1)
    ensure_certificate(ca_dir, NAMES, keep_at)
    assert (ca_dir / "parent-cert.pem").read_bytes() == first_cert
    assert (ca_dir / "parent-key.pem").read_bytes() == first_key

    renew_at = ISSUED + timedelta(days=27)
    ensure_certificate(ca_dir, NAMES, renew_at)
    assert (ca_dir / "parent-cert.pem").read_bytes() != first_cert
    renewed = _leaf(ca_dir)
    assert renewed.not_valid_before_utc == renew_at
    assert renewed.not_valid_after_utc == renew_at + timedelta(days=30)


def test_a_missing_configured_name_or_a_different_ca_issues_a_new_certificate(tmp_path):
    ca_dir = tmp_path / "ca"
    _write_ca(ca_dir)
    ensure_certificate(ca_dir, ("reports.home",), ISSUED)
    first = (ca_dir / "parent-cert.pem").read_bytes()
    ensure_certificate(ca_dir, ("reports.home", "192.0.2.10"), ISSUED)
    assert (ca_dir / "parent-cert.pem").read_bytes() != first
    assert _names(_leaf(ca_dir)) == ({"reports.home"}, {"192.0.2.10"})
    assert "evil.example" not in (ca_dir / "parent-cert.pem").read_text(encoding="utf-8")

    current = (ca_dir / "parent-cert.pem").read_bytes()
    _write_ca(ca_dir, common="replacement")
    ensure_certificate(ca_dir, ("reports.home", "192.0.2.10"), ISSUED)
    assert (ca_dir / "parent-cert.pem").read_bytes() != current


def test_a_client_trusts_the_certificate_only_for_the_configured_name(tmp_path):
    ca_dir = tmp_path / "ca"
    ca_cert = _write_ca(ca_dir)
    issued = datetime.now(timezone.utc).replace(microsecond=0)
    _key, cert_path = ensure_certificate(ca_dir, NAMES, issued)
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(cert_path, ca_dir / "parent-key.pem")
    bound = socket.socket()
    bound.bind(("127.0.0.1", 0))
    bound.listen(1)
    bound.settimeout(5)
    port = bound.getsockname()[1]
    tls = server.wrap_socket(bound, server_side=True)

    def serve_one():
        try:
            connection, _address = tls.accept()
        except OSError:
            return
        try:
            connection.recv(8)
        except OSError:
            pass
        connection.close()

    thread = threading.Thread(target=serve_one)
    thread.start()
    client = ssl.create_default_context(cadata=ca_cert.public_bytes(serialization.Encoding.PEM).decode())
    with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
        with client.wrap_socket(raw, server_hostname="reports.home") as wrapped:
            peer = wrapped.getpeercert()
    thread.join(5)
    tls.close()
    assert peer["subjectAltName"] == (
        ("DNS", "reports.home"),
        ("IP Address", "192.0.2.10"),
    )

    refused = ssl.create_default_context(cadata=ca_cert.public_bytes(serialization.Encoding.PEM).decode())
    bound = socket.socket()
    bound.bind(("127.0.0.1", 0))
    bound.listen(1)
    bound.settimeout(5)
    port = bound.getsockname()[1]
    tls = server.wrap_socket(bound, server_side=True)
    thread = threading.Thread(target=serve_one)
    thread.start()
    with pytest.raises(ssl.SSLCertVerificationError):
        with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
            with refused.wrap_socket(raw, server_hostname="evil.example") as wrapped:
                wrapped.send(b"hi")
    thread.join(5)
    tls.close()
