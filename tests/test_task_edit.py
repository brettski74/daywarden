"""S023.2: rewriting one task in a policy file and leaving the rest of the file as it was."""

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy.task_edit import EditError, ListEdit, ListItem, read_task, rewrite_task, scalar  # noqa: E402
from policy.tasks import TaskKey  # noqa: E402

SOURCE = Path("/etc/daywarden/policy.yaml")
FILE = """\
rule_sets:
  gate:
    - condition: always
      when_true: { action: allow }
tasks:
  worksheet:
    first:
      group: younger
      pass_cooldown: 1 # a comment
      body:
        timeout: 30s

    short: { group: younger }
  spelling:
    words:
      groups: [younger, older]
      body: {"timeout": "30s", "revision_required": 10}
"""
FIRST = TaskKey("worksheet", "first")
SHORT = TaskKey("worksheet", "short")
WORDS = TaskKey("spelling", "words")


def _tasks(text: str) -> dict:
    return yaml.safe_load(text)["tasks"]


def test_reading_a_task_gives_each_field_as_written():
    written = read_task(FILE, SOURCE, FIRST)
    assert written.fields == {"pass_cooldown": "1"}
    assert (written.groups, written.group_key) == (("younger",), "group")
    assert written.body == {"timeout": "30s"}
    assert read_task(FILE, SOURCE, WORDS).groups == ("younger", "older")


def test_a_changed_value_keeps_its_comment_and_every_other_line():
    changed = rewrite_task(FILE, SOURCE, FIRST, {"pass_cooldown": "3", "body": {"timeout": "20s"}})
    assert changed == FILE.replace("pass_cooldown: 1 # a comment", "pass_cooldown: 3 # a comment").replace(
        "        timeout: 30s\n", "        timeout: 20s\n"
    )


def test_new_fields_go_inside_their_own_mapping_and_a_cleared_one_loses_its_line():
    changed = rewrite_task(
        FILE, SOURCE, FIRST, {"pass_cooldown": None, "max_skips": "2", "body": {"word_pause": "500ms"}}
    )
    assert changed == FILE.replace("      pass_cooldown: 1 # a comment\n", "").replace(
        "        timeout: 30s\n", "        timeout: 30s\n        word_pause: 500ms\n      max_skips: 2\n"
    )


def test_a_body_whose_last_field_is_cleared_is_removed():
    changed = rewrite_task(FILE, SOURCE, FIRST, {"body": {"timeout": None}})
    assert "      body:\n" not in changed.split("words:")[0]
    assert _tasks(changed)["worksheet"]["first"] == {"group": "younger", "pass_cooldown": 1}


def test_a_flow_body_is_written_again_as_flow_with_its_untouched_entries_as_they_were():
    changed = rewrite_task(FILE, SOURCE, WORDS, {"body": {"timeout": "20s", "current_required": "3"}})
    line = '      body: { timeout: 20s, "revision_required": 10, current_required: 3 }\n'
    assert line in changed
    assert changed.replace(line, "") == FILE.replace('      body: {"timeout": "30s", "revision_required": 10}\n', "")


def test_a_flow_task_and_a_new_body_in_a_block_task():
    changed = rewrite_task(FILE, SOURCE, SHORT, {"max_passes": "4", "body": {"timeout": "10s"}})
    assert "    short: { group: younger, max_passes: 4, body: { timeout: 10s } }\n" in changed
    changed = rewrite_task(changed, SOURCE, WORDS, {"group": None, "groups": "[older]"})
    assert _tasks(changed)["spelling"]["words"]["groups"] == ["older"]
    changed = rewrite_task(FILE.replace("      body:\n        timeout: 30s\n", ""), SOURCE, FIRST, {"body": {"timeout": "5s"}})
    assert _tasks(changed)["worksheet"]["first"]["body"] == {"timeout": "5s"}


def test_a_typed_value_cannot_change_the_shape_of_the_file():
    for typed in ("3\nentry: other", "{a: 1}", "x # y", "[1, 2]", "a: b"):
        changed = rewrite_task(FILE, SOURCE, FIRST, {"pass_cooldown": scalar(typed)})
        assert _tasks(changed)["worksheet"]["first"]["pass_cooldown"] == typed
    assert scalar("2026-11-30") == "2026-11-30"
    assert scalar("-1") == "-1"
    assert scalar("yes", name=True) == '"yes"'


def test_an_unknown_task_cannot_be_edited():
    with pytest.raises(EditError, match="does not define the task worksheet/nope"):
        rewrite_task(FILE, SOURCE, TaskKey("worksheet", "nope"), {"max_skips": "1"})
    with pytest.raises(EditError, match="does not define the task spelling/first"):
        rewrite_task(FILE, SOURCE, TaskKey("spelling", "first"), {"max_skips": "1"})


def test_tasks_that_share_a_name_are_edited_by_type():
    shared = FILE + "  arithmetic:\n    words:\n      group: younger\n      pass_cooldown: 2\n"
    changed = rewrite_task(shared, SOURCE, TaskKey("arithmetic", "words"), {"pass_cooldown": "5"})
    assert changed == shared.replace("      pass_cooldown: 2\n", "      pass_cooldown: 5\n")
    assert read_task(shared, SOURCE, WORDS).groups == ("younger", "older")
    assert read_task(shared, SOURCE, TaskKey("arithmetic", "words")).fields == {"pass_cooldown": "2"}


# S007.3: a list in the body, item by item

LISTED = """\
tasks:
  parts_of_speech:
    words:
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
LISTED_WORDS = TaskKey("parts_of_speech", "words")
ONE = {"sentence": "One.", "parts": {"noun": ["One"]}}


def _sentences(*items: ListItem) -> dict:
    return {"body": {"sentences": ListEdit(items)}}


def test_unchanged_items_keep_their_text_and_a_changed_one_is_written_again_in_its_place():
    changed = rewrite_task(
        LISTED,
        SOURCE,
        LISTED_WORDS,
        _sentences(
            ListItem(0, ONE, False),
            ListItem(1, {"sentence": "Two: yes.", "parts": {"noun": ["Two", "yes"], "verb": []}, "timeout": "1m"}, True),
            ListItem(2, {}, False),
        ),
    )
    assert changed == LISTED.replace(
        "          -\n            sentence: Two.\n            parts:\n              noun: [Two]\n",
        '          - sentence: "Two: yes."\n            parts:\n              noun: [Two, "yes"]\n              verb: []\n'
        "            timeout: 1m\n",
    )
    assert _tasks(changed)["parts_of_speech"]["words"]["body"]["sentences"][1] == {
        "sentence": "Two: yes.",
        "parts": {"noun": ["Two", "yes"], "verb": []},
        "timeout": "1m",
    }


def test_a_removed_item_loses_its_lines_and_a_new_one_goes_after_the_last():
    changed = rewrite_task(
        LISTED,
        SOURCE,
        LISTED_WORDS,
        _sentences(ListItem(1, {}, False), ListItem(None, {"sentence": "Dry it dry.", "parts": {"verb": ["Dry"], "adverb": ["dry[2]"]}}, True)),
    )
    assert changed == LISTED.replace('          - sentence: "One."   # kept as written\n            parts: { noun: [One] }\n', "").replace(
        "          - sentence: Three.\n            parts:\n              noun:\n                - Three\n",
        '          - sentence: Dry it dry.\n            parts:\n              verb: [Dry]\n              adverb: ["dry[2]"]\n',
    )


def test_a_list_cannot_be_reordered():
    with pytest.raises(EditError, match="keep their order"):
        rewrite_task(LISTED, SOURCE, LISTED_WORDS, _sentences(ListItem(1, {}, False), ListItem(0, ONE, False)))


def test_a_flow_list_and_a_flow_body_are_written_again_as_block_lists():
    flow_list = LISTED.split("        sentences:")[0] + '        sentences: [{"sentence": "One.", "parts": {"noun": ["One"]}}]\n'
    changed = rewrite_task(flow_list, SOURCE, LISTED_WORDS, _sentences(ListItem(0, ONE, False), ListItem(None, ONE, True)))
    assert changed.endswith("        sentences:\n" + "          - sentence: One.\n            parts:\n              noun: [One]\n" * 2)
    flow_body = LISTED.split("      body:")[0] + '      body: {"timeout": "45s", "sentences": [{"sentence": "One.", "parts": {"noun": ["One"]}}]}\n'
    changed = rewrite_task(flow_body, SOURCE, LISTED_WORDS, {"body": {"timeout": None, "sentences": ListEdit((ListItem(None, ONE, True),))}})
    assert changed.endswith("      body:\n        sentences:\n          - sentence: One.\n            parts:\n              noun: [One]\n")
    kept = rewrite_task(flow_body, SOURCE, LISTED_WORDS, {"body": {"sentences": ListEdit((ListItem(0, ONE, False),))}})
    assert _tasks(kept)["parts_of_speech"]["words"]["body"] == {"timeout": "45s", "sentences": [ONE]}


def test_a_flow_task_cannot_take_a_list_edit():
    flow_task = "tasks:\n  parts_of_speech:\n    words: { group: younger, body: { sentences: [] } }\n"
    with pytest.raises(EditError, match="edit it by hand"):
        rewrite_task(flow_task, SOURCE, LISTED_WORDS, _sentences(ListItem(None, ONE, True)))


COUNTED = """\
tasks:
  skip_counting:
    counting:
      body:
        difference:
          # Twos and fives.
          - { value: 2, weight: 1 }   # twos
          - value: 5
            weight: 2
        timeout: 2m
"""
COUNTING = TaskKey("skip_counting", "counting")


def _flow(*entries: dict) -> dict:
    return {"body": {"difference": ListEdit(tuple(ListItem(None, entry, True) for entry in entries), flow=True)}}


def test_a_flow_list_edit_writes_the_whole_list_again_one_flow_mapping_per_line():
    changed = rewrite_task(COUNTED, SOURCE, COUNTING, _flow({"from": 3, "to": 9, "weight": 10, "maximum_value": 99}, {"value": -2, "weight": 1}))
    assert changed == (
        "tasks:\n  skip_counting:\n    counting:\n      body:\n        difference:\n"
        "          - { from: 3, to: 9, weight: 10, maximum_value: 99 }\n"
        "          - { value: -2, weight: 1 }\n"
        "        timeout: 2m\n"
    )


def test_a_flow_list_edit_adds_a_missing_list_and_writes_a_flow_body_as_a_block():
    missing = COUNTED.split("        difference:")[0] + "        timeout: 2m\n"
    assert rewrite_task(missing, SOURCE, COUNTING, _flow({"value": 2, "weight": 1})).endswith(
        "        timeout: 2m\n        difference:\n          - { value: 2, weight: 1 }\n"
    )
    flow_body = COUNTED.split("      body:")[0] + '      body: {"timeout": "2m", "difference": [{"value": 5, "weight": 1}]}\n'
    assert rewrite_task(flow_body, SOURCE, COUNTING, _flow({"value": 2, "weight": 1})).endswith(
        '      body:\n        "timeout": "2m"\n        difference:\n          - { value: 2, weight: 1 }\n'
    )


def test_reading_a_task_gives_the_body_as_the_loader_reads_it():
    assert read_task(LISTED, SOURCE, LISTED_WORDS).body_data["sentences"][2] == {"sentence": "Three.", "parts": {"noun": ["Three"]}}
