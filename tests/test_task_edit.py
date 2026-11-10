"""S023.2: rewriting one task in a policy file and leaving the rest of the file as it was."""

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy.task_edit import EditError, ListEdit, ListItem, read_task, rewrite_task, scalar  # noqa: E402

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


# S007.3: a list in the body, item by item

LISTED = """\
tasks:
  words:
    type: parts_of_speech
    group: younger
    body:
      sentences:
        # The first one.
        - sentence: "One."   # kept as written
          parts: { noun: [One] }
        -
          sentence: Two.
          parts:
            noun: [Two]
        - sentence: Three.
          parts:
            noun:
              - Three
      timeout: 30s
"""
ONE = {"sentence": "One.", "parts": {"noun": ["One"]}}


def _sentences(*items: ListItem) -> dict:
    return {"body": {"sentences": ListEdit(items)}}


def test_unchanged_items_keep_their_text_and_a_changed_one_is_written_again_in_its_place():
    changed = rewrite_task(
        LISTED,
        SOURCE,
        "words",
        _sentences(
            ListItem(0, ONE, False),
            ListItem(1, {"sentence": "Two: yes.", "parts": {"noun": ["Two", "yes"], "verb": []}, "timeout": "1m"}, True),
            ListItem(2, {}, False),
        ),
    )
    assert changed == LISTED.replace(
        "        -\n          sentence: Two.\n          parts:\n            noun: [Two]\n",
        '        - sentence: "Two: yes."\n          parts:\n            noun: [Two, "yes"]\n            verb: []\n          timeout: 1m\n',
    )
    assert yaml.safe_load(changed)["tasks"]["words"]["body"]["sentences"][1] == {
        "sentence": "Two: yes.",
        "parts": {"noun": ["Two", "yes"], "verb": []},
        "timeout": "1m",
    }


def test_a_removed_item_loses_its_lines_and_a_new_one_goes_after_the_last():
    changed = rewrite_task(
        LISTED,
        SOURCE,
        "words",
        _sentences(ListItem(1, {}, False), ListItem(None, {"sentence": "Dry it dry.", "parts": {"verb": ["Dry"], "adverb": ["dry[2]"]}}, True)),
    )
    assert changed == LISTED.replace('        - sentence: "One."   # kept as written\n          parts: { noun: [One] }\n', "").replace(
        "        - sentence: Three.\n          parts:\n            noun:\n              - Three\n",
        '        - sentence: Dry it dry.\n          parts:\n            verb: [Dry]\n            adverb: ["dry[2]"]\n',
    )


def test_a_list_cannot_be_reordered():
    with pytest.raises(EditError, match="keep their order"):
        rewrite_task(LISTED, SOURCE, "words", _sentences(ListItem(1, {}, False), ListItem(0, ONE, False)))


def test_a_flow_list_and_a_flow_body_are_written_again_as_block_lists():
    flow_list = LISTED.split("      sentences:")[0] + '      sentences: [{"sentence": "One.", "parts": {"noun": ["One"]}}]\n'
    changed = rewrite_task(flow_list, SOURCE, "words", _sentences(ListItem(0, ONE, False), ListItem(None, ONE, True)))
    assert changed.endswith("      sentences:\n" + "        - sentence: One.\n          parts:\n            noun: [One]\n" * 2)
    flow_body = LISTED.split("    body:")[0] + '    body: {"timeout": "45s", "sentences": [{"sentence": "One.", "parts": {"noun": ["One"]}}]}\n'
    changed = rewrite_task(flow_body, SOURCE, "words", {"body": {"timeout": None, "sentences": ListEdit((ListItem(None, ONE, True),))}})
    assert changed.endswith("    body:\n      sentences:\n        - sentence: One.\n          parts:\n            noun: [One]\n")
    kept = rewrite_task(flow_body, SOURCE, "words", {"body": {"sentences": ListEdit((ListItem(0, ONE, False),))}})
    assert yaml.safe_load(kept)["tasks"]["words"]["body"] == {"timeout": "45s", "sentences": [ONE]}


def test_a_flow_task_cannot_take_a_list_edit():
    flow_task = "tasks:\n  words: { type: parts_of_speech, group: younger, body: { sentences: [] } }\n"
    with pytest.raises(EditError, match="edit it by hand"):
        rewrite_task(flow_task, SOURCE, "words", _sentences(ListItem(None, ONE, True)))


def test_reading_a_task_gives_the_body_as_the_loader_reads_it():
    assert read_task(LISTED, SOURCE, "words").body_data["sentences"][2] == {"sentence": "Three.", "parts": {"noun": ["Three"]}}
