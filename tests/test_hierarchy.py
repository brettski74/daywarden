"""S008.1: the YAML policy loader. Decisions still use the TOML engine."""

import sys
from datetime import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy.hierarchy import (  # noqa: E402
    DEFAULT_TIME_GRACE,
    DEFAULT_VOLUME_GRACE,
    ConfigError,
    Policy,
    load,
)

OPEN = """\
entry: open
rule_sets:
  open:
    - condition: always
      when_true: { action: allow }
"""


def _file(directory: Path, relative: str, text: str) -> Path:
    path = directory / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _load(directory: Path, text: str, **kwargs) -> Policy:
    loaded = load(_file(directory, "policy.yaml", text), **kwargs)
    assert isinstance(loaded, Policy)
    return loaded


def _dns(table: dict):
    def lookup(host, *_args, **_kwargs):
        if host not in table:
            raise OSError(f"{host} not found")
        value = table[host]
        if isinstance(value, OSError):
            raise value
        return [(None, None, None, "", (ip, 0)) for ip in value]

    return lookup


def _illustration() -> str:
    text = (ROOT / "docs" / "hierarchical-policy.md").read_text(encoding="utf-8")
    start = text.index("```yaml\nentry: household\n") + len("```yaml\n")
    body = text[start:]
    return body[: body.index("\n```")] + "\n"


def test_the_design_illustration_loads(tmp_path):
    policy = _load(
        tmp_path,
        _illustration(),
        lookup=_dns(
            {
                "younger.lan": ["192.168.1.21"],
                "older.lan": ["192.168.1.22"],
                "older-tablet.lan": ["192.168.1.23"],
            }
        ),
    )
    assert policy.entry == "household"
    assert policy.timezone == "America/Toronto"
    assert policy.hostname == "policy.home"
    assert policy.port is None
    assert policy.bucket_length == 300
    assert policy.time_grace == DEFAULT_TIME_GRACE
    assert policy.volume_grace == DEFAULT_VOLUME_GRACE
    assert policy.client_group("younger").ips == ("192.168.1.21",)
    assert policy.client_group("older").ips == ("192.168.1.22", "192.168.1.23")
    entertainment = policy.site_group("entertainment")
    assert entertainment.priority == 30
    assert "*.youtube.com" in entertainment.patterns
    assert "youtube.com" in entertainment.patterns
    assert [group.priority for group in policy.site_groups] == [10, 20, 30]
    before = policy.time_window("younger_before_school").periods[0]
    assert before.weekdays == frozenset({0, 1, 2, 3, 4})
    evening = policy.time_window("younger_evening").periods
    assert evening[1].weekdays == frozenset({4, 5, 6})
    weekend = policy.time_window("older_weekend").periods[0]
    assert (weekend.start, weekend.end, weekend.extra_days, weekend.weekdays) == (
        time(14, 0),
        time(18, 0),
        2,
        frozenset({4}),
    )
    bedtime = policy.time_window("weekday_bedtime").periods[0]
    assert bedtime.start > bedtime.end
    assert bedtime.extra_days == 0
    assert bedtime.weekdays == frozenset({0, 1, 2, 3})
    younger = policy.quota("younger_entertainment")
    older = policy.quota("older_entertainment")
    assert (younger.time_limit, younger.byte_limit) == (30 * 60, 0)
    assert (older.time_limit, older.byte_limit) == (2 * 3600, 0)
    assert younger.time_grace == DEFAULT_TIME_GRACE
    assert younger.volume_grace == DEFAULT_VOLUME_GRACE
    youtube = policy.rule_set("younger_youtube")
    assert youtube[0].when_true.kind == "continue"
    assert youtube[0].when_false.location == "revision_task"
    household = policy.rule_set("household")
    assert household[0].when_true.ruleset == "younger"
    assert household[0].when_false.kind == "continue"
    assert policy.rule_set("older_weekend_sites")[0].groups == ("reading", "entertainment")


def test_one_spelling_may_be_used_in_every_namespace(tmp_path):
    policy = _load(
        tmp_path,
        """\
entry: evening
client_groups:
  evening:
    addresses: ["10.1.0.8"]
site_groups:
  evening:
    priority: 1
    patterns: ["evening.example"]
time_windows:
  evening:
    periods:
      - start: "15:00"
        end: "18:00"
quotas:
  evening:
    time: 30m
    ruleset: evening
rule_sets:
  evening:
    - condition: client_group
      group: evening
      when_true: { action: allow }
    - condition: site_group
      group: evening
      when_true: { action: allow }
    - condition: time_window
      window: evening
      when_true: { action: allow }
    - condition: time_remaining
      quota: evening
      when_true: { action: continue }
""",
    )
    assert policy.client_group("evening").ips == ("10.1.0.8",)
    assert policy.site_group("evening").patterns == ("evening.example",)
    assert policy.time_window("evening").periods[0].weekdays is None
    assert policy.quota("evening").ruleset == "evening"
    assert policy.rule_set("evening")[0].groups == ("evening",)


def test_a_client_condition_does_not_see_a_site_group_of_the_same_name(tmp_path):
    text = """\
entry: open
site_groups:
  evening:
    priority: 1
    patterns: ["evening.example"]
rule_sets:
  open:
    - condition: client_group
      group: evening
      when_true: { action: allow }
"""
    with pytest.raises(ConfigError, match="unknown client group"):
        _load(tmp_path, text)


def test_default_is_reserved_for_the_two_group_namespaces(tmp_path):
    with pytest.raises(ConfigError, match="reserved"):
        _load(
            tmp_path,
            """\
entry: open
site_groups:
  default:
    priority: 1
    patterns: ["a.example"]
"""
            + OPEN.split("entry: open\n", 1)[1],
        )
    with pytest.raises(ConfigError, match="reserved"):
        _load(
            tmp_path,
            """\
entry: open
client_groups:
  default:
    addresses: ["10.0.0.1"]
"""
            + OPEN.split("entry: open\n", 1)[1],
        )
    policy = _load(
        tmp_path,
        """\
entry: default
rule_sets:
  default:
    - condition: site_group
      group: default
      when_true: { action: deny, message: "No." }
    - condition: client_group
      groups: [default]
      when_true: { action: deny, message: "No." }
""",
    )
    assert policy.entry == "default"
    assert policy.rule_set("default")[0].groups == ("default",)
    assert policy.site_groups == ()
    assert policy.client_groups == ()


def test_site_groups_keep_overlapping_patterns_and_reject_a_shared_priority(tmp_path):
    policy = _load(
        tmp_path,
        """\
entry: open
site_groups:
  narrow:
    priority: 1
    patterns: ["*.youtube.com"]
  wide:
    priority: 2
    patterns: ["*.youtube.com", "youtube.com"]
"""
        + OPEN.split("entry: open\n", 1)[1],
    )
    assert policy.site_group("narrow").patterns == ("*.youtube.com",)
    assert policy.site_group("wide").patterns == ("*.youtube.com", "youtube.com")
    with pytest.raises(ConfigError, match="at least one"):
        _load(
            tmp_path,
            """\
entry: open
site_groups:
  empty:
    priority: 1
    patterns: []
"""
            + OPEN.split("entry: open\n", 1)[1],
        )
    with pytest.raises(ConfigError, match="whole number"):
        _load(
            tmp_path,
            """\
entry: open
site_groups:
  reading:
    priority: true
    patterns: ["a.example"]
"""
            + OPEN.split("entry: open\n", 1)[1],
        )
    with pytest.raises(ConfigError, match="priority"):
        _load(
            tmp_path,
            """\
entry: open
site_groups:
  narrow:
    priority: 1
    patterns: ["a.example"]
  wide:
    priority: 1
    patterns: ["b.example"]
"""
            + OPEN.split("entry: open\n", 1)[1],
        )


def test_client_addresses_are_unique_once_canonical(tmp_path):
    with pytest.raises(ConfigError, match="at least one"):
        _load(
            tmp_path,
            """\
entry: open
client_groups:
  younger:
    addresses: []
"""
            + OPEN.split("entry: open\n", 1)[1],
        )
    with pytest.raises(ConfigError, match="listed twice"):
        _load(
            tmp_path,
            """\
entry: open
client_groups:
  younger:
    addresses: ["10.0.0.1", "10.0.0.1"]
"""
            + OPEN.split("entry: open\n", 1)[1],
        )
    with pytest.raises(ConfigError, match="listed twice"):
        _load(
            tmp_path,
            """\
entry: open
client_groups:
  younger:
    addresses: ["10.0.0.9", "::ffff:10.0.0.9"]
"""
            + OPEN.split("entry: open\n", 1)[1],
        )
    with pytest.raises(ConfigError, match="belongs"):
        _load(
            tmp_path,
            """\
entry: open
client_groups:
  younger:
    addresses: ["10.0.0.1"]
  older:
    addresses: ["::ffff:10.0.0.1"]
"""
            + OPEN.split("entry: open\n", 1)[1],
        )
    with pytest.raises(ConfigError, match="listed twice"):
        _load(
            tmp_path,
            """\
entry: open
client_groups:
  younger:
    addresses: ["a.lan", "b.lan"]
"""
            + OPEN.split("entry: open\n", 1)[1],
            lookup=_dns({"a.lan": ["10.2.0.1"], "b.lan": ["10.2.0.1"]}),
        )
    policy = _load(
        tmp_path,
        """\
entry: open
client_groups:
  younger:
    addresses: ["10.9.8.7", "2001:0db8:0000:0000:0000:0000:0000:0001"]
"""
        + OPEN.split("entry: open\n", 1)[1],
        lookup=_dns({}),
    )
    assert policy.client_group("younger").ips == ("10.9.8.7", "2001:db8::1")


def test_a_failed_dns_name_keeps_the_last_resolution(tmp_path):
    text = """\
entry: open
client_groups:
  younger:
    addresses: ["younger.lan", "tablet.lan"]
rule_sets:
  open:
    - condition: always
      when_true: { action: allow }
"""
    warnings: list[str] = []
    first = _load(
        tmp_path,
        text,
        lookup=_dns({"younger.lan": ["10.0.0.2"], "tablet.lan": ["10.0.0.3"]}),
        warn=warnings.append,
    )
    second = _load(
        tmp_path,
        text,
        previous=first,
        lookup=_dns({"younger.lan": ["10.0.0.8"], "tablet.lan": OSError("down")}),
        warn=warnings.append,
    )
    assert second.client_group("younger").resolved == (("10.0.0.8",), ("10.0.0.3",))
    assert first.client_group("younger").resolved == (("10.0.0.2",), ("10.0.0.3",))
    assert any("keeping" in message for message in warnings)

    moved = """\
entry: open
client_groups:
  younger:
    addresses: ["other.lan"]
rule_sets:
  open:
    - condition: always
      when_true: { action: allow }
"""
    quiet: list[str] = []
    changed = _load(
        tmp_path,
        moved,
        previous=first,
        lookup=_dns({"other.lan": OSError("down")}),
        warn=quiet.append,
    )
    assert changed.client_group("younger").ips == ()
    assert any("no IP" in message for message in quiet)

    with pytest.raises(ConfigError, match="listed twice"):
        _load(
            tmp_path,
            text,
            previous=first,
            lookup=_dns({"younger.lan": ["10.0.0.3"], "tablet.lan": OSError("down")}),
            warn=lambda _message: None,
        )


def test_periods_accept_clocks_ranges_and_the_day_suffix(tmp_path):
    policy = _load(
        tmp_path,
        """\
entry: open
time_windows:
  bed:
    periods:
      - start: "07:00"
        end: "1930"
      - start: "2200"
        end: "0700+1"
        days: friday-tuesday
      - start: "14:00"
        end: "14:00"
        day: friday
      - start: "14:00"
        end: "14:00+0"
        days: [monday, thursday]
      - start: "20:00"
        end: "07:00"
        days: monday-thursday
rule_sets:
  open:
    - condition: always
      when_true: { action: allow }
""",
    )
    periods = policy.time_window("bed").periods
    assert (periods[0].start, periods[0].end, periods[0].extra_days, periods[0].weekdays) == (
        time(7, 0),
        time(19, 30),
        0,
        None,
    )
    assert periods[1].extra_days == 1
    assert periods[1].weekdays == frozenset({4, 5, 6, 0, 1})
    assert periods[2].start == periods[2].end == time(14, 0)
    assert periods[2].weekdays == frozenset({4})
    assert periods[3].extra_days == 0
    assert periods[3].weekdays == frozenset({0, 3})
    assert periods[4].start == time(20, 0)
    assert periods[4].end == time(7, 0)
    assert periods[4].weekdays == frozenset({0, 1, 2, 3})


@pytest.mark.parametrize(
    ("fragment", "match"),
    [
        ('start: 14:00\n        end: "19:00"', "unquoted"),
        ('start: 0700\n        end: "0800"', "unquoted"),
        ('start: 07:00\n        end: "08:00"', "quoted"),
        ('start: "14:00"\n        end: "18:00+-1"', "negative"),
        ('start: "14:00"\n        end: "18:00+2.5"', "whole number"),
        ('start: "14:00"\n        end: "15:00"\n        day: monday\n        days: tuesday', "not both"),
        ('start: "14:00"\n        end: "15:00"\n        days: []', "empty day list"),
        ('start: "14:00"\n        end: "15:00"\n        days: friday-friday', "same day"),
        ('start: "14:00"\n        end: "15:00"\n        day: monday-thursday', "range"),
        (
            'start: "14:00"\n        end: "15:00"\n        days: [monday-wednesday, tuesday]',
            "listed twice",
        ),
    ],
)
def test_periods_reject_bad_clocks_and_days(tmp_path, fragment, match):
    text = f"""\
entry: open
time_windows:
  bed:
    periods:
      - {fragment}
rule_sets:
  open:
    - condition: always
      when_true: {{ action: allow }}
"""
    with pytest.raises(ConfigError, match=match):
        _load(tmp_path, text)


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("2h", 2 * 3600),
        ("120m", 120 * 60),
        ("7200s", 7200),
        ("0s", 0),
    ],
)
def test_time_limits_are_durations(tmp_path, written, expected):
    policy = _load(
        tmp_path,
        f"""\
entry: open
quotas:
  meter:
    time: {written}
    ruleset: open
rule_sets:
  open:
    - condition: always
      when_true: {{ action: allow }}
""",
    )
    assert policy.quota("meter").time_limit == expected
    assert policy.quota("meter").byte_limit == 0


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("720b", 720),
        ("720k", 720 * 1024),
        ("720M", 720 * 1024**2),
        ("720G", 720 * 1024**3),
        ("720T", 720 * 1024**4),
        ("0b", 0),
    ],
)
def test_byte_limits_are_powers_of_two(tmp_path, written, expected):
    policy = _load(
        tmp_path,
        f"""\
entry: open
quotas:
  meter:
    bytes: {written}
    ruleset: open
rule_sets:
  open:
    - condition: always
      when_true: {{ action: allow }}
""",
    )
    assert policy.quota("meter").byte_limit == expected
    assert policy.quota("meter").time_limit == 0


def test_omitted_limits_are_zero_and_grace_defaults_to_five_minutes_and_1m(tmp_path):
    policy = _load(tmp_path, """\
entry: open
quotas:
  meter:
    ruleset: open
rule_sets:
  open:
    - condition: always
      when_true: { action: allow }
""")
    quota = policy.quota("meter")
    assert quota.time_limit == 0
    assert quota.byte_limit == 0
    assert quota.time_grace == 5 * 60
    assert quota.volume_grace == 1024**2
    assert policy.bucket_length == 300
    assert policy.time_grace == 5 * 60
    assert policy.volume_grace == 1024**2


def test_a_quota_grace_wins_and_zero_is_allowed(tmp_path):
    policy = _load(
        tmp_path,
        """\
entry: open
time_grace: 10m
volume_grace: 2M
quotas:
  household_default:
    ruleset: open
  explicit:
    ruleset: open
    time_grace: 0s
    volume_grace: 0b
rule_sets:
  open:
    - condition: always
      when_true: { action: allow }
""",
    )
    assert policy.time_grace == 600
    assert policy.volume_grace == 2 * 1024**2
    inherited = policy.quota("household_default")
    assert inherited.time_grace == 600
    assert inherited.volume_grace == 2 * 1024**2
    explicit = policy.quota("explicit")
    assert explicit.time_grace == 0
    assert explicit.volume_grace == 0


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("time: 2\n", "bare number"),
        ("time: 2H\n", "duration"),
        ("bytes: 720\n", "bare number"),
        ("bytes: 720m\n", "size"),
        ("bytes: 720MB\n", "size"),
        ("bytes: 720K\n", "size"),
        ("time_grace: -5m\n", "negative"),
        ("time_grace: -5\n", "negative"),
        ("volume_grace: -1b\n", "negative"),
        ("bytes: -1b\n", "negative"),
    ],
)
def test_quotas_reject_bad_limits_and_grace(tmp_path, text, match):
    document = f"""\
entry: open
quotas:
  meter:
    ruleset: open
    {text}rule_sets:
  open:
    - condition: always
      when_true: {{ action: allow }}
"""
    with pytest.raises(ConfigError, match=match):
        _load(tmp_path, document)


def test_group_and_window_are_one_list(tmp_path):
    policy = _load(
        tmp_path,
        """\
entry: open
site_groups:
  reading:
    priority: 1
    patterns: ["*.wikipedia.org"]
  entertainment:
    priority: 2
    patterns: ["*.youtube.com"]
time_windows:
  evening:
    periods:
      - start: "15:00"
        end: "18:00"
  bedtime:
    periods:
      - start: "20:00"
        end: "07:00"
rule_sets:
  open:
    - condition: site_group
      group: reading
      when_true: { action: allow }
    - condition: site_group
      groups: [reading, entertainment]
      when_false: { action: deny, message: "Closed." }
    - condition: time_window
      window: evening
      when_true: { action: allow }
    - condition: time_window
      windows: [evening, bedtime]
      when_true: { action: allow }
""",
    )
    rules = policy.rule_set("open")
    assert rules[0].groups == ("reading",)
    assert rules[1].groups == ("reading", "entertainment")
    assert rules[2].windows == ("evening",)
    assert rules[3].windows == ("evening", "bedtime")


@pytest.mark.parametrize(
    ("rule", "match"),
    [
        ("condition: site_group\n      group: reading\n      groups: [reading]", "not both"),
        ("condition: site_group\n      groups: []", "at least one"),
        ("condition: time_window\n      window: evening\n      windows: [evening]", "not both"),
        ("condition: time_window\n      windows: []", "at least one"),
        ("condition: site_group\n      group: [reading]", "string"),
        ("condition: site_group\n      groups: reading", "list"),
        ("condition: always\n      group: reading", "unknown setting"),
        ("condition: sometimes", "unknown condition"),
        ("condition: tasks_required\n      required: -1", "zero or more"),
        ("condition: always\n      when_true: { action: allow, message: No }", "unknown setting"),
        ("condition: always\n      when_true: { action: deny }", "message"),
        ("condition: always\n      when_true: { action: redirect, location: /tasks }", "absolute"),
        ("condition: always\n      when_true: { action: pause }", "unknown action"),
        (
            "condition: always\n      when_true: { action: evaluate, ruleset: open, rules: [] }",
            "not both",
        ),
        ("condition: always\n      when_true: { action: evaluate }", "needs a ruleset"),
    ],
)
def test_rules_reject_bad_conditions_and_actions(tmp_path, rule, match):
    text = f"""\
entry: open
site_groups:
  reading:
    priority: 1
    patterns: ["*.wikipedia.org"]
time_windows:
  evening:
    periods:
      - start: "15:00"
        end: "18:00"
rule_sets:
  open:
    - {rule}
"""
    with pytest.raises(ConfigError, match=match):
        _load(tmp_path, text)


def test_tasks_required_accepts_zero_and_revision_task(tmp_path):
    policy = _load(
        tmp_path,
        """\
entry: open
rule_sets:
  open:
    - condition: tasks_required
      required: 0
      when_false: { action: redirect, location: revision_task }
    - condition: always
      when_true:
        action: evaluate
        rules:
          - condition: always
            when_true: { action: allow }
""",
    )
    assert policy.rule_set("open")[0].required == 0
    assert policy.rule_set("open")[0].when_true.kind == "continue"
    assert policy.rule_set("open")[0].when_false.location == "revision_task"
    assert policy.rule_set("open")[1].when_true.rules[0].when_true.kind == "allow"


def test_evaluate_cycles_fail_and_include_cycles_do_not(tmp_path):
    with pytest.raises(ConfigError, match="evaluate cycle"):
        _load(
            tmp_path,
            """\
entry: loop
rule_sets:
  loop:
    - condition: always
      when_true: { action: evaluate, ruleset: loop }
""",
        )
    with pytest.raises(ConfigError, match="evaluate cycle"):
        _load(
            tmp_path,
            """\
entry: a
rule_sets:
  a:
    - condition: always
      when_true: { action: evaluate, ruleset: b }
  b:
    - condition: always
      when_true: { action: evaluate, ruleset: a }
""",
        )
    with pytest.raises(ConfigError, match="evaluate cycle"):
        _load(
            tmp_path,
            """\
entry: a
rule_sets:
  a:
    - condition: always
      when_true:
          action: evaluate
          rules:
            - condition: always
              when_true: { action: evaluate, ruleset: a }
""",
        )
    _file(
        tmp_path,
        "a.yaml",
        """\
include:
  - b.yaml
site_groups:
  alpha:
    priority: 1
    patterns: ["a.example"]
""",
    )
    _file(
        tmp_path,
        "b.yaml",
        """\
include:
  - a.yaml
site_groups:
  beta:
    priority: 2
    patterns: ["b.example"]
""",
    )
    root = _file(tmp_path, "policy.yaml", "entry: open\ninclude: [a.yaml]\n" + OPEN.split("entry: open\n", 1)[1])
    policy = load(root)
    assert isinstance(policy, Policy)
    assert policy.site_group("alpha").priority == 1
    assert policy.site_group("beta").priority == 2


def test_includes_merge_files_and_one_directory_level(tmp_path):
    _file(
        tmp_path,
        "child.yaml",
        """\
timezone: America/Toronto
client_groups:
  younger:
    addresses: ["10.4.0.1"]
""",
    )
    policy = _load(
        tmp_path,
        """\
entry: open
include:
  - child.yaml
  - child.yaml
  - ./child.yaml
rule_sets:
  open:
    - condition: always
      when_true: { action: allow }
""",
    )
    assert policy.timezone == "America/Toronto"
    assert policy.client_group("younger").ips == ("10.4.0.1",)

    _file(tmp_path, "nested/one.yaml", 'include: ["two.yaml"]\n')
    _file(
        tmp_path,
        "nested/two.yaml",
        """\
site_groups:
  nested:
    priority: 4
    patterns: ["nested.example"]
""",
    )
    nested = _load(
        tmp_path,
        """\
entry: open
include: ["nested/one.yaml"]
rule_sets:
  open:
    - condition: always
      when_true: { action: allow }
""",
    )
    assert nested.site_group("nested").patterns == ("nested.example",)

    parts = tmp_path / "parts"
    _file(
        parts,
        "10.yaml",
        """\
site_groups:
  ten:
    priority: 10
    patterns: ["ten.example"]
""",
    )
    _file(
        parts,
        "2.yaml",
        """\
site_groups:
  two:
    priority: 2
    patterns: ["two.example"]
""",
    )
    _file(
        parts,
        "a.yml",
        """\
site_groups:
  aye:
    priority: 3
    patterns: ["aye.example"]
""",
    )
    _file(
        parts,
        "b.yaml",
        """\
site_groups:
  bee:
    priority: 4
    patterns: ["bee.example"]
""",
    )
    _file(parts, "notes.txt", ":::\n")
    _file(parts, "readme.yaml.bak", ":::\n")
    _file(
        parts,
        "sub/hidden.yaml",
        """\
site_groups:
  hidden:
    priority: 10
    patterns: ["hidden.example"]
""",
    )
    listed = load(
        _file(
            tmp_path,
            "directory.yaml",
            """\
entry: open
include:
  - parts
rule_sets:
  open:
    - condition: always
      when_true: { action: allow }
""",
        )
    )
    assert isinstance(listed, Policy)
    assert [group.name for group in listed.site_groups] == ["ten", "two", "aye", "bee"]

    with pytest.raises(ConfigError, match="already defined"):
        _load(
            tmp_path,
            """\
entry: open
include: ["child.yaml"]
client_groups:
  younger:
    addresses: ["10.9.0.1"]
rule_sets:
  open:
    - condition: always
      when_true: { action: allow }
""",
        )
    _file(tmp_path, "again.yaml", "bucket_length: 10m\n")
    with pytest.raises(ConfigError, match="already set"):
        _load(
            tmp_path,
            """\
entry: open
bucket_length: 5m
include: ["again.yaml"]
rule_sets:
  open:
    - condition: always
      when_true: { action: allow }
""",
        )
    with pytest.raises(ConfigError, match="does not exist"):
        _load(
            tmp_path,
            """\
entry: open
include: ["missing.yaml"]
rule_sets:
  open:
    - condition: always
      when_true: { action: allow }
""",
        )
    with pytest.raises(ConfigError, match="relative"):
        _load(
            tmp_path,
            """\
entry: open
include: ["/etc/policy.yaml"]
rule_sets:
  open:
    - condition: always
      when_true: { action: allow }
""",
        )


def test_a_missing_root_keeps_the_previous_policy(tmp_path):
    previous = _load(tmp_path, OPEN)
    rules = previous.rule_set("open")
    assert load(tmp_path / "absent.yaml", previous=previous) is previous
    assert load(tmp_path / "absent.yaml") is None
    _file(tmp_path, "beside.yaml", "entry: other\n")
    assert load(tmp_path / "policy.yaml").entry == "open"

    with pytest.raises(ConfigError, match="duplicate key"):
        _load(tmp_path, "entry: open\nentry: other\n" + OPEN.split("entry: open\n", 1)[1])
    with pytest.raises(ConfigError, match="anchors"):
        _load(tmp_path, "entry: &name open\n" + OPEN.split("entry: open\n", 1)[1])
    with pytest.raises(ConfigError, match="aliases"):
        _load(tmp_path, "entry: *missing\n")
    with pytest.raises(ConfigError, match="another document"):
        _load(tmp_path, "---\nentry: open\n---\nentry: other\n")
    with pytest.raises(ConfigError, match="entry is required"):
        _load(tmp_path, OPEN.split("entry: open\n", 1)[1])
    with pytest.raises(ConfigError, match="does not name a rule set"):
        _load(
            tmp_path,
            """\
entry: missing
rule_sets:
  open:
    - condition: always
      when_true: { action: allow }
""",
        )
    with pytest.raises(ConfigError, match="unknown setting"):
        _load(tmp_path, "hobby: fishing\n" + OPEN)
    with pytest.raises(ConfigError, match="unknown rule set"):
        _load(
            tmp_path,
            """\
entry: open
quotas:
  meter:
    ruleset: missing
"""
            + OPEN.split("entry: open\n", 1)[1],
        )
    with pytest.raises(ConfigError, match="unknown time window"):
        _load(
            tmp_path,
            """\
entry: open
rule_sets:
  open:
    - condition: time_window
      window: bedtime
      when_true: { action: allow }
""",
        )
    with pytest.raises(ConfigError, match="unknown quota"):
        _load(
            tmp_path,
            """\
entry: open
rule_sets:
  open:
    - condition: volume_remaining
      quota: meter
      when_false: { action: deny, message: "Full." }
""",
        )
    with pytest.raises(ConfigError, match="divide"):
        _load(tmp_path, "bucket_length: 7s\n" + OPEN)
    with pytest.raises(ConfigError, match="unknown timezone"):
        _load(tmp_path, "timezone: Mars/Olympus\n" + OPEN)
    bad = _file(tmp_path, "bad.yaml", "entry: open\ninclude: [missing.yaml]\n")
    with pytest.raises(ConfigError, match="does not exist"):
        load(bad, previous=previous)
    assert previous.rule_set("open") is rules
    assert previous.entry == "open"


def test_bucket_length_of_five_minutes_is_the_default(tmp_path):
    policy = _load(tmp_path, "bucket_length: 5m\n" + OPEN)
    assert policy.bucket_length == 300
    assert _load(tmp_path, "bucket_length: 24h\n" + OPEN).bucket_length == 24 * 3600
