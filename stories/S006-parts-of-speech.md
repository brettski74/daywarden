Ticket: S006
Title: Parts of speech quiz
Status: Draft
Story Points: 13
Last Updated: 2026-10-31 12:31:02
---

# User Voice

As a parent, I want him to sort words in a sentence into their parts of speech, and I want a quiz he has already passed to stay away for a few weeks while a quiz he failed can come back sooner.

# Use Cases

- A quiz is a list of sentences, each with the words expected in each part of speech.
- He drags a copy of a word into a table and submits the sentence.
- The quiz ends after every sentence. The total is compared with a pass mark.
- Passing and failing use the two cooldowns from S003.1.

# Acceptance Criteria

- [ ] S006.1 and S006.2 are done.
- [ ] A passing attempt increments the daily revision count. A failing attempt does not, and it becomes eligible again according to the failure cooldown.

# Child stories

| Ticket | Title | Points |
| --- | --- | --- |
| S006.1 | Sentence bank and scoring | 5 |
| S006.2 | Drag-and-drop answering | 8 |

# Notes

Depends on S003. The scoring rules in the problem statement are easy to read two ways. S006.1 states the reading this project will use.

A further set of sentences is a new task of this type, with its own name, its own `available_from`, `due_date`, `max_skips`, and `max_passes`, and its own attempt history. Two such tasks do not share passes or skips. `max_passes` of 3 means that client group is not offered this quiz again after the third pass. The passes before that are the reinforcement visits, spaced by the pass cooldown. Changing the sentences on a task a client group has already passed does not make that group due again. S007.3 warns on that save when the task has a due date.
