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
from policy.engine import NO_RULE_MESSAGE, Ledger, Trace, decide as decide_hierarchy, log_fields
from policy.gate import COOKIE_NAME, ParentGate, cookie_value
from policy.groups import SiteGroups
from policy.hierarchy import Policy, load as load_hierarchy
from policy.report import format_byte_limit, parse_form, respond
from policy.store import PolicyStore
from policy.usage import UsageStore


def create_app() -> FastAPI:
    policy_file = Path(os.environ.get("POLICY_FILE", "/etc/smartproxy/policy.toml"))
    database = Path(os.environ.get("POLICY_DB", "/var/lib/smartproxy/policy.sqlite3"))
    decision_file = Path(os.environ.get("DECISION_FILE", "/etc/smartproxy/decision.json"))
    decision_stub = os.environ.get("DECISION_STUB") == "1"
    decision_log = DecisionLog(Path(os.environ.get("DECISION_LOG", "/tmp/decisions.jsonl")))
    localtime = Path(os.environ.get("MACHINE_LOCALTIME", "/etc/localtime"))

    database.parent.mkdir(parents=True, exist_ok=True)
    store = PolicyStore(database)
    # YAML is the hierarchical policy and is decided by nested rule sets.
    # A TOML file stays on the previous engine until S008.5 stops loading it.
    yaml_mode = policy_file.suffix.lower() in {".yaml", ".yml"}
    hierarchy_policy: Policy | None = None
    ledger: Ledger = Ledger()
    if yaml_mode:
        hierarchy_policy, clock, source = _start_hierarchy(policy_file, localtime)
        usage = UsageStore(connection=store.connection)
        if hierarchy_policy is not None:
            usage.install_length(hierarchy_policy.bucket_length, clock.local())
        ledger = usage
        _announce_hierarchy(hierarchy_policy, clock, source)
        gate = ParentGate(os.environ.get("PARENT_PASSWORD"))
        if gate.configured:
            print("usage report is /usage", flush=True)
        else:
            print("usage report is closed until PARENT_PASSWORD is set", flush=True)
        directory = ClientDirectory(())
        site_groups = SiteGroups(())
    elif policy_file.is_file():
        print(f"loading {policy_file}", flush=True)
        loaded = config.load(policy_file)
        _zone, source = _household_zone(loaded.timezone, localtime)
        clock = HouseholdClock(_zone)
        config.apply(loaded, store, loaded_at=clock.local())
        directory, site_groups, gate = _announce_stored(store, clock, source)
    else:
        print(f"{policy_file} not found; using the stored policy", flush=True)
        _zone, source = _household_zone(store.timezone(), localtime)
        clock = HouseholdClock(_zone)
        directory, site_groups, gate = _announce_stored(store, clock, source)
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
        if yaml_mode:
            try:
                parsed = parse_request(document)
            except ValueError as exc:
                decision_log.append(log_entry(document, None, None))
                return PlainTextResponse(str(exc), status_code=400)
            at = clock.local(parsed.occurred_at)
            trace = _trace_for(hierarchy_policy, ledger, parsed.client_ip, parsed.url, at)
            decision = json.dumps(trace.decision).encode()
            decision_log.append({"request": document, "local_time": at.isoformat(), **log_fields(trace)})
            where = "no rule" if trace.continued else f"{trace.rule_set} rule {trace.rule_index}"
            print(
                f"decision {parsed.method} {parsed.url} ({trace.site_group}) "
                f"for {trace.client_group} at {at.isoformat(timespec='seconds')} by {where}",
                flush=True,
            )
            return Response(decision, media_type="application/json")
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


def _announce_stored(store: PolicyStore, clock: HouseholdClock, source: str):
    """Print the TOML policy the way the service always has, and return what decisions use."""
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
    return ClientDirectory(clients), SiteGroups(groups), gate


def _start_hierarchy(policy_file: Path, localtime: Path):
    """Load a YAML policy. A missing file leaves the service with nothing to decide."""
    if policy_file.is_file():
        print(f"loading {policy_file}", flush=True)
        policy = load_hierarchy(policy_file)
    else:
        print(f"{policy_file} not found; no hierarchical policy is loaded", flush=True)
        policy = None
    timezone = None if policy is None else policy.timezone
    zone, source = _household_zone(timezone, localtime)
    return policy, HouseholdClock(zone), source


def _announce_hierarchy(policy: Policy | None, clock: HouseholdClock, source: str) -> None:
    print(f"household {source}; local time is {clock.local().isoformat(timespec='seconds')}", flush=True)
    if policy is None:
        print("no hierarchical policy loaded", flush=True)
        return
    if policy.revision_task:
        print(f"revision task placeholder {policy.revision_task}", flush=True)
    print(f"usage buckets are {_span(policy.bucket_length)}", flush=True)
    print(f"entry {policy.entry}", flush=True)
    for group in policy.client_groups:
        print(f"client group {group.name}: {', '.join(group.ips) or 'no address'}", flush=True)
    print("client group default: addresses in no configured group", flush=True)
    for group in sorted(policy.site_groups, key=lambda item: item.priority):
        print(
            f"site group {group.name}: priority {group.priority}, {len(group.patterns)} patterns",
            flush=True,
        )
    print("site group default: urls that match no configured group", flush=True)


def _trace_for(policy: Policy | None, ledger: Ledger, client_ip: str, url: str, at) -> Trace:
    if policy is None:
        return Trace(
            "default",
            "default",
            None,
            None,
            True,
            {"action": "deny", "status": 403, "message": NO_RULE_MESSAGE},
        )
    return decide_hierarchy(policy, client_ip=client_ip, url=url, at=at, ledger=ledger)


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
