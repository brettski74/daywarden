"""The parent portal on the HTTPS listener.

The portal is a React app built into PORTAL_DIR. Every /parent/... address
that is not a built file and not under /parent/api/ returns its index.html,
so a deep link and Reload open the right page. The shell and its files carry
no household data.

Household data comes only from JSON under /parent/api/, and the spelling
recordings the task pages play. Those endpoints need a parent session from
S007.1. With no session they answer 401, and with no parent account 403,
with no data. They never redirect: only the portal's own code reacts to
those answers. Sign-in, sign-out, the parent check, a task save, Retire,
cutting or keeping a recording, and each step of a new week's spelling words
are JSON POSTs, and a POST whose body is not
application/json is refused, so a form on another site cannot use the
parent's cookie to act. The one exception is the upload of a recording,
which is the raw audio, and must be audio/webm or audio/ogg. A form cannot
send either, and a script on another site would need a CORS preflight,
which is never approved.

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

from policy.accounts import COOKIE_NAME, Accounts, cookie_value
from policy.hierarchy import Policy
from policy.recordings import LONGEST_TAKE_BYTES, TOO_LONG, RecordingError, Recordings, cut_settings, take_type
from policy.report import USAGE_KEYS, usage_report
from policy.review import NOT_STORED, attempt_report, attempts_report, record_parent_check
from policy.sounds import media_type
from policy.task_admin import TaskAdmin
from policy.tasks import AttemptStore
from policy.usage import UsageStore
from policy.week import Weeks

PORTAL_DIR = Path(__file__).resolve().parent / "portal" / "dist"
HOME = "/parent/"
# Addresses under /parent/ that are not portal pages.
_NOT_PAGES = frozenset({"api", "assets", "login"})
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


def safe_next(value: object) -> str:
    """Return value when it is a portal page address, otherwise the portal home.

    A page address is a path under /parent/, with its query string. It is not
    under /parent/api/ or /parent/assets/, it is not the sign-in screen, and
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

    def guard(request: Request) -> tuple[str | None, Response | None]:
        """Return the signed-in username, or the refusal to send instead."""
        if request.url.scheme != "https":
            return None, _json(403, {"error": "Open this page over HTTPS."})
        if accounts.count() == 0:
            return None, _json(403, {"error": _CLOSED, "closed": True})
        username = accounts.accept(_cookie(request), loaded().clock.local())
        if username is None:
            return None, _json(401, {"error": _SIGNED_OUT})
        return username, None

    @app.get("/parent/api/session")
    async def session(request: Request) -> Response:
        username, refused = guard(request)
        if refused is not None:
            return refused
        return _json(200, {"username": username})

    @app.post("/parent/api/login")
    async def login(request: Request) -> Response:
        if request.url.scheme != "https":
            return _json(403, {"error": "Open this page over HTTPS."})
        body, refused = await _json_body(request)
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

    @app.get("/parent/api/usage")
    async def usage(request: Request) -> Response:
        _username, refused = guard(request)
        if refused is not None:
            return refused
        now = loaded()
        query = {key: request.query_params[key] for key in USAGE_KEYS if key in request.query_params}
        return _json(200, usage_report(now.policy, usage_store, query, now.clock.local()))

    @app.get("/parent/api/tasks")
    async def task_list(request: Request) -> Response:
        _username, refused = guard(request)
        if refused is not None:
            return refused
        return _json(200, {"tasks": [] if tasks is None else tasks.names()})

    @app.get("/parent/api/tasks/{name}")
    async def task_page(request: Request, name: str) -> Response:
        _username, refused = guard(request)
        if refused is not None:
            return refused
        if tasks is None:
            return _json(404, {"error": f"There is no task named {name}."})
        answer = tasks.page(name)
        return _json(answer.status, answer.body)

    @app.post("/parent/api/tasks/{name}")
    async def task_save(request: Request, name: str) -> Response:
        if request.url.scheme != "https":
            return _json(403, {"error": "Open this page over HTTPS."})
        body, refused = await _json_body(request)
        if refused is not None:
            return refused
        username, refused = guard(request)
        if refused is not None:
            return refused
        if tasks is None:
            return _json(404, {"error": f"There is no task named {name}."})
        answer = tasks.save(name, body, username)
        return _json(answer.status, answer.body)

    @app.post("/parent/api/tasks/{name}/retire")
    async def task_retire(request: Request, name: str) -> Response:
        if request.url.scheme != "https":
            return _json(403, {"error": "Open this page over HTTPS."})
        body, refused = await _json_body(request)
        if refused is not None:
            return refused
        _username, refused = guard(request)
        if refused is not None:
            return refused
        if tasks is None:
            return _json(404, {"error": f"There is no task named {name}."})
        answer = tasks.retire(name, body.get("word"))
        return _json(answer.status, answer.body)

    @app.post("/parent/api/tasks/{name}/recordings")
    async def task_keep(request: Request, name: str) -> Response:
        if request.url.scheme != "https":
            return _json(403, {"error": "Open this page over HTTPS."})
        body, refused = await _json_body(request)
        if refused is not None:
            return refused
        _username, refused = guard(request)
        if refused is not None:
            return refused
        if tasks is None:
            return _json(404, {"error": f"There is no task named {name}."})
        answer = tasks.keep(name, body)
        return _json(answer.status, answer.body)

    async def acting(request: Request) -> tuple[dict, str, Response | None]:
        """Return a state-changing request's JSON body and the signed-in username, or the refusal to send instead."""
        if request.url.scheme != "https":
            return {}, "", _json(403, {"error": "Open this page over HTTPS."})
        body, refused = await _json_body(request)
        if refused is not None:
            return {}, "", refused
        username, refused = guard(request)
        if refused is not None:
            return {}, "", refused
        return body, username or "", None

    @app.get("/parent/api/tasks/{name}/week")
    async def week_page(request: Request, name: str) -> Response:
        _username, refused = guard(request)
        if refused is not None:
            return refused
        if weeks is None:
            return _json(404, {"error": f"There is no task named {name}."})
        answer = weeks.page(name)
        return _json(answer.status, answer.body)

    @app.post("/parent/api/tasks/{name}/week")
    async def week_save(request: Request, name: str) -> Response:
        body, _username, refused = await acting(request)
        if refused is not None:
            return refused
        if weeks is None:
            return _json(404, {"error": f"There is no task named {name}."})
        answer = weeks.save(name, body)
        return _json(answer.status, answer.body)

    @app.post("/parent/api/tasks/{name}/week/recordings")
    async def week_keep(request: Request, name: str) -> Response:
        body, _username, refused = await acting(request)
        if refused is not None:
            return refused
        if weeks is None:
            return _json(404, {"error": f"There is no task named {name}."})
        answer = weeks.keep(name, body)
        return _json(answer.status, answer.body)

    @app.post("/parent/api/tasks/{name}/week/cancel")
    async def week_cancel(request: Request, name: str) -> Response:
        _body, _username, refused = await acting(request)
        if refused is not None:
            return refused
        if weeks is None:
            return _json(404, {"error": f"There is no task named {name}."})
        answer = weeks.cancel(name)
        return _json(answer.status, answer.body)

    @app.post("/parent/api/tasks/{name}/week/apply")
    async def week_apply(request: Request, name: str) -> Response:
        body, username, refused = await acting(request)
        if refused is not None:
            return refused
        if weeks is None:
            return _json(404, {"error": f"There is no task named {name}."})
        answer = weeks.apply(name, body, username)
        return _json(answer.status, answer.body)

    @app.get("/parent/api/tasks/{name}/week/clips/{file_name}")
    async def week_clip(request: Request, name: str, file_name: str) -> Response:
        _username, refused = guard(request)
        if refused is not None:
            return refused
        found = None if weeks is None else weeks.clip(name, file_name)
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

    @app.get("/parent/api/tasks/{name}/audio/{pool}/{file_name}")
    async def task_audio(request: Request, name: str, pool: str, file_name: str) -> Response:
        _username, refused = guard(request)
        if refused is not None:
            return refused
        found = None if tasks is None else tasks.audio(name, pool, file_name)
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
                cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "max-age=3600"
                return FileResponse(found, headers={"cache-control": cache})
            if path.startswith("assets/"):
                return PlainTextResponse("not found", status_code=404)
        index = root / "index.html"
        if not index.is_file():
            return PlainTextResponse(_NOT_BUILT, status_code=503, headers={"cache-control": "no-store"})
        return FileResponse(index, media_type="text/html; charset=utf-8", headers={"cache-control": "no-store"})

    @app.get("/")
    async def home(request: Request) -> Response:
        if request.url.scheme != "https":
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return RedirectResponse(HOME, status_code=302)

    @app.get("/usage")
    async def old_usage(request: Request) -> Response:
        return _moved(request, "/parent/usage")

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


async def _limited_body(request: Request, limit: int) -> tuple[bytes, Response | None]:
    """Return a POST body, or a 413 as soon as it is known to be longer than limit."""
    try:
        declared = int(request.headers.get("content-length", "0"))
    except ValueError:
        declared = 0
    if declared > limit:
        return b"", _json(413, {"error": TOO_LONG})
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return b"", _json(413, {"error": TOO_LONG})
        chunks.append(chunk)
    return b"".join(chunks), None


async def _json_body(request: Request) -> tuple[dict, Response | None]:
    """Return the JSON object in a POST body, or the refusal to send instead."""
    kind = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if kind != "application/json":
        return {}, _json(415, {"error": "Send this as application/json."})
    try:
        body = json.loads(await request.body() or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}, _json(400, {"error": "The body is not JSON."})
    if not isinstance(body, dict):
        return {}, _json(400, {"error": "The body is not a JSON object."})
    return body, None
