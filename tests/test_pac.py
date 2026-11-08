"""S019: the proxy auto-config file, run the way a browser runs it."""

import ipaddress
import json
import re
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from conftest import needs_node
from policy.pac import SWITCHES, DirectEntries, Server, parse_extra, render, server_names

HARNESS = Path(__file__).resolve().parent / "pac_harness.js"
PROXY = "PROXY garden:8080"
SERVER = Server(
    names=("garden", "tasks.example.org"),
    addresses=tuple(ipaddress.ip_address(text) for text in ("192.0.2.10", "2001:db8::10", "203.0.113.5")),
    subnets=tuple(ipaddress.ip_network(text) for text in ("192.0.2.0/24", "2001:db8::/64", "fe80::/64")),
    search_domains=("bakuna.net",),
)
# Hosts that only one direct entry sends direct.
ONLY = {
    "localhost": ["app.localhost", "127.0.0.9", "::1"],
    "plain_host_names": ["printer"],
    "policy_server": ["tasks.example.org", "203.0.113.5"],
    "local_subnets": ["192.0.2.77", "2001:db8::77"],
    "local_domains": ["nas.bakuna.net"],
}
ELSEWHERE = ["www.example.com", "garden.example.com", "198.51.100.7", "2001:db8:1::7", "fe80::1"]


def run(pac: str, hosts, scheme: str = "https") -> dict[str, str]:
    done = subprocess.run(
        ["node", str(HARNESS)],
        input=json.dumps({"pac": pac, "hosts": list(hosts), "scheme": scheme}),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(done.stdout)


def direct(results: dict[str, str]) -> set[str]:
    return {host for host, answer in results.items() if answer == "DIRECT"}


@needs_node
def test_every_default_entry_goes_direct_and_everything_else_goes_to_the_one_proxy():
    hosts = [host for group in ONLY.values() for host in group] + ["localhost", "garden"] + ELSEWHERE
    results = run(render("garden:8080", DirectEntries(), SERVER), hosts)
    assert direct(results) == {host for host in hosts if host not in ELSEWHERE}
    assert {results[host] for host in ELSEWHERE} == {PROXY}


@needs_node
@pytest.mark.parametrize("scheme", ["http", "ws", "wss"])
def test_every_scheme_is_sent_the_same_way(scheme):
    pac = render("garden:8080", DirectEntries(), SERVER)
    assert run(pac, ["www.example.com", "nas.bakuna.net"], scheme) == {"www.example.com": PROXY, "nas.bakuna.net": "DIRECT"}


@needs_node
@pytest.mark.parametrize("switch", SWITCHES)
def test_each_switch_turned_off_removes_only_its_own_entry(switch):
    hosts = [host for group in ONLY.values() for host in group] + ELSEWHERE
    results = run(render("garden:8080", replace(DirectEntries(), **{switch: False}), SERVER), hosts)
    assert direct(results) == {host for name, group in ONLY.items() if name != switch for host in group}
    assert {results[host] for host in ONLY[switch]} == {PROXY}


@needs_node
def test_localhost_covers_names_under_it_and_the_loopback_addresses():
    pac = render("garden:8080", replace(DirectEntries(), plain_host_names=False), Server())
    hosts = ["localhost", "a.b.localhost", "127.0.0.1", "127.255.0.3", "[::1]", "0:0:0:0:0:0:0:1", "128.0.0.1", "notlocalhost.com"]
    assert direct(run(pac, hosts)) == set(hosts[:6])


@needs_node
def test_a_search_domain_covers_itself_and_every_name_under_it_and_nothing_else():
    pac = render("garden:8080", DirectEntries(), SERVER)
    results = run(pac, ["bakuna.net", "nas.bakuna.net", "a.b.bakuna.net", "notbakuna.net", "bakuna.net.evil.com"])
    assert direct(results) == {"bakuna.net", "nas.bakuna.net", "a.b.bakuna.net"}


@needs_node
def test_case_and_a_trailing_dot_are_ignored():
    pac = render("garden:8080", DirectEntries(), SERVER)
    hosts = ["NAS.Bakuna.NET.", "Tasks.Example.Org.", "APP.LOCALHOST", "WWW.Example.com."]
    assert direct(run(pac, hosts)) == set(hosts[:3])


@needs_node
def test_ipv6_hosts_match_with_or_without_brackets_and_in_any_spelling():
    pac = render("garden:8080", DirectEntries(), SERVER)
    hosts = ["2001:db8::99", "[2001:db8::99]", "2001:0DB8:0000:0000:0000:0000:0000:0099", "2001:db8::10", "::ffff:192.0.2.55"]
    assert direct(run(pac, hosts)) == set(hosts)


@needs_node
def test_link_local_subnets_are_left_out_and_host_names_are_never_looked_up():
    pac = render("garden:8080", replace(DirectEntries(), plain_host_names=False), SERVER)
    results = run(pac, ["fe80::1", "[fe80::2]", "media.lan", "garden.example.com", "printer"])
    assert set(results.values()) == {PROXY}


@needs_node
def test_extra_items_go_direct_even_with_every_switch_off():
    items = ["*.home.arpa", "nas?.example", ".lan.example", "media.example.net", "198.51.100.20", "10.8.0.0/16", "fd00::/8", "2001:db8:5::1"]
    off = DirectEntries(**{name: False for name in SWITCHES}, extra=tuple(parse_extra(item) for item in items))
    hosts = {
        "tv.home.arpa": "DIRECT",
        "home.arpa": PROXY,
        "nas1.example": "DIRECT",
        "nas12.example": PROXY,
        "lan.example": "DIRECT",
        "x.y.lan.example": "DIRECT",
        "media.example.net": "DIRECT",
        "www.media.example.net": PROXY,
        "198.51.100.20": "DIRECT",
        "198.51.100.21": PROXY,
        "10.8.3.4": "DIRECT",
        "10.9.0.1": PROXY,
        "fd12::1": "DIRECT",
        "[2001:db8:5::1]": "DIRECT",
        "localhost": PROXY,
        "printer": PROXY,
        "garden": PROXY,
        "nas.bakuna.net": PROXY,
        "192.0.2.77": PROXY,
    }
    assert run(render("garden:8080", off, SERVER), hosts) == hosts


@needs_node
def test_the_file_names_only_the_proxy_with_no_direct_fallback():
    pac = render("tasks.example:9080", DirectEntries(), SERVER)
    assert set(run(pac, ELSEWHERE).values()) == {"PROXY tasks.example:9080"}


def test_the_file_is_es5():
    pac = render("garden:8080", DirectEntries(extra=(parse_extra("*.home.arpa"),)), SERVER)
    assert not re.search(r"\b(let|const|class)\s|=>|`", pac)


@pytest.mark.parametrize(
    ("text", "kind", "value"),
    [
        ("NAS.Home.Arpa.", "host", "nas.home.arpa"),
        ("*.home.arpa", "glob", "*.home.arpa"),
        ("nas?", "glob", "nas?"),
        (".home.arpa", "domain", "home.arpa"),
        ("10.8.0.1", "address", "10.8.0.1"),
        ("[2001:DB8::1]", "address", "2001:db8::1"),
        ("10.8.0.0/16", "subnet", "10.8.0.0/16"),
        ("2001:db8::/48", "subnet", "2001:db8::/48"),
    ],
)
def test_each_form_of_extra_item_is_recognised(text, kind, value):
    found = parse_extra(text)
    assert (found.kind, found.value) == (kind, value)


@pytest.mark.parametrize("text", ["10.8.0.0/33", "http://nas/", "nas:8080", "10.8.0", "two words", ".", "*/8", "fe80::1/129"])
def test_an_item_that_is_none_of_the_forms_is_refused(text):
    with pytest.raises(ValueError, match="is not a host name, a host glob, a domain"):
        parse_extra(text)


def test_the_server_names_leave_out_loopback_and_keep_listed_addresses_apart():
    names, addresses = server_names("garden, Garden.Bakuna.NET., localhost,127.0.0.1,::1,[2001:db8::10],192.0.2.10", "Tasks.Example", "garden")
    assert names == ["garden", "garden.bakuna.net", "tasks.example"]
    assert addresses == [ipaddress.ip_address("2001:db8::10"), ipaddress.ip_address("192.0.2.10")]
