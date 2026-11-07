#!/usr/bin/env python3
"""Test decision service. Answers every decision with the document a test wrote.

tests/stub-decisions.compose.yml runs this in place of the decisions service,
so a proxy test can hand the addon any decision, including documents the
rule engine never produces. The answer is the bytes of DECISION_DOCUMENT,
read on each request, as they are. A missing file is a 500. Each request is
appended to DECISION_LOG with the decision that was answered.
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DOCUMENT = Path(os.environ.get("DECISION_DOCUMENT", "/etc/daywarden/next-decision.json"))
LOG_PATH = Path(os.environ.get("DECISION_LOG", "/tmp/decisions.jsonl"))
PORT = int(os.environ.get("PORT", "8090"))
_LOG_LOCK = threading.Lock()


def _json(raw: bytes) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw.decode("utf-8", "replace")}


def _append_log(document: dict) -> None:
    line = json.dumps(document, separators=(",", ":")) + "\n"
    with _LOG_LOCK:
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == "/health":
            self._send(200, b"ok", "text/plain; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b""
        if self.path.split("?", 1)[0] != "/v1/decisions":
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        answer = DOCUMENT.read_bytes() if DOCUMENT.is_file() else None
        _append_log({"request": _json(raw), "decision": None if answer is None else _json(answer)})
        if answer is None:
            self._send(500, b"missing decision", "text/plain; charset=utf-8")
        else:
            self._send(200, answer, "application/json")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        return


def main() -> None:
    print(f"stub decision service listening on {PORT}; answers {DOCUMENT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
