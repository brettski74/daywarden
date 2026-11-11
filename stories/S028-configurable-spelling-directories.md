Ticket: S028
Title: Make spelling directories configurable
Status: Refined
Story Points: 21
Last Updated: 2026-11-10 20:00:00
---

# User Voice

As a parent, I want to choose a spelling task's word directories from its page, make new ones there, and fill them
with words in the browser, so that I can keep a set of words for each term or each child, and add a batch of revision
words, without editing YAML or moving files on the server by hand.

# Scenarios

## A new term's directories

The parent creates `year-4/current` and `year-4/revision` from the directory pull-downs, chooses them, and saves. The
save is refused because the new directories have no words, and the page shows them empty, with the reason. The parent
opens Words › Add to Current, types the first week's words, records them, and applies. The task now uses the
`year-4` directories, with those words current. Later, Words › Add to Revision adds a batch of last term's words to
revision.

# Behaviour

## The directory pull-downs

The four directory fields are Current Pool Directory, Revision Pool Directory, Attic Directory, and Alphabet Directory,
in the Directories group of a spelling task's page. The spelling directory is `spelling/` in the data directory.

- [ ] Each directory field is a pull-down showing its directory relative to the spelling directory. A task that sets
      none shows `current`, `revision`, `attic`, and `alphabet`, and one with `attic_dir: spelling/old-words` shows
      `old-words` as its Attic Directory.
- [ ] Open, each pull-down lists every directory under the spelling directory, at any depth, relative to it and in name
      order, each with the Lucide `folder` icon, such as `alphabet`, `attic`, `current`, `revision`, `year-3`, and
      `year-3/current`. A directory whose name, or a parent's name, starts with `.` is not listed. The list is read
      when the page loads, so a directory made by hand on the server shows after a reload.
- [ ] The field's own directory is highlighted with a tick. When it is missing on disk, such as an attic no Retire has
      made yet, it is still listed and chosen, marked "(missing)". A directory outside the spelling directory, set by
      hand, such as `current_dir: words/year-3`, is listed and chosen as its path from the data directory, marked
      "(outside spelling)".
- [ ] Last in every list, under a divider, is New directory… with the Lucide `folder-plus` icon, so a directory named
      `New directory` would still look like a directory.
- [ ] Each pull-down opens and closes with the shared animation, and its keys and clicks work as the Client Groups
      pull-down's do in S023.2, except that choosing an option closes it.
- [ ] Choosing another directory is an edit. The field is marked as changed, and the Unsaved changes marker, Save,
      Ctrl+S, and the unsaved-changes prompt work as in S023.2. Choosing the saved directory again is not a change.

## A new directory

- [ ] New directory… closes the pull-down and opens a dialog titled New directory, with a text box labelled "Name,
      under spelling/", which has the focus, and OK and Cancel. The field keeps its value meanwhile.
- [ ] Cancel or Escape closes the dialog, creates nothing, leaves the field as it was, and puts the focus back on the
      pull-down.
- [ ] OK or Enter sends the name to the server, and OK is disabled until it answers. A space at either end of the name
      is ignored. A name the server refuses keeps the dialog open with the name as typed, and shows why under the box,
      such as "`year-3/current` already exists." or "A part of the name may only have letters, digits, spaces, -, _,
      and .".
- [ ] A name is valid by these rules. Each one has its own message.
  - The name is one or more parts separated by single `/` characters, with no `/` at either end.
  - Each part has only letters, digits, spaces, `-`, `_`, and `.`, does not start with `.` or a space, does not end
    with a space, and is at most 255 bytes.
  - Nothing at that path already exists, as a directory or as a file, when compared without regard to case. With
    `current` there, `Current` is refused, and with a file `notes.txt` in the spelling directory, so is `notes.txt`.
  - No part before the last is an existing file, so `notes.txt/words` is refused too.
- [ ] A valid name makes the directory at once, with any missing parent directories, owned by the host user. With no
      `year-3` there, `year-3/current` makes both. The dialog closes, the field is set to the new directory as an
      unsaved edit, and every directory pull-down on the page lists it.
- [ ] Making a directory is not part of Save and makes no commit in the config history. Leaving the page without
      saving keeps the new directory on the server, empty, and the field as the file has it.
- [ ] With the parent's session ended, OK keeps the dialog open with the name, and says to sign in again in another
      tab, as the recording dialog does in S023.3.

## Saving the directories

- [ ] Saving writes each changed field as its path from the data directory, such as
      `revision_dir: spelling/year-3/revision`. Choosing a field's default directory, such as `revision` for Revision
      Pool Directory, removes the field from the file. The save is checked, applied, and committed as in S023.2.
- [ ] Two of a task's four fields on the same directory show "Current Pool Directory and Revision Pool Directory are
      the same directory." under the second field and block Save as in S025.
- [ ] While a directory change is unsaved and has not been refused, the word list is replaced by "Save to see the
      words in the new directories." While a word's pool change is unsaved, the four pull-downs are disabled, with the
      title "Save the word moves first."
- [ ] A save that changes a directory and would leave the policy unable to load is refused, and nothing is written, as
      in S023.2. The page keeps the chosen directories as unsaved edits and lists the words in them, and the status
      bar lists the errors followed by "Add words to the new directories from the Words menu. Its Apply saves the
      directories with the words." Two new, empty pool directories are always refused this way, since a task with no
      words has nothing to ask.
- [ ] In that list, a word's pool can be changed and is saved with the directories. Retire and the recording buttons
      are disabled, with the title "Save the directory change first.", because they act at once.
- [ ] After a save, the word list shows the words in the new directories, and the next spelling run asks them. Pool
      moves, Retire, and re-recording work on the new directories as in S023.2 and S023.3.
- [ ] A spelling run the child has started keeps playing its words for the rest of that run after the task's
      directories change. His next run uses the new directories.

## The Words menu

The setup page is S023.4's New week's words page. Each mode below uses it, and works as S023.4 describes, except where
a check here says otherwise. A task still has one setup in progress at a time.

- [ ] The spelling page's New week's words link becomes a Words menu button in the context bar, with the Lucide
      `list-plus` icon. It opens, with the shared animation, a menu of three links: Add to Current, Add to Revision,
      and Replace Current. The arrow keys move between them, Enter follows one, and Escape or a click elsewhere closes
      the menu.
- [ ] The links go to `/parent/tasks/spelling/<name>/words/add-current`, `.../words/add-revision`, and
      `.../words/replace-current`. Each address shows the setup page with Tasks › `<name>` › Add to Current, Add to
      Revision, or Replace Current in the context bar. The old `.../week` address goes to `.../words/replace-current`.
- [ ] Replace Current is S023.4's new week: its Apply moves every current word that is not listed into revision.
- [ ] Add to Current's Apply puts every listed word in the current pool and moves no word that is not listed. A new
      word's clips are written there, a listed revision or attic word moves there, and a current word stays. Its kept
      clips replace older ones, as in S023.4.
- [ ] Add to Revision does the same into the revision pool, so a listed current word moves to revision.
- [ ] After Apply, the spelling page's status bar says what was done, such as "Added 6 words to current, 2 of them
      moved from revision." or "Added 12 words to revision." Replace Current's message is S023.4's.
- [ ] Opening a mode whose setup is in progress carries on with that setup. Choosing another mode from the menu while
      a setup is in progress asks on the spelling page, before going anywhere: "Throw away the Replace Current setup in
      progress, with 6 words, and start Add to Revision?", with Keep it as the default. Keep it closes the question
      and leaves the spelling page as it was, with any unsaved changes still there. Throw away discards the setup, as
      S023.4's Cancel does, and opens the new mode with an empty list.
- [ ] Opening another mode's address any other way, such as from a bookmark or a new tab, asks the same question on
      the setup page, and Keep it there goes to the spelling page. In neither case does the parent land in the setup
      in progress without choosing its mode.

## Setting up words in new directories

- [ ] Opening a Words link while the spelling page shows unsaved directories, refused or not, starts the setup with
      those directories. The leaving prompt from S023.2 asks only when other changes are unsaved too. A setup already
      in progress keeps its own directories.
- [ ] The setup page shows the four directories it applies into, relative to the spelling directory. Where one differs
      from the task's saved directory, it is marked, and the page says "Apply also makes the task use these
      directories."
- [ ] The setup works against its own directories throughout. Where each word is now, which homographs it matches, and
      which current words Replace Current moves to revision all come from those directories, not the saved ones.
- [ ] Apply writes the directories to the policy file along with the words and any target changed in the Targets box,
      in one checked step and one commit, as S023.4's Apply does with a target. An Apply that would leave the policy
      unable to load is refused as in S023.4, and nothing moves or is written. For example, Add to Current into new
      directories with `revision_required: 10` is refused until Required Correct (Revision Pool) is lowered to 0 in
      the Targets box.
- [ ] Cancel throws away the setup and leaves the task's directories as the file has them.

## Everywhere

- [ ] Without a parent session, the new pages go to sign-in and come back afterwards, and the new data addresses
      under `/parent/api/` answer 401 and never redirect.
- [ ] `docs/hierarchical-policy.md` says the directory fields can be chosen, and new directories made and filled,
      from the task's page. `docs/parent-portal.md` describes a single-choice pull-down that ends with an option for
      making a new entry in a dialog, and a context bar menu of links.

# Notes

Depends on S023.2 for the task page, the save, and the word list, on S025 for problems that block Save, on S023.3 for
the recordings, and on S023.4 for the setup page, its Apply, and its Targets box. S012 is in progress, and the
addresses here follow its `/parent/tasks/<type>/<name>` form.

S027's New task page shows a new spelling task's section from an empty body, so with this story it shows these
pull-downs with the defaults chosen. Whichever of S027 and this story is built second makes sure the pull-downs and
New directory… are disabled whenever the rest of that section is. A task that has never been saved has no Words menu.

Design hints:

- One single-choice pull-down in `policy/portal/src/components/`, built as `MultiSelect` is with `useExpander()`, and a
  small name dialog in the style of `Dialog`. A native `<select>` cannot show the icons. The Words menu can share the
  pull-down's panel.
- The task page's spelling data gains the list of directories under the spelling directory, and the word list can be
  asked for with directories in place of the saved ones, for the list after a refused save. Making a directory is a
  new `POST` under the task's `/parent/api/` address, using `make_directory` in `policy/owned.py`. The server's name
  check is the only one, so the page and the service never disagree.
- The save accepts the four directory fields as it accepts the other spelling settings in `_changes` in
  `policy/task_admin.py`, with a field equal to its default in `spelling._DIRECTORIES` written as removed.
- The Words links carry unsaved directories in their query string, as plain `<a href>` links must. The setup keeps
  its mode and its directories in `state.json` in `.weeks/<name>/`, from its first Check or Save. The setup's
  `Settings` are the task's with its directories put in, so `policy/week.py` works against them with no other change.
- The spelling page's data gains the mode and word count of any setup in progress, so a menu link can ask before it
  is followed. The links stay real `<a href>` links, so middle click and Copy link address still work.
- Each attempt already keeps the body its run started with in `detail["settings"]`. `task_media` in
  `policy/task_page.py` can look up the client's open attempt and search that run's directories before the task's
  current ones, as `find_clip` already falls back across pools.

Out of scope: renaming, moving, or deleting a directory from the portal, choosing a directory outside the spelling
directory except by editing the policy file, changing a setup's directories after it starts, other than by throwing it
away and starting again, and copying words from one task's directories to another's.

Sizing: 21 points, with 35 checks. Choosing and making directories is about 8. That covers a pull-down component smaller
than S029's calendar, the name dialog and its service call, four more fields on the save with the same-directory
problem, the word list after a refused save, and the audio lookup from a run's own directories. The Words menu and the
two add modes are about 8, since they are new Apply rules and addresses on S023.4's existing page. Carrying the
directories into a setup and applying them with the words is about 5. It stays one story because the three parts
share the save path in `policy/task_admin.py`, the setup in `policy/week.py`, and their tests, and because new
directories cannot be accepted until a setup can fill them.
