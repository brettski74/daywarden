Ticket: S047
Title: Config history in the portal and MCP
Status: Refined
Story Points: 13
Last Updated: 2026-11-22 17:12:30
---

# User Voice

As an admin parent, I want to see every saved version of the configuration, compare any two, and go back to an earlier
one from the portal or through an agent, so that a bad change can be undone without `git` on the server and without
losing any version in between.

# Behaviour

## History list

Config History is a new page in the Settings group of the sidebar, at `/parent/settings/history`. A revision is one
commit in the config history from S023.1.

- [ ] The page lists the revisions newest first, 50 to a page, with Newer and Older links that change `?page=` in the
      address. Each row shows the time in household-local time as `yyyy-mm-dd HH:MM`, who made it, what was done, and
      the files it changed. After a task save in the portal by `brett`, the top row is that save, by `brett`, with
      `saved task spelling` and `tasks.d/spelling.yaml`.
  - Who: the commit's author, such as a parent's username, or the host login for `dw` and `install.sh`.
  - What: the commit message without its leading time and `<user>: `, so `2026-11-17 20:15 -0500 ada via Claude
    Code: saved task arithmetic/times-7` shows as `via Claude Code: saved task arithmetic/times-7`, by `ada`. A
    message in any other form, such as one made with `git commit` by hand, is shown whole.
  - Each row's time is a link to that revision's page.
- [ ] Each file name in a row is a link to the list filtered to that file, `?file=tasks.d/spelling.yaml`, which shows
      only the revisions that changed it, with a way back to the whole list. A file that has since been removed can
      still be filtered on.
- [ ] When the config directory has uncommitted hand edits, the page says so above the list and names the files. They
      are committed by the next `dw reload` or portal save, as in S023.1 and S023.2.
- [ ] Where the config directory has no history of its own, as in a clone of the daywarden repository, the page says
      so instead of a list, and the revision pages and Revert are not offered.

## Revision page and comparing

A diff shows each file that differs, marked added, changed, or removed, with each changed part and three lines of
context. Added and removed lines carry `+` and `-` as well as their colours, which are new role properties in the theme.

- [ ] A revision's page, `/parent/settings/history/<revision>`, shows the row's details, its full revision id, and the
      diff of what it changed against the revision before it. The first revision shows every file as added. A short or
      full id both open the page, and an unknown one shows the portal's not-found page.
- [ ] The page links to Compare with current, the comparison from this revision to the newest one.
- [ ] The list has From and To radio buttons on each row and a Compare link, which opens
      `/parent/settings/history/compare?from=<revision>&to=<revision>`. The page shows the diff between the two, in
      that direction, with each revision's time and author at the top. Two revisions with the same files say that
      nothing differs.

## Revert

- [ ] A revision's page has Revert to this version, except on the newest revision. It opens the portal's own dialog,
      with Cancel the default, which shows the diff from the newest revision to this one that the revert will make.
      Pressing Cancel changes nothing.
- [ ] Revert puts every file in the config directory back as it was at that revision, except `mcp.yaml`, which stays
      as it is now. A file added since is removed, and a file removed since comes back. The dialog says that the MCP
      settings are kept.
- [ ] The reverted files are checked as `dw check` checks them. When the check fails, nothing is written or
      committed, and the dialog lists the errors. An old revision whose spelling task names a directory no longer in
      the data directory is refused this way.
- [ ] A revert that passes is applied with a reload, as a save is, and committed as one new revision with the message
      `<time> <user>: reverted to <short id> (<that revision's time>)`. Every revision from before the revert is still
      in the list, and Compare from the revision reverted to, to the new one, shows nothing differs apart from
      `mcp.yaml`.
- [ ] A revert can itself be reverted, which brings back the configuration from before it.
- [ ] Uncommitted hand edits are handled before a revert as before a portal save in S023.2: committed first as their
      own revision when they pass the check, and refusing the revert with the errors when they do not.
- [ ] When the newest revision is no longer the one the dialog was opened on, because something was saved
      meanwhile, Revert is refused, and the dialog says the configuration changed and to look again. Nothing is
      written.
- [ ] When a revision changes nothing apart from `mcp.yaml`, Revert says so, and nothing is committed.
- [ ] When the revert crosses a rename made in the portal, the dialog lists each one, such as "Client group kids was
      renamed to younger after this version. Attempts and usage recorded under younger stay under younger." The rows
      are not moved.
- [ ] When the commit fails, the revert still stands and is applied, and the status bar warns that it is not in the
      history, as for a save in S023.2.

## MCP tools

A new permission class, `config_history`, with read and update, is on the MCP page and in `mcp.yaml`. A revision in
these tools is a short or full id, and `current` means the newest revision.

- [ ] `list_config_history` (config_history: read) returns revisions newest first, each with its full and short id,
      household-local time, author, message, and files changed. It takes `limit` (default 50), `before`, a revision
      to list older revisions from, and `file`, which keeps only revisions that changed that file.
- [ ] `get_config_revision` (config_history: read) returns a revision's details and the text of each of its files as
      it was then, or of one file when `file` is given. An unknown revision or file is an error naming it.
- [ ] `diff_config_revisions` (config_history: read) takes `from` and `to`, with `to` defaulting to `current`, and
      returns the diff as each file's unified diff text, with whether it was added, changed, or removed. Given
      `revision` instead of `from`, it returns what that revision changed against the one before it.
- [ ] `revert_config` (config_history: update) takes `revision` and `dry_run`, and reverts as Revert does, with the
      same checks, refusals, rename warnings, and `mcp.yaml` kept. A dry run answers with the diff and warnings and
      changes nothing. The commit names the approving parent and the agent, as the other write tools do in S036.2,
      such as `ada via Claude Code: reverted to 3f2a9c1 (2026-11-17 20:15)`, and the activity log shows the call as in
      S036.2.
- [ ] A reviewer's agent cannot use these tools, which answer "This needs an admin's approval.", as for any class
      outside the reviewer's in S043.
- [ ] Where the config directory has no history of its own, each tool answers that there is no config history.

## Access

- [ ] Config History is admin-only. A reviewer has no sidebar entry, and its pages and the data addresses under
      `/parent/api/` answer as for any admin-only page in `docs/parent-portal.md`. Without a session, the pages go to
      sign-in and come back to the same page, and the data addresses answer 401 and never redirect.
- [ ] The revert dialog's request is a JSON POST, refused with 415 otherwise, as every action in
      `docs/parent-portal.md` is.

# Notes

Depends on S023.1 and S023.2 for the history and the portal's commits, S036.2 for the MCP write conventions, and S043
for roles.

- Reverting never rewrites history. Build the new tree from the old revision's files with `mcp.yaml` swapped for the
  current one, check it in a staging copy before anything is written, then write, reload, and commit on top of the
  newest revision through `History` in `policy/history.py`. Nothing runs `git reset`, `git revert`, or moves a branch.
- `mcp.yaml` is kept so that a revert never silently widens or narrows what an agent may do. Changing the MCP settings
  stays the MCP page's job.
- Renames crossed are found from the commit messages between the revision and the newest one, which the portal writes
  as `renamed <kind> <old> to <new>` (`policy/policy_admin.py`, `policy/task_create.py`, `policy/pool_admin.py`). A
  rename made by hand is not detected.
- `config_history: read` lets an agent read every file in the config directory, including sections it has no read
  permission for. The MCP page's description of the class says so.
- The data directory is not in the history, as in S023.1. Spelling words, recordings, attempts, and usage are not
  reverted.
- Out of scope: restoring one file from an old revision, which stays the manual `git checkout` step in the README, and
  a `dw` command for reverting.
- Sized at 13 against S036.3 (13): git log, show, and diff behind three portal pages and a diff view, one revert
  path shared by the portal and one MCP tool, and three thin read tools. The checks, reload, and commit already exist.
