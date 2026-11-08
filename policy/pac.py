"""Build the proxy auto-config file that browsers fetch from the auto-configuration service.

The file is plain ES5 JavaScript with one ``FindProxyForURL``. A URL whose
host is in a direct entry gets ``DIRECT``. Every other URL gets the one
proxy, with no ``DIRECT`` fallback, so a proxy outage does not open the
internet to a browser.

The direct entries are switched on and off in the policy's
``proxy_configuration`` section. ``extra`` adds hosts, host globs, domains,
addresses, and subnets of the parent's own. The file never looks up a name:
subnets are tested against IP address URLs with a small parser in the file,
because ``isInNet`` looks names up and ``isInNetEx`` is not in Firefox. Host
matching ignores case and a trailing dot, the same as ``config/bypass.txt``.

None of this changes what the proxy does with a request a browser sends it.
"""

from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass

CONTENT_TYPE = "application/x-ns-proxy-autoconfig"
SWITCHES = ("localhost", "plain_host_names", "policy_server", "local_subnets", "local_domains")
LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})
LINK_LOCAL = ipaddress.ip_network("fe80::/10")

_LABEL = r"[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?"
_HOST = re.compile(rf"{_LABEL}(?:\.{_LABEL})*")
_GLOB = re.compile(r"[a-z0-9_.*?-]+")

Address = ipaddress.IPv4Address | ipaddress.IPv6Address
Network = ipaddress.IPv4Network | ipaddress.IPv6Network


@dataclass(frozen=True)
class Extra:
    """One ``extra`` item: ``text`` as written, its ``kind``, and the ``value`` matched."""

    text: str
    kind: str
    value: str


@dataclass(frozen=True)
class DirectEntries:
    localhost: bool = True
    plain_host_names: bool = True
    policy_server: bool = True
    local_subnets: bool = True
    local_domains: bool = True
    extra: tuple[Extra, ...] = ()

    def switched_on(self) -> tuple[str, ...]:
        return tuple(name for name in SWITCHES if getattr(self, name))


@dataclass(frozen=True)
class Server:
    """What the file needs to know about the policy server, read for each fetch.

    ``names`` are its host names. ``addresses`` are the addresses on its real
    interfaces and any address in ``PARENT_NAMES``. ``subnets`` are the
    subnets of its real interfaces that are up. ``search_domains`` are the
    search domains in its resolver configuration.
    """

    names: tuple[str, ...] = ()
    addresses: tuple[Address, ...] = ()
    subnets: tuple[Network, ...] = ()
    search_domains: tuple[str, ...] = ()


def parse_extra(text: str) -> Extra:
    """Return what one ``extra`` item matches. Raise ValueError when it is none of the forms."""
    raw = text.strip()
    lowered = raw.lower()
    if "/" in lowered:
        try:
            network = ipaddress.ip_network(lowered, strict=False)
        except ValueError:
            pass
        else:
            return Extra(raw, "subnet", str(network))
    else:
        bare = lowered[1:-1] if lowered.startswith("[") and lowered.endswith("]") else lowered
        try:
            return Extra(raw, "address", str(ipaddress.ip_address(bare)))
        except ValueError:
            pass
        name = lowered.rstrip(".") if lowered != "." else lowered
        if name.startswith(".") and host_name(name[1:]):
            return Extra(raw, "domain", name[1:])
        if ("*" in name or "?" in name) and _GLOB.fullmatch(name):
            return Extra(raw, "glob", name)
        if host_name(name):
            return Extra(raw, "host", name)
    raise ValueError(
        f"{raw!r} is not a host name, a host glob, a domain such as .home.arpa, "
        "an IP address, or a subnet such as 10.8.0.0/16"
    )


def host_name(text: str) -> bool:
    """True for a lower-case DNS host name whose last label is not all digits."""
    if not text or len(text) > 253 or _HOST.fullmatch(text) is None:
        return False
    return not text.rsplit(".", 1)[-1].isdigit()


def server_names(parent_names: str | None, *hostnames: str | None) -> tuple[list[str], list[Address]]:
    """Split ``PARENT_NAMES`` and the server's host names into names and addresses.

    The loopback names are left out, as the proxy leaves them out of
    ``PARENT_NAMES``. Names are lower case, without a trailing dot.
    """
    names: list[str] = []
    addresses: list[Address] = []
    for token in [*(parent_names or "").split(","), *(name or "" for name in hostnames)]:
        text = token.strip().strip("[]").lower().rstrip(".")
        if not text or text in LOOPBACK_NAMES:
            continue
        try:
            address = ipaddress.ip_address(text)
        except ValueError:
            if host_name(text) and text not in names:
                names.append(text)
            continue
        if not address.is_loopback and address not in addresses:
            addresses.append(address)
    return names, addresses


def render(proxy: str, direct: DirectEntries, server: Server) -> str:
    """Return the auto-config file that sends every URL outside a direct entry to ``proxy``.

    ``proxy`` is ``host:port``.
    """
    hosts: list[str] = []
    domains: list[str] = []
    globs: list[str] = []
    nets: list[Network] = []
    if direct.localhost:
        domains.append("localhost")
        nets += [ipaddress.ip_network("127.0.0.0/8"), ipaddress.ip_network("::1/128")]
    if direct.policy_server:
        hosts += server.names
        nets += [ipaddress.ip_network(address) for address in server.addresses]
    if direct.local_subnets:
        nets += [subnet for subnet in server.subnets if not _link_local(subnet)]
    if direct.local_domains:
        domains += server.search_domains
    for item in direct.extra:
        if item.kind == "host":
            hosts.append(item.value)
        elif item.kind == "domain":
            domains.append(item.value)
        elif item.kind == "glob":
            globs.append(item.value)
        else:
            nets.append(ipaddress.ip_network(item.value, strict=False))
    on = ", ".join(direct.switched_on()) or "none"
    extra = ", ".join(item.text for item in direct.extra) or "none"
    return _TEMPLATE.format(
        on=on,
        extra=extra,
        proxy=json.dumps(f"PROXY {proxy}"),
        plain="true" if direct.plain_host_names else "false",
        hosts=_array(_unique(hosts)),
        domains=_array(_unique(domains)),
        globs=_array(_unique(globs)),
        nets=_nets(_unique(nets)),
    )


def _link_local(network: Network) -> bool:
    return network.version == 6 and network.subnet_of(LINK_LOCAL)


def _unique(items: Iterable) -> list:
    return list(dict.fromkeys(items))


def _array(items: list[str]) -> str:
    return json.dumps(items)


def _nets(nets: list[Network]) -> str:
    if not nets:
        return "[]"
    rows = [f"  [{json.dumps(list(net.network_address.packed))}, {net.prefixlen}]" for net in nets]
    comments = [f"  // {net}" for net in nets]
    body = ",\n".join(f"{comment}\n{row}" for comment, row in zip(comments, rows, strict=True))
    return "[\n" + body + "\n]"


_TEMPLATE = """\
// Proxy auto-config from daywarden. It is made again for each fetch.
// Direct entries: {on}.
// Extra direct entries: {extra}.
// Every other URL goes to the proxy, with no DIRECT fallback.

var PROXY = {proxy};
var PLAIN_HOST_NAMES_DIRECT = {plain};
var DIRECT_HOSTS = {hosts};
var DIRECT_DOMAINS = {domains};
var DIRECT_GLOBS = {globs};
var DIRECT_NETS = {nets};

function FindProxyForURL(url, host) {{
  var name = String(host).toLowerCase();
  if (name.charAt(0) == "[" && name.charAt(name.length - 1) == "]") {{
    name = name.substring(1, name.length - 1);
  }}
  while (name.length > 1 && name.charAt(name.length - 1) == ".") {{
    name = name.substring(0, name.length - 1);
  }}
  if (daywardenDirect(name)) {{
    return "DIRECT";
  }}
  return PROXY;
}}

function daywardenDirect(name) {{
  var i;
  if (PLAIN_HOST_NAMES_DIRECT && name.indexOf(".") < 0 && name.indexOf(":") < 0) {{
    return true;
  }}
  for (i = 0; i < DIRECT_HOSTS.length; i++) {{
    if (name == DIRECT_HOSTS[i]) {{
      return true;
    }}
  }}
  for (i = 0; i < DIRECT_DOMAINS.length; i++) {{
    if (name == DIRECT_DOMAINS[i] || dnsDomainIs(name, "." + DIRECT_DOMAINS[i])) {{
      return true;
    }}
  }}
  for (i = 0; i < DIRECT_GLOBS.length; i++) {{
    if (shExpMatch(name, DIRECT_GLOBS[i])) {{
      return true;
    }}
  }}
  var address = daywardenAddress(name);
  if (address === null) {{
    return false;
  }}
  for (i = 0; i < DIRECT_NETS.length; i++) {{
    if (daywardenInNet(address, DIRECT_NETS[i][0], DIRECT_NETS[i][1])) {{
      return true;
    }}
  }}
  return false;
}}

// The bytes of an IPv4 or IPv6 address literal, or null for a host name.
// An IPv4-mapped IPv6 address is its IPv4 address.
function daywardenAddress(name) {{
  var bytes = name.indexOf(":") < 0 ? daywardenIPv4(name) : daywardenIPv6(name);
  if (bytes !== null && bytes.length == 16) {{
    var mapped = true;
    for (var i = 0; i < 12; i++) {{
      if (bytes[i] != (i < 10 ? 0 : 255)) {{
        mapped = false;
      }}
    }}
    if (mapped) {{
      return bytes.slice(12);
    }}
  }}
  return bytes;
}}

function daywardenIPv4(text) {{
  var parts = text.split(".");
  if (parts.length != 4) {{
    return null;
  }}
  var bytes = [];
  for (var i = 0; i < 4; i++) {{
    if (!/^[0-9]{{1,3}}$/.test(parts[i])) {{
      return null;
    }}
    var value = parseInt(parts[i], 10);
    if (value > 255) {{
      return null;
    }}
    bytes.push(value);
  }}
  return bytes;
}}

function daywardenIPv6(text) {{
  var zone = text.indexOf("%");
  if (zone >= 0) {{
    text = text.substring(0, zone);
  }}
  var tail = null;
  var last = text.lastIndexOf(":");
  if (text.indexOf(".", last) >= 0) {{
    tail = daywardenIPv4(text.substring(last + 1));
    if (tail === null) {{
      return null;
    }}
    text = text.substring(0, last + 1) + "0:0";
  }}
  var halves = text.split("::");
  if (halves.length > 2) {{
    return null;
  }}
  var groups = halves[0] === "" ? [] : halves[0].split(":");
  if (halves.length == 2) {{
    var rest = halves[1] === "" ? [] : halves[1].split(":");
    var fill = 8 - groups.length - rest.length;
    if (fill < 1) {{
      return null;
    }}
    for (var f = 0; f < fill; f++) {{
      groups.push("0");
    }}
    groups = groups.concat(rest);
  }}
  if (groups.length != 8) {{
    return null;
  }}
  var bytes = [];
  for (var i = 0; i < 8; i++) {{
    if (!/^[0-9a-f]{{1,4}}$/.test(groups[i])) {{
      return null;
    }}
    var value = parseInt(groups[i], 16);
    bytes.push(value >> 8, value & 255);
  }}
  if (tail !== null) {{
    for (var t = 0; t < 4; t++) {{
      bytes[12 + t] = tail[t];
    }}
  }}
  return bytes;
}}

function daywardenInNet(address, network, prefix) {{
  if (address.length != network.length) {{
    return false;
  }}
  for (var i = 0; i < network.length && prefix > 0; i++) {{
    var bits = prefix >= 8 ? 8 : prefix;
    var mask = (255 << (8 - bits)) & 255;
    if ((address[i] & mask) != (network[i] & mask)) {{
      return false;
    }}
    prefix -= bits;
  }}
  return true;
}}
"""
