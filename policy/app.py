"""The policy service. The container runs: python -m policy.serve

On start, POLICY_FILE is loaded. The household file is YAML
(/etc/daywarden/policy.yaml). A YAML policy is decided by nested rule sets,
and GET /usage slices today's usage by site group, client group, or quota.
A path ending in .toml is still the previous engine, so older tests can
point POLICY_FILE at a file they wrote. The shipped config/policy.toml is
not that path. Parent pages stay closed until a parent account is added,
and they are served only over HTTPS. The quiz sound sets are read once at
start, from SOUND_DIR or the image's policy/static/sounds. Spelling words
are read from DAYWARDEN_DATA_DIR each time a run starts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response

from policy import config
from policy.accounts import COOKIE_NAME, Accounts, cookie_value, session_limits
from policy.clients import ClientDirectory, normalize_ip
from policy.clock import HouseholdClock, machine_zone, named_zone
from policy.decisions import (
    DecisionLog,
    answer_from_store,
    context_for,
    log_entry,
    parse_request,
)
from policy.engine import NO_RULE_MESSAGE, Assumption, Ledger, Trace, classify_client, judge, log_fields
from policy.groups import SiteGroups
from policy.hierarchy import Policy, load as load_hierarchy
from policy.report import format_byte_limit, parse_form, respond, respond_hierarchy
from policy.returns import ReturnPages, way_back
from policy.review import QUIZ_PAGE, https_only_page, respond_attempt, respond_attempts, respond_parent_check
from policy.selection import picker_url
from policy.sounds import SOUND_DIR, SOUND_PATH, load_sounds, media_type
from policy.store import PolicyStore
from policy.task_page import respond_task, task_media
from policy.tasks import AttemptStore
from policy.usage import UsageStore


def create_app() -> FastAPI:
    policy_file = Path(os.environ.get("POLICY_FILE", "/etc/daywarden/policy.yaml"))
    database = Path(os.environ.get("POLICY_DB", "/var/lib/daywarden/policy.sqlite3"))
    decision_file = Path(os.environ.get("DECISION_FILE", "/etc/daywarden/decision.json"))
    decision_stub = os.environ.get("DECISION_STUB") == "1"
    decision_log = DecisionLog(Path(os.environ.get("DECISION_LOG", "/tmp/decisions.jsonl")))
    localtime = Path(os.environ.get("MACHINE_LOCALTIME", "/etc/localtime"))

    database.parent.mkdir(parents=True, exist_ok=True)
    idle, lifetime = session_limits(os.environ)
    store = PolicyStore(database)
    accounts = Accounts(store.connection, idle=idle, lifetime=lifetime)
    attempts = AttemptStore(connection=store.connection)
    returns = ReturnPages(store.connection)
    # YAML is the household policy. A .toml path is the previous engine.
    yaml_mode = policy_file.suffix.lower() in {".yaml", ".yml"}
    hierarchy_policy: Policy | None = None
    ledger: Ledger = Ledger()
    usage_store: UsageStore | None = None
    if yaml_mode:
        hierarchy_policy, clock, source = _start_hierarchy(policy_file, localtime)
        usage_store = UsageStore(connection=store.connection)
        if hierarchy_policy is not None:
            usage_store.install_length(hierarchy_policy.bucket_length, clock.local())
        ledger = usage_store
        _announce_hierarchy(hierarchy_policy, clock, source)
        directory = ClientDirectory(())
        site_groups = SiteGroups(())
    elif policy_file.is_file():
        print(f"loading {policy_file}", flush=True)
        loaded = config.load(policy_file)
        _zone, source = _household_zone(loaded.timezone, localtime)
        clock = HouseholdClock(_zone)
        config.apply(loaded, store, loaded_at=clock.local())
        directory, site_groups = _announce_stored(store, clock, source)
    else:
        print(f"{policy_file} not found; using the stored policy", flush=True)
        _zone, source = _household_zone(store.timezone(), localtime)
        clock = HouseholdClock(_zone)
        directory, site_groups = _announce_stored(store, clock, source)
    _announce_parents(accounts)
    sounds = load_sounds(Path(os.environ.get("SOUND_DIR", str(SOUND_DIR))))
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.idle = accounts.idle
    app.state.lifetime = accounts.lifetime

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
            trace, assumption = _judge_for(
                hierarchy_policy,
                ledger,
                parsed.client_ip,
                parsed.url,
                at,
                attempts,
            )
            if (
                usage_store is not None
                and parsed.flow_id
                and trace.decision.get("action") == "allow"
            ):
                usage_store.save_transfer(
                    parsed.flow_id,
                    trace.client_group,
                    trace.site_group,
                    parsed.url,
                    assumption,
                )
            if hierarchy_policy is not None:
                returns.note(
                    hierarchy_policy,
                    trace,
                    client_ip=parsed.client_ip,
                    method=parsed.method,
                    url=parsed.url,
                    sec_fetch_dest=parsed.sec_fetch_dest,
                    accept=parsed.accept,
                    at=at,
                )
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

    @app.get("/quiz")
    def quiz_page() -> Response:
        # The revision page does not use the parent session.
        return Response(QUIZ_PAGE, media_type="text/html; charset=utf-8")

    @app.get("/tasks/work/{task_name}/audio/{file_name}")
    async def task_work_audio(request: Request, task_name: str, file_name: str) -> Response:
        return _task_audio(request, "/tasks/work/" + quote(task_name, safe="") + "/audio/" + file_name)

    @app.get("/tasks/{task_name}/audio/{file_name}")
    async def task_audio(request: Request, task_name: str, file_name: str) -> Response:
        return _task_audio(request, "/tasks/" + quote(task_name, safe="") + "/audio/" + file_name)

    @app.api_route("/tasks/work/{task_name}", methods=["GET", "POST"])
    async def task_work_page(request: Request, task_name: str) -> Response:
        return await _task_page(request, "/tasks/work/" + quote(task_name, safe=""))

    @app.api_route("/tasks/{task_name}", methods=["GET", "POST"])
    async def task_page(request: Request, task_name: str) -> Response:
        return await _task_page(request, "/tasks/" + quote(task_name, safe=""))

    @app.get(SOUND_PATH + "{outcome}/{name}")
    def sound_file(outcome: str, name: str) -> Response:
        found = sounds.path(outcome, name)
        if found is None:
            return PlainTextResponse("not found", status_code=404)
        return FileResponse(found, media_type=media_type(name), headers={"cache-control": "max-age=3600"})

    def _task_audio(request: Request, path: str) -> Response:
        policy = hierarchy_policy if hierarchy_policy is not None else _empty_policy()
        found = task_media(
            policy,
            attempts,
            path=path,
            client_ip=_client_address(request, hierarchy_policy),
            now=clock.local(),
        )
        if found is None:
            return PlainTextResponse("not found", status_code=404)
        return FileResponse(found, media_type=media_type(found.name), headers={"cache-control": "private, max-age=3600"})

    async def _task_page(request: Request, path: str) -> Response:
        raw = await request.body() if request.method == "POST" else b""
        policy = hierarchy_policy if hierarchy_policy is not None else _empty_policy()
        client_ip = _client_address(request, hierarchy_policy)

        def back() -> str | None:
            if hierarchy_policy is None:
                return None
            return way_back(hierarchy_policy, returns, ledger, client_ip, clock.local())

        page = respond_task(
            policy,
            attempts,
            method=request.method,
            path=path,
            client_ip=client_ip,
            cookie=request.headers.get("cookie"),
            now=clock.local(),
            query=_query(request, ("do",)),
            body=raw,
            sounds=sounds,
            back=back,
        )
        response = Response(page.body, status_code=page.status, media_type="text/html; charset=utf-8")
        for name, value in page.headers:
            if name == "set-cookie":
                response.headers.append("set-cookie", value)
            else:
                response.headers[name] = value
        return response

    @app.api_route("/usage", methods=["GET", "POST"])
    async def usage_page(request: Request) -> Response:
        return await _parent_page(request, _usage_page)

    @app.api_route("/attempts", methods=["GET", "POST"])
    async def attempts_page(request: Request) -> Response:
        return await _parent_page(request, _attempts_page)

    @app.api_route("/attempts/parent-check", methods=["POST"])
    async def parent_check_page(request: Request) -> Response:
        return await _parent_page(request, _parent_check_page)

    @app.api_route("/attempts/{attempt_id}", methods=["GET", "POST"])
    async def attempt_page(request: Request, attempt_id: str) -> Response:
        def render(request: Request, raw: bytes) -> object:
            return _attempt_page(request, raw, attempt_id)

        return await _parent_page(request, render)

    async def _parent_page(request: Request, render) -> Response:
        # Stay on the event-loop thread. A sync endpoint would run in a
        # threadpool, and this process's SQLite connection is not shared.
        # Plain HTTP does not return the page, set the cookie, or act.
        if request.url.scheme != "https":
            refused = Response(
                https_only_page(),
                status_code=403,
                media_type="text/html; charset=utf-8",
            )
            refused.headers["cache-control"] = "no-store"
            return refused
        raw = await request.body() if request.method == "POST" else b""
        page = render(request, raw)
        response = Response(page.body, status_code=page.status, media_type="text/html; charset=utf-8")
        for name, value in page.headers:
            if name == "set-cookie":
                response.headers.append("set-cookie", value)
            else:
                response.headers[name] = value
        return response

    def _usage_page(request: Request, raw: bytes):
        cookie = cookie_value(request.headers.get("cookie"), COOKIE_NAME)
        form = parse_form(raw)
        if yaml_mode:
            assert usage_store is not None
            return respond_hierarchy(
                hierarchy_policy,
                usage_store,
                accounts,
                method=request.method,
                query=_query(request, ("view", "client", "site", "quota")),
                cookie=cookie,
                form=form,
                now=clock.local(),
            )
        return respond(
            store,
            accounts,
            method=request.method,
            query=_query(request, ("client", "group")),
            cookie=cookie,
            form=form,
            now=clock.local(),
        )

    def _attempts_page(request: Request, raw: bytes):
        return respond_attempts(
            accounts,
            method=request.method,
            query=_query(request, ("client",)),
            cookie=cookie_value(request.headers.get("cookie"), COOKIE_NAME),
            form=parse_form(raw),
            now=clock.local(),
            attempts=attempts,
            clients=_client_names(hierarchy_policy),
        )

    def _attempt_page(request: Request, raw: bytes, attempt_id: str):
        return respond_attempt(
            accounts,
            attempt_id=attempt_id,
            method=request.method,
            query={},
            cookie=cookie_value(request.headers.get("cookie"), COOKIE_NAME),
            form=parse_form(raw),
            now=clock.local(),
            attempts=attempts,
        )

    def _parent_check_page(request: Request, raw: bytes):
        return respond_parent_check(
            accounts,
            cookie=cookie_value(request.headers.get("cookie"), COOKIE_NAME),
            form=parse_form(raw),
            now=clock.local(),
            tasks=() if hierarchy_policy is None else hierarchy_policy.tasks,
            attempts=attempts,
            clients=_client_names(hierarchy_policy),
        )

    return app


def _query(request: Request, keys: tuple[str, ...]) -> dict[str, str]:
    found = {}
    for key in keys:
        value = request.query_params.get(key)
        if value is not None:
            found[key] = value
    return found


def _announce_parents(accounts: Accounts) -> None:
    if accounts.count():
        print("usage report is /usage", flush=True)
    else:
        print("usage report is closed until a parent account is added", flush=True)


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
    return ClientDirectory(clients), SiteGroups(groups)


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
    print(f"task pages are {picker_url(policy)}", flush=True)
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


def _empty_policy() -> Policy:
    return Policy(entry="", rule_sets=())


def _client_names(policy: Policy | None) -> tuple[str, ...]:
    """Return the client groups a parent can review, including ``default``."""
    if policy is None:
        return ()
    names = [group.name for group in policy.client_groups]
    if "default" not in names:
        names.append("default")
    return tuple(names)


def _client_address(request: Request, policy: Policy | None) -> str:
    """Return the child address the task page should trust.

    A browser that reaches this service directly is classified from the
    connection. A request the proxy forwarded carries the child address in
    ``X-Daywarden-Client``, because the connection itself is the proxy.
    """
    peer = request.client.host if request.client is not None else ""
    header = request.headers.get("x-daywarden-client", "")
    if policy is not None and peer and classify_client(policy, peer) != "default":
        return peer
    if normalize_ip(header) is not None:
        return header.strip()
    return peer


def _judge_for(policy: Policy | None, ledger: Ledger, client_ip: str, url: str, at, attempts: AttemptStore):
    if policy is None:
        trace = Trace(
            "default",
            "default",
            None,
            None,
            True,
            {"action": "deny", "status": 403, "message": NO_RULE_MESSAGE},
        )
        return trace, Assumption()
    return judge(policy, client_ip=client_ip, url=url, at=at, ledger=ledger, attempts=attempts)


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
