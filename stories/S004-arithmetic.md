Ticket: S004
Title: Arithmetic quizzes
Status: Draft
Story Points: 13
Last Updated: 2026-11-10 00:40:00
---

# User Voice

As a parent, I want him to practice addition, subtraction, multiplication, and division until he can answer them quickly from memory, and I want a finished session to count as one revision task.

# Use Cases

- One session shell draws weighted operands, shows a large question, times the answer, and gives immediate feedback with a sound. The sound is picked at random from the set for that outcome: correct, incorrect, or timeout.
- Addition, multiplication, subtraction, and division are the same shell with a different question on screen. A task chooses one with its `operation` field. S004.2 is addition. S026 adds the other three.
- The parent sets the pace in the task body: `max_timeout`, `min_timeout`, `correct_answers_required`, a weighted `operands` list, and an optional weighted `first` list that narrows the first operand to one fact family. S004.1 defines these fields.
- The session counts as a pass when he reaches the configured number of correct answers. He cannot fail it by getting answers wrong. He can abandon it when S003.2 allows give-up. A required arithmetic task has no failure outcome, so it stays required until he passes it or a parent changes the assignment.

# Acceptance Criteria

- [ ] S004.1, S004.2, and S004.6 are done, and S026 has added subtraction, multiplication, and division.
- [ ] A completed arithmetic attempt increments the daily pass count from S003.1.
- [ ] The parent attempt view shows each question, the answer he gave, and whether it was correct, incorrect, or timed out.

# Child stories

| Ticket | Title | Points |
| --- | --- | --- |
| S004.1 | Arithmetic session shell | 8 |
| S004.2 | Addition | 2 |
| S004.6 | Arithmetic attempt review | 3 |

Multiplication, subtraction, and division were S004.3 to S004.5. They are now part of S026, with the arithmetic task
page.

# Notes

Depends on S003. This is the first quiz because it needs no recorded speech and no drag-and-drop. Its only audio is the shipped sound effects in `policy/static/sounds/`.
