"""Decide a request by walking nested rule sets.

The request is classified once. Site groups are tried in priority order,
lowest number first, and the first pattern match is the site group. Anything
left over is the implicit site group ``default``. The source address belongs
to the one configured client group that contains it, or to the implicit
client group ``default``. Rules test those two names. They do not match the
URL or the address again, and a site group does not own a rule list.

``decide`` is the access path. It starts at ``entry``. ``allow``, ``deny``,
and ``redirect`` are terminal at every depth. ``evaluate`` substitutes the
child set's decision, including ``continue``. A ``continue`` that reaches
this call, which has no parent, becomes a deny: "No rule granted access."

``evaluate`` is the same walk for a caller that wants the raw decision.
A quota uses it, and a continue there stays a continue. ``revision_task``
is replaced with the household URL before either answer is returned.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from policy.clients import normalize_ip
from policy.groups import matches
from policy.hierarchy import Action, Period, Policy, Rule
from policy.rules import REVISION_TASK, UNCONFIGURED_TASK_MESSAGE, absolute_http_url

NO_RULE_MESSAGE = "No rule granted access."


@dataclass(frozen=True)
class Trace:
    """What was decided, and which rule produced it.

    ``rule_set`` is a rule-set name, or the path of an inline list. ``rule_index``
    counts from 1 in that list. Both are None when a top-level continue became
    the deny in ``decision``. ``continued`` is true only in that case.
    """

    client_group: str
    site_group: str
    rule_set: str | None
    rule_index: int | None
    continued: bool
    decision: dict


class Ledger:
    """The counts an access rule reads.

    Successes stay zero until S003 stores them. Ended seconds and stored bytes
    are one client group's balance on a named quota. ``policy.usage.UsageStore``
    records those. A missing row and an empty ledger answer the same way.

    ``when`` is a household-local time, or a date. A time is what decides
    whether a bucket has ended. A date means the whole of that local day.
    """

    def successes(self, client_group: str, day: date) -> int:
        return 0

    def ended_seconds(self, client_group: str, quota: str, when: date | datetime) -> int:
        return 0

    def stored_bytes(self, client_group: str, quota: str, when: date | datetime) -> int:
        return 0


class MemoryLedger(Ledger):
    """Counts kept in the process, for a test or a caller that has no database yet."""

    def __init__(self) -> None:
        self._successes: dict[tuple[str, date], int] = {}
        self._seconds: dict[tuple[str, str, date], int] = {}
        self._bytes: dict[tuple[str, str, date], int] = {}

    def set_successes(self, client_group: str, day: date, count: int) -> None:
        self._successes[(client_group, day)] = count

    def set_ended_seconds(self, client_group: str, quota: str, day: date, seconds: int) -> None:
        self._seconds[(client_group, quota, day)] = seconds

    def set_stored_bytes(self, client_group: str, quota: str, day: date, count: int) -> None:
        self._bytes[(client_group, quota, day)] = count

    def successes(self, client_group: str, day: date) -> int:
        return self._successes.get((client_group, day), 0)

    def ended_seconds(self, client_group: str, quota: str, when: date | datetime) -> int:
        return self._seconds.get((client_group, quota, _day(when)), 0)

    def stored_bytes(self, client_group: str, quota: str, when: date | datetime) -> int:
        return self._bytes.get((client_group, quota, _day(when)), 0)


@dataclass(frozen=True)
class _Facts:
    policy: Policy
    client_group: str
    site_group: str
    at: datetime
    ledger: Ledger


@dataclass(frozen=True)
class _Hit:
    action: Action
    rule_set: str
    rule_index: int


def classify_site(policy: Policy, url: str) -> str:
    """Return the site group for url.

    Configured groups are tried lowest priority number first. ``default`` is
    what remains after every one of them misses. It is not tried in between.
    """
    ordered = sorted(policy.site_groups, key=lambda group: group.priority)
    for group in ordered:
        if any(matches(pattern, url) for pattern in group.patterns):
            return group.name
    return "default"


def classify_client(policy: Policy, client_ip: str) -> str:
    """Return the client group that contains client_ip, or ``default``."""
    ip = normalize_ip(client_ip)
    if ip is None:
        return "default"
    for group in policy.client_groups:
        if ip in group.ips:
            return group.name
    return "default"


def log_fields(trace: Trace) -> dict:
    """Return the decision-log fields that name the groups and the deciding rule."""
    return {
        "client_group": trace.client_group,
        "site_group": trace.site_group,
        "rule_set": trace.rule_set,
        "rule_index": trace.rule_index,
        "continued": trace.continued,
        "decision": dict(trace.decision),
    }


def decide(
    policy: Policy,
    *,
    client_ip: str,
    url: str,
    at: datetime,
    ledger: Ledger | None = None,
) -> Trace:
    """Judge one request on the access path.

    ``at`` is already household-local. The client group and the site group are
    classified once, then ``entry`` is evaluated with no parent. A continue
    from that evaluation is a deny.
    """
    client_group = classify_client(policy, client_ip)
    site_group = classify_site(policy, url)
    rules = policy.rule_set(policy.entry)
    if rules is None:
        return _fallthrough(client_group, site_group)
    trace = evaluate(
        policy,
        rules,
        client_group=client_group,
        site_group=site_group,
        at=at,
        ledger=ledger,
        rule_set=policy.entry,
    )
    if trace.decision.get("action") == "continue":
        return _fallthrough(client_group, site_group)
    return trace


def evaluate(
    policy: Policy,
    rules: tuple[Rule, ...],
    *,
    client_group: str,
    site_group: str,
    at: datetime,
    ledger: Ledger | None = None,
    rule_set: str,
) -> Trace:
    """Walk ``rules`` and return that set's own decision, including continue.

    This is not the access path. A continue is still a continue, which is
    what a quota reads when it asks whether traffic belongs to it. ``rule_set``
    is the name or the inline path used when this list itself produces the hit.
    """
    facts = _Facts(policy, client_group, site_group, at, ledger or Ledger())
    hit = _walk(rules, rule_set, facts, ())
    if hit is None:
        return Trace(client_group, site_group, rule_set, None, False, {"action": "continue"})
    return Trace(
        client_group,
        site_group,
        hit.rule_set,
        hit.rule_index,
        False,
        _answered(hit.action, policy),
    )


def _day(when: date | datetime) -> date:
    """Return the local date of a ledger lookup.

    A datetime is already household-local. Its date is taken as it stands,
    not shifted into another zone. ``datetime`` is a ``date``, so the time
    check has to come first.
    """
    if isinstance(when, datetime):
        return when.date()
    if type(when) is date:
        return when
    raise ValueError("usage is read at a date or a time")


def _fallthrough(client_group: str, site_group: str) -> Trace:
    return Trace(
        client_group,
        site_group,
        None,
        None,
        True,
        {"action": "deny", "status": 403, "message": NO_RULE_MESSAGE},
    )


def _walk(rules: tuple[Rule, ...], label: str, facts: _Facts, seen: tuple[int, ...]) -> _Hit | None:
    marker = id(rules)
    if marker in seen:
        return _Hit(Action("deny", message=NO_RULE_MESSAGE), label, 1)
    seen = seen + (marker,)
    for index, rule in enumerate(rules, start=1):
        holds = _holds(rule, facts)
        action = rule.when_true if holds else rule.when_false
        if action.kind == "continue":
            continue
        if action.kind == "evaluate":
            hit = _evaluated(action, holds, label, index, facts, seen)
            if hit is None:
                continue
            return hit
        return _Hit(action, label, index)
    return None


def _evaluated(
    action: Action,
    holds: bool,
    label: str,
    index: int,
    facts: _Facts,
    seen: tuple[int, ...],
) -> _Hit | None:
    branch = "when_true" if holds else "when_false"
    if action.ruleset is not None:
        child = facts.policy.rule_set(action.ruleset)
        if child is None:
            return _Hit(Action("deny", message=NO_RULE_MESSAGE), label, index)
        return _walk(child, action.ruleset, facts, seen)
    child = action.rules or ()
    return _walk(child, f"{label} rule {index} {branch}", facts, seen)


def _holds(rule: Rule, facts: _Facts) -> bool:
    if rule.condition == "always":
        return True
    if rule.condition == "time_window":
        return any(_window_contains(facts.policy, name, facts.at) for name in rule.windows)
    if rule.condition == "site_group":
        return facts.site_group in rule.groups
    if rule.condition == "client_group":
        return facts.client_group in rule.groups
    if rule.condition == "tasks_required":
        required = 0 if rule.required is None else rule.required
        return facts.ledger.successes(facts.client_group, facts.at.date()) >= required
    if rule.condition == "time_remaining":
        quota = facts.policy.quota(rule.quota or "")
        if quota is None:
            return False
        used = facts.ledger.ended_seconds(facts.client_group, quota.name, facts.at)
        return used < quota.time_limit
    if rule.condition == "volume_remaining":
        quota = facts.policy.quota(rule.quota or "")
        if quota is None:
            return False
        used = facts.ledger.stored_bytes(facts.client_group, quota.name, facts.at)
        return used < quota.byte_limit
    return False


def _window_contains(policy: Policy, name: str, at: datetime) -> bool:
    window = policy.time_window(name)
    if window is None:
        return False
    return any(_period_contains(period, at) for period in window.periods)


def _period_contains(period: Period, at: datetime) -> bool:
    """True when at sits in this period.

    The start clock is included and the end is excluded. An end clock later
    than the start falls on the same day. An earlier end clock falls on the
    next day, and the named day is the day the period starts, so Saturday
    morning is still Friday night when Friday is the only start. Equal clocks
    are 24 hours, not an empty period. ``+n`` adds that many times 24 hours
    after that end. A start on an earlier day still contains ``at`` when the
    span reaches it. That is not a second start.
    """
    zone = at.tzinfo
    for back in range(period.extra_days + 3):
        day = at.date() - timedelta(days=back)
        if period.weekdays is not None and day.weekday() not in period.weekdays:
            continue
        start = datetime.combine(day, period.start, tzinfo=zone)
        end = _base_end(start, period.end) + timedelta(hours=24 * period.extra_days)
        if start <= at < end:
            return True
    return False


def _base_end(start: datetime, end_clock: time) -> datetime:
    """Return the first moment after start at which the clock shows end_clock.

    Equal clocks are 24 hours later, which is the moment the spec adds extra
    days onto. A later clock is the same calendar day. An earlier clock is
    the next calendar day.
    """
    start_clock = start.timetz().replace(tzinfo=None)
    if end_clock == start_clock:
        return start + timedelta(hours=24)
    day = start.date()
    if end_clock < start_clock:
        day += timedelta(days=1)
    return datetime.combine(day, end_clock, tzinfo=start.tzinfo)


def _answered(action: Action, policy: Policy) -> dict:
    if action.kind == "allow":
        return {"action": "allow"}
    if action.kind == "deny":
        return {"action": "deny", "status": 403, "message": action.message}
    if action.kind == "redirect":
        location = policy.revision_task if action.location == REVISION_TASK else action.location
        if location and absolute_http_url(location):
            return {"action": "redirect", "status": 302, "location": location}
        return {"action": "deny", "status": 403, "message": UNCONFIGURED_TASK_MESSAGE}
    return {"action": "deny", "status": 403, "message": NO_RULE_MESSAGE}
