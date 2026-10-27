Ticket: S008
Title: Hierarchical policy
Status: Refined
Story Points: 37
Last Updated: 2026-10-27 03:15:12
---

# User Voice

As a parent, I want the household rules written as nested checks on clients, times, and sites, so that one child can have a different bedtime, a different site list, and a different quota from another.

# Use Cases

- The policy file is the model in `docs/hierarchical-policy.md`.
- A request is classified once into a site group and a client group, then an ordered rule set decides.
- Usage is recorded for those groups and accrued to each quota whose rule set accepts it.
- The sample household schedule still denies bedtime YouTube, redirects during school hours, and allows the evening only after revision and inside the time limit.

# Acceptance Criteria

- [x] S008.1 through S008.5 are done.
- [ ] S008.6 is not required for this epic to be done. It is the later cut of a live transfer.
- [ ] The decision API still returns only allow, deny, or redirect. The addon does not learn about rule sets.
- [ ] No TOML policy loader, no rule list owned by a site group, and no compatibility layer for the old rule rows remain once S008.5 is done.

# Child stories

| Ticket | Title | Points |
| --- | --- | --- |
| S008.1 | Load the policy file | 8 |
| S008.2 | Decide with nested rule sets | 8 |
| S008.3 | Accrue usage to quotas | 8 |
| S008.4 | Report usage by group and quota | 5 |
| S008.5 | Household policy file | 3 |
| S008.6 | Cut a transfer past grace (later) | 5 |

# Notes

Depends on S000.2 and S000.3. S001 and S002 stay as the record of the engine this epic replaces. There is no production policy to preserve. An existing policy database does not have to keep its rule rows or its old usage keys. The service loads the new file into a store shaped for this model.

The spec is `docs/hierarchical-policy.md`. These stories do not restate every parsing rule. Where a test needs a behaviour, the spec is the source.
