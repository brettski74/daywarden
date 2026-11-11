"""S016: the policy check lists every error it can find, and python -m policy.check reports them."""

import json
import re
from pathlib import Path

import pytest

from conftest import write_alphabet, write_wav
from policy import check
from policy.hierarchy import ConfigError, load

GOOD = """\
entry: household
client_groups:
  younger:
    addresses: ["192.0.2.40"]
site_groups:
  school:
    priority: 10
    patterns: ["school.example"]
rule_sets:
  household:
    - condition: site_group
      group: school
      when_true: { action: allow }
"""

# One mistake in each of seven items.
SEVEN = """\
entry: household
timezon: Australia/Sydney
client_groups:
  younger:
    addresses: ["192.0.2.40", "not an address"]
site_groups:
  school:
    priority: 10
    patterns: ["school.example"]
  games:
    priority: 10
    patterns: ["games.example"]
time_windows:
  evening:
    periods:
      - start: "25:00"
        end: "20:00"
quotas:
  games:
    time: 1h
    time_grace: -5m
    ruleset: household
tasks:
  arithmetic:
    sums:
      group: younger
      pass_cooldown: 0
      body:
        operation: addition
        max_timeout: 10s
        min_timeout: 5s
        correct_answers_required: 0
        operands: [{value: 1, weight: 1}]
rule_sets:
  household:
    - condition: time_window
      window: evening
      when_true: { action: evaluate, ruleset: missing }
"""
SEVEN_ERRORS = [
    ":2:1: unknown setting timezon",
    ":5:31: 'not an address' is not an IP address or a host name",
    ":11:5: site groups 'school' and 'games' both have priority 10",
    ":16:9: period 1: start must be a quoted time",
    ":21:17: time_grace cannot be negative",
    ":32:9: task 'arithmetic/sums': body.correct_answers_required: must be a whole number, 1 or more",
    ":36:7: rule 1: when_true: unknown rule set 'missing'",
]


def _write(directory: Path, relative: str, text: str) -> Path:
    path = directory / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _problems(path: Path) -> tuple[str, ...]:
    with pytest.raises(ConfigError) as raised:
        load(path)
    return raised.value.problems


def _assert_listed(problems, expected: list[str]) -> None:
    assert len(problems) == len(expected), "\n".join(problems)
    for problem, fragment in zip(problems, expected, strict=True):
        assert fragment in problem, problem


def test_one_check_lists_a_mistake_in_each_of_seven_items(tmp_path):
    path = _write(tmp_path, "policy.yaml", SEVEN)
    problems = _problems(path)
    _assert_listed(problems, SEVEN_ERRORS)
    assert all(problem.startswith(f"{path}:") for problem in problems)


def test_two_mistakes_in_one_item_are_both_listed(tmp_path):
    text = (
        GOOD
        + """\
time_windows:
  evening:
    periods:
      - start: "7am"
        end: "20:00"
        days: funday
tasks:
  arithmetic:
    sums:
      group: younger
      pass_cooldown: 0
      body:
        operation: addition
        max_timeout: 10
        min_timeout: 5s
        correct_answers_required: many
        operands: [{value: 1, weight: 1}]
  skip_counting:
    words:
      group: younger
      pass_cooldown: 0
      body:
        timeout: 3
        maximum_questions: none
"""
    )
    problems = _problems(_write(tmp_path, "policy.yaml", text))
    _assert_listed(
        problems,
        [
            "period 1: start must be a quoted time",
            "period 1: days: 'funday' is not a weekday",
            "body.max_timeout: must be a duration",
            "body.correct_answers_required: must be a whole number",
            "body.timeout: must be a duration",
            "body.maximum_questions:",
        ],
    )


def test_a_parts_of_speech_task_lists_a_mistake_in_each_sentence(tmp_path):
    body = {
        "sentences": [
            {"sentence": "The fox ran.", "parts": {"noun": ["cat"]}},
            {"sentence": "A dog sat.", "parts": {"verb": ["sat"]}},
            {"sentence": "The hen.", "parts": {"noun": ["hen"]}, "colour": "red"},
        ],
    }
    text = GOOD + f"tasks:\n  parts_of_speech:\n    parts:\n      group: younger\n      pass_cooldown: 0\n      body: {json.dumps(body)}\n"
    problems = _problems(_write(tmp_path, "policy.yaml", text))
    _assert_listed(problems, ["body.sentences entry 1: parts.noun", "body.sentences entry 3: colour: unknown setting"])


def test_errors_in_included_files_do_not_hide_each_other_and_name_their_file(tmp_path):
    root = _write(tmp_path, "policy.yaml", GOOD.replace("entry: household", "entry: household\ninclude: [a.yaml, more]\nport: none"))
    first = _write(tmp_path, "a.yaml", "quotas:\n  q:\n    time: 1h\n    ruleset: nowhere\n")
    second = _write(tmp_path, "more/b.yaml", "site_groups:\n  games:\n    priority: ten\n    patterns: [g.example]\n")
    problems = _problems(root)
    assert [problem.split(":", 1)[0] for problem in problems] == [str(root), str(first), str(second)]
    _assert_listed(problems, ["port must be a whole number", "unknown rule set 'nowhere'", "priority must be a whole number"])


def test_a_yaml_syntax_error_stops_only_its_own_file(tmp_path):
    root = _write(tmp_path, "policy.yaml", GOOD.replace("entry: household", "entry: household\ninclude: [broken.yaml, fine.yaml]\nbogus: 1"))
    broken = _write(tmp_path, "broken.yaml", "include: [never.yaml]\nsite_groups: [unclosed\n")
    fine = _write(tmp_path, "fine.yaml", "quotas:\n  q:\n    time: soon\n    ruleset: household\n")
    problems = _problems(root)
    _assert_listed(problems, ["unknown setting bogus", "while parsing", "time must be a duration"])
    assert problems[1].startswith(f"{broken}:3:")
    assert problems[2].startswith(f"{fine}:")
    assert not any("never.yaml" in problem for problem in problems)


def test_a_broken_item_still_counts_as_defined(tmp_path):
    text = """\
entry: household
client_groups:
  younger:
    addresses: "192.0.2.40"
site_groups:
  school:
    priority: high
    patterns: ["school.example"]
time_windows:
  evening:
    periods: []
quotas:
  video:
    time: lots
    ruleset: household
tasks:
  arithmetic:
    sums:
      group: younger
      pass_cooldown: soon
rule_sets:
  broken:
    - condition: sometimes
  household:
    - condition: client_group
      group: younger
      when_true: { action: evaluate, ruleset: broken }
    - condition: site_group
      group: school
      when_true: { action: allow }
    - condition: time_window
      window: evening
      when_true: { action: deny, message: "Late." }
    - condition: time_remaining
      quota: video
      when_false: { action: deny, message: "Done." }
"""
    problems = _problems(_write(tmp_path, "policy.yaml", text))
    assert not any(re.search(r"unknown (client group|site group|time window|quota|rule set)", problem) for problem in problems)
    assert [problem.split(":")[1] for problem in problems if "body." not in problem] == ["4", "7", "11", "14", "20", "23"]


def test_every_instance_of_a_whole_policy_problem_is_listed(tmp_path):
    text = """\
client_groups:
  younger:
    addresses: ["192.0.2.40", "192.0.2.41"]
  older:
    addresses: ["192.0.2.40", "192.0.2.41"]
site_groups:
  a: { priority: 1, patterns: [a.example] }
  b: { priority: 1, patterns: [b.example] }
  c: { priority: 2, patterns: [c.example] }
  d: { priority: 2, patterns: [d.example] }
  e: { priority: 3, patterns: [e.example] }
  f: { priority: 3, patterns: [f.example] }
rule_sets:
  loop:
    - condition: always
      when_true: { action: evaluate, ruleset: loop }
"""
    path = _write(tmp_path, "policy.yaml", text)
    problems = _problems(path)
    _assert_listed(
        problems,
        [
            f"{path}: entry is required",
            "192.0.2.40 belongs to client groups 'younger' and 'older'",
            "192.0.2.41 belongs to client groups 'younger' and 'older'",
            "'a' and 'b' both have priority 1",
            "'c' and 'd' both have priority 2",
            "'e' and 'f' both have priority 3",
            "evaluate cycle: loop -> loop",
        ],
    )


def test_an_error_in_a_file_included_twice_is_listed_once(tmp_path):
    root = _write(tmp_path, "policy.yaml", GOOD.replace("entry: household", "entry: household\ninclude: [shared.yaml, again.yaml]"))
    _write(tmp_path, "again.yaml", "include: [shared.yaml]\n")
    _write(tmp_path, "shared.yaml", "quotas:\n  q:\n    time: soon\n    ruleset: household\n")
    _assert_listed(_problems(root), ["time must be a duration"])


def test_spelling_tasks_whose_words_cannot_be_read_are_each_listed(tmp_path, monkeypatch):
    data = tmp_path / "data"
    write_wav(data / "spelling" / "current" / "cat.wav")
    write_alphabet(data / "spelling" / "alphabet")
    monkeypatch.setenv("DAYWARDEN_DATA_DIR", str(data))
    text = (
        GOOD.replace("entry: household", "entry: household\nbucket_length: 7m")
        + """\
tasks:
  spelling:
    fine:
      group: younger
      pass_cooldown: 0
    first:
      group: younger
      pass_cooldown: 0
      body: { current_dir: spelling/missing }
    second:
      group: younger
      pass_cooldown: 0
      body: { revision_dir: spelling/gone }
"""
    )
    _assert_listed(
        _problems(_write(tmp_path, "policy.yaml", text)),
        ["bucket_length must divide", "body.current_dir: ", "body.revision_dir: "],
    )


# python -m policy.check


@pytest.fixture
def mounted(tmp_path, monkeypatch):
    """A configuration directory standing in for /etc/daywarden."""
    config = tmp_path / "etc-daywarden"
    config.mkdir()
    monkeypatch.setattr(check, "CONFIG_MOUNT", str(config))
    monkeypatch.setenv("POLICY_FILE", str(config / "policy.yaml"))
    return config


def test_the_check_prints_every_error_with_the_host_path_and_exits_1(mounted, capsys):
    _write(mounted, "policy.yaml", SEVEN)
    assert check.main(["--host-dir", "config"]) == 1
    out, err = capsys.readouterr()
    assert out == ""
    lines = err.splitlines()
    assert lines[0] == "dw: the policy has 7 errors."
    _assert_listed(lines[1:], [f"config/policy.yaml{fragment}" for fragment in SEVEN_ERRORS])
    assert all(line.startswith("config/policy.yaml:") for line in lines[1:])


def test_the_count_line_says_one_error_and_what_was_refused(mounted, capsys):
    _write(mounted, "policy.yaml", GOOD + "bogus: 1\n")
    assert check.main(["--host-dir", "config", "--refused", "Nothing was reloaded."]) == 1
    lines = capsys.readouterr().err.splitlines()
    assert lines == ["dw: the policy has 1 error. Nothing was reloaded.", "config/policy.yaml:14:1: unknown setting bogus"]


def test_warnings_follow_the_errors_and_are_not_counted(mounted, capsys, monkeypatch):
    _write(mounted, "policy.yaml", GOOD.replace('"192.0.2.40"', '"192.0.2.40", "laptop.invalid"') + "bogus: 1\n")
    monkeypatch.setattr("policy.hierarchy.resolve_address", _no_dns)
    assert check.main([]) == 1
    lines = capsys.readouterr().err.splitlines()
    assert lines[0] == "dw: the policy has 1 error."
    assert lines[2] == "Warnings:"
    assert lines[3].startswith("  client group younger: laptop.invalid")


def test_a_good_policy_prints_the_summary_and_any_warnings(mounted, capsys, monkeypatch):
    _write(mounted, "policy.yaml", GOOD.replace('"192.0.2.40"', '"192.0.2.40", "laptop.invalid"'))
    monkeypatch.setattr("policy.hierarchy.resolve_address", _no_dns)
    assert check.main(["--host-dir", "config"]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    lines = out.splitlines()
    assert "entry household" in lines
    assert "client group younger: 192.0.2.40" in lines
    assert "site group school: priority 10, 1 patterns" in lines
    assert any(line.startswith("task pages are https://") for line in lines)
    assert lines[-2] == "Warnings:"


def test_quiet_prints_nothing_for_a_good_policy(mounted, capsys):
    _write(mounted, "policy.yaml", GOOD)
    assert check.main(["--quiet"]) == 0
    assert capsys.readouterr() == ("", "")


def test_a_missing_policy_file_is_an_error(mounted, capsys):
    assert check.main(["--host-dir", "config"]) == 1
    assert capsys.readouterr().err.splitlines() == [
        "dw: the policy has 1 error.",
        "config/policy.yaml: the policy file does not exist",
    ]


def test_a_path_outside_the_mount_is_shown_as_it_is():
    assert check.shown("/srv/policy.yaml:3:1: bad", "config") == "/srv/policy.yaml:3:1: bad"


def _no_dns(address, _lookup):
    from policy.clients import UnresolvedAddress, normalize_ip

    if normalize_ip(address) is not None:
        return (normalize_ip(address),)
    raise UnresolvedAddress(f"{address}: no such name")


def test_each_parent_name_bypass_txt_does_not_match_is_a_warning_even_when_quiet(mounted, capsys):
    _write(mounted, "policy.yaml", GOOD)
    _write(mounted, "bypass.txt", "# policy server\ngarden\n*.bakuna.net\n")
    names = "garden,garden.bakuna.net,tundra,192.168.12.5,localhost,127.0.0.1,::1"
    assert check.main(["--host-dir", "config", "--quiet", "--parent-names", names]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    lines = out.splitlines()
    assert lines[0] == "Warnings:"
    assert len(lines) == 3
    assert lines[1].startswith("  config/bypass.txt: tundra is in PARENT_NAMES and not in this list.")
    assert "only bypasses the proxy until the next restart picks up a change" in lines[1]
    assert lines[2].startswith("  config/bypass.txt: 192.168.12.5 is in PARENT_NAMES")


def test_parent_names_all_in_bypass_txt_add_no_warning(mounted, capsys):
    _write(mounted, "policy.yaml", GOOD)
    _write(mounted, "bypass.txt", "GARDEN\n")
    assert check.main(["--quiet", "--parent-names", "garden,localhost"]) == 0
    assert capsys.readouterr() == ("", "")


def test_a_missing_bypass_txt_warns_about_every_parent_name_beside_the_errors(mounted, capsys):
    _write(mounted, "policy.yaml", GOOD + "bogus: 1\n")
    assert check.main(["--host-dir", "config", "--parent-names", "garden"]) == 1
    lines = capsys.readouterr().err.splitlines()
    assert lines[0] == "dw: the policy has 1 error."
    assert lines[2] == "Warnings:"
    assert lines[3].startswith("  config/bypass.txt: garden is in PARENT_NAMES")
