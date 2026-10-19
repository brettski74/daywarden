"""The three decision documents the addon knows how to enforce."""

from __future__ import annotations

from urllib.parse import urlparse

UNAVAILABLE_MESSAGE = "The authorization service is unavailable."
UNRECOGNIZED_MESSAGE = "The authorization service returned an unrecognized decision."


def recognize(document: object) -> dict | None:
    """Return the document when it is one of the three decisions, otherwise None."""
    if not isinstance(document, dict):
        return None
    action = document.get("action")
    if action == "allow" and set(document) == {"action"}:
        return document
    if (
        action == "deny"
        and set(document) == {"action", "status", "message"}
        and document["status"] == 403
        and isinstance(document["message"], str)
    ):
        return document
    if (
        action == "redirect"
        and set(document) == {"action", "status", "location"}
        and document["status"] == 302
        and _absolute_http_url(document["location"])
    ):
        return document
    return None


def _absolute_http_url(value: object) -> bool:
    if not isinstance(value, str) or any(char in value for char in "\r\n\t "):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
