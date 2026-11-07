"""A client group address is an IP, written any way, or a DNS name."""

import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy.clients import UnresolvedAddress, normalize_ip, resolve_address  # noqa: E402


class FakeDns:
    def __init__(self, answers: dict[str, list[str]]):
        self.answers = answers
        self.asked: list[str] = []

    def __call__(self, host, port, **_kwargs):
        self.asked.append(host)
        if host not in self.answers:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return [
            (socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))
            for ip in self.answers[host]
        ]


def test_an_ip_address_is_used_without_asking_dns():
    dns = FakeDns({})
    assert resolve_address("192.168.1.40", dns) == ("192.168.1.40",)
    assert resolve_address("fe80::1", dns) == ("fe80::1",)
    assert dns.asked == []


def test_a_dns_name_resolves_to_every_distinct_address():
    dns = FakeDns({"older-child.lan": ["192.168.1.41", "192.168.1.41", "fd00::41", "::ffff:192.168.1.41"]})
    assert resolve_address("older-child.lan", dns) == ("192.168.1.41", "fd00::41")


def test_localhost_resolves_with_the_system_resolver():
    assert set(resolve_address("localhost")) & {"127.0.0.1", "::1"}


def test_an_unknown_name_is_reported_with_the_name():
    with pytest.raises(UnresolvedAddress, match="nowhere.lan"):
        resolve_address("nowhere.lan", FakeDns({}))


def test_an_ipv4_mapped_address_is_the_ipv4_address():
    assert normalize_ip("::ffff:192.168.1.40") == "192.168.1.40"
    assert normalize_ip(" 192.168.1.40 ") == "192.168.1.40"
    assert normalize_ip("FE80::1") == "fe80::1"
    assert normalize_ip("not an ip") is None
