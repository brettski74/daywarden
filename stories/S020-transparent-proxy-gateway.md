Ticket: S020
Title: Transparent proxy for devices that cannot use a proxy setting
Status: Draft
Story Points: 
Last Updated: 2026-11-08 10:45:00
---

# User Voice

As a parent, I want daywarden to govern a computer whose proxy settings I cannot change, such as my older son's
school Chromebook. The school district enforces "Direct Internet Connection" on it, so neither a manual proxy nor the
configuration URL from S019 can be set. YouTube on that Chromebook is the main way he watches videos, so it needs the
same time windows, quotas, and redirects to the task pages as the other computers.

I would like to make the daywarden server the gateway for those devices. The server forwards their traffic, sends web
traffic through the proxy without the device knowing, and OPNsense blocks anything those devices try to send to the
internet directly.

# Use Cases

## UC1 - A locked-down device is governed

- The parent gives the Chromebook the daywarden server as its gateway, through its DHCP reservation, and installs the
  daywarden CA on it.
- The Chromebook keeps its enforced direct connection. Its web traffic still goes through daywarden, and the policy
  decides it as it does for the other computers.
- YouTube in the browser follows the child's time windows and quotas, and a blocked page redirects to the task pages.

## UC2 - Other traffic still works

- Traffic that is not web traffic, and LAN traffic, keeps working for that device, as the parent configures it.

## UC3 - Going around daywarden fails

- If the device sets its own gateway, uses IPv6, or tries QUIC, it gets no internet. It does not get around the
  policy.
- If the daywarden server is down, the device has no internet.

# Acceptance Criteria

- [ ] A device whose gateway is the daywarden server, with the daywarden CA installed, has its HTTP and HTTPS traffic
  decided by the policy, without any proxy setting on the device.
- [ ] Redirects to the task pages, and the task pages themselves, work for that device. The device is classified into
  its client group by its own address.
- [ ] Which devices are handled this way, and what happens to their traffic that is not web traffic, is set in
  daywarden's configuration.
- [ ] Devices that use the proxy setting or the configuration URL work as before.
- [ ] The documentation covers the OPNsense side: the DHCP gateway for the device, blocking its direct internet
  access, its IPv6, and UDP/443.
- [ ] The documentation covers installing the CA on a Chromebook, and says that Android apps on it do not trust that CA.

# Notes

To be refined later. Other features come first. This is an outline of what was found while refining S019, not a
design.

## Findings so far

- The Chromebook's Wi-Fi proxy section says "Your admin is enforcing the following proxy: Connection Type: Direct
  Internet Connection". That is the `ProxyMode` policy set to `direct`. It also turns off auto-detection, so DHCP
  option 252 and WPAD are ignored.
- No filtering extension was found, and its DNS is the one DHCP hands out, which is OPNsense.
- The certificate manager appears to allow importing an authority, so the daywarden CA can probably be trusted.
  Android apps, such as the YouTube app, do not trust certificates the user installs.

## Points to work out in refinement

- Running mitmproxy in transparent mode, which probably needs host networking, because the original destination of
  each connection cannot be looked up from inside a bridge-network container.
- How the server forwards traffic: turning on IP forwarding, rules in Docker's `DOCKER-USER` chain, and masquerading
  forwarded traffic so the replies come back through the server rather than straight from OPNsense.
- What daywarden sets up on the host and what the parent sets up, and how `dw` manages it.
- IPv6, QUIC, and what happens while the server is down or rebooting.
- Whether to decide by host name without decrypting, for a device that cannot trust the CA. That would be a separate
  story.

## Out of scope

- Any change to S019.
- Getting around the school district's own management of the device.
