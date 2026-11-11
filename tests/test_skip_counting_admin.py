"""S025: the skip counting area of a task page, and saving its settings and differences to the policy file."""

import random
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_task_admin import HOUSE, House, _git  # noqa: E402

from policy import check  # noqa: E402
from policy.skip_counting import Session  # noqa: E402
from policy.tasks import TaskKey  # noqa: E402

ZONE = ZoneInfo("America/Toronto")
LIST = """\
        difference:
          # Up by twos, and the odd ones.
          - { value: 2, weight: 3, maximum_value: 99 }
          - { from: 3, to: 9, weight: 1 }   # odd ones
          - { value: -5, weight: 2, minimum_value: -50, maximum_value: 50, multiples_only: true }
"""
COUNTING = f"""\
  skip_counting:
    counting:
      group: younger
      pass_cooldown: 1
      body:
        sequence_length: 6
        consecutive: false
{LIST}        timeout: 2m
    defaulted:
      group: younger
      pass_cooldown: 1
      body:
        timeout: 2m
"""
TEXT = HOUSE + COUNTING
ROWS = [
    {"from": "2", "to": "", "weight": "3", "minimum_value": "", "maximum_value": "99", "multiples_only": None},
    {"from": "3", "to": "9", "weight": "1", "minimum_value": "", "maximum_value": "", "multiples_only": None},
    {"from": "-5", "to": "", "weight": "2", "minimum_value": "-50", "maximum_value": "50", "multiples_only": True},
]


@pytest.fixture
def house(tmp_path, monkeypatch):
    return House(tmp_path, monkeypatch, text=TEXT)


def _body(house, name: str = "counting") -> dict:
    return yaml.safe_load(house.policy.read_text(encoding="utf-8"))["tasks"]["skip_counting"][name]["body"]


def _row(start: str, end: str = "", weight: str = "", **bounds) -> dict:
    return {"from": start, "to": end, "weight": weight, "minimum_value": "", "maximum_value": "", "multiples_only": None, **bounds}


def test_the_page_shows_the_settings_the_flags_in_force_and_each_difference_as_a_row(house):
    page = house.page("skip_counting/counting")["skip_counting"]
    assert page["settings"] == {
        "sequence_length": "6",
        "completed": "",
        "minimum_value": "",
        "maximum_value": "",
        "consecutive": "false",
        "multiples_only": "",
        "timeout": "2m",
        "correct_answers_required": "",
        "minimum_questions": "",
        "maximum_questions": "",
    }
    assert page["flags"] == {"consecutive": False, "multiples_only": False}
    assert page["difference"] == ROWS
    assert page["problems"] == []


def test_a_task_with_no_difference_list_gets_the_default_list_with_each_cap(house):
    page = house.page("skip_counting/defaulted")["skip_counting"]
    assert page["difference"] is None
    assert page["flags"] == {"consecutive": True, "multiples_only": False}
    shown = [(row["from"], row["maximum_value"], row["multiples_only"]) for row in page["default"]]
    assert shown == [
        ("2", "99", None),
        ("5", "199", None),
        ("10", "499", None),
        ("25", "", True),
        ("100", "", None),
        ("-2", "99", None),
        ("-5", "199", None),
        ("-10", "499", None),
        ("-25", "", True),
        ("-100", "", None),
    ]
    assert {row["weight"] for row in page["default"]} == {"1"}


def test_an_unchanged_list_keeps_its_text_exactly(house):
    rows = [dict(row) for row in ROWS]
    rows[0]["weight"] = " 3 "
    status, body = house.save("skip_counting/counting", lists={"difference": rows}, settings={"timeout": "2m"})
    assert (status, body["message"]) == (200, "Nothing has changed, so nothing was saved."), body
    assert house.policy.read_text(encoding="utf-8") == TEXT


def test_a_changed_list_is_written_whole_with_one_flow_mapping_per_row_in_table_order(house):
    rows = [ROWS[2], _row("3", "9", "10", maximum_value="99"), _row("11", "11"), _row("12", "15", "2", multiples_only=False)]
    status, body = house.save("skip_counting/counting", lists={"difference": rows})
    assert status == 200, body
    assert house.policy.read_text(encoding="utf-8") == TEXT.replace(
        LIST,
        "        difference:\n"
        "          - { value: -5, weight: 2, minimum_value: -50, maximum_value: 50, multiples_only: true }\n"
        "          - { from: 3, to: 9, weight: 10, maximum_value: 99 }\n"
        "          - { value: 11, weight: 1 }\n"
        "          - { from: 12, to: 15, weight: 2, multiples_only: false }\n",
    )
    assert check.main(["--quiet"]) == 0
    shown = house.page("skip_counting/counting")["skip_counting"]["difference"]
    assert shown[2] == _row("11", weight="1")


def test_a_list_written_over_a_default_list_goes_in_the_body_and_the_default_takes_it_away_again(house):
    status, body = house.save("skip_counting/defaulted", lists={"difference": [_row("2"), _row("5", "", "2")]})
    assert status == 200, body
    assert _body(house, "defaulted") == {"timeout": "2m", "difference": [{"value": 2, "weight": 1}, {"value": 5, "weight": 2}]}
    assert house.policy.read_text(encoding="utf-8").endswith(
        "        timeout: 2m\n        difference:\n          - { value: 2, weight: 1 }\n          - { value: 5, weight: 2 }\n"
    )
    status, body = house.save("skip_counting/defaulted", lists={"difference": "default"})
    assert status == 200, body
    assert house.policy.read_text(encoding="utf-8") == TEXT


def test_going_back_to_the_default_list_removes_the_field_and_is_nothing_when_it_is_already_default(house):
    status, body = house.save("skip_counting/defaulted", lists={"difference": "default"})
    assert (status, body["message"]) == (200, "Nothing has changed, so nothing was saved.")
    status, body = house.save("skip_counting/counting", lists={"difference": "default"})
    assert status == 200, body
    assert house.policy.read_text(encoding="utf-8") == TEXT.replace(LIST, "")
    assert house.page("skip_counting/counting")["skip_counting"]["difference"] is None


def test_settings_are_written_in_the_body_and_cleared_ones_lose_their_line(house):
    status, body = house.save(
        "skip_counting/counting",
        settings={"sequence_length": "", "consecutive": "true", "multiples_only": "true", "maximum_questions": "12"},
    )
    assert status == 200, body
    written = _body(house)
    assert "sequence_length" not in written
    assert (written["consecutive"], written["multiples_only"], written["maximum_questions"]) == (True, True, 12)
    assert written["difference"][0] == {"value": 2, "weight": 3, "maximum_value": 99}
    assert LIST in house.policy.read_text(encoding="utf-8")


def test_a_check_that_needs_the_whole_task_refuses_the_save_naming_the_entry_by_its_place(house):
    rows = [_row("2"), _row("5"), _row("7"), _row("10"), _row("100")]
    status, body = house.save("skip_counting/counting", lists={"difference": rows}, settings={"sequence_length": "8", "maximum_value": "702"})
    assert status == 400
    assert any("difference entry 5" in problem and "counting by 100" in problem for problem in body["errors"]), body
    assert house.policy.read_text(encoding="utf-8") == TEXT


def test_a_setting_outside_its_range_is_refused_naming_it(house):
    status, body = house.save("skip_counting/counting", settings={"sequence_length": "13"})
    assert status == 400
    assert any("sequence_length" in problem for problem in body["errors"]), body


@pytest.mark.parametrize(
    ("lists", "says"),
    [
        ({"difference": [_row("two")]}, "difference row 1: from must be a whole number"),
        ({"difference": [_row("")]}, "difference row 1: from is needed"),
        ({"difference": [{**_row("2"), "step": "1"}]}, "step is not a column"),
        ({"difference": [{**_row("2"), "multiples_only": "yes"}]}, "multiples_only"),
        ({"difference": "nothing"}, "difference must be a list of rows"),
        ({"operands": []}, "operands cannot be changed"),
    ],
)
def test_a_request_the_page_would_never_send_is_refused(house, lists, says):
    status, body = house.save("skip_counting/counting", lists=lists)
    assert status == 400
    assert says in body["error"]
    assert house.policy.read_text(encoding="utf-8") == TEXT


def test_the_next_run_uses_the_saved_list_and_a_run_in_progress_keeps_its_own(house):
    started = datetime(2026, 11, 9, 16, 0, tzinfo=ZONE)
    running = Session({}, house.task("skip_counting/counting").document())
    running.issue(started, random.Random(1))
    assert house.save("skip_counting/counting", lists={"difference": [_row("10"), _row("-10")]})[0] == 200
    later = Session(running.detail, house.task("skip_counting/counting").document())
    assert later.settings.differences.count == 9
    fresh = Session({}, house.task("skip_counting/counting").document())
    question = fresh.issue(started, random.Random(1))
    assert question["difference"] in (10, -10)
    assert fresh.settings.differences.count == 2


def test_a_difference_save_is_committed_as_the_parent(tmp_path, monkeypatch):
    kept = House(tmp_path, monkeypatch, history=True, text=TEXT)
    status, body = kept.save("skip_counting/counting", lists={"difference": ROWS[:1]})
    assert status == 200, body
    assert kept.log()[0].endswith(" ada: saved task skip_counting/counting")
    assert _git(kept.config, "status", "--porcelain") == ""
