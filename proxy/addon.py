"""Ask the decision service, then allow, refuse, or redirect the request."""

from __future__ import annotations

import html
import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path

from mitmproxy import ctx
from mitmproxy import http

import bypass
import decision

DECISION_URL = os.environ.get("DECISION_URL", "http://decisions:8090/v1/decisions")
BYPASS_PATH = Path(os.environ.get("BYPASS_PATH", "/etc/smartproxy/bypass.txt"))
TIMEOUT = float(os.environ.get("DECISION_TIMEOUT", "2"))

_UNAVAILABLE = object()
_UNRECOGNIZED = object()


class DecisionEnforcer:
    def http_connect(self, flow: http.HTTPFlow) -> None:
        """Leave the tunnel response to mitmproxy.

        A browser applies a redirect to the decrypted request inside the
        tunnel. The CONNECT response stays the tunnel acknowledgement.
        """
        return

    def requestheaders(self, flow: http.HTTPFlow) -> None:
        try:
            self._enforce(flow)
        except Exception as exc:
            ctx.log.error(f"decision enforcement failed: {exc}")
            flow.response = _deny_page(decision.UNAVAILABLE_MESSAGE)

    def _enforce(self, flow: http.HTTPFlow) -> None:
        if flow.request.method.upper() == "CONNECT":
            return
        host = flow.request.pretty_host
        if bypass.is_bypassed(host, bypass.load_patterns(BYPASS_PATH)):
            ctx.log.info(f"bypass {flow.request.method} {host}")
            return
        outcome = _ask(flow)
        if outcome is _UNAVAILABLE:
            flow.response = _deny_page(decision.UNAVAILABLE_MESSAGE)
            return
        if outcome is _UNRECOGNIZED or not isinstance(outcome, dict):
            flow.response = _deny_page(decision.UNRECOGNIZED_MESSAGE)
            return
        action = outcome["action"]
        if action == "allow":
            ctx.log.info(f"allow {flow.request.method} {host}")
            return
        if action == "deny":
            ctx.log.info(f"deny {flow.request.method} {host}")
            flow.response = _deny_page(outcome["message"])
            return
        ctx.log.info(f"redirect {flow.request.method} {host}")
        flow.response = http.Response.make(
            302,
            "",
            {
                "Location": outcome["location"],
                "Cache-Control": "no-store",
            },
        )


def _ask(flow: http.HTTPFlow):
    peer = flow.client_conn.peername
    if not peer or not peer[0]:
        ctx.log.warn("decision skipped: missing client address")
        return _UNAVAILABLE
    payload = {
        "client_ip": peer[0],
        "method": flow.request.method,
        "url": flow.request.pretty_url.split("#", 1)[0],
        "occurred_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    request = urllib.request.Request(
        DECISION_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read()
            status = response.status
    except Exception as exc:
        ctx.log.warn(f"decision request failed: {exc}")
        return _UNAVAILABLE
    if status != 200:
        ctx.log.warn(f"decision service returned HTTP {status}")
        return _UNRECOGNIZED
    try:
        document = json.loads(body)
    except json.JSONDecodeError:
        ctx.log.warn("decision service returned a body that is not JSON")
        return _UNRECOGNIZED
    recognized = decision.recognize(document)
    if recognized is None:
        ctx.log.warn("decision service returned an unrecognized decision")
        return _UNRECOGNIZED
    return recognized


def _deny_page(message: str) -> http.Response:
    body = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        "<title>Not allowed</title>\n"
        "</head>\n"
        "<body>\n"
        f"<p>{html.escape(message)}</p>\n"
        "</body>\n"
        "</html>\n"
    )
    return http.Response.make(
        403,
        body,
        {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-store",
        },
    )


addons = [DecisionEnforcer()]
