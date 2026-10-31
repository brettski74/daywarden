"""Run the decisions service.

Plain HTTP stays on port 8090 for the health check and the decision API.
Parent pages listen on PARENT_HTTPS_PORT (8443) once the household CA is
there to sign their certificate. Both listeners share one event loop, so
the SQLite connection stays on the thread that opened it.

An empty PARENT_NAMES stops the process before either port is opened.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import uvicorn

from policy.parent_tls import ensure_certificate, require_names


class _ParentServer(uvicorn.Server):
    """HTTPS listener. Signals stay with the HTTP server."""

    async def serve(self, sockets=None) -> None:
        await self._serve(sockets)


def main() -> None:
    names = require_names(os.environ.get("PARENT_NAMES"))
    # Imported after the name check so a missing name fails before the app loads.
    from policy.app import create_app

    app = create_app()
    http_port = int(os.environ.get("PORT", "8090"))
    https_port = int(os.environ.get("PARENT_HTTPS_PORT", "8443"))
    ca_dir = Path(os.environ.get("CA_DIR", "/var/lib/smartproxy/ca"))
    http = uvicorn.Server(
        uvicorn.Config(
            app,
            host="0.0.0.0",
            port=http_port,
            access_log=False,
            # The listener's own scheme is the scheme. A forwarded-proto
            # header must not turn a plain HTTP request into a parent page.
            proxy_headers=False,
        )
    )
    asyncio.run(_run(http, app, ca_dir, names, https_port))


async def _run(http: uvicorn.Server, app, ca_dir: Path, names: tuple[str, ...], port: int) -> None:
    parent: dict[str, uvicorn.Server | None] = {"server": None}
    original = http.handle_exit

    def handle_exit(sig, frame) -> None:
        original(sig, frame)
        peer = parent["server"]
        if peer is not None:
            peer.should_exit = True
            peer.force_exit = http.force_exit

    http.handle_exit = handle_exit  # type: ignore[method-assign]
    listener = asyncio.create_task(_parent_listener(http, app, ca_dir, names, port, parent))
    try:
        await http.serve()
    finally:
        peer = parent["server"]
        if peer is not None:
            peer.should_exit = True
        listener.cancel()
        await asyncio.gather(listener, return_exceptions=True)


async def _parent_listener(http, app, ca_dir: Path, names: tuple[str, ...], port: int, parent: dict) -> None:
    announced = False
    while not http.should_exit:
        try:
            key_path, cert_path = ensure_certificate(ca_dir, names, datetime.now(timezone.utc))
        except FileNotFoundError:
            if not announced:
                print("parent listener is waiting for the household CA", flush=True)
                announced = True
            await asyncio.sleep(1)
            continue
        except (OSError, ValueError) as exc:
            print(f"parent certificate was not issued: {exc}", flush=True)
            await asyncio.sleep(1)
            continue
        print(f"parent pages listen on {port}", flush=True)
        server = _ParentServer(
            uvicorn.Config(
                app,
                host="0.0.0.0",
                port=port,
                ssl_certfile=str(cert_path),
                ssl_keyfile=str(key_path),
                access_log=False,
                proxy_headers=False,
                # The plain HTTP server already ran the application startup.
                lifespan="off",
            )
        )
        parent["server"] = server
        await server.serve()
        return


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
