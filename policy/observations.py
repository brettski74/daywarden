"""POST /v1/observations writes the usage ledger.

The proxy reports body bytes here after it has forwarded a request. The
report is filed once under the classified client group and site group,
including ``default``, and again under each quota whose rule set accepts it.
That path is ``policy.usage``. A report with no new bytes is accepted and
ignored, and so is every report while no policy is loaded.

None of these are turned into a refusal. The proxy has already forwarded the
response, and a failure of this call must not become a 403, a 302, or a cut.
A report cuts the transfer only when that flow's recorded allow has reached
a clock deadline or a volume ceiling, and the access rules no longer allow
it. Any other answer leaves the transfer running.

A POLICY_FILE that does not end in .yaml or .yml stops the service.

Run with: python -m policy.observations
"""
from __future__ import annotations

import json
import os
import signal
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from policy.clock import HouseholdClock, machine_zone, named_zone
from policy.hierarchy import Policy, load as load_hierarchy, require_yaml
from policy.store import PolicyStore
from policy.usage import UsageStore, cut_required, file_report

# The only instruction the proxy treats as a cut. An empty body is not one.
CUT_BODY = b'{"action":"cut"}'

LOG_PATH = Path(os.environ.get("OBSERVATION_LOG", "/tmp/observations.jsonl"))
PORT = int(os.environ.get("OBSERVATION_PORT", "8091"))
_LOG_LOCK = threading.Lock()


def status_for(policy: Policy | None, usage: UsageStore, body: bytes) -> tuple[int, bytes]:
    """Return the status and body for one observation.

    The report is filed by ``file_report``. The answer is ``{"action":"cut"}``
    when the flow named on the report has a recorded allow whose deadline or
    volume ceiling has been reached, and the access rules no longer allow it.
    Otherwise the answer is 204 with an empty body, including a report that
    names no flow, a flow that was not allowed here, a report that matches
    nothing, and a ledger with no policy loaded. An empty body is not an
    instruction to cut the transfer. A malformed report raises ValueError.
    """
    try:
        document = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("an observation is a JSON object") from exc
    if policy is not None:
        flow_id = _flow_id(document)
        filing = file_report(policy, usage, _clock_for(policy), document)
        if filing is not None and cut_required(policy, usage, filing, flow_id):
            return 200, CUT_BODY
    return 204, b""


def listen(
    policy: Policy | None,
    usage: UsageStore,
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
                    code, payload = 404, b"not found"
                else:
                    try:
                        code, payload = status_for(policy, usage, raw)
                    except ValueError as exc:
                        print(f"observation rejected: {exc}", flush=True)
                        code, payload = 400, b""
                    except Exception as exc:
                        print(f"observation failed: {exc}", flush=True)
                        code, payload = 500, b""
                    else:
                        if payload == CUT_BODY:
                            print(f"observation cut {url}", flush=True)
            self._send(code, payload)

        def _send(self, status: int, body: bytes) -> None:
            if body == CUT_BODY:
                content_type = "application/json"
            else:
                content_type = "text/plain; charset=utf-8"
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    database = Path(os.environ.get("POLICY_DB", "/var/lib/daywarden/policy.sqlite3"))
    policy = _load_policy(Path(os.environ.get("POLICY_FILE", "/etc/daywarden/policy.yaml")))
    database.parent.mkdir(parents=True, exist_ok=True)
    store = PolicyStore(database, check_same_thread=False)
    server = listen(policy, UsageStore(connection=store.connection))
    # Exit 0 on docker stop. A container that exits non-zero when Docker
    # shuts down is started again by an on-failure restart policy at boot.
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    print(f"observation ledger listening on {PORT}", flush=True)
    server.serve_forever()
    server.server_close()


def _load_policy(path: Path) -> Policy | None:
    """Return the household policy, or None when the file is missing.

    The decisions service is what installs a new bucket length.
    """
    require_yaml(path)
    if not path.is_file():
        print(f"{path} not found; observations are not recorded", flush=True)
        return None
    print(f"loading {path}", flush=True)
    return load_hierarchy(path, task_data=False)


def _clock_for(policy: Policy) -> HouseholdClock:
    if policy.timezone:
        return HouseholdClock(named_zone(policy.timezone))
    localtime = Path(os.environ.get("MACHINE_LOCALTIME", "/etc/localtime"))
    return HouseholdClock(machine_zone(localtime=localtime))


def _flow_id(document: object) -> str | None:
    """Return the flow id, or None when the report does not name one."""
    if not isinstance(document, dict) or "flow_id" not in document or document["flow_id"] is None:
        return None
    flow_id = document["flow_id"]
    if not isinstance(flow_id, str) or not flow_id:
        raise ValueError("flow_id must be a string")
    return flow_id


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
