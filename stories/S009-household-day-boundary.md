Ticket: S009
Title: Configurable household day boundary
Status: Draft
Story Points: 5
Last Updated: 2026-10-28 23:29:00
---

# User Voice

As a parent, I want the household day to roll over at a time I choose, so that quotas and revision counts reset when the house starts its day, rather than at midnight in the middle of a late evening.

# Use Cases

- The household sets one local clock, such as `05:00`. The day runs from that time, inclusive, until the same time the next day, exclusive.
- Omitted, the boundary stays local midnight, which is the behaviour the policy has now.
- Quota balances, the revision count behind `tasks_required`, and the alignment of usage buckets all use that boundary. A request at 02:00 belongs to the household day that started the previous morning when the boundary is 05:00.
- Time windows stay wall-clock periods. Bedtime at `00:00` is still midnight. This setting does not move a window. It moves the moment usage and task counts start a new day.
- Changing the boundary does not have to affect a transfer that is already running. That is the same choice as any other policy edit during a transfer.

# Acceptance Criteria

- [ ] With no boundary configured, balances, task counts, and buckets still reset and align at local midnight.
- [ ] A configured clock is household-local. A moment before that clock counts toward the previous household day. A moment at that clock counts toward the new day.
- [ ] Quota time, quota bytes, and `tasks_required` all agree on which household day a moment belongs to.
- [ ] Buckets still divide 24 hours, and they align to the configured boundary rather than to midnight.
- [ ] A clock the loader cannot read, or a boundary that does not divide the day the way buckets require, is a load error. The previous policy stays in force.

# Notes

Not part of the in-flight grace work. Logged so a later change can move the reset off midnight without rewriting the cut rules. `docs/hierarchical-policy.md` currently says other reset periods are out of scope. The likely use is a morning reset, so a count that clears overnight does not land in the middle of something the evening rules still allow. A household that never has the internet open past midnight does not need this.
