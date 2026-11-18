"""S036.1: reading mcp.yaml, and writing a page's save back into it without losing what was written by hand."""

import sys
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy.mcp_settings import DEFAULTS, FIRST_TIME, SettingsError, from_data, settings_text  # noqa: E402

PATH = Path("mcp.yaml")


def _round_trip(old: str, change) -> tuple[str, object]:
    before = from_data(yaml.safe_load(old))
    after = change(before)
    text = settings_text(old, PATH, before, after)
    assert from_data(yaml.safe_load(text)) == after
    return text, after


def test_left_out_fields_take_their_defaults():
    assert from_data({}) == DEFAULTS
    assert from_data({"permissions": {"usage": ["read"]}}).permissions == {"usage": frozenset({"read"})}


def test_a_changed_class_keeps_its_comment_and_a_block_list_is_rewritten():
    old = "enabled: true  # mine\npermissions:\n  tasks: [read]  # only read\n  attempts:\n    - read\n"
    text, _after = _round_trip(
        old, lambda before: replace(before, permissions={"tasks": frozenset({"read", "update"}), "attempts": frozenset()})
    )
    assert "enabled: true  # mine" in text
    assert "tasks: [read, update]  # only read" in text
    assert "attempts" not in text


def test_a_file_with_no_permissions_has_the_block_added_after_the_rest():
    text, _after = _round_trip("# hand written\nenabled: true\n", lambda _before: FIRST_TIME)
    assert text.startswith("# hand written\nenabled: true\npermissions:\n")


def test_no_permissions_at_all_is_written_as_an_empty_mapping_not_left_out():
    text, after = _round_trip("permissions:\n  tasks: [read]\n", lambda before: replace(before, permissions={}))
    assert "permissions: {}" in text
    assert not any(after.permissions.values())


def test_page_values_are_checked_as_the_file_is():
    with pytest.raises(SettingsError) as refused:
        from_data({"enabled": "yes", "activity_days": 0, "colour": "red", "permissions": {"household": ["delete"]}})
    assert len(refused.value.problems) == 4
