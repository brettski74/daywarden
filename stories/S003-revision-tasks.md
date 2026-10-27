Ticket: S003
Title: Revision task platform
Status: Draft
Story Points: 13
Last Updated: 2026-10-26 00:49:00
---

# User Voice

As a parent, I want a refused entertainment site to become a revision task chosen for that client group, and I want a finished task to count toward today's requirement so the site can open.

# Use Cases

- Tasks are assigned to a client group and remember when they were last attempted.
- A redirect to `revision_task` picks an eligible task and sends the browser there.
- The child can abandon a task and be offered another one.
- Success increments today's completion count for that client group. One success scores one point. Failure and abandonment do not.
- The child cannot mark a task complete by hitting a URL. The server marks success when the quiz's own completion rule is met, based on the child submitting correct answers. The temporary `parent_check` task is the exception, and only a parent can record that success.
- A parent can read back what was asked and what was answered.

# Acceptance Criteria

- [ ] S003.1, S003.2, and S003.3 are done.
- [ ] The rule engine's `revision_task` token resolves to a real task URL for the classified client group, replacing the placeholder from S001.3.
- [ ] A successful completion changes the result of `tasks_required` without any hand-written count.
- [ ] For a real quiz, that success is recorded only when the quiz's own completion rule is met from answers the child submitted. A request whose only purpose is to mark the attempt complete does not succeed.

# Child stories

| Ticket | Title | Points |
| --- | --- | --- |
| S003.1 | Task catalogue, cooldown, and attempts | 5 |
| S003.2 | Task selection and give-up | 5 |
| S003.3 | Parent review of attempts | 3 |

# Notes

Depends on S008.2 for `tasks_required` and the client group on the request. Quiz types in S004, S005, and S006 plug into this epic. A minimal built-in task that a parent marks complete from the parent pages is enough to prove the gate before those quizzes exist. That minimal task is part of S003.2, not a fourth quiz.

Every address in a client group shares that group's tasks and today's count. The implicit `default` group is a client group like any other. This epic does not add a sign-in for the child.
