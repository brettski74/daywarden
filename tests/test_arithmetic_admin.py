"""S026: the arithmetic area of a task page, and saving its operation, settings, and numbers to the policy file."""

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_task_admin import HOUSE, House  # noqa: E402

from policy import check  # noqa: E402

FIRST = """\
        first:
          - { value: 7, weight: 1 }   # the seven times table
"""
SUMS = f"""\
  arithmetic:
    times:
      group: younger
      pass_cooldown: 1
      body:
        operation: addition
        max_timeout: 10s
        min_timeout: 4s
        correct_answers_required: 20
{FIRST}        operands:
          - {{ value: 1, weight: 5 }}
          - {{ from: 2, to: 12, weight: 10 }}
"""
TEXT = HOUSE + SUMS
# The page shows no weight, so the file's weights are not in the rows.
OPERANDS = [{"from": "1", "to": ""}, {"from": "2", "to": "12"}]


@pytest.fixture
def house(tmp_path, monkeypatch):
    return House(tmp_path, monkeypatch, text=TEXT)


def _body(house) -> dict:
    return yaml.safe_load(house.policy.read_text(encoding="utf-8"))["tasks"]["arithmetic"]["times"]["body"]


def test_the_page_shows_the_settings_the_operations_and_both_lists(house):
    page = house.page("arithmetic/times")["arithmetic"]
    assert page == {
        "settings": {
            "operation": "addition", "max_timeout": "10s", "min_timeout": "4s", "correct_answers_required": "20",
            "practice_fallback": "", "practice_required": "",
        },
        "operations": [
            {"name": "addition", "label": "Addition"},
            {"name": "subtraction", "label": "Subtraction"},
            {"name": "multiplication", "label": "Multiplication"},
            {"name": "division", "label": "Division"},
        ],
        "first": [{"from": "7", "to": ""}],
        "operands": OPERANDS,
        "problems": [],
    }


def test_choosing_an_operation_writes_it_and_keeps_both_lists_as_written_weights_and_all(house):
    status, body = house.save(
        "arithmetic/times",
        settings={"operation": "multiplication", "max_timeout": "10s"},
        lists={"first": [{"from": "7", "to": "7"}], "operands": OPERANDS},
    )
    assert status == 200, body
    assert house.policy.read_text(encoding="utf-8") == TEXT.replace("operation: addition", "operation: multiplication")
    assert house.task("arithmetic/times").document()["operation"] == "multiplication"


def test_a_changed_list_is_written_whole_and_an_empty_first_list_is_removed(house):
    status, body = house.save("arithmetic/times", lists={"first": [], "operands": [{"from": "0", "to": "10"}]})
    assert status == 200, body
    assert house.policy.read_text(encoding="utf-8").endswith(
        "        correct_answers_required: 20\n        operands:\n          - { from: 0, to: 10 }\n"
    )
    assert "first" not in _body(house)
    assert check.main(["--quiet"]) == 0
    assert house.page("arithmetic/times")["arithmetic"]["first"] == []
    status, body = house.save("arithmetic/times", lists={"first": []})
    assert (status, body["message"]) == (200, "Nothing has changed, so nothing was saved.")


def test_a_changed_list_is_written_without_weights_and_a_weight_sent_with_a_row_is_ignored(house):
    status, body = house.save(
        "arithmetic/times", lists={"operands": [{"from": "1", "to": "", "weight": "5"}, {"from": "2", "to": "13", "weight": "9"}]}
    )
    assert status == 200, body
    assert _body(house)["operands"] == [{"value": 1}, {"from": 2, "to": 13}]
    assert "weight" not in house.policy.read_text(encoding="utf-8").split("operands:")[1]
    assert house.page("arithmetic/times")["arithmetic"]["operands"] == [{"from": "1", "to": ""}, {"from": "2", "to": "13"}]
    assert check.main(["--quiet"]) == 0


def test_division_with_zero_in_the_first_numbers_list_is_refused_naming_the_field(house):
    status, body = house.save("arithmetic/times", settings={"operation": "division"}, lists={"first": [{"from": "0", "to": "3"}]})
    assert status == 400
    assert any("body.first: division cannot divide by 0" in problem for problem in body["errors"]), body
    assert house.policy.read_text(encoding="utf-8") == TEXT


def test_a_cleared_required_setting_is_refused_naming_it(house):
    status, body = house.save("arithmetic/times", settings={"min_timeout": ""})
    assert status == 400
    assert any("min_timeout: is required" in problem for problem in body["errors"]), body


def test_practice_fallback_is_written_changed_and_cleared_from_the_file(house):
    status, body = house.save("arithmetic/times", settings={"practice_fallback": "2"})
    assert status == 200, body
    assert _body(house)["practice_fallback"] == 2
    assert house.page("arithmetic/times")["arithmetic"]["settings"]["practice_fallback"] == "2"
    assert house.task("arithmetic/times").document()["practice_fallback"] == 2
    status, body = house.save("arithmetic/times", settings={"practice_fallback": "4"})
    assert status == 200, body
    assert _body(house)["practice_fallback"] == 4
    status, body = house.save("arithmetic/times", settings={"practice_fallback": ""})
    assert status == 200, body
    assert house.policy.read_text(encoding="utf-8") == TEXT
    assert "practice_fallback" not in _body(house)
    assert check.main(["--quiet"]) == 0


@pytest.mark.parametrize("text", ["0", "-1", "2.5", "three"])
def test_practice_fallback_that_is_not_a_whole_number_of_one_or_more_is_refused_naming_it(house, text):
    status, body = house.save("arithmetic/times", settings={"practice_fallback": text})
    assert status == 400
    assert any("practice_fallback: must be a whole number, 1 or more" in problem for problem in body["errors"]), body
    assert house.policy.read_text(encoding="utf-8") == TEXT
