"""S036.3: the MCP write tools for client groups, site groups, time windows, quotas, rule sets, and the household."""

import json
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_engine import _post_decision  # noqa: E402
from test_mcp_server import activity, call_tool, connect, sign_in, tool_answer, tool_names  # noqa: E402
from test_mcp_writes import TIMES, git  # noqa: E402

from policy.accounts import Accounts  # noqa: E402
from policy.store import PolicyStore  # noqa: E402
from policy.usage import UsageStore  # noqa: E402

PASSWORD = "s3cret-pass"
HOUSE = """\
# The household policy.
timezone: Australia/Sydney
entry: household
include:
  - policy.d
  - tasks.d
client_groups:
  younger:
    addresses: ["192.0.2.40"]   # the den computer
  older:
    addresses: ["192.0.2.41"]
site_groups:
  school:
    priority: 10
    patterns:
      - classroom.google.com   # Classroom
  entertainment:
    priority: 30
    patterns:
      - "*.youtube.com"
time_windows:
  bedtime:
    periods:
      - start: "21:00"   # lights out on Friday
        end: "07:00"
        day: friday
      - start: "20:00"
        end: "07:00"
        days: [sunday, monday, tuesday, wednesday, thursday]
  homework:
    periods:
      - { start: "16:00", end: "17:00" }
rule_sets:
  household:
    - condition: time_window
      window: bedtime
      when_true: { action: deny, message: "Bedtime." }
    - condition: client_group
      groups: [younger, older]
      when_true: { action: evaluate, ruleset: browsing }
  browsing:
    # Entertainment is metered; everything else is allowed.
    - condition: site_group
      group: entertainment
      when_true: { action: evaluate, ruleset: entertainment-time }
      when_false: { action: allow }
"""
LIMITS = """\
# Entertainment limits.
quotas:
  entertainment:
    time: 45m   # a school night
    ruleset: entertainment-sites
rule_sets:
  entertainment-sites:
    - condition: site_group
      group: entertainment
      when_false: { action: deny, message: "Not entertainment." }
  entertainment-time:
    - condition: time_remaining
      quota: entertainment
      when_true: { action: allow }
      when_false: { action: deny, message: "Entertainment time is used up." }
"""
BYPASS = "# Hosts the proxy never sees.\nclassroom.google.com\n"
MCP_FILE = """\
enabled: true
permissions:
  household: [read, update]
  client_groups: [create, read, update, delete]
  site_groups: [create, read, update, delete]
  time_windows: [create, read, update, delete]
  quotas: [create, read, update, delete]
  rule_sets: [create, read, update, delete]
  tasks: [read]
"""
SYDNEY = ZoneInfo("Australia/Sydney")
# Wednesday 21 October 2026, and the Friday after it.
WEDNESDAY = datetime(2026, 10, 21, tzinfo=SYDNEY)
FRIDAY = datetime(2026, 10, 23, tzinfo=SYDNEY)


@pytest.fixture
def house(tmp_path, monkeypatch):
    """The decisions app with a policy split over policy.yaml and policy.d/limits.yaml, and an agent connected."""
    pytest.importorskip("mcp")
    from policy.app import create_app

    built = tmp_path / "dist"
    built.mkdir()
    (built / "index.html").write_text("<!DOCTYPE html><title>Daywarden</title>", encoding="utf-8")
    config = tmp_path / "config"
    (config / "policy.d").mkdir(parents=True)
    (config / "tasks.d").mkdir()
    (config / "policy.yaml").write_text(HOUSE, encoding="utf-8")
    (config / "policy.d" / "limits.yaml").write_text(LIMITS, encoding="utf-8")
    (config / "tasks.d" / "times-6.yaml").write_text(TIMES, encoding="utf-8")
    (config / "bypass.txt").write_text(BYPASS, encoding="utf-8")
    (config / "mcp.yaml").write_text(MCP_FILE, encoding="utf-8")
    if shutil.which("git") is not None:
        git(config, "init", "-q")
        git(config, "add", "-A")
        git(config, "commit", "-qm", "first")
    database = tmp_path / "policy.sqlite3"
    monkeypatch.setenv("POLICY_FILE", str(config / "policy.yaml"))
    monkeypatch.setenv("POLICY_DB", str(database))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "decisions.jsonl"))
    monkeypatch.setenv("PORTAL_DIR", str(built))
    monkeypatch.setenv("PARENT_NAMES", "garden,localhost")
    monkeypatch.setenv("POLICY_PORT", "8084")
    monkeypatch.delenv("MCP_FILE", raising=False)
    with PolicyStore(database) as store:
        Accounts(store.connection).set_password("ada", PASSWORD)
    app = create_app()
    cookie = sign_in(app)
    _client, tokens = connect(app, cookie)
    return House(app, config, tmp_path, tokens["access_token"], cookie)


class House:
    def __init__(self, app, config: Path, root: Path, access: str, cookie: str) -> None:
        self.app, self.config, self.root, self.access, self.cookie = app, config, root, access, cookie

    def ok(self, name: str, arguments: dict) -> dict:
        return tool_answer(self.app, self.access, name, arguments)

    def refused(self, name: str, arguments: dict) -> str:
        result = call_tool(self.app, self.access, name, arguments)
        assert result["isError"] is True, result
        return result["content"][0]["text"]

    def text(self, relative: str) -> str:
        return (self.config / relative).read_text(encoding="utf-8")

    def files(self) -> dict[str, str]:
        return {str(path.relative_to(self.config)): path.read_text() for path in sorted(self.config.rglob("*.*")) if path.is_file() and ".git" not in path.parts}

    def last(self) -> dict:
        return activity(self.app, self.cookie)[0]

    def in_force(self):
        return self.app.state.holder.loaded.policy

    def commit(self) -> str:
        if shutil.which("git") is None:
            pytest.skip("git is not installed")
        return git(self.config, "log", "-1", "--format=%an|%s").strip()

    def decide(self, client: str, url: str, at: datetime) -> tuple[dict, dict]:
        """Return the proxy's decision for a request, and the decision log's entry for it."""
        status, body = _post_decision(
            self.app, {"client_ip": client, "method": "GET", "url": url, "occurred_at": at.isoformat()}
        )
        assert status == 200, body
        lines = (self.root / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
        return json.loads(body), json.loads(lines[-1])

    def used(self, client_group: str, quota: str, start: datetime, minutes: int) -> None:
        """Record ``minutes`` of ended five-minute buckets on a quota from ``start``."""
        with PolicyStore(self.root / "policy.sqlite3") as store:
            usage = UsageStore(connection=store.connection)
            for step in range(0, minutes, 5):
                usage.file_observation(client_group, "entertainment", start + timedelta(minutes=step), 1000, [quota])


# Tools


def test_each_class_has_its_create_update_and_delete_tools_by_permission(house):
    names = set(tool_names(house.app, house.access))
    for singular in ("client_group", "site_group", "time_window", "quota", "rule_set"):
        assert {f"create_{singular}", f"update_{singular}", f"delete_{singular}"} <= names
    assert "update_household" in names
    (house.config / "mcp.yaml").write_text(MCP_FILE.replace("quotas: [create, read, update, delete]", "quotas: [read]"), encoding="utf-8")
    status, _body = _post_reload(house)
    assert status == 200
    assert house.refused("delete_quota", {"name": "entertainment"}) == "This needs quotas: delete."
    assert "entertainment" in house.text("policy.d/limits.yaml")


def _post_reload(house) -> tuple[int, str]:
    from asgi import call

    status, body, _headers = call(house.app, "POST", "/v1/reload", scheme="http")
    return status, body


# Writing


def test_a_new_site_group_is_written_checked_reloaded_committed_and_logged(house):
    found = house.ok("create_site_group", {"name": "games", "priority": 40, "patterns": ["*.minecraft.net", "roblox.com"]})
    assert found["site_group"] == {"name": "games", "priority": 40, "patterns": ["*.minecraft.net", "roblox.com"]}
    assert "Created the site group games" in found["message"]
    text = house.text("policy.yaml")
    assert '  games:\n    priority: 40\n    patterns: ["*.minecraft.net", roblox.com]\n' in text
    assert text.replace('  games:\n    priority: 40\n    patterns: ["*.minecraft.net", roblox.com]\n', "") == HOUSE
    assert house.in_force().site_group("games").patterns == ("*.minecraft.net", "roblox.com")
    assert house.commit().endswith("ada via Claude Code: created site group games")
    logged = house.last()
    assert (logged["tool"], logged["target"], logged["outcome"]) == ("create_site_group", "games", "done")


def test_a_dry_run_shows_the_diff_and_writes_nothing(house):
    before = house.files()
    found = house.ok("update_quota", {"name": "entertainment", "time": "60m", "dry_run": True})
    assert found["dry_run"] is True
    assert "-    time: 45m   # a school night" in found["changes"]
    assert "+    time: 60m   # a school night" in found["changes"]
    assert house.files() == before
    assert house.in_force().quota("entertainment").time_limit == 45 * 60
    assert house.last()["outcome"] == "checked"


@pytest.mark.parametrize(
    "tool, arguments, reason",
    [
        ("create_client_group", {"name": "default", "addresses": ["192.0.2.60"]}, "client group name 'default' is reserved"),
        ("create_site_group", {"name": "games", "priority": 30, "patterns": ["*.roblox.com"]}, "site groups 'entertainment' and 'games' both have priority 30"),
        ("create_client_group", {"name": "guests", "addresses": ["192.0.2.40"]}, "192.0.2.40"),
        ("update_quota", {"name": "entertainment", "time_grace": "-5m"}, "time_grace"),
        ("create_time_window", {"name": "late", "periods": [{"start": 2100, "end": "23:00"}]}, "an unquoted clock is not a time"),
        ("create_time_window", {"name": "late", "periods": [{"start": "25:00", "end": "23:00"}]}, 'must be a quoted time like "07:00"'),
        ("create_time_window", {"name": "late", "periods": [{"start": "21:00", "end": "23:00", "day": "friday", "days": ["saturday"]}]}, "specify day or days, not both"),
        ("create_quota", {"name": "reading", "time": "1h", "ruleset": "nowhere"}, "unknown rule set 'nowhere'"),
        ("update_rule_set", {"name": "browsing", "rules": [{"condition": "site_group", "group": "games"}]}, "unknown site group 'games'"),
        ("update_rule_set", {"name": "browsing", "rules": [{"condition": "always", "when_true": {"action": "evaluate", "ruleset": "nowhere"}}]}, "unknown rule set 'nowhere'"),
        ("update_household", {"entry": "nowhere"}, "entry 'nowhere' does not name a rule set"),
        ("update_household", {"timezone": "Mars/Olympus"}, "Mars/Olympus"),
        ("update_household", {"bucket_length": "7m"}, "bucket_length must divide a 24-hour day"),
    ],
)
def test_a_write_is_refused_with_the_reasons_dw_check_gives(house, tool, arguments, reason):
    before = house.files()
    text = house.refused(tool, arguments)
    assert reason in text
    assert house.files() == before
    logged = house.last()
    assert logged["outcome"] == "refused"
    assert any(reason in item for item in logged["reasons"])


def test_a_change_to_an_included_file_is_written_there_and_policy_yaml_is_unchanged(house):
    house.ok("update_quota", {"name": "entertainment", "time": "60m"})
    assert house.text("policy.yaml") == HOUSE
    assert house.text("policy.d/limits.yaml") == LIMITS.replace("time: 45m", "time: 60m")
    house.ok("create_quota", {"name": "reading", "time": "2h", "ruleset": "entertainment-sites"})
    assert house.text("policy.yaml") == HOUSE
    assert "  reading:\n    time: 2h\n    ruleset: entertainment-sites\n" in house.text("policy.d/limits.yaml")
    house.ok("update_household", {"timezone": "America/Toronto"})
    assert house.text("policy.yaml") == HOUSE.replace("timezone: Australia/Sydney", "timezone: America/Toronto")
    assert house.text("bypass.txt") == BYPASS


def test_a_rule_set_in_an_included_file_is_deleted_there(house):
    house.ok("create_rule_set", {"name": "spare", "rules": [{"condition": "always"}]})
    assert "  spare:\n    - condition: always\n" in house.text("policy.yaml")
    house.ok("delete_rule_set", {"name": "spare"})
    assert house.text("policy.yaml") == HOUSE
    house.ok("update_quota", {"name": "entertainment", "ruleset": "browsing"})
    house.ok("update_rule_set", {"name": "browsing", "rules": [{"condition": "always", "when_true": {"action": "allow"}}]})
    found = house.ok("delete_rule_set", {"name": "entertainment-time"})
    assert found["deleted"] == {"rule_set": "entertainment-time"}
    limits = house.text("policy.d/limits.yaml")
    assert "entertainment-time" not in limits and "entertainment-sites:" in limits
    assert house.in_force().rule_set("entertainment-time") is None


def test_a_file_left_with_nothing_keeps_its_comments(house):
    (house.config / "policy.d" / "extra.yaml").write_text("# Spare windows.\ntime_windows:\n  lunch:\n    periods:\n      - { start: \"12:00\", end: \"13:00\" }\n", encoding="utf-8")
    house.ok("delete_time_window", {"name": "lunch"})
    assert house.text("policy.d/extra.yaml") == "# Spare windows.\n{}\n"
    assert house.in_force().time_window("lunch") is None


# The implicit default and deleting


@pytest.mark.parametrize("tool", ["update_client_group", "delete_client_group", "update_site_group", "delete_site_group"])
def test_the_implicit_default_group_cannot_be_changed_or_deleted(house, tool):
    arguments = {"name": "default"}
    if tool.startswith("update"):
        arguments["addresses" if "client" in tool else "priority"] = ["192.0.2.60"] if "client" in tool else 50
    assert "is implicit" in house.refused(tool, arguments)


def test_deleting_something_in_use_names_each_user(house):
    text = house.refused("delete_time_window", {"name": "bedtime"})
    assert "Time window bedtime is used by rule set household, rule 1." in text
    text = house.refused("delete_client_group", {"name": "younger"})
    assert "Client group younger is used by task arithmetic/times-6." in text
    assert "Client group younger is used by rule set household, rule 2." in text
    text = house.refused("delete_rule_set", {"name": "entertainment-sites"})
    assert "Rule set entertainment-sites is used by quota entertainment." in text
    text = house.refused("delete_rule_set", {"name": "browsing"})
    assert "Rule set browsing is used by rule set household, rule 2 when_true." in text
    assert "Rule set household is used by the household's entry." in house.refused("delete_rule_set", {"name": "household"})
    assert "Quota entertainment is used by rule set entertainment-time, rule 1." in house.refused("delete_quota", {"name": "entertainment"})
    assert "Site group entertainment is used by rule set browsing, rule 1." in house.refused("delete_site_group", {"name": "entertainment"})
    assert house.last()["reasons"] == ["Site group entertainment is used by rule set browsing, rule 1.", "Site group entertainment is used by rule set entertainment-sites, rule 1."]
    house.ok("delete_time_window", {"name": "homework"})
    assert "homework" not in house.text("policy.yaml")


def test_an_inline_rule_that_names_an_item_is_found(house):
    house.ok("create_rule_set", {
        "name": "nested",
        "rules": [{"condition": "always", "when_true": {"action": "evaluate", "rules": [{"condition": "time_window", "window": "homework"}]}}],
    })
    assert "Time window homework is used by rule set nested, rule 1 when_true rule 1." in house.refused("delete_time_window", {"name": "homework"})


def test_names_are_checked_before_anything_is_written(house):
    assert house.refused("create_time_window", {"name": "bedtime", "periods": []}).startswith("A time window named bedtime already exists")
    assert house.refused("update_time_window", {"name": "naptime", "periods": []}) == "There is no time window named naptime."
    assert "is not a field of a quota" in house.refused("update_quota", {"name": "entertainment", "grace": "5m"})
    assert "plain text" in house.refused("create_quota", {"name": "two: words", "ruleset": "browsing"})
    assert house.refused("update_quota", {"name": "entertainment"}).startswith("Name at least one field")


# Each class


def test_an_address_added_to_younger_follows_younger_rules_at_once(house):
    at = WEDNESDAY.replace(hour=11)
    decision, logged = house.decide("192.0.2.50", "https://classroom.google.com/", at)
    assert logged["client_group"] == "default" and decision["action"] == "deny"
    found = house.ok("update_client_group", {"name": "younger", "addresses": ["192.0.2.40", "192.0.2.50"]})
    assert found["client_group"] == {"name": "younger", "addresses": ["192.0.2.40", "192.0.2.50"]}
    assert '    addresses: [192.0.2.40, 192.0.2.50]   # the den computer\n' in house.text("policy.yaml")
    decision, logged = house.decide("192.0.2.50", "https://classroom.google.com/", at)
    assert logged["client_group"] == "younger" and decision["action"] == "allow"
    house.ok("create_client_group", {"name": "guests", "addresses": ["192.0.2.70"]})
    house.ok("delete_client_group", {"name": "guests"})
    assert house.text("policy.yaml") == HOUSE.replace('["192.0.2.40"]', "[192.0.2.40, 192.0.2.50]")


def test_a_pattern_added_to_entertainment_meters_and_blocks_the_site(house):
    at = WEDNESDAY.replace(hour=11)
    _decision, logged = house.decide("192.0.2.40", "https://www.minecraft.net/", at)
    assert logged["site_group"] == "default"
    house.ok("update_site_group", {"name": "entertainment", "patterns": ["*.youtube.com", "*.minecraft.net"]})
    assert '      - "*.youtube.com"\n      - "*.minecraft.net"\n' in house.text("policy.yaml")
    assert house.in_force().site_group("entertainment").priority == 30
    decision, logged = house.decide("192.0.2.40", "https://www.minecraft.net/", at)
    assert logged["site_group"] == "entertainment" and decision["action"] == "allow"
    house.used("younger", "entertainment", WEDNESDAY.replace(hour=10), 50)
    decision, _logged = house.decide("192.0.2.40", "https://www.minecraft.net/", at)
    assert decision == {"action": "deny", "status": 403, "message": "Entertainment time is used up."}


def test_raising_a_quota_lets_entertainment_through_until_the_new_limit(house):
    house.used("younger", "entertainment", WEDNESDAY.replace(hour=10), 50)
    at = WEDNESDAY.replace(hour=11)
    assert house.decide("192.0.2.40", "https://www.youtube.com/", at)[0]["action"] == "deny"
    found = house.ok("update_quota", {"name": "entertainment", "time": "60m"})
    assert found["quota"]["time"] == "1h"
    assert found["quota"]["ruleset"] == "entertainment-sites"
    assert house.decide("192.0.2.40", "https://www.youtube.com/", at)[0]["action"] == "allow"
    assert house.decide("192.0.2.40", "https://www.youtube.com/", at.replace(hour=12))[0]["action"] == "allow"
    house.used("younger", "entertainment", WEDNESDAY.replace(hour=11), 10)
    assert house.decide("192.0.2.40", "https://www.youtube.com/", at.replace(hour=12))[0]["action"] == "deny"
    found = house.ok("update_quota", {"name": "entertainment", "bytes": "500M", "time_grace": "0s"})
    assert found["quota"]["bytes"] == "500M"
    assert house.in_force().quota("entertainment").time_grace == 0
    house.ok("update_quota", {"name": "entertainment", "bytes": None})
    assert "bytes" not in house.text("policy.d/limits.yaml")


def test_moving_the_friday_bedtime_later_changes_the_next_decision(house):
    at = FRIDAY.replace(hour=21, minute=30)
    assert house.decide("192.0.2.40", "https://classroom.google.com/", at)[0]["message"] == "Bedtime."
    periods = [
        {"start": "22:00", "end": "07:00", "day": "friday"},
        {"start": "20:00", "end": "07:00", "days": ["sunday", "monday", "tuesday", "wednesday", "thursday"]},
    ]
    found = house.ok("update_time_window", {"name": "bedtime", "periods": periods})
    assert found["time_window"]["periods"][0] == {"start": "22:00", "end": "07:00", "days": ["friday"]}
    text = house.text("policy.yaml")
    # The changed period is written again; the unchanged one keeps its text.
    assert '      - start: "22:00"\n        end: "07:00"\n        day: friday\n      - start: "20:00"\n        end: "07:00"\n        days: [sunday, monday, tuesday, wednesday, thursday]\n' in text
    assert house.decide("192.0.2.40", "https://classroom.google.com/", at)[0]["action"] == "allow"
    assert house.decide("192.0.2.40", "https://classroom.google.com/", at.replace(hour=22, minute=30))[0]["message"] == "Bedtime."


def test_a_period_whose_start_equals_its_end_is_24_hours(house):
    found = house.ok("create_time_window", {"name": "saturday", "periods": [{"start": "00:00", "end": "00:00", "day": "saturday"}]})
    assert found["time_window"] == {"name": "saturday", "periods": [{"start": "00:00", "end": "00:00", "days": ["saturday"]}]}
    found = house.ok("create_time_window", {"name": "weekend", "periods": [{"start": "21:00", "end": "21:00+2", "day": "friday"}]})
    assert found["time_window"]["periods"] == [{"start": "21:00", "end": "21:00+2", "days": ["friday"]}]
    assert '  saturday:\n    periods:\n      - start: "00:00"\n        end: "00:00"\n        day: saturday\n' in house.text("policy.yaml")
    house.ok("update_rule_set", {
        "name": "household",
        "rules": [
            {"condition": "time_window", "window": "saturday", "when_true": {"action": "deny", "message": "Saturday is a day off."}},
            {"condition": "time_window", "window": "bedtime", "when_true": {"action": "deny", "message": "Bedtime."}},
            {"condition": "client_group", "groups": ["younger", "older"], "when_true": {"action": "evaluate", "ruleset": "browsing"}},
        ],
    })
    saturday = FRIDAY + timedelta(days=1)
    assert house.decide("192.0.2.40", "https://classroom.google.com/", saturday.replace(hour=23, minute=59))[0]["message"] == "Saturday is a day off."


def test_a_rule_set_is_its_whole_ordered_list_and_an_action_left_out_continues(house):
    rules = [
        {"condition": "site_group", "group": "school", "when_true": {"action": "allow"}},
        {"condition": "site_group", "group": "entertainment", "when_true": {"action": "evaluate", "ruleset": "entertainment-time"}, "when_false": {"action": "allow"}},
    ]
    found = house.ok("update_rule_set", {"name": "browsing", "rules": rules})
    shown = found["rule_set"]["rules"]
    assert shown[0] == {"condition": "site_group", "groups": ["school"], "when_true": {"action": "allow"}, "when_false": {"action": "continue"}}
    text = house.text("policy.yaml")
    assert "      when_true: { action: allow }\n" in text
    # Rules are matched by place: the first is written again under the comment above it, and the second is added.
    assert "    # Entertainment is metered; everything else is allowed.\n" in text
    assert text.index("group: school") < text.index("group: entertainment")


def test_a_household_setting_not_yet_written_goes_after_entry(house):
    found = house.ok("update_household", {"bucket_length": "10m"})
    assert found["household"]["bucket_length"] == "10m"
    assert "entry: household\nbucket_length: 10m\ninclude:" in house.text("policy.yaml")
    assert house.in_force().bucket_length == 600
    house.ok("update_household", {"bucket_length": None, "entry": "browsing"})
    assert house.text("policy.yaml") == HOUSE.replace("entry: household", "entry: browsing")
    assert house.commit().endswith("ada via Claude Code: saved household settings")
