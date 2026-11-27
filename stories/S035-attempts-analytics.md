Ticket: S035
Title: Attempts Analytics
Status: Draft
Story Points: 76
Last Updated: 2026-11-26 23:12:06
---

# User Voice

As a parent, I want to start from how he is doing at each task over a period, and drill down to the facts, words, and
parts of speech he gets wrong, and then to the single attempt and answer, so that I can see where he needs more help
or practice.

# Scenarios

## Seven times table

On `/parent/attempts`, the past month's overview shows `arithmetic/times` passed every time, but its sparkline shows
the questions climbing well above the pass mark of 20. Its trend page shows the last few passes took 35 to 45
questions, with timeouts rising. The link to the multiplication facts shades most of the 7 row, and the fact list puts
`7 × 8 = 56` first, missed 6 times in 9. Choosing it lists the attempts that asked it. One of them opens on its own
page, where he answered 54 twice before getting it right.

# Behaviour

## Done

- [ ] S035.1 to S035.5 are done.

# Child stories

| Ticket | Title | Points |
| --- | --- | --- |
| S035.1 | Attempts overview and task trends | 13 |
| S035.2 | Arithmetic facts and attempt page | 13 |
| S035.3 | Parts of speech confusions and attempt page | 21 |
| S035.4 | Spelling words and attempt page | 21 |
| S035.5 | Skip counting breakdown and attempt page | 8 |

# Notes

## Approach

The work goes in layers: an overview of every task over a period, a trend for each task, a breakdown for each task
type, and a page for each attempt. The first two layers are shared by every task type. The breakdown and the attempt
page are different for each type, and each type's pair is one child. S035.1 to S035.4 are refined. S035.5
is Draft. Refine it once S035.1 and S035.2 have been used for a while, because what proves useful
there should shape it. Its points are provisional.

## One model for every task type

The rough notes proposed two categories: a fixed number of questions, pass or fail, and questions until he passes or
gives up. In the code, every type is points against a pass mark, `correct_answers_required` or spelling's two targets.
Types differ only in whether a run can fail:

- Arithmetic and spelling never fail. They run until he passes or gives up.
- Skip counting fails only when `maximum_questions` is set.
- Parts of speech always has a maximum, the runnable size by default. It is the only type that always has a fixed
  number of questions.

So one trend chart serves every type, with points, pass mark, questions, and the maximum where there is one. The gap
between points and questions is the "20 needed, 21 or 50 asked" measure from the rough notes.

## Replaces

S004.6 (arithmetic attempt review) and S006.4 (parts of speech attempt review) were never built. Their attempt pages
are re-refined here as part of S035.2 and S035.3, and both stories are removed. The S004 and S006 epics no longer list
them. `S032-attempts-analytics.md`, an earlier copy of these notes under a clashing number, is removed too.

## Out of scope

- Parent checks. They hold no questions or answers to analyse, and counting them alongside the tasks he did would
  only add noise. The attempts list still shows when each was given. If they are wanted later, they get a table or
  chart of their own, apart from the tasks.
- Comparing client groups on one chart. Each page shows one client group, as the attempts page does.
- Combining attempts per day or per week on the trend. Each attempt is a point. Revisit if long periods get crowded.
- Feeding arithmetic fact figures back into question choice, as S033 does for spelling words. That would be a later
  story, and S035.2's figures are the evidence for it.
- Exporting data.

## Sizing

Each child is sized against S006.1 to S006.3 (14 points). S035.1 builds the shared pieces: period and filter controls
on the attempts page, figures read from each type's stored attempts, the overview table with sparklines, and a trend
page with a chart that has markers and points that open. The breakdown children reuse those pieces and add one
type-specific chart and one attempt page each.
