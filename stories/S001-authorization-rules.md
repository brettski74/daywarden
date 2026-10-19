Ticket: S001
Title: Authorization rules
Status: Draft
Story Points: 21
Last Updated: 2026-10-18 15:05:00
---

# User Voice

As a parent, I want each request classified into a site group and then judged by time of day, whether today's revision is done, and whether today's time quota remains, so that Classroom can stay open while YouTube is earned.

# Use Cases

- A client is a source IP address in a household timezone.
- Site groups are tested in priority order. The first matching glob wins. One group is the default.
- Each group has an ordered list of rules. Each rule can continue, deny with a message, redirect to a URL or to a revision task, or allow the request.
- The Monday-to-Thursday entertainment schedule from the problem statement is configuration, loaded as the sample household policy.

# Acceptance Criteria

- [ ] S001.1 through S001.6 are done.
- [ ] The worked entertainment example in S001.3 passes as an automated test against the sample policy from S001.6.
- [ ] No quiz pages are required for this epic. Task and quota conditions read counts that may still be zero.

# Child stories

| Ticket | Title | Points |
| --- | --- | --- |
| S001.1 | Clients and household timezone | 3 |
| S001.2 | Site groups and glob matching | 5 |
| S001.3 | Rule engine and time windows | 5 |
| S001.4 | Task-completion condition | 3 |
| S001.5 | Quota-remaining condition | 3 |
| S001.6 | Sample household policy | 2 |

# Notes

Depends on the decision API shape in S000.2. The service implemented here replaces the test double. The addon does not change.
