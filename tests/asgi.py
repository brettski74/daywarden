"""Call the policy service's ASGI app in process, as the HTTP or HTTPS listener would."""

import asyncio
import json


def call(app, method, path, *, query="", body=b"", cookie=None, content_type=None, scheme="https", json_body=None):
    """Return the status, the body text, and the headers, each header a list of values."""
    if json_body is not None:
        body = json.dumps(json_body).encode()
        content_type = content_type or "application/json"
    messages = []
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            # A client that stays connected until the response is sent.
            await asyncio.Event().wait()
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    headers = []
    if content_type:
        headers.append((b"content-type", content_type.encode()))
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": scheme,
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode() if isinstance(query, str) else query,
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8443 if scheme == "https" else 8090),
        "root_path": "",
    }
    asyncio.run(app(scope, receive, send))
    start = next(item for item in messages if item["type"] == "http.response.start")
    payload = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
    found: dict[str, list[str]] = {}
    for key, value in start["headers"]:
        found.setdefault(key.decode(), []).append(value.decode())
    return start["status"], payload.decode("utf-8", "replace"), found


def session_cookie(headers) -> str:
    """Return the Cookie header value for the session a sign-in set."""
    return headers["set-cookie"][0].split(";", 1)[0]
