Ticket: S010
Title: Maintenance commands
Status: In Progress
Story Points: 8
Last Updated: 2026-11-01 14:40:28
---

# User Voice

As a parent who runs the household server, I want a small set of commands I can run inside the decisions container, so that routine fixes and test resets do not need hand-written SQL.

# Use Cases

- Every command is a short script in `bin/`, run on the machine running Compose, such as `rm-attempts --task sums`. It works from any directory once linked into a directory on the `PATH`, such as `~/bin`. The script runs the job inside the decisions container, so the parent never types `docker compose exec` or `python -m`.
- The jobs themselves are subcommands of `policy.maintenance` in the policy image. Each script passes its arguments straight through, and `--help` describes them.
- A command reads the same `POLICY_DB` and `POLICY_FILE` as the decisions service, so it acts on the household's own data.
- A command that removes or changes stored data shows what it would do first. It only acts when it is given `--yes`.
- A command that removes data refuses to run with no filter at all, unless it is told `--all`.

# Acceptance Criteria

- [x] S010.1 is done.
- [x] Every maintenance command is a script in `bin/` that runs from any directory, with no `docker compose exec` or `python -m` to type.

# Child stories

| Ticket | Title | Points |
| --- | --- | --- |
| S010.1 | Remove attempts | 3 |

# Notes

Later commands are expected to include things such as clearing the task picker's rotation and pruning old usage buckets. They are not part of this epic until they are written as stories.
