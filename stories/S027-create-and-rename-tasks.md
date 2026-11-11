Ticket: S027
Title: Create and rename tasks
Status: In Progress
Story Points: 21
Last Updated: 2026-11-10 21:05:00
---

# User Voice

As a parent, I want to add a new task and rename an existing one from the parent portal, so that starting a new topic
or fixing a name does not mean writing YAML by hand, choosing a file name, and carrying the child's history across
myself.

# Behaviour

## Task names

These rules apply to a new task's name and to a rename. They are checked both when a new task's name and type are
locked in and when a task is written.

- [ ] A name is valid when it is not empty, has no space at either end, and is at most 40 characters. Any other
      characters are allowed. A name that breaks a rule blocks Save as in S025, and shows the problem under the Name
      box, such as "A name is at most 40 characters.", once the box loses focus or Save or Ctrl+S is pressed. The
      problem shown changes only then, never while the name is being typed. *Changed in implementation:* a name also may not hold a `/`
      ("A name cannot hold a /, because the task's address could not."), since S012's `/tasks/<type>/<name>` cannot
      carry one.
- [ ] *Changed in implementation, for S012:* a name is taken when a task of the same type in the policy has it, or
      when stored attempts of that type use it, as they do for a task that was removed. Case is ignored, so `Sums` is
      taken by `sums`. Save is refused, nothing is written, and the status bar says why: "An arithmetic task named
      sums already exists." or "Attempts are still stored under arithmetic/sums, from a task no longer in the policy.
      Choose another name, or remove them with `bin/rm-attempts --task sums --type arithmetic`." The same name with
      another type, such as a spelling `sums`, is not taken.
- [ ] A rename that only changes the case of the task's own name, such as `sums` to `Sums`, is not taken.

## File names

A task's file name in `tasks.d` comes from its name:

- It is lower-cased, and an accented letter folds to its closest ASCII letter or letters, such as `é` to `e` and `ß`
  to `ss`.
- ASCII letters, digits, and the ASCII dash `-` are kept.
- Every run of any other characters becomes one `_`. That includes spaces, `_` itself, punctuation, en and em dashes,
  and characters with no ASCII equivalent, such as `中`.
- When that name is already used in `tasks.d`, with either `.yaml` or `.yml`, `.2`, `.3`, and so on is added before
  `.yaml`, taking the first that is free.

- [ ] `Café Sums` gets `tasks.d/cafe_sums.yaml`, `year-3 spelling` gets `year-3_spelling.yaml`, and
      `Week 3 — Times Tables!` gets `week_3_times_tables_.yaml`.
- [ ] With `some_new_task.yaml` and `some_new_task.2.yaml` in `tasks.d`, a new task `Some New Task` gets
      `some_new_task.3.yaml`. With `sums.yml` there, holding a task named `addition`, a new task `Sums` gets
      `sums.2.yaml`.

## Create New Task

- [ ] Task Administration's list starts with Create New Task, above the tasks. It is a link to `/parent/new-task`,
      with the Lucide `square-plus` icon. Opening that address, or reloading it, shows Task Administration expanded
      with Create New Task marked as the open page.
- [ ] The page shows Tasks › New task in the context bar, with Save, then S023.2's common settings and the divider,
      with nothing under the divider. Name is a text box. Type is a pull-down of the task types as the policy file
      writes them, `arithmetic`, `parts_of_speech`, `skip_counting`, and `spelling`, with none chosen at first. It
      never offers `parent_check`, which is only how a parent records credit for work done outside daywarden. Every
      other field is shown and disabled.
- [ ] Save and Ctrl+S are enabled once the name is valid and a type is chosen. Saving checks that the name is not
      taken and writes nothing. Name and Type then become read-only, and the other common fields are enabled, empty,
      and show S023.2's placeholders, such as `1` for Pass Cooldown.
- [ ] At the same time the type's own section loads under the divider, as it would for a task whose `body` is
      empty, with its defaults as placeholders and its required fields marked as problems where its page marks them,
      such as "Add a number." under an empty Operands table. *Changed in implementation:* an arithmetic task's empty
      Operation is marked "Operation is required." under its pull-down, as Max Timeout is, on every arithmetic page.
- [ ] *Added in implementation:* on a new spelling task, the recording buttons and Retire are disabled with the
      title "Save the new task first.", the words play from the default pools, and there is no New week's words link
      until the task is written.
- [ ] From the lock-in until the task is written, the page has unsaved changes: leaving, Back, and Reload ask first
      as in S023.2, and leaving loses the new task.
- [ ] The next Save writes the task to its own new file in `tasks.d`. It is checked, applied, and refused exactly as
      a task page's save is in S023.2, including the hand-edit checks. A task the policy check refuses, such as one
      with no client group, is not written, and the status bar lists the errors.
- [ ] The new file holds only `tasks:` and the one task, with empty fields left out, lists written as S025 writes
      them, and no comments. It is owned by the host user, and `dw check` passes on it.
- [ ] *Changed in implementation, for S012:* after that save the address becomes `/parent/tasks/<type>/<name>`,
      with the outcome in the status bar, the task is listed under Task Administration in name order and marked as the
      open page, and the page works as any task page from then on. The child's picker offers the task by the same
      rules as any other. *Changed in implementation:* name order ignores case, so `Skip Twos` comes after `check`.
- [ ] *Changed in implementation, for S012:* the save is one commit in the config history,
      `<time> <parent>: created task <type>/<name>`, which adds the new file.
- [ ] When there is no `tasks.d` beside the root policy file, the save creates it, owned by the host user. When the
      root policy file does not include `tasks.d`, the save adds it to the file's `include` list, or adds an
      `include` list holding it, and keeps the rest of the file as it was. Both files are in the one commit.

## Rename

- [ ] A task's page has Rename in the context bar, beside Save, with the Lucide `text-cursor-input` icon. While the
      page has unsaved changes it is disabled, with the title "Save the changes on this page first." The new task
      page has no Rename.
- [ ] Rename makes the Name box editable, focuses it with its text selected, and disables every other field and
      action on the page, including the type's own section, Retire, and the recording buttons. Rename becomes Cancel
      rename, with the Lucide `x` icon.
- [ ] Cancel rename, or Escape in the Name box, puts the old name back and enables the page again.
- [ ] Save and Ctrl+S are enabled once the name differs from the old one and is valid. A changed name is an unsaved
      change for leaving the page, as in S023.2.
- [ ] Saving renames the task in its file, keeping the file's comments, its layout, and every other entry as they
      were. It is checked, applied, and refused as a save is in S023.2. *Changed in implementation, for S012:* the
      page moves to `/parent/tasks/<type>/<new name>`, with the outcome in the status bar, the sidebar lists the new
      name in name order, and the old address shows S012's "There is no <type> task named <old name>.".
- [ ] When the task is in a file in `tasks.d` and is the only task in it, the file is renamed to the new name's file
      name. The task's own file is not a clash, so a rename whose file name comes out the same, such as `sums` to
      `Sums` in `sums.yaml`, keeps the file. A task in the root policy file, in a file outside `tasks.d`, or sharing
      its file with another task keeps its file.
- [ ] *Changed in implementation, for S012:* the rename is one commit,
      `<time> <parent>: renamed task <type>/<old> to <type>/<new>`. When the file was renamed, `git log --follow` on
      the new file shows its earlier versions.
- [ ] The task's history moves with it. Its passes, cooldowns, skip days, `max_passes` count, and any attempt in
      progress carry on under the new name. `/parent/attempts` shows its earlier attempts under the new name, and
      *changed in implementation, for S012,* `bin/rm-attempts --task <new> --type <type>` lists them while
      `--task <old> --type <type>` lists none. Attempts of another type under the old name stay where they are.
- [ ] A spelling task's new week's setup that is not yet applied moves with it, so
      `/parent/tasks/spelling/<new>/week` shows it as it was, with its clips.
- [ ] With the task open on the child's computer during a rename, his next answer from that page sends him to the
      picker. The picker offers the renamed task, and opening it carries on the same attempt with his progress.

## Everywhere

- [ ] Without a parent session, `/parent/new-task` goes to sign-in and comes back to it afterwards. The new data
      addresses under `/parent/api/` answer 401 and never redirect.
- [ ] `docs/hierarchical-policy.md` describes creating and renaming tasks from the portal and the file name rule.

# Notes

Depends on S023.2 for the task page, the save path, and the config history, on S025 for problems that block Save and
for how lists are written, on S023.4 for the new week's setup, and on S010.1 for `remove-attempts`.

S012, making a task's identity its type and name, was built first, so this story follows its rules: a name is taken
only within its type, and the stored attempts, addresses, and commit messages use both. S012 also renamed
`bin/daywarden remove-attempts` to `bin/rm-attempts`.

Design hints:

- The new task page is at `/parent/new-task`, not under `/parent/tasks/`, so that no task's name can clash with it.
- The lock-in is a service call that checks the name and writes nothing. The type's section is given the page data a
  task with an empty body would have, built by the same code that builds it for a written task.
- The rename rewrites only the task's key in `policy/task_edit.py`, as other fields are rewritten today. The file
  rewrite, the file rename, the move of the week's setup in `.weeks/`, and the update of the stored attempts happen
  together or not at all. A failure partway undoes the steps already done. The automated tests cover that, since it
  cannot be seen from outside.
- The file is renamed on disk as one of those steps, not with `git mv`, and the commit is given both the old and the
  new path, which `History.commit` stages with `git add --all`. That makes the same commit `git mv` would. Git records
  no renames, and `git log --follow` finds one by comparing the two files' contents. Only the key line changes, so it
  finds this one either way. `git mv` would fail where the config directory has no history of its own, which S023.2
  allows. It would also stage the rename before the other steps had all worked, leaving the index to undo as well when
  one fails.
- The accent folding can use Unicode decomposition with combining marks dropped, plus a short table for letters that
  do not decompose, such as `ß`, `æ`, `ø`, and `ł`. A library for it would be pinned in `policy/requirements.txt`.

A new spelling task uses the default pool directories, so it shares its words with any spelling task that also uses
them, as S023.2 allows. S028 makes the directories configurable.

Out of scope: deleting a task, changing a task's type, moving a task to another file, and copying a task.

Sizing: creating a task is about 13 points. The page's lock-in, each of the four types' sections starting from an
empty body, the new file and its name, and adding the `include`, are about the effort of S025. Renaming is about 8:
the key rewrite, the file rename, moving the history and the week's setup together, and the child's open page. That
makes 21, with 27 checks. It is one story rather than an epic because both halves rewrite the same save path in
`policy/task_admin.py` and the same context bar, and moving the stored attempts is a rename of one column's value,
not an upgrade of the database.

# Implementation

## Files Added

- `policy/task_names.py`: the name rules, the file name a name gives, and the first free file for it in a directory.
- `policy/task_create.py`: `TaskChanges`, the new task page's data, the lock-in, creating a task in `tasks.d` with the
  `include` added, renaming a task with its file, attempts, and new week's setup, and the taken-name check.
- `tests/test_task_create.py`: the name and file name rules, the lock-in for each type, creating, renaming, the
  rollback of a failed create and a failed rename, the child's open page, and the 401 and 415 answers.
- `policy/portal/src/newTask.test.tsx`: the new task page and Rename in the portal.

## Files Changed

- `policy/tasks.py`: `AttemptStore.names` lists the names stored with a type, and `AttemptStore.rename` moves a
  task's attempts to a new name in one transaction.
- `policy/hierarchy.py`: an override for a file not written yet, in an included directory, is loaded as though the
  file were there, even when the directory is missing too.
- `policy/task_edit.py`: `rename_task` rewrites only a task's key, `new_task_text` writes a new task's file, and
  `included` and `add_include` read and extend a file's `include` list.
- `policy/task_admin.py`: `write` is now built on `change`, which takes the files to check in place and a list of
  `Step`s, each with its undo. `page_body` builds a page from a written task or an empty one. `pool_file` serves a
  recording from any pool settings. The task list sorts by name ignoring case.
- `policy/parts_of_speech_admin.py`: a body with no `sentences` has no problem of its own, so the page's "There are no
  sentences" stands alone.
- `policy/portal.py`: `GET /parent/api/new-task`, `POST /parent/api/new-task/check`, `POST /parent/api/new-task`,
  `GET /parent/api/new-task/audio/<pool>/<file>`, and `POST /parent/api/tasks/<type>/<name>/rename`.
- `policy/portal/src/taskRef.ts`: the new task address and the name rules, as the service checks them.
- `policy/portal/src/routes.tsx`, `components/Sidebar.tsx`: the `/new-task` route, and Create New Task at the top of
  Task Administration.
- `policy/portal/src/pages/Task.tsx`: the editor serves the new task page and gains Rename, with the Name box, the Type
  pull-down, and the disabled areas.
- `policy/portal/src/pages/Spelling.tsx`: a task not written yet plays from the default pools and cannot retire or
  record.
- `policy/portal/src/pages/PartsOfSpeech.tsx`: Alt+N does nothing while the section is disabled.
- `policy/portal/src/arithmetic.ts`, `pages/Arithmetic.tsx`: an empty Operation is a problem marked under it.
- `policy/portal/src/styles/layout.css`, `styles/theme.css`: the `lock-area` fieldset, the look of disabled and
  read-only boxes with the new `--input-disabled-bg` role, and a marked pull-down's border.
- `policy/portal/src/tasks.test.tsx`: the sidebar list starts with Create New Task.
- `docs/hierarchical-policy.md`: creating and renaming tasks, the name rules, and the file name rule.
- `docs/parent-portal.md`: the new state-changing requests, and fields shown disabled together.

## Files Removed

None.

## Change Summary

The new task page is the task page's editor started with no task. Its first Save posts the name and type to
`/parent/api/new-task/check`, which checks them and answers with the page a task with an empty body would have, built
by the same `page_body` a written task uses. From then on the page edits that data as any task page does, and its next
Save posts the whole page, with the name and type, to `/parent/api/new-task`. The service builds the task's fields
with the same `_changes` a save uses, against an empty task, and writes them as a block mapping with groups first,
then the common fields in page order, then the body.

Every save, create, and rename now goes through `TaskAdmin.change`. It checks hand edits, loads the whole policy with
the planned text in place, and then makes its steps in order. A create's steps are making `tasks.d`, writing the new
file, and adding the `include`. A rename's steps are rewriting the key, renaming the file, moving the `.weeks` folder,
and renaming the attempts, in that order. The database step comes last, and a failure there rolls back in its own
transaction. When a step fails, the steps before it are taken back in reverse. The check before a create loads the new file
from memory, through the loader's overrides, so nothing is written until the policy is known to load. A rename is
checked with the new text under the old file name. The loader reads a file's name only for its messages and its place
in the directory's order, so the result is the same.

The renamed file is renamed with `os.rename`, never over another file, and both paths are given to the commit, as the
Notes suggested. A new file is written to a hidden file first and then linked into place, so it never replaces a file
another process made in the meantime, and nothing reading `tasks.d` sees half a file.

The accent folding uses Unicode decomposition with combining marks dropped and a short table for the letters that do
not decompose, so no library was added. The portal checks a name with the same rules as the service, so the problem
shows as the parent types, and the service checks again.

The child's open page needs nothing new. Its next answer after a rename names a task no longer in the policy, so the
service answers with the existing reload, and the reload of the old address goes to the picker.

## Suggested Acceptance Testing

### Acceptance test cases for S027

1. **Create a task.** On the running stack, open Task Administration, then Create New Task. Check the page before the
   lock-in, then type `Café Sums`, choose `arithmetic`, and Save. Check the lock-in, the arithmetic section's marked
   fields, and that leaving asks. Fill in Operation, the timeouts, the target, an operand, a client group, and a Pass
   Cooldown, and Save. Check the address, the sidebar, `config/tasks.d/cafe_sums.yaml`, `dw check`, the commit in
   the config history on an installed machine, and that the child's picker offers it. Covers Create New Task and
   the first File names check.
2. **No `tasks.d` and no `include`.** On a scratch copy of the config, or with `tasks.d` moved aside and its
   `include` line removed from `policy.yaml`, create a task. Check that `tasks.d` is made, owned by the host user,
   that `policy.yaml` gains the `include` with nothing else changed, and that both are in one commit. Then try
   saving a new task with no client group, and check that nothing is written and the status bar lists the error.
   Covers the last two Create New Task checks.
3. **Names.** On the new task page, type a name with a space at either end, 41 characters, and a `/`, and read
   each problem. Lock in `SPELLING` as `spelling`, and `spelling` as `arithmetic`. Record attempts under a task,
   remove it from the policy, then try its name again, and follow the `bin/rm-attempts` hint. Put
   `some_new_task.yaml`, `some_new_task.2.yaml`, and a `sums.yml` holding `addition` in `tasks.d`, then create
   `Some New Task` and `Sums`, and try `year-3 spelling` and `Week 3 — Times Tables!`. Covers Task names and
   File names.
4. **Rename on the page.** On a task page, change a field and check that Rename is disabled with its title. Save,
   then Rename: the name is selected, everything else is disabled, and Cancel rename and Escape put the name back.
   Type a new name, try leaving, then Save. Check the address, the sidebar, the old address's message, and the
   config history. Rename a task alone in a file in `tasks.d`, one in `policy.yaml`, one sharing a file, and `sums`
   to `Sums` in `sums.yaml`, and check which files are renamed and that `git log --follow` follows the renamed one.
   Covers Rename's page, file, and commit checks.
5. **History moves with a rename.** Pass a task and leave a second attempt open on the child's computer, and set up
   a spelling task's new week with a kept clip. Rename both. Check `/parent/attempts`,
   `bin/rm-attempts --task <new> --type <type>` and `--task <old> --type <type>`, and the week page under the new
   name. On the child's computer, answer the open question: he goes to the picker, which offers the renamed task,
   and opening it carries on the same attempt. Covers the history, week, and child's page checks.
6. **A new spelling task.** Create a spelling task. Before it is written, check that its words play and that Retire,
   the recording buttons, and New week's words are not offered. Covers the Added in implementation check.
7. **Signed out.** In a private window, open `/parent/new-task`: sign-in comes back to it. Use `curl -k` to POST JSON
   to `/parent/api/new-task/check`, `/parent/api/new-task`, and `/parent/api/tasks/spelling/spelling/rename`, and
   GET `/parent/api/new-task`, without a cookie: each answers 401 with no `Location`. Read the new section of
   `docs/hierarchical-policy.md`. Covers Everywhere.
