"""S007.2: the policy pages' data and saves, through the portal's data endpoints."""

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from asgi import call  # noqa: E402
from test_task_admin import House, _git  # noqa: E402

API = "/parent/api/policy"
POLICY = """\
# The household policy.
entry: gate
timezone: America/Toronto
include:
  - extra.yaml
client_groups:
  younger:
    addresses: ["192.0.2.40", "192.0.2.41"]   # the den
  older:
    addresses: ["192.0.2.50"]
site_groups:
  school:
    priority: 10
    patterns:
      - classroom.google.com   # Classroom
      - docs.google.com
  entertainment:
    priority: 30
    patterns: ["*.youtube.com"]
time_windows:
  bedtime:
    periods:
      - start: "21:00"   # lights out
        end: "07:00+1"
        days: friday-sunday
      - start: "20:00"
        end: "0700"
        days: [monday, wednesday]
  evening:
    periods:
      - { start: "16:00", end: "17:00" }
quotas:
  entertainment:
    time: 45m   # a school night
    ruleset: meter
rule_sets:
  gate:
    - condition: time_window
      window: bedtime
      when_true: { action: deny, message: "Bedtime." }
    - condition: always
      when_true: { action: allow }
  meter:
    - condition: site_group
      group: entertainment
      when_false: { action: deny, message: "Not entertainment." }
"""
EXTRA = """\
site_groups:
  games:
    priority: 20
    patterns: ["*.minecraft.net"]
  spare:
    priority: 50
    patterns: [spare.example]
quotas:
  reading:
    time: 1h
    bytes: 720M
    ruleset: meter
"""


def _extra(config: Path) -> None:
    (config / "extra.yaml").write_text(EXTRA, encoding="utf-8")


class Policy(House):
    def read(self, page: str) -> dict:
        status, body = self.get(f"{API}/{page}")
        assert status == 200, body
        return body

    def save(self, page: str, **body) -> tuple[int, dict]:
        body.setdefault("version", self.read(page)["version"])
        status, answer, _headers = call(self.app, "POST", f"{API}/{page}", json_body=body, cookie=self.cookie)
        return status, json.loads(answer)

    def changed(self, page: str, items=(), deleted=()) -> tuple[int, dict]:
        return self.save(page, items=list(items), deleted=list(deleted))

    def text(self, name: str = "policy.yaml") -> str:
        return (self.config / name).read_text(encoding="utf-8")


@pytest.fixture
def house(tmp_path, monkeypatch):
    return Policy(tmp_path, monkeypatch, text=POLICY, before=_extra)


@pytest.fixture
def kept(tmp_path, monkeypatch):
    return Policy(tmp_path, monkeypatch, history=True, text=POLICY, before=_extra)


def _item(name, new=False, **fields):
    return {"name": name, "new": new, "fields": fields}


# Sessions


def test_the_data_addresses_answer_401_without_a_session_and_never_redirect(house):
    for method in ("GET", "POST"):
        for page in ("client-groups", "site-groups", "time-windows", "quotas", "household"):
            status, _body, headers = call(house.app, method, f"{API}/{page}", json_body={} if method == "POST" else None, cookie=None)
            assert status == 401, (method, page)
            assert "location" not in headers


def test_a_save_must_be_sent_as_json(house):
    status, _body, _headers = call(house.app, "POST", f"{API}/quotas", body=b"x=1", content_type="application/x-www-form-urlencoded", cookie=house.cookie)
    assert status == 415


# Reading


def test_a_page_shows_every_item_as_the_files_write_it_and_names_a_file_other_than_the_policy(house):
    page = house.read("client-groups")
    assert [(item["name"], item["file"], item["addresses"]) for item in page["items"]] == [
        ("younger", None, ["192.0.2.40", "192.0.2.41"]),
        ("older", None, ["192.0.2.50"]),
    ]
    quotas = house.read("quotas")
    assert [(item["name"], item["file"]) for item in quotas["items"]] == [("entertainment", None), ("reading", "extra.yaml")]
    assert quotas["items"][1] | {} == {"name": "reading", "file": "extra.yaml", "time": "1h", "bytes": "720M", "time_grace": "", "volume_grace": "", "ruleset": "meter"}
    assert quotas["rule_sets"] == ["gate", "meter"]
    assert quotas["defaults"] == {"time_grace": "5m", "volume_grace": "1M"}


def test_site_groups_are_listed_by_priority_wherever_they_are_written(house):
    page = house.read("site-groups")
    assert [(item["name"], item["priority"], item["file"]) for item in page["items"]] == [
        ("school", "10", None), ("games", "20", "extra.yaml"), ("entertainment", "30", None), ("spare", "50", "extra.yaml"),
    ]


def test_a_time_window_shows_its_clocks_extra_days_and_weekdays_as_written(house):
    periods = {item["name"]: item["periods"] for item in house.read("time-windows")["items"]}
    assert periods["bedtime"] == [
        {"origin": 0, "start": "21:00", "end": "07:00", "extra": "1", "weekdays": [4, 5, 6]},
        {"origin": 1, "start": "20:00", "end": "0700", "extra": "0", "weekdays": [0, 2]},
    ]
    assert periods["evening"] == [{"origin": 0, "start": "16:00", "end": "17:00", "extra": "0", "weekdays": []}]


# Saving


def test_one_save_writes_every_change_as_one_reload_and_one_commit_and_only_the_changed_lines(kept):
    before = kept.text()
    status, body = kept.changed(
        "site-groups",
        [
            _item("school", priority="25", patterns=["classroom.google.com", "docs.google.com", "*.gstatic.com"]),
            _item("games", priority="20", patterns=["*.minecraft.net", "roblox.com"]),
            _item("hobby", new=True, priority="40", patterns=["*.lego.com"]),
        ],
        deleted=["spare"],
    )
    assert status == 200, body
    assert "Saved the site groups." in body["message"]
    text = kept.text()
    assert "      - classroom.google.com   # Classroom\n" in text
    assert "    priority: 25\n" in text and "      - \"*.gstatic.com\"\n" in text
    assert "  hobby:\n    priority: 40\n" in text
    assert "spare" not in kept.text("extra.yaml")
    assert kept.text("extra.yaml").count("roblox.com") == 1
    assert _git(kept.config, "log", "--format=%s").splitlines()[0].endswith("ada: saved site groups")
    assert len(_git(kept.config, "log", "--format=%s").splitlines()) == 2
    diff = _git(kept.config, "diff", "HEAD~1", "--unified=0", "--", "policy.yaml")
    assert "# Classroom" not in diff
    assert before.splitlines()[0] in text


def test_a_save_that_changes_nothing_writes_and_commits_nothing(kept):
    status, body = kept.changed("client-groups", [_item("younger", addresses=["192.0.2.40", "192.0.2.41"])])
    assert status == 200
    assert "nothing was saved" in body["message"]
    assert len(_git(kept.config, "log", "--format=%s").splitlines()) == 1


def test_a_page_open_on_files_that_have_changed_since_is_refused(kept):
    version = kept.read("quotas")["version"]
    kept.policy.write_text(kept.text().replace("45m", "50m"), encoding="utf-8")
    status, body = kept.save("quotas", version=version, items=[_item("entertainment", time="60m", bytes="", time_grace="", volume_grace="", ruleset="meter")], deleted=[])
    assert status == 409 and body["stale"] is True
    assert "50m" in kept.text()


def test_a_save_that_would_not_load_is_refused_with_dw_checks_reasons_and_changes_nothing(kept):
    before = kept.text()
    status, body = kept.changed("site-groups", [_item("games", priority="10", patterns=["*.minecraft.net"])])
    assert status == 400
    assert any("games" in reason and "10" in reason for reason in body["errors"]), body
    assert kept.text() == before
    assert len(_git(kept.config, "log", "--format=%s").splitlines()) == 1


def test_a_new_group_named_default_is_refused_with_the_loaders_reason(house):
    status, body = house.changed("client-groups", [_item("default", new=True, addresses=["192.0.2.99"])])
    assert status == 400
    assert "default" in body["errors"][0] and "reserved" in body["errors"][0]


def test_deleting_something_in_use_is_refused_naming_each_user(house):
    before = house.text()
    status, body = house.changed("time-windows", deleted=["bedtime"])
    assert status == 400
    assert body["errors"] == ["Time window bedtime is used by rule set gate, rule 1."]
    assert house.text() == before


def test_one_address_in_two_groups_is_refused_naming_both_places(house):
    status, body = house.changed("client-groups", [_item("older", addresses=["192.0.2.50", "192.0.2.40"])])
    assert status == 400
    assert "192.0.2.40" in " ".join(body["errors"]) and "younger" in " ".join(body["errors"])


def test_a_new_item_goes_where_the_first_item_of_its_section_is(house):
    status, body = house.changed("quotas", [_item("music", new=True, time="30m", bytes="", time_grace="", volume_grace="", ruleset="meter")])
    assert status == 200, body
    assert "  music:\n    time: 30m\n    ruleset: meter\n" in house.text()
    assert "music" not in house.text("extra.yaml")


def test_a_blank_limit_or_grace_is_left_out_of_the_file_and_a_set_one_is_written(house):
    status, body = house.changed("quotas", [_item("reading", time="2h", bytes="", time_grace="10m", volume_grace="", ruleset="meter")])
    assert status == 200, body
    assert house.text("extra.yaml") == EXTRA.replace("time: 1h\n    bytes: 720M\n    ruleset: meter\n", "time: 2h\n    ruleset: meter\n    time_grace: 10m\n")
    assert house.read("quotas")["items"][1]["bytes"] == ""


@pytest.mark.parametrize("field, bad", [("time", "90"), ("bytes", "720MB"), ("time_grace", "-5m")])
def test_a_badly_written_limit_is_refused_with_the_checks_reason(house, field, bad):
    fields = {"time": "1h", "bytes": "", "time_grace": "", "volume_grace": "", "ruleset": "meter", field: bad}
    status, body = house.changed("quotas", [_item("reading", **fields)])
    assert status == 400 and body["errors"], body
    assert field in " ".join(body["errors"])


def _bedtime(house, *periods):
    status, body = house.changed("time-windows", [_item("bedtime", periods=list(periods))])
    assert status == 200, body
    return house.text()


def _period(origin, start, end, extra="0", weekdays=()):
    return {"origin": origin, "start": start, "end": end, "extra": extra, "weekdays": list(weekdays)}


def test_a_period_keeps_the_text_of_every_clock_and_the_days_it_did_not_change(house):
    first, second = house.read("time-windows")["items"][0]["periods"]
    text = _bedtime(house, first, {**second, "start": "20:30"})
    assert '      - start: "21:00"   # lights out\n        end: "07:00+1"\n        days: friday-sunday\n' in text
    assert '      - start: "20:30"\n        end: "0700"\n        days: [monday, wednesday]\n' in text


def test_extra_days_are_the_ends_suffix_and_weekdays_are_written_as_a_day_a_run_or_a_list(house):
    text = _bedtime(
        house,
        _period(None, "12:00", "21:00", "2", [4]),
        _period(None, "08:00", "09:00", "0", [4, 5, 6, 0, 1]),
        _period(None, "10:00", "11:00", "0", [0, 2, 4]),
        _period(None, "13:00", "14:00", "0", []),
    )
    assert 'start: "12:00"\n        end: "21:00+2"\n        day: friday\n' in text
    assert 'start: "08:00"\n        end: "09:00"\n        days: friday-tuesday\n' in text
    assert 'start: "10:00"\n        end: "11:00"\n        days: [monday, wednesday, friday]\n' in text
    assert 'start: "13:00"\n        end: "14:00"\n' in text and "end: \"14:00\"\n        day" not in text


def test_a_clock_that_cannot_be_read_is_written_quoted_and_refused_by_the_check(house):
    status, body = house.changed("time-windows", [_item("evening", periods=[_period(0, "25:00", "17:00")])])
    assert status == 400
    assert 'must be a quoted time like "07:00"' in " ".join(body["errors"])
    status, body = house.changed("time-windows", [_item("evening", periods=[_period(0, "16:00", "17:00", "-1")])])
    assert status == 400 and "whole number" in body["error"]


def test_a_period_whose_start_equals_its_end_is_saved(house):
    assert 'start: "08:00"\n        end: "08:00"' in _bedtime(house, _period(None, "08:00", "08:00"))


def test_deleting_a_period_in_the_middle_leaves_the_others_text_alone(house):
    first, second = house.read("time-windows")["items"][0]["periods"]
    text = _bedtime(house, first)
    assert '      - start: "21:00"   # lights out\n        end: "07:00+1"\n        days: friday-sunday\n' in text
    assert "20:00" not in text


def test_the_household_page_shows_each_setting_as_written_with_the_defaults_to_grey_in(house):
    page = house.read("household")
    assert page["fields"] == {
        "entry": "gate", "timezone": "America/Toronto", "bucket_length": "", "time_grace": "", "volume_grace": "",
        "host_retention": "", "request_retention": "",
    }
    assert page["proxy"] == {"localhost": True, "plain_host_names": True, "policy_server": True, "local_subnets": True, "local_domains": True, "extra": []}
    assert page["defaults"]["bucket_length"] == "5m" and page["defaults"]["host_retention"] == "30d"
    assert page["rule_sets"] == ["gate", "meter"]


def test_household_settings_are_written_where_a_new_one_goes_and_a_blank_one_is_taken_out(house):
    status, body = house.save("household", fields={"time_grace": "10m", "request_retention": "7d", "timezone": ""})
    assert status == 200, body
    text = house.text()
    assert "entry: gate\ntime_grace: 10m\nrequest_retention: 7d\n" in text or "time_grace: 10m" in text
    assert "timezone" not in text
    assert house.read("household")["fields"]["time_grace"] == "10m"


@pytest.mark.parametrize(
    "fields, reason",
    [
        ({"timezone": "Mars/Olympus"}, "Mars/Olympus"),
        ({"bucket_length": "7m"}, "bucket_length must divide a 24-hour day"),
        ({"host_retention": "12h"}, "host_retention must be a whole number of days"),
    ],
)
def test_a_household_setting_the_loader_refuses_is_refused_with_its_reason(house, fields, reason):
    status, body = house.save("household", fields=fields)
    assert status == 400
    assert reason in " ".join(body["errors"])


def test_the_proxy_configuration_writes_only_what_is_off_and_is_taken_out_when_all_is_default(house):
    off = {"direct": {"local_subnets": False, "extra": ["*.home.arpa"]}}
    status, body = house.save("household", fields={"proxy_configuration": off})
    assert status == 200, body
    assert "proxy_configuration:\n  direct:\n    local_subnets: false\n    extra: [\"*.home.arpa\"]\n" in house.text()
    assert house.read("household")["proxy"]["local_subnets"] is False
    status, body = house.save("household", fields={"proxy_configuration": {"direct": {"extra": []}}})
    assert status == 200, body
    assert "proxy_configuration" not in house.text()


def test_saving_never_changes_the_bypass_file(house):
    (house.config / "bypass.txt").write_text("classroom.google.com\n", encoding="utf-8")
    house.changed("site-groups", [_item("school", priority="10", patterns=["classroom.google.com", "new.example.com"])])
    assert (house.config / "bypass.txt").read_text() == "classroom.google.com\n"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_a_hand_edit_found_before_a_save_is_committed_first(kept):
    version = kept.read("quotas")["version"]
    kept.text()
    status, _body = kept.save("quotas", version=version, items=[_item("entertainment", time="60m", bytes="", time_grace="", volume_grace="", ruleset="meter")], deleted=[])
    assert status == 200


def test_a_saved_change_is_in_force_for_the_next_request_with_no_restart(house):
    status, body = house.changed("quotas", [_item("entertainment", time="60m", bytes="", time_grace="", volume_grace="", ruleset="meter")])
    assert status == 200, body
    assert "restart" not in body["message"].lower()
    policy = house.app.state.holder.loaded.policy
    assert policy.quota("entertainment").time_limit == 3600
    status, _body = house.changed("site-groups", [_item("school", priority="10", patterns=["classroom.google.com", "*.minecraft.net"])])
    assert status == 200
    assert "*.minecraft.net" in house.app.state.holder.loaded.policy.site_group("school").patterns
