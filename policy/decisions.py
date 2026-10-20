"""POST /v1/decisions, without the HTTP framework.

Every request is judged by the household rules, whether or not its source IP
belongs to a client. The client only supplies a name now, and later the tasks
and usage that belong to that computer. A URL that is in no site group is
denied. Until the rule engine exists, every site group answers with the single
decision in DECISION_FILE.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from policy.clients import Client, ClientDirectory, normalize_ip
from policy.clock import HouseholdClock
from policy.groups import SiteGroup, SiteGroups

UNGROUPED_MESSAGE = "This site is not in a configured group."


@dataclass(frozen=True)
class DecisionRequest:
    client_ip: str
    method: str
    url: str
    occurred_at: datetime | None


@dataclass(frozen=True)
class DecisionContext:
    request: DecisionRequest
    client: Client | None
    local_time: datetime
    group: SiteGroup | None


def parse_request(document: object) -> DecisionRequest:
    """Return the request the addon sent. Raise ValueError when it is malformed."""
    if not isinstance(document, dict):
        raise ValueError("a decision request is a JSON object")
    client_ip = document.get("client_ip")
    if not isinstance(client_ip, str) or normalize_ip(client_ip) is None:
        raise ValueError("client_ip must be an IP address")
    for key in ("method", "url"):
        if not isinstance(document.get(key), str) or not document[key]:
            raise ValueError(f"{key} is required")
    occurred_at = document.get("occurred_at")
    if occurred_at is None:
        moment = None
    elif isinstance(occurred_at, str):
        try:
            moment = datetime.fromisoformat(occurred_at)
        except ValueError as exc:
            raise ValueError("occurred_at must be an ISO 8601 time") from exc
    else:
        raise ValueError("occurred_at must be an ISO 8601 time")
    return DecisionRequest(client_ip, document["method"], document["url"], moment)


def context_for(
    request: DecisionRequest,
    clock: HouseholdClock,
    directory: ClientDirectory,
    groups: SiteGroups,
) -> DecisionContext:
    """Attach the client and site group, if any, and the household-local time of the request."""
    return DecisionContext(
        request,
        directory.find(request.client_ip),
        clock.local(request.occurred_at),
        groups.classify(request.url),
    )


def decide(context: DecisionContext, decision_file: Path) -> bytes | None:
    """Deny a URL in no site group. Otherwise answer with the household decision."""
    if context.group is None:
        return json.dumps({"action": "deny", "status": 403, "message": UNGROUPED_MESSAGE}).encode()
    return household_decision(decision_file)


def household_decision(decision_file: Path) -> bytes | None:
    """Return the configured decision, or None when the file is missing."""
    if not decision_file.is_file():
        return None
    return decision_file.read_bytes()


def log_entry(raw: object, context: DecisionContext | None, decision: bytes | None) -> dict:
    """Record what the addon sent, who it was for, its site group, and what was answered."""
    try:
        answered = json.loads(decision) if decision is not None else None
    except json.JSONDecodeError:
        answered = {"raw": decision.decode("utf-8", "replace")}
    return {
        "request": raw,
        "client": context.client.name if context and context.client else None,
        "local_time": context.local_time.isoformat() if context else None,
        "group": context.group.name if context and context.group else None,
        "decision": answered,
    }


class DecisionLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def append(self, entry: dict) -> None:
        line = json.dumps(entry, separators=(",", ":")) + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
