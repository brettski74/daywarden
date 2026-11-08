"""The policy service. The container runs: python -m policy.serve

On start, POLICY_FILE is loaded. The household file is
/etc/daywarden/policy.yaml. Requests are decided by its nested rule sets,
and GET /usage slices recent usage by site group, client group, or quota.
A POLICY_FILE that does not end in .yaml or .yml stops the service. A
missing file leaves it running with nothing allowed. Parent pages stay
closed until a parent account is added, and they are served only over
HTTPS. The quiz sound sets are read once at start, from SOUND_DIR or the
image's policy/static/sounds. Spelling words are read from
DAYWARDEN_DATA_DIR each time a run starts.

POST /v1/reload loads POLICY_FILE again and swaps the new policy in whole,
so a request is decided by the old policy or the new one, never a mix. A
policy with errors is refused and the one in force stays. Only a plain HTTP
request from inside this container is accepted. Any other peer gets 404,
because the proxy can reach this port on the compose network.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response

from policy.accounts import COOKIE_NAME, Accounts, cookie_value, session_limits
from policy.check import household_zone, load_required, summary_lines
from policy.clients import normalize_ip
from policy.clock import HouseholdClock
from policy.decisions import DecisionLog, log_entry, parse_request
from policy.engine import NO_RULE_MESSAGE, Assumption, Ledger, Trace, classify_client, judge, log_fields
from policy.hierarchy import ConfigError, Policy, load as load_hierarchy, require_yaml
from policy.report import parse_form, respond
from policy.returns import ReturnPages, way_back
from policy.review import QUIZ_PAGE, https_only_page, respond_attempt, respond_attempts, respond_parent_check
from policy.sounds import SOUND_DIR, SOUND_PATH, load_sounds, media_type
from policy.store import PolicyStore
from policy.task_page import respond_task, task_media
from policy.tasks import AttemptStore
from policy.usage import UsageStore

LOOPBACK = frozenset({"127.0.0.1", "::1"})


@dataclass(frozen=True)
class Loaded:
    """The policy in force and the household clock it sets."""

    policy: Policy | None
    clock: HouseholdClock
    source: str


class Holder:
    """Holds the policy in force. A reload replaces ``loaded`` in one assignment."""

    def __init__(self, loaded: Loaded) -> None:
        self.loaded = loaded


def create_app() -> FastAPI:
    policy_file = Path(os.environ.get("POLICY_FILE", "/etc/daywarden/policy.yaml"))
    database = Path(os.environ.get("POLICY_DB", "/var/lib/daywarden/policy.sqlite3"))
    decision_log = DecisionLog(Path(os.environ.get("DECISION_LOG", "/tmp/decisions.jsonl")))
    localtime = Path(os.environ.get("MACHINE_LOCALTIME", "/etc/localtime"))

    database.parent.mkdir(parents=True, exist_ok=True)
    idle, lifetime = session_limits(os.environ)
    holder = Holder(_load_policy(policy_file, localtime))
    store = PolicyStore(database)
    accounts = Accounts(store.connection, idle=idle, lifetime=lifetime)
    attempts = AttemptStore(connection=store.connection)
    returns = ReturnPages(store.connection)
    usage_store = UsageStore(connection=store.connection)
    if holder.loaded.policy is not None:
        usage_store.install_length(holder.loaded.policy.bucket_length, holder.loaded.clock.local())
    _announce(summary_lines(holder.loaded.policy, holder.loaded.clock, holder.loaded.source))
    _announce_parents(accounts)
    sounds = load_sounds(Path(os.environ.get("SOUND_DIR", str(SOUND_DIR))))
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.idle = accounts.idle
    app.state.lifetime = accounts.lifetime
    app.state.holder = holder

    @app.get("/health")
    def health() -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.post("/v1/reload")
    async def reload(request: Request) -> Response:
        # Stays on the event-loop thread, where this process's SQLite connection lives.
        peer = request.client.host if request.client is not None else ""
        if request.url.scheme != "http" or peer not in LOOPBACK:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        warnings: list[str] = []
        try:
            policy = load_required(policy_file, holder.loaded.policy, warn=warnings.append)
        except ConfigError as error:
            print(f"reload refused: the policy has {len(error.problems)} errors", flush=True)
            _announce(error.problems)
            return JSONResponse({"reloaded": False, "errors": list(error.problems), "warnings": warnings})
        zone, source = household_zone(policy.timezone, localtime)
        clock = HouseholdClock(zone)
        usage_store.install_length(policy.bucket_length, clock.local())
        holder.loaded = Loaded(policy, clock, source)
        summary = summary_lines(policy, clock, source)
        print(f"reloaded {policy_file}", flush=True)
        _announce([*summary, *warnings])
        return JSONResponse({"reloaded": True, "summary": summary, "warnings": warnings})

    @app.post("/v1/decisions")
    async def decisions(request: Request) -> Response:
        now = holder.loaded
        raw = await request.body()
        try:
            document = json.loads(raw)
        except json.JSONDecodeError:
            document = {"raw": raw.decode("utf-8", "replace")}
        try:
            parsed = parse_request(document)
        except ValueError as exc:
            decision_log.append(log_entry(document))
            return PlainTextResponse(str(exc), status_code=400)
        at = now.clock.local(parsed.occurred_at)
        trace, assumption = _judge_for(
            now.policy,
            usage_store,
            parsed.client_ip,
            parsed.url,
            at,
        )
        if parsed.flow_id and trace.decision.get("action") == "allow":
            usage_store.save_transfer(
                parsed.flow_id,
                trace.client_group,
                trace.site_group,
                parsed.url,
                assumption,
            )
        if now.policy is not None:
            returns.note(
                now.policy,
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
        now = holder.loaded
        found = task_media(
            now.policy if now.policy is not None else _empty_policy(),
            attempts,
            path=path,
            client_ip=_client_address(request, now.policy),
            now=now.clock.local(),
        )
        if found is None:
            return PlainTextResponse("not found", status_code=404)
        return FileResponse(found, media_type=media_type(found.name), headers={"cache-control": "private, max-age=3600"})

    async def _task_page(request: Request, path: str) -> Response:
        now = holder.loaded
        raw = await request.body() if request.method == "POST" else b""
        client_ip = _client_address(request, now.policy)

        def back() -> str | None:
            if now.policy is None:
                return None
            return way_back(now.policy, returns, usage_store, client_ip, now.clock.local())

        page = respond_task(
            now.policy if now.policy is not None else _empty_policy(),
            attempts,
            method=request.method,
            path=path,
            client_ip=client_ip,
            now=now.clock.local(),
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
        def render(request: Request, raw: bytes, now: Loaded) -> object:
            return _attempt_page(request, raw, now, attempt_id)

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
        now = holder.loaded
        raw = await request.body() if request.method == "POST" else b""
        page = render(request, raw, now)
        response = Response(page.body, status_code=page.status, media_type="text/html; charset=utf-8")
        for name, value in page.headers:
            if name == "set-cookie":
                response.headers.append("set-cookie", value)
            else:
                response.headers[name] = value
        return response

    def _usage_page(request: Request, raw: bytes, now: Loaded):
        cookie = cookie_value(request.headers.get("cookie"), COOKIE_NAME)
        return respond(
            now.policy,
            usage_store,
            accounts,
            method=request.method,
            query=_query(request, ("view", "client", "site", "quota")),
            cookie=cookie,
            form=parse_form(raw),
            now=now.clock.local(),
        )

    def _attempts_page(request: Request, raw: bytes, now: Loaded):
        return respond_attempts(
            accounts,
            method=request.method,
            query=_query(request, ("client",)),
            cookie=cookie_value(request.headers.get("cookie"), COOKIE_NAME),
            form=parse_form(raw),
            now=now.clock.local(),
            attempts=attempts,
            clients=_client_names(now.policy),
            tasks=() if now.policy is None else now.policy.tasks,
        )

    def _attempt_page(request: Request, raw: bytes, now: Loaded, attempt_id: str):
        return respond_attempt(
            accounts,
            attempt_id=attempt_id,
            method=request.method,
            query={},
            cookie=cookie_value(request.headers.get("cookie"), COOKIE_NAME),
            form=parse_form(raw),
            now=now.clock.local(),
            attempts=attempts,
        )

    def _parent_check_page(request: Request, raw: bytes, now: Loaded):
        return respond_parent_check(
            accounts,
            cookie=cookie_value(request.headers.get("cookie"), COOKIE_NAME),
            form=parse_form(raw),
            now=now.clock.local(),
            tasks=() if now.policy is None else now.policy.tasks,
            attempts=attempts,
            clients=_client_names(now.policy),
        )

    return app


def _query(request: Request, keys: tuple[str, ...]) -> dict[str, str]:
    found = {}
    for key in keys:
        value = request.query_params.get(key)
        if value is not None:
            found[key] = value
    return found


def _announce(lines) -> None:
    for line in lines:
        print(line, flush=True)


def _announce_parents(accounts: Accounts) -> None:
    if accounts.count():
        print("usage report is /usage", flush=True)
    else:
        print("usage report is closed until a parent account is added", flush=True)


def _load_policy(policy_file: Path, localtime: Path) -> Loaded:
    """Load the household policy. A missing file leaves the service with nothing to decide."""
    require_yaml(policy_file)
    if policy_file.is_file():
        print(f"loading {policy_file}", flush=True)
    else:
        print(f"{policy_file} not found; no policy is loaded", flush=True)
    try:
        policy = load_hierarchy(policy_file)
    except ConfigError as error:
        print(f"the policy has {len(error.problems)} errors", flush=True)
        _announce(error.problems)
        raise
    timezone = None if policy is None else policy.timezone
    zone, source = household_zone(timezone, localtime)
    return Loaded(policy, HouseholdClock(zone), source)


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


def _judge_for(policy: Policy | None, ledger: Ledger, client_ip: str, url: str, at):
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
    return judge(policy, client_ip=client_ip, url=url, at=at, ledger=ledger)
