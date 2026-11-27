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
from datetime import datetime, time

from policy.check import size, span
from policy.decisions import FETCH_KEYS, parse_request
from policy.engine import FixtureLedger, judge
from policy.hierarchy import Action, Period, Policy, Rule
from policy.mcp_settings import McpSettings
from policy.pac import SWITCHES
from policy.policy_admin import PolicyChanges
from policy.pool_admin import PoolAdmin
from policy.portal import client_names
from policy.parts_of_speech_report import LEFT_OUT, NO_PART, NO_POOL, TRY_CHOICES, pair_placements, word_asks
from policy.parts_of_speech import word_key
from policy.review import NOT_STORED, attempt_report, attempts_report, confusions_report, facts_report, trend_report, words_report
from policy.spelling_report import POOL_CHOICES
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


# Testing a request


def _count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ToolProblem(f"{name} must be a whole number of 0 or more.")
    return value


def _fixture_quotas(policy: Policy, given: object) -> dict[str, tuple[int, int]]:
    if given is None:
        return {}
    if not isinstance(given, Mapping):
        raise ToolProblem("quotas must map a quota's name to its seconds_used and bytes_used.")
    found: dict[str, tuple[int, int]] = {}
    for name, balance in given.items():
        if policy.quota(name) is None:
            known = ", ".join(quota.name for quota in policy.quotas) or "none"
            raise ToolProblem(f"There is no quota named {name}. The policy's quotas are {known}.")
        if not isinstance(balance, Mapping) or not set(balance) <= {"seconds_used", "bytes_used"}:
            raise ToolProblem(f"quotas.{name} takes seconds_used and bytes_used.")
        found[name] = (_count(balance.get("seconds_used", 0), f"{name} seconds_used"), _count(balance.get("bytes_used", 0), f"{name} bytes_used"))
    return found


def _sentence(decision: Mapping, rule_set: str | None, recheck: str | None) -> str:
    kind = decision["action"]
    if kind == "allow":
        return "Allowed. " + (f"The proxy would look at it again at {recheck}." if recheck else "No clock makes the proxy look at it again.")
    if kind == "redirect":
        return f"Redirected with {decision['status']} to {decision['location']}."
    message = decision.get("message", "")
    if rule_set is None:
        return f"No rule matched, so the proxy would block with {decision['status']}: {message}"
    return f"Blocked with {decision['status']}: {message}"


def test_proxy_request(sources: Sources, arguments: Mapping) -> dict:
    policy = _policy(sources)
    document = {key: arguments.get(key) for key in ("client_ip", "method", "url", *FETCH_KEYS) if arguments.get(key) is not None}
    try:
        request = parse_request(document)
    except ValueError as problem:
        raise ToolProblem(str(problem)) from problem
    raw = arguments.get("at")
    moment = None
    if raw is not None:
        try:
            if not isinstance(raw, str):
                raise ValueError(raw)
            moment = datetime.fromisoformat(raw)
        except ValueError as problem:
            raise ToolProblem("at must be an ISO 8601 time, such as 2026-11-14T19:30.") from problem
    local = sources.loaded().clock.local(moment)
    completed = 0 if arguments.get("tasks_completed") is None else _count(arguments["tasks_completed"], "tasks_completed")
    ledger = FixtureLedger(completed, _fixture_quotas(policy, arguments.get("quotas")))
    trace, assumption = judge(policy, client_ip=request.client_ip, url=request.url, at=local, ledger=ledger)
    recheck = assumption.recheck_at.strftime("%Y-%m-%d %H:%M:%S") if assumption.recheck_at is not None else None
    found: dict = dict(trace.decision)
    found.update(
        local_time=local.strftime("%Y-%m-%d %H:%M:%S"),
        client_group=trace.client_group,
        site_group=trace.site_group,
        rule_set=trace.rule_set,
        rule_index=trace.rule_index,
        summary=_sentence(trace.decision, trace.rule_set, recheck),
    )
    if trace.decision["action"] == "allow":
        found["recheck_at"] = recheck
    return found


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


def get_spelling_words(sources: Sources, arguments: Mapping) -> dict:
    """The words page's tiles and list. A named word adds its misspellings and the attempts that asked it."""
    now = sources.loaded()
    policy = now.policy
    pairs = _attempt_pairs(arguments) + _list_pairs(arguments, "task") + _list_pairs(arguments, "pool")
    if "task" in arguments and not _names(arguments, "task"):
        pairs.append(("task", "none"))
    if "pool" in arguments and not _names(arguments, "pool"):
        pairs.append(("pool", "none"))
    found = words_report(
        sources.attempts,
        client_names(policy),
        now=now.clock.local(),
        tasks=() if policy is None else policy.tasks,
        timezone=None if policy is None else policy.timezone,
        pairs=pairs,
    )
    named = _text(arguments, "word", required=False).lower()
    data = found.get("words")
    if data is not None:
        detail = {}
        for word in data["words"]:
            misspellings = word.pop("misspellings")
            asked = word.pop("attempts")
            if word["word"] == named:
                detail = {"word": word["word"], "misspellings": misspellings, "timeouts": word["timeouts"], "attempts": asked}
        if detail:
            detail["attempts"] = [{**data["attempts"][str(each["id"])], **each} for each in detail["attempts"]]
        elif named:
            found["notes"].append(f"{named} is not one of the words shown.")
        del data["columns"], data["attempts"]
        found["word"] = detail or None
    return found


def _pools_root(sources: Sources):
    return None if sources.pools is None else sources.pools.tasks.policy_file.parent


def get_parts_of_speech_confusions(sources: Sources, arguments: Mapping) -> dict:
    """The confusions page's grid, each part's Right, and the word list. A named pair or word adds its placements."""
    now = sources.loaded()
    policy = now.policy
    pairs = _attempt_pairs(arguments) + _list_pairs(arguments, "task") + _list_pairs(arguments, "pool")
    tries = arguments.get("try")
    if tries is not None:
        if not isinstance(tries, list) or not all(isinstance(item, int) and not isinstance(item, bool) for item in tries):
            raise ToolProblem("try must be a list of try numbers, 1 to 3.")
        pairs += [("try", str(item)) for item in tries] or [("try", "none")]
    for name in ("task", "pool"):
        if name in arguments and not _names(arguments, name):
            pairs.append((name, "none"))
    found = confusions_report(
        sources.attempts,
        client_names(policy),
        now=now.clock.local(),
        tasks=() if policy is None else policy.tasks,
        timezone=None if policy is None else policy.timezone,
        pairs=pairs,
        root=_pools_root(sources),
    )
    belongs = _text(arguments, "belongs", required=False)
    put = _text(arguments, "put", required=False)
    word = word_key(_text(arguments, "word", required=False))
    part = _text(arguments, "part", required=False)
    if bool(belongs) != bool(put):
        raise ToolProblem("Give both belongs and put to name a pair.")
    if part and not word:
        raise ToolProblem("Give word with part.")
    data = found.get("confusions")
    found["pair"] = None
    found["word"] = None
    if data is None:
        return found
    if belongs:
        found["pair"] = {"belongs": belongs, "put": put, "placements": pair_placements(data, belongs.casefold(), put.casefold())}
    if word:
        matches = [row for row in data["words"] if row["word"] == word and (not part or row["part"] == part.casefold())]
        if matches:
            found["word"] = [{"word": row["word"], "part": row["part_label"], "sentences": word_asks(data, row)} for row in matches]
        else:
            found["notes"].append(f"{word} is not one of the words shown.")
    for row in data["words"]:
        del row["asks"]
    del data["asks"]
    return found


def get_attempt(sources: Sources, arguments: Mapping) -> dict:
    now = sources.loaded()
    raw = arguments.get("id")
    attempt_id = str(raw).strip() if isinstance(raw, (int, str)) and not isinstance(raw, bool) else ""
    if not attempt_id:
        raise ToolProblem("Give id, the attempt's number.")
    found = attempt_report(
        sources.attempts,
        attempt_id,
        now=now.clock.local(),
        timezone=None if now.policy is None else now.policy.timezone,
        root=_pools_root(sources),
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
    Tool(
        "test_proxy_request", "rule_sets", "read",
        "What the proxy would do with one request under the policy in force: its action, the groups it falls in, and the rule set and rule number that decided. "
        "Nothing is recorded. at is an ISO 8601 time, household-local when it has no offset, and now when left out. "
        "tasks_completed and quotas (name to seconds_used and bytes_used) are the day's balances to test with, and count as 0 when left out. "
        "They apply to the client group the address falls in, and the child's real usage is never read.",
        test_proxy_request,
        {
            "client_ip": {"type": "string", "description": "The child's address."},
            "method": {"type": "string", "description": "The HTTP method, such as GET."},
            "url": {"type": "string", "description": "The full URL."},
            **{key: {"type": "string", "description": "Fetch metadata header, optional."} for key in FETCH_KEYS},
            "at": {"type": "string", "description": "ISO 8601 time to test at."},
            "tasks_completed": {"type": "integer", "minimum": 0, "description": "Revision tasks the client group completed that day."},
            "quotas": {
                "type": "object",
                "description": "Quota name to its balance that day.",
                "additionalProperties": {
                    "type": "object",
                    "properties": {"seconds_used": {"type": "integer", "minimum": 0}, "bytes_used": {"type": "integer", "minimum": 0}},
                    "additionalProperties": False,
                },
            },
        },
        ("client_ip", "method", "url"), lambda arguments: str(arguments.get("url", "")),
    ),
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
        "get_spelling_words", "attempts", "read",
        "A client group's spelling words, as the words page shows them: the tiles and each word's figures for the period, "
        "filters, chosen tasks, and pools now. Run and weight are all-time, as bin/word-stats gives them. this_week is the "
        "period This week's words chooses. Name a word to add its misspellings and the attempts that asked it.",
        get_spelling_words,
        {
            **_ATTEMPT_FILTERS,
            "task": {"type": "array", "items": {"type": "string"}, "description": "Spelling task names. Every task offered when left out."},
            "pool": {"type": "array", "items": {"type": "string", "enum": list(POOL_CHOICES)}, "description": "Pools now. All when left out. no_pool is a word in none of the tasks' pools."},
            "word": {"type": "string", "description": "A word's entry key, such as necessary or read.1."},
        },
        ("client",), lambda arguments: str(arguments.get("client", "")),
    ),
    Tool(
        "get_parts_of_speech_confusions", "attempts", "read",
        "A client group's parts of speech confusions, as the confusions page shows them: the grid of placements, with a row "
        "for each part the words belong in and a column for each row they were put in, each row's right (a whole "
        "percentage, null when the part was never a row), and the word list. A word the task's filter hid belongs in the "
        "part its pool gives it now, or no_part. Name a pair with belongs and put to add its placements, or a word, with "
        "part if you like, to add the sentences that asked it.",
        get_parts_of_speech_confusions,
        {
            **_ATTEMPT_FILTERS,
            "task": {"type": "array", "items": {"type": "string"}, "description": "Parts of speech task names. Every task offered when left out."},
            "pool": {"type": "array", "items": {"type": "string"}, "description": f"Pool ids now, from list_sentence_pools, or {NO_POOL} for a sentence in none. All when left out."},
            "try": {"type": "array", "items": {"type": "integer", "enum": list(TRY_CHOICES)}, "description": "Tries to count. All when left out."},
            "belongs": {"type": "string", "description": f"A pair's part, such as adverb, or {NO_PART}."},
            "put": {"type": "string", "description": f"A pair's row he put it in, such as adjective, or {LEFT_OUT}."},
            "word": {"type": "string", "description": "A word, such as dry."},
            "part": {"type": "string", "description": f"The part the word belongs in, such as verb, or {NO_PART}. Every part when left out."},
        },
        ("client",), lambda arguments: str(arguments.get("client", "")),
    ),
    Tool(
        "get_attempt", "attempts", "read",
        "One attempt's page: its summary, answers, and timings, with an arithmetic, capitalisation, parts of speech, or spelling "
        "attempt's runs. A parts of speech try has each word's row, or left out, judged as the quiz judged it.",
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
