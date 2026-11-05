Ticket: S006
Title: Parts of speech quiz
Status: Refined
Story Points: 17
Last Updated: 2026-11-04 23:55:00
---

# User Voice

As a parent, I want to write sentences and say which of their words are nouns, verbs, adjectives, or any other part of speech I choose, so that he practises sorting the words of a real sentence into their parts of speech.

As a child, I want to drag words out of the sentence into a table, and get another go with a bit more help when I get some wrong, so that I can work it out myself.

As a parent, I want a quiz he has passed to stay away for a few weeks while a quiz he failed can come back sooner.

# Use Cases

## UC1 - Parent writes a parts of speech task

- A `parts_of_speech` task lists as many sentences as the parent wants. Each sentence has a `parts` table mapping part of speech names, chosen by the parent, to words from that sentence (S006.1).
- Not every word has to be listed. A word that appears more than once is told apart by its occurrence number, such as `dry[1]` and `dry[2]`, or `the[1,2]` for both. Words are matched without regard to case.
- Each sentence gets 90 seconds unless the task or the sentence sets another `timeout`. The pass mark defaults to 70% of the sentences, rounded up.
- A mistake in the configuration fails the policy load and names the task, the sentence, and the word.

## UC2 - Child sorts the words of each sentence

- Every sentence is asked once per run, in a random order (S006.2).
- The sentence is shown in large text with a table under it, one row per part of speech in that sentence. He drags copies of words into rows, moves them between rows, or drops them outside the table to send them back (S006.2).
- He submits with a large Submit button or Enter. He has up to three tries, worth 1, 0.5, and 0.25 points. After a wrong try he is told how many words are in the wrong row and how many he missed (S006.2).
- After a wrong second try, those words turn red. After a wrong third try or a timeout, he is shown the answer (S006.3).

## UC3 - Pass or fail

- The run ends after the last sentence. Points at or above the pass mark are a pass, which counts toward today's revision. Anything less is a failure, which starts the failure cooldown and records a skip day.

## UC4 - Parent reviews the attempt

- The parent sees each sentence, where he put each word on each try, and the answer (S006.4).

# Acceptance Criteria

- [ ] S006.1 through S006.4 are done.
- [ ] A passing attempt increments today's revision pass count. A failing attempt does not, records a skip day, and becomes eligible again according to `failure_cooldown`. A passed attempt becomes eligible again according to `pass_cooldown`.
- [ ] End to end on the child's computer through the proxy, with a two-sentence task ("The quick, brown fox jumped over the lazy dog." and "Dry the dishes with a dry towel."), `failure_cooldown: 0`, and the default pass mark of 2 points:
  - Getting both sentences wrong on all three tries ends the attempt on the failure screen. `/attempts` shows a `failure`, today's revision count is unchanged, and the task is offered again straight away.
  - On that next attempt, sorting both sentences correctly on the first try ends on "Well done". `/attempts` shows a `pass`, and today's revision count goes up by one.

# Child stories

| Ticket | Title | Points |
| --- | --- | --- |
| S006.1 | Parts of speech sentences and configuration | 3 |
| S006.2 | Parts of speech quiz | 8 |
| S006.3 | Parts of speech red marks and answer | 3 |
| S006.4 | Parts of speech attempt review | 3 |

# Notes

Depends on S003 for tasks, selection, and give-up, and on the shell shared by S004.1 and S011: the start screen, sound sets, server timing, the one-hour expiry, "Try a different task", and the "Well done" and failure screens.

A task is identified by its name, as in S003.1. Its attempt history, including passes, skip days, and whether a due date has been met, belongs to that name. Editing the sentences, timeouts, or pass mark under the same name keeps all of that history. A client group that has already passed the task is not made due again, and its pass count toward `max_passes` carries on. The quiz does not track which sentences an earlier attempt was given beyond what that attempt's own record stores. S007.3 warns on such a save when the task has a due date.

To give him a genuinely new set of sentences with a fresh history, the parent adds a task with a new name, such as `parts-of-speech-2`. That task has its own `available_from`, `due_date`, `max_skips`, and `max_passes`, and does not share passes or skips with the first. Reusing an old name for new sentences works, but is usually not what the parent wants, because the old passes and skip days still count.

`max_passes` of 3 means that client group is not offered this quiz again after the third pass. The passes before that are the reinforcement visits, spaced by the pass cooldown.

## Decisions from refinement on 2026-11-04

From the parent:

- The child-facing wording uses "sort": "Sort the words into the table" and "2 words are in the wrong row. You missed 1 word. Try again." The stories say "sorted" and "not sorted" for classified and unclassified.
- Every configured sentence is asked in each run. The run always ends after the last sentence, even when a pass is out of reach.
- `correct_answers_required` defaults to 70% of the sentences, rounded up.
- Each sentence has a timer, 90 seconds by default, set for the whole task or per sentence. The default was 45 seconds until 2026-11-05, when the parent found that too short. Its deadline is fixed when the sentence is issued and does not move for tries or reloads. When the bar empties, the table is submitted as it stands. A sentence that is abandoned, or not answered by its deadline, is a timeout.
- A reload within the deadline brings back the same sentence with the tries used, his last submitted table, and its feedback.
- The answer display shows each correct word in its row on pale green, pale red, or pale orange. A word he sorted that belongs in no row is struck through on pale red where he put it.
- "Next Question" and Enter are ignored for the first 3 seconds of the answer display.
- After a wrong second try, correctly sorted words stay black and movable.
- Words in the sentence look the same whether sorted or not. Light grey shading appears only while the mouse is over a word that can be picked up. Once he starts dragging, the shading stays on the sentence word until the copy is dropped on a row or lands after flying back. The dragged copy has a transparent background, so it never hides a row's light blue.
- Dragging a word from the table shades both that word and its twin in the sentence. The word stays in its cell until the mouse button is released somewhere else. Released on its own row, it does not move. Both shadings go on release (S006.2 UC5).
- An empty table, or one unchanged since the last wrong try, cannot be submitted and uses no try.
- Points are shown out of the number of sentences, such as "6.75 / 10 points", with the pass mark shown beside them.
- A confirmed give-up is always an abandonment, on any sentence and whatever his points. A give-up refused on the only required task leaves the open sentence alone, with its deadline still running, rather than closing it as a timeout as S004.1 does (S006.2 UC10).

Assumed while refining. Change any of these in the child stories if they are wrong:

- The whole table row, label included, is the drop target (S006.2 UC4).
- Only red words turn blue when moved. Black words stay black (S006.3 UC1).
- A part may have an empty list, which gives a row where nothing belongs (S006.1 UC1).
- Part names are at most 20 characters (S006.1).
- Sorting needs a mouse. There is no keyboard way to sort a word (S006.2 UC11).
- The pass mark keeps the name `correct_answers_required` used by arithmetic and skip counting, although it counts points.
