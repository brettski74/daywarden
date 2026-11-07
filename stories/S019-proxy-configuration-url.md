Ticket: S019
Title: Proxy Configuration URL
Status: Draft
Story Points: 
Last Updated: 2026-11-07 14:44:44
---

# User Voice

As a parent, I want to have simple and consistent proxy setup for my children's computers. Modern browsers often support setting up proxy settings automatically. For example, Firefox has options to "Auto-detect proxy settings for this network" and an "Automatic proxy configuration URL". We should support one or both of these methods. I suspect that the auto-detection is probably using the DHCP server or something. If so, that's probably not applicable. I think the latter option - "Automatic proxy configuration URL" - is probably the primary mechanism we should focus on.

I haven't looked into other browsers, since Firefox is our primary browser of choice, but we should try to support Chromium based browsers like Chrome and Edge if possible. I'm hoping there is a standard format for the configuration data returned from these automatic proxy configuration URLs that will be understood by most major browsers including all of the ones mentioned above.

The system shoudl make such a URL endpoint available. By default, it should:

- configure the browser to use this proxy for both HTTP and HTTPS requests and any other protocols we can support at the time.
- Bypass the proxy for:
  - localhost
  - <local> urls
  - the proxy/policy server itself, both by all IP addresses and all hostnames it is known by - the PARENT_NAMES environment variable might be sufficient for this.
  - all local subnets, defined as by the IP address and net mask of all *real* network interfaces that are UP and have an IP address associated with them. Virtual IPs or IPs associated with container networks or loopback or anything else that doesn't actually provide connectivity to other hosts can be ignored.
  - all local domains, based on the search domains specified in the resolver configuration. So if the search domains include mydomain.net and mydomain.org, then we add .mydomain.net and .mydomain.org to the proxy bypass list in our response to the browser.

Each of the line items above should be able to be toggled on or off in the configuration somehow. By default they should all be on, so the toggle exists to allow administrators to exclude items that they don't want included in the bypass list.We should also provide an option somewhere for a list of additional proxy bypass patterns to be able to be specified. To be clear, this is **not** the list in config/bypass.txt. That list is a list of hosts that when sent to the proxy server bypass policy and the proxy server should pass without any further scrutiny or rule processing. The bypass list being discussed in this story if the set of hosts or IP addresses that the browser should never send to the proxy server in the first place and should just connect to directly.

# Use Cases

## UC1 - [Use case description]

- bullet
- point
- list

## UC2 - [Use case description]

- bullet
- point
- list

# Acceptance Criteria

- [ ] Sample
- [ ] Sample
- [ ] Sample

# Child stories

| Ticket | Title | Points |
| --- | --- | --- |
| Sxxx.1 | First child | 8 |
| Sxxx.2 | Second child | 2 |
| Sxxx.3 | Third child | 2 |

# Notes
