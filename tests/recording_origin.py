#!/usr/bin/env python3
"""Test origin. Records each request it actually receives."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

LOG_PATH = Path(os.environ.get("ORIGIN_LOG", "/tmp/origin.jsonl"))
_LOG_LOCK = threading.Lock()


def append_log(document: dict) -> None:
    line = json.dumps(document, separators=(",", ":")) + "\n"
    with _LOG_LOCK:
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else b""
        path = self.path
        host = self.headers.get("Host", "")
        append_log(
            {
                "method": self.command,
                "path": path,
                "host": host,
                "client": self.headers.get("X-Daywarden-Client"),
                "body_len": len(body),
            }
        )
        print(f"origin {self.command} {host} {path} {len(body)}", flush=True)
        route = urlsplit(path).path
        if route == "/drip":
            self._drip(parse_qs(urlsplit(path).query))
            return
        if route == "/hold":
            self._hold(parse_qs(urlsplit(path).query))
            return
        payload = f"daywarden-origin-ok {path}".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _drip(self, query: dict) -> None:
        """Write a body slowly enough that a short reporting interval elapses."""
        seconds = _bounded(query, "seconds", 4.0)
        chunk = b"x" * 200
        sent = 0
        self._begin_chunks()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self._write_chunk(chunk)
            sent += len(chunk)
            time.sleep(0.2)
        self._end_chunks()
        self._event("finished", sent)

    def _hold(self, query: dict) -> None:
        """Send bytes, then keep the response open without sending any more."""
        active = _bounded(query, "active", 2.0)
        pause = _bounded(query, "pause", 5.0)
        chunk = b"z" * 250
        sent = 0
        self._begin_chunks()
        deadline = time.monotonic() + active
        while time.monotonic() < deadline:
            self._write_chunk(chunk)
            sent += len(chunk)
            time.sleep(0.1)
        self._event("idle", sent)
        time.sleep(pause)
        self._end_chunks()
        self._event("finished", sent)

    def _begin_chunks(self) -> None:
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _write_chunk(self, data: bytes) -> None:
        self.wfile.write(f"{len(data):x}\r\n".encode("ascii") + data + b"\r\n")
        self.wfile.flush()

    def _end_chunks(self) -> None:
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def _event(self, event: str, sent: int) -> None:
        append_log(
            {
                "event": event,
                "path": self.path,
                "bytes": sent,
                "at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            }
        )

    def log_message(self, fmt: str, *args) -> None:
        return


def _bounded(query: dict, name: str, default: float) -> float:
    raw = query.get(name, [str(default)])[0]
    try:
        value = float(raw)
    except ValueError:
        return default
    return min(max(value, 0.0), 30.0)


def main() -> None:
    ThreadingHTTPServer(("0.0.0.0", 80), Handler).serve_forever()


if __name__ == "__main__":
    main()
