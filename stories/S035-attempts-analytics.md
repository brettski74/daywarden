Ticket: S035
Title: Attempts Analytics
Status: Draft
Story Points: 
Last Updated: 2026-11-17 15:05:00
---

<!--
Follow "Writing stories" in AGENTS.md. Above all, say each thing once.
Delete these comments, and any optional section left empty, when writing the story.
-->

# User Voice

As a [user], I want [something] so that [reason].

# Scenarios

<!--
Optional. Short narratives of a user reaching a goal across several features. They state no rules; the rules are
in Behaviour. Leave this section out when Behaviour says it all.
-->

## [Scenario name]

[Who does what, and what they see, in a few sentences.]

# Behaviour

<!--
Grouped by area. A checkbox for each thing a reviewer can check through the policy file, the data directory, the
web pages, or the command line, with its example inside it. A plain bullet for detail that is not a check of its
own. A sentence under a heading may define terms its checks use.
-->

## [Area]

- [ ] [Something a reviewer can see, such as: dragging a word onto a row adds it to the end of that row.]
- [ ] [Behaviour inherited from another story, as one check: saving works as in Snnn.]
- [Detail that is not a check of its own, such as an icon name or a list of accepted values.]

# Child stories

<!-- Epics only. -->

| Ticket | Title | Points |
| --- | --- | --- |
| Sxxx.1 | [First child] | 8 |
| Sxxx.2 | [Second child] | 5 |

# Notes

<!-- Optional. Dependencies, design and implementation hints, what is out of scope, and sizing. Never Behaviour. -->
Rough notes collected over time - remove after refinement.

We already have some review screen stories for tasks, and even though they were labelled "Refined" by a previous agent, I would consider them drafts. We first need to think about how we get into the requests data in the first place. I don't think that should be from a naive listing of tasks in some kind of chronological order. I think more realistically I'd want to start at some kind of higher level analytics showing his progression at different tasks over time. This could include things like:

- how many tasks of a given type he may have attempted/completed/passed over the reporting period.
- his scores over time for a particular task type, possibly compared against the total questions asked or the required pass mark

There are several different types of task and likely will be more task types added in the future. Based on the scoring behaviours, I think these can probably be grouped into two different categories, each of which will have different reporting needs.

1. tasks with a fixed number of questions that the child either passes or fails once all questions are exhausted.
2. tasks with a variable number of questions that keep going until the child either gives up or answers sufficient questions correctly.

For the first category, it's probably useful to show something like the number of correct answers against the required pass mark, either as a percentage or as an absolute value. With the recent changes to part-of-speech tasks, I'm not sure how real this category of task is any more - something to review and consider.

For the second category, knowing the total number of questions asked or the number answered wrong is likely an important additional data point, since maybe he passes every attempt, but a pass mark of 20 achieved with only 21 questions asked is significantly different than a pass mark of 20 achieved with 50 questions asked.

All of the above could probably be shown effectively over time using line charts with a different line for the child's final score, pass mark required, total questions asked, etc and as appropriate for the category of task that it is.

Ultimately, we need to be able to drill down into more specific layers of information to understand what the child is doing well at and what areas he may still need help with or additional practice.

