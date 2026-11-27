"""S007.6: renaming client groups, site groups, time windows, quotas, and rule sets, with their history."""

import json
import shutil
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from asgi import call  # noqa: E402
from test_policy_pages import Policy  # noqa: E402
from test_task_admin import _git  # noqa: E402

from policy import rename_history  # noqa: E402
from policy.task_admin import TaskAdmin  # noqa: E402
from policy.tasks import AttemptStore, TaskKey  # noqa: E402
from policy.usage import UsageStore  # noqa: E402
from policy.usage_graph import Presets, Settings  # noqa: E402

API = "/parent/api/policy"
YOUNGER = "192.0.2.40"
OLDER = "192.0.2.50"
YOUTUBE = "https://www.youtube.com/watch"
POLICY = """\
# The household policy.
entry: gate
timezone: America/Toronto
include:
  - extra.yaml
client_groups:
  younger:
    addresses: ["192.0.2.40"]   # the den
  older:
    addresses: ["192.0.2.50"]
site_groups:
  school:
    priority: 10
    patterns: [classroom.google.com]
  entertainment:
    priority: 30
    patterns: ["*.youtube.com"]
time_windows:
  bedtime:
    periods:
      - { start: "21:00", end: "07:00+1" }   # lights out
quotas:
  entertainment:
    time: 45m   # a school night
    ruleset: meter
rule_sets:
  gate:
    - condition: time_window
      window: bedtime
      when_true: { action: deny, message: "Bedtime." }
    - condition: client_group
      groups: [younger, "older"]   # both
      when_true:
        action: evaluate
        rules:
          - condition: site_group
            groups:
              - entertainment
            when_true: { action: evaluate, ruleset: meter }
            when_false: { action: allow }
    - condition: always
      when_true: { action: allow }
  meter:
    - condition: time_remaining
      quota: entertainment
      when_false: { action: deny, message: "Used up." }
    - condition: always
      when_true: { action: allow }
tasks:
  spelling:
    spelling:
      # Words for this week.
      group: younger
      pass_cooldown: 1   # once a day
      max_skips: 3
      body:
        timeout: 30s
        revision_required: 1
"""
EXTRA = """\
# Tasks in another file.
tasks:
  worksheet:
    sums:
      groups: [younger, older]
      pass_cooldown: 2
"""


def _extra(config: Path) -> None:
    (config / "extra.yaml").write_text(EXTRA, encoding="utf-8")


@pytest.fixture
def house(tmp_path, monkeypatch):
    return Policy(tmp_path, monkeypatch, text=POLICY, before=_extra)


@pytest.fixture
def kept(tmp_path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    return Policy(tmp_path, monkeypatch, history=True, text=POLICY, before=_extra)


def _rename(house: Policy, page: str, name: str, to: str, **extra) -> tuple[int, dict]:
    body = {"version": house.read(page)["version"], "name": name, "to": to, **extra}
    status, answer, _headers = call(house.app, "POST", f"{API}/{page}/rename", json_body=body, cookie=house.cookie)
    return status, json.loads(answer)


def _now(house: Policy):
    return house.app.state.holder.loaded.clock.local()


def _usage(house: Policy) -> UsageStore:
    return UsageStore(house.database)


def _attempts(house: Policy) -> AttemptStore:
    return AttemptStore(house.database)


def _decide(house: Policy, ip: str, url: str = YOUTUBE) -> dict:
    when = _now(house).replace(tzinfo=house.app.state.holder.loaded.clock.zone).isoformat()
    status, body, _headers = call(
        house.app, "POST", "/v1/decisions", scheme="http",
        json_body={"client_ip": ip, "method": "GET", "url": url, "occurred_at": when},
    )
    assert status == 200, body
    return json.loads(body)


def _graph(house: Policy) -> tuple[int, dict]:
    status, body, _headers = call(house.app, "GET", "/parent/api/usage/minutes", query="by=client&range=past-week", cookie=house.cookie)
    return status, json.loads(body)


def _rows(house: Policy, sql: str, *args) -> list[tuple]:
    connection = sqlite3.connect(house.database)
    try:
        return connection.execute(sql, args).fetchall()
    finally:
        connection.close()


# The files


def test_a_client_group_rename_changes_its_key_and_each_reference_in_every_file_and_nothing_else(kept):
    status, body = _rename(kept, "client-groups", "younger", "kids")
    assert status == 200, body
    assert body["name"] == "kids" and "Renamed the client group younger to kids." in body["message"]
    text, extra = kept.text(), kept.text("extra.yaml")
    assert "  kids:\n    addresses: [\"192.0.2.40\"]   # the den\n" in text
    assert "groups: [kids, \"older\"]   # both" in text
    assert "      group: kids\n      pass_cooldown: 1   # once a day\n" in text
    assert "groups: [kids, older]" in extra and "# Tasks in another file." in extra
    assert "younger" not in text and "younger" not in extra
    assert text.replace("kids", "younger") == _git(kept.config, "show", "HEAD~1:policy.yaml")
    subject = _git(kept.config, "log", "--format=%s").splitlines()
    assert subject[0].endswith("ada: renamed client group younger to kids") and len(subject) == 2
    assert kept.app.state.holder.loaded.policy.task(TaskKey("spelling", "spelling")).groups == ("kids",)


def test_a_site_group_a_time_window_and_a_quota_rename_everywhere_a_rule_names_them(house):
    assert _rename(house, "site-groups", "entertainment", "video")[0] == 200
    assert _rename(house, "time-windows", "bedtime", "lights-out")[0] == 200
    assert _rename(house, "quotas", "entertainment", "fun")[0] == 200
    text = house.text()
    assert "  video:\n    priority: 30" in text and "  lights-out:\n" in text and "  fun:\n    time: 45m   # a school night" in text
    assert "            groups:\n              - video\n" in text
    assert "      window: lights-out\n" in text and "      quota: fun\n" in text
    assert "entertainment" not in text.replace("*.youtube.com", "")


def test_a_rule_set_rename_changes_entry_a_quotas_ruleset_and_each_evaluate_and_keeps_every_decision(house):
    before = [_decide(house, ip) for ip in (YOUNGER, OLDER)] + [_decide(house, YOUNGER, "https://example.org/")]
    assert _rename(house, "rule-sets", "gate", "front-door")[0] == 200
    assert _rename(house, "rule-sets", "meter", "the-meter")[0] == 200
    text = house.text()
    assert "entry: front-door\n" in text and "  front-door:\n" in text and "    ruleset: the-meter\n" in text
    assert "ruleset: the-meter }" in text and "gate" not in text and "meter\n" not in text.replace("the-meter", "")
    after = [_decide(house, ip) for ip in (YOUNGER, OLDER)] + [_decide(house, YOUNGER, "https://example.org/")]
    assert [item["action"] for item in after] == [item["action"] for item in before]


def test_a_time_window_used_by_several_rules_keeps_every_decision(house):
    before = _decide(house, YOUNGER, "https://example.org/")
    assert _rename(house, "time-windows", "bedtime", "night")[0] == 200
    assert _decide(house, YOUNGER, "https://example.org/")["action"] == before["action"]


def test_a_name_written_in_quotes_stays_quoted(house):
    house.text()
    (house.config / "policy.yaml").write_text(house.text().replace("group: younger\n", 'group: "younger"\n'), encoding="utf-8")
    assert _rename(house, "client-groups", "younger", "kids")[0] == 200
    assert 'group: "kids"\n' in house.text()


# Names that are refused


@pytest.mark.parametrize(
    "page, name, to, reason",
    [
        ("client-groups", "younger", "older", "already exists"),
        ("client-groups", "younger", "OLDER", "already exists"),
        ("client-groups", "younger", "default", "implicit"),
        ("site-groups", "school", "default", "implicit"),
        ("quotas", "entertainment", "entertainment ", "cannot be a quota's name"),
        ("time-windows", "bedtime", "", "new name"),
        ("rule-sets", "gate", "meter", "already exists"),
    ],
)
def test_a_name_in_use_or_reserved_or_unusable_is_refused_with_the_reason_and_nothing_changes(house, page, name, to, reason):
    before = house.text()
    status, body = _rename(house, page, name, to)
    assert status == 400 and reason in body["error"]
    assert house.text() == before


def test_a_name_the_loader_refuses_is_refused_with_its_reason(house, monkeypatch):
    before = house.text()
    status, body = _rename(house, "site-groups", "school", "a: b")
    assert status == 400
    assert house.text() == before


def test_a_rename_that_changes_only_case_is_allowed(house):
    status, body = _rename(house, "client-groups", "younger", "Younger")
    assert status == 200, body
    assert "  Younger:\n" in house.text() and "groups: [Younger," in house.text()


def test_renaming_an_item_that_is_not_there_or_to_its_own_name_changes_nothing(house):
    assert _rename(house, "client-groups", "nobody", "x")[0] == 404
    status, body = _rename(house, "client-groups", "younger", "younger")
    assert status == 200 and "has not changed" in body["message"]


def test_the_implicit_default_group_cannot_be_renamed(house):
    status, body = _rename(house, "client-groups", "default", "everyone")
    assert status == 400 and "implicit" in body["error"]


def test_a_page_open_on_files_that_have_changed_since_is_refused(house):
    version = house.read("client-groups")["version"]
    (house.config / "policy.yaml").write_text(house.text() + "\n# edited by hand\n", encoding="utf-8")
    status, body = _rename(house, "client-groups", "younger", "kids", version=version)
    assert status == 409 and body["stale"] is True
    assert "younger" in house.text()


def test_the_household_page_has_nothing_to_rename(house):
    status, _body = _rename(house, "household", "entry", "x")
    assert status == 404


@pytest.mark.parametrize(
    "page, section, left_by",
    [("client-groups", "client_groups", "gone"), ("site-groups", "site_groups", "gone"), ("quotas", "quotas", "gone")],
)
def test_a_name_that_a_group_no_longer_in_the_policy_left_history_under_is_refused(house, page, section, left_by):
    with _usage(house) as usage:
        usage.file_observation(left_by, left_by, _now(house) - timedelta(days=1), 100, [left_by])
    only = {"client_groups": "younger", "site_groups": "school", "quotas": "entertainment"}[section]
    before = house.text()
    status, body = _rename(house, page, only, left_by.upper())
    assert status == 400 and "History is still stored under gone" in body["error"]
    assert house.text() == before
    assert _rename(house, page, only, "fresh")[0] == 200


# History


def test_a_client_group_rename_moves_every_stored_row_so_the_history_goes_on_under_the_new_name(house):
    now = _now(house)
    with _usage(house) as usage:
        for days in (3, 2, 1):
            usage.file_observation("younger", "entertainment", now - timedelta(days=days), 600, ["entertainment"], host="www.youtube.com")
        usage.file_observation("older", "entertainment", now - timedelta(days=1), 600, ["entertainment"], host="www.youtube.com")
        usage.record_request(
            "flow-1", started_at=now, client_ip=YOUNGER, client_group="younger", site_group="entertainment",
            method="GET", url=YOUTUBE, outcome="allowed", status=None,
        )
    attempts = _attempts(house)
    started = now - timedelta(hours=3)
    attempt = attempts.begin("younger", TaskKey("spelling", "spelling"), started)
    attempts.finish(attempt.id, "pass", started + timedelta(minutes=5))
    attempts.connection.execute("INSERT INTO parent_checks (client_group, recorded_at) VALUES ('younger', '2026-11-17T08:00:00')")
    attempts.connection.commit()
    status, body = _graph(house)
    assert status == 200 and {line["name"] for line in body["graph"]["lines"]} == {"younger", "older"}

    assert _rename(house, "client-groups", "younger", "kids")[0] == 200

    status, body = _graph(house)
    lines = {line["name"]: line["values"] for line in body["graph"]["lines"]}
    assert set(lines) == {"kids", "older"} and sum(lines["kids"]) > 0
    assert [attempt.task for attempt in _attempts(house).history("kids")] == ["spelling"]
    assert _attempts(house).history("younger") == ()
    assert _rows(house, "SELECT client_group FROM parent_checks") == [("kids",)]
    assert _rows(house, "SELECT DISTINCT client_group FROM requests") == [("kids",)]
    for table in ("group_buckets", "quota_buckets", "host_buckets", "host_quota_buckets"):
        names = {name for (name,) in _rows(house, f"SELECT DISTINCT client_group FROM {table}")}
        assert names == {"kids", "older"}, table


def test_the_figures_read_from_attempts_and_the_task_turn_follow_the_group(house):
    connection = sqlite3.connect(house.database)
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS task_turns (client_group TEXT PRIMARY KEY, turn INTEGER NOT NULL);
        INSERT INTO task_turns VALUES ('younger', 4);
        INSERT INTO spelling_word_tasks (client_group, word, attempt_id, started_at, missed)
            VALUES ('younger', 'rope', 1, '2026-11-17T08:00:00', 0);
        INSERT INTO arithmetic_fact_questions (client_group, operation, m, n, attempt_id, started_at, position, outcome)
            VALUES ('younger', 'add', 2, 3, 1, '2026-11-17T08:00:00', 0, 'correct');
        """
    )
    connection.commit()
    connection.close()
    assert _rename(house, "client-groups", "younger", "kids")[0] == 200
    assert _rows(house, "SELECT client_group, turn FROM task_turns") == [("kids", 4)]
    assert _rows(house, "SELECT client_group FROM spelling_word_tasks") == [("kids",)]
    assert _rows(house, "SELECT client_group FROM arithmetic_fact_questions") == [("kids",)]


def test_a_quota_rename_keeps_the_days_used_so_the_balance_is_the_same(house):
    now = _now(house)
    with _usage(house) as usage:
        moment = now.replace(hour=1, minute=0, second=0, microsecond=0)
        # Read the balance an hour after the usage, not at the real time, which may be before 01:00.
        later = moment + timedelta(hours=1)
        for step in range(8):
            usage.file_observation("younger", "entertainment", moment + timedelta(minutes=5 * step), 100, ["entertainment"])
        used = usage.ended_seconds("younger", "entertainment", later)
    assert used > 0
    assert _rename(house, "quotas", "entertainment", "fun")[0] == 200
    with _usage(house) as usage:
        assert usage.ended_seconds("younger", "fun", later) == used
        assert usage.ended_seconds("younger", "entertainment", later) == 0
        assert usage.quota_clients("fun") == ["younger"]
    assert _rows(house, "SELECT DISTINCT quota FROM host_quota_buckets") == []


def test_a_site_group_rename_moves_the_usage_host_request_and_transfer_rows(house):
    now = _now(house)
    with _usage(house) as usage:
        usage.file_observation("younger", "entertainment", now - timedelta(days=1), 500, ["entertainment"], host="www.youtube.com")
        usage.record_request(
            "flow-2", started_at=now, client_ip=YOUNGER, client_group="younger", site_group="entertainment",
            method="GET", url=YOUTUBE, outcome="allowed", status=None,
        )
    assert _rename(house, "site-groups", "entertainment", "video")[0] == 200
    assert _rows(house, "SELECT DISTINCT site_group FROM group_buckets") == [("video",)]
    assert _rows(house, "SELECT DISTINCT site_group FROM host_buckets") == [("video",)]
    assert _rows(house, "SELECT DISTINCT site_group FROM requests") == [("video",)]
    assert _rows(house, "SELECT DISTINCT quota FROM quota_buckets") == [("entertainment",)]


def test_a_download_running_across_a_quota_rename_keeps_its_ceilings_under_the_new_name(house):
    from policy.usage import Assumption

    with _usage(house) as usage:
        usage.save_transfer(
            "flow-3", "younger", "entertainment", YOUTUBE,
            Assumption(recheck_at=None, ceilings=(("entertainment", 3000), ("other", 10))),
        )
    assert _rename(house, "quotas", "entertainment", "fun")[0] == 200
    assert _rename(house, "client-groups", "younger", "kids")[0] == 200
    with _usage(house) as usage:
        found = usage.transfer("flow-3")
    assert found[0] == "kids" and found[1] == "entertainment" and found[4] == (("fun", 3000), ("other", 10))


def test_a_saved_usage_preset_names_the_new_group_and_quota(house):
    with _usage(house) as usage:
        presets = Presets(usage.connection)
        settings = Settings(clients=("younger", "older"), sites=(), quotas=("entertainment",), by="quota")
        assert presets.save({"name": "Mine", "settings": settings.as_json()}, "ada", _now(house)).status == 200
    assert _rename(house, "client-groups", "younger", "kids")[0] == 200
    assert _rename(house, "quotas", "entertainment", "fun")[0] == 200
    with _usage(house) as usage:
        held = Presets(usage.connection).settings("Mine")
    assert held.clients == ("kids", "older") and held.quotas == ("fun",)


def test_rows_filed_under_the_old_name_while_the_services_reload_are_moved_after_it(house, monkeypatch):
    original = TaskAdmin._reload

    def reloading(self, warnings):
        answer = original(self, warnings)
        with _usage(house) as usage:
            usage.file_observation("younger", "entertainment", _now(house), 100, ["entertainment"])
        return answer

    monkeypatch.setattr(TaskAdmin, "_reload", reloading)
    assert _rename(house, "client-groups", "younger", "kids")[0] == 200
    assert _rows(house, "SELECT DISTINCT client_group FROM group_buckets") == [("kids",)]


def test_moving_again_moves_only_what_has_been_filed_under_the_old_name_since():
    connection = sqlite3.connect(":memory:")
    UsageStore(connection=connection)
    now = "2026-11-17T10:00:00"
    connection.execute("INSERT INTO group_buckets VALUES ('a', 's', '2026-11-17', ?, 300, 1)", (now,))
    assert rename_history.move(connection, "client_groups", "a", "b") == 1
    connection.execute("INSERT INTO group_buckets VALUES ('a', 's', '2026-11-17', '2026-11-17T10:05:00', 300, 1)")
    assert rename_history.move(connection, "client_groups", "a", "b") == 1
    assert rename_history.move(connection, "client_groups", "a", "b") == 0
    assert rename_history.stored_names(connection, "client_groups") == {"b"}


# Taking it back


def test_a_failure_moving_the_rows_puts_every_file_back_and_commits_nothing(kept, monkeypatch):
    def broken(connection, section, old, new):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(rename_history, "move", broken)
    before, extra = kept.text(), kept.text("extra.yaml")
    status, body = _rename(kept, "client-groups", "younger", "kids")
    assert status == 500 and "stored history could not be moved" in body["error"] and "locked" in body["error"]
    assert kept.text() == before and kept.text("extra.yaml") == extra
    assert len(_git(kept.config, "log", "--format=%s").splitlines()) == 1
    assert kept.app.state.holder.loaded.policy.client_group("younger") is not None


def test_a_failure_after_the_reload_puts_the_files_and_the_rows_back_and_reloads_again(kept, monkeypatch):
    with _usage(kept) as usage:
        usage.file_observation("younger", "entertainment", _now(kept) - timedelta(days=1), 100, ["entertainment"])
    real = rename_history.move
    calls: list[tuple[str, str]] = []

    def second_fails(connection, section, old, new):
        calls.append((old, new))
        if (old, new) == ("younger", "kids") and calls.count(("younger", "kids")) == 2:
            raise sqlite3.OperationalError("disk is full")
        return real(connection, section, old, new)

    monkeypatch.setattr(rename_history, "move", second_fails)
    before = kept.text()
    status, body = _rename(kept, "client-groups", "younger", "kids")
    assert status == 500 and "disk is full" in body["error"]
    assert kept.text() == before
    assert _rows(kept, "SELECT DISTINCT client_group FROM group_buckets") == [("younger",)]
    assert len(_git(kept.config, "log", "--format=%s").splitlines()) == 1
    assert kept.app.state.holder.loaded.policy.client_group("younger") is not None
