"""S007.5: the rule sets page's data, saves, and deletes, through the portal's data endpoints."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_policy_pages import EXTRA, POLICY, Policy, _extra, _item  # noqa: E402
from test_task_admin import _git  # noqa: E402

PAGE = "rule-sets"
WRITTEN = POLICY.replace(
    """  meter:
""",
    """  nested:
    - condition: site_group
      groups: [school, games]
      when_true:
        action: evaluate
        rules:
          - condition: tasks_required
            required: 2
            when_false: { action: redirect, location: revision_task }
  meter:
""",
)


@pytest.fixture
def kept(tmp_path, monkeypatch):
    return Policy(tmp_path, monkeypatch, history=True, text=WRITTEN, before=_extra)


def _log(house) -> list[str]:
    return _git(house.config, "log", "--format=%s").splitlines()


def test_the_page_lists_each_rule_set_as_written_with_its_users_and_the_choices(kept):
    body = kept.read(PAGE)
    by_name = {item["name"]: item for item in body["items"]}
    assert list(by_name) == ["gate", "nested", "meter"]
    assert by_name["gate"]["rules"][0] == {"condition": "time_window", "window": "bedtime", "when_true": {"action": "deny", "message": "Bedtime."}}
    assert by_name["nested"]["rules"][0]["when_true"]["rules"][0]["required"] == 2
    assert by_name["gate"]["users"] == [{"kind": "entry", "name": "", "text": "the household's entry"}]
    assert by_name["meter"]["users"] == [{"kind": "quota", "name": "entertainment", "text": "quota entertainment"},
                                         {"kind": "quota", "name": "reading", "text": "quota reading"}]
    assert by_name["nested"]["users"] == []
    assert body["choices"]["site_group"] == ["school", "entertainment", "games", "spare", "default"]
    assert body["choices"]["client_group"] == ["younger", "older", "default"]
    assert body["choices"]["time_window"] == ["bedtime", "evening"]
    assert body["choices"]["quota"] == ["entertainment", "reading"]


def test_a_save_writes_only_the_rule_set_changed_and_commits_it_by_name(kept):
    rules = [{"condition": "time_window", "windows": ["bedtime", "evening"], "when_true": {"action": "deny", "message": "Not now."}}, {"condition": "always", "when_true": {"action": "allow"}}]
    status, body = kept.changed(PAGE, [_item("gate", rules=rules)])
    assert status == 200, body
    text = kept.text()
    assert 'when_true: { action: deny, message: Not now. }' in text
    assert "windows: [bedtime, evening]" in text
    assert "group: entertainment" in text
    assert _log(kept)[0].endswith("saved rule set gate")


def test_a_save_that_changes_nothing_writes_and_commits_nothing(kept):
    gate = next(item for item in kept.read(PAGE)["items"] if item["name"] == "gate")
    before = _log(kept)
    status, body = kept.changed(PAGE, [_item("gate", rules=gate["rules"])])
    assert status == 200
    assert "nothing was saved" in body["message"]
    assert _log(kept) == before


def test_a_rule_set_made_from_an_inline_list_is_one_commit_with_both_names(kept):
    inline = [{"condition": "tasks_required", "required": 2, "when_false": {"action": "redirect", "location": "revision_task"}}]
    nested = [{"condition": "site_group", "groups": ["school", "games"], "when_true": {"action": "evaluate", "ruleset": "nested_inner"}}]
    status, body = kept.changed(PAGE, [_item("nested", rules=nested), _item("nested_inner", new=True, rules=inline)])
    assert status == 200, body
    assert _log(kept)[0].endswith("saved rule set nested, created rule set nested_inner")
    assert "nested_inner:" in kept.text()
    assert len(_log(kept)) == 2


def test_a_new_rule_set_is_empty_committed_and_a_name_in_use_is_refused(kept):
    status, body = kept.changed(PAGE, [_item("fresh", new=True, rules=[])])
    assert status == 200, body
    assert _log(kept)[0].endswith("created rule set fresh")
    assert next(item for item in kept.read(PAGE)["items"] if item["name"] == "fresh")["rules"] == []
    status, body = kept.changed(PAGE, [_item("gate", new=True, rules=[])])
    assert status == 400
    assert "already exists" in body["error"]


def test_a_cycle_and_a_deny_with_no_message_are_refused_with_the_checks_reasons(kept):
    cycle = [{"condition": "always", "when_true": {"action": "evaluate", "ruleset": "nested"}}]
    status, body = kept.changed(PAGE, [_item("nested", rules=cycle)])
    assert status == 400
    assert any("cycle" in reason for reason in [body["error"], *body.get("errors", [])])
    silent = [{"condition": "always", "when_true": {"action": "deny", "message": ""}}]
    status, body = kept.changed(PAGE, [_item("nested", rules=silent)])
    assert status == 400
    assert body.get("errors") or body["error"]
    assert "nested_inner" not in kept.text()


def test_a_rule_set_in_use_is_not_deleted_and_the_refusal_names_each_user(kept):
    status, body = kept.changed(PAGE, deleted=["meter"])
    assert status == 400
    assert body["errors"] == ["Rule set meter is used by quota entertainment.", "Rule set meter is used by quota reading."]
    status, body = kept.changed(PAGE, deleted=["gate"])
    assert status == 400
    assert "entry" in " ".join(body["errors"])


def test_a_rule_set_nothing_uses_is_deleted_at_once_as_its_own_commit(kept):
    status, body = kept.changed(PAGE, deleted=["nested"])
    assert status == 200, body
    assert "nested:" not in kept.text()
    assert _log(kept)[0].endswith("deleted rule set nested")


def test_the_extra_file_is_unchanged_by_a_rule_set_save(kept):
    kept.changed(PAGE, [_item("fresh", new=True, rules=[])])
    assert kept.text("extra.yaml") == EXTRA
