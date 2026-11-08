"""Host globs used by the proxy bypass list."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proxy"))

import bypass


def test_star_matches_a_suffix_and_leaves_other_hosts_alone():
    patterns = ["*.google.test", "tasks.daywarden.test"]
    assert bypass.is_bypassed("class.google.test", patterns)
    assert bypass.is_bypassed("CLASS.Google.Test", patterns)
    assert bypass.is_bypassed("tasks.daywarden.test", patterns)
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


def test_parent_names_are_bypassed_except_the_loopback_names():
    names = bypass.parent_names(" garden , Garden.Bakuna.NET,localhost,127.0.0.1,::1,192.168.12.5,,")
    assert names == {"garden", "garden.bakuna.net", "192.168.12.5"}
    for host in ("garden", "GARDEN.bakuna.net.", "192.168.12.5"):
        assert bypass.is_bypassed(host, [], names)
        assert bypass.is_parent(host, names)
    for host in ("localhost", "127.0.0.1", "::1", "gardener"):
        assert not bypass.is_bypassed(host, [], names)
        assert not bypass.is_parent(host, names)


def test_the_two_lists_are_merged_and_only_parent_names_carry_the_childs_address():
    names = bypass.parent_names("garden")
    patterns = ["garden", "*.google.test"]
    assert bypass.is_bypassed("garden", patterns, names)
    assert bypass.is_bypassed("class.google.test", patterns, names)
    assert bypass.is_parent("garden", names)
    assert not bypass.is_parent("class.google.test", names)
    assert not bypass.is_bypassed("garden", ["*.google.test"], frozenset())


def test_an_unset_parent_names_adds_nothing():
    assert bypass.parent_names(None) == frozenset()
    assert bypass.parent_names("") == frozenset()
