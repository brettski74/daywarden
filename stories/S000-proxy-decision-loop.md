Ticket: S000
Title: Proxy decision loop
Status: Draft
Story Points: 13
Last Updated: 2026-10-18 15:05:00
---

# User Voice

As a parent, I want my child's browser to reach the internet only through a proxy that asks our authorization service before it forwards anything, so that later rules can allow, refuse, or redirect a request without us writing a proxy.

# Use Cases

- The household runs mitmproxy and the policy service together with Docker Compose.
- A request is allowed, answered with `403` and a message, or answered with `302` to a URL the policy service chose.
- Hosts that must keep working when the policy service is down (the task site, and Classroom) are on a local bypass list.
- The addon reports that bytes moved, so the ledger can fill five-minute buckets while a transfer is still open.
- A parent can follow written steps to trust the proxy CA and point the browser at the proxy.

# Acceptance Criteria

- [ ] S000.1, S000.2, S000.3, and S000.4 are done.
- [ ] The addon contains no rule about weekdays, quotas, or quizzes. It enforces a decision and reports observations.
- [ ] Replacing mitmproxy later would mean rewriting the addon, not the policy service. The decision and observation APIs are plain HTTP.

# Child stories

| Ticket | Title | Points |
| --- | --- | --- |
| S000.1 | Run mitmproxy with a local CA | 3 |
| S000.2 | Enforce allow, 403, and 302 | 5 |
| S000.3 | Report traffic observations | 3 |
| S000.4 | Document the child computer setup | 2 |

# Notes

Squid plus ICAP remains the documented fallback in `implementation_plan.md` if this epic cannot intercept the child's browser. Do not start that fallback inside this epic.
