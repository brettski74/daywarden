Ticket: S002
Title: Usage accounting
Status: Draft
Story Points: 13
Last Updated: 2026-10-26 00:49:00
---

# User Voice

As a parent, I want the house to count internet use in short buckets, so that a quota means time the site was actually moving data, and so that I can see when Classroom was used.

# Use Cases

- Observations from the proxy mark a bucket for a client and a site group.
- A bucket counts toward the consumed time only after it has ended, and it contributes the length it was opened with. The quota itself stays a configured duration.
- A parent can read, for a client and a group, which buckets were active and on which days.
- A volume cap can sit on the same stored byte counts. The sample does not turn it on until real totals justify a number.

# Acceptance Criteria

- [ ] S002.1 and S002.2 are done before the quota is trusted with a real browser.
- [ ] S002.3 is not required for that. It waits until real traffic has been looked at.
- [x] Classroom traffic is visible in the report even though that group has no quota.

# Child stories

| Ticket | Title | Points |
| --- | --- | --- |
| S002.1 | Bucket ledger | 5 |
| S002.2 | Usage report | 3 |
| S002.3 | Volume limit | 5 |

# Notes

Depends on S000.3 for observations and on S001.2 for groups. S001.5 reads the same ledger.

Quotas, client groups, and the wider report are specified in `docs/hierarchical-policy.md`. S008.3 and S008.4 replace the ledger key and the report shape. This epic stays the record of the buckets that were built.

S002.3's condition is implemented. The sample policy does not turn it on. On 2026-10-22 the running household database was still schema 2 and had no usage buckets, so no starting byte limit was chosen.
