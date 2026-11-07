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

POST /v1/reload loads POLICY_FILE again and swaps it in whole. Each report
reads the policy once, so it is filed and judged under one policy. Running
transfers keep the deadline and the ceiling recorded when they were allowed.
A policy with errors is refused and the one in force stays. Only a request
from inside this container is accepted. Any other peer gets 404.

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

from policy.check import load_required
from policy.clock import HouseholdClock, machine_zone, named_zone
from policy.hierarchy import ConfigError, Policy, load as load_hierarchy, require_yaml
from policy.store import PolicyStore
from policy.usage import UsageStore, cut_required, file_report

# The only instruction the proxy treats as a cut. An empty body is not one.
CUT_BODY = b'{"action":"cut"}'

LOG_PATH = Path(os.environ.get("OBSERVATION_LOG", "/tmp/observations.jsonl"))
PORT = int(os.environ.get("OBSERVATION_PORT", "8091"))
LOOPBACK = frozenset({"127.0.0.1", "::1"})
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
    policy_file: Path | None = None,
) -> ThreadingHTTPServer:
    """Serve /health, /v1/observations, and /v1/reload. The returned server is not started.

    Without ``policy_file`` there is nothing to reload, and /v1/reload is 404.
    """
    destination = log_path if log_path is not None else LOG_PATH
    lock = threading.Lock()
    current = {"policy": policy}

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
            if path == "/v1/reload":
                self._reload()
                return
            recorded = _document(raw)
            with lock:
                policy = current["policy"]
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

        def _reload(self) -> None:
            if policy_file is None or self.client_address[0] not in LOOPBACK:
                self._send(404, b"not found")
                return
            warnings: list[str] = []
            with lock:
                try:
                    current["policy"] = load_required(
                        policy_file, current["policy"], warn=warnings.append, task_data=False
                    )
                except ConfigError as error:
                    print(f"reload refused: the policy has {len(error.problems)} errors", flush=True)
                    answer = {"reloaded": False, "errors": list(error.problems), "warnings": warnings}
                else:
                    print(f"reloaded {policy_file}", flush=True)
                    answer = {"reloaded": True, "warnings": warnings}
            self._send(200, json.dumps(answer).encode(), "application/json")

        def _send(self, status: int, body: bytes, content_type: str | None = None) -> None:
            if content_type is None:
                content_type = "application/json" if body == CUT_BODY else "text/plain; charset=utf-8"
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
    policy_file = Path(os.environ.get("POLICY_FILE", "/etc/daywarden/policy.yaml"))
    policy = _load_policy(policy_file)
    database.parent.mkdir(parents=True, exist_ok=True)
    store = PolicyStore(database, check_same_thread=False)
    server = listen(policy, UsageStore(connection=store.connection), policy_file=policy_file)
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
    try:
        return load_hierarchy(path, task_data=False)
    except ConfigError as error:
        print(f"the policy has {len(error.problems)} errors", flush=True)
        for problem in error.problems:
            print(problem, flush=True)
        raise


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
