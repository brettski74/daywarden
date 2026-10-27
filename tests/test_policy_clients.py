"""S001.1: clients are configured by IP or DNS name and stored in SQLite."""

import re
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy import config
from policy.clients import ClientDirectory, UnresolvedAddress, normalize_ip, resolve_address
from policy.store import PolicyStore

TWO_CHILDREN = """
[household]
timezone = "America/Toronto"

[[clients]]
name = "Younger child"
address = "192.168.1.40"

[[clients]]
name = "Older child"
address = "older-child.lan"
"""


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


def _quiet(_message):
    return None


def _names(store: PolicyStore) -> dict[str, tuple[str, ...]]:
    return {client.name: client.ips for client in store.clients()}


def test_an_ip_address_is_used_without_asking_dns():
    dns = FakeDns({})
    assert resolve_address("192.168.1.40", dns) == ("192.168.1.40",)
    assert resolve_address("fe80::1", dns) == ("fe80::1",)
    assert dns.asked == []


def test_a_dns_name_resolves_to_every_distinct_address():
    dns = FakeDns({"older-child.lan": ["192.168.1.41", "192.168.1.41", "fd00::41"]})
    assert resolve_address("older-child.lan", dns) == ("192.168.1.41", "fd00::41")


def test_localhost_resolves_with_the_system_resolver():
    assert set(resolve_address("localhost")) & {"127.0.0.1", "::1"}


def test_an_unknown_name_is_reported():
    with pytest.raises(UnresolvedAddress):
        resolve_address("nowhere.lan", FakeDns({}))


def test_an_ipv4_mapped_address_matches_the_ipv4_client():
    assert normalize_ip("::ffff:192.168.1.40") == "192.168.1.40"
    assert normalize_ip("not an ip") is None


def test_directory_finds_a_client_by_any_of_its_ips():
    dns = FakeDns({"older-child.lan": ["192.168.1.41", "fd00::41"]})
    with PolicyStore(":memory:") as store:
        config.apply(config.parse(TWO_CHILDREN), store, dns, _quiet)
        directory = ClientDirectory(store.clients())
    assert directory.find("192.168.1.40").name == "Younger child"
    assert directory.find("::ffff:192.168.1.40").name == "Younger child"
    assert directory.find("FD00::41").name == "Older child"
    assert directory.find("192.168.1.99") is None
    assert directory.find("garbage") is None


def test_dns_is_asked_when_loading_and_not_when_looking_up():
    dns = FakeDns({"older-child.lan": ["192.168.1.41"]})
    with PolicyStore(":memory:") as store:
        config.apply(config.parse(TWO_CHILDREN), store, dns, _quiet)
        directory = ClientDirectory(store.clients())
    for _ in range(5):
        directory.find("192.168.1.41")
    assert dns.asked == ["older-child.lan"]


def test_timezone_and_clients_survive_reopening_the_database(tmp_path):
    database = tmp_path / "policy.sqlite3"
    dns = FakeDns({"older-child.lan": ["192.168.1.41"]})
    with PolicyStore(database) as store:
        config.apply(config.parse(TWO_CHILDREN), store, dns, _quiet)
    with PolicyStore(database) as reopened:
        assert reopened.timezone() == "America/Toronto"
        assert _names(reopened) == {
            "Younger child": ("192.168.1.40",),
            "Older child": ("192.168.1.41",),
        }


def test_a_missing_timezone_is_stored_as_unset(tmp_path):
    database = tmp_path / "policy.sqlite3"
    with PolicyStore(database) as store:
        config.apply(config.parse(TWO_CHILDREN), store, FakeDns({}), _quiet)
        config.apply(config.parse('[[clients]]\nname = "A"\naddress = "10.0.0.1"\n'), store)
    with PolicyStore(database) as reopened:
        assert reopened.timezone() is None


def test_adding_the_second_child_keeps_the_first_childs_record(tmp_path):
    database = tmp_path / "policy.sqlite3"
    one = '[[clients]]\nname = "Younger child"\naddress = "192.168.1.40"\n'
    with PolicyStore(database) as store:
        config.apply(config.parse(one), store, FakeDns({}), _quiet)
        (younger,) = store.clients()
    with PolicyStore(database) as store:
        config.apply(
            config.parse(TWO_CHILDREN), store, FakeDns({"older-child.lan": ["192.168.1.41"]}), _quiet
        )
        clients = {client.name: client for client in store.clients()}
    assert clients["Younger child"].id == younger.id
    assert clients["Older child"].ips == ("192.168.1.41",)


def test_loading_twice_does_not_duplicate_clients():
    dns = FakeDns({"older-child.lan": ["192.168.1.41"]})
    with PolicyStore(":memory:") as store:
        config.apply(config.parse(TWO_CHILDREN), store, dns, _quiet)
        config.apply(config.parse(TWO_CHILDREN), store, dns, _quiet)
        assert len(store.clients()) == 2


def test_a_client_removed_from_the_file_is_removed_from_the_database():
    one = '[[clients]]\nname = "Younger child"\naddress = "192.168.1.40"\n'
    with PolicyStore(":memory:") as store:
        config.apply(config.parse(TWO_CHILDREN), store, FakeDns({"older-child.lan": ["192.168.1.41"]}), _quiet)
        config.apply(config.parse(one), store, FakeDns({}), _quiet)
        assert _names(store) == {"Younger child": ("192.168.1.40",)}


def test_an_unresolved_name_keeps_the_last_addresses_it_resolved_to():
    warnings = []
    with PolicyStore(":memory:") as store:
        config.apply(config.parse(TWO_CHILDREN), store, FakeDns({"older-child.lan": ["192.168.1.41"]}), _quiet)
        config.apply(config.parse(TWO_CHILDREN), store, FakeDns({}), warnings.append)
        assert _names(store)["Older child"] == ("192.168.1.41",)
    assert any("Older child" in warning and "192.168.1.41" in warning for warning in warnings)


def test_an_unresolved_name_never_seen_before_has_no_ip():
    warnings = []
    with PolicyStore(":memory:") as store:
        config.apply(config.parse(TWO_CHILDREN), store, FakeDns({}), warnings.append)
        assert _names(store)["Older child"] == ()
    assert any("Older child" in warning for warning in warnings)


def test_a_changed_address_that_does_not_resolve_drops_the_old_ips():
    moved = TWO_CHILDREN.replace("older-child.lan", "new-laptop.lan")
    with PolicyStore(":memory:") as store:
        config.apply(config.parse(TWO_CHILDREN), store, FakeDns({"older-child.lan": ["192.168.1.41"]}), _quiet)
        config.apply(config.parse(moved), store, FakeDns({}), _quiet)
        assert _names(store)["Older child"] == ()


def test_two_clients_with_the_same_ip_are_rejected_and_nothing_is_stored():
    clash = TWO_CHILDREN.replace("older-child.lan", "192.168.1.40")
    with PolicyStore(":memory:") as store:
        with pytest.raises(config.ConfigError, match="192.168.1.40"):
            config.apply(config.parse(clash), store, FakeDns({}), _quiet)
        assert store.clients() == []
        assert store.timezone() is None


def test_a_kept_address_now_used_by_another_client_is_dropped():
    warnings = []
    one_name = TWO_CHILDREN.replace('"192.168.1.40"', '"younger-child.lan"')
    with PolicyStore(":memory:") as store:
        config.apply(
            config.parse(one_name),
            store,
            FakeDns({"younger-child.lan": ["192.168.1.40"], "older-child.lan": ["192.168.1.41"]}),
            _quiet,
        )
        config.apply(config.parse(one_name), store, FakeDns({"older-child.lan": ["192.168.1.40"]}), warnings.append)
        assert _names(store) == {"Younger child": (), "Older child": ("192.168.1.40",)}
    assert any("dropping 192.168.1.40" in warning for warning in warnings)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[household]\ntimezone = "Mars/Olympus_Mons"\n', "unknown timezone"),
        ('[household]\ntimezone = ""\n', "IANA"),
        ('[household]\ntz = "UTC"\n', "unknown setting tz"),
        ('bedtime = "19:00"\n', "unknown setting bedtime"),
        ('[[clients]]\naddress = "10.0.0.1"\n', "name is required"),
        ('[[clients]]\nname = "A"\n', "address is required"),
        ('[[clients]]\nname = "A"\naddress = "10.0.0.1"\nip = "x"\n', "unknown setting ip"),
        ('[[clients]]\nname = "A"\naddress = "10.0.0.1"\n[[clients]]\nname = "A"\naddress = "10.0.0.2"\n', "used twice"),
        ('clients = "A"\n', "[[clients]]"),
        ("[household\n", "policy file"),
    ],
)
def test_invalid_configuration_is_rejected(text, message):
    with pytest.raises(config.ConfigError, match=re.escape(message)):
        config.parse(text)
