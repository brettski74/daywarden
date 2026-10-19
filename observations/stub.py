#!/usr/bin/env python3
"""Temporary observation API.

Each POST /v1/observations is appended to OBSERVATION_LOG.
S002.1 replaces this process. The request path stays POST /v1/observations.
A failure here must not change a proxy decision; the addon ignores errors.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOG_PATH = Path(os.environ.get("OBSERVATION_LOG", "/tmp/observations.jsonl"))
PORT = int(os.environ.get("STUB_PORT", "8091"))
_LOG_LOCK = threading.Lock()


def append_log(document: dict) -> None:
    line = json.dumps(document, separators=(",", ":")) + "\n"
    with _LOG_LOCK:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] != "/health":
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        self._send(200, b"ok", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b""
        try:
            recorded = json.loads(raw)
            if not isinstance(recorded, dict):
                recorded = {"raw": raw.decode("utf-8", "replace")}
        except json.JSONDecodeError:
            recorded = {"raw": raw.decode("utf-8", "replace")}
        recorded["received_at"] = datetime.now().astimezone().isoformat(timespec="milliseconds")
        append_log(recorded)
        url = recorded.get("url", "?")
        nbytes = recorded.get("bytes", "?")
        print(f"observation {nbytes} {url}", flush=True)
        if self.path.split("?", 1)[0] != "/v1/observations":
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        self._send(204, b"", "text/plain; charset=utf-8")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"observation stub listening on {PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
