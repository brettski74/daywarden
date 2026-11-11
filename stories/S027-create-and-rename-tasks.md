Ticket: S027
Title: Create and rename tasks
Status: Draft
Story Points: 21
Last Updated: 2026-11-10 18:40:00
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
      characters are allowed. A name that breaks a rule shows the problem under the Name box, such as "A name is at
      most 40 characters.", and blocks Save as in S025.
- [ ] A name is taken when a task in the policy has it, or when stored attempts use it, as they do for a task that
      was removed. Case is ignored, so `Sums` is taken by `sums`. Save is refused, nothing is written, and the status
      bar says why: "A task named sums already exists." or "Attempts are still stored under sums, from a task no
      longer in the policy. Choose another name, or remove them with `bin/daywarden remove-attempts --task sums`."
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
      such as "Add a number." under an empty Operands table.
- [ ] From the lock-in until the task is written, the page has unsaved changes: leaving, Back, and Reload ask first
      as in S023.2, and leaving loses the new task.
- [ ] The next Save writes the task to its own new file in `tasks.d`. It is checked, applied, and refused exactly as
      a task page's save is in S023.2, including the hand-edit checks. A task the policy check refuses, such as one
      with no client group, is not written, and the status bar lists the errors.
- [ ] The new file holds only `tasks:` and the one task, with empty fields left out, lists written as S025 writes
      them, and no comments. It is owned by the host user, and `dw check` passes on it.
- [ ] After that save the address becomes `/parent/tasks/<name>`, the task is listed under Task Administration in
      name order and marked as the open page, and the page works as any task page from then on. The child's picker
      offers the task by the same rules as any other.
- [ ] The save is one commit in the config history, `<time> <parent>: created task <name>`, which adds the new file.
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
      were. It is checked, applied, and refused as a save is in S023.2. The page moves to `/parent/tasks/<new name>`,
      the sidebar lists the new name in name order, and the old address shows S023.2's not-found message.
- [ ] When the task is in a file in `tasks.d` and is the only task in it, the file is renamed to the new name's file
      name. The task's own file is not a clash, so a rename whose file name comes out the same, such as `sums` to
      `Sums` in `sums.yaml`, keeps the file. A task in the root policy file, in a file outside `tasks.d`, or sharing
      its file with another task keeps its file.
- [ ] The rename is one commit, `<time> <parent>: renamed task <old> to <new>`. When the file was renamed,
      `git log --follow` on the new file shows its earlier versions.
- [ ] The task's history moves with it. Its passes, cooldowns, skip days, `max_passes` count, and any attempt in
      progress carry on under the new name. `/parent/attempts` shows its earlier attempts under the new name, and
      `bin/daywarden remove-attempts --task <new>` lists them while `--task <old>` lists none.
- [ ] A spelling task's new week's setup that is not yet applied moves with it, so `/parent/tasks/<new>/week` shows
      it as it was, with its clips.
- [ ] With the task open on the child's computer during a rename, his next answer from that page sends him to the
      picker. The picker offers the renamed task, and opening it carries on the same attempt with his progress.

## Everywhere

- [ ] Without a parent session, `/parent/new-task` goes to sign-in and comes back to it afterwards. The new data
      addresses under `/parent/api/` answer 401 and never redirect.
- [ ] `docs/hierarchical-policy.md` describes creating and renaming tasks from the portal and the file name rule.

# Notes

Depends on S023.2 for the task page, the save path, and the config history, on S025 for problems that block Save and
for how lists are written, on S023.4 for the new week's setup, and on S010.1 for `remove-attempts`.

S012, making a task's identity its type and name, is not built yet. Whichever of the two is built second adapts the
other's rules: with S012, a name is taken only within its type, and the stored attempts and addresses use both.

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
