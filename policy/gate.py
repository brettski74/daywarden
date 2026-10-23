"""Temporary parent gate for the usage report.

S007.1 replaces this with parent sign-in. Until then the report stays closed
unless PARENT_PASSWORD is set on the decisions service. The password lives in
that environment. It is not written into the policy file and it is not stored
in SQLite.
"""

from __future__ import annotations

import hashlib
import hmac

COOKIE_NAME = "parent_session"
_TOKEN = b"smartproxy-parent"


class ParentGate:
    def __init__(self, password: str | None) -> None:
        self._password = "" if password is None else password

    @property
    def configured(self) -> bool:
        return self._password != ""

    def accepts_password(self, offered: str) -> bool:
        """Return whether offered is the configured password.

        A missing password never matches, so the report cannot be opened by
        submitting an empty form while the gate is unset.
        """
        if not self.configured or not isinstance(offered, str):
            return False
        return hmac.compare_digest(
            hashlib.sha256(offered.encode()).digest(),
            hashlib.sha256(self._password.encode()).digest(),
        )

    def token(self) -> str:
        """Return the session cookie value for the current password."""
        return hmac.new(self._password.encode(), _TOKEN, hashlib.sha256).hexdigest()

    def accepts_cookie(self, value: str | None) -> bool:
        """Return whether value is the session cookie for the current password."""
        if not self.configured or not isinstance(value, str) or not value:
            return False
        expected = self.token()
        if len(value) != len(expected):
            return False
        return hmac.compare_digest(value, expected)

    def cookie_header(self) -> str:
        """Return a session cookie that ends when the browser closes."""
        return f"{COOKIE_NAME}={self.token()}; HttpOnly; SameSite=Lax; Path=/usage"


def cookie_value(header: str | None, name: str) -> str | None:
    """Return the value of name in a Cookie header, or None when it is absent."""
    if not header:
        return None
    prefix = name + "="
    for part in header.split(";"):
        item = part.strip()
        if item.startswith(prefix):
            return item[len(prefix) :]
    return None
