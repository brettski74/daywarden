"""Placeholder pages that share the parent session.

The attempt review lists parent_check passes recorded from this service.
Quiz stories replace the revision page. Neither page is the usage report.
A parent_check is recorded only after a valid session has been accepted.
"""

from __future__ import annotations

from datetime import datetime
from collections.abc import Mapping

from policy.accounts import Accounts
from policy.report import PageResponse, _closed_page, _document, _e, _response, _sign_in_page, open_parent

QUIZ_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Revision</title>
</head>
<body>
<h1>Revision</h1>
<p>This is a revision task.</p>
</body>
</html>
"""


def respond_attempts(
    accounts: Accounts,
    *,
    method: str,
    query: Mapping[str, str],
    cookie: str | None,
    form: Mapping[str, str],
    now: datetime,
) -> PageResponse:
    """Return the attempt list, the sign-in form, or the closed page."""
    denied = open_parent(
        accounts,
        method=method,
        query=query,
        cookie=cookie,
        form=form,
        now=now,
        keys=(),
        title="Attempts",
        home="/attempts",
    )
    if denied is not None:
        return denied
    return _response(200, _attempts_body(accounts))


def respond_parent_check(
    accounts: Accounts,
    *,
    cookie: str | None,
    form: Mapping[str, str],
    now: datetime,
) -> PageResponse:
    """Record a parent_check pass when the session is valid.

    A missing or expired session returns the sign-in form and writes nothing.
    """
    if accounts.count() == 0:
        return _response(403, _closed_page("Attempts"))
    if accounts.accept(cookie, now) is None:
        return _response(
            200,
            _sign_in_page({}, rejected=False, keys=(), title="Attempts", home="/attempts"),
        )
    client = form.get("client", "")
    if isinstance(client, str) and client.strip():
        accounts.record_parent_check(client.strip(), now)
    return _response(200, _attempts_body(accounts))


def https_only_page() -> str:
    """Return the refusal for a parent page that did not arrive over HTTPS."""
    return _document(
        "<h1>Parent pages</h1>\n<p>Open this page over HTTPS.</p>",
        "Parent pages",
    )


def _attempts_body(accounts: Accounts) -> str:
    rows = accounts.parent_checks()
    if rows:
        listed = "\n".join(
            f"<li>{_e(client)} at {_e(recorded)}</li>" for client, recorded in rows
        )
        listing = f"<ul>\n{listed}\n</ul>"
    else:
        listing = "<p>No attempts yet.</p>"
    form = (
        '<form method="post" action="/attempts/parent-check">\n'
        '<label for="client">Client group</label>\n'
        '<input id="client" name="client">\n'
        '<button type="submit">Record a pass</button>\n'
        "</form>"
    )
    return _document(
        "<h1>Attempts</h1>\n"
        f"{listing}\n"
        "<h2>Record a parent check</h2>\n"
        f"{form}",
        "Attempts",
    )
