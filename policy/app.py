"""The policy service. The container runs: python -m policy.serve

On start, POLICY_FILE is loaded. The household file is
/etc/daywarden/policy.yaml. Requests are decided by its nested rule sets.
A POLICY_FILE that does not end in .yaml or .yml stops the service. A
missing file leaves it running with nothing allowed. The parent portal under
/parent/ stays closed until a parent account is added, and it is served only
over HTTPS. Its built files are read from PORTAL_DIR. The quiz sound sets are read once at start, from SOUND_DIR or the
image's policy/static/sounds. Spelling words are read from
DAYWARDEN_DATA_DIR each time a run starts.

POST /v1/reload loads POLICY_FILE again and swaps the new policy in whole,
so a request is decided by the old policy or the new one, never a mix. A
policy with errors is refused and the one in force stays. Only a plain HTTP
request from inside this container is accepted. Any other peer gets 404,
because the proxy can reach this port on the compose network.

A save on a parent portal task page reloads the same way, then asks the
observations and autoconfig services to reload through the Unix sockets at
OBSERVATIONS_SOCKET and AUTOCONFIG_SOCKET. See ``policy.task_admin``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response

from policy.account_pages import install_account_pages
from policy.accounts import Accounts, session_limits
from policy.check import household_zone, load_required, summary_lines
from policy.child_page import FAVICON_FILE, FAVICON_PATH
from policy.clients import normalize_ip
from policy.clock import HouseholdClock
from policy.decisions import DecisionLog, log_entry, parse_request
from policy.mail import Mailer, mail_settings, reset_lifetime
from policy.engine import NO_RULE_MESSAGE, Assumption, Ledger, Trace, classify_client, judge, log_fields
from policy.hierarchy import ConfigError, Policy, load as load_hierarchy, require_yaml
from policy import control
from policy import mcp_settings
from policy.mcp_server import McpServer, install_mcp, parent_names
from policy.mcp_tools import Sources
from policy.pool_admin import CAPITALISATION, PoolAdmin
from policy.task_create import TaskChanges
from policy.policy_admin import PolicyChanges
from policy.week import Weeks
from policy.portal import PORTAL_DIR, PortalGate, client_names, install_portal
from policy.returns import ReturnPages, way_back
from policy.review import QUIZ_PAGE
from policy.selection import published_port, task_media_path, task_page_path
from policy.sounds import SOUND_DIR, SOUND_PATH, load_sounds, media_type
from policy.recordings import Recordings
from policy.store import PolicyStore
from policy.task_admin import Reloads, TaskAdmin
from policy.task_page import respond_task, task_media
from policy.tasks import AttemptStore, TaskKey
from policy.usage import UsageStore, outcome_of
from policy.usage_graph import Presets

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
    # Read once, so a bad email setting stops the service before anything starts.
    mail = mail_settings(os.environ)
    reset_life = reset_lifetime(os.environ)
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
    _announce(["email is off: SMTP_HOST is not set" if mail is None else mail.describe()])
    sounds = load_sounds(Path(os.environ.get("SOUND_DIR", str(SOUND_DIR))))
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.idle = accounts.idle
    app.state.lifetime = accounts.lifetime
    app.state.holder = holder

    @app.get("/health")
    def health() -> PlainTextResponse:
        return PlainTextResponse("ok")

    mcp_box: dict[str, McpServer] = {}

    def apply_reload(*, with_mcp: bool = True) -> dict:
        """Load the policy again, and mcp.yaml with it unless with_mcp is False, as after a portal save of a task."""
        warnings: list[str] = []
        problems: list[str] = []
        try:
            policy = load_required(policy_file, holder.loaded.policy, warn=warnings.append)
        except ConfigError as error:
            problems = list(error.problems)
            policy = None
        settings = mcp_settings.load(mcp_settings.settings_file(policy_file)) if with_mcp else None
        if settings is not None:
            problems += settings.problems
        if problems or policy is None:
            print(f"reload refused: the policy has {len(problems)} errors", flush=True)
            _announce(problems)
            return {"reloaded": False, "errors": problems, "warnings": warnings}
        zone, source = household_zone(policy.timezone, localtime)
        clock = HouseholdClock(zone)
        usage_store.install_length(policy.bucket_length, clock.local())
        holder.loaded = Loaded(policy, clock, source)
        summary = summary_lines(policy, clock, source)
        if settings is not None and "server" in mcp_box:
            mcp_box["server"].apply(settings)
            summary.append(mcp_settings.summary_line(settings))
        print(f"reloaded {policy_file}", flush=True)
        _announce([*summary, *warnings])
        return {"reloaded": True, "summary": summary, "warnings": warnings}

    @app.post("/v1/reload")
    async def reload(request: Request) -> Response:
        # Stays on the event-loop thread, where this process's SQLite connection lives.
        peer = request.client.host if request.client is not None else ""
        if request.url.scheme != "http" or peer not in LOOPBACK:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return JSONResponse(apply_reload())

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
        if parsed.flow_id:
            outcome, status = outcome_of(trace.decision)
            usage_store.record_request(
                parsed.flow_id,
                started_at=at,
                client_ip=parsed.client_ip,
                client_group=trace.client_group,
                site_group=trace.site_group,
                method=parsed.method,
                url=parsed.url,
                outcome=outcome,
                status=status,
                sec_fetch_dest=parsed.sec_fetch_dest,
                sec_fetch_mode=parsed.sec_fetch_mode,
                sec_fetch_site=parsed.sec_fetch_site,
                sec_fetch_user=parsed.sec_fetch_user,
                sec_purpose=parsed.sec_purpose,
                accept=parsed.accept,
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
        print(decision_line(parsed.method, parsed.url, trace, at), flush=True)
        return Response(decision, media_type="application/json")

    @app.get(FAVICON_PATH)
    def favicon() -> Response:
        # The task pages' icon. Like them, it needs no parent session.
        return FileResponse(FAVICON_FILE, media_type="image/png", headers={"cache-control": "max-age=86400"})

    @app.get("/quiz")
    def quiz_page() -> Response:
        # The revision page does not use the parent session.
        return Response(QUIZ_PAGE, media_type="text/html; charset=utf-8")

    @app.get("/tasks/{task_type}/{task_name}/audio/{file_name}")
    async def task_audio(request: Request, task_type: str, task_name: str, file_name: str) -> Response:
        return _task_audio(request, task_media_path(TaskKey(task_type, task_name)) + file_name)

    @app.api_route("/tasks/{task_type}/{task_name}", methods=["GET", "POST"])
    async def task_page(request: Request, task_type: str, task_name: str) -> Response:
        return await _task_page(request, task_page_path(TaskKey(task_type, task_name)))

    # The picker, the selector, and any other one-part address, which goes to the picker.
    @app.api_route("/tasks/{page}", methods=["GET", "POST"])
    async def task_site_page(request: Request, page: str) -> Response:
        return await _task_page(request, "/tasks/" + quote(page, safe=""))

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

    others = {
        name: (lambda path=path, name=name: control.ask("reload", path, service=f"{name} service"))
        for name, path in (
            ("observations", control.socket_path("OBSERVATIONS_SOCKET")),
            ("autoconfig", control.socket_path("AUTOCONFIG_SOCKET")),
        )
        if path is not None
    }
    recordings = Recordings()
    recordings.clean()
    tasks = TaskAdmin(
        policy_file,
        policy=lambda: holder.loaded.policy,
        now=lambda: holder.loaded.clock.local(),
        today=lambda: holder.loaded.clock.today(),
        attempts=attempts,
        reloads=Reloads(lambda: apply_reload(with_mcp=False), others),
        clients=lambda: client_names(holder.loaded.policy),
        recordings=recordings,
    )
    gate = PortalGate(accounts, lambda: holder.loaded)
    mcp = McpServer(
        policy_file=policy_file,
        loaded=lambda: holder.loaded,
        accounts=accounts,
        sources=Sources(
            loaded=lambda: holder.loaded,
            attempts=attempts,
            usage=usage_store,
            presets=Presets(usage_store.connection),
            tasks=tasks,
            pools=PoolAdmin(tasks),
            capitalisation_pools=PoolAdmin(tasks, CAPITALISATION),
            changes=TaskChanges(tasks, Weeks(tasks)),
            policy_changes=PolicyChanges(tasks),
        ),
        names=parent_names(os.environ.get("PARENT_NAMES")),
    )
    mcp_box["server"] = mcp
    _announce([mcp_settings.summary_line(mcp.state), *mcp.state.problems])
    install_mcp(app, mcp, gate)
    install_account_pages(
        app,
        gate=gate,
        accounts=accounts,
        loaded=lambda: holder.loaded,
        mailer=None if mail is None else Mailer(mail),
        reset_lifetime=reset_life,
        names=parent_names(os.environ.get("PARENT_NAMES")),
        port=published_port,
    )
    install_portal(
        app,
        loaded=lambda: holder.loaded,
        accounts=accounts,
        attempts=attempts,
        usage_store=usage_store,
        tasks=tasks,
        portal_dir=Path(os.environ.get("PORTAL_DIR", str(PORTAL_DIR))),
    )
    return app


def _query(request: Request, keys: tuple[str, ...]) -> dict[str, str]:
    found = {}
    for key in keys:
        value = request.query_params.get(key)
        if value is not None:
            found[key] = value
    return found


def decision_line(method: str, url: str, trace: Trace, at: datetime) -> str:
    """The line the decisions service logs for one request, as dw logs decisions shows it."""
    action = trace.decision.get("action", "deny")
    where = "no rule" if trace.continued else f"{trace.rule_set} rule {trace.rule_index}"
    line = (
        f"decision {action} {method} {url} ({trace.site_group}) "
        f"for {trace.client_group} at {at.isoformat(timespec='seconds')} by {where}"
    )
    if action == "redirect":
        line += f" to {trace.decision.get('location', '')}"
    return line


def _announce(lines) -> None:
    for line in lines:
        print(line, flush=True)


def _announce_parents(accounts: Accounts) -> None:
    if accounts.count():
        print("parent portal is /parent/", flush=True)
    else:
        print("parent portal is closed until a parent account is added", flush=True)


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
