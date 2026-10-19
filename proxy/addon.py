"""Ask the decision service, then allow, refuse, or redirect the request.

Forwarded flows also report body bytes to the observation service. A failed
report is logged and ignored. It never changes the decision already taken.
"""

from __future__ import annotations

import html
import json
import os
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from mitmproxy import ctx
from mitmproxy import http

import bypass
import decision
import observe

DECISION_URL = os.environ.get("DECISION_URL", "http://decisions:8090/v1/decisions")
OBSERVATION_URL = os.environ.get(
    "OBSERVATION_URL", "http://observations:8091/v1/observations"
)
BYPASS_PATH = Path(os.environ.get("BYPASS_PATH", "/etc/smartproxy/bypass.txt"))
TIMEOUT = float(os.environ.get("DECISION_TIMEOUT", "2"))
# How often an open flow is checked for bytes that are ready to report.
_POLL_SECONDS = 0.2

_UNAVAILABLE = object()
_UNRECOGNIZED = object()


class _Account:
    def __init__(self, client_ip: str, url: str, interval: float) -> None:
        self.client_ip = client_ip
        self.url = url
        self.meter = observe.TrafficMeter(interval, time.monotonic())


def _positive_float(raw: str | None, default: float) -> float:
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if value <= 0:
        return default
    return value


class DecisionEnforcer:
    def __init__(self) -> None:
        self.interval = _positive_float(os.environ.get("OBSERVATION_INTERVAL"), 60.0)
        self.observation_timeout = _positive_float(
            os.environ.get("OBSERVATION_TIMEOUT"), 2.0
        )
        self._accounts: dict[str, _Account] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def running(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._watch_open_flows,
            name="observations",
            daemon=True,
        )
        self._thread.start()

    def done(self) -> None:
        self._stop.set()

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
            self._disarm(flow)
            flow.response = _deny_page(decision.UNAVAILABLE_MESSAGE)

    def _enforce(self, flow: http.HTTPFlow) -> None:
        if flow.request.method.upper() == "CONNECT":
            return
        host = flow.request.pretty_host
        if bypass.is_bypassed(host, bypass.load_patterns(BYPASS_PATH)):
            ctx.log.info(f"bypass {flow.request.method} {host}")
            self._arm(flow)
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
            self._arm(flow)
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

    def responseheaders(self, flow: http.HTTPFlow) -> None:
        """Count response body bytes as they arrive, including a long stream.

        Denied and redirected flows are never armed, so their pages are not
        treated as upstream traffic. Streaming has to be chosen here: by the
        response hook the body is already buffered.
        """
        if not self._armed(flow) or flow.response is None:
            return
        flow.response.stream = self._watch(flow.id)

    def response(self, flow: http.HTTPFlow) -> None:
        self._close(flow)

    def error(self, flow: http.HTTPFlow) -> None:
        self._close(flow)

    def _armed(self, flow: http.HTTPFlow) -> bool:
        with self._lock:
            return flow.id in self._accounts

    def _arm(self, flow: http.HTTPFlow) -> None:
        peer = flow.client_conn.peername
        if not peer or not peer[0]:
            ctx.log.warn("observation skipped: missing client address")
            return
        account = _Account(
            peer[0],
            flow.request.pretty_url.split("#", 1)[0],
            self.interval,
        )
        with self._lock:
            self._accounts[flow.id] = account
        # A request body is streamed only when we are forwarding. A deny or a
        # redirect also sets flow.response, and mitmproxy refuses that pair.
        if _request_has_body(flow):
            flow.request.stream = self._watch(flow.id)

    def _disarm(self, flow: http.HTTPFlow) -> None:
        with self._lock:
            self._accounts.pop(flow.id, None)
        flow.request.stream = False

    def _watch(self, flow_id: str):
        def watch(data: bytes) -> bytes:
            try:
                if data:
                    self._note(flow_id, len(data))
            except Exception as exc:
                print(f"observation failed: {exc}", flush=True)
            return data

        return watch

    def _note(self, flow_id: str, nbytes: int) -> None:
        with self._lock:
            account = self._accounts.get(flow_id)
            if account is None:
                return
            count = account.meter.add(nbytes, time.monotonic())
        if count:
            self._post(account, count)

    def _close(self, flow: http.HTTPFlow) -> None:
        try:
            with self._lock:
                account = self._accounts.pop(flow.id, None)
                count = account.meter.finish(time.monotonic()) if account else 0
            if account and count:
                self._post(account, count)
        except Exception as exc:
            print(f"observation failed: {exc}", flush=True)

    def _watch_open_flows(self) -> None:
        while not self._stop.wait(_POLL_SECONDS):
            try:
                self._flush_due()
            except Exception as exc:
                print(f"observation failed: {exc}", flush=True)

    def _flush_due(self) -> None:
        now = time.monotonic()
        ready: list[tuple[_Account, int]] = []
        with self._lock:
            for account in self._accounts.values():
                count = account.meter.due(now)
                if count:
                    ready.append((account, count))
        for account, count in ready:
            self._post(account, count)

    def _post(self, account: _Account, nbytes: int) -> None:
        if nbytes <= 0:
            return
        payload = {
            "client_ip": account.client_ip,
            "url": account.url,
            "occurred_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "bytes": nbytes,
        }
        request = urllib.request.Request(
            OBSERVATION_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.observation_timeout
            ) as response:
                response.read()
        except Exception as exc:
            print(f"observation failed: {exc}", flush=True)
            return
        print(f"observe {nbytes} {account.url}", flush=True)


def _request_has_body(flow: http.HTTPFlow) -> bool:
    if "chunked" in flow.request.headers.get("transfer-encoding", "").lower():
        return True
    length = flow.request.headers.get("content-length")
    if length is None:
        return False
    try:
        return int(length) > 0
    except ValueError:
        return False


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
