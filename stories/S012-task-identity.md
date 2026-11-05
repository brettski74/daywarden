Ticket: S012
Title: Task identity is type and name
Status: Refined
Story Points: 5
Last Updated: 2026-11-04 23:40:00
---

# User Voice

As a parent, I want a task to be identified by its type and its name together, everywhere: in the policy file, in its web address, and in its history. Then I can reuse a name for a different kind of quiz, or run an arithmetic `week-1` beside a spelling `week-1`, without one inheriting the other's passes, skips, cooldown, or half-finished attempt.

# Use Cases

## UC1 - The policy file groups tasks by type

- Under `tasks:`, each key is a task type, and under each type each key is a task name. The `type:` field inside a task goes away, because the type is the key above it. The sample policy's tasks become:

```yaml
tasks:
  arithmetic:
    sums:
      group: younger
      pass_cooldown: 1
      body:
        operation: addition
        # ...
  skip_counting:
    skip_counting:
      group: younger
      pass_cooldown: 1
  spelling:
    spelling:
      group: younger
      pass_cooldown: 1
      body:
        timeout: 30s
        revision_required: 10
```

- Two tasks may share a name when their types differ, such as `arithmetic: { week-1: ... }` and `spelling: { week-1: ... }`. Each is a separate task with its own address, history, dates, and limits.
- The same type and name twice is a load error, in one file (a duplicate key) or across included files ("already defined at ..."), as a duplicate name is today.
- An included file may add tasks under a type that another file also uses.
- A type key follows the same rules as today's `type:` field. Every other task field, and each quiz type's `body`, is unchanged.
- The old layout is not supported. A policy file still written that way fails to load, like any other malformed policy file. There is no special check or message for it. `config/policy.yaml` is rewritten in the new layout as part of this story.
- Every load error about a task names it as `<type>/<name>`, such as `task 'arithmetic/sums': body.operands entry 2: ...`.

## UC2 - Task addresses include the type

- The picker stays at `/tasks/next`. It is the one address to send him to when he should do some work and no particular task has been chosen. A rule's `revision_task` redirect goes there, and it forwards him to the task S003.2 chooses. A later screen where he chooses from the tasks he may open would replace what this address shows. It would keep the address.
- A task's own page is at `/tasks/<type>/<name>`, such as `https://<task host>/tasks/arithmetic/sums`. Spelling audio is under `/tasks/<type>/<name>/audio/<file>`.
- Today a task's page is at `/tasks/<name>`, and a task named `next` is moved to `/tasks/work/next` so that it does not clash with the picker. A task address now always has two parts after `/tasks/`, and the picker has one, so they cannot clash and `/tasks/work/` goes away. A task named `next` is at `/tasks/<type>/next`.
- Everything that sends him to a task uses the new address: the picker, "Next task", and the page he goes to after giving up.
- The proxy allows a task's page, its quiz requests, and its audio while he may open that task, exactly as it does today.
- An address that is not a task he may open goes to the task the picker chooses, as today. That includes the right name with the wrong type, a type and name not in the policy, and an old-style `/tasks/<name>` address. No special handling is needed for the old form.

## UC3 - History belongs to type and name

- Every attempt stores its task's type beside its name. A task's history is the attempts with the same client group, type, and name. Every rule that reads history uses that match:
  - the cooldown after the last finished attempt
  - skip days and `max_skips`
  - whether a pass has met the `due_date`
  - the pass count for `max_passes`
  - coming back to the attempt in progress rather than opening a second one
- Today's revision count from S003.1 is unchanged. It still counts every pass this client group finished today, whatever the task.
- Removing `arithmetic: { quiz-1: ... }` from the policy file and later adding `skip_counting: { quiz-1: ... }` gives a task with no history. An arithmetic attempt left in progress under `quiz-1` is not resumed by skip counting. Putting the arithmetic task back brings its history back, including that attempt.
- Editing a task's body under the same type and name keeps its history, as S006 describes for editing sentences.

## UC4 - Everything else that names a task

- Giving up on a task leaves that task out of the picker for the rest of the visit, as S003.2 describes. That is the task with that type and name only. Giving up `arithmetic/week-1` does not leave out `spelling/week-1`.
- When tasks tie in the picker's ranking, they are taken in order of name, then type.
- The parent's attempt list and attempt view from S003.3 show each attempt's type and name. An attempt's formatted view, such as the S004.6 arithmetic review, is chosen by the attempt's stored type, not by whatever task has that name now.
- A `parent_check` recorded from the parent pages stores the type `parent_check`.
- `bin/daywarden remove-attempts --task NAME` matches attempts with that name of any type. `--type TYPE` matches the type stored on each attempt. Together they match one task. `--type` no longer needs the policy file to load.

## UC5 - Starting with a fresh database

- No household history is worth keeping yet, so there is no upgrade of stored data. After this story is deployed, the household starts with a fresh, empty database.
- That removes the `policy-data` volume, which holds every stored attempt, the usage buckets, and the parent accounts. For example, run `docker compose down -v` and then `make up`. The parent account is added again with `python -m policy.accounts`, as the README describes.
- The service does not have to detect, convert, or reject a database made before this story. Running it on one is unsupported.
- `README.md` says this in its upgrade notes for this change.

# Acceptance Criteria

## Policy file

- [ ] The sample policy, rewritten in the new layout, loads on a fresh database, and the arithmetic, skip counting, and spelling tasks work as before.
- [ ] A policy with `arithmetic: { week-1: ... }` and `spelling: { week-1: ... }` loads. Both tasks are offered, each at its own address, and each keeps its own attempts, passes, and cooldown.
- [ ] The same type and name twice, in one file or across an included file, fails the load naming both places.
- [ ] A policy file in the old layout fails to load and the previous policy stays in force.
- [ ] Load errors about a task name it as `<type>/<name>`.

## Addresses

- [ ] A `revision_task` redirect goes to `/tasks/next`, which forwards to the chosen task at `/tasks/<type>/<name>`. "Next task" and the page after a give-up also go to `/tasks/<type>/<name>` addresses.
- [ ] On the child's computer, through the proxy, an arithmetic task, a skip counting task, and a spelling task can each be opened and finished at their new addresses. Spelling audio plays.
- [ ] A task named `next` opens at `/tasks/<type>/next`, and `/tasks/next` is still the picker.
- [ ] Opening `/tasks/sums`, `/tasks/work/sums`, `/tasks/spelling/sums` (the wrong type), or `/tasks/arithmetic/nothing-here` sends him to the task the picker chooses.

## History and the parent pages

- [ ] With `arithmetic: { quiz-1: ... }` passed today with a 21-day pass cooldown, replacing it with `skip_counting: { quiz-1: ... }` makes the new task available straight away. It is not retired by `max_passes: 1` and not required by the arithmetic task's skip days.
- [ ] An arithmetic attempt in progress under `quiz-1` is not resumed when `quiz-1` becomes skip counting. A new skip counting attempt starts. Putting the arithmetic task back resumes the arithmetic attempt where it was.
- [ ] Editing a task's body without changing its type or name keeps its cooldown, passes, skip days, and attempt in progress.
- [ ] Giving up `arithmetic/week-1` does not stop `spelling/week-1` from being offered in the same visit.
- [ ] Today's revision count includes a pass from earlier today for a task that has since been removed from the policy file.
- [ ] The attempt review shows each attempt's type and name. An arithmetic attempt stored under `quiz-1` is shown with the arithmetic view after `quiz-1` becomes a skip counting task.
- [ ] A parent check recorded from the parent pages shows as type `parent_check`.
- [ ] `remove-attempts --type arithmetic` lists attempts stored as arithmetic, including those whose name is now another type or is gone from the policy file, and works when the policy file does not load. `--task week-1 --type spelling` lists only the spelling task's attempts. `--task week-1` alone lists both.

# Notes

Depends on S003.1, S003.2, S003.3, S003.4, and S010.1, which it changes. It is independent of S006 and can be built before or after it. S006.1 says how its example is written if this story is done first.

The attempts table is created by `ensure_attempts` in `policy/tasks.py`. Because the database starts fresh, its schema can simply gain the type column. The rule of one attempt in progress per task becomes one per client group, type, and name. The picker's give-up cookie holds type and name.

Done stories keep the old layout in their examples as a record of what was built then. Stories not yet built use the new layout from the time this story is done.
