"""The MCP write tools for the policy's named items and household settings (S036.3).

Each class, client groups, site groups, time windows, quotas, and rule
sets, has a create, an update, and a delete tool, and ``update_household``
changes the household settings. Each is a thin wrapper over
``PolicyChanges``, the one write path for these parts of the policy, and
writes as the task tools in ``policy.mcp_writes`` do: a dry run, the
checks, the commit naming the agent, the activity log, and an answer that
shows the item as its read tool shows it now.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from policy.mcp_tools import (
    Sources,
    Tool,
    ToolProblem,
    WriteRefused,
    Writer,
    get_household,
    list_client_groups,
    list_quotas,
    list_rule_sets,
    list_site_groups,
    list_time_windows,
)
from policy.mcp_writes import _DRY_RUN, _answer, _made, _with
from policy.policy_admin import HOUSEHOLD, SECTIONS, PolicyChanges

_ARGUMENTS = frozenset({"name", "dry_run"})


def _policy_changes(sources: Sources) -> PolicyChanges:
    if sources.policy_changes is None:
        raise ToolProblem("The policy cannot be changed here.")
    return sources.policy_changes


def _fields(section: str, arguments: Mapping) -> dict:
    """Return the item's fields an agent named. Raises ``WriteRefused`` naming any argument the tool does not take."""
    allowed = SECTIONS[section].fields
    unknown = sorted(str(key) for key in arguments if key not in allowed and key not in _ARGUMENTS)
    if unknown:
        label = SECTIONS[section].label
        raise WriteRefused([f"{', '.join(unknown)} {'is not a field' if len(unknown) == 1 else 'are not fields'} of a {label}. Its fields are {', '.join(allowed)}."])
    return {key: arguments[key] for key in allowed if key in arguments}


_LISTED: dict[str, tuple[Callable[[Sources, Mapping], dict], str]] = {
    "client_groups": (list_client_groups, "client_groups"),
    "site_groups": (list_site_groups, "site_groups"),
    "time_windows": (list_time_windows, "time_windows"),
    "quotas": (list_quotas, "quotas"),
    "rule_sets": (list_rule_sets, "rule_sets"),
}


def _shown(sources: Sources, section: str, name: str) -> Callable[[], dict]:
    """Return how the item's read tool shows it now."""

    def shown() -> dict:
        read, key = _LISTED[section]
        found = next((item for item in read(sources, {})[key] if item["name"] == name), None)
        return {SECTIONS[section].label.replace(" ", "_"): found}

    return shown


def _creator(section: str):
    def create(sources: Sources, arguments: Mapping, writer: Writer) -> dict:
        name = arguments.get("name")
        fields = _fields(section, arguments)
        with _with(writer):
            body = _made(_policy_changes(sources).create(section, name, fields, writer.parent))
        return _answer(body, writer, _shown(sources, section, str(name)))

    return create


def _updater(section: str):
    def update(sources: Sources, arguments: Mapping, writer: Writer) -> dict:
        name = arguments.get("name")
        fields = _fields(section, arguments)
        with _with(writer):
            body = _made(_policy_changes(sources).update(section, name, fields, writer.parent))
        return _answer(body, writer, _shown(sources, section, str(name)))

    return update


def _deleter(section: str):
    def delete(sources: Sources, arguments: Mapping, writer: Writer) -> dict:
        name = arguments.get("name")
        with _with(writer):
            body = _made(_policy_changes(sources).delete(section, name, writer.parent))
        return _answer(body, writer, lambda: {"deleted": {SECTIONS[section].label.replace(" ", "_"): name}})

    return delete


def update_household(sources: Sources, arguments: Mapping, writer: Writer) -> dict:
    unknown = sorted(str(key) for key in arguments if key not in HOUSEHOLD and key != "dry_run")
    if unknown:
        raise WriteRefused([f"{', '.join(unknown)}: the household settings changed here are {', '.join(HOUSEHOLD)}."])
    fields = {key: arguments[key] for key in HOUSEHOLD if key in arguments}
    with _with(writer):
        body = _made(_policy_changes(sources).household(fields, writer.parent))
    return _answer(body, writer, lambda: {"household": get_household(sources, {})})


# The tools

_NAME = {"name": {"type": "string", "description": "The item's name. Nothing is renamed: a new name is a delete and a create."}}
_ACTION = {
    "type": "object",
    "description": (
        "What to do: {\"action\": \"allow\"}, {\"action\": \"continue\"}, {\"action\": \"deny\", \"message\": ...}, "
        "{\"action\": \"redirect\", \"location\": an http or https URL or revision_task}, or {\"action\": \"evaluate\"} "
        "with ruleset, a rule set's name, or rules, a list of rules. Left out, it is continue."
    ),
}
_PROPERTIES: dict[str, dict[str, dict]] = {
    "client_groups": {
        "addresses": {
            "type": "array", "items": {"type": "string"},
            "description": "Every address in the group, each an IP address or a DNS name. An address is in one group only.",
        },
    },
    "site_groups": {
        "priority": {"type": "integer", "description": "Lower is tried first. No two site groups share one."},
        "patterns": {
            "type": "array", "items": {"type": "string"},
            "description": (
                "Every pattern in the group. A pattern with :// matches the whole URL, any other the host only, "
                "ignoring case. * matches anything and ? one character, so *.youtube.com matches www.youtube.com."
            ),
        },
    },
    "time_windows": {
        "periods": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "string", "description": "A clock such as 21:00 or 2100."},
                    "end": {"type": "string", "description": "A clock, with +n for n days later, such as 07:00+1. An end equal to the start is 24 hours."},
                    "day": {"type": "string", "description": "One weekday the period starts on, such as friday."},
                    "days": {
                        "type": ["string", "array"], "items": {"type": "string"},
                        "description": "Weekdays the period starts on, such as [monday, wednesday] or monday-friday.",
                    },
                },
                "required": ["start", "end"],
            },
            "description": "Every period of the window. Give day or days, not both, or neither for every day.",
        },
    },
    "quotas": {
        "time": {"type": ["string", "null"], "description": "A time limit a day, such as 45m, 2h, or 7200s. null takes it out."},
        "bytes": {"type": ["string", "null"], "description": "A byte limit a day with b, k, M, G, or T, such as 500M. null takes it out."},
        "time_grace": {"type": ["string", "null"], "description": "Time past the limit before a transfer is cut, such as 5m. null uses the household's."},
        "volume_grace": {"type": ["string", "null"], "description": "Bytes past the limit before a transfer is cut, such as 1M. null uses the household's."},
        "ruleset": {"type": "string", "description": "The rule set that decides which traffic counts against the quota."},
    },
    "rule_sets": {
        "rules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "condition": {
                        "type": "string",
                        "enum": ["always", "client_group", "site_group", "time_window", "tasks_required", "time_remaining", "volume_remaining"],
                    },
                    "group": {"type": "string"}, "groups": {"type": "array", "items": {"type": "string"}},
                    "window": {"type": "string"}, "windows": {"type": "array", "items": {"type": "string"}},
                    "required": {"type": "integer"},
                    "quota": {"type": "string"},
                    "when_true": _ACTION,
                    "when_false": _ACTION,
                },
                "required": ["condition"],
            },
            "description": "The whole ordered list of rules, as list_rule_sets shows them.",
        },
    },
}
_HOUSEHOLD = {
    "entry": {"type": "string", "description": "The rule set every request starts at."},
    "timezone": {"type": ["string", "null"], "description": "An IANA name, such as America/Toronto. null uses the machine's."},
    "bucket_length": {"type": ["string", "null"], "description": "The usage bucket length, which divides a day, such as 5m. null is 5m."},
    "time_grace": {"type": ["string", "null"], "description": "Time past a quota's limit before a transfer is cut, such as 5m. A quota's own grace wins. null is 5m."},
    "volume_grace": {"type": ["string", "null"], "description": "Bytes past a quota's limit before a transfer is cut, such as 1M. A quota's own grace wins. null is 1M."},
    "host_retention": {"type": ["string", "null"], "description": "How long the usage by host is kept, a whole number of days such as 30d. null is 30d."},
    "request_retention": {"type": ["string", "null"], "description": "How long each request is kept, a whole number of days such as 30d. null is 30d."},
    "proxy_configuration": {
        "type": ["object", "null"],
        "description": (
            "Which hosts the proxy auto-configuration file sends direct: {\"direct\": {localhost, plain_host_names, "
            "policy_server, local_subnets, local_domains: true or false, each on when left out, extra: [hosts, "
            "domains, addresses, or subnets]}}. null takes the section out, so every switch is on and extra is empty."
        ),
    },
}


def _target(arguments: Mapping) -> str:
    return str(arguments.get("name", ""))


def _tools() -> tuple[Tool, ...]:
    tools: list[Tool] = []
    for section, info in SECTIONS.items():
        label = info.label
        singular = label.replace(" ", "_")
        fields = _PROPERTIES[section]
        tools += [
            Tool(
                f"create_{singular}", section, "create",
                f"Make a {label} with these fields. It is checked as dw check checks the policy.",
                _creator(section), {**_NAME, **fields, **_DRY_RUN}, ("name",), _target, write=True,
            ),
            Tool(
                f"update_{singular}", section, "update",
                f"Change only the fields named of a {label}. A list named replaces the whole list.",
                _updater(section), {**_NAME, **fields, **_DRY_RUN}, ("name",), _target, write=True,
            ),
            Tool(
                f"delete_{singular}", section, "delete",
                f"Take a {label} out of the policy. Refused while anything still names it.",
                _deleter(section), {**_NAME, **_DRY_RUN}, ("name",), _target, write=True,
            ),
        ]
    tools.append(
        Tool(
            "update_household", "household", "update",
            "Change the household's entry rule set, timezone, usage bucket length, graces, retentions, or proxy configuration.",
            update_household, {**_HOUSEHOLD, **_DRY_RUN}, (), lambda _arguments: "household", write=True,
        )
    )
    return tuple(tools)


POLICY_WRITE_TOOLS: tuple[Tool, ...] = _tools()
