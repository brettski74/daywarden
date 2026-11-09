"""S023.2: rewriting one task in a policy file and leaving the rest of the file as it was."""

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy.task_edit import EditError, read_task, rewrite_task, scalar  # noqa: E402

SOURCE = Path("/etc/daywarden/policy.yaml")
FILE = """\
rule_sets:
  gate:
    - condition: always
      when_true: { action: allow }
tasks:
  first:
    type: worksheet
    group: younger
    pass_cooldown: 1 # a comment
    body:
      timeout: 30s

  words:
    type: spelling
    groups: [younger, older]
    body: {"timeout": "30s", "revision_required": 10}
  short: { type: worksheet, group: younger }
"""


def test_reading_a_task_gives_each_field_as_written():
    written = read_task(FILE, SOURCE, "first")
    assert written.fields == {"type": "worksheet", "pass_cooldown": "1"}
    assert (written.groups, written.group_key) == (("younger",), "group")
    assert written.body == {"timeout": "30s"}
    assert read_task(FILE, SOURCE, "words").groups == ("younger", "older")


def test_a_changed_value_keeps_its_comment_and_every_other_line():
    changed = rewrite_task(FILE, SOURCE, "first", {"pass_cooldown": "3", "body": {"timeout": "20s"}})
    assert changed == FILE.replace("pass_cooldown: 1 # a comment", "pass_cooldown: 3 # a comment").replace(
        "      timeout: 30s\n", "      timeout: 20s\n"
    )


def test_new_fields_go_inside_their_own_mapping_and_a_cleared_one_loses_its_line():
    changed = rewrite_task(
        FILE, SOURCE, "first", {"pass_cooldown": None, "max_skips": "2", "body": {"word_pause": "500ms"}}
    )
    assert changed == FILE.replace("    pass_cooldown: 1 # a comment\n", "").replace(
        "      timeout: 30s\n", "      timeout: 30s\n      word_pause: 500ms\n    max_skips: 2\n"
    )


def test_a_body_whose_last_field_is_cleared_is_removed():
    changed = rewrite_task(FILE, SOURCE, "first", {"body": {"timeout": None}})
    assert "    body:\n" not in changed.split("words:")[0]
    assert yaml.safe_load(changed)["tasks"]["first"] == {"type": "worksheet", "group": "younger", "pass_cooldown": 1}


def test_a_flow_body_is_written_again_as_flow_with_its_untouched_entries_as_they_were():
    changed = rewrite_task(FILE, SOURCE, "words", {"body": {"timeout": "20s", "current_required": "3"}})
    assert '    body: { timeout: 20s, "revision_required": 10, current_required: 3 }\n' in changed
    assert changed.replace('    body: { timeout: 20s, "revision_required": 10, current_required: 3 }\n', "") == FILE.replace(
        '    body: {"timeout": "30s", "revision_required": 10}\n', ""
    )


def test_a_flow_task_and_a_new_body_in_a_block_task():
    changed = rewrite_task(FILE, SOURCE, "short", {"max_passes": "4", "body": {"timeout": "10s"}})
    assert "  short: { type: worksheet, group: younger, max_passes: 4, body: { timeout: 10s } }\n" in changed
    changed = rewrite_task(changed, SOURCE, "words", {"group": None, "groups": "[older]"})
    assert yaml.safe_load(changed)["tasks"]["words"]["groups"] == ["older"]
    changed = rewrite_task(FILE.replace("    body:\n      timeout: 30s\n", ""), SOURCE, "first", {"body": {"timeout": "5s"}})
    assert yaml.safe_load(changed)["tasks"]["first"]["body"] == {"timeout": "5s"}


def test_a_typed_value_cannot_change_the_shape_of_the_file():
    for typed in ("3\nentry: other", "{a: 1}", "x # y", "[1, 2]", "a: b"):
        changed = rewrite_task(FILE, SOURCE, "first", {"pass_cooldown": scalar(typed)})
        assert yaml.safe_load(changed)["tasks"]["first"]["pass_cooldown"] == typed
    assert scalar("2026-11-30") == "2026-11-30"
    assert scalar("-1") == "-1"
    assert scalar("yes", name=True) == '"yes"'


def test_an_unknown_task_cannot_be_edited():
    with pytest.raises(EditError, match="does not define the task nope"):
        rewrite_task(FILE, SOURCE, "nope", {"max_skips": "1"})
