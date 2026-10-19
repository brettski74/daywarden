# Child computer

Both children's computers run Arch Linux. This note is for those machines. The proxy runs on the machine that runs Docker Compose, a separate computer from these two.

## Certificate

Copy `mitmproxy-ca-cert.pem` off the proxy machine. With the `.env` shipped here, that file is:

```text
data/ca/mitmproxy-ca-cert.pem
```

The name stays `mitmproxy-ca-cert.pem` when `CA_VOLUME_PATH` changes. Leave `mitmproxy-ca.pem` where it is. That file also holds the private key.

On the child computer, install the PEM with the system trust tools. Either:

```sh
sudo trust anchor mitmproxy-ca-cert.pem
```

or copy it to `/etc/ca-certificates/trust-source/anchors/mitmproxy-ca-cert.pem` and then run:

```sh
sudo update-ca-trust
```

## Proxy

The proxy is an explicit HTTP proxy. The proxy host is the machine running Compose. The proxy port is `PROXY_PORT` in that machine's `.env`. The file shipped here sets it to `8080`.

## Browser

Firefox is the browser these computers use. Chromium is set up as well. Both need the proxy host and `PROXY_PORT` from the section above.

### Firefox

Firefox keeps its own certificate store and does not use the system store unless `security.enterprise_roots.enabled` is turned on.

After the PEM is in the system trust store, turn that preference on. Open `about:config`, search for `security.enterprise_roots.enabled`, and set it to true. Quit Firefox and start it again.

If that preference stays off, import `mitmproxy-ca-cert.pem` instead. Open Settings, then Privacy & Security, then Certificates, then View Certificates, then Authorities, then Import. Trust the certificate to identify websites.

Point Firefox at the proxy from Settings, then General, then Network Settings, then Settings. Choose Manual proxy configuration. Set the HTTP proxy to the proxy host and `PROXY_PORT`, and tick "Also use this proxy for HTTPS". Leave the SOCKS fields empty.

### Chromium

Chromium uses the system trust store, so the certificate above is the one it trusts. No extra certificate step.

Arch's Chromium reads `~/.config/chromium-flags.conf`. One line points it at the proxy. Fill in the proxy host and `PROXY_PORT`:

```text
--proxy-server=http://proxy-host:8080
```

Quit Chromium and start it again so it reads that file.

## What the proxy cannot see

The household firewall is OPNsense. For the younger child's reserved IP, that box is responsible for three jobs:

- the DHCP reservation
- no direct path to the internet
- UDP/443 blocked, so QUIC cannot bypass the proxy

IPv6 for that host needs the same treatment when the LAN has IPv6, because an IPv4 reservation does not pin the host's IPv6 address.

An OPNsense schedule is the wrong tool for bedtime: a schedule can only pass or block, and it cannot send him to a quiz.

A VPN, a phone hotspot, or IPv6 that does not use the proxy also bypasses the system.

Applications which pin certificates will not work through the intercepting proxy. The intended client is a normal browser.

## Check

Open an `https` page in Firefox, or in Chromium. On the proxy machine, `docker compose logs decisions` shows that page's absolute URL, path included. A certificate warning means Firefox is still using its own store with the preference off and the PEM not imported, or the PEM is not in the system trust store. A page that never appears in that log is not using the proxy.

# OPNsense rule tips

These are the attributes for the rule that blocks a direct path to the internet, so the alias has to use the proxy. They are field values, not a click-through of the UI.

- Group the machines in a Firewall Alias. That alias is the set of hosts forced through the proxy.
- Source and Destination match the IP addresses in the IP packet. They are independent of the route the packet would take through the firewall. Set Source to the alias. Set Destination to any.
- `Interface (rule)` is the interface the matching traffic passes through. On a household LAN, set it to that LAN interface and no other. A more exotic layout is outside these tips.
- Direction is relative to the interfaces listed in `Interface (rule)`. The traffic to block arrives at that interface from another machine, so Direction is `In`.
- Protocol and port can be any, or left blank.
- Version can be IPv4, or any, depending on whether the LAN uses IPv6. Most networks use IPv4. A LAN that already uses IPv6 is outside these tips. The setup note still says that host's IPv6 needs the same treatment when the LAN has IPv6, because an IPv4 reservation does not pin the IPv6 address.