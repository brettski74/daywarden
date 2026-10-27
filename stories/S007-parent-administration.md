Ticket: S007
Title: Parent administration
Status: Draft
Story Points: 21
Last Updated: 2026-10-26 00:49:00
---

# User Voice

As a parent, I want to change the rules, the word lists, and which client group they apply to from a browser, so that a normal week does not involve editing a database by hand.

# Use Cases

- A parent signs in. The child does not know the password, and the quiz pages do not ask for it.
- The parent edits client groups, site groups, time windows, quotas, rule sets, and the household settings those rules use.
- The parent edits arithmetic weights, spelling pools, and parts-of-speech sentences, and assigns tasks to a client group.

# Acceptance Criteria

- [ ] S007.1 is part of the initial build, so usage reports and attempt review are behind a password.
- [ ] S007.2 and S007.3 are not part of the initial build. The policy and the quiz content are edited in config files.
- [ ] When S007.2 and S007.3 are done, everything the sample policy and the quiz stories can express in their stores can be changed from these pages.
- [ ] The child, using only the task site, cannot open a parent page or change a rule.

# Child stories

| Ticket | Title | Points |
| --- | --- | --- |
| S007.1 | Parent sign-in | 5 |
| S007.2 | Edit the hierarchical policy (later) | 8 |
| S007.3 | Edit tasks and assignments (later) | 8 |

# Notes

The initial build uses config files for the policy and the quiz content. S007.1 is in that build so the child cannot open the usage report or the attempt review. S007.2 and S007.3 are a quiz-and-policy builder. They are nice to have and are not required for the first setup. S008.4 and S003.3 share the sign-in from S007.1.

S007.2 edits the model in `docs/hierarchical-policy.md`. It does not edit a rule list owned by a site group, and it does not generate the proxy bypass list.
