"""The "Not allowed" page the addon answers a deny with.

The owl is embedded in the page, so showing it makes no request to the
blocked site or to the policy server.
"""

from __future__ import annotations

import base64
import html
from pathlib import Path

_ICON = "data:image/png;base64," + base64.b64encode((Path(__file__).resolve().parent / "favicon.png").read_bytes()).decode("ascii")


def deny_body(message: str) -> str:
    """Return the page that shows the decision's message."""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f'<link rel="icon" type="image/png" href="{_ICON}">\n'
        "<title>Not allowed</title>\n"
        "</head>\n"
        "<body>\n"
        f"<p>{html.escape(message)}</p>\n"
        "</body>\n"
        "</html>\n"
    )
