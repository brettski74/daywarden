"""The parent portal on the HTTPS listener.

The portal is a React app built into PORTAL_DIR. Every /parent/... address
that is not a built file and not under /parent/api/ returns its index.html,
so a deep link and Reload open the right page. The shell and its files carry
no household data.

Household data comes only from JSON under /parent/api/, and the spelling
recordings the task pages play. Those endpoints need a parent session from
S007.1. With no session they answer 401, and with no parent account 403,
with no data. They never redirect: only the portal's own code reacts to
those answers. Sign-in, sign-out, the parent check, a task save, creating
or renaming a task, making a spelling directory, Retire, cutting or keeping
a recording, each step of a setup of spelling words, and saving or deleting a
usage preset are JSON POSTs, and a POST whose body is not
application/json is refused, so a form on another site cannot use the
parent's cookie to act. The one exception is the upload of a recording,
which is the raw audio, and must be audio/webm or audio/ogg. A form cannot
send either, and a script on another site would need a CORS preflight,
which is never approved.

Each account is an admin or a reviewer (S043). A reviewer may use only the
data addresses in ``REVIEWER_ADDRESSES``. Every other address answers a
reviewer 403 with no household data, so a new endpoint is admin-only unless
it is added to that list. See Access control in docs/parent-portal.md.

Sign-in returns a page address for the portal to open. ``safe_next`` keeps
that to a portal page, never a data address, a file, the sign-in screen, or
another site.

Plain HTTP does not return a portal page, set the cookie, or act.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from policy.accounts import COOKIE_NAME, Accounts, Parent, cookie_value
from policy.hierarchy import Policy
from policy.recordings import LONGEST_TAKE_BYTES, TOO_LONG, RecordingError, Recordings, cut_settings, take_type
from policy.review import NOT_STORED, attempt_report, attempts_report, facts_report, record_parent_check, trend_report, words_report
from policy.sounds import media_type
from policy.spelling_directories import from_query
from policy.policy_admin import PolicyChanges
from policy.pool_admin import CAPITALISATION, PoolAdmin
from policy.task_admin import TaskAdmin, missing
from policy.task_create import TaskChanges
from policy.tasks import AttemptStore, TaskKey
from policy.usage import UsageStore
from policy.usage_graph import UNITS, Presets, usage_graph
from policy.usage_requests import usage_requests
from policy.week import Weeks

PORTAL_DIR = Path(__file__).resolve().parent / "portal" / "dist"
HOME = "/parent/"
# Vite writes the hashed scripts and stylesheets under /parent/build/. /parent/assets/ is Asset Administration.
BUILT = "build/"
# Addresses under /parent/ that are not portal pages.
# A sign-in body holds a username, a password of at most 200 characters, and the page to return to.
_LONGEST_SIGN_IN = 4096
_NOT_PAGES = frozenset({"api", "build", "login"})
_CLOSED = "The parent portal is closed until a parent account is added."
_SIGNED_OUT = "Sign in to see this."
_HTTPS_ONLY = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Parent pages</title>
</head>
<body>
<h1>Parent pages</h1>
<p>Open this page over HTTPS.</p>
</body>
</html>
"""
_NOT_BUILT = "The parent portal is not built into this image."
NO_FRAMES = {"content-security-policy": "frame-ancestors 'none'", "x-frame-options": "DENY"}
# The data addresses a reviewer may use, as (method, route template). Sign-in and sign-out need no session.
# Any address not listed here answers a reviewer 403. Add one only under the rule in docs/parent-portal.md.
REVIEWER_ADDRESSES = frozenset(
    {
        ("GET", "/parent/api/session"),
        ("GET", "/parent/api/attempts"),
        ("GET", "/parent/api/attempts/tasks/{kind}/{name}"),
        ("GET", "/parent/api/attempts/facts/{operation}"),
        ("GET", "/parent/api/attempts/words"),
        ("GET", "/parent/api/attempts/{attempt_id}"),
        # The one reviewer write: a parent check, for work done outside the system.
        ("POST", "/parent/api/parent-check"),
        ("GET", "/parent/api/usage/requests"),
        ("GET", "/parent/api/usage/{unit}"),
        # The MCP consent page. A reviewer's agent is limited to what a reviewer may read.
        ("GET", "/parent/api/settings/mcp/connect"),
        ("POST", "/parent/api/settings/mcp/connect"),
    }
)


def safe_next(value: object) -> str:
    """Return value when it is a portal page address, otherwise the portal home.

    A page address is a path under /parent/, with its query string. It is not
    under /parent/api/ or /parent/build/, it is not the sign-in screen, and
    its last segment is not a file name. Another site, a scheme, a host, and
    a path that climbs out with ``..`` all return the home.
    """
    if not isinstance(value, str) or value == "":
        return HOME
    if any(ord(char) < 0x20 or ord(char) == 0x7F or char == "\\" for char in value):
        return HOME
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or not parts.path.startswith(HOME):
        return HOME
    segments = unquote(parts.path).split("/")[2:]
    if any(segment in (".", "..") for segment in segments) or "" in segments[:-1]:
        return HOME
    if segments[0] in _NOT_PAGES or "." in segments[-1]:
        return HOME
    return parts.path + ("?" + parts.query if parts.query else "")


def client_names(policy: Policy | None) -> tuple[str, ...]:
    """Return the client groups a parent can review, including ``default``."""
    if policy is None:
        return ()
    names = [group.name for group in policy.client_groups]
    if "default" not in names:
        names.append("default")
    return tuple(names)


def reviewer_may(request: Request) -> bool:
    """Whether the data address this request matched is one a reviewer may use."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path is not None and (request.method, path) in REVIEWER_ADDRESSES


class PortalGate:
    """The parent session checks every data endpoint makes, for endpoints added outside ``install_portal``."""

    def __init__(self, accounts: Accounts, loaded: Callable[[], object]) -> None:
        self.accounts = accounts
        self.loaded = loaded

    def parent(self, request: Request) -> tuple[Parent | None, Response | None]:
        """Return the signed-in account and its role, or the refusal to send instead.

        A reviewer is refused with 403 at any address not in ``REVIEWER_ADDRESSES``.
        """
        if request.url.scheme != "https":
            return None, _json(403, {"error": "Open this page over HTTPS."})
        if self.accounts.count() == 0:
            return None, _json(403, {"error": _CLOSED, "closed": True})
        parent = self.accounts.accept(_cookie(request), self.loaded().clock.local())
        if parent is None:
            return None, _json(401, {"error": _SIGNED_OUT})
        if not parent.admin and not reviewer_may(request):
            return None, _json(
                403,
                {"error": f"This address is for admins. You are signed in as {parent.username}, a reviewer.", "admins_only": True},
            )
        return parent, None

    def guard(self, request: Request) -> tuple[str | None, Response | None]:
        """Return the signed-in username, or the refusal to send instead."""
        parent, refused = self.parent(request)
        return (None if parent is None else parent.username), refused

    async def acting(self, request: Request) -> tuple[dict, str, Response | None]:
        """Return a state-changing request's JSON body and the signed-in username, or the refusal to send instead."""
        body, parent, refused = await self.acting_parent(request)
        return body, "" if parent is None else parent.username, refused

    async def acting_parent(self, request: Request) -> tuple[dict, Parent | None, Response | None]:
        """Return a state-changing request's JSON body and the signed-in account, or the refusal to send instead."""
        if request.url.scheme != "https":
            return {}, None, _json(403, {"error": "Open this page over HTTPS."})
        body, refused = await _json_body(request)
        if refused is not None:
            return {}, None, refused
        parent, refused = self.parent(request)
        if refused is not None:
            return {}, None, refused
        return body, parent, None


def install_portal(
    app: FastAPI,
    *,
    loaded: Callable[[], object],
    accounts: Accounts,
    attempts: AttemptStore,
    usage_store: UsageStore,
    tasks: TaskAdmin | None = None,
    portal_dir: Path = PORTAL_DIR,
) -> None:
    """Add the portal, its data endpoints, and the old parent addresses to app.

    loaded returns the policy in force, with ``policy`` and ``clock``.
    tasks reads and saves the task pages, and keeps recordings.
    Handlers are async so they stay on the event-loop thread, where this
    process's SQLite connection lives. Storing and cutting a recording run on
    a worker thread, so ffmpeg never holds up the proxy's decisions.
    """
    root = portal_dir.resolve()
    recordings = tasks.recordings if tasks is not None else Recordings()
    weeks = Weeks(tasks) if tasks is not None else None
    changes = TaskChanges(tasks, weeks) if tasks is not None and weeks is not None else None
    presets = Presets(usage_store.connection)
    pools = PoolAdmin(tasks) if tasks is not None else None
    policy_changes = PolicyChanges(tasks) if tasks is not None else None
    capitalisation_pools = PoolAdmin(tasks, CAPITALISATION) if tasks is not None else None
    gate = PortalGate(accounts, loaded)
    guard = gate.guard
    acting = gate.acting

    @app.get("/parent/api/session")
    async def session(request: Request) -> Response:
        parent, refused = gate.parent(request)
        if refused is not None or parent is None:
            return refused
        return _json(200, {"username": parent.username, "role": parent.role})

    @app.post("/parent/api/login")
    async def login(request: Request) -> Response:
        if request.url.scheme != "https":
            return _json(403, {"error": "Open this page over HTTPS."})
        body, refused = await _json_body(request, _LONGEST_SIGN_IN)
        if refused is not None:
            return refused
        if accounts.count() == 0:
            return _json(403, {"error": _CLOSED, "closed": True})
        key = accounts.login(body.get("username", ""), body.get("password", ""), loaded().clock.local())
        if key is None:
            return _json(401, {"error": "Username or password incorrect."})
        response = _json(200, {"next": safe_next(body.get("next"))})
        response.headers.append("set-cookie", accounts.cookie_header(key))
        return response

    @app.post("/parent/api/logout")
    async def logout(request: Request) -> Response:
        if request.url.scheme != "https":
            return _json(403, {"error": "Open this page over HTTPS."})
        _body, refused = await _json_body(request)
        if refused is not None:
            return refused
        accounts.end(_cookie(request))
        response = _json(200, {"signed_out": True})
        response.headers.append("set-cookie", accounts.clear_cookie_header())
        return response

    @app.get("/parent/api/attempts")
    async def attempt_list(request: Request) -> Response:
        _username, refused = guard(request)
        if refused is not None:
            return refused
        now = loaded()
        policy = now.policy
        return _json(
            200,
            attempts_report(
                attempts,
                client_names(policy),
                request.query_params.get("client", ""),
                now=now.clock.local(),
                tasks=() if policy is None else policy.tasks,
                timezone=None if policy is None else policy.timezone,
                pairs=list(request.query_params.multi_items()),
            ),
        )

    @app.get("/parent/api/attempts/tasks/{kind}/{name}")
    async def attempt_trend(request: Request, kind: str, name: str) -> Response:
        _username, refused = guard(request)
        if refused is not None:
            return refused
        now = loaded()
        policy = now.policy
        return _json(
            200,
            trend_report(
                attempts,
                client_names(policy),
                TaskKey(kind, name),
                now=now.clock.local(),
                tasks=() if policy is None else policy.tasks,
                timezone=None if policy is None else policy.timezone,
                pairs=list(request.query_params.multi_items()),
            ),
        )

    @app.get("/parent/api/attempts/facts/{operation}")
    async def attempt_facts(request: Request, operation: str) -> Response:
        _username, refused = guard(request)
        if refused is not None:
            return refused
        now = loaded()
        policy = now.policy
        return _json(
            200,
            facts_report(
                attempts,
                client_names(policy),
                operation,
                now=now.clock.local(),
                timezone=None if policy is None else policy.timezone,
                pairs=list(request.query_params.multi_items()),
            ),
        )

    @app.get("/parent/api/attempts/words")
    async def attempt_words(request: Request) -> Response:
        _username, refused = guard(request)
        if refused is not None:
            return refused
        now = loaded()
        policy = now.policy
        return _json(
            200,
            words_report(
                attempts,
                client_names(policy),
                now=now.clock.local(),
                tasks=() if policy is None else policy.tasks,
                timezone=None if policy is None else policy.timezone,
                pairs=list(request.query_params.multi_items()),
            ),
        )

    @app.get("/parent/api/attempts/{attempt_id}")
    async def attempt(request: Request, attempt_id: str) -> Response:
        _username, refused = guard(request)
        if refused is not None:
            return refused
        now = loaded()
        timezone = None if now.policy is None else now.policy.timezone
        found = attempt_report(attempts, attempt_id, now=now.clock.local(), timezone=timezone)
        if found is None:
            return _json(404, {"error": NOT_STORED})
        return _json(200, found)

    @app.post("/parent/api/parent-check")
    async def parent_check(request: Request) -> Response:
        if request.url.scheme != "https":
            return _json(403, {"error": "Open this page over HTTPS."})
        body, refused = await _json_body(request)
        if refused is not None:
            return refused
        _username, refused = guard(request)
        if refused is not None:
            return refused
        now = loaded()
        policy = now.policy
        client = body.get("client")
        problem = record_parent_check(
            accounts,
            attempts,
            client,
            now=now.clock.local(),
            tasks=() if policy is None else policy.tasks,
            clients=client_names(policy),
        )
        if problem is not None:
            return _json(400, {"error": problem})
        return _json(200, {"message": f"Recorded a parent check for {client.strip()}."})

    @app.post("/parent/api/usage/presets")
    async def preset_save(request: Request) -> Response:
        body, username, refused = await acting(request)
        if refused is not None:
            return refused
        answer = presets.save(body, username, loaded().clock.local())
        return _json(answer.status, answer.body)

    @app.post("/parent/api/usage/presets/delete")
    async def preset_delete(request: Request) -> Response:
        body, _username, refused = await acting(request)
        if refused is not None:
            return refused
        answer = presets.delete(body)
        return _json(answer.status, answer.body)

    @app.get("/parent/api/usage/requests")
    async def usage_request_table(request: Request) -> Response:
        _username, refused = guard(request)
        if refused is not None:
            return refused
        now = loaded()
        pairs = list(request.query_params.multi_items())
        return _json(200, usage_requests(now.policy, usage_store, presets, pairs, now.clock.local()))

    @app.get("/parent/api/usage/{unit}")
    async def usage(request: Request, unit: str) -> Response:
        _username, refused = guard(request)
        if refused is not None:
            return refused
        if unit not in UNITS:
            return _json(404, {"error": "Not found."})
        now = loaded()
        pairs = list(request.query_params.multi_items())
        return _json(200, usage_graph(now.policy, usage_store, presets, pairs, now.clock.local(), unit))

    @app.get("/parent/api/policy/{page}")
    async def policy_page(request: Request, page: str) -> Response:
        _username, refused = guard(request)
        if refused is not None:
            return refused
        if policy_changes is None:
            return _json(404, {"error": f"{page} is not a policy page."})
        answer = policy_changes.page(page)
        return _json(answer.status, answer.body)

    @app.post("/parent/api/policy/{page}")
    async def policy_save(request: Request, page: str) -> Response:
        if request.url.scheme != "https":
            return _json(403, {"error": "Open this page over HTTPS."})
        body, refused = await _json_body(request)
        if refused is not None:
            return refused
        username, refused = guard(request)
        if refused is not None:
            return refused
        if policy_changes is None:
            return _json(404, {"error": f"{page} is not a policy page."})
        answer = policy_changes.save_page(page, body, username)
        return _json(answer.status, answer.body)

    @app.post("/parent/api/policy/{page}/rename")
    async def policy_rename(request: Request, page: str) -> Response:
        body, username, refused = await acting(request)
        if refused is not None:
            return refused
        if policy_changes is None:
            return _json(404, {"error": f"{page} is not a policy page."})
        answer = policy_changes.rename_page(page, body, username)
        return _json(answer.status, answer.body)

    @app.get("/parent/api/tasks")
    async def task_list(request: Request) -> Response:
        _username, refused = guard(request)
        if refused is not None:
            return refused
        return _json(200, {"tasks": [] if tasks is None else tasks.catalogue()})

    @app.get("/parent/api/tasks/{kind}/{name}")
    async def task_page(request: Request, kind: str, name: str) -> Response:
        _username, refused = guard(request)
        if refused is not None:
            return refused
        if tasks is None:
            return _json(404, {"error": missing(TaskKey(kind, name))})
        answer = tasks.page(TaskKey(kind, name))
        if answer.status == 200 and "spelling" in answer.body and weeks is not None:
            answer.body["spelling"]["setup"] = weeks.progress(name)
        return _json(answer.status, answer.body)

    @app.post("/parent/api/tasks/{kind}/{name}/directories")
    async def task_directory(request: Request, kind: str, name: str) -> Response:
        body, _username, refused = await acting(request)
        if refused is not None:
            return refused
        if tasks is None:
            return _json(404, {"error": missing(TaskKey(kind, name))})
        answer = tasks.make_folder(TaskKey(kind, name), body)
        return _json(answer.status, answer.body)

    @app.post("/parent/api/new-task/directories")
    async def new_task_directory(request: Request) -> Response:
        body, _username, refused = await acting(request)
        if refused is not None:
            return refused
        if tasks is None:
            return _json(404, {"error": "Tasks cannot be created here."})
        answer = tasks.make_folder(None, body)
        return _json(answer.status, answer.body)

    @app.post("/parent/api/tasks/{kind}/{name}")
    async def task_save(request: Request, kind: str, name: str) -> Response:
        if request.url.scheme != "https":
            return _json(403, {"error": "Open this page over HTTPS."})
        body, refused = await _json_body(request)
        if refused is not None:
            return refused
        username, refused = guard(request)
        if refused is not None:
            return refused
        if tasks is None:
            return _json(404, {"error": missing(TaskKey(kind, name))})
        answer = tasks.save(TaskKey(kind, name), body, username)
        return _json(answer.status, answer.body)

    @app.post("/parent/api/tasks/{kind}/{name}/retire")
    async def task_retire(request: Request, kind: str, name: str) -> Response:
        if request.url.scheme != "https":
            return _json(403, {"error": "Open this page over HTTPS."})
        body, refused = await _json_body(request)
        if refused is not None:
            return refused
        _username, refused = guard(request)
        if refused is not None:
            return refused
        if tasks is None:
            return _json(404, {"error": missing(TaskKey(kind, name))})
        answer = tasks.retire(TaskKey(kind, name), body.get("word"))
        return _json(answer.status, answer.body)

    @app.post("/parent/api/tasks/{kind}/{name}/recordings")
    async def task_keep(request: Request, kind: str, name: str) -> Response:
        if request.url.scheme != "https":
            return _json(403, {"error": "Open this page over HTTPS."})
        body, refused = await _json_body(request)
        if refused is not None:
            return refused
        _username, refused = guard(request)
        if refused is not None:
            return refused
        if tasks is None:
            return _json(404, {"error": missing(TaskKey(kind, name))})
        answer = tasks.keep(TaskKey(kind, name), body)
        return _json(answer.status, answer.body)

    @app.post("/parent/api/tasks/{kind}/{name}/rename")
    async def task_rename(request: Request, kind: str, name: str) -> Response:
        body, username, refused = await acting(request)
        if refused is not None:
            return refused
        if changes is None:
            return _json(404, {"error": missing(TaskKey(kind, name))})
        answer = changes.rename(TaskKey(kind, name), body, username)
        return _json(answer.status, answer.body)

    @app.get("/parent/api/new-task")
    async def new_task_page(request: Request) -> Response:
        _username, refused = guard(request)
        if refused is not None:
            return refused
        if changes is None:
            return _json(404, {"error": "Tasks cannot be created here."})
        return _json(200, changes.blank())

    @app.post("/parent/api/new-task/check")
    async def new_task_check(request: Request) -> Response:
        body, _username, refused = await acting(request)
        if refused is not None:
            return refused
        if changes is None:
            return _json(404, {"error": "Tasks cannot be created here."})
        answer = changes.lock(body)
        if answer.status == 200 and "spelling" in answer.body and weeks is not None:
            answer.body["spelling"]["setup"] = weeks.progress(answer.body["name"])
        return _json(answer.status, answer.body)

    @app.post("/parent/api/new-task")
    async def new_task_create(request: Request) -> Response:
        body, username, refused = await acting(request)
        if refused is not None:
            return refused
        if changes is None:
            return _json(404, {"error": "Tasks cannot be created here."})
        answer = changes.create(body, username)
        return _json(answer.status, answer.body)

    def pool_routes(address: str, admin: PoolAdmin | None, label: str) -> None:
        """Add the list, make, page, save, rename, and delete addresses of one kind of pool."""
        unavailable = f"{label} pools cannot be edited here."
        base = f"/parent/api/{address}"

        @app.get(base)
        async def pool_list(request: Request) -> Response:
            _username, refused = guard(request)
            if refused is not None:
                return refused
            return _json(200, {"pools": []} if admin is None else admin.catalogue())

        @app.post(base)
        async def pool_create(request: Request) -> Response:
            body, username, refused = await acting(request)
            if refused is not None:
                return refused
            if admin is None:
                return _json(404, {"error": unavailable})
            answer = admin.create(body, username)
            return _json(answer.status, answer.body)

        @app.get(base + "/{pool_id}")
        async def pool_page(request: Request, pool_id: str) -> Response:
            _username, refused = guard(request)
            if refused is not None:
                return refused
            if admin is None:
                return _json(404, {"error": unavailable})
            answer = admin.page(pool_id)
            return _json(answer.status, answer.body)

        @app.post(base + "/{pool_id}")
        async def pool_save(request: Request, pool_id: str) -> Response:
            body, username, refused = await acting(request)
            if refused is not None:
                return refused
            if admin is None:
                return _json(404, {"error": unavailable})
            answer = admin.save(pool_id, body, username)
            return _json(answer.status, answer.body)

        @app.post(base + "/{pool_id}/rename")
        async def pool_rename(request: Request, pool_id: str) -> Response:
            body, username, refused = await acting(request)
            if refused is not None:
                return refused
            if admin is None:
                return _json(404, {"error": unavailable})
            answer = admin.rename(pool_id, body, username)
            return _json(answer.status, answer.body)

        @app.post(base + "/{pool_id}/delete")
        async def pool_delete(request: Request, pool_id: str) -> Response:
            body, username, refused = await acting(request)
            if refused is not None:
                return refused
            if admin is None:
                return _json(404, {"error": unavailable})
            answer = admin.delete(pool_id, body, username)
            return _json(answer.status, answer.body)

    pool_routes("parts-of-speech-pools", pools, "Parts of speech")
    pool_routes("capitalisation-pools", capitalisation_pools, "Capitalisation")

    @app.get("/parent/api/new-task/audio/{pool}/{file_name}")
    async def new_task_audio(request: Request, pool: str, file_name: str) -> Response:
        _username, refused = guard(request)
        if refused is not None:
            return refused
        found = None if tasks is None else tasks.audio(None, pool, file_name, from_query(request.query_params))
        if found is None:
            return _json(404, {"error": "There is no such recording."})
        return FileResponse(found, media_type=media_type(found.name), headers={"cache-control": "private, no-store"})

    @app.get("/parent/api/tasks/{kind}/{name}/week")
    async def week_page(request: Request, kind: str, name: str) -> Response:
        _username, refused = guard(request)
        if refused is not None:
            return refused
        if weeks is None:
            return _json(404, {"error": missing(TaskKey(kind, name))})
        answer = weeks.page(TaskKey(kind, name), request.query_params)
        return _json(answer.status, answer.body)

    @app.post("/parent/api/tasks/{kind}/{name}/week")
    async def week_save(request: Request, kind: str, name: str) -> Response:
        body, _username, refused = await acting(request)
        if refused is not None:
            return refused
        if weeks is None:
            return _json(404, {"error": missing(TaskKey(kind, name))})
        answer = weeks.save(TaskKey(kind, name), body)
        return _json(answer.status, answer.body)

    @app.post("/parent/api/tasks/{kind}/{name}/week/recordings")
    async def week_keep(request: Request, kind: str, name: str) -> Response:
        body, _username, refused = await acting(request)
        if refused is not None:
            return refused
        if weeks is None:
            return _json(404, {"error": missing(TaskKey(kind, name))})
        answer = weeks.keep(TaskKey(kind, name), body)
        return _json(answer.status, answer.body)

    @app.post("/parent/api/tasks/{kind}/{name}/week/cancel")
    async def week_cancel(request: Request, kind: str, name: str) -> Response:
        _body, _username, refused = await acting(request)
        if refused is not None:
            return refused
        if weeks is None:
            return _json(404, {"error": missing(TaskKey(kind, name))})
        answer = weeks.cancel(TaskKey(kind, name))
        return _json(answer.status, answer.body)

    @app.post("/parent/api/tasks/{kind}/{name}/week/apply")
    async def week_apply(request: Request, kind: str, name: str) -> Response:
        body, username, refused = await acting(request)
        if refused is not None:
            return refused
        if weeks is None:
            return _json(404, {"error": missing(TaskKey(kind, name))})
        answer = weeks.apply(TaskKey(kind, name), body, username)
        return _json(answer.status, answer.body)

    @app.get("/parent/api/tasks/{kind}/{name}/week/clips/{file_name}")
    async def week_clip(request: Request, kind: str, name: str, file_name: str) -> Response:
        _username, refused = guard(request)
        if refused is not None:
            return refused
        found = None if weeks is None else weeks.clip(TaskKey(kind, name), file_name)
        if found is None:
            return _json(404, {"error": "There is no such recording."})
        return FileResponse(found, media_type="audio/ogg", headers={"cache-control": "private, no-store"})

    @app.post("/parent/api/recordings")
    async def recording_upload(request: Request) -> Response:
        if request.url.scheme != "https":
            return _json(403, {"error": "Open this page over HTTPS."})
        extension = take_type(request.headers.get("content-type", ""))
        if extension is None:
            return _json(415, {"error": "Send a recording as audio/webm or audio/ogg."})
        _username, refused = guard(request)
        if refused is not None:
            return refused
        body, refused = await _limited_body(request, LONGEST_TAKE_BYTES)
        if refused is not None:
            return refused
        try:
            take = await run_in_threadpool(recordings.store, body, extension)
        except RecordingError as error:
            return _refused(error)
        return _json(200, {"take": take})

    @app.post("/parent/api/recordings/{take}/cut")
    async def recording_cut(request: Request, take: str) -> Response:
        if request.url.scheme != "https":
            return _json(403, {"error": "Open this page over HTTPS."})
        body, refused = await _json_body(request)
        if refused is not None:
            return refused
        _username, refused = guard(request)
        if refused is not None:
            return refused
        try:
            settings = cut_settings(body.get("settings"))
            return _json(200, await run_in_threadpool(recordings.cut, take, settings))
        except RecordingError as error:
            return _refused(error)

    @app.post("/parent/api/recordings/{take}/discard")
    async def recording_discard(request: Request, take: str) -> Response:
        if request.url.scheme != "https":
            return _json(403, {"error": "Open this page over HTTPS."})
        _body, refused = await _json_body(request)
        if refused is not None:
            return refused
        _username, refused = guard(request)
        if refused is not None:
            return refused
        recordings.discard(take)
        return _json(200, {"discarded": True})

    @app.get("/parent/api/recordings/{take}/{file_name}")
    async def recording_clip(request: Request, take: str, file_name: str) -> Response:
        _username, refused = guard(request)
        if refused is not None:
            return refused
        found = recordings.clip(take, file_name.removesuffix(".opus")) if file_name.endswith(".opus") else None
        if found is None:
            return _json(404, {"error": "There is no such recording."})
        return FileResponse(found, media_type="audio/ogg", headers={"cache-control": "private, no-store"})

    @app.get("/parent/api/tasks/{kind}/{name}/audio/{pool}/{file_name}")
    async def task_audio(request: Request, kind: str, name: str, pool: str, file_name: str) -> Response:
        _username, refused = guard(request)
        if refused is not None:
            return refused
        found = None if tasks is None else tasks.audio(TaskKey(kind, name), pool, file_name, from_query(request.query_params))
        if found is None:
            return _json(404, {"error": "There is no such recording."})
        return FileResponse(found, media_type=media_type(found.name), headers={"cache-control": "private, no-store"})

    @app.api_route("/parent/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def unknown_data(request: Request, rest: str) -> Response:
        if request.url.scheme != "https":
            return _json(403, {"error": "Open this page over HTTPS."})
        return _json(404, {"error": "Not found."})

    @app.get("/parent")
    async def portal_bare(request: Request) -> Response:
        if request.url.scheme != "https":
            return _https_only()
        return RedirectResponse(HOME, status_code=308)

    @app.get("/parent/{path:path}")
    async def portal_page(request: Request, path: str) -> Response:
        if request.url.scheme != "https":
            return _https_only()
        if path and path != "index.html":
            found = (root / path).resolve()
            if found.is_relative_to(root) and found.is_file():
                cache = "public, max-age=31536000, immutable" if path.startswith(BUILT) else "max-age=3600"
                return FileResponse(found, headers={"cache-control": cache})
            if path.startswith(BUILT):
                return PlainTextResponse("not found", status_code=404)
        index = root / "index.html"
        if not index.is_file():
            return PlainTextResponse(_NOT_BUILT, status_code=503, headers={"cache-control": "no-store"})
        # No portal page, the MCP consent page above all, may be shown in a frame on another site.
        return FileResponse(index, media_type="text/html; charset=utf-8", headers={"cache-control": "no-store", **NO_FRAMES})

    @app.get("/")
    async def home(request: Request) -> Response:
        if request.url.scheme != "https":
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return RedirectResponse(HOME, status_code=302)

    @app.get("/usage")
    async def old_usage(request: Request) -> Response:
        # The old report's choices mean nothing to the graph, so they are not carried over.
        if request.url.scheme != "https":
            return _https_only()
        return RedirectResponse("/parent/usage/minutes", status_code=301)

    @app.get("/attempts")
    async def old_attempts(request: Request) -> Response:
        return _moved(request, "/parent/attempts")

    @app.get("/attempts/{attempt_id}")
    async def old_attempt(request: Request, attempt_id: str) -> Response:
        return _moved(request, "/parent/attempts/" + quote(attempt_id, safe=""))


def _moved(request: Request, path: str) -> Response:
    """Send an old parent address to the same page in the portal."""
    if request.url.scheme != "https":
        return _https_only()
    query = request.url.query
    return RedirectResponse(path + ("?" + query if query else ""), status_code=301)


def _https_only() -> Response:
    return Response(_HTTPS_ONLY, status_code=403, media_type="text/html; charset=utf-8", headers={"cache-control": "no-store"})


def _cookie(request: Request) -> str | None:
    return cookie_value(request.headers.get("cookie"), COOKIE_NAME)


def _json(status: int, body: dict) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={"cache-control": "no-store"})


def _refused(error: RecordingError) -> JSONResponse:
    body: dict = {"error": str(error)}
    if error.errors:
        body["errors"] = error.errors
    return _json(error.status, body)


async def _limited_body(request: Request, limit: int, too_long: str = TOO_LONG) -> tuple[bytes, Response | None]:
    """Return a POST body, or a 413 as soon as it is known to be longer than limit."""
    try:
        declared = int(request.headers.get("content-length", "0"))
    except ValueError:
        declared = 0
    if declared > limit:
        return b"", _json(413, {"error": too_long})
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return b"", _json(413, {"error": too_long})
        chunks.append(chunk)
    return b"".join(chunks), None


async def _json_body(request: Request, limit: int | None = None) -> tuple[dict, Response | None]:
    """Return the JSON object in a POST body, or the refusal to send instead.

    With limit, a body longer than limit bytes is refused with 413 before it is read to the end.
    """
    kind = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if kind != "application/json":
        return {}, _json(415, {"error": "Send this as application/json."})
    if limit is None:
        raw = await request.body()
    else:
        raw, refused = await _limited_body(request, limit, "The request is too large.")
        if refused is not None:
            return {}, refused
    try:
        body = json.loads(raw or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}, _json(400, {"error": "The body is not JSON."})
    if not isinstance(body, dict):
        return {}, _json(400, {"error": "The body is not a JSON object."})
    return body, None
