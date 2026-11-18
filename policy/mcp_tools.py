"""The tools an MCP agent can call, and the permission each needs.

Each read tool gives what its portal page shows for the same choices. The
attempts and usage tools turn their arguments into the page's query string
and call the same report the page's data endpoint calls, so the figures are
the same. Times are household-local, as on the pages.

A period is one of the portal's ranges, written with underscores, such as
``past_week``, or a ``from`` and ``to`` date as ``yyyy-mm-dd``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import time

from policy.check import size, span
from policy.hierarchy import Action, Period, Policy, Rule
from policy.mcp_settings import McpSettings
from policy.pac import SWITCHES
from policy.policy_admin import PolicyChanges
from policy.pool_admin import PoolAdmin
from policy.portal import client_names
from policy.review import NOT_STORED, attempt_report, attempts_report, facts_report, trend_report
from policy.task_admin import TaskAdmin
from policy.task_create import TaskChanges
from policy.tasks import AttemptStore, TaskKey
from policy.usage import UsageStore
from policy.usage_graph import RANGES, UNITS, Presets, usage_graph
from policy.usage_requests import FETCH_LEVELS, OUTCOMES as REQUEST_OUTCOMES, SORTS, usage_requests
from policy.attempt_trends import OUTCOMES as ATTEMPT_OUTCOMES, SETS

PERIODS = tuple(name.replace("-", "_") for name in RANGES if name != "custom")
_WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class ToolProblem(Exception):
    """A call that cannot be answered, and why, in a sentence the agent can show."""


class WriteRefused(ToolProblem):
    """A write refused by its checks. ``reasons`` lists every reason, for the agent and the activity log."""

    def __init__(self, reasons: Sequence[str], heading: str | None = None) -> None:
        self.reasons = [str(reason) for reason in reasons]
        shown = self.reasons if heading is None or self.reasons == [heading] else [heading, *("- " + reason for reason in self.reasons)]
        super().__init__("\n".join(shown))


class WriteFailed(ToolProblem):
    """A write that passed its checks but could not be made, such as a file that could not be written."""

    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons = [str(reason) for reason in reasons]
        super().__init__("\n".join(self.reasons))


@dataclass(frozen=True)
class Writer:
    """Who a write is made for: the parent who approved the agent, the agent, and whether it is a dry run."""

    parent: str
    agent: str
    dry_run: bool = False


@dataclass
class Sources:
    """Where the tools read from. ``loaded`` returns the policy in force and the household clock."""

    loaded: Callable[[], object]
    attempts: AttemptStore
    usage: UsageStore
    presets: Presets
    tasks: TaskAdmin | None = None
    pools: PoolAdmin | None = None
    capitalisation_pools: PoolAdmin | None = None
    changes: TaskChanges | None = None
    policy_changes: PolicyChanges | None = None


@dataclass(frozen=True)
class Tool:
    name: str
    kind: str
    permission: str
    description: str
    # A read tool is run with the sources and the arguments, a write tool with its ``Writer`` too.
    run: Callable[..., object]
    properties: Mapping[str, dict] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    # What the call names, such as ``arithmetic/times-7``, for the activity log.
    target: Callable[[Mapping], str] = lambda _arguments: ""
    write: bool = False

    @property
    def needs(self) -> str:
        return f"{self.kind}: {self.permission}"

    def schema(self) -> dict:
        found: dict = {"type": "object", "properties": dict(self.properties), "additionalProperties": False}
        if self.required:
            found["required"] = list(self.required)
        return found

    def allowed(self, settings: McpSettings) -> bool:
        return settings.allows(self.kind, self.permission)


# Arguments


def _text(arguments: Mapping, name: str, required: bool = True) -> str:
    value = arguments.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ToolProblem(f"Give {name}.")
        return ""
    if not isinstance(value, str):
        raise ToolProblem(f"{name} must be text.")
    return value.strip()


def _names(arguments: Mapping, name: str) -> list[str]:
    value = arguments.get(name)
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ToolProblem(f"{name} must be a list of names.")
    return [item.strip() for item in value if item.strip()]


def _period_pairs(arguments: Mapping) -> list[tuple[str, str]]:
    """Return the page's ``range``, ``from``, and ``to`` for a tool's ``period``, ``from``, and ``to``."""
    period = _text(arguments, "period", required=False)
    first = _text(arguments, "from", required=False)
    last = _text(arguments, "to", required=False)
    if first or last or period == "custom":
        if period and period != "custom":
            raise ToolProblem("Give either period or from and to, not both.")
        if not first or not last:
            raise ToolProblem("Give both from and to, as yyyy-mm-dd.")
        return [("range", "custom"), ("from", first), ("to", last)]
    if not period:
        return []
    if period not in PERIODS:
        raise ToolProblem(f"{period} is not a period. The periods are {', '.join(PERIODS)}.")
    return [("range", period.replace("_", "-"))]


def _list_pairs(arguments: Mapping, name: str, key: str | None = None) -> list[tuple[str, str]]:
    return [(key or name, item) for item in _names(arguments, name)]


_PERIOD_PROPERTIES = {
    "period": {"type": "string", "enum": list(PERIODS), "description": "One of the portal's ranges. Leave out with from and to."},
    "from": {"type": "string", "description": "First day, yyyy-mm-dd, with to."},
    "to": {"type": "string", "description": "Last day, yyyy-mm-dd, with from."},
}
_ATTEMPT_FILTERS = {
    "client": {"type": "string", "description": "The client group, such as younger."},
    **_PERIOD_PROPERTIES,
    "set": {"type": "array", "items": {"type": "string", "enum": list(SETS)}, "description": "Sets to include. All when left out."},
    "outcome": {"type": "array", "items": {"type": "string", "enum": list(ATTEMPT_OUTCOMES)}, "description": "Outcomes to include. All when left out."},
}
_USAGE_FILTERS = {
    "client": {"type": "array", "items": {"type": "string"}, "description": "Client groups. All when left out."},
    "site": {"type": "array", "items": {"type": "string"}, "description": "Site groups."},
    "quota": {"type": "array", "items": {"type": "string"}, "description": "Quotas. Not used with site groups."},
    **_PERIOD_PROPERTIES,
}


def _attempt_pairs(arguments: Mapping) -> list[tuple[str, str]]:
    pairs = [("client", _text(arguments, "client"))]
    pairs += _period_pairs(arguments)
    pairs += _list_pairs(arguments, "set")
    pairs += _list_pairs(arguments, "outcome")
    return pairs


def _usage_pairs(arguments: Mapping) -> list[tuple[str, str]]:
    pairs = _list_pairs(arguments, "client") + _list_pairs(arguments, "site") + _list_pairs(arguments, "quota")
    pairs += _period_pairs(arguments)
    for name in ("by", "line"):
        value = _text(arguments, name, required=False)
        if value:
            pairs.append((name, value))
    if pairs and not any(key == "range" for key, _value in pairs):
        # The page's own default, so a filter alone does not fall back to a preset's period.
        pairs.append(("range", "past-week"))
    return pairs


def _key(arguments: Mapping) -> TaskKey:
    return TaskKey(_text(arguments, "type"), _text(arguments, "name"))


def _key_target(arguments: Mapping) -> str:
    return f"{arguments.get('type', '')}/{arguments.get('name', '')}"


# The policy, as the file writes it


def _policy(sources: Sources) -> Policy:
    policy = sources.loaded().policy
    if policy is None:
        raise ToolProblem("No policy is loaded.")
    return policy


def _clock_text(moment: time, extra: int = 0) -> str:
    return moment.strftime("%H:%M") + (f"+{extra}" if extra else "")


def _period(period: Period) -> dict:
    found = {"start": _clock_text(period.start), "end": _clock_text(period.end, period.extra_days)}
    if period.weekdays is not None:
        found["days"] = [_WEEKDAY_NAMES[day] for day in sorted(period.weekdays)]
    return found


_size = size


def _action(action: Action) -> dict:
    found: dict = {"action": action.kind}
    if action.message:
        found["message"] = action.message
    if action.location:
        found["location"] = action.location
    if action.ruleset:
        found["ruleset"] = action.ruleset
    if action.rules is not None:
        found["rules"] = [_rule(rule) for rule in action.rules]
    return found


def _rule(rule: Rule) -> dict:
    found: dict = {"condition": rule.condition}
    if rule.groups:
        found["groups"] = list(rule.groups)
    if rule.windows:
        found["windows"] = list(rule.windows)
    if rule.required is not None:
        found["required"] = rule.required
    if rule.quota is not None:
        found["quota"] = rule.quota
    found["when_true"] = _action(rule.when_true)
    found["when_false"] = _action(rule.when_false)
    return found


def get_household(sources: Sources, _arguments: Mapping) -> dict:
    now = sources.loaded()
    policy = _policy(sources)
    local = now.clock.local()
    return {
        "entry": policy.entry,
        "timezone": policy.timezone,
        "bucket_length": span(policy.bucket_length),
        "time_grace": span(policy.time_grace),
        "volume_grace": size(policy.volume_grace),
        "host_retention": f"{policy.host_retention}d",
        "request_retention": f"{policy.request_retention}d",
        "proxy_configuration": {
            "direct": {
                **{name: getattr(policy.proxy_configuration, name) for name in SWITCHES},
                "extra": [item.text for item in policy.proxy_configuration.extra],
            }
        },
        "date": local.date().isoformat(),
        "time": local.strftime("%H:%M:%S"),
        "weekday": _WEEKDAY_NAMES[local.weekday()],
    }


def list_client_groups(sources: Sources, _arguments: Mapping) -> dict:
    policy = _policy(sources)
    return {"client_groups": [{"name": group.name, "addresses": list(group.addresses)} for group in policy.client_groups]}


def list_site_groups(sources: Sources, _arguments: Mapping) -> dict:
    policy = _policy(sources)
    ordered = sorted(policy.site_groups, key=lambda group: group.priority)
    return {
        "site_groups": [{"name": group.name, "priority": group.priority, "patterns": list(group.patterns)} for group in ordered]
    }


def list_time_windows(sources: Sources, _arguments: Mapping) -> dict:
    policy = _policy(sources)
    return {"time_windows": [{"name": window.name, "periods": [_period(period) for period in window.periods]} for window in policy.time_windows]}


def list_quotas(sources: Sources, _arguments: Mapping) -> dict:
    policy = _policy(sources)
    return {
        "quotas": [
            {
                "name": quota.name,
                "time": span(quota.time_limit) if quota.time_limit else None,
                "bytes": _size(quota.byte_limit) if quota.byte_limit else None,
                "time_grace": span(quota.time_grace),
                "volume_grace": _size(quota.volume_grace),
                "ruleset": quota.ruleset,
            }
            for quota in policy.quotas
        ]
    }


def list_rule_sets(sources: Sources, _arguments: Mapping) -> dict:
    policy = _policy(sources)
    return {"entry": policy.entry, "rule_sets": [{"name": name, "rules": [_rule(rule) for rule in rules]} for name, rules in policy.rule_sets]}


# Tasks and pools


def _tasks(sources: Sources) -> TaskAdmin:
    if sources.tasks is None:
        raise ToolProblem("Tasks cannot be read here.")
    return sources.tasks


def _pools(sources: Sources) -> PoolAdmin:
    if sources.pools is None:
        raise ToolProblem("Sentence pools cannot be read here.")
    return sources.pools


def list_tasks(sources: Sources, _arguments: Mapping) -> dict:
    return {"tasks": _tasks(sources).catalogue()}


def get_task(sources: Sources, arguments: Mapping) -> dict:
    answer = _tasks(sources).page(_key(arguments))
    if answer.status != 200:
        raise ToolProblem(answer.body.get("error", "That task cannot be read."))
    body = dict(answer.body)
    body.pop("version", None)
    return body


def _capitalisation_pools(sources: Sources) -> PoolAdmin:
    if sources.capitalisation_pools is None:
        raise ToolProblem("Capitalisation pools cannot be read here.")
    return sources.capitalisation_pools


def list_sentence_pools(sources: Sources, _arguments: Mapping) -> dict:
    return _list_pools(_pools(sources))


def list_capitalisation_pools(sources: Sources, _arguments: Mapping) -> dict:
    return _list_pools(_capitalisation_pools(sources))


def _list_pools(pools: PoolAdmin) -> dict:
    listed = []
    for pool in pools.catalogue()["pools"]:
        page = pools.page(pool["id"])
        listed.append(
            {
                "id": pool["id"],
                "name": pool["name"],
                "sentences": pool.get("sentences", 0),
                "tasks": page.body.get("tasks", []) if page.status == 200 else [],
            }
        )
    return {"pools": listed}


def get_sentence_pool(sources: Sources, arguments: Mapping) -> dict:
    return _get_pool(_pools(sources), arguments)


def get_capitalisation_pool(sources: Sources, arguments: Mapping) -> dict:
    return _get_pool(_capitalisation_pools(sources), arguments)


def _get_pool(pools: PoolAdmin, arguments: Mapping) -> dict:
    answer = pools.page(_text(arguments, "id"))
    if answer.status != 200:
        raise ToolProblem(answer.body.get("error", "That pool cannot be read."))
    body = dict(answer.body)
    body.pop("version", None)
    return body


# Attempts


def list_attempts(sources: Sources, arguments: Mapping) -> dict:
    now = sources.loaded()
    policy = now.policy
    return attempts_report(
        sources.attempts,
        client_names(policy),
        "",
        now=now.clock.local(),
        tasks=() if policy is None else policy.tasks,
        timezone=None if policy is None else policy.timezone,
        pairs=_attempt_pairs(arguments),
    )


def get_task_trend(sources: Sources, arguments: Mapping) -> dict:
    now = sources.loaded()
    policy = now.policy
    return trend_report(
        sources.attempts,
        client_names(policy),
        _key(arguments),
        now=now.clock.local(),
        tasks=() if policy is None else policy.tasks,
        timezone=None if policy is None else policy.timezone,
        pairs=_attempt_pairs(arguments),
    )


def get_arithmetic_facts(sources: Sources, arguments: Mapping) -> dict:
    now = sources.loaded()
    policy = now.policy
    return facts_report(
        sources.attempts,
        client_names(policy),
        _text(arguments, "operation"),
        now=now.clock.local(),
        timezone=None if policy is None else policy.timezone,
        pairs=_attempt_pairs(arguments),
    )


def get_attempt(sources: Sources, arguments: Mapping) -> dict:
    now = sources.loaded()
    raw = arguments.get("id")
    attempt_id = str(raw).strip() if isinstance(raw, (int, str)) and not isinstance(raw, bool) else ""
    if not attempt_id:
        raise ToolProblem("Give id, the attempt's number.")
    found = attempt_report(
        sources.attempts, attempt_id, now=now.clock.local(), timezone=None if now.policy is None else now.policy.timezone
    )
    if found is None:
        raise ToolProblem(NOT_STORED)
    return found


# Usage


def get_usage(sources: Sources, arguments: Mapping) -> dict:
    now = sources.loaded()
    unit = _text(arguments, "unit", required=False) or "minutes"
    if unit not in UNITS:
        raise ToolProblem(f"{unit} is not a unit. The units are {', '.join(UNITS)}.")
    found = usage_graph(now.policy, sources.usage, sources.presets, _usage_pairs(arguments), now.clock.local(), unit)
    found.pop("presets", None)
    return found


def list_requests(sources: Sources, arguments: Mapping) -> dict:
    now = sources.loaded()
    pairs = _usage_pairs(arguments) or [("range", "past-week")]
    for name in ("host", "fetch", "sort", "dir"):
        value = _text(arguments, name, required=False)
        if value:
            pairs.append((name, value))
    if arguments.get("exact"):
        pairs.append(("exact", "1"))
    pairs += _list_pairs(arguments, "outcome")
    page = arguments.get("page")
    if page is not None:
        pairs.append(("page", str(page)))
    found = usage_requests(now.policy, sources.usage, sources.presets, pairs, now.clock.local())
    found.pop("presets", None)
    return found


_TASK_KEY = {
    "type": {"type": "string", "description": "The task's type, such as arithmetic."},
    "name": {"type": "string", "description": "The task's name, such as times-7."},
}

READ_TOOLS: tuple[Tool, ...] = (
    Tool("get_household", "household", "read", "The household's entry rule set, timezone, usage bucket length, graces, retentions, proxy configuration, and its date and time now.", get_household),
    Tool("list_client_groups", "client_groups", "read", "Each client group and its addresses.", list_client_groups),
    Tool("list_site_groups", "site_groups", "read", "Each site group, its priority, and its host patterns.", list_site_groups),
    Tool("list_time_windows", "time_windows", "read", "Each time window and its periods. An end such as 09:00+1 is on a later day.", list_time_windows),
    Tool("list_quotas", "quotas", "read", "Each quota's time, bytes, grace, and the rule set it meters.", list_quotas),
    Tool("list_rule_sets", "rule_sets", "read", "Each named rule set's rules in order, and the entry rule set.", list_rule_sets),
    Tool("list_tasks", "tasks", "read", "Every task's type and name, as Task Administration lists them.", list_tasks),
    Tool(
        "get_task", "tasks", "read",
        "Every field a task's page shows, with a spelling task's words and the pool each is in.",
        get_task, _TASK_KEY, ("type", "name"), _key_target,
    ),
    Tool("list_sentence_pools", "sentence_pools", "read", "Each parts of speech sentence pool's id, name, sentence count, and the tasks using it.", list_sentence_pools),
    Tool(
        "get_sentence_pool", "sentence_pools", "read", "A parts of speech pool's sentences and their marked words.",
        get_sentence_pool, {"id": {"type": "string", "description": "The pool's id, from list_sentence_pools."}}, ("id",),
        lambda arguments: str(arguments.get("id", "")),
    ),
    Tool("list_capitalisation_pools", "capitalisation_pools", "read", "Each capitalisation pool's id, name, sentence count, and the tasks using it.", list_capitalisation_pools),
    Tool(
        "get_capitalisation_pool", "capitalisation_pools", "read", "A capitalisation pool's sentences, each with its own level of difficulty if it has one.",
        get_capitalisation_pool, {"id": {"type": "string", "description": "The pool's id, from list_capitalisation_pools."}}, ("id",),
        lambda arguments: str(arguments.get("id", "")),
    ),
    Tool(
        "list_attempts", "attempts", "read",
        "A client group's day so far, its overview by task, and its attempts over a period, newest first, as /parent/attempts shows them. "
        "The period is the past month when left out.",
        list_attempts, _ATTEMPT_FILTERS, ("client",), lambda arguments: str(arguments.get("client", "")),
    ),
    Tool(
        "get_task_trend", "attempts", "read", "One task's trend for a client group over a period, as its trend page shows it.",
        get_task_trend, {**_TASK_KEY, **_ATTEMPT_FILTERS}, ("client", "type", "name"), _key_target,
    ),
    Tool(
        "get_arithmetic_facts", "attempts", "read",
        "One arithmetic operation's facts for a client group, as the facts page shows them. Each fact's asked, right, wrong, "
        "timeouts, and median time are for the period and filters. Its all_time figures (asked, run, smoothed time, miss boost, "
        "slow boost, and weight, the weight that chooses his questions) and slow (the operation's median smoothed time and "
        "where the slow boost starts and is full, or that too few facts are timed yet) are all-time, from his whole record "
        "whatever the period and filters.",
        get_arithmetic_facts,
        {"operation": {"type": "string", "description": "The operation, such as multiplication."}, **_ATTEMPT_FILTERS},
        ("client", "operation"), lambda arguments: str(arguments.get("operation", "")),
    ),
    Tool(
        "get_attempt", "attempts", "read", "One attempt's page: its summary, answers, and timings.",
        get_attempt, {"id": {"type": ["string", "integer"], "description": "The attempt's number."}}, ("id",),
        lambda arguments: str(arguments.get("id", "")),
    ),
    Tool(
        "get_usage", "usage", "read",
        "The usage graph in minutes or bytes, with its filters. Name a line to get its top hosts. "
        "With no filters, the Default preset is shown, as on the page.",
        get_usage,
        {
            "unit": {"type": "string", "enum": list(UNITS), "description": "minutes, the default, or bytes."},
            **_USAGE_FILTERS,
            "by": {"type": "string", "enum": ["client", "site", "quota", "none"], "description": "What each line is."},
            "line": {"type": "string", "description": "A line to open its top hosts, such as younger, or Total when by is none."},
        },
    ),
    Tool(
        "list_requests", "usage", "read", "The request table, 100 rows a page, with its filters. The period is the past week when left out.",
        list_requests,
        {
            **_USAGE_FILTERS,
            "host": {"type": "string", "description": "Part of a host name, or the whole name with exact."},
            "exact": {"type": "boolean"},
            "outcome": {"type": "array", "items": {"type": "string", "enum": list(REQUEST_OUTCOMES)}},
            "fetch": {"type": "string", "enum": list(FETCH_LEVELS)},
            "sort": {"type": "string", "enum": list(SORTS)},
            "dir": {"type": "string", "enum": ["asc", "desc"]},
            "page": {"type": "integer", "minimum": 1},
        },
    ),
)

def answer_text(found: object) -> str:
    return json.dumps(found, ensure_ascii=False, default=str)


def visible(settings: McpSettings, tools: Sequence[Tool]) -> list[Tool]:
    return [tool for tool in tools if tool.allowed(settings)]
