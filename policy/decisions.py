"""POST /v1/decisions, without the HTTP framework.

``parse_request`` reads what the proxy addon sent. The household policy
decides it in ``policy.engine``. Each request is appended to the decision
log, including one that was refused because it was malformed.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from policy.clients import normalize_ip


@dataclass(frozen=True)
class DecisionRequest:
    client_ip: str
    method: str
    url: str
    occurred_at: datetime | None
    flow_id: str | None = None
    sec_fetch_dest: str | None = None
    accept: str | None = None


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
    flow_id = document.get("flow_id")
    if flow_id is not None and (not isinstance(flow_id, str) or not flow_id):
        raise ValueError("flow_id must be a string")
    headers = {}
    for key in ("sec_fetch_dest", "accept"):
        value = document.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        headers[key] = value
    return DecisionRequest(client_ip, document["method"], document["url"], moment, flow_id, **headers)


def log_entry(raw: object) -> dict:
    """Record a request that was refused before any rule was tried."""
    return {"request": raw, "decision": None}


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
