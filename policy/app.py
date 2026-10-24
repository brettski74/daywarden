"""The policy service. Run with: uvicorn --factory policy.app:create_app

On start, POLICY_FILE (when present) is loaded into the SQLite database at
POLICY_DB. Without the file, the service uses what the database already holds.
Each decision reads that database for today's revision count, for the
ended usage recorded against today's quota, and for the bytes already stored
against a byte limit. GET /usage is the parent report of that usage. It stays
closed until PARENT_PASSWORD is set.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, Response

from policy import config
from policy.clients import ClientDirectory
from policy.clock import HouseholdClock, machine_zone, named_zone
from policy.decisions import (
    DecisionLog,
    answer_from_store,
    context_for,
    log_entry,
    parse_request,
)
from policy.gate import COOKIE_NAME, ParentGate, cookie_value
from policy.groups import SiteGroups
from policy.report import format_byte_limit, parse_form, respond
from policy.store import PolicyStore


def create_app() -> FastAPI:
    policy_file = Path(os.environ.get("POLICY_FILE", "/etc/smartproxy/policy.toml"))
    database = Path(os.environ.get("POLICY_DB", "/var/lib/smartproxy/policy.sqlite3"))
    decision_file = Path(os.environ.get("DECISION_FILE", "/etc/smartproxy/decision.json"))
    decision_stub = os.environ.get("DECISION_STUB") == "1"
    decision_log = DecisionLog(Path(os.environ.get("DECISION_LOG", "/tmp/decisions.jsonl")))
    localtime = Path(os.environ.get("MACHINE_LOCALTIME", "/etc/localtime"))

    database.parent.mkdir(parents=True, exist_ok=True)
    store = PolicyStore(database)
    if policy_file.is_file():
        print(f"loading {policy_file}", flush=True)
        loaded = config.load(policy_file)
        _zone, source = _household_zone(loaded.timezone, localtime)
        clock = HouseholdClock(_zone)
        config.apply(loaded, store, loaded_at=clock.local())
    else:
        print(f"{policy_file} not found; using the stored policy", flush=True)
        _zone, source = _household_zone(store.timezone(), localtime)
        clock = HouseholdClock(_zone)
    clients = store.clients()
    groups = store.groups()
    revision_task = store.revision_task()
    print(f"household {source}; local time is {clock.local().isoformat(timespec='seconds')}", flush=True)
    for client in clients:
        print(f"client {client.name}: {', '.join(client.ips) or 'no IP'}", flush=True)
    if revision_task:
        print(f"revision task placeholder {revision_task}", flush=True)
    print(f"usage buckets are {_span(store.bucket_length())}", flush=True)
    gate = ParentGate(os.environ.get("PARENT_PASSWORD"))
    if gate.configured:
        print("usage report is /usage", flush=True)
    else:
        print("usage report is closed until PARENT_PASSWORD is set", flush=True)
    for group in sorted(groups, key=lambda group: (group.default, group.priority)):
        detail = "default" if group.default else f"priority {group.priority}, {len(group.patterns)} patterns"
        rules = "1 rule" if len(group.rules) == 1 else f"{len(group.rules)} rules"
        quota = "no quota" if group.quota is None else f"quota {_span(group.quota)}"
        volume = (
            "no byte limit"
            if group.byte_limit is None
            else f"byte limit {format_byte_limit(group.byte_limit)}"
        )
        print(f"group {group.name}: {detail}, {rules}, {quota}, {volume}", flush=True)
    if not any(group.default for group in groups):
        print("no default group; sites outside every group are denied", flush=True)

    directory = ClientDirectory(clients)
    site_groups = SiteGroups(groups)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    def health() -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.post("/v1/decisions")
    async def decisions(request: Request) -> Response:
        raw = await request.body()
        try:
            document = json.loads(raw)
        except json.JSONDecodeError:
            document = {"raw": raw.decode("utf-8", "replace")}
        try:
            context = context_for(parse_request(document), clock, directory, site_groups)
        except ValueError as exc:
            decision_log.append(log_entry(document, None, None))
            return PlainTextResponse(str(exc), status_code=400)
        decision = answer_from_store(
            store,
            context,
            decision_file,
            stub=decision_stub,
        )
        decision_log.append(log_entry(document, context, decision))
        who = context.client.name if context.client else context.request.client_ip
        group = context.group.name if context.group else "no group"
        print(
            f"decision {context.request.method} {context.request.url} ({group}) "
            f"for {who} at {context.local_time.isoformat(timespec='seconds')}",
            flush=True,
        )
        if decision is None:
            return PlainTextResponse("missing decision", status_code=500)
        return Response(decision, media_type="application/json")

    @app.api_route("/usage", methods=["GET", "POST"])
    async def usage(request: Request) -> Response:
        # Stay on the event-loop thread. A sync endpoint would run in a
        # threadpool, and this process's SQLite connection is not shared.
        raw = await request.body() if request.method == "POST" else b""
        query = {}
        for key in ("client", "group"):
            value = request.query_params.get(key)
            if value is not None:
                query[key] = value
        page = respond(
            store,
            gate,
            method=request.method,
            query=query,
            cookie=cookie_value(request.headers.get("cookie"), COOKIE_NAME),
            form=parse_form(raw),
            now=clock.local(),
        )
        response = Response(page.body, status_code=page.status, media_type="text/html; charset=utf-8")
        for name, value in page.headers:
            if name == "set-cookie":
                response.headers.append("set-cookie", value)
            else:
                response.headers[name] = value
        return response

    return app


def _household_zone(timezone: str | None, localtime: Path):
    """Return the zone for timezone, or the machine zone, and a phrase for the log."""
    if timezone:
        return named_zone(timezone), f"timezone {timezone}"
    return machine_zone(localtime=localtime), "timezone of this machine"


def _span(seconds: int) -> str:
    """Return a short duration such as 2h, 5m, or 90s."""
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"
