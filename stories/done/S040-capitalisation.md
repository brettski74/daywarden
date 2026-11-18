Ticket: S040
Title: Capitalisation
Status: Done
Story Points: 34
Last Updated: 2026-11-18 06:17:49
---

# User Voice

As a parent, I want to keep pools of correctly capitalised sentences, so that he practises finding which words need a
capital letter in sentences shown to him all in lowercase.

As a child, I want to click the words that need capitals, and get a hint and another go when I get some wrong, so that
I can work it out myself before I am shown the answer.

# Behaviour

## Done

- [ ] S040.1 and S040.2 are done.

# Child stories

| Ticket | Title | Points |
| --- | --- | --- |
| S040.1 | Capitalisation pools and quiz | 13 |
| S040.2 | Capitalisation in the portal and MCP | 21 |

# Notes

Capitalisation copies the parts of speech model in S031: pools of sentences on disk, tasks that name pools, a timer
scaled by level of difficulty, and the same end conditions. It has its own pools because its sentences carry nothing
but their capitals.

Sizing: 34, so an epic. S040.1 can be accepted through the policy files and the child's page before any portal work.
It is sized against S006.1 to S006.3 (14), which built a new task type with a harder page. Here most of the run,
timer, and pool loading code already exists. S040.2 holds the portal pool and task pages (about 13 against S031.2 and
S031.3, with a much simpler editor), the attempt page (about 5), and the MCP tools (about 3), all of which wrap code
that S031 and S036 already have.
