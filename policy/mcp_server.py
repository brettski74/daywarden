"""The MCP server on the HTTPS parent port, and its OAuth 2.1 authorization server.

``/mcp`` is a stateless MCP endpoint served by the official ``mcp`` SDK. Each
POST is answered with JSON, and GET and DELETE with 405, since no tool
streams. A call needs an access token from the authorization server here.
Without one, or with an expired or revoked one, it answers 401 with a
``WWW-Authenticate`` header that names the protected resource metadata, and
the agent opens the browser to be approved.

The authorization server is written here rather than taken from a library.
It is small: Dynamic Client Registration (RFC 7591), Client ID Metadata
Documents, the ``code`` flow with PKCE ``S256`` for public clients, refresh
with rotation, and revocation (RFC 7009). Its one sign-in is the portal's own
session, on the consent page ``/parent/settings/mcp/connect``.

Which tools an agent sees and may call is ``permissions`` in ``mcp.yaml``,
read again on every call, so a change applies from an agent's next call. A
connection approved by a reviewer gets only what that file grants to
``attempts`` and ``usage``, to read (S043). The approving account's role is
read again on every call too.

With the server off, or no ``mcp.yaml``, every address here answers 404.

Addresses given to agents use the published port, as task URLs do, and the
host the agent asked for when it is one of ``PARENT_NAMES``.
"""

from __future__ import annotations

import contextvars
import json
import os
import re
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

import mcp_types as types
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from mcp.server.lowlevel.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.concurrency import run_in_threadpool
from starlette.routing import Route

from policy import mcp_settings
from policy.accounts import ADMIN, REVIEWER, Accounts
from policy.history import History, HistoryError, stamp
from policy.mcp_settings import CLASSES, FIRST_TIME, READ, REVIEWER_CLASSES, McpSettings, SettingsError, for_role
from policy.mcp_store import CHECKED, DONE, FAILED, REFUSED, REVOKED, Client, McpStore, Refused
from policy.mcp_tools import READ_TOOLS, Sources, Tool, ToolProblem, WriteFailed, WriteRefused, Writer, answer_text, visible
from policy.mcp_policy_writes import POLICY_WRITE_TOOLS
from policy.mcp_writes import WRITE_TOOLS
from policy.owned import make_directory, own_like
from policy.portal import PortalGate
from policy.selection import published_port, task_port
from policy.task_admin import replace_text

MCP_PATH = "/mcp"
RESOURCE_METADATA = "/.well-known/oauth-protected-resource/mcp"
SERVER_METADATA = "/.well-known/oauth-authorization-server"
CONNECT_PAGE = "/parent/settings/mcp/connect"
_NOT_FOUND = {"detail": "Not Found"}
_LONGEST_NAME = 100
_LONGEST_DOCUMENT = 64 * 1024
_STALE = "mcp.yaml has changed on the server since this page was opened. Reload the page and make the change again."
_UNKNOWN_REQUEST = "This approval request is not known, or has expired. Start again from the agent."
_NEEDS_ADMIN = "This needs an admin's approval."
_NOTHING_FOR_REVIEWER = (
    "mcp.yaml gives agents no permission to read attempts or usage, so there is nothing a reviewer's agent could use. "
    "An admin can approve this agent, or grant attempts: read or usage: read on the MCP page."
)
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]", "::1"})
_HEX = re.compile(r"[0-9a-f]{64}\Z")
ALL_TOOLS: tuple[Tool, ...] = READ_TOOLS + WRITE_TOOLS + POLICY_WRITE_TOOLS
TOOLS: dict[str, Tool] = {tool.name: tool for tool in ALL_TOOLS}
# Some hosts, claude.ai among them, refuse urllib's default Python-urllib user agent with 403.
_USER_AGENT = "daywarden-mcp/1.0"


@dataclass(frozen=True)
class Caller:
    """The connection a call to /mcp came on."""

    agent: str
    parent: str
    role: str = ADMIN


_CALLER: contextvars.ContextVar[Caller] = contextvars.ContextVar("mcp_caller")


def parent_names(value: str | None) -> tuple[str, ...]:
    """Return the names in ``PARENT_NAMES``, as the listener's certificate holds them."""
    names = []
    for part in (value or "").split(","):
        token = part.strip()
        if token.startswith("[") and token.endswith("]"):
            token = token[1:-1]
        if token and token.lower() not in (name.lower() for name in names):
            names.append(token)
    return tuple(names) or ("localhost",)


def _host(name: str) -> str:
    return f"[{name}]" if ":" in name else name


class McpServer:
    def __init__(
        self,
        *,
        policy_file: Path,
        loaded: Callable[[], object],
        accounts: Accounts,
        sources: Sources,
        names: tuple[str, ...],
    ) -> None:
        self.path = mcp_settings.settings_file(policy_file)
        self.loaded = loaded
        self.accounts = accounts
        self.store = McpStore(accounts.connection)
        self.sources = sources
        self.names = names
        self.state = mcp_settings.load(self.path)
        if not self.state.on:
            # Started with the server off: turning it on again must ask for each agent's approval again.
            self.store.end_all(self.now(), "the MCP server was off when the service started")
        self.sdk = Server(
            "daywarden",
            version="1",
            instructions="Daywarden manages a household's internet time and the tasks children do to earn it. "
            "Times in answers are the household's local time.",
            on_list_tools=self._list_tools,
            on_call_tool=self._call_tool,
        )

    # Settings

    @property
    def settings(self) -> McpSettings | None:
        return self.state.settings if self.state.on else None

    def now(self) -> datetime:
        return self.loaded().clock.local()

    def apply(self, loaded: mcp_settings.Loaded) -> None:
        """Put new settings in force. Turning the server off ends every connection."""
        was_on = self.state.on
        self.state = loaded
        if was_on and not loaded.on:
            self.store.end_all(self.now(), "the MCP server was turned off")

    # Addresses

    def port(self) -> int:
        policy = self.loaded().policy
        return published_port() if policy is None else task_port(policy)

    def origin(self, name: str) -> str:
        port = self.port()
        return f"https://{_host(name)}" + ("" if port == 443 else f":{port}")

    def endpoint(self) -> str:
        return self.origin(self.names[0]) + MCP_PATH

    def base(self, request: Request) -> str:
        """Return the origin agents are given: the host they asked for when it is a parent name, else the first name."""
        asked = urlsplit("//" + request.headers.get("host", "")).hostname or ""
        for name in self.names:
            if name.lower() == asked.lower():
                return self.origin(name)
        return self.origin(self.names[0])

    def resources(self) -> set[str]:
        return {self.origin(name) + MCP_PATH for name in self.names}

    def origins(self) -> set[str]:
        return {self.origin(name).lower() for name in self.names}

    # MCP

    async def _list_tools(self, _context, _params) -> types.ListToolsResult:
        settings = self.settings
        tools = [] if settings is None else visible(for_role(settings, _CALLER.get().role), ALL_TOOLS)
        return types.ListToolsResult(
            tools=[types.Tool(name=tool.name, description=tool.description, input_schema=tool.schema()) for tool in tools]
        )

    async def _call_tool(self, _context, params) -> types.CallToolResult:
        caller = _CALLER.get()
        arguments = params.arguments or {}
        tool = TOOLS.get(params.name)
        settings = self.settings
        if tool is None:
            return self._refuse(caller, params.name, "", f"There is no tool {params.name}.")
        target = tool.target(arguments) if isinstance(arguments, Mapping) else ""
        if caller.role != ADMIN and not reviewer_tool(tool):
            return self._refuse(caller, tool.name, target, _NEEDS_ADMIN)
        if settings is None or not tool.allowed(for_role(settings, caller.role)):
            return self._refuse(caller, tool.name, target, f"This needs {tool.needs}.")
        if tool.write:
            return self._write(caller, tool, target, arguments)
        try:
            found = tool.run(self.sources, arguments)
        except ToolProblem as problem:
            return _tool_error(str(problem))
        except Exception as error:  # noqa: BLE001 - an agent gets a sentence, not a dropped request
            print(f"mcp tool {tool.name} failed: {error!r}", flush=True)
            return _tool_error(f"{tool.name} failed: {error}")
        return types.CallToolResult(content=[types.TextContent(type="text", text=answer_text(found))], is_error=False)

    def _write(self, caller: Caller, tool: Tool, target: str, arguments: Mapping) -> types.CallToolResult:
        """Run a write tool, and log it: Done, Checked for a dry run, Refused with every reason, or Failed."""
        dry_run = arguments.get("dry_run", False)
        if not isinstance(dry_run, bool):
            return self._refuse(caller, tool.name, target, "dry_run must be true or false.")
        writer = Writer(caller.parent, caller.agent, dry_run)
        try:
            found = tool.run(self.sources, arguments, writer)
        except WriteFailed as failure:
            self.store.log(caller.agent, caller.parent, tool.name, target, FAILED, failure.reasons, self.now())
            return _tool_error(str(failure))
        except WriteRefused as refusal:
            self.store.log(caller.agent, caller.parent, tool.name, target, REFUSED, refusal.reasons, self.now())
            return _tool_error(str(refusal))
        except ToolProblem as problem:
            return self._refuse(caller, tool.name, target, str(problem))
        except Exception as error:  # noqa: BLE001 - an agent gets a sentence, not a dropped request
            print(f"mcp tool {tool.name} failed: {error!r}", flush=True)
            self.store.log(caller.agent, caller.parent, tool.name, target, FAILED, [str(error)], self.now())
            return _tool_error(f"{tool.name} failed: {error}")
        self.store.log(caller.agent, caller.parent, tool.name, target, CHECKED if dry_run else DONE, [], self.now())
        return types.CallToolResult(content=[types.TextContent(type="text", text=answer_text(found))], is_error=False)

    def _refuse(self, caller: Caller, tool: str, target: str, reason: str) -> types.CallToolResult:
        self.store.log(caller.agent, caller.parent, tool, target, REFUSED, [reason], self.now())
        return _tool_error(reason)


def reviewer_tool(tool: Tool) -> bool:
    """Whether a reviewer's agent may ever call tool: a read in a reviewer class."""
    return tool.kind in REVIEWER_CLASSES and tool.permission == READ and not tool.write


def _tool_error(text: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=True)


class _McpEndpoint:
    """``/mcp`` as an ASGI app, so the SDK sends its own response."""

    def __init__(self, server: McpServer) -> None:
        self.server = server

    async def __call__(self, scope, receive, send) -> None:
        server = self.server
        request = Request(scope, receive)
        settings = server.settings
        if request.url.scheme != "https" or settings is None:
            await JSONResponse(_NOT_FOUND, status_code=404)(scope, receive, send)
            return
        origin = request.headers.get("origin")
        if origin is not None and origin.rstrip("/").lower() not in server.origins():
            await JSONResponse({"error": "This origin may not call the MCP server."}, status_code=403)(scope, receive, send)
            return
        connection = None
        scheme, _space, token = request.headers.get("authorization", "").partition(" ")
        token = token.strip()
        if scheme.lower() == "bearer" and _HEX.fullmatch(token):
            connection = server.store.accept(token, settings, server.now())
        if connection is None:
            challenge = f'Bearer resource_metadata="{server.base(request)}{RESOURCE_METADATA}"'
            await JSONResponse(
                {"error": "invalid_token", "error_description": "Approve this agent in the browser to use the MCP server."},
                status_code=401,
                headers={"www-authenticate": challenge, "cache-control": "no-store"},
            )(scope, receive, send)
            return
        if request.method != "POST":
            await JSONResponse(
                {"error": "This server answers each POST with JSON and opens no stream."}, status_code=405, headers={"allow": "POST"}
            )(scope, receive, send)
            return
        _CALLER.set(Caller(connection.client_name, connection.username, connection.role))
        manager = StreamableHTTPSessionManager(server.sdk, json_response=True, stateless=True)
        async with manager.run():
            await manager.handle_request(scope, receive, send)


def install_mcp(app: FastAPI, server: McpServer, gate: PortalGate) -> None:
    """Add /mcp, the authorization server, and the MCP page's data endpoints. Call before ``install_portal``."""
    store = server.store

    def off(request: Request) -> Response | None:
        if request.url.scheme != "https" or server.settings is None:
            return JSONResponse(_NOT_FOUND, status_code=404)
        return None

    app.router.routes.append(Route(MCP_PATH, endpoint=_McpEndpoint(server), methods=["GET", "POST", "DELETE"]))

    @app.get(RESOURCE_METADATA)
    async def resource_metadata(request: Request) -> Response:
        refused = off(request)
        if refused is not None:
            return refused
        base = server.base(request)
        return _json(
            200,
            {
                "resource": base + MCP_PATH,
                "authorization_servers": [base],
                "bearer_methods_supported": ["header"],
                "resource_name": "Daywarden",
            },
        )

    @app.get(SERVER_METADATA)
    async def server_metadata(request: Request) -> Response:
        refused = off(request)
        if refused is not None:
            return refused
        base = server.base(request)
        return _json(
            200,
            {
                "issuer": base,
                "authorization_endpoint": base + "/oauth/authorize",
                "token_endpoint": base + "/oauth/token",
                "registration_endpoint": base + "/oauth/register",
                "revocation_endpoint": base + "/oauth/revoke",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"],
                "revocation_endpoint_auth_methods_supported": ["none"],
                "client_id_metadata_document_supported": True,
            },
        )

    @app.post("/oauth/register")
    async def register(request: Request) -> Response:
        refused = off(request)
        if refused is not None:
            return refused
        try:
            body = json.loads(await request.body() or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _oauth_error(400, "invalid_client_metadata", "The body is not JSON.")
        if not isinstance(body, dict):
            return _oauth_error(400, "invalid_client_metadata", "The body is not a JSON object.")
        uris, problem = _redirect_uris(body.get("redirect_uris"))
        if problem is not None:
            return _oauth_error(400, "invalid_redirect_uri", problem)
        grants = body.get("grant_types", ["authorization_code", "refresh_token"])
        if not isinstance(grants, list) or not set(grants) <= {"authorization_code", "refresh_token"}:
            return _oauth_error(400, "invalid_client_metadata", "Only the authorization_code and refresh_token grants are offered.")
        client = store.register(_client_name(body.get("client_name")), uris, server.now())
        return _json(
            201,
            {
                "client_id": client.client_id,
                "client_id_issued_at": int(server.now().timestamp()),
                "client_name": client.name,
                "redirect_uris": list(client.redirect_uris),
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
        )

    @app.get("/oauth/authorize")
    async def authorize(request: Request) -> Response:
        refused = off(request)
        if refused is not None:
            return refused
        asked = request.query_params
        client_id = asked.get("client_id", "")
        redirect_uri = asked.get("redirect_uri", "")
        store.forget_unapproved(server.now())
        client, problem = await _client_for(store, client_id, server.now())
        if problem is None:
            problem = _request_problem(asked, client, server.resources())
        request_id = store.add_request(
            client_id[:500], redirect_uri[:2000], asked.get("state"), asked.get("code_challenge", "")[:200],
            asked.get("resource", "")[:500], problem, server.now(),
        )
        return RedirectResponse(f"{CONNECT_PAGE}?request={request_id}", status_code=302, headers={"cache-control": "no-store"})

    @app.post("/oauth/token")
    async def token(request: Request) -> Response:
        refused = off(request)
        if refused is not None:
            return refused
        form = _form(await request.body())
        grant = form.get("grant_type", "")
        settings = server.settings
        assert settings is not None
        try:
            if grant == "authorization_code":
                tokens = store.exchange(
                    form.get("code", ""), form.get("client_id", ""), form.get("redirect_uri", ""),
                    form.get("code_verifier", ""), form.get("resource"), settings, server.now(),
                )
            elif grant == "refresh_token":
                resource = form.get("resource")
                if resource is not None and resource not in server.resources():
                    raise Refused("invalid_target", "resource must be the /mcp address.")
                tokens = store.refresh(form.get("refresh_token", ""), form.get("client_id", ""), settings, server.now())
            else:
                raise Refused("unsupported_grant_type", "The grants are authorization_code and refresh_token.")
        except Refused as refusal:
            return _oauth_error(400, refusal.error, refusal.description)
        return _json(
            200,
            {
                "access_token": tokens.access_token,
                "token_type": "Bearer",
                "expires_in": tokens.expires_in,
                "refresh_token": tokens.refresh_token,
            },
        )

    @app.post("/oauth/revoke")
    async def revoke(request: Request) -> Response:
        refused = off(request)
        if refused is not None:
            return refused
        token_text = _form(await request.body()).get("token", "")
        if _HEX.fullmatch(token_text):
            store.revoke_token(token_text, server.now())
        return Response(status_code=200, headers={"cache-control": "no-store"})

    # The MCP page

    @app.get("/parent/api/settings/mcp")
    async def settings_page(request: Request) -> Response:
        _username, refused = gate.guard(request)
        if refused is not None:
            return refused
        return _json(200, page_body(server))

    @app.post("/parent/api/settings/mcp")
    async def settings_save(request: Request) -> Response:
        body, username, refused = await gate.acting(request)
        if refused is not None:
            return refused
        on_disk = mcp_settings.load(server.path)
        if body.get("version") != on_disk.version:
            return _json(409, {"error": _STALE, "stale": True})
        try:
            chosen = mcp_settings.from_data(body.get("settings"))
        except SettingsError as error:
            return _json(400, {"error": "The MCP settings were not saved.", "errors": error.problems})
        text = mcp_settings.settings_text(on_disk.text, server.path, on_disk.settings, chosen)
        warnings: list[str] = []
        if text != on_disk.text:
            try:
                _write(server.path, text, on_disk.exists)
            except OSError as error:
                return _json(500, {"error": f"{server.path} could not be written, so nothing was saved: {error}"})
            _commit(server, username, warnings)
        server.apply(mcp_settings.Loaded(server.path, chosen, exists=True, text=text))
        state = "on" if chosen.enabled else "off"
        return _json(200, {"message": f"Saved the MCP settings. The MCP server is {state}, and they are in force now.", "warnings": warnings})

    @app.post("/parent/api/settings/mcp/connections/{connection_id}/revoke")
    async def connection_revoke(request: Request, connection_id: str) -> Response:
        _body, username, refused = await gate.acting(request)
        if refused is not None:
            return refused
        found = store.connection_by_id(int(connection_id)) if connection_id.isdigit() else None
        if found is None:
            return _json(404, {"error": "That connection has already ended."})
        store.end(found, server.now(), REVOKED, f"revoked by {username}")
        return _json(200, {"message": f"Revoked {found.client_name}. Its next call is refused, and it must be approved again."})

    @app.get("/parent/api/settings/mcp/activity")
    async def activity(request: Request) -> Response:
        _username, refused = gate.guard(request)
        if refused is not None:
            return refused
        if server.settings is not None:
            store.sweep(server.settings, server.now())
        keep = (server.state.settings or mcp_settings.DEFAULTS).activity_days
        clock = server.loaded().clock
        policy = server.loaded().policy
        entries = [
            {**entry, "at": clock.local(entry["at"]).strftime("%Y-%m-%d %H:%M:%S")}
            for entry in store.activity(keep, server.now())
        ]
        from policy.report import timezone_note

        return _json(200, {"entries": entries, "keep_days": keep, "times": timezone_note(None if policy is None else policy.timezone)})

    @app.get("/parent/api/settings/mcp/connect")
    async def connect_page(request: Request) -> Response:
        parent, refused = gate.parent(request)
        if refused is not None or parent is None:
            return refused
        found = store.request(request.query_params.get("request", ""), server.now())
        if server.settings is None:
            return _json(200, {"problem": "The MCP server is off, so no agent can be approved."})
        if found is None:
            return _json(200, {"problem": _UNKNOWN_REQUEST})
        client = store.client(found.client_id)
        shown = {
            "request": found.id,
            "agent": client.name if client is not None else "",
            "client_id": found.client_id,
            "redirect_uri": found.redirect_uri if client is not None and _registered(found.redirect_uri, client) else "",
            "permissions": _granted(for_role(server.settings, parent.role)),
            "problem": found.problem,
            "reviewer": parent.role == REVIEWER,
        }
        return _json(200, shown)

    @app.post("/parent/api/settings/mcp/connect")
    async def connect_decide(request: Request) -> Response:
        body, parent, refused = await gate.acting_parent(request)
        if refused is not None or parent is None:
            return refused
        username = parent.username
        if server.settings is None:
            return _json(400, {"error": "The MCP server is off, so no agent can be approved."})
        found = store.request(str(body.get("request", "")), server.now())
        if found is None:
            return _json(400, {"error": _UNKNOWN_REQUEST})
        client = store.client(found.client_id)
        if found.problem or client is None or not _registered(found.redirect_uri, client):
            return _json(400, {"error": found.problem or _UNKNOWN_REQUEST})
        decision = body.get("decision")
        if decision == "approve" and not parent.admin and not _granted(for_role(server.settings, parent.role)):
            return _json(400, {"error": _NOTHING_FOR_REVIEWER})
        if decision == "approve":
            account = server.accounts.account_id(username)
            if account is None:
                return _json(400, {"error": "The signed-in parent has no account."})
            code = store.approve(found, client, account, server.now())
            answer = {"code": code}
        elif decision == "deny":
            store.drop_request(found.id)
            answer = {"error": "access_denied"}
        else:
            return _json(400, {"error": "Choose Approve or Deny."})
        if found.state is not None:
            answer["state"] = found.state
        answer["iss"] = server.base(request)
        joiner = "&" if urlsplit(found.redirect_uri).query else "?"
        return _json(200, {"location": found.redirect_uri + joiner + urlencode(answer)})


def page_body(server: McpServer) -> dict:
    """Return the MCP page: the file's settings, its problems, the endpoint, and the connections."""
    on_disk = mcp_settings.load(server.path)
    if on_disk.settings is not None:
        shown = on_disk.settings
    elif on_disk.exists:
        # A file with problems: the page offers the defaults, and saving writes them over it.
        shown = replace(mcp_settings.DEFAULTS, enabled=False)
    else:
        # No file: turning the server on gives read on every class and nothing else.
        shown = replace(FIRST_TIME, enabled=False)
    in_force = server.state.settings
    connections = server.store.connections(in_force if server.state.on else None, server.now())
    clock = server.loaded().clock
    return {
        "exists": on_disk.exists,
        "on": server.state.on,
        "problems": list(on_disk.problems),
        "version": on_disk.version,
        "file": str(server.path),
        "endpoint": server.endpoint(),
        "settings": shown.as_json(),
        "classes": [{"name": name, "permissions": list(permissions)} for name, permissions in CLASSES.items()],
        "connections": [
            {
                "id": found.id,
                "agent": found.client_name,
                "parent": found.username,
                "role": found.role,
                "approved": _shown_time(clock, found.approved_at),
                "last_used": _shown_time(clock, found.last_used_at),
                "lapses": _shown_time(clock, found.lapses_at(in_force)) if in_force is not None else "",
            }
            for found in connections
        ],
    }


def _shown_time(clock, moment: datetime) -> str:
    return clock.local(moment).strftime("%Y-%m-%d %H:%M")


def _granted(settings: McpSettings) -> list[dict]:
    return [
        {"name": name, "permissions": mcp_settings.ordered(settings.permissions.get(name, ()))}
        for name in CLASSES
        if settings.permissions.get(name)
    ]


def _write(path: Path, text: str, exists: bool) -> None:
    if exists and path.exists():
        replace_text(path, text)
        return
    make_directory(path.parent)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.saving")
    try:
        temporary.write_text(text, encoding="utf-8")
        own_like(temporary, path.parent.stat())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _commit(server: McpServer, username: str, warnings: list[str]) -> None:
    """Commit mcp.yaml as a portal save does: any other hand edits first, as their own version."""
    history = History(server.path.parent)
    if not history.kept:
        return
    when = server.now()
    try:
        others = [name for name in history.changed() if name != server.path.name]
        if others:
            history.commit(f"{stamp(when)} hand edits found before a portal save", username, when, None)
        history.commit(f"{stamp(when)} {username}: saved MCP settings", username, when, [server.path.name])
    except HistoryError as error:
        print(f"the MCP settings save is not in the config history: {error}", flush=True)
        warnings.append(f"This change is not in the config history, because git could not commit it: {error}")


async def _client_for(store: McpStore, client_id: str, now: datetime) -> tuple[Client | None, str | None]:
    """Return the registered client, fetching a Client ID Metadata Document for an https client id."""
    if client_id.startswith("https://"):
        try:
            name, uris = await run_in_threadpool(_fetch_document, client_id)
        except (OSError, ValueError) as error:
            return None, f"The agent's client document at {client_id} could not be read: {error}"
        return store.register(name, uris, now, client_id=client_id), None
    client = store.client(client_id)
    if client is None:
        return None, "This agent is not registered here, or its registration has expired. Connect it again from the agent."
    return client, None


def _fetch_document(url: str) -> tuple[str, tuple[str, ...]]:
    request = urllib.request.Request(url, headers={"accept": "application/json", "user-agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=5) as response:
        raw = response.read(_LONGEST_DOCUMENT + 1)
    if len(raw) > _LONGEST_DOCUMENT:
        raise ValueError("it is too long")
    document = json.loads(raw)
    if not isinstance(document, dict) or document.get("client_id") != url:
        raise ValueError("its client_id is not its own address")
    uris, problem = _redirect_uris(document.get("redirect_uris"))
    if problem is not None:
        raise ValueError(problem)
    return _client_name(document.get("client_name")), uris


def _request_problem(asked: Mapping[str, str], client: Client | None, resources: set[str]) -> str | None:
    if client is None:
        return "This agent is not registered here."
    if not _registered(asked.get("redirect_uri", ""), client):
        return "The agent asked to return to an address it did not register, so it cannot be approved."
    if asked.get("response_type") != "code":
        return "The agent asked for a response type other than code, so it cannot be approved."
    if not asked.get("code_challenge") or asked.get("code_challenge_method") != "S256":
        return "The agent did not use PKCE with S256, so it cannot be approved."
    if asked.get("resource", "").rstrip("/") not in resources:
        return "The agent did not name this MCP server as the resource, so it cannot be approved."
    return None


def _registered(uri: str, client: Client) -> bool:
    """Whether uri is one the client registered; on an http loopback address any port matches (RFC 8252 7.3)."""
    if uri in client.redirect_uris:
        return True
    asked = urlsplit(uri)
    if asked.scheme != "http" or (asked.hostname or "") not in _LOOPBACK_HOSTS:
        return False
    try:
        asked.port
    except ValueError:
        return False
    for registered in client.redirect_uris:
        known = urlsplit(registered)
        if (known.scheme, known.hostname, known.path, known.query) == (asked.scheme, asked.hostname, asked.path, asked.query):
            return True
    return False


def _redirect_uris(value: object) -> tuple[tuple[str, ...], str | None]:
    if not isinstance(value, list) or not value or not all(isinstance(uri, str) for uri in value):
        return (), "redirect_uris must list at least one address."
    for uri in value:
        parts = urlsplit(uri)
        if parts.fragment or not parts.netloc:
            return (), f"{uri} is not an address an agent can return to."
        if parts.scheme == "https" or (parts.scheme == "http" and (parts.hostname or "") in _LOOPBACK_HOSTS):
            continue
        return (), f"{uri} must be https, or http on this machine's loopback address."
    return tuple(value), None


def _client_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return "Unnamed agent"
    return "".join(char for char in value.strip() if char.isprintable())[:_LONGEST_NAME]


def _form(raw: bytes) -> dict[str, str]:
    try:
        return dict(parse_qsl(raw.decode("utf-8"), keep_blank_values=True))
    except UnicodeDecodeError:
        return {}


def _json(status: int, body: dict) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={"cache-control": "no-store"})


def _oauth_error(status: int, error: str, description: str) -> JSONResponse:
    return _json(status, {"error": error, "error_description": description})

