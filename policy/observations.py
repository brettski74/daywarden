"""POST /v1/observations writes the usage ledger.

The proxy reports body bytes here after it has forwarded a request. The URL
is matched to a site group the same way a decision is. A match marks the
bucket that contains the report's time, for that client, and adds the bytes.
A URL in no group, and no default group, is accepted and ignored. So is a
client the household has not enrolled, and a report with no new bytes. None
of those are errors: the proxy has already allowed the response, and a
failure of this call must not turn it into a 403 or a 302.

Run with: python -m policy.observations
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from policy.clients import ClientDirectory, normalize_ip
from policy.clock import HouseholdClock, machine_zone, named_zone
from policy.groups import SiteGroups
from policy.store import PolicyStore

LOG_PATH = Path(os.environ.get("OBSERVATION_LOG", "/tmp/observations.jsonl"))
PORT = int(os.environ.get("OBSERVATION_PORT", "8091"))
_LOG_LOCK = threading.Lock()


def record(store: PolicyStore, clock: HouseholdClock, document: object) -> bool:
    """Mark the bucket this observation falls in. Return False when it is ignored.

    Ignored means the client is not enrolled, the URL is in no group, or no
    bytes moved. The caller still answers success. A malformed report raises
    ValueError.
    """
    if not isinstance(document, dict):
        raise ValueError("an observation is a JSON object")
    client_ip = document.get("client_ip")
    if not isinstance(client_ip, str) or normalize_ip(client_ip) is None:
        raise ValueError("client_ip must be an IP address")
    url = document.get("url")
    if not isinstance(url, str) or not url:
        raise ValueError("url is required")
    occurred_at = document.get("occurred_at")
    if not isinstance(occurred_at, str):
        raise ValueError("occurred_at must be an ISO 8601 time")
    try:
        moment = datetime.fromisoformat(occurred_at)
    except ValueError as exc:
        raise ValueError("occurred_at must be an ISO 8601 time") from exc
    nbytes = document.get("bytes")
    if isinstance(nbytes, bool) or not isinstance(nbytes, int) or nbytes < 0:
        raise ValueError("bytes is a whole number, zero or more")
    if nbytes == 0:
        return False
    client = ClientDirectory(store.clients()).find(client_ip)
    if client is None:
        return False
    group = SiteGroups(store.groups()).classify(url)
    if group is None:
        return False
    start, length = store.bucket_for(clock.local(moment))
    store.mark_bucket(
        client.id,
        group.name,
        start,
        length_seconds=length,
        byte_count=nbytes,
    )
    return True


def status_for(store: PolicyStore, body: bytes) -> int:
    """Return 204 after recording the body, or ignoring a report that matches nothing."""
    try:
        document = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("an observation is a JSON object") from exc
    record(store, _clock(store), document)
    return 204


def listen(
    store: PolicyStore,
    host: str = "0.0.0.0",
    port: int = PORT,
    log_path: Path | None = None,
) -> ThreadingHTTPServer:
    """Serve /health and /v1/observations. The returned server is not started."""
    destination = log_path if log_path is not None else LOG_PATH
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            if self.path.split("?", 1)[0] != "/health":
                self._send(404, b"not found")
                return
            self._send(200, b"ok")

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b""
            path = self.path.split("?", 1)[0]
            recorded = _document(raw)
            with lock:
                _append_log(destination, recorded)
                url = recorded.get("url", "?")
                nbytes = recorded.get("bytes", "?")
                print(f"observation {nbytes} {url}", flush=True)
                if path != "/v1/observations":
                    code = 404
                else:
                    try:
                        code = status_for(store, raw)
                    except ValueError as exc:
                        print(f"observation rejected: {exc}", flush=True)
                        code = 400
                    except Exception as exc:
                        print(f"observation failed: {exc}", flush=True)
                        code = 500
            self._send(code, b"")

        def _send(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    database = Path(os.environ.get("POLICY_DB", "/var/lib/smartproxy/policy.sqlite3"))
    database.parent.mkdir(parents=True, exist_ok=True)
    store = PolicyStore(database, check_same_thread=False)
    server = listen(store)
    print(f"observation ledger listening on {PORT}", flush=True)
    server.serve_forever()


def _clock(store: PolicyStore) -> HouseholdClock:
    name = store.timezone()
    if name:
        return HouseholdClock(named_zone(name))
    localtime = Path(os.environ.get("MACHINE_LOCALTIME", "/etc/localtime"))
    return HouseholdClock(machine_zone(localtime=localtime))


def _document(raw: bytes) -> dict:
    try:
        recorded = json.loads(raw) if raw else {}
        if not isinstance(recorded, dict):
            recorded = {"raw": raw.decode("utf-8", "replace")}
    except json.JSONDecodeError:
        recorded = {"raw": raw.decode("utf-8", "replace")}
    recorded["received_at"] = datetime.now().astimezone().isoformat(timespec="milliseconds")
    return recorded


def _append_log(path: Path, document: dict) -> None:
    line = json.dumps(document, separators=(",", ":")) + "\n"
    with _LOG_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())


if __name__ == "__main__":
    main()
