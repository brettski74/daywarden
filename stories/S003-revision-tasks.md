Ticket: S003
Title: Revision task platform
Status: Draft
Story Points: 13
Last Updated: 2026-10-31 13:03:05
---

# User Voice

As a parent, I want a refused entertainment site to become a revision task chosen for that client group, and I want a finished task to count toward today's requirement so the site can open.

# Use Cases

- Tasks are assigned to a client group and remember when they were last attempted. Optional `available_from`, `due_date`, `max_skips`, and `max_passes` on a task say when it may appear, when an unpassed task becomes required, how many household days he may fail or abandon it before it becomes required, and after how many passes it stays finished. S003.1 defines those rules. Failure and abandon accrue the same way: one skip on a household day, and no more, whatever mix of the two he uses that day.
- A redirect to `revision_task` picks an eligible task and sends the browser there. While a required task is eligible, the picker stays inside the required tasks.
- The child can abandon a task and be offered another one. He can abandon a required task only when another required task is eligible, and the next task is still a required one.
- A pass increments today's completion count for that client group. One pass scores one point, including a pass on a required task. Failure and abandonment do not.
- The child cannot mark a task passed by hitting a URL. The server records a pass when the quiz's own completion rule is met, based on the child submitting correct answers. `parent_check` is the exception: it is never shown to the child, and only an authenticated parent can record that pass for a client group.
- A parent can read back what was asked and what was answered.

# Acceptance Criteria

- [ ] S003.1, S003.2, and S003.3 are done.
- [ ] The rule engine's `revision_task` token resolves to a real task URL for the classified client group, replacing the placeholder from S001.3.
- [ ] A pass changes the result of `tasks_required` without any hand-written count.
- [ ] For a real quiz, that pass is recorded only when the quiz's own completion rule is met from answers the child submitted. A request whose only purpose is to mark the attempt passed does not record a pass.

# Child stories

| Ticket | Title | Points |
| --- | --- | --- |
| S003.1 | Task catalogue, cooldown, and attempts | 5 |
| S003.2 | Task selection and give-up | 5 |
| S003.3 | Parent review of attempts | 3 |

# Notes

Depends on S008.2 for `tasks_required` and the client group on the request. Quiz types in S004, S005, and S006 plug into this epic. A minimal built-in task that a parent marks complete from the parent pages is enough to prove the gate before those quizzes exist. That minimal task is part of S003.2, not a fourth quiz.

Every address in a client group shares that group's tasks and today's count. The implicit `default` group is a client group like any other. This epic does not add a sign-in for the child. The task site this project serves is HTTPS, with a certificate from the household CA under the lifetime rules in S007.1. The placeholder URL in the sample policy stays until that site exists.
