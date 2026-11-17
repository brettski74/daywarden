Ticket: S023
Title: Task administration in the parent portal
Status: Done
Story Points: 60
Last Updated: 2026-11-08 21:30:00
---

# User Voice

As a parent, I want to look after each task from the parent portal, so that changing a cooldown, swapping a word's
pool, fixing a bad recording, or setting up next week's spelling words does not mean editing YAML, running
`bin/cut-clips`, and shuffling files around by hand.

# Use Cases

## UC1 - Find a task

- The parent opens Task Administration in the sidebar. It expands into a list of every configured task, indented under
  it. Clicking Task Administration again collapses it.
- Clicking a task opens its administration page in the content pane.

## UC2 - Change a task's common settings

- The top of every task page shows the settings every task has, such as the cooldowns, the skip and pass limits, the
  dates, and the client groups, in three columns.
- The parent changes them and saves with Save or Ctrl+S. The change is written to the policy file that defines the task
  and applied as `dw reload` would apply it.

## UC3 - Look after the spelling words

- Below the common settings, the spelling page lists every word in the current pool, the revision pool, and the attic.
  The parent plays each word and sentence, moves a word between pools, and retires a word to the attic.
- The parent re-records a word, its sentence, or both with the browser's microphone, hears the result, and keeps it or
  discards it.

## UC4 - Set up the new week's words

- The parent types the coming week's words and sees which ones already exist and which have recordings.
- They record everything in one take, or only the missing pieces, then review the clips one by one.
- Apply makes the week's words the current pool and moves last week's current words to revision.

# Acceptance Criteria

- [ ] S023.1, S023.2, S023.3, and S023.4 are done.
- [ ] Every change to the config directory, whether saved from the portal or applied with `dw reload` or `dw up`, can
      be found and restored from the git history in the config directory.
- [ ] A normal week's spelling change, with new words, recordings, and the rotation of last week's words, can be done
      entirely from the parent portal, with no shell, no YAML editing, and no `bin/cut-clips`.
- [ ] The child, using only the task site, cannot open a task administration page, play a recording through it, or
      change a task.

# Child stories

| Ticket | Title | Points |
| --- | --- | --- |
| S023.1 | Keep a history of the config directory in git | 5 |
| S023.2 | Task pages, common settings, and the spelling word list | 21 |
| S023.3 | Record a word or sentence in the browser | 13 |
| S023.4 | Set up the new week's spelling words | 21 |

# Notes

This epic takes over spelling, and the common task settings, from S007.3. Editing each of the other task types
(arithmetic, skip counting, parts of speech) is expected to need its own story or epic, written once this epic has
settled the page layout. S007.3 is cut back to a placeholder for them. If one of those types turns out small enough to
be a single story, it can take the S007.3 number.

Creating and deleting tasks is not part of this epic. When the portal does create tasks, it writes each new task to its
own file in a `tasks/` subdirectory of the config directory, and the root `policy.yaml` gets one directory include for
`tasks`. Editing an existing task, as in this epic, rewrites the task in whichever file already defines it.

The children are split along features a parent can see. S023.1 comes first, so the config history is in place, and
protecting hand edits, before the portal writes anything. S023.2 carries the risk the rest does not: the decisions
service starts writing to the config directory and the data directory, which are both read-only today. That should be
seen working and accepted before recording is built on top of it.

The config history covers the YAML policy files only. Spelling recordings live in the data directory, which is not
under version control. The attic is what protects a retired word.
