Ticket: S019
Title: Proxy Configuration URL
Status: Refined
Story Points: 21
Last Updated: 2026-11-08 09:10:00
---

# User Voice

As a parent, I want to have simple and consistent proxy setup for my children's computers. Modern browsers often
support setting up proxy settings automatically. For example, Firefox has options to "Auto-detect proxy settings for
this network" and an "Automatic proxy configuration URL". We should support one or both of these methods. I suspect
that the auto-detection is probably using the DHCP server or something. If so, that's probably not applicable. I think
the latter option - "Automatic proxy configuration URL" - is probably the primary mechanism we should focus on.

I haven't looked into other browsers, since Firefox is our primary browser of choice, but we should try to support
Chromium based browsers like Chrome and Edge if possible. I'm hoping there is a standard format for the configuration
data returned from these automatic proxy configuration URLs that will be understood by most major browsers including
all of the ones mentioned above.

The system should make such a URL endpoint available. By default, it should:

- configure the browser to use this proxy for both HTTP and HTTPS requests and any other protocols we can support at
  the time.
- Bypass the proxy for:
  - localhost
  - `<local>` urls
  - the proxy/policy server itself, both by all IP addresses and all hostnames it is known by - the PARENT_NAMES
    environment variable might be sufficient for this.
  - all local subnets, defined as by the IP address and net mask of all *real* network interfaces that are UP and have
    an IP address associated with them. Virtual IPs or IPs associated with container networks or loopback or anything
    else that doesn't actually provide connectivity to other hosts can be ignored.
  - all local domains, based on the search domains specified in the resolver configuration. So if the search domains
    include mydomain.net and mydomain.org, then we add .mydomain.net and .mydomain.org to the proxy bypass list in our
    response to the browser.

Each of the line items above should be able to be toggled on or off in the configuration somehow. By default they
should all be on, so the toggle exists to allow administrators to exclude items that they don't want included in the
bypass list. We should also provide an option somewhere for a list of additional proxy bypass patterns to be able to be
specified. To be clear, this is **not** the list in config/bypass.txt. That list is a list of hosts that when sent to
the proxy server bypass policy and the proxy server should pass without any further scrutiny or rule processing. The
bypass list being discussed in this story is the set of hosts or IP addresses that the browser should never send to the
proxy server in the first place and should just connect to directly.

Auto-detection should be documented, so I can set it up with DNS and a reverse proxy outside daywarden if I want it,
but daywarden should not listen on port 80, because that needs root privileges. With another port to publish, I also
want the ports to come from one `PORT_BASE`: the proxy on `PORT_BASE`, the policy pages on `PORT_BASE+4`, and the
auto-configuration file on `PORT_BASE+8`. One daywarden should fit in a block of 10 ports, such as 8080 to 8089, so that
a later environment on the same host could start at the next block. Running several environments on one host is not
part of this story.

# Use Cases

## UC1 - Set up a child's Firefox once

- The parent opens Firefox's Network Settings on a child's computer, chooses "Automatic proxy configuration URL", and
  enters `http://garden:8088/proxy.pac`.
- Every web page then goes through the proxy, the same as with today's manual settings, and a blocked site still
  redirects to the task pages.
- The task pages, the usage page, printers, and other machines on the household LAN are opened directly, without the
  proxy.

## UC2 - Set up Chromium, Chrome, or Edge

- On the Arch machines, the parent puts `--proxy-pac-url=http://garden:8088/proxy.pac` in
  `~/.config/chromium-flags.conf`.
- On a Windows machine, the parent sets the same address as the setup script in Windows' proxy settings, which Chrome
  and Edge use.
- Both behave as Firefox does in UC1.

## UC3 - Keep a LAN site under the policy

- The household runs a media server on the LAN, and the parent wants bedtime and quotas to apply to it.
- The parent turns off `local_subnets` and `local_domains` in `proxy_configuration` and runs `dw reload`.
- After the browser fetches the file again, the media server goes through the proxy, and the policy decides it. The
  other default entries still go direct.

## UC4 - Add extra direct entries

- The household has a second LAN domain that is not a search domain, and a VPN subnet the children may reach.
- The parent adds `*.home.arpa` and `10.8.0.0/16` to `extra` in `proxy_configuration` and runs `dw reload`.
- Those hosts go direct. Nothing is added to `config/bypass.txt`, and the proxy does not treat them differently if a
  browser sends them anyway.

## UC5 - The server's network changes

- The server gets a new DHCP lease on a different subnet, or it boots before its network is up.
- The next fetch of the file uses the server's current interfaces and search domains. No `dw reload` or `dw restart`
  is needed.

## UC6 - Move every port at once

- Port 8080 is already used by something else on the server. The parent sets `PORT_BASE=9080` in `.env` and runs
  `dw restart`.
- The proxy moves to 9080, the policy pages to 9084, and the auto-configuration file to 9088. The file names the new
  proxy port, and the task page redirects use the new policy port.
- The one existing install sets `PROXY_PORT=8080` and `POLICY_PORT=8090` in its `.env`. The parent deletes those two
  lines and runs `dw restart`, and the policy pages move to 8084.

## UC7 - Auto-detect

- The parent follows the documentation: a `wpad` DNS host override in OPNsense, and a reverse proxy on port 80 that
  forwards `/wpad.dat` to the auto-configuration port.
- Firefox with "Auto-detect proxy settings for this network" then behaves as in UC1, with nothing typed on the child's
  computer except that choice.

# Acceptance Criteria

## The configuration file

- [ ] `http://<server>:<PROXY_CONFIG_PORT>/proxy.pac` and `http://<server>:<PROXY_CONFIG_PORT>/wpad.dat` return the
  same proxy auto-config file, with content type `application/x-ns-proxy-autoconfig`. Any other path returns 404.
- [ ] The file is served over plain HTTP, needs no sign-in, and is returned to any computer that can reach the port,
  including one in no client group. Its content does not depend on who asks or on the `Host` header.
- [ ] Every URL that is not in a direct entry gets `PROXY <hostname>:<PROXY_PORT>`, where `<hostname>` is the policy's
  `hostname`, or the server's own hostname when that is left out. The same rule as the task page redirects. That
  covers `http`, `https`, `ws`, and `wss` URLs.
- [ ] The file has no `DIRECT` fallback after the proxy. It names one proxy and nothing else for every URL that is
  not a direct entry. What a browser does when it cannot fetch the file at all is described under "What a browser does
  when the file cannot be fetched" in the notes. This criterion does not cover it.
- [ ] A host that looks local but is not in any direct entry goes through the proxy, such as `garden.example.com` when
  `example.com` is not a search domain, or a host name that resolves to a LAN address but is not under a local domain.
- [ ] The file is ES5 JavaScript using only the standard PAC functions, so Firefox, Chromium, Chrome, and Edge all
  read it.

## Firefox and Chromium

- [ ] Firefox with "Automatic proxy configuration URL" set to `/proxy.pac`: an `https` page appears in
  `docker compose logs decisions`, a site the policy denies is denied, and a site the policy redirects goes to the
  task picker.
- [ ] From that Firefox, the task picker and a quiz open directly, without the proxy, and the quiz is for the child's
  client group. The usage page opens directly too.
- [ ] Chromium started with `--proxy-pac-url=http://<server>:<PROXY_CONFIG_PORT>/proxy.pac` behaves the same as
  Firefox in the two cases above.
- [ ] With Firefox and Chromium open and browsing through the proxy, run `dw restart`. Once it prints
  `daywarden restarted.`, the next page each browser loads goes through the proxy and appears in
  `docker compose logs decisions`, without restarting the browser or reloading its proxy settings.

## Direct entries

- [ ] `localhost`: `localhost`, any name ending in `.localhost`, `127.0.0.0/8`, and `::1` go direct.
- [ ] `plain_host_names`: a host name with no dot goes direct, such as `printer` or `garden`. This is Firefox's
  `<local>`.
- [ ] `policy_server`: every name in `PARENT_NAMES` except `localhost`, `127.0.0.1`, and `::1`, the policy `hostname`,
  the server's own hostname, and every address on the server's real interfaces go direct.
- [ ] `local_subnets`: an IP address URL inside the subnet of any real interface that is up and has an address goes
  direct, with the subnet taken from that interface's address and prefix length. Host names are not looked up for
  this entry.
- [ ] A real interface is a physical network interface, or a bridge, bond, or VLAN built on one. Loopback, Docker
  bridges (`docker0`, `br-*`), `veth` interfaces, libvirt bridges, and `tun`, `tap`, and WireGuard interfaces are not
  real interfaces. Interfaces that are down or have no address are left out.
- [ ] IPv4 and IPv6 subnets are both covered. An IPv6 link-local subnet, `fe80::/10`, is left out. An IPv6 URL host
  matches with or without its square brackets.
- [ ] `local_domains`: for each search domain in the server's resolver configuration, the domain itself and every name
  under it go direct. With `search bakuna.net`, `bakuna.net`, `nas.bakuna.net`, and `a.b.bakuna.net` go direct, and
  `notbakuna.net` does not.
- [ ] Host matching ignores case and a trailing dot, the same as `config/bypass.txt`.
- [ ] The interfaces, their addresses, and the search domains are read each time the file is fetched. A new address or
  search domain on the server appears in the next fetch without `dw reload` or `dw restart`.
- [ ] When daywarden starts at boot before the server's network is up, the file fetched after the network comes up
  includes its subnets and search domains.

## proxy_configuration in the policy

- [ ] `config/policy.yaml` accepts an optional `proxy_configuration` section with a `direct` mapping. It holds the
  switches `localhost`, `plain_host_names`, `policy_server`, `local_subnets`, and `local_domains`, and an `extra` list.
  It can be in an included file.
- [ ] With the section, or any switch, left out, every switch is on and `extra` is empty.
- [ ] Each switch set to `false` removes only that entry from the file. Every other entry stays the same.
- [ ] Each `extra` item is one of: a host name, a host glob with `*` and `?` as in `config/bypass.txt`, a domain
  written with a leading dot that matches the domain and every name under it, an IPv4 or IPv6 address, or an IPv4 or
  IPv6 subnet in CIDR form. Each goes direct. `extra` items are added even when every switch is off.
- [ ] `dw check` reports each mistake in the section, each with its file and line, alongside any other errors in the
  policy: an unknown key, a switch that is not `true` or `false`, and an `extra` item that is none of the forms above,
  such as `10.8.0.0/33` or `http://nas/`.
- [ ] The summary that `dw check` and `dw reload` print includes the configuration URL, which direct entries are on,
  and the `extra` items.
- [ ] After `dw reload`, the next fetch of the file uses the reloaded section, and no container restarts. A refused
  reload leaves the file as it was.
- [ ] `config/bypass.txt` does not change the file, and `extra` does not change what the proxy forwards without a
  decision.

## The auto-configuration service

- [ ] `dw up` starts the auto-configuration service with the others and waits until it is healthy. `dw status` lists
  it. `dw down` stops it. `dw restart` replaces it. Starting at boot starts it.
- [ ] `dw up` and `dw status` print the configuration URL, `http://<hostname>:<PROXY_CONFIG_PORT>/proxy.pac`.
- [ ] When `PROXY_CONFIG_PORT` is already in use on the server, `dw up` names the auto-configuration service as not
  healthy and shows why, as it does for the other services.
- [ ] With the auto-configuration service stopped, the proxy and the policy pages keep working. A running browser that
  already has the file keeps using it until something makes it fetch the file again.
- [ ] A request to the auto-configuration port cannot trigger a reload or change anything, including a request that
  reaches it through a reverse proxy on the server.
- [ ] `make up` and `make down` start and stop the auto-configuration service as `dw up` and `dw down` do.

## Ports

- [ ] `.env` has `PORT_BASE`, which is 8080 when it is left out. `PROXY_PORT` is `PORT_BASE`, `POLICY_PORT` is
  `PORT_BASE+4`, and `PROXY_CONFIG_PORT` is `PORT_BASE+8`. With the defaults, every port daywarden publishes on the
  server is in 8080 to 8089.
- [ ] Each of the three ports can still be set on its own in `.env` or the environment, and that value wins over the one
  worked out from `PORT_BASE`.
- [ ] An upgrade with `install.sh` does not add, remove, or change port settings in an existing `.env`. After deleting
  `PROXY_PORT` and `POLICY_PORT` from it and running `dw restart`, the proxy is on `PORT_BASE`, the policy pages on
  `PORT_BASE+4`, and the auto-configuration file on `PORT_BASE+8`.
- [ ] A bare `docker compose up`, without `dw` or `make`, publishes the policy pages on 8084, the same as `dw up` with
  the defaults.
- [ ] `dw up`, `dw restart`, `make up`, and the start at boot all publish the same ports from the same `.env`.
- [ ] A `PORT_BASE` that is not a whole number, or that puts a port above 65535, and two of the three ports set to the
  same number, are refused by `dw up` and `dw restart` with a message naming the setting. Nothing starts or stops.
- [ ] Changing `PORT_BASE` and running `dw reload` warns that `dw restart` is needed and names the services. After
  `dw restart`, the proxy, the file, and the policy pages are on the new ports. The file names the new proxy port, and
  task page redirects use the new policy port.
- [ ] `install.sh` warns about each of the three ports that another program is already using, using `PORT_BASE` the
  same way `dw` does. A new install's `.env` sets `PORT_BASE` and not the three ports.

## Documentation

- [ ] `docs/child-computer.md` shows how to set the configuration URL in Firefox, in Arch's Chromium, and in Windows
  for Chrome and Edge. It keeps the manual settings as an alternative, and says how to make a browser fetch the file
  again after a change, such as restarting Firefox or pressing Reload in its Connection Settings.
- [ ] `docs/child-computer.md` says when each browser fetches the file, and what happens when the fetch fails: both
  go direct, Firefox retries within 5 minutes, and Chromium's retries back off to every 4 hours. It also says that
  Chromium always connects directly to `localhost` and link-local addresses, whatever the file says.
- [ ] `docs/child-computer.md` describes optional browser policies for a managed child computer, without any tool to
  deploy them. For Firefox, a `policies.json` `Proxy` policy with `"Mode": "autoConfig"`, the `AutoConfigURL`, and
  `"Locked": true`, and the `Preferences` for `network.proxy.autoconfig_retry_interval_min` and
  `network.proxy.autoconfig_retry_interval_max`. For Chromium, a managed policy file with `ProxySettings` set to
  `"ProxyMode": "pac_script"`, the `ProxyPacUrl`, and `"ProxyPacMandatory": true`. It says what each one changes, and
  that Chromium's retry and failed-proxy timings cannot be changed.
- [ ] The documentation describes auto-detection without daywarden listening on port 80. It covers a `wpad` DNS host
  override in OPNsense that points at a reverse proxy, a sample reverse proxy setting that forwards
  `http://wpad.<domain>/wpad.dat` to `PROXY_CONFIG_PORT`, the Firefox and Chromium auto-detect settings, and DHCP
  option 252 as the Windows alternative that needs no port 80.
- [ ] `README.md` describes `PORT_BASE` and `PROXY_CONFIG_PORT` in the `.env` table and the `proxy_configuration`
  section, and explains the difference between direct entries and `config/bypass.txt`.
- [ ] The documentation warns that a direct entry takes a LAN site outside the policy, and that the firewall rule in
  `docs/child-computer.md` is still what stops a child going direct to the internet.

# Notes

## Proposed design

**The file.** A function builds the PAC text from the proxy host and port, the switches and `extra` items, the server's
names, its interface addresses and subnets, and its search domains. It is plain ES5 using only `isPlainHostName`,
`dnsDomainIs`, `shExpMatch`, and string tests. Subnets are tested with a small helper in the file that parses IPv4 and
IPv6 literals and compares prefixes, so no host name is ever looked up. `isInNet` would look up names, and
`isInNetEx` is not in Firefox. Tests evaluate the generated file with `node`, with the standard PAC functions defined
in a small harness, and assert the result for each kind of host. Those tests are skipped without `node`, as the page
tests are.

**The service.** A new `autoconfig` service runs the policy image with `python -m policy.autoconfig` and
`network_mode: host`, so it sees the server's real interfaces and binds `PROXY_CONFIG_PORT` directly. It does not need
the compose network. It loads the policy the way the observations service does, and keeps it in a holder that a
reload swaps.

- Interfaces come from `/sys/class/net`, which shows the host's interfaces in a host-network container. An interface
  is physical when its sysfs device path is not under `/devices/virtual`. A bridge, bond, or VLAN counts when one of its
  lower devices is physical. Addresses and prefix lengths come from netlink, `/proc/net/if_inet6`, or a pinned
  `psutil`. Whichever is chosen goes in `policy/requirements.txt`.
- The search domains have to be read live from the host. A single-file bind mount of `/etc/resolv.conf` would go stale,
  because NetworkManager and systemd-resolved replace the file rather than edit it. The container's own copy from
  Docker is made once at creation. Mount the directories that hold it read-only, following a `resolv.conf` symlink into
  `/run/systemd/resolve` or `/run/NetworkManager` where the host uses one. Do not mount `/run` whole, because it holds
  the Docker socket.
- The server's hostname comes from `/etc/hostname`, mounted as the decisions service mounts it.

**Reload.** `dw reload` reloads the auto-configuration service after decisions and observations. The S016 loopback
check is not enough here, because with host networking the service's loopback is the host's, and a reverse proxy on
the server forwarding `/wpad.dat` would reach it from `127.0.0.1`. Use a trigger that the PAC port cannot reach, such
as a Unix socket inside the container that `docker compose exec` can use.

**Ports.** Compose cannot add numbers. `dw_prepare` in `daywarden-lib.sh` works out the three ports after loading
`.env` and exports them, so `docker compose`, including `config --hash` for the reload warning, sees them. The
Makefile's `make up` and `install.sh`'s port check use the same function. The compose file's defaults move to the
8080-based block, so a bare `docker compose up` still runs with the default ports. The policy port default of 8090
changes to 8084 in `docker-compose.yml` (both `${POLICY_PORT:-8090}`), `DEFAULT_PUBLISHED_PORT` in
`policy/selection.py`, and the fallback in `install.sh`'s port check. The ports inside the containers do not change.
The plain HTTP decision API stays on 8090, HTTPS stays bound on 8443, and observations stays on 8091. Those are not
host ports, so they do not use the block. The proxy's `DECISION_URL`, the health checks, and the reload client are
unaffected. The examples in `README.md` and `docs/hierarchical-policy.md` that show `https://garden:8090/...` change to
8084.

**Direct connections to the policy server.** With `policy_server` on, the task pages are reached directly, not
through the proxy, so the decisions service classifies the child from the connection, as `_client_address` already
allows. Docker's port publishing keeps the client's IPv4 address. If a child reaches the server over IPv6 and Docker
has no IPv6 NAT, the userland proxy hides the address. The Firefox acceptance case checks that the quiz is for the
child's group.

## What a browser does when the file cannot be fetched

A browser downloads the file, keeps it in memory, and runs `FindProxyForURL` for every request. Neither browser keeps
it between runs.

- **When it is fetched.** Firefox fetches it at start, when its proxy settings change, when Reload is pressed in
  Connection Settings, and 2 seconds after a network change on the child's computer. It never fetches a working file
  again on a timer. Chromium fetches it in the same cases, and also about 12 hours after a good fetch, once the browser
  is used again. Neither uses the HTTP cache for it. A failed connection to the proxy does not make either fetch it
  again.
- **When the fetch fails.** Both browsers go direct for every request. That includes a browser started while
  daywarden is down, and a fetch after a network change that fails. Firefox retries after 5 seconds, doubling up to 5
  minutes, and then every 5 minutes (`network.proxy.autoconfig_retry_interval_min` and `_max`). Chromium retries after
  8 seconds, 32 seconds, and 2 minutes, then every 4 hours. Chromium can be told the file is mandatory with the
  `ProxyPacMandatory` policy, so requests fail instead of going direct. That does not shorten its retries. Firefox has
  no equivalent. `network.proxy.failover_direct` only covers Firefox's own internal requests.
- **When the proxy is down.** The file names one proxy with no `DIRECT`. Firefox shows a proxy error, and Chromium
  fails the request with `ERR_PROXY_CONNECTION_FAILED`. Both remember a failed proxy, Chromium for 5 minutes and
  Firefox for `network.proxy.failover_timeout`, which defaults to 30 minutes. Neither stops using it while it is the
  only proxy in the list. Firefox tries every proxy again when all of them have failed
  (`network.proxy.retry_failed_proxies`, which defaults to true). Chromium moves a failed proxy to the end of the list
  rather than removing it. The `dw restart` acceptance criterion checks this.
- **Hosts Chromium never proxies.** Chromium always connects directly to `localhost` and link-local addresses, whatever
  the file says. Turning `localhost` off cannot route those through the proxy in Chromium.

The household firewall rule is what makes going direct safe. The children's computers have no direct path to the
internet, so a browser that goes direct loses internet sites and keeps LAN sites. In the worst case, that is an
outage of up to 5 minutes in Firefox or up to 4 hours in Chromium, not a way around daywarden.

Sources are the [Chromium proxy documentation](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/net/docs/proxy.md),
Firefox's `nsProtocolProxyService.cpp` and `StaticPrefList_network.h`, and
[Mozilla bug 1779005](https://bugzilla.mozilla.org/show_bug.cgi?id=1779005). The real browser checks in this story
confirm the parts daywarden depends on.

## Out of scope

- Listening on port 80, and running a reverse proxy or DNS for WPAD. Both are documented setup outside daywarden.
- Serving the file over HTTPS.
- Deploying browser policies to the child computers. They are documented only.
- Changing how browsers retry a failed fetch, or how long they remember a failed proxy. Those are browser behaviour.
- Sending the browser to a SOCKS proxy, or any proxy mode other than mitmproxy's regular HTTP proxy.
- A `dw check` warning for a site group whose hosts would go direct. The check runs in the decisions container, which
  cannot see the server's interfaces or search domains. The documentation warning covers it for now.
- Changing what the proxy forwards without a decision. `config/bypass.txt` and `PARENT_NAMES` keep their current
  meaning.

## Decided in refinement

- The file is served by a new host-network service over plain HTTP on its own port, and reads the interfaces and
  search domains live, rather than from the HTTPS policy port with a snapshot taken by `dw`.
- The switches and the extra list live in a `proxy_configuration` section of the policy, checked by `dw check` and
  applied by `dw reload`.
- Auto-detection is documented, not delivered. daywarden serves `/wpad.dat` with the same content as `/proxy.pac`, and
  does not listen on port 80. A reverse proxy on port 80 and a DNS override do the rest.
- Ports come from `PORT_BASE`, default 8080: the proxy at `+0`, the policy pages at `+4`, and the auto-configuration
  file at `+8`. One environment fits in a block of 10 host ports. Running several environments on one host is longer
  term thinking, not part of this story.
- No migration code for the old 8090 default. There is one production install, nothing is bookmarked yet, and it
  moves to 8084 by hand. `install.sh` leaves the ports in an existing `.env` alone.
- The file has no `DIRECT` fallback, so a proxy outage does not open the internet to a browser on a network without
  the firewall rule. A file that cannot be fetched still makes both browsers go direct, and only the firewall rule or
  Chromium's `ProxyPacMandatory` stops that.
- Browser policies for the child computers, such as Firefox's `policies.json` and Chromium's managed policy file, are
  documented. Deploying them, for example with Ansible, is not part of this story.
- `local_subnets` applies to IP address URLs only. Host names are covered by `local_domains`, `plain_host_names`, and
  `extra`, so the file never looks up a name.

## Sizing

21 points. The parts are:

- About 6 for the file: the direct entries, interface and search domain discovery with the "real interface" rule,
  IPv4 and IPv6 matching in ES5, and the `node` tests over each kind of host.
- About 5 for the service: the host-network compose service, its health check, the `dw` commands, the boot start,
  `make`, the reload trigger, and Compose-backed tests.
- About 2 for the `proxy_configuration` section: loading, collected errors, the summary, and reload.
- About 3 for `PORT_BASE`: `dw`, `make`, `install.sh`, the new-install `.env`, the 8084 default, and the
  host-fake tests.
- About 2 for the documentation and the real Firefox and Chromium checks.

The parts add up to about 18, which rounds up to 21. The design depends on the host's network setup, which carries
some risk. The story has 48 acceptance criteria, which is near the guide of about 50. `PORT_BASE` could be split out as
a 3-point story. It was kept here because the new port is what prompts it, and they share the `dw` and `install.sh`
tests.
