"""S019: the proxy_configuration section of the policy, its checks, and its summary."""

from pathlib import Path

import pytest

from policy import check
from policy.hierarchy import ConfigError, load
from policy.pac import SWITCHES

GOOD = """\
entry: household
hostname: garden
rule_sets:
  household:
    - condition: always
      when_true: { action: allow }
"""


def _write(directory: Path, relative: str, text: str) -> Path:
    path = directory / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_without_the_section_every_switch_is_on_and_extra_is_empty(tmp_path):
    direct = load(_write(tmp_path, "policy.yaml", GOOD)).proxy_configuration
    assert direct.switched_on() == SWITCHES
    assert direct.extra == ()


def test_a_switch_left_out_stays_on_and_one_set_false_is_off(tmp_path):
    text = GOOD + "proxy_configuration:\n  direct:\n    local_subnets: false\n    local_domains: no\n    localhost: true\n"
    direct = load(_write(tmp_path, "policy.yaml", text)).proxy_configuration
    assert direct.switched_on() == ("localhost", "plain_host_names", "policy_server")


def test_the_section_can_be_in_an_included_file_and_extra_keeps_its_order(tmp_path):
    _write(tmp_path, "proxy.yaml", "proxy_configuration:\n  direct:\n    extra:\n      - '*.home.arpa'\n      - 10.8.0.0/16\n      - .lan.example\n")
    direct = load(_write(tmp_path, "policy.yaml", GOOD + "include: [proxy.yaml]\n")).proxy_configuration
    assert [(item.text, item.kind) for item in direct.extra] == [
        ("*.home.arpa", "glob"),
        ("10.8.0.0/16", "subnet"),
        (".lan.example", "domain"),
    ]


def test_every_mistake_in_the_section_is_listed_with_its_place_beside_other_errors(tmp_path):
    text = GOOD + (
        "bogus: 1\n"
        "proxy_configuration:\n"
        "  direct:\n"
        "    localhost: maybe\n"
        "    local_subnets: 0\n"
        "    lan: true\n"
        "    extra:\n"
        "      - 10.8.0.0/33\n"
        "      - http://nas/\n"
        "      - 8080\n"
        "      - nas.example\n"
        "  bypass: []\n"
    )
    path = _write(tmp_path, "policy.yaml", text)
    with pytest.raises(ConfigError) as raised:
        load(path)
    assert raised.value.problems == (
        f"{path}:7:1: unknown setting bogus",
        f"{path}:10:16: proxy_configuration.direct.localhost must be true or false",
        f"{path}:11:20: proxy_configuration.direct.local_subnets must be true or false",
        f"{path}:12:5: unknown setting proxy_configuration.direct.lan",
        f"{path}:14:9: proxy_configuration.direct.extra: '10.8.0.0/33' is not a host name, a host glob, a domain "
        "such as .home.arpa, an IP address, or a subnet such as 10.8.0.0/16",
        f"{path}:15:9: proxy_configuration.direct.extra: 'http://nas/' is not a host name, a host glob, a domain "
        "such as .home.arpa, an IP address, or a subnet such as 10.8.0.0/16",
        f"{path}:16:9: proxy_configuration.direct.extra item must be a string",
        f"{path}:18:3: unknown setting proxy_configuration.bypass",
    )


@pytest.mark.parametrize(
    ("body", "problem"),
    [
        ("proxy_configuration: []\n", "proxy_configuration must be a mapping"),
        ("proxy_configuration:\n  direct: true\n", "proxy_configuration.direct must be a mapping"),
        ("proxy_configuration:\n  direct:\n    extra: '*.lan'\n", "proxy_configuration.direct.extra must be a list"),
    ],
)
def test_a_section_of_the_wrong_shape_is_an_error(tmp_path, body, problem):
    with pytest.raises(ConfigError) as raised:
        load(_write(tmp_path, "policy.yaml", GOOD + body))
    assert len(raised.value.problems) == 1 and problem in raised.value.problems[0]


def test_the_section_written_twice_is_an_error_naming_the_first(tmp_path):
    _write(tmp_path, "more.yaml", "proxy_configuration:\n  direct: {}\n")
    path = _write(tmp_path, "policy.yaml", GOOD + "include: [more.yaml]\nproxy_configuration:\n  direct: {}\n")
    with pytest.raises(ConfigError) as raised:
        load(path)
    assert raised.value.problems == (f"{tmp_path / 'more.yaml'}:2:3: proxy_configuration is already set at {path}:9:3",)


@pytest.fixture
def mounted(tmp_path, monkeypatch):
    config = tmp_path / "etc-daywarden"
    config.mkdir()
    monkeypatch.setattr(check, "CONFIG_MOUNT", str(config))
    monkeypatch.setenv("POLICY_FILE", str(config / "policy.yaml"))
    monkeypatch.setenv("PROXY_CONFIG_PORT", "9088")
    return config


def test_the_summary_names_the_configuration_url_the_switches_on_and_the_extra_items(mounted, capsys):
    _write(mounted, "policy.yaml", GOOD + "proxy_configuration:\n  direct:\n    local_domains: false\n    extra: ['*.home.arpa', 10.8.0.0/16]\n")
    assert check.main([]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "proxy configuration is http://garden:9088/proxy.pac" in lines
    assert "proxy configuration direct entries: localhost, plain_host_names, policy_server, local_subnets" in lines
    assert "proxy configuration extra direct entries: *.home.arpa, 10.8.0.0/16" in lines


def test_the_summary_says_none_when_every_switch_is_off(mounted, capsys):
    switches = "".join(f"    {name}: false\n" for name in SWITCHES)
    _write(mounted, "policy.yaml", GOOD + "proxy_configuration:\n  direct:\n" + switches)
    assert check.main([]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "proxy configuration direct entries: none" in lines
    assert "proxy configuration extra direct entries: none" in lines
