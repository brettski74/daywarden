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

The proxy is an explicit HTTP proxy. The proxy host is the machine running Compose. The proxy port is `PROXY_PORT`, which is `PORT_BASE` in that machine's `.env`, `8080` by default.

The simplest setup gives each browser one address, the configuration URL, and lets it fetch the rest:

```text
http://garden:8088/proxy.pac
```

The port is `PROXY_CONFIG_PORT`, `PORT_BASE+8`, `8088` by default. `dw up` and `dw status` print the URL for this machine. The same file is also served as `/wpad.dat`, for auto-detection below. It is plain HTTP and needs no sign-in.

The file tells the browser to send every URL to the proxy, `http`, `https`, `ws`, and `wss` alike, except these direct entries, which the browser opens itself:

- `localhost`: `localhost`, any name ending in `.localhost`, `127.0.0.0/8`, and `::1`.
- `plain_host_names`: a host name with no dot, such as `printer` or `garden`. This is Firefox's `<local>`.
- `policy_server`: the names in `PARENT_NAMES` other than the loopback ones, the policy's `hostname`, this machine's hostname, and every address on this machine's real network interfaces. The task pages and the usage page open this way.
- `local_subnets`: an IP address URL inside the subnet of any of this machine's real interfaces that is up. A host name is never looked up for this entry.
- `local_domains`: each search domain in this machine's resolver configuration, and every name under it.

A real interface is a physical network interface, or a bridge, bond, or VLAN built on one. Docker and libvirt bridges, `veth`, `tun`, `tap`, and WireGuard interfaces are not. The interfaces and the search domains are read each time a browser fetches the file, so a new address or a new DHCP lease is in the next fetch without `dw reload`. The `proxy_configuration` section of `config/policy.yaml` turns each entry off and adds more. See [the README](../README.md#direct-entries-and-bypasstxt).

The file has no `DIRECT` fallback. When the proxy is down, the browser shows a proxy error rather than going to the internet by itself.

**A direct entry takes a site outside the policy.** A LAN site that the browser opens directly never reaches the proxy, so bedtime and quotas do not apply to it. Turn off `local_subnets` and `local_domains` to keep a LAN site, such as a media server, under the policy. The direct entries do not stop a child going direct to the internet. A browser that cannot fetch the file goes direct, and a child can change the browser's settings. The firewall rule under [OPNsense rule tips](#opnsense-rule-tips) is still what stops that.

## Browser

Firefox is the browser these computers use. Chromium is set up as well. Set each one to the configuration URL. The manual settings at the end of each section still work instead.

### Firefox

Firefox keeps its own certificate store and does not use the system store unless `security.enterprise_roots.enabled` is turned on.

After the PEM is in the system trust store, turn that preference on. Open `about:config`, search for `security.enterprise_roots.enabled`, and set it to true. Quit Firefox and start it again.

If that preference stays off, import `mitmproxy-ca-cert.pem` instead. Open Settings, then Privacy & Security, then Certificates, then View Certificates, then Authorities, then Import. Trust the certificate to identify websites.

Point Firefox at the proxy from Settings, then General, then Network Settings, then Settings. Choose "Automatic proxy configuration URL" and enter the configuration URL, such as `http://garden:8088/proxy.pac`. Press OK.

To make Firefox fetch the file again after a change, such as a `dw reload` that changed `proxy_configuration`, press Reload beside the URL in the same dialog, or quit Firefox and start it again.

The manual alternative: choose Manual proxy configuration. Set the HTTP proxy to the proxy host and `PROXY_PORT`, and tick "Also use this proxy for HTTPS". Leave the SOCKS fields empty. Add the policy server's names to "No proxy for" so the task pages open directly.

### Chromium

Chromium uses the system trust store, so the certificate above is the one it trusts. No extra certificate step.

Arch's Chromium reads `~/.config/chromium-flags.conf`. One line points it at the configuration URL:

```text
--proxy-pac-url=http://garden:8088/proxy.pac
```

Quit Chromium and start it again so it reads that file. Starting it again is also how it fetches the file again after a change.

The manual alternative is one line with the proxy host and `PROXY_PORT` instead:

```text
--proxy-server=http://garden:8080
```

### Chrome and Edge on Windows

Chrome and Edge use Windows' proxy settings. Open Settings, then Network & internet, then Proxy. Under Manual proxy setup, turn on "Use setup script", set the script address to the configuration URL, such as `http://garden:8088/proxy.pac`, and press Save. Restart the browser to make it fetch the file again.

The certificate goes into Windows' "Trusted Root Certification Authorities" store, which both browsers use.

### When a browser fetches the file

A browser downloads the file, keeps it in memory, and asks it about every request. Neither browser keeps it between runs, and neither uses its HTTP cache for it.

- Firefox fetches it when it starts, when its proxy settings change, when Reload is pressed in Connection Settings, and 2 seconds after a network change on the child's computer. It never fetches a working file again on a timer.
- Chromium fetches it in the same cases, and also about 12 hours after a good fetch, once the browser is used again.
- `dw restart` does not need a fetch. The file names the same proxy, and both browsers go back to it once it answers.

When the fetch fails, for example because daywarden is down when the browser starts, both browsers go direct for every request. Firefox tries again after 5 seconds, doubling up to 5 minutes, then every 5 minutes. Chromium tries again after 8 seconds, 32 seconds, and 2 minutes, then every 4 hours. On a computer behind the firewall rule, going direct loses internet sites and keeps LAN sites. The worst case is an outage of up to 5 minutes in Firefox, or up to 4 hours in Chromium, not a way around daywarden.

Chromium always connects directly to `localhost` and link-local addresses, whatever the file says. Turning `localhost` off cannot route those through the proxy in Chromium.

### Browser policies on a managed computer

These are optional. They stop the child changing the proxy settings, and shorten Firefox's retries. daywarden does not deploy them. Put the file in place by hand, or with a tool of your own.

For Firefox, `/etc/firefox/policies/policies.json`:

```json
{
  "policies": {
    "Proxy": {
      "Mode": "autoConfig",
      "AutoConfigURL": "http://garden:8088/proxy.pac",
      "Locked": true
    },
    "Preferences": {
      "network.proxy.autoconfig_retry_interval_min": { "Value": 5, "Status": "locked" },
      "network.proxy.autoconfig_retry_interval_max": { "Value": 60, "Status": "locked" }
    }
  }
}
```

`Proxy` sets the configuration URL, and `Locked` greys out the Network Settings dialog. The two preferences are the seconds Firefox waits before it tries a failed fetch again, first and at most. With these values, a computer that started while daywarden was down picks up the file within a minute of daywarden coming back, instead of 5 minutes. `about:policies` shows whether Firefox read the file.

For Chromium, `/etc/chromium/policies/managed/daywarden.json`:

```json
{
  "ProxySettings": {
    "ProxyMode": "pac_script",
    "ProxyPacUrl": "http://garden:8088/proxy.pac",
    "ProxyPacMandatory": true
  }
}
```

`ProxyMode` and `ProxyPacUrl` set the configuration URL and lock the browser's proxy settings, so the line in `chromium-flags.conf` is not needed. `ProxyPacMandatory` makes a failed fetch fail every request, rather than go direct. It does not shorten the retries. Chromium's retry and failed-proxy timings cannot be changed. `chrome://policy` shows whether Chromium read the file. Chrome and Edge on Windows take the same `ProxySettings` policy through Group Policy or the registry.

Firefox has no equivalent of `ProxyPacMandatory`. `network.proxy.failover_direct` only covers Firefox's own internal requests.

### Auto-detection

Firefox's "Auto-detect proxy settings for this network", Chromium's `--proxy-auto-detect` flag, and Windows' "Automatically detect settings" look for `http://wpad.<search domain>/wpad.dat`. That is port 80, which daywarden does not listen on, because it needs root. To use auto-detection, put a reverse proxy on port 80 in front of daywarden, and a DNS name for it:

1. In OPNsense, open Services, then Unbound DNS, then Overrides. Add a host override with host `wpad`, the household domain such as `bakuna.net`, and the address of the machine running the reverse proxy.
2. On that machine, forward `/wpad.dat` to `PROXY_CONFIG_PORT`. A sample nginx server block:

   ```nginx
   server {
       listen 80;
       server_name wpad.bakuna.net wpad;
       location = /wpad.dat {
           proxy_pass http://127.0.0.1:8088/wpad.dat;
       }
   }
   ```

   The reverse proxy can only fetch the file. A request through it cannot reload daywarden or change anything.
3. In Firefox's Network Settings, choose "Auto-detect proxy settings for this network". For Arch's Chromium, put `--proxy-auto-detect` in `~/.config/chromium-flags.conf` instead of `--proxy-pac-url`.

DHCP option 252 is the Windows alternative, and needs no port 80. In OPNsense, open Services, then DHCPv4, then the LAN interface, and under Additional Options add number `252`, type text, with the configuration URL as the value. Windows' "Automatically detect settings" uses it, and Chrome and Edge follow Windows.

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

With the configuration URL, `docker compose logs autoconfig` shows each fetch of the file and the address it came from, such as `served /proxy.pac to 192.168.12.40`. A browser that never appears there has not fetched it. Open the task picker too. It opens directly, so it does not appear in the decisions log, and it should still offer that child's tasks.

# OPNsense rule tips

These are the attributes for the rule that blocks a direct path to the internet, so the alias has to use the proxy. They are field values, not a click-through of the UI.

- Group the machines in a Firewall Alias. That alias is the set of hosts forced through the proxy.
- Source and Destination match the IP addresses in the IP packet. They are independent of the route the packet would take through the firewall. Set Source to the alias. Set Destination to any.
- `Interface (rule)` is the interface the matching traffic passes through. On a household LAN, set it to that LAN interface and no other. A more exotic layout is outside these tips.
- Direction is relative to the interfaces listed in `Interface (rule)`. The traffic to block arrives at that interface from another machine, so Direction is `In`.
- Protocol and port can be any, or left blank.
- Version can be IPv4, or any, depending on whether the LAN uses IPv6. Most networks use IPv4. A LAN that already uses IPv6 is outside these tips. The setup note still says that host's IPv6 needs the same treatment when the LAN has IPv6, because an IPv4 reservation does not pin the IPv6 address.