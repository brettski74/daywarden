"""The certificate for parent pages, signed by the household CA.

Names come from configuration: the DNS names and IP addresses a parent uses
to open the service. They are not taken from the Host header. A certificate
is valid for 30 days. It is issued when there is none, when it does not
cover the configured names, when it is not signed by the current CA, or when
it expires within 3 days. Otherwise the files already beside the CA are kept,
including across a restart.
"""

from __future__ import annotations

import ipaddress
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CA_FILE = "mitmproxy-ca.pem"
CERT_FILE = "parent-cert.pem"
KEY_FILE = "parent-key.pem"
VALIDITY = timedelta(days=30)
RENEW_WITHIN = timedelta(days=3)

_DNS = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\Z"
)


def require_names(value: str | None) -> tuple[str, ...]:
    """Return the configured DNS names and IP addresses.

    An empty list is a startup error. A token that is neither a DNS name
    nor an IP address is a startup error too.
    """
    if value is None or not value.strip():
        raise SystemExit(
            "PARENT_NAMES is empty; the parent listener needs a DNS name or an IP address"
        )
    names: list[str] = []
    seen: set[str] = set()
    for part in value.split(","):
        token = part.strip()
        if token.startswith("[") and token.endswith("]"):
            token = token[1:-1]
        if token == "":
            continue
        if not _is_ip(token) and _DNS.fullmatch(token) is None:
            raise SystemExit(f"{token!r} in PARENT_NAMES is not a DNS name or an IP address")
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(token)
    if not names:
        raise SystemExit(
            "PARENT_NAMES is empty; the parent listener needs a DNS name or an IP address"
        )
    return tuple(names)


def ensure_certificate(
    ca_dir: Path,
    names: tuple[str, ...] | list[str],
    now: datetime,
) -> tuple[Path, Path]:
    """Return the parent key and certificate, issuing a new pair when required.

    names are the configured DNS names and IP addresses. The private key and
    the certificate are written beside the household CA and nowhere else.
    """
    configured = tuple(names)
    if not configured:
        raise ValueError("the parent certificate needs a DNS name or an IP address")
    ca_cert, ca_key = _load_ca(ca_dir)
    cert_path = ca_dir / CERT_FILE
    key_path = ca_dir / KEY_FILE
    current = _load_leaf(cert_path, key_path)
    if (
        current is not None
        and _signed_by(current, ca_cert)
        and _covers(current, configured)
        and _still_good(current, now)
    ):
        return key_path, cert_path
    leaf_key, leaf = _issue(ca_cert, ca_key, configured, now)
    _write(
        key_path,
        leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        0o600,
    )
    _write(cert_path, leaf.public_bytes(serialization.Encoding.PEM), 0o644)
    return key_path, cert_path


def _load_ca(ca_dir: Path):
    path = ca_dir / CA_FILE
    if not path.is_file():
        raise FileNotFoundError(path)
    pem = path.read_bytes()
    if b"BEGIN CERTIFICATE" not in pem or b"PRIVATE KEY" not in pem:
        raise ValueError("the household CA file is not ready")
    return x509.load_pem_x509_certificate(pem), serialization.load_pem_private_key(
        _private_key_pem(pem), password=None
    )


def _private_key_pem(pem: bytes) -> bytes:
    for label in ("PRIVATE KEY", "RSA PRIVATE KEY", "EC PRIVATE KEY"):
        begin = f"-----BEGIN {label}-----".encode()
        start = pem.find(begin)
        if start == -1:
            continue
        end_marker = f"-----END {label}-----".encode()
        end = pem.find(end_marker, start)
        if end == -1:
            raise ValueError("the household CA key is truncated")
        return pem[start : end + len(end_marker)] + b"\n"
    raise ValueError("the household CA key is missing")


def _load_leaf(cert_path: Path, key_path: Path) -> x509.Certificate | None:
    if not cert_path.is_file() or not key_path.is_file():
        return None
    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    except (ValueError, TypeError):
        return None
    cert_public = cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    key_public = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    if cert_public != key_public:
        return None
    return cert


def _issue(ca_cert: x509.Certificate, ca_key, names: tuple[str, ...], now: datetime):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    moment = _utc_second(now)
    alternative: list[x509.GeneralName] = []
    common = names[0]
    for name in names:
        address = _ip_or_none(name)
        if address is None:
            alternative.append(x509.DNSName(name))
        else:
            alternative.append(x509.IPAddress(address))
            if common == names[0] and _ip_or_none(common) is not None:
                common = name
    for name in names:
        if _ip_or_none(name) is None:
            common = name
            break
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common)]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(moment)
        .not_valid_after(moment + VALIDITY)
        .add_extension(x509.SubjectAlternativeName(alternative), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


def _signed_by(cert: x509.Certificate, ca_cert: x509.Certificate) -> bool:
    if cert.issuer != ca_cert.subject:
        return False
    public = ca_cert.public_key()
    algorithm = cert.signature_hash_algorithm
    if algorithm is None:
        return False
    try:
        if isinstance(public, rsa.RSAPublicKey):
            public.verify(cert.signature, cert.tbs_certificate_bytes, padding.PKCS1v15(), algorithm)
        elif isinstance(public, ec.EllipticCurvePublicKey):
            public.verify(cert.signature, cert.tbs_certificate_bytes, ec.ECDSA(algorithm))
        else:
            return False
    except Exception:
        return False
    return True


def _covers(cert: x509.Certificate, names: tuple[str, ...]) -> bool:
    try:
        alternative = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return False
    dns = {item.lower() for item in alternative.get_values_for_type(x509.DNSName)}
    addresses = set(alternative.get_values_for_type(x509.IPAddress))
    for name in names:
        address = _ip_or_none(name)
        if address is None:
            if name.lower() not in dns:
                return False
        elif address not in addresses:
            return False
    return True


def _still_good(cert: x509.Certificate, now: datetime) -> bool:
    """Return whether more than 3 days of validity remain."""
    return cert.not_valid_after_utc - _utc_second(now) > RENEW_WITHIN


def _write(path: Path, data: bytes, mode: int) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def _is_ip(value: str) -> bool:
    return _ip_or_none(value) is not None


def _ip_or_none(value: str):
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _utc_second(moment: datetime) -> datetime:
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise ValueError("time must be an aware datetime")
    return moment.astimezone(timezone.utc).replace(microsecond=0)
