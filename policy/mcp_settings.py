"""The MCP server's settings: ``mcp.yaml`` beside the policy file.

The file is separate from ``policy.yaml`` and is not included by it. Every
field may be left out, and then takes its default::

    enabled: true
    access_token: 1h        # how long an access token lasts
    refresh_idle: 30d       # a connection unused this long lapses
    refresh_lifetime: 90d   # a connection lapses this long after it was approved
    activity_days: 90       # how long the activity log keeps an entry
    permissions:
      tasks: [create, read, update]
      attempts: [read]

A class left out of ``permissions`` has no permissions. With no file the
server is off.

The MCP page writes the file with ``settings_text``, which changes only the
lines whose values change, so comments written by hand stay where they were.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from policy.task_edit import EditError, rewrite_root

FILE_NAME = "mcp.yaml"
CREATE, READ, UPDATE, DELETE = "create", "read", "update", "delete"
PERMISSIONS = (CREATE, READ, UPDATE, DELETE)
CRUD = PERMISSIONS
# Each class and the permissions it has, in the order the page lists them.
CLASSES: dict[str, tuple[str, ...]] = {
    "household": (READ, UPDATE),
    "client_groups": CRUD,
    "site_groups": CRUD,
    "time_windows": CRUD,
    "quotas": CRUD,
    "rule_sets": CRUD,
    "tasks": CRUD,
    "sentence_pools": CRUD,
    "capitalisation_pools": CRUD,
    "attempts": (READ,),
    "usage": (READ,),
}
# The classes a reviewer's agent may use, and only to read (S043). mcp.yaml's grants are masked by this.
REVIEWER_CLASSES = ("attempts", "usage")
DURATIONS = ("access_token", "refresh_idle", "refresh_lifetime")
FIELDS = ("enabled", *DURATIONS, "activity_days", "permissions")
_DURATION = re.compile(r"([0-9]+)([mhd])\Z")
_UNIT_SECONDS = {"m": 60, "h": 3600, "d": 86400}


class SettingsError(ValueError):
    """The settings have problems. ``problems`` holds each, one sentence each."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class McpSettings:
    enabled: bool = True
    access_token: int = 3600
    refresh_idle: int = 30 * 86400
    refresh_lifetime: int = 90 * 86400
    activity_days: int = 90
    permissions: Mapping[str, frozenset[str]] = field(
        default_factory=lambda: {"tasks": frozenset({CREATE, READ, UPDATE}), "attempts": frozenset({READ})}
    )

    def __post_init__(self) -> None:
        # A class with no permissions is the same as a class left out.
        held = {kind: frozenset(names) for kind, names in self.permissions.items() if names}
        object.__setattr__(self, "permissions", held)

    def allows(self, kind: str, permission: str) -> bool:
        return permission in self.permissions.get(kind, frozenset())

    def as_json(self) -> dict:
        return {
            "enabled": self.enabled,
            **{name: duration_text(getattr(self, name)) for name in DURATIONS},
            "activity_days": self.activity_days,
            "permissions": {kind: ordered(self.permissions.get(kind, ())) for kind in CLASSES},
        }


def for_role(settings: McpSettings, role: str) -> McpSettings:
    """Return what a connection approved by an account with role may use: all of settings for an admin."""
    if role == "admin":
        return settings
    masked = {kind: settings.permissions.get(kind, frozenset()) & {READ} for kind in REVIEWER_CLASSES}
    return replace(settings, permissions=masked)


DEFAULTS = McpSettings()
# What turning the server on gives when there is no file: read on every class.
FIRST_TIME = replace(DEFAULTS, permissions={kind: frozenset({READ}) for kind in CLASSES})


@dataclass(frozen=True)
class Loaded:
    """What the service read from the file: the settings in force, or why there are none.

    ``settings`` is None when there is no file or it has problems; the server
    is then off. ``exists`` says whether the file is there.
    """

    path: Path
    settings: McpSettings | None
    problems: tuple[str, ...] = ()
    exists: bool = False
    text: str = ""

    @property
    def on(self) -> bool:
        return self.settings is not None and self.settings.enabled

    @property
    def version(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def settings_file(policy_file: Path) -> Path:
    """Return ``MCP_FILE``, or ``mcp.yaml`` beside the policy file."""
    named = os.environ.get("MCP_FILE", "").strip()
    return Path(named) if named else policy_file.parent / FILE_NAME


def ordered(permissions) -> list[str]:
    return [name for name in PERMISSIONS if name in permissions]


def duration_text(seconds: int) -> str:
    """Return a duration as the file writes it, in the largest unit that divides it, such as 30d or 36h."""
    for unit in ("d", "h"):
        if seconds % _UNIT_SECONDS[unit] == 0:
            return f"{seconds // _UNIT_SECONDS[unit]}{unit}"
    return f"{seconds // 60}m"


def parse_duration(value: object, name: str, problems: list[str]) -> int | None:
    text = value.strip() if isinstance(value, str) else ""
    match = _DURATION.fullmatch(text)
    if match is None or int(match.group(1)) < 1:
        shown = value if isinstance(value, str) else yaml.safe_dump(value, default_flow_style=True).strip().removesuffix("...").strip()
        problems.append(f"{name}: {shown} is not a duration. Use a whole number above 0 with m, h, or d, such as 1h or 30d.")
        return None
    return int(match.group(1)) * _UNIT_SECONDS[match.group(2)]


def from_data(data: object) -> McpSettings:
    """Return the settings a parsed file or a page's save holds, or raise SettingsError listing every problem."""
    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        raise SettingsError(["the file must be a mapping of the MCP settings"])
    problems: list[str] = []
    for key in data:
        if key not in FIELDS:
            problems.append(f"{key} is not an MCP setting. The settings are {', '.join(FIELDS)}.")
    found: dict = {}
    if "enabled" in data:
        if isinstance(data["enabled"], bool):
            found["enabled"] = data["enabled"]
        else:
            problems.append("enabled: must be true or false")
    for name in DURATIONS:
        if name in data:
            seconds = parse_duration(data[name], name, problems)
            if seconds is not None:
                found[name] = seconds
    if "activity_days" in data:
        days = data["activity_days"]
        if isinstance(days, int) and not isinstance(days, bool) and days >= 1:
            found["activity_days"] = days
        else:
            problems.append(f"activity_days: {days} is not a whole number of days above 0")
    if "permissions" in data:
        found["permissions"] = _permissions(data["permissions"], problems)
    if problems:
        raise SettingsError(problems)
    return replace(DEFAULTS, **found)


def _permissions(value: object, problems: list[str]) -> dict[str, frozenset[str]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        problems.append("permissions: must map each class to a list of permissions, such as tasks: [read]")
        return {}
    granted: dict[str, frozenset[str]] = {}
    for kind, names in value.items():
        if kind not in CLASSES:
            problems.append(f"permissions: {kind} is not a permission class. The classes are {', '.join(CLASSES)}.")
            continue
        if names is None:
            names = []
        if isinstance(names, str):
            names = [names]
        if not isinstance(names, list):
            problems.append(f"permissions: {kind} must be a list of permissions, such as [read]")
            continue
        has = CLASSES[kind]
        chosen = set()
        for name in names:
            if name not in has:
                problems.append(
                    f"permissions: {kind}: {name} is not a permission {kind} has. It has {', '.join(has)}."
                )
            else:
                chosen.add(name)
        granted[kind] = frozenset(chosen)
    return granted


def load(path: Path) -> Loaded:
    """Read the file. A missing file is no settings and no problems. Problems name the file."""
    try:
        text = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        return Loaded(path, None)
    except (OSError, UnicodeDecodeError) as error:
        return Loaded(path, None, (f"{path}: could not be read: {error}",), exists=True)
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        return Loaded(path, None, (f"{path}: is not YAML: {error}",), exists=True, text=text)
    try:
        settings = from_data(data)
    except SettingsError as error:
        return Loaded(path, None, tuple(f"{path}: {problem}" for problem in error.problems), exists=True, text=text)
    return Loaded(path, settings, exists=True, text=text)


def summary_line(loaded: Loaded) -> str:
    if loaded.problems:
        return f"MCP server is off: {loaded.path} has {len(loaded.problems)} problem{'' if len(loaded.problems) == 1 else 's'}"
    if loaded.settings is None:
        return "MCP server is off: there is no mcp.yaml"
    return "MCP server is on" if loaded.settings.enabled else "MCP server is off"


def settings_text(old: str, path: Path, before: McpSettings | None, after: McpSettings) -> str:
    """Return the file's text with ``after`` written in, changing only what differs from ``before``.

    ``old`` is the file as it stands, or empty when there is none. A field
    the file leaves out is added only when its new value is not the one it
    already takes.
    """
    if not old.strip():
        return _fresh(after)
    try:
        data = yaml.safe_load(old)
    except yaml.YAMLError:
        data = None
    if not isinstance(data, Mapping) or before is None:
        return _fresh(after)
    changes: dict[str, object] = {}
    if after.enabled != before.enabled:
        changes["enabled"] = "true" if after.enabled else "false"
    for name in DURATIONS:
        if getattr(after, name) != getattr(before, name):
            changes[name] = duration_text(getattr(after, name))
    if after.activity_days != before.activity_days:
        changes["activity_days"] = str(after.activity_days)
    changed = {
        kind: (_flow(after.permissions.get(kind, ())) if after.permissions.get(kind) else None)
        for kind in CLASSES
        if frozenset(after.permissions.get(kind, ())) != frozenset(before.permissions.get(kind, ()))
    }
    block = ""
    if changed:
        if not any(after.permissions.get(kind) for kind in CLASSES):
            changes["permissions"] = "{}"
        elif isinstance(data.get("permissions"), Mapping):
            changes["permissions"] = changed
        else:
            # No permissions, or ``permissions:`` with nothing under it: the whole block is written after the rest.
            if "permissions" in data:
                changes["permissions"] = None
            block = _permission_block(after)
    try:
        text = rewrite_root(old, path, changes) if changes else old
    except EditError:
        return _fresh(after)
    return text.rstrip("\n") + "\n" + block if block else text


def _flow(permissions) -> str:
    return "[" + ", ".join(ordered(permissions)) + "]"


def _permission_block(settings: McpSettings) -> str:
    lines = [f"  {kind}: {_flow(settings.permissions[kind])}" for kind in CLASSES if settings.permissions.get(kind)]
    if not lines:
        return "permissions: {}\n"
    return "permissions:\n" + "\n".join(lines) + "\n"


def _fresh(settings: McpSettings) -> str:
    return (
        "# The MCP server's settings. See /parent/settings/mcp.\n"
        f"enabled: {'true' if settings.enabled else 'false'}\n"
        f"access_token: {duration_text(settings.access_token)}        # how long an access token lasts\n"
        f"refresh_idle: {duration_text(settings.refresh_idle)}       # a connection unused this long lapses\n"
        f"refresh_lifetime: {duration_text(settings.refresh_lifetime)}   # a connection lapses this long after it was approved\n"
        f"activity_days: {settings.activity_days}       # how long the activity log keeps an entry\n"
        + _permission_block(settings)
    )
