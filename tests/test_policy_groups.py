"""S001.2: site groups are matched by glob in priority order and stored in SQLite."""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy import config
from policy.groups import SiteGroup, SiteGroups, matches
from policy.store import SCHEMA_VERSION, PolicyStore

GROUPS = """
[[groups]]
name = "School work"
priority = 10
patterns = ["https://classroom.google.com/*", "classroom.google.com"]

[[groups]]
name = "Google"
priority = 20
patterns = ["*.google.com"]

[[groups]]
name = "Entertainment"
priority = 30
patterns = ["*.youtube.com", "youtu.be", "*.googlevideo.com"]

[[groups]]
name = "Everything else"
priority = 1000
default = true
"""


def _quiet(_message):
    return None


def _groups(text: str = GROUPS) -> SiteGroups:
    return SiteGroups(config.parse(text).groups)


def _name(groups: SiteGroups, url: str) -> str | None:
    group = groups.classify(url)
    return group.name if group else None


@pytest.mark.parametrize(
    ("pattern", "url"),
    [
        ("https://classroom.google.com/*", "https://classroom.google.com/u/0/h"),
        ("classroom.google.com", "https://classroom.google.com/u/0/h"),
        ("*.youtube.com", "https://www.youtube.com/watch?v=abc#t=10"),
        ("youtu.be", "https://youtu.be/abc"),
        ("*.youtube.com", "https://WWW.YouTube.COM/watch"),
        ("*.YOUTUBE.com", "https://www.youtube.com/watch"),
        ("HTTPS://Classroom.Google.com/*", "https://classroom.google.com/c/xyz"),
        ("https://*.google.com/*/edit", "https://docs.google.com/document/d/1/edit"),
        ("youtu.?e", "https://youtu.be/abc"),
        ("www.youtube.com", "https://www.youtube.com:8443/watch"),
        ("www.youtube.com", "https://www.youtube.com./watch"),
        ("https://www.youtube.com/watch?v=abc", "https://www.youtube.com/watch?v=abc#t=10"),
    ],
)
def test_pattern_matches(pattern, url):
    assert matches(pattern, url)


@pytest.mark.parametrize(
    ("pattern", "url"),
    [
        ("*.googlevideo.com", "https://www.youtube.com/watch?v=abc"),
        ("*.youtube.com", "https://youtube.com/watch"),
        ("youtube.com", "https://www.youtube.com/watch"),
        ("youtube.com", "https://example.org/youtube.com"),
        ("https://www.youtube.com/watch?v=abc#t=10", "https://www.youtube.com/watch?v=abc#t=10"),
        ("*#t=10", "https://www.youtube.com/watch?v=abc#t=10"),
        ("https://classroom.google.com/*", "http://classroom.google.com/u/0/h"),
        ("youtu.?e", "https://youtu.bbe/abc"),
        ("classroom.google.com", "https://evil.test/?classroom.google.com"),
    ],
)
def test_pattern_does_not_match(pattern, url):
    assert not matches(pattern, url)


def test_a_star_in_a_url_pattern_matches_across_slashes():
    assert matches("https://www.youtube.com*", "https://www.youtube.com/a/b/c?d=e")
    assert matches("*://classroom.google.com/*", "http://classroom.google.com/x/y")


def test_a_url_that_matches_two_groups_goes_to_the_lower_priority_number():
    groups = _groups()
    assert _name(groups, "https://classroom.google.com/u/0/h") == "School work"
    assert _name(groups, "https://mail.google.com/") == "Google"


def test_priority_order_is_by_number_not_by_file_order():
    reordered = """
[[groups]]
name = "Google"
priority = 20
patterns = ["*.google.com"]

[[groups]]
name = "School work"
priority = 5
patterns = ["classroom.google.com"]
"""
    assert _name(_groups(reordered), "https://classroom.google.com/") == "School work"


def test_an_unrecognized_url_goes_to_the_default_group():
    assert _name(_groups(), "https://example.org/") == "Everything else"


def test_the_default_group_is_tried_after_every_other_group_and_its_patterns_are_ignored():
    text = """
[[groups]]
name = "Everything else"
priority = 1
default = true
patterns = ["*.youtube.com"]

[[groups]]
name = "Entertainment"
priority = 30
patterns = ["*.youtube.com"]
"""
    groups = _groups(text)
    assert _name(groups, "https://www.youtube.com/") == "Entertainment"
    assert _name(groups, "https://example.org/") == "Everything else"


def test_without_a_default_group_an_unrecognized_url_has_no_group():
    without_default = GROUPS.split('[[groups]]\nname = "Everything else"')[0]
    assert _name(_groups(without_default), "https://example.org/") is None
    assert _name(SiteGroups([]), "https://www.youtube.com/") is None


def test_groups_survive_reopening_the_database(tmp_path):
    database = tmp_path / "policy.sqlite3"
    with PolicyStore(database) as store:
        config.apply(config.parse(GROUPS), store, warn=_quiet)
    with PolicyStore(database) as reopened:
        stored = reopened.groups()
    assert stored == list(config.parse(GROUPS).groups)
    assert _name(SiteGroups(stored), "https://youtu.be/abc") == "Entertainment"


def test_loading_twice_does_not_duplicate_groups_and_keeps_their_ids():
    with PolicyStore(":memory:") as store:
        config.apply(config.parse(GROUPS), store, warn=_quiet)
        first = dict(store.connection.execute("SELECT name, id FROM site_groups"))
        swapped = GROUPS.replace("priority = 10", "priority = 25").replace("priority = 20", "priority = 10")
        config.apply(config.parse(swapped), store, warn=_quiet)
        second = dict(store.connection.execute("SELECT name, id FROM site_groups"))
        assert second == first
        assert {group.name: group.priority for group in store.groups()}["Google"] == 10


def test_a_group_removed_from_the_file_is_removed_from_the_database():
    one = '[[groups]]\nname = "Entertainment"\npriority = 1\npatterns = ["youtu.be"]\n'
    with PolicyStore(":memory:") as store:
        config.apply(config.parse(GROUPS), store, warn=_quiet)
        config.apply(config.parse(one), store, warn=_quiet)
        assert store.groups() == [SiteGroup("Entertainment", 1, ("youtu.be",))]
        (patterns,) = store.connection.execute("SELECT count(*) FROM site_group_patterns").fetchone()
        assert patterns == 1


def test_a_version_1_database_is_upgraded_and_keeps_its_clients(tmp_path):
    database = tmp_path / "policy.sqlite3"
    with PolicyStore(database) as store:
        config.apply(config.parse('[[clients]]\nname = "A"\naddress = "10.0.0.1"\n'), store, warn=_quiet)
        store.connection.executescript(
            """
            DROP TABLE rule_actions;
            DROP TABLE rule_windows;
            DROP TABLE rules;
            DROP TABLE site_group_patterns;
            DROP TABLE site_groups;
            PRAGMA user_version = 1;
            """
        )
    with PolicyStore(database) as upgraded:
        (version,) = upgraded.connection.execute("PRAGMA user_version").fetchone()
        assert version == SCHEMA_VERSION
        assert [client.name for client in upgraded.clients()] == ["A"]
        assert upgraded.groups() == []


def test_the_sample_has_one_default_group():
    sample = config.load(ROOT / "config" / "policy.toml")
    assert [group.name for group in sample.groups if group.default] == ["Everything else"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            '[[groups]]\nname = "A"\npriority = 1\n[[groups]]\nname = "B"\npriority = 1\n',
            "groups 'A' and 'B' both have priority 1",
        ),
        (
            '[[groups]]\nname = "A"\npriority = 1\ndefault = true\n'
            '[[groups]]\nname = "B"\npriority = 2\ndefault = true\n',
            "groups 'A' and 'B' are both the default",
        ),
        ('[[groups]]\nname = "A"\npriority = 1\n[[groups]]\nname = "A"\npriority = 2\n', "used twice"),
        ('[[groups]]\npriority = 1\n', "name is required"),
        ('[[groups]]\nname = "A"\n', "priority must be a whole number"),
        ('[[groups]]\nname = "A"\npriority = "1"\n', "priority must be a whole number"),
        ('[[groups]]\nname = "A"\npriority = 1.5\n', "priority must be a whole number"),
        ('[[groups]]\nname = "A"\npriority = true\n', "priority must be a whole number"),
        ('[[groups]]\nname = "A"\npriority = 1\ndefault = "yes"\n', "default must be true or false"),
        ('[[groups]]\nname = "A"\npriority = 1\npatterns = "*.youtube.com"\n', "patterns must be a list"),
        ('[[groups]]\nname = "A"\npriority = 1\npatterns = ["ok", ""]\n', "patterns must be a list"),
        ('[[groups]]\nname = "A"\npriority = 1\npatterns = [1]\n', "patterns must be a list"),
        ('[[groups]]\nname = "A"\npriority = 1\nlabel = "x"\n', "unknown setting label"),
        ('groups = "A"\n', "[[groups]]"),
    ],
)
def test_invalid_groups_are_rejected(text, message):
    with pytest.raises(config.ConfigError, match=re.escape(message)):
        config.parse(text)
