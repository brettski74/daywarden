"""Commands to a running service through a Unix socket.

A service answers one-line commands, such as ``reload``, with one line of
JSON. The socket is a file, so no request to any port can reach it. In the
Compose stack the observations and auto-configuration services put theirs
in a directory that only the stack's own containers mount, so ``dw reload``
reaches each one with ``docker compose exec``, and a parent portal save in
the decisions service reaches them too. Nothing on the household network,
and nothing the proxy forwards, can.
"""

from __future__ import annotations

import json
import os
import socket
import socketserver
from collections.abc import Callable, Mapping
from pathlib import Path

Command = Callable[[], dict]


def serve(path: Path, commands: Mapping[str, Command]) -> socketserver.UnixStreamServer:
    """Answer each command in ``commands`` on a Unix socket at ``path``. Not started."""

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            command = self.rfile.readline(64).decode("ascii", "replace").strip()
            run = commands.get(command)
            answer = {"error": f"unknown command {command!r}"} if run is None else run()
            self.wfile.write(json.dumps(answer).encode() + b"\n")

    path.unlink(missing_ok=True)
    server = socketserver.ThreadingUnixStreamServer(str(path), Handler)
    server.daemon_threads = True
    return server


def ask(command: str, path: Path, timeout: float = 60, *, service: str = "service") -> dict:
    """Send one command to a running service and return its answer."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(path))
        client.sendall(command.encode("ascii") + b"\n")
        with client.makefile("rb") as answer:
            line = answer.readline()
    if not line:
        raise OSError(f"the {service} closed the connection without an answer")
    return json.loads(line)


def socket_path(variable: str) -> Path | None:
    """Return the socket path an environment variable names, or None when it is not set."""
    value = os.environ.get(variable, "").strip()
    return Path(value) if value else None
