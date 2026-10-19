"""Host globs used by the proxy bypass list."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proxy"))

import bypass


def test_star_matches_a_suffix_and_leaves_other_hosts_alone():
    patterns = ["*.google.test", "tasks.smartproxy.test"]
    assert bypass.is_bypassed("class.google.test", patterns)
    assert bypass.is_bypassed("CLASS.Google.Test", patterns)
    assert bypass.is_bypassed("tasks.smartproxy.test", patterns)
    assert not bypass.is_bypassed("notgoogle.test", patterns)
    assert not bypass.is_bypassed("google.test", patterns)
    assert not bypass.is_bypassed("class.google.test.evil", patterns)


def test_question_mark_matches_one_character():
    patterns = ["?.google.test"]
    assert bypass.is_bypassed("a.google.test", patterns)
    assert not bypass.is_bypassed("ab.google.test", patterns)


def test_comments_and_blank_lines_are_not_patterns(tmp_path):
    path = tmp_path / "bypass.txt"
    path.write_text("# classroom\n\n*.google.test # school\n")
    assert bypass.load_patterns(path) == ["*.google.test"]


def test_missing_file_bypasses_nothing(tmp_path):
    assert bypass.load_patterns(tmp_path / "missing.txt") == []
