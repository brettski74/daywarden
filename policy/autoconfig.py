"""Serve the proxy auto-config file: python -m policy.autoconfig

GET ``/proxy.pac`` and GET ``/wpad.dat`` return the same file, built by
``policy.pac`` for each fetch. Any other path is 404. Nothing needs a
sign-in, and the answer does not depend on who asks or on the ``Host``
header. Plain HTTP on ``PROXY_CONFIG_PORT``, IPv4 and IPv6.

The service runs with the host's network, so ``/sys/class/net`` and the
interface addresses are the server's own. They are read on every fetch, and
so is the resolver configuration at ``RESOLV_CONF``, so a new address or a
new search domain is in the next fetch without a reload or a restart.

A real interface is a physical one, or a bridge, bond, or VLAN with a
physical device under it. Loopback, Docker and libvirt bridges, ``veth``,
``tun``, ``tap``, and WireGuard interfaces are all virtual and left out, as
is an interface that is down or has no address.

The policy is loaded from ``POLICY_FILE`` at start for its
``proxy_configuration`` section and ``hostname``. ``dw reload`` reloads it
through a Unix socket inside this container, which no request to the HTTP
port can reach, including one forwarded by a reverse proxy on the server.

Run with: python -m policy.autoconfig [--url]
``--url`` asks the running service for the configuration URL and prints it.
"""

from __future__ import annotations

import argparse
import errno
import ipaddress
import json
import os
import re
import signal
import socket
import socketserver
import sys
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from policy.check import load_required
from policy.hierarchy import ConfigError, Policy, load as load_hierarchy, require_yaml
from policy.pac import CONTENT_TYPE, DirectEntries, Server, host_name, render, server_names
from policy.selection import machine_hostname, proxy_config_port, proxy_port

PATHS = frozenset({"/proxy.pac", "/wpad.dat"})
SYS_NET = Path("/sys/class/net")
CONTROL_SOCKET = Path("/tmp/daywarden-autoconfig.sock")
IFF_UP = 0x1
# Docker and libvirt name their bridges so. They are virtual anyway.
_NOT_REAL = re.compile(r"docker\d+|br-[0-9a-f]{12}|virbr\d+(-nic)?|veth.*|lo")

Addresses = Mapping[str, list[ipaddress.IPv4Interface | ipaddress.IPv6Interface]]


def real_interfaces(sys_net: Path = SYS_NET) -> list[str]:
    """Return the names of the real interfaces that are up, sorted."""
    try:
        names = sorted(entry.name for entry in sys_net.iterdir())
    except OSError:
        return []
    return [name for name in names if _up(sys_net / name) and _real(sys_net, name, set())]


def _up(entry: Path) -> bool:
    try:
        flags = int((entry / "flags").read_text(encoding="ascii").strip(), 16)
        state = (entry / "operstate").read_text(encoding="ascii").strip()
    except (OSError, ValueError):
        return False
    return bool(flags & IFF_UP) and state in {"up", "unknown"}


def _real(sys_net: Path, name: str, seen: set[str]) -> bool:
    """True for a physical device, or one with a physical device under it."""
    if name in seen or _NOT_REAL.fullmatch(name):
        return False
    seen.add(name)
    entry = sys_net / name
    if "/devices/virtual/" not in os.path.realpath(entry) + "/":
        return True
    lower = []
    try:
        lower += [child.name[len("lower_") :] for child in entry.iterdir() if child.name.startswith("lower_")]
    except OSError:
        return False
    try:
        lower += [child.name for child in (entry / "brif").iterdir()]
    except OSError:
        pass
    return any(_real(sys_net, below, seen) for below in lower)


def interface_addresses() -> dict[str, list[ipaddress.IPv4Interface | ipaddress.IPv6Interface]]:
    """Return each interface's addresses with their prefix lengths."""
    import psutil

    found: dict[str, list] = {}
    for name, entries in psutil.net_if_addrs().items():
        for entry in entries:
            if entry.family not in (socket.AF_INET, socket.AF_INET6):
                continue
            address = entry.address.split("%", 1)[0]
            try:
                ip = ipaddress.ip_address(address)
                prefix = ip.max_prefixlen
                if entry.netmask:
                    prefix = bin(int(ipaddress.ip_address(entry.netmask.split("/", 1)[0]))).count("1")
                found.setdefault(name, []).append(ipaddress.ip_interface(f"{ip}/{prefix}"))
            except ValueError:
                continue
    return found


def search_domains(resolv_conf: Path) -> tuple[str, ...]:
    """Return the search domains in a resolver configuration, from ``search`` and ``domain`` lines."""
    try:
        text = resolv_conf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()
    found: list[str] = []
    for line in text.splitlines():
        words = line.split()
        if not words or words[0] not in {"search", "domain"}:
            continue
        for word in words[1:]:
            if word.startswith(("#", ";")):
                break
            name = word.lower().rstrip(".")
            if host_name(name) and name not in found:
                found.append(name)
    return tuple(found)


@dataclass
class Source:
    """Where the file's facts about this server come from. Each is read for every fetch."""

    proxy_port: int
    config_port: int
    parent_names: str = ""
    sys_net: Path = SYS_NET
    resolv_conf: Path = Path("/etc/resolv.conf")
    addresses: Callable[[], Addresses] = interface_addresses
    hostname: Callable[[], str | None] = machine_hostname

    def host(self, policy: Policy | None) -> str:
        """The policy's ``hostname``, or this server's own, as the task page redirects use."""
        if policy is not None and policy.hostname:
            return policy.hostname
        return self.hostname() or socket.gethostname().strip() or "localhost"

    def server(self, policy: Policy | None) -> Server:
        found = self.addresses()
        own: list = []
        subnets: list = []
        for name in real_interfaces(self.sys_net):
            for interface in found.get(name, []):
                own.append(interface.ip)
                subnets.append(interface.network)
        machine = self.hostname() or socket.gethostname().strip()
        names, listed = server_names(self.parent_names, None if policy is None else policy.hostname, machine)
        return Server(
            tuple(names),
            tuple(dict.fromkeys([*own, *listed])),
            tuple(dict.fromkeys(subnets)),
            search_domains(self.resolv_conf),
        )

    def pac(self, policy: Policy | None) -> str:
        direct = DirectEntries() if policy is None else policy.proxy_configuration
        return render(f"{self.host(policy)}:{self.proxy_port}", direct, self.server(policy))

    def url(self, policy: Policy | None) -> str:
        return f"http://{self.host(policy)}:{self.config_port}/proxy.pac"


@dataclass
class Holder:
    """The policy in force. A reload swaps it whole."""

    policy: Policy | None
    lock: threading.Lock = field(default_factory=threading.Lock)


class _DualStack(ThreadingHTTPServer):
    address_family = socket.AF_INET6
    daemon_threads = True

    def server_bind(self) -> None:
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


class _IPv4(ThreadingHTTPServer):
    daemon_threads = True


def listen(holder: Holder, source: Source, host: str = "", port: int | None = None) -> ThreadingHTTPServer:
    """Serve the file on ``port``, by default the source's, over IPv4 and IPv6. Not started.

    ``host`` empty is every address. Without IPv6 on the machine, IPv4 only.
    """
    bound = source.config_port if port is None else port

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            self._answer(body=True)

        def do_HEAD(self) -> None:
            self._answer(body=False)

        def _answer(self, body: bool) -> None:
            path = urlsplit(self.path).path
            if path not in PATHS:
                self._send(404, b"not found\n", "text/plain; charset=utf-8", body)
                return
            with holder.lock:
                policy = holder.policy
            try:
                text = source.pac(policy)
            except Exception as exc:  # noqa: BLE001 - one bad fetch must not stop the service
                print(f"the auto-configuration file could not be made: {exc}", flush=True)
                self._send(500, b"error\n", "text/plain; charset=utf-8", body)
                return
            if body:
                print(f"served {path} to {self.client_address[0].removeprefix('::ffff:')}", flush=True)
            self._send(200, text.encode("utf-8"), CONTENT_TYPE, body)

        def _send(self, status: int, payload: bytes, content_type: str, body: bool) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if body:
                self.wfile.write(payload)

        def log_message(self, fmt: str, *args) -> None:
            return

    if socket.has_ipv6 and host in {"", "::"}:
        try:
            return _DualStack(("::", bound), Handler)
        except OSError as error:
            if error.errno == errno.EADDRINUSE:
                raise
    return _IPv4((host or "0.0.0.0", bound), Handler)


def control(holder: Holder, source: Source, policy_file: Path, path: Path = CONTROL_SOCKET) -> socketserver.UnixStreamServer:
    """Answer ``reload`` and ``url`` on a Unix socket at ``path``. Not started.

    The socket is inside this container, so only ``docker compose exec`` reaches it.
    """

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            command = self.rfile.readline(64).decode("ascii", "replace").strip()
            if command == "reload":
                answer = _reload(holder, policy_file)
            elif command == "url":
                with holder.lock:
                    answer = {"url": source.url(holder.policy)}
            else:
                answer = {"error": f"unknown command {command!r}"}
            self.wfile.write(json.dumps(answer).encode() + b"\n")

    path.unlink(missing_ok=True)
    server = socketserver.ThreadingUnixStreamServer(str(path), Handler)
    server.daemon_threads = True
    return server


def _reload(holder: Holder, policy_file: Path) -> dict:
    warnings: list[str] = []
    with holder.lock:
        try:
            holder.policy = load_required(policy_file, holder.policy, warn=warnings.append, task_data=False)
        except ConfigError as error:
            print(f"reload refused: the policy has {len(error.problems)} errors", flush=True)
            return {"reloaded": False, "errors": list(error.problems), "warnings": warnings}
    print(f"reloaded {policy_file}", flush=True)
    return {"reloaded": True, "warnings": warnings}


def ask(command: str, path: Path = CONTROL_SOCKET, timeout: float = 60) -> dict:
    """Send one command to the running service and return its answer."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(path))
        client.sendall(command.encode("ascii") + b"\n")
        with client.makefile("rb") as answer:
            line = answer.readline()
    if not line:
        raise OSError("the auto-configuration service closed the connection without an answer")
    return json.loads(line)


def _load_policy(path: Path) -> Policy | None:
    """Return the household policy, or None when the file is missing."""
    require_yaml(path)
    if not path.is_file():
        print(f"{path} not found; every direct entry is on", flush=True)
        return None
    print(f"loading {path}", flush=True)
    try:
        return load_hierarchy(path, task_data=False)
    except ConfigError as error:
        print(f"the policy has {len(error.problems)} errors", flush=True)
        for problem in error.problems:
            print(problem, flush=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m policy.autoconfig", description="Serve the proxy auto-config file.")
    parser.add_argument("--url", action="store_true", help="print the configuration URL of the running service")
    args = parser.parse_args(argv)
    if args.url:
        try:
            print(ask("url")["url"])
        except (OSError, ValueError, KeyError) as error:
            print(f"the auto-configuration service did not answer: {error}", file=sys.stderr)
            return 1
        return 0
    policy_file = Path(os.environ.get("POLICY_FILE", "/etc/daywarden/policy.yaml"))
    source = Source(
        proxy_port=proxy_port(),
        config_port=proxy_config_port(),
        parent_names=os.environ.get("PARENT_NAMES", ""),
        sys_net=Path(os.environ.get("SYS_NET", str(SYS_NET))),
        resolv_conf=Path(os.environ.get("RESOLV_CONF", "/etc/resolv.conf")),
    )
    holder = Holder(_load_policy(policy_file))
    try:
        server = listen(holder, source)
    except OSError as error:
        print(
            f"the auto-configuration file cannot be served on port {source.config_port}: "
            f"{error.strerror or error}. Is another program using PROXY_CONFIG_PORT?",
            flush=True,
        )
        return 1
    controller = control(holder, source, policy_file)
    threading.Thread(target=controller.serve_forever, daemon=True).start()

    def stop(*_args) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    # Exit 0 on docker stop, so an on-failure restart policy does not start it again at boot.
    signal.signal(signal.SIGTERM, stop)
    print(f"proxy auto-config on port {source.config_port}: {source.url(holder.policy)}", flush=True)
    server.serve_forever()
    server.server_close()
    controller.shutdown()
    controller.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
