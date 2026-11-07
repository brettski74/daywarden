"""The page a computer was sent away from, and the way back to it.

A page load that the rules sent to ``revision_task`` is remembered for the
computer that asked, by its normalized address. Only a ``GET`` is a page
load, and only when ``Sec-Fetch-Dest`` is ``document``, or when there is no
``Sec-Fetch-Dest`` and ``Accept`` includes ``text/html``. A request for the
policy server itself is never remembered. Each computer keeps only its
last such page.

The page is forgotten when the proxy allows that exact URL for that
computer. A page remembered on an earlier household day is not used.

When a quiz passes, ``way_back`` decides the remembered page again for that
address. An allow is where the "Well done" screen sends him back to.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from policy.clients import normalize_ip
from policy.engine import Ledger, Trace, judge
from policy.hierarchy import Policy
from policy.selection import same_task_site
from policy.tasks import household_day

SCHEMA = """
CREATE TABLE IF NOT EXISTS return_pages (
    client_ip TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    household_day TEXT NOT NULL,
    remembered_at TEXT NOT NULL
);
"""


def is_page_load(method: str, sec_fetch_dest: str | None, accept: str | None) -> bool:
    """Return whether this request is a browser opening a page, not a fetch the page makes."""
    if method.upper() != "GET":
        return False
    if sec_fetch_dest is not None:
        return sec_fetch_dest.strip().lower() == "document"
    if accept is None:
        return False
    return any(part.split(";", 1)[0].strip().lower() == "text/html" for part in accept.split(","))


class ReturnPages:
    """One remembered URL for each computer, kept in the policy database."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        connection.executescript(SCHEMA)

    def remember(self, client_ip: str, url: str, at: datetime) -> None:
        address = normalize_ip(client_ip)
        if address is None:
            return
        with self.connection:
            self.connection.execute(
                "INSERT INTO return_pages (client_ip, url, household_day, remembered_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(client_ip) DO UPDATE SET url = excluded.url, "
                "household_day = excluded.household_day, remembered_at = excluded.remembered_at",
                (address, url, household_day(at).isoformat(), at.isoformat()),
            )

    def forget(self, client_ip: str, url: str) -> None:
        """Forget this computer's page when it is url."""
        address = normalize_ip(client_ip)
        if address is None:
            return
        with self.connection:
            self.connection.execute(
                "DELETE FROM return_pages WHERE client_ip = ? AND url = ?",
                (address, url),
            )

    def recall(self, client_ip: str, at: datetime) -> str | None:
        """Return the page remembered for this computer on the household day of at, or None."""
        address = normalize_ip(client_ip)
        if address is None:
            return None
        row = self.connection.execute(
            "SELECT url, household_day FROM return_pages WHERE client_ip = ?",
            (address,),
        ).fetchone()
        if row is None or row[1] != household_day(at).isoformat():
            return None
        return row[0]

    def note(
        self,
        policy: Policy,
        trace: Trace,
        *,
        client_ip: str,
        method: str,
        url: str,
        sec_fetch_dest: str | None,
        accept: str | None,
        at: datetime,
    ) -> None:
        """Remember or forget the page after the proxy has been told what to do with this request."""
        action = trace.decision.get("action")
        if action == "allow":
            self.forget(client_ip, url)
            return
        if (
            action == "redirect"
            and trace.revision
            and is_page_load(method, sec_fetch_dest, accept)
            and not same_task_site(url, policy)
        ):
            self.remember(client_ip, url, at)


def way_back(
    policy: Policy,
    pages: ReturnPages,
    ledger: Ledger,
    client_ip: str,
    at: datetime,
) -> str | None:
    """Return the remembered page when the rules would let this computer open it now, or None.

    This is the decision the proxy would make for that page, without moving
    on the task rotation that a redirect would use.
    """
    url = pages.recall(client_ip, at)
    if url is None:
        return None
    trace, _assumption = judge(policy, client_ip=client_ip, url=url, at=at, ledger=ledger)
    if trace.decision.get("action") != "allow":
        return None
    return url
