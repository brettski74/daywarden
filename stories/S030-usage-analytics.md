Ticket: S030
Title: Usage analytics
Status: Draft
Story Points: 55
Last Updated: 2026-11-14 01:25:00
---

# User Voice

As a parent, I want to see usage as a graph over any period, compare children, site groups, and quotas side by side,
and drill down from a line to the hosts it was spent on and then to the requests themselves, so that I can see how
much time and data goes to YouTube or any other site, and what was fetched.

# Behaviour

## Done

- [ ] S030.1, S030.2, and S030.3 are done.

# Child stories

| Ticket | Title | Points |
| --- | --- | --- |
| S030.1 | Usage graph with filters and presets | 21 |
| S030.2 | Drill down to usage by host | 13 |
| S030.3 | Requests: drill-down table and Requests page | 21 |

# Notes

## What the usage ledger holds today

The usage ledger in `policy.sqlite3` in the `policy-data` volume has two tables of buckets, written by
`policy/usage.py` for every observation the proxy reports:

- `group_buckets`: one row per client group, site group, and bucket start, with the bucket's length and its bytes.
- `quota_buckets`: one row per client group, quota, and bucket start, with the same length and bytes, for each quota
  whose rule set accepted the observation.

The bucket length is `bucket_length` in the policy, 3m in the household file, and buckets align to local midnight. A
bucket's minutes are its whole length whenever any traffic was reported in it. Nothing prunes either table, so the
graph reaches back to the day daywarden was installed. The bytes are request and response bodies added together.

What is not kept today:

- **Host, port, URL, and single requests.** The proxy sends the full URL with each report. The observations service
  classifies it into a site group and drops it. S030.2 keeps the host in buckets, and S030.3 keeps each request.
- **Site group on a quota row.** A quota row knows its client group but not the site group. The graph cannot split
  by site group and quota together. S030.1 handles this without changing those tables.
- **Upload and download apart.** S030.2 counts them apart for hosts. The graph's totals stay combined.

## Retention

The existing bucket tables are small and kept forever, so the graph covers all history. The host buckets and the
requests are much larger. The host buckets are kept for `host_retention`, from S030.2, and the requests for
`request_retention`, from S030.3. Both default to 30 days and are set separately, because the host buckets are about
twenty times smaller and may be worth keeping longer. A drill-down or a request list over a range that reaches further
back says from when its detail is kept.

## Split

S030.1 uses only the existing tables, so it changes no stored data. S030.2 changes what the proxy reports and adds the
host buckets and the retention, and is accepted through the host bar chart. S030.3 adds a record of every request,
including those a rule refuses, and is accepted through the request table and the Requests page. Each child is accepted through its own
page, and each changes the proxy and the stored data in a way worth seeing working before the next is built on it.
