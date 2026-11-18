Ticket: S033
Title: Spelling word statistics and weighted revision
Status: Done
Story Points: 8
Last Updated: 2026-11-16 21:25:00
---

# User Voice

As a parent, I want daywarden to keep a record of how often each spelling word has been asked, spelled right, and
spelled wrong for each client group, so that the figures can feed analytics later.

As a parent, I want revision words chosen with that record, so that over many tasks he is asked every revision word
about equally often, and a word he keeps getting wrong comes up more until he has it right a few times in a row.

# Scenarios

## A word he cannot spell

He misses `necessary` in a revision slot. The next few tasks ask it more often than its neighbours. He spells it right
three tasks running, and by the fifth right answer it is as likely to come up as any other revision word. A parent runs
`bin/word-stats` and sees its run climb as the weight falls back.

# Behaviour

## What is counted

A **task** here is one spelling attempt, whatever its task set. A word is **asked** in a task when one of its
questions was answered or timed out. A word offered more than once in a task, because a miss put it back on the queue,
still counts once. Words are identified by their entry key, folded to lower case, such as `rope` or `read.1`, within a
client group. The figures belong to the word, not to a pool or a task. The same word may be in several pool
directories, used by different tasks, and it has one set of figures per client group whichever task asked it. A word
keeps its figures when it moves between pools, including across a Replace Current.

- [ ] A word asked in a task adds 1 to its **attempts**.
- [ ] A word spelled wrongly, or timed out, at least once in a task adds 1 to its **incorrect**, however many times it
      was missed in that task. A timeout is a miss, as in the missed-words list.
- [ ] A word asked in a task and never missed in it adds 1 to its **correct**. A current word missed once and then
      spelled right when it came back is incorrect, not correct.
- [ ] Each word also has a **run**: the number of tasks in a row, counting back from the latest, in which it was
      correct. A task in which it was incorrect sets the run to 0, and each correct task after that adds 1. Run is
      never more than attempts, and equals attempts for a word that has never been missed.
- [ ] Figures are kept for each client group separately. A word asked by `younger` does not change `older`'s figures.
- [ ] Figures are updated as each answer is recorded, so a task given up, or left unfinished at the end of the day, still
      counts the words he was asked. Giving up and coming back to the same attempt (S013) does not count a word twice,
      and a word first asked after he came back counts once.
- [ ] Practice mode (S005.2) changes nothing: its walk through the words is not a question. Words asked in a quiz run
      after practice count as part of the same task.
- [ ] Removing attempts with `bin/rm-attempts` leaves the figures as they are.

## Seeing the figures

- [ ] `bin/word-stats` lists, for each client group and word, its attempts, correct, incorrect, run, and the weight
      worked out below that it would have as a revision word. It shows no pool for a word. `--client GROUP` shows one
      client group, and `--word WORD` shows one word. It is read-only and says `daywarden is not running. Start it with
      dw up.` when the stack is down, as `rm-attempts` does. Its installation and options are documented beside
      `rm-attempts` in the README.
- [ ] `--sort COLUMN` orders the rows by `client`, `word`, `attempts`, `correct`, `incorrect`, `run`, or `weight`,
      smallest first, and `weight-` (or `--sort=-weight`) largest first. It may be given more than once, each term
      applying after the earlier ones, and rows left level stay in client group then word order. Any other column is
      an error that lists the choices. Without `--sort` the rows are in client group then word order.
- [ ] `--pool DIRECTORY` shows every word that has a recording in that pool directory, named as a task's `current_dir`
      is, such as `spelling/revision`. `--task NAME` shows every word in any of that task's current, revision, or
      attic directories. Each may be given more than once, and a word in any of the named pools or tasks is shown.
      A word never asked is shown too, with 0 for each figure and the weight of a new word, for each client group in
      the policy or with figures, or for each `--client` named.
      With both given, a word must satisfy both. Without either, only words with figures are shown, including words no
      longer in any directory. A pool directory that does not exist, or a task name that is not in the policy, is an
      error that names it, and nothing is listed. A word in two pools shows the same figures under each filter.
- [ ] After the first start with this story, `bin/word-stats` already shows figures built from every spelling attempt
      stored before it, counted by the rules above in the order the attempts started. Starting again does not count
      them a second time.

## Choosing revision words

Every current word is still asked in every task, and nothing about current words changes. Only the choice of revision
words and of a replacement revision word after a miss (S005.1) is weighted. Each revision word has a weight. A task's
revision words are chosen at random without repeats, each word's chance of being picked in proportion to its weight.

For a revision word with `a` attempts and `r` run:

- `base = 1 / (a + 1)`, so a word asked fewer times is more likely.
- `boost = 0` when `r >= min(5, a)`, which covers a word never missed and a word right on its last 5 tasks. Otherwise
  `boost = 4 × 0.5^r`.
- `weight = base + boost`. The boost does not shrink as `a` grows, so a word missed on its last task is as likely as
  about 4 never-asked words however many times it has been asked.

| Word | a | r | base | boost | weight |
| --- | --- | --- | --- | --- | --- |
| Never asked | 0 | 0 | 1.000 | 0 | 1.000 |
| Never missed | 10 | 10 | 0.091 | 0 | 0.091 |
| Missed on its last task | 10 | 0 | 0.091 | 4 | 4.091 |
| Missed, then right once | 10 | 1 | 0.091 | 2 | 2.091 |
| Missed, then right twice | 10 | 2 | 0.091 | 1 | 1.091 |
| Missed, then right 4 times | 10 | 4 | 0.091 | 0.25 | 0.341 |
| Missed, then right 5 times | 10 | 5 | 0.091 | 0 | 0.091 |
| Missed on all of 100 tasks | 100 | 0 | 0.010 | 4 | 4.010 |
| Missed on its first task | 1 | 0 | 0.500 | 4 | 4.500 |

- [ ] The weight in `bin/word-stats` matches the formula and the table above.
- [ ] A revision word missed on its last task has a weight of at least 4, however many times it has been asked, and
      with a run of 1 and of 2 about 2 and about 1: as likely as 4, 2, and 1 never-asked words.
- [ ] A revision word he misses shows a larger weight on `bin/word-stats` straight after the task, and its weight falls
      back to its base after 5 correct tasks in a row. A word he has never missed has no boost.
- [ ] With revision words he has never missed, chosen over many tasks, each is asked about equally often, and a word
      added to revision with no figures is asked in the next tasks until it catches up with the others.
- [ ] A revision word he misses most of the time is asked clearly more often than words he gets right, and goes back to
      the same rate as the others once he has spelled it right several tasks running.
- [ ] A replacement revision word picked after a miss (S005.1) is weighted the same way, among the revision words not
      yet right in the run and not already waiting in the queue.
- [ ] A run started by practice mode picks its revision words with the weights at that moment.
- [ ] The number of revision words asked, the pass rules, the questions, and the quiz pages are unchanged.

# Notes

The weighting numbers (`1 / (a + 1)`, a boost of 4 halving with each correct task, cut-off at `min(5, a)`) are
proposals for review, and are fixed in the code, not in the policy file. A simulation with 40 revision words and 5
asked per task, run for 200 tasks, gave this: a word missed half the time was asked in about half of all tasks, against
one in eight for an ordinary word, and a word missed one time in five was asked in about one task in five. The other
words stayed level. With none missed, base alone only narrows the spread a little, because random picking is already
close to even. Its main work is catching up a word added late.

Figures are keyed by entry key so that two homographs (`read.1`, `read.2`) are separate words. Renaming a recording
starts a new word. A word's figures are kept when its recording is removed.

A word's weight depends only on its figures, so a word in the revision pools of two tasks has the same weight in both.
The word-stats filters read the pool directories as they are when the command runs.

Out of scope: any page that shows the figures (analytics, S035.4), tuning the weights from the policy file or the
portal, and weighting current words. The figures are added to the household database. Counting as answers are recorded
(rather than when an attempt ends) is what makes a given-up or reopened attempt safe, so the recording must be
idempotent per attempt and word.

Sized at 8 against S006.1 to S006.3, which used about 40% of a context window for 14 points: a new table, recording from
the quiz, a one-time rebuild from stored attempts, weighted choice in two places, and one command-line tool.

# Implementation

## Files Added

- `policy/spelling_words.py`: the word ledger table, counting rules, the weight formula, weighted picking without repeats, and the figures read-out.
- `bin/word-stats`: host script that runs `word-stats` in the decisions container, installed beside `rm-attempts`.
- `tests/test_spelling_words.py`: counting, idempotence, rebuild, weights, weighted selection, and the `word-stats` filters.

## Files Changed

- `policy/tasks.py`: `AttemptStore` creates the ledger, builds it once from stored attempts, and records a spelling attempt's answered words on every `save`, `finish`, and `record`. `store.words` reads the figures.
- `policy/spelling.py`: `Session` takes a figures lookup and uses it to draw revision words and the replacement after a miss. Without one, the draw is uniform as before.
- `policy/spelling_page.py`: passes the client group's figures to each `Session`.
- `policy/maintenance.py`: the `word-stats` command and its `--client`, `--word`, `--pool`, and `--task` filters.
- `deploy/build.py`, `deploy/install.sh`, `README.md`, `tests/test_install.py`, `tests/test_dw.py`: ship, link, and document `word-stats`.

## Change Summary

The figures are derived from a ledger with one row for each word in each attempt that asked it, holding whether the word was missed there. Attempts and correct and incorrect counts are row counts, and the run is the trailing rows with no miss, so recording the same attempt again changes nothing and a word first missed after it was recorded right flips its row. An attempt is identified by its id and start time, so an id reused after `rm-attempts` is a new task. Ledger rows are never deleted. Recording happens when the attempt's detail is stored, which covers answers, timeouts, giving up, and reopening, and practice mode asks no questions so it adds nothing. The first start fills the ledger from stored spelling attempts in start order, guarded by a marker row written in the same transaction.

Rows are ordered by the order they were first recorded, so tasks that overlap in time order by when each first asked the word, not by start time. A word with no figures weighs as never asked. `word-stats` shows words by folded entry key. `--word` matches the whole key, so `read` does not match `read.1`.

### Acceptance test cases for S033

1. Create a task with a revision pool of 6 or more words and miss one in a revision slot. Run `word-stats --client younger`. Covers counting, weight, and "Seeing the figures".
2. Spell the missed word right on later tasks and watch the run climb and the weight fall to its base after 5. Covers the scenario and the weight checks.
3. Run `rm-attempts --client younger --all --yes` then `word-stats`. Covers figures staying after removal. Give up and come back to an attempt and check nothing counts twice.
4. Use `--pool`, `--task`, `--word`, and both together, including a missing pool and an unknown task. Covers the filters and errors.
5. Over many tasks, compare how often missed and never-missed revision words are asked, and add a new revision word with no figures. Covers weighted choice, and a replacement after a miss.
6. Restart with `dw restart` on a database that already has spelling attempts and check the figures are built once. Covers the rebuild.
