Ticket: S012
Title: Task identity is type and name
Status: Done
Story Points: 5
Last Updated: 2026-11-10 19:20:00
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
- [ ] *Added in implementation:* The same type and name twice in one file says `task 'spelling/week-1' is already
      defined at <file>:<line>:<column>`, naming the first place, as the error across files does.

## Addresses

- [ ] A `revision_task` redirect goes to `/tasks/next`, which forwards to the chosen task at `/tasks/<type>/<name>`. "Next task" and the page after a give-up also go to `/tasks/<type>/<name>` addresses.
- [ ] On the child's computer, through the proxy, an arithmetic task, a skip counting task, and a spelling task can each be opened and finished at their new addresses. Spelling audio plays.
- [ ] A task named `next` opens at `/tasks/<type>/next`, and `/tasks/next` is still the picker.
- [ ] Opening `/tasks/sums`, `/tasks/work/sums`, `/tasks/spelling/sums` (the wrong type), or `/tasks/arithmetic/nothing-here` sends him to the task the picker chooses.
- [ ] *Added in implementation:* On the selector at `/tasks/choose`, a task whose name another task shares shows its
      type in brackets, such as `week-1 (arithmetic)` and `week-1 (spelling)`. Tasks that tie are listed in order of
      name, then type. A task whose name is its own shows the name alone, as before.
- [ ] *Added in implementation:* The parent portal's task pages are at `/parent/tasks/<type>/<name>`, such as
      `/parent/tasks/spelling/spelling`, and a spelling task's new week's words at
      `/parent/tasks/spelling/<name>/week`. Task Administration lists each task by name, with its type in brackets
      where two tasks share a name, and each opens its own page. `/parent/tasks/arithmetic/nothing-here` says "There
      is no arithmetic task named nothing-here.", and the old form `/parent/tasks/spelling` shows the portal's
      page-not-found. A save is committed as `<time> <parent>: saved task <type>/<name>`.

## History and the parent pages

- [ ] With `arithmetic: { quiz-1: ... }` passed today with a 21-day pass cooldown, replacing it with `skip_counting: { quiz-1: ... }` makes the new task available straight away. It is not retired by `max_passes: 1` and not required by the arithmetic task's skip days.
- [ ] An arithmetic attempt in progress under `quiz-1` is not resumed when `quiz-1` becomes skip counting. A new skip counting attempt starts. Putting the arithmetic task back resumes the arithmetic attempt where it was.
- [ ] Editing a task's body without changing its type or name keeps its cooldown, passes, skip days, and attempt in progress.
- [ ] Giving up `arithmetic/week-1` does not stop `spelling/week-1` from being offered in the same visit.
- [ ] Today's revision count includes a pass from earlier today for a task that has since been removed from the policy file.
- [ ] *Changed in implementation:* `/parent/attempts` has a Type column beside Task, and an attempt's page lists its
      Type in the summary, both from the type stored with the attempt. An arithmetic attempt stored under `quiz-1` still
      shows Type `arithmetic` after `quiz-1` becomes a skip counting task. The tasks named in the summary above the list
      are written `<type>/<name>`. S004.6's arithmetic view is not built, so no attempt has a view of its own yet; the
      attempt page shows the stored answers for every type.
- [ ] A parent check recorded from the parent pages shows as type `parent_check`.
- [ ] `remove-attempts --type arithmetic` lists attempts stored as arithmetic, including those whose name is now another type or is gone from the policy file, and works when the policy file does not load. `--task week-1 --type spelling` lists only the spelling task's attempts. `--task week-1` alone lists both.
      *Changed in implementation:* the command is `bin/rm-attempts`. Its listing has a type column, and a `--type` no
      attempt has says only "no attempts match".

# Notes

Depends on S003.1, S003.2, S003.3, S003.4, and S010.1, which it changes. It is independent of S006 and can be built before or after it. S006.1 says how its example is written if this story is done first.

The attempts table is created by `ensure_attempts` in `policy/tasks.py`. Because the database starts fresh, its schema can simply gain the type column. The rule of one attempt in progress per task becomes one per client group, type, and name. The picker's give-up cookie holds type and name.

Done stories keep the old layout in their examples as a record of what was built then. Stories not yet built use the new layout from the time this story is done.

# Implementation

## Files Added

- `tests/test_task_identity.py`: the S012 checks end to end: shared names across types, duplicates in one file and
  across an include, `type/name` in load errors, two-part addresses and what goes to the picker, tie order and
  selector labels, give-up of one of two same-named tasks, history kept per type, editing a body, and today's score
  counting a removed task's pass.
- `policy/portal/src/taskRef.ts`: a task's type and name in the portal, its address, and its sidebar label.

## Files Changed

- `policy/tasks.py`: `TaskKey(type, name)`, `Task.key` and `Attempt.key`; the attempts table gains `task_type`, and
  its indexes and the one-in-progress rule use client group, type, and name. Every history rule and store method takes
  a key. The upgrade from before task sets is gone.
- `policy/hierarchy.py`: `tasks:` is read as type, then name. Duplicate and other task errors name `type/name`; a
  repeated key in one file names where it was first written. `Policy.task` and `task_files` are keyed by type and name.
- `policy/selection.py`, `policy/task_page.py`, `policy/app.py`: `/tasks/<type>/<name>` and its `/audio/`;
  `/tasks/work/` is gone and any one-part address other than the picker and selector goes to the picker. Ties are
  ordered by name, then type. Selector labels add the type when names clash.
- `policy/arithmetic_page.py`, `policy/parts_of_speech_page.py`, `policy/skip_counting_page.py`,
  `policy/spelling_page.py`: look up the attempt and the audio path by key.
- `policy/review.py`: type on each attempt row and page, `type/name` in the summary, parent checks stored as type
  `parent_check`.
- `policy/maintenance.py`: `--type` matches the stored type and no longer loads the policy for it; the listing has a
  type column.
- `policy/task_edit.py`, `policy/task_admin.py`, `policy/week.py`, `policy/portal.py`: tasks found, rewritten, and
  addressed by type and name; `/parent/api/tasks/<type>/<name>/...`; the task list is `{type, name}` pairs.
- `policy/portal/src/routes.tsx`, `components/Layout.tsx`, `components/Sidebar.tsx`, `pages/Task.tsx`,
  `pages/Week.tsx`, `pages/Spelling.tsx`, `pages/Attempts.tsx`, `pages/Attempt.tsx`: `/parent/tasks/:type/:name`,
  sidebar labels, and the Type column.
- `config/tasks.d/*.yaml`: rewritten in the new layout.
- `docs/hierarchical-policy.md`, `README.md`: the layout, identity, addresses, `rm-attempts`, and the upgrade note.
- Tests: `tests/conftest.py` gains `merge_task_types` so a test can join tasks of one type; every test that writes a
  policy, names a task, or opens a task address now uses the new layout, keys, and addresses. The test of the
  pre-task-set upgrade is removed with the upgrade. The portal tests follow the new addresses and cover the sidebar
  labels and the Type column.

## Files Removed

None.

## Change Summary

A task's identity is `TaskKey(type, name)`, written `type/name`. The loader reads `tasks:` as a mapping of types to
mappings of names, so the old layout fails as an ordinary malformed file: each old field shows up as a task that is
not a mapping. Every problem raised inside a task is rewritten to name the task after its location, so field errors
that used to give only a line and column now name `type/name` too.

Each attempt row stores `task_type` beside `task_name`, and every rule that reads history matches on both. The
history functions check that they were given a key, so passing a bare name fails at once rather than quietly matching
nothing. The database is not upgraded: the old task-set upgrade could not produce the new column, so it was removed
rather than left half working.

The parent portal's task pages came after this story was written (S023), so they were brought along: their page and
data addresses carry the type, the YAML editor finds a task under its type, and the commit message names
`type/name`. The new week's setup in `.weeks/` stays keyed by name, because only spelling tasks have one. This, with
the many tests that write policies, made the story noticeably larger than its 5 points.

The "give-up cookie" in the Notes no longer exists: S018 stopped leaving given-up tasks out of the picker, so giving
up one task cannot hide another.

## Suggested Acceptance Testing

### Acceptance test cases for S012

1. **Fresh start with the sample policy.** Follow the README upgrade note: `docker compose down -v`, `make up`, then
   add the parent account. Check `dw check` passes on `config/policy.yaml`. On the child's computer, open
   `/tasks/next` and finish an arithmetic, a skip counting, and a spelling task at their `/tasks/<type>/<name>`
   addresses, with spelling audio playing. Covers the sample policy check and the Addresses checks for working
   tasks, the picker, "Next task", and the page after a give-up.
2. **Shared names.** Add `arithmetic: { week-1: ... }` and `spelling: { week-1: ... }` to a file in `tasks.d` and
   `dw reload`. Open `/tasks/choose` and see both, labelled with their types. Pass one, give up the other, and check
   each keeps its own attempts on `/parent/attempts`, and the given-up one's twin is still offered. In the portal,
   open both from Task Administration and save a field on one. Covers the shared-name check, the selector and portal
   label checks, give-up, and the portal address check.
3. **Load errors.** Write the same type and name twice in one file, then in two files; write a task in the old layout;
   give a task a bad field. Each `dw reload` refuses, names both places for the duplicates and `type/name` for the
   rest, and the previous policy stays in force. Covers the Policy file checks.
4. **Other addresses.** Open `/tasks/sums`, `/tasks/work/sums`, `/tasks/spelling/sums`, and
   `/tasks/arithmetic/nothing-here`; each goes to the picker. Add a task named `next` and open
   `/tasks/<type>/next`, then `/tasks/next`. Covers the remaining Addresses checks.
5. **History by type.** With `arithmetic: { quiz-1: { pass_cooldown: 21, max_passes: 1 } }`, pass it, and start
   another attempt from a bookmark and leave it open. Replace it with `skip_counting: { quiz-1: ... }`: it is offered
   at once and starts a new attempt. Put the arithmetic task back and the open attempt carries on. Then edit its body
   only and check its cooldown and open attempt survive. Remove a task passed today and check today's score on
   `/parent/attempts` still counts it. Covers the History checks.
6. **Parent pages and the command line.** On `/parent/attempts`, check the Type column, the `type/name` summary, an
   attempt page's Type after its name changed type, and a parent check shown as `parent_check`. Run
   `bin/rm-attempts --type arithmetic`, `--task week-1 --type spelling`, and `--task week-1`, then `--type arithmetic`
   with a broken `policy.yaml`. Covers the attempt review, parent check, and `remove-attempts` checks.
