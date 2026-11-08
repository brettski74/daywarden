Ticket: S022
Title: Some sites fail with 502 through the proxy because of whitespace around a response header
Status: Draft
Story Points: 3
Last Updated: 2026-11-08 13:30:00
---

# User Voice

As a parent, I want a site that the policy allows to load through the proxy whenever it loads in a browser without the
proxy. A news article that shows "502 Bad Gateway" from mitmproxy looks like a daywarden fault, and the child cannot
read a page he is allowed to read.

# Use Cases

## UC1 - An allowed article fails only through the proxy

- On the child's computer, with Firefox using the proxy, the parent opens
  `https://globalnews.ca/news/12136868/cruise-ship-leaves-without-passengers-cambodia/`.
- Firefox shows mitmproxy's "502 Bad Gateway" page:
  `HTTP/2 protocol error: Received header value surrounded by whitespace b"\tdefault-src 'self' *.wp.com;..."`.
- The same URL loads normally on the server, which does not use the proxy.
- It happens on the development stack and in production, which runs the release before S019, so it is not caused by
  S019.

# Acceptance Criteria

- [ ] Through the proxy, Firefox and Chromium load
  `https://globalnews.ca/news/12136868/cruise-ship-leaves-without-passengers-cambodia/` the same as without it, and
  the page appears in `docker compose logs decisions`.
- [ ] The page is still decided by the policy. A policy that denies `globalnews.ca` still denies it, and a quota still
  counts its bytes.
- [ ] A response header whose value starts or ends with a space or a tab no longer turns into a 502, over HTTP/2 or
  HTTP/1.1, for any site.
- [ ] Requests from the children's browsers are still checked as strictly as they are today. A request that mitmproxy
  refuses today as malformed, such as one with both `Content-Length` and `Transfer-Encoding`, is still refused.
- [ ] Sites still use HTTP/2 through the proxy where they did before.
- [ ] A comment in the proxy configuration says why the setting is there and which mitmproxy version it was checked
  against, so a mitmproxy upgrade checks it again.

# Notes

## What happens

The HAR file saved from Firefox, `globalnews.ca_news_12136868_cruise-ship-leaves-without-passengers-cambodia__Archive
[26-11-08 13-10-32].har` in the repository root, holds one request. It is the page itself, answered `502` by
`mitmproxy 12.2.3` after 137 ms, with the error above in the body. The policy allowed the request. The site's response
then failed inside mitmproxy, before the addon saw it.

The site sends this header, with a tab at the start of its value, over both HTTP/2 and HTTP/1.1:

```text
content-security-policy-report-only: \tdefault-src 'self' *.wp.com;\timg-src data: https:;\tscript-src ...
```

RFC 9113 section 8.2.1 says an HTTP/2 field value must not start or end with whitespace, so the site is wrong. Browsers
accept it anyway. mitmproxy's upstream HTTP/2 connection uses the `h2` library (4.3.0 in the 12.2.3 image), which
checks inbound headers and treats this as a protocol error. mitmproxy then answers the browser with 502. The site is on
WordPress VIP (192.0.66.x), so other WordPress-hosted sites are likely to hit the same thing.

This is known mitmproxy behaviour, not a daywarden bug. The maintainers' answer in
[mitmproxy#4836](https://github.com/mitmproxy/mitmproxy/issues/4836),
[mitmproxy#5480](https://github.com/mitmproxy/mitmproxy/issues/5480) (also a WordPress host), and
[mitmproxy#6383](https://github.com/mitmproxy/mitmproxy/issues/6383) is to turn off the `validate_inbound_headers`
option.

## Reproduced on 2026-11-08

With a stock `mitmproxy/mitmproxy:12.2.3` container, without the daywarden addon, and `curl --http2` through it:

| mitmproxy setting | Result |
| --- | --- |
| Defaults | 502, the same error |
| `--set http2=false` | 200, over HTTP/1.1 |
| `--set validate_inbound_headers=false` | 200, over HTTP/2, with the tab passed on to the client |

## Options

1. **`validate_inbound_headers=false` for the whole proxy.** One line in the proxy's command in `docker-compose.yml`.
   mitmproxy's own help says that disabling it "makes mitmproxy vulnerable to HTTP smuggling attacks". The same option
   also controls mitmproxy's checks on requests from the browsers (`mitmproxy/proxy/layers/http/__init__.py`), and the
   browsers are the children's. A request that slips past mitmproxy's framing checks is one the decisions service may
   not have judged as the server sees it. Not recommended.
2. **`http2=false`.** Everything goes over HTTP/1.1, between the browser and the proxy and between the proxy and
   sites. h11 strips the whitespace, and the request checks stay on. It costs HTTP/2's multiplexing, which matters
   most on pages with many requests, and it changes how every site is fetched to fix a few.
3. **Relax only what upstream servers send.** In 12.2.3, the connection to a site is `Http2Client`, with its own
   `H2Configuration`, separate from `Http2Server`, which faces the browser. `Http2Connection.__init__` copies the
   option onto that configuration for each connection. The addon could turn inbound header validation off for
   `Http2Client` only, leaving the option on, so every check on the children's requests stays. It reaches into
   mitmproxy internals, so it is tied to the pinned image version, and an upgrade has to check it again. A test that
   runs a local HTTP/2 origin sending a header with a leading tab would catch a break. An upstream mitmproxy option to
   relax only server responses would replace it.

Option 3 is the recommendation, with an upstream mitmproxy issue or pull request for a server-only setting. Option 2 is
a quick stop-gap if this needs fixing before then.

## Points to work out in refinement

- Which option, and whether to offer it as a setting in `.env`.
- Whether to log each response that would have failed the strict check, so the parent can see how often it happens.
- Whether the HTTP/1.1 upstream path has the same problem with other malformed headers. The tab here is accepted over
  HTTP/1.1.
- Whether to move the HAR file next to this ticket. It holds only this one request and no cookies.
