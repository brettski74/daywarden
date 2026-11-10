"""What every page the task site shows the child shares: the colours, the icon, and the counting line.

The colours are custom properties on ``:root``. The standard palette is for
an attempt that counts right now. ``data-palette="practice"`` on ``<html>``
swaps in the purple palette for one that doesn't: a practice attempt, or a
potential attempt while a task is required. Page styles name only these
properties, so a new quiz type gets both palettes. They belong to the child
pages, and are separate from the parent portal's theme.

The icon is a copy of the portal's owl, served at ``/favicon.png`` without a
session, so it loads over either listener.
"""

from __future__ import annotations

from pathlib import Path

from policy.report import _e
from policy.tasks import POTENTIAL, PRACTICE, TaskSets

FAVICON_PATH = "/favicon.png"
FAVICON_FILE = Path(__file__).resolve().parent / "static" / "favicon.png"
PRACTICE_PALETTE = "practice"
PRACTICE_LINE = "Practice: this won't count toward internet time today."
WAITING_LINE = "This counts once your other tasks are done."

# The selector's After These and Extra Practice buttons, and the practice palette's accent.
_TEAL = "#0f766e"
_PURPLE = "#6d28d9"

PALETTE = f"""\
:root {{
  --page-bg: #fbfbf7; --text: #222; --strong-text: #000; --soft-text: #444; --muted: #555;
  --surface: #fff; --control-border: #aaa; --field-border: #888; --shadow: rgba(0, 0, 0, 0.2);
  --accent: #2f6fd6; --on-accent: #fff; --accent-disabled: #a9b8d1; --accent-strong: #1d4ed8;
  --accent-soft: #dbeafe; --accent-edge: #93c5fd; --accent-hover: #2563eb; --entry: #4169e1;
  --highlight: #e5e7eb; --given-bg: #f1f1ea; --given-border: #bbb; --track: #e4e4e4;
  --disabled-text: #9ca3af; --disabled-bg: #e5e7eb; --disabled-edge: #d1d5db;
  --right: #1a7f37; --wrong: #b42318; --mark: #dc2626;
  --right-soft: #dcfce7; --wrong-soft: #fee2e2; --missed-soft: #ffedd5;
  --choice-after: {_TEAL}; --choice-extra: {_PURPLE};
  --expand-duration: 500ms; --expand-easing: cubic-bezier(0.37, 0, 0.63, 1);
}}
:root[data-palette="{PRACTICE_PALETTE}"] {{
  --page-bg: #f7f3fd; --accent: {_PURPLE}; --accent-disabled: #b9a7dc; --accent-strong: #5b21b6;
  --accent-soft: #ede9fe; --accent-edge: #c4b5fd; --accent-hover: #7c3aed; --entry: #7c3aed;
  --highlight: #e4daf7; --given-bg: #eee8f6; --track: #e2d9f3;
}}
@media (prefers-reduced-motion: reduce) {{
  :root {{ --expand-duration: 0ms; }}
}}
.counting {{ margin: 0; padding: 0.6rem 1rem 0; font-size: 1.3rem; font-weight: bold; color: var(--accent-strong); text-align: center; }}
"""


def counting_line(task_set: str, sets: TaskSets) -> str:
    """Return the line for an attempt in this set that doesn't count right now, or "" when it does.

    A practice attempt never counts. A potential attempt counts once no task
    is required. ``sets`` is the task sets when the page loads.
    """
    if task_set == PRACTICE:
        return PRACTICE_LINE
    if task_set == POTENTIAL and sets.required:
        return WAITING_LINE
    return ""


def html_tag(line: str) -> str:
    """Return the ``<html>`` tag, with the practice palette when there is a counting line."""
    if line:
        return f'<html lang="en" data-palette="{PRACTICE_PALETTE}">'
    return '<html lang="en">'


def head(title: str, style: str) -> str:
    """Return the inside of ``<head>``: the icon, the title, and the palette before the page's own style."""
    return (
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<link rel="icon" type="image/png" href="{FAVICON_PATH}">\n'
        f"<title>{_e(title)}</title>\n"
        f"<style>\n{PALETTE}{style}</style>"
    )


def line_html(line: str) -> str:
    """Return the counting line at the top of the page, or "" when the attempt counts right now."""
    return f'<p class="counting" id="counting">{_e(line)}</p>\n' if line else ""
