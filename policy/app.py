"""The policy service. Run with: uvicorn --factory policy.app:create_app

On start, POLICY_FILE (when present) is loaded into the SQLite database at
POLICY_DB. Without the file, the service uses what the database already holds.
Each decision reads that database for today's revision count.
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
    answer,
    completed_today,
    context_for,
    log_entry,
    parse_request,
)
from policy.groups import SiteGroups
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
        config.apply(config.load(policy_file), store)
    else:
        print(f"{policy_file} not found; using the stored policy", flush=True)
    timezone = store.timezone()
    clients = store.clients()
    groups = store.groups()
    revision_task = store.revision_task()

    if timezone:
        zone = named_zone(timezone)
        source = f"timezone {timezone}"
    else:
        zone = machine_zone(localtime=localtime)
        source = "timezone of this machine"
    clock = HouseholdClock(zone)
    print(f"household {source}; local time is {clock.local().isoformat(timespec='seconds')}", flush=True)
    for client in clients:
        print(f"client {client.name}: {', '.join(client.ips) or 'no IP'}", flush=True)
    if revision_task:
        print(f"revision task placeholder {revision_task}", flush=True)
    for group in sorted(groups, key=lambda group: (group.default, group.priority)):
        detail = "default" if group.default else f"priority {group.priority}, {len(group.patterns)} patterns"
        rules = "1 rule" if len(group.rules) == 1 else f"{len(group.rules)} rules"
        print(f"group {group.name}: {detail}, {rules}", flush=True)
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
        decision = answer(
            context,
            decision_file,
            stub=decision_stub,
            revision_task=revision_task,
            completed=completed_today(store, context),
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

    return app
