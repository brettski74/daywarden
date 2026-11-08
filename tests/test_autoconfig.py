"""S019: the auto-configuration service finds the server's network and serves the file."""

import http.client
import ipaddress
import threading
from pathlib import Path

import pytest

from policy import autoconfig, reload
from policy.autoconfig import Holder, Source, control, listen, real_interfaces, search_domains
from policy.hierarchy import load
from policy.pac import CONTENT_TYPE

POLICY = """\
entry: household
rule_sets:
  household:
    - condition: always
      when_true: { action: allow }
"""


class SysNet:
    """A /sys/class/net with each interface a link into devices/, as the kernel lays it out."""

    def __init__(self, root: Path):
        self.root = root
        self.net = root / "class" / "net"
        self.net.mkdir(parents=True)

    def add(self, name: str, *, physical: bool, up: bool = True, lower=(), bridge_ports=()) -> None:
        parent = "pci0000:00/0000:00:1c.0" if physical else "virtual"
        device = self.root / "devices" / parent / "net" / name
        device.mkdir(parents=True)
        (device / "flags").write_text("0x1003\n" if up else "0x1002\n", encoding="ascii")
        (device / "operstate").write_text("up\n" if up else "down\n", encoding="ascii")
        for below in lower:
            (device / f"lower_{below}").symlink_to(self.net / below)
        if bridge_ports:
            (device / "brif").mkdir()
            for port in bridge_ports:
                (device / "brif" / port).symlink_to(self.net / port)
        (self.net / name).symlink_to(Path("..", "..", "devices", parent, "net", name))


@pytest.fixture
def sysnet(tmp_path):
    fake = SysNet(tmp_path / "sys")
    fake.add("lo", physical=False)
    fake.add("enp2s0", physical=True)
    fake.add("enp1s0", physical=True, up=False)
    fake.add("wlan0", physical=True)
    fake.add("eth1", physical=True)
    fake.add("eth2", physical=True)
    fake.add("br0", physical=False, bridge_ports=("eth1",))
    fake.add("bond0", physical=False, lower=("eth2",))
    fake.add("bond0.10", physical=False, lower=("bond0",))
    fake.add("veth1a2b", physical=False)
    fake.add("docker0", physical=False, lower=("veth1a2b",))
    fake.add("br-0123456789ab", physical=False)
    fake.add("virbr0", physical=False)
    fake.add("tun0", physical=False)
    fake.add("tap0", physical=False)
    fake.add("wg0", physical=False)
    fake.add("br9", physical=False, bridge_ports=("tap0",))
    return fake


def test_real_interfaces_are_physical_or_built_on_a_physical_device_and_up(sysnet):
    assert real_interfaces(sysnet.net) == ["bond0", "bond0.10", "br0", "enp2s0", "eth1", "eth2", "wlan0"]


def test_no_sysfs_means_no_real_interfaces(tmp_path):
    assert real_interfaces(tmp_path / "missing") == []


def test_search_domains_come_from_search_and_domain_lines(tmp_path):
    resolv = tmp_path / "resolv.conf"
    resolv.write_text(
        "# search commented.example\nnameserver 192.0.2.1\nsearch Bakuna.NET. home.example # trailing\n"
        "domain office.example\nsearch bakuna.net bad_label$\n",
        encoding="utf-8",
    )
    assert search_domains(resolv) == ("bakuna.net", "home.example", "office.example")
    assert search_domains(tmp_path / "missing") == ()


def _interfaces(table):
    return lambda: {name: [ipaddress.ip_interface(text) for text in texts] for name, texts in table.items()}


class Machine:
    """The server as the service sees it, which a test can change between fetches."""

    def __init__(self, tmp_path: Path, sysnet: SysNet):
        self.resolv = tmp_path / "resolv.conf"
        self.resolv.write_text("search bakuna.net\n", encoding="utf-8")
        self.addresses = {
            "lo": ["127.0.0.1/8"],
            "enp2s0": ["192.168.12.120/24", "fe80::1/64"],
            "docker0": ["172.17.0.1/16"],
            "br0": ["10.20.0.1/24", "2001:db8:20::1/64"],
        }
        self.policy_file = tmp_path / "policy.yaml"
        self.policy_file.write_text(POLICY, encoding="utf-8")
        self.source = Source(
            proxy_port=8080,
            config_port=8088,
            parent_names="garden,garden.bakuna.net,localhost,127.0.0.1",
            sys_net=sysnet.net,
            resolv_conf=self.resolv,
            addresses=lambda: _interfaces(self.addresses)(),
            hostname=lambda: "garden",
        )


@pytest.fixture
def machine(tmp_path, sysnet):
    return Machine(tmp_path, sysnet)


def test_the_server_facts_come_from_its_real_interfaces_names_and_search_domains(machine):
    server = machine.source.server(None)
    assert server.names == ("garden", "garden.bakuna.net")
    assert [str(address) for address in server.addresses] == ["10.20.0.1", "2001:db8:20::1", "192.168.12.120", "fe80::1"]
    assert "10.20.0.0/24" in [str(net) for net in server.subnets]
    assert "172.17.0.0/16" not in [str(net) for net in server.subnets]
    assert server.search_domains == ("bakuna.net",)


class Running:
    def __init__(self, machine: Machine, socket_path: Path):
        self.machine = machine
        self.holder = Holder(load(machine.policy_file, task_data=False))
        self.server = listen(self.holder, machine.source, host="127.0.0.1", port=0)
        self.socket_path = socket_path
        self.controller = control(self.holder, machine.source, machine.policy_file, socket_path)
        for server in (self.server, self.controller):
            threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def get(self, path: str, *, method: str = "GET", host: str | None = None, body: bytes | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        try:
            headers = {} if host is None else {"Host": host}
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, response.getheader("Content-Type"), response.read().decode()
        finally:
            connection.close()

    def pac(self) -> str:
        status, kind, text = self.get("/proxy.pac")
        assert (status, kind) == (200, CONTENT_TYPE)
        return text

    def stop(self) -> None:
        for server in (self.server, self.controller):
            server.shutdown()
            server.server_close()


@pytest.fixture
def running(machine, tmp_path):
    service = Running(machine, tmp_path / "control.sock")
    yield service
    service.stop()


def test_both_paths_serve_the_same_file_whoever_asks_and_any_other_path_is_404(running):
    status, kind, pac = running.get("/proxy.pac")
    assert (status, kind) == (200, CONTENT_TYPE)
    assert "FindProxyForURL" in pac and '"PROXY garden:8080"' in pac
    assert running.get("/wpad.dat") == (200, CONTENT_TYPE, pac)
    assert running.get("/proxy.pac?x=1", host="wpad.bakuna.net") == (200, CONTENT_TYPE, pac)
    assert running.get("http://evil.example/wpad.dat") == (200, CONTENT_TYPE, pac)
    for path in ("/", "/proxy.pac/", "/v1/reload", "/health", "/PROXY.PAC"):
        assert running.get(path)[0] == 404, path


def test_no_request_to_the_port_can_reload_or_change_anything(running):
    before = running.pac()
    running.machine.policy_file.write_text(POLICY + "proxy_configuration:\n  direct:\n    local_domains: false\n", encoding="utf-8")
    for path in ("/proxy.pac", "/v1/reload", "/reload"):
        for method in ("POST", "PUT", "DELETE"):
            assert running.get(path, method=method, body=b"reload")[0] in {404, 501}
    assert running.pac() == before


def test_the_next_fetch_reads_the_network_and_search_domains_again(running):
    before = running.pac()
    assert "bakuna.net" in before and "office.example" not in before
    running.machine.resolv.write_text("search office.example\n", encoding="utf-8")
    running.machine.addresses["enp2s0"] = ["192.168.50.7/24"]
    after = running.pac()
    assert '"office.example"' in after and '"bakuna.net"' not in after
    assert "// 192.168.50.0/24" in after and "// 192.168.12.0/24" not in after


def test_a_server_that_starts_before_its_network_picks_it_up_on_a_later_fetch(running):
    running.machine.resolv.unlink()
    running.machine.addresses = {"lo": ["127.0.0.1/8"]}
    bare = running.pac()
    assert "192.168.12" not in bare and "bakuna.net" not in bare.split("var DIRECT_HOSTS")[1].split(";")[1]
    running.machine.resolv.write_text("search bakuna.net\n", encoding="utf-8")
    running.machine.addresses = {"enp2s0": ["192.168.12.120/24"]}
    later = running.pac()
    assert "// 192.168.12.0/24" in later and 'var DIRECT_DOMAINS = ["localhost", "bakuna.net"]' in later


def test_a_reload_changes_the_next_fetch_and_a_refused_one_leaves_it(running):
    running.machine.policy_file.write_text(
        POLICY + "hostname: tasks.example\nproxy_configuration:\n  direct:\n    local_domains: false\n    extra: ['*.home.arpa']\n",
        encoding="utf-8",
    )
    assert autoconfig.ask("reload", running.socket_path) == {"reloaded": True, "warnings": []}
    reloaded = running.pac()
    assert '"PROXY tasks.example:8080"' in reloaded
    assert 'var DIRECT_DOMAINS = ["localhost"]' in reloaded and 'var DIRECT_GLOBS = ["*.home.arpa"]' in reloaded
    assert autoconfig.ask("url", running.socket_path) == {"url": "http://tasks.example:8088/proxy.pac"}
    running.machine.policy_file.write_text(POLICY + "proxy_configuration:\n  direct:\n    localhost: maybe\n", encoding="utf-8")
    answer = autoconfig.ask("reload", running.socket_path)
    assert answer["reloaded"] is False
    assert answer["errors"] == [f"{running.machine.policy_file}:8:16: proxy_configuration.direct.localhost must be true or false"]
    assert running.pac() == reloaded


def test_the_reload_command_reports_a_refused_autoconfig_reload(running, monkeypatch, capsys):
    monkeypatch.setattr(autoconfig, "CONTROL_SOCKET", running.socket_path)
    monkeypatch.setattr(autoconfig.ask, "__defaults__", (running.socket_path, 60))
    assert reload.main(["--service", "autoconfig"]) == 0
    running.machine.policy_file.write_text(POLICY + "proxy_configuration: []\n", encoding="utf-8")
    assert reload.main(["--service", "autoconfig", "--host-dir", "config"]) == 1
    err = capsys.readouterr().err
    assert "The autoconfig service did not reload and keeps the policy it had." in err
    assert "proxy_configuration must be a mapping" in err


def test_without_a_policy_every_entry_is_on_and_the_machine_hostname_is_used(machine, tmp_path):
    holder = Holder(None)
    server = listen(holder, machine.source, host="127.0.0.1", port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        connection.request("GET", "/wpad.dat")
        pac = connection.getresponse().read().decode()
    finally:
        server.shutdown()
        server.server_close()
    assert '"PROXY garden:8080"' in pac
    assert "Direct entries: localhost, plain_host_names, policy_server, local_subnets, local_domains." in pac


def test_a_port_already_in_use_is_named_and_the_service_exits_1(machine, monkeypatch, capsys):
    holder = Holder(None)
    busy = listen(holder, machine.source, host="", port=0)
    try:
        monkeypatch.setenv("PROXY_CONFIG_PORT", str(busy.server_address[1]))
        monkeypatch.setenv("POLICY_FILE", str(machine.policy_file))
        assert autoconfig.main([]) == 1
    finally:
        busy.server_close()
    assert f"cannot be served on port {busy.server_address[1]}" in capsys.readouterr().out
