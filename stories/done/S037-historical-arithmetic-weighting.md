Ticket: S037
Title: Historical Arithmetic Weighting
Status: Done
Story Points: 13
Last Updated: 2026-11-18 05:26:15
---

# User Voice

As a parent, I want arithmetic questions chosen from his own record, so that facts he gets wrong or answers slowly
come up more often until he knows them, and every fact gets its turn, instead of relying on the weights I guessed in
the policy file.

# Scenarios

## A fact he counts on his fingers

He answers most times-table facts in about 2 seconds, but `7 × 8` takes him 7 or 8 seconds even when he gets it
right. On the facts page `7 × 8` shows a slow boost, and it comes up more often than its neighbours. Over a few
sessions he answers it in 3 seconds four times running, its smoothed time falls under where the slow boost starts,
and its weight drops back to that of the other facts.

# Behaviour

## What is counted

A fact is a question as asked, `(operation, m, n)`, as defined in S035.2, so `6 × 7` and `7 × 6` have separate figures.
Figures belong to the fact for each client group, whichever arithmetic task asked it.

- [ ] Every question with an outcome counts once, including questions in expired runs and in abandoned, unfinished,
      and in-progress attempts. A question still showing with no answer does not count. Giving up and coming back to
      the same attempt (S013) does not count a question twice.
- [ ] Each fact has an **all-time asked** count, and a **run**: the number of answers in a row, counting back from the
      latest, that were right. A wrong answer or a timeout sets the run to 0.
- [ ] Each fact has a **smoothed time**, built only from its right answers. The first right answer sets it to that
      answer's time `t`. Each later right answer moves it to `s × (t / s)^α`, with `α = 1 − e^(−1/3) ≈ 0.283`, so
      after three fast answers in a row a slow history has about a third of its pull left. Wrong answers and timeouts
      leave it unchanged.
- [ ] Figures are updated as each answer is recorded, and the facts page shows them straight away.
- [ ] Figures are kept for each client group separately. A fact asked by `younger` does not change `older`'s figures.
- [ ] Removing attempts with `bin/rm-attempts` leaves the figures as they are.
- [ ] After the first start with this story, the facts page already shows all-time figures built from every
      arithmetic attempt stored before it, counted in the order the attempts started. Starting again does not count
      them a second time.

## Choosing questions

A task's **domain** is every `m` in `first` (or in `operands` when there is no `first`) paired with every `n` in
`operands`. `N` is the number of facts in the domain. For a fact asked `a` times with run `r`:

- **base** `= 1 / (a + 1)`, so a fact asked less often is more likely, and a never-asked fact has base 1.
- **miss boost** `= 0` when `r >= min(5, a)`, which covers a fact never missed and a fact right on its last 5 answers.
  Otherwise `4 × 0.5^r`.
- **slow boost** uses `M`, the median smoothed time over the client group's facts of that operation with at least 3
  right answers. It is 0 until there are at least 10 such facts, and 0 for a fact with fewer than 3 right answers.
  Otherwise it starts at `start = max(1.5 × M, M + 2 s)`, rises in a straight line to 4 at `start + 2 × M`, and stays
  at 4 beyond that.
- **weight** `= base + miss boost + slow boost`. This is the figure the facts page shows.
- In a task, a fact's chance of being drawn is in proportion to `base + unit × (miss boost + slow boost)`, where
  `unit = (sum of the domain's bases) / min(N, 20)`. In a domain of up to 20 facts, a boost of 4 makes a fact as
  likely as about 5 average facts. In a larger domain, it takes about a sixth of the draws however large the domain is.

| Fact | a | r | Smoothed time (M = 2 s) | base | miss | slow | weight |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Never asked | 0 | 0 | none | 1.000 | 0 | 0 | 1.000 |
| Never missed, quick | 10 | 10 | 2 s | 0.091 | 0 | 0 | 0.091 |
| Missed on its last answer | 10 | 0 | 2 s | 0.091 | 4 | 0 | 4.091 |
| Missed, then right twice | 10 | 2 | 2 s | 0.091 | 1 | 0 | 1.091 |
| Missed, then right 5 times | 10 | 5 | 2 s | 0.091 | 0 | 0 | 0.091 |
| Never missed, slow | 10 | 10 | 6 s | 0.091 | 0 | 2 | 2.091 |
| Never missed, very slow | 10 | 10 | 9 s | 0.091 | 0 | 4 | 4.091 |
| Never missed, below the start | 10 | 10 | 3.9 s | 0.091 | 0 | 0 | 0.091 |

With `M` = 2 s the slow boost starts at 4 s and is full at 8 s. With `M` = 0.8 s it starts at 2.8 s and is full at
4.4 s.

- [ ] An attempt's questions are drawn with weights from the figures of every other attempt, so its own answers never
      change its own draws. A fact he misses is no more likely to come back later in the same attempt than any other
      fact, including after a run expires or he gives up and comes back (S013). Its weight is higher from the next
      attempt on.
- [ ] The weights on the facts page match the formulas and the table above.
- [ ] The `weight` of `first` and `operands` entries no longer affects which questions are asked. In a task whose
      `operands` give `3` a weight of 10 and `1` a weight of 1, never-asked facts with `n` = 1 and `n` = 3 come up
      about equally often.
- [ ] Over many tasks with no misses and no slow facts, every fact in the domain is asked about equally often, and a
      fact added to the domain later is asked more until it catches up.
- [ ] *Changed in implementation:* In a times-table task of 13 facts that have each been asked about equally often
      and never missed, a fact he gets wrong comes up in roughly one question in six in his next attempts. Its weight
      gives it about 0.29 of the draws, but none of the last three questions is asked again, so it can come up at most
      one question in four. After 5 right answers in a row its boost is gone, and it comes up no more often than the
      others, a little less while they catch up with the extra times it was asked.
- [ ] A fact whose smoothed time is past the slow boost's start comes up more often than its neighbours, and stops
      coming up more often once its smoothed time falls back under the start.
- [ ] None of the last three questions in the attempt is asked again while another question is possible, as before.
      The timing, scoring, pass rules, and quiz page are unchanged.

## Policy file and task editing

- [ ] *Changed in implementation:* An arithmetic `first` or `operands` entry may leave out `weight`, as in
      `- { from: 3, to: 9 }`. A weight already in a file still loads and is ignored, whatever its value, so a weight
      such as `0` that used to fail the load now loads. Every other check on these lists is as before.
- [ ] *Changed in implementation:* The portal's arithmetic task page shows no weight for `first` and `operands`
      rows. Saving the task writes a changed list without weights. A list the save does not change keeps its text, so
      a weight already in it stays, ignored, until that list is next changed.
- [ ] The MCP task write tools accept arithmetic rows without `weight`, ignore a weight given, and their description
      no longer asks for one.
- The arithmetic section of `docs/hierarchical-policy.md` says the lists set which facts can be asked and that
  questions are weighted from his record, and refers to this story for the formulas.
- Skip counting's weighted `difference` list is not changed.

## Facts page

- [ ] *Changed in implementation:* The facts list and the cell readout from S035.2 add All-time asked, Run, Smoothed
      time, Miss boost, Slow boost, and Weight. These come from his whole record, whatever the Period and filters. The
      list heads them All time, beside In this period over the S035.2 columns, and the readout's lines for them start
      "All time:". The list and grid still show the facts asked in the period, each with its all-time figures. Each
      new list column sorts like the others.
- [ ] *Added in implementation:* At phone width the facts list scrolls sideways inside its own box, and the page does
      not scroll sideways.
- [ ] The grid has a third shading, Weight, beside Misses and Time, kept in the address with a key like the others.
- [ ] The page shows the operation's median smoothed time and where the slow boost starts and is full, such as
      "All time: Median 2.0 s. Slow from 4.0 s, full at 8.0 s.", even when nothing was asked in the period. When there
      are too few timed facts it says so, such as "All time: Slow boost starts once 10 facts each have 3 right answers.
      4 have so far."
- Weight shading levels are proposals: under 0.5, 0.5 to 1, 1 to 2, 2 to 4, and 4 or more. Their colours are role
  properties in the theme, as in S035.2. They run from ivory through gold to brick, so they do not look like the
  Misses shading.

## MCP

- [ ] The read-only `get_arithmetic_facts` tool (S036.1) gives each fact the same all-time figures and weight as the
      facts page, and the operation's median smoothed time and where the slow boost starts and is full, or that there
      are too few timed facts yet. Its description says which figures are all-time. It changes nothing.

# Notes

The constants (miss boost 4 halving each right answer, the cut-off at `min(5, a)`, `α`, 3 right answers and 10 facts
before timing counts, `1.5 × M` and `M + 2 s` for the start, `2 × M` to full, a slow boost of at most 4, and the cap of
20 in `unit`) are proposals to try, fixed in the code and not in the policy file. They may be made configurable later.

The slow measure is a multiple of the median and not standard deviations, so it keeps working as he gets fast at
everything and the spread shrinks. The 2 s guard keeps typing a two-digit answer from counting as slow once his
median is small. Smoothing works on the ratio of times, so one distracted 15-second answer does not swamp several
quick ones. Timeouts and wrong answers count only toward the miss boost, so a slow miss is not counted twice. Times
are compared within an operation across all tasks, so each fact has one weight wherever it is asked.

`unit` is needed because `a` counts questions, not tasks as in S033, so bases get small fast. Without it a boost of 4
would take most draws in a single times table and barely show in 400 addition facts.

Weights are fixed for each attempt so every session is a stable sample, and a miss is not pushed back at him in the
same session. Practising a fact straight away is left to the arithmetic practice mode, S039.

Implementation hints: keep the figures in a ledger like S033's, one row per question, so recording is idempotent per
attempt and question, and they survive `rm-attempts`. Read a question's operation from the sign in its stored text, as
S035.2 does. A domain can be large, so draw without listing it: never-asked facts each weigh 1, and only facts with
figures need their own weight. The facts page and `get_arithmetic_facts` share `facts_report`, so the figures are
worked out once for both.

Out of scope: removing statistics, for spelling or arithmetic, which is S038. Configurable constants. Sharing figures
between turned-around facts.

Sized at 13 against S033 (8), which had a ledger, a rebuild, weighted choice, and a command-line tool. This adds the
smoothed times and the median, a weighted draw over a domain that may not be listed one by one, the facts page columns,
shading, and median line, and removing weights from the task editor and MCP write tools.

# Implementation

## Files Added

- `policy/fact_figures.py`: the fact ledger, its one-time rebuild, each fact's all-time figures (asked, run, smoothed
  time), the operation's median and slow boost line, and the weight formulas. `operation_of`, which reads a question's
  operation from its sign, moved here from `arithmetic_facts.py`.
- `tests/test_arithmetic_weighting.py`: counting, idempotence, reopening, the rebuild, smoothing, the weight table, the
  slow boost's thresholds, the draws over many simulated attempts, a huge domain, the last-three rule, an attempt's own
  answers through the quiz page, and the facts report's all-time figures.

## Files Changed

- `policy/arithmetic.py`: `first` and `operands` load without weights and ignore any given. `draw` weights each fact by
  its figures over the task's domain without listing it, and `Session.issue` takes the figures to draw with.
- `policy/quiz.py`: `weighted` can make a list whose entries need no weight, and `WeightedList.has`.
- `policy/tasks.py`: `AttemptStore` builds the fact ledger once, records an arithmetic attempt's answered questions on
  every `save`, `finish`, and `record`, reads figures with `store.facts`, and gives an attempt the figures of every
  other attempt with `draw_figures`.
- `policy/arithmetic_page.py`: issues each question with the attempt's `draw_figures`.
- `policy/arithmetic_facts.py`, `policy/review.py`: each fact on the facts page has `all_time`, and the report has
  `slow`, the median line, whatever the period.
- `policy/number_lists_admin.py`: an arithmetic table has no weight column, a weight in the file is not shown, and one
  sent with a row is ignored.
- `policy/mcp_tools.py`, `policy/mcp_writes.py`: `get_arithmetic_facts` says which figures are all-time. The task write
  tools describe rows without weights for arithmetic.
- `policy/portal/src/facts.ts`, `pages/Facts.tsx`, `components/FactGrid.tsx`: the all-time columns under their own
  heading, their sorts, the readout's all-time lines, the median line, and the Weight shading and key.
- `policy/portal/src/numberTable.ts`, `components/WeightedTable.tsx`, `arithmetic.ts`, `pages/Arithmetic.tsx`,
  `skipCounting.ts`: a table can have no Weight column, and the arithmetic tables have none.
- `policy/portal/src/styles/layout.css`, `styles/theme.css`: the list's own sideways scrolling, its group headings, the
  median line, and the Weight levels as role properties.
- `docs/hierarchical-policy.md`, `docs/parent-portal.md`, `README.md`: the lists set which facts can be asked and
  questions are weighted from his record, a difference still needs a weight, and a grid can have more than one
  shading.
- Tests: `tests/test_arithmetic.py` (draws without weights, and the last-three rule with figures),
  `tests/test_arithmetic_admin.py`, `tests/test_task_create.py`, and `tests/test_mcp_writes.py` (lists without
  weights), `tests/test_mcp_server.py`
  (`get_arithmetic_facts` matches the page), and the portal's `facts.test.tsx`, `arithmetic.test.tsx`,
  `numberTable.test.ts`, and `test/portal.tsx`.

## Files Removed

None.

## Change Summary

The ledger has one row for each question with an outcome, keyed by its attempt (id and start, as in S033) and its
place in the attempt's questions, holding the client group, operation, `m`, `n`, outcome, and time taken. Recording
inserts only questions not yet recorded, so saving again, giving up, and coming back count nothing twice. A question
still showing waits until it has an outcome. Figures are worked out from the rows in the order they were recorded,
when they are asked for, so a fact's run and smoothed time follow the order he answered. Rows are never deleted. The
first start fills the ledger from stored arithmetic attempts in start order, guarded by a marker row written in the
same transaction.

The draw works on the domain as ranges. Every fact with figures gets its own chance, `base + unit × boost`, and the
rest of the domain weighs 1 each and is drawn evenly by walking the ranges and stepping over the facts that have
figures or are recent, as the old weighted draw stepped over recent questions. So a domain of a hundred million
million facts draws as quickly as a times table. The figures an attempt draws with leave out that attempt's own rows,
so they are the same whether he gets its questions right or wrong. Each question reads the ledger again. With 50,000
rows, about three years of daily practice, issuing a question takes about 50 ms.

The weight constants in the story, used as written, give a missed fact in a 13-fact times table 0.29 of the draws. The
unchanged rule against repeating any of the last three questions caps it at one question in four, and in practice it
comes up about one question in six. The checks say so now. Raising the miss boost would bring it nearer one in four, if
that is wanted. Similarly, from a smoothed time of 7 or 8 seconds it takes four 3-second answers, not three, to fall
under a 4-second start, so the scenario says four.

Not checked in a browser: no browser was connected, so the Weight colours, the list's group headings, and its
sideways scrolling at phone width were checked only in jsdom and by a production build of the portal.

## Suggested Acceptance Testing

### Acceptance test cases for S037

Rebuild and start with `make up` on a database that already has a few weeks of arithmetic attempts, including a
multiplication task, and sign in to the parent pages. Make a times-table task, such as `first: [{ value: 7 }]` and
`operands: [{ from: 0, to: 12 }]`, with a pass cooldown of 0.

1. **The facts page's all-time figures.** Open the multiplication facts page with Past week. Check the All time
   columns, their counts against older attempts, the readout's All time lines, and the median line, or the too-few
   message with its count. Sort by each new column, shade by Weight and check the key, reload, and narrow the window
   to phone width. Run `dw restart` and check nothing doubles. Covers the Facts page area and the rebuild check.
2. **A miss.** In the times-table task answer `7 × 8` wrong. Check the facts page at once: Run 0, Miss boost 4.000.
   Keep going and check `7 × 8` comes up no more than the others in the same attempt, including after giving up and
   coming back within the hour. In the next two or three attempts it comes up about one question in six. Answer it
   right 5 times running and check its miss boost is 0. Covers What is counted and the miss checks.
3. **The weights.** Compare a few facts' Run, Smoothed time, boosts, and Weight with the formulas and table, and the
   median line's start and full with the median. Covers the formula and table check.
4. **A slow fact.** Once the median line shows numbers, answer one fact right but slowly, waiting about 8 seconds,
   three or four times. Check its slow boost and that it comes up more often. Answer it in about 3 seconds four times
   and check the boost is 0. Covers the slow checks and the scenario.
5. **Policy file and editing.** In a task file, leave out the weights of one list and give another entry `weight: 0`,
   and check `dw check` passes. For a new operation or client group with no history, give `operands` 1 a weight of 1
   and 3 a weight of 10, and check `n` = 1 and 3 come up about equally. Open the task in the portal: no Weight column.
   Change a row and save, and check the file has no weights. Check a skip counting task still has Weight. Ask the MCP
   agent to update the task with a weight, and check it is written without one. Covers Policy file and task editing.
6. **Groups, removal, and MCP.** Practise a fact as `older` and check `younger`'s figures do not change. Run
   `bin/rm-attempts --client younger --type arithmetic --older-than 7d --yes` and check All-time asked is unchanged for
   facts asked this week. Ask the MCP agent for `get_arithmetic_facts` and compare with the page. Covers the client
   group, removal, and MCP checks.
