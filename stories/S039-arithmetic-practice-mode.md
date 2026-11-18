Ticket: S039
Title: Arithmetic practice mode
Status: Done
Story Points: 8
Last Updated: 2026-11-18 06:25:00
---

# User Voice

As a parent, I want him to practise the facts he finds hardest by walking one number's table two steps up and one
step down, so that each answer follows from the one before, and the change of direction makes him think about which
question was just asked before he answers.

# Behaviour

## Offering practice

- [ ] An arithmetic task with 5 or more values in `operands` shows a smaller "Practice" button at the bottom right of
      the start screen and the question screen, as the spelling task does (S005.2). A task with fewer has no Practice
      button.
- [ ] *Added in implementation:* The Practice buttons are not shown while a walk is on screen, so a walk cannot be
      restarted from inside itself. They are back when it ends.
- [ ] Starting, confirming, and leaving practice work as in S005.2: a confirmation that quiz progress will be reset,
      a question showing is closed as a timeout, practice continues the same attempt, it is allowed when the task is
      the only required one, it never passes the attempt, scores nothing, and never marks it abandoned, and coming
      back after leaving resumes on the start screen with the score at zero.
- [ ] Practice ends when he reaches the end of the walk, which starts a new quiz run on the same attempt from zero, or
      when he gives up through "Try a different task" as usual. *Changed in implementation:* The new run starts when
      practice is entered, as in S005.2, so reloading mid-walk also lands on zero. At the end of the walk the page
      returns to the start screen, which says "Practice done. Start the quiz when you are ready." and shows `0 / n
      correct` with Start focused, and the quiz's first question is asked when he presses Start.

## The walk

The walk is for one `m`, through the task's `n` values in increasing order, going two up and one down. It starts and
ends with a single step up and back, so the first and last `n` are each asked twice and every other `n` three times.
With `N` values of `n` the walk has `3N − 2` questions.

- [ ] `m` is the value in `first` (or in `operands` when there is no `first`) whose facts with the task's `n` values
      have the highest total Weight on the S037 facts page at that moment, including this attempt's answers so far.
      A tie is broken at random. *Changed in implementation:* A fact never asked weighs 1, as in the S037 table, so a
      number with no history is worth as many as there are `n` values and is chosen over numbers he has answered well. A task with `first` of 6 to 8 where most of the 7s show a miss or slow boost
      practises the 7s.
- [ ] The walk asks its questions in order. For `m` = 7 and `n` from 1 to 10 in addition, that is 28 questions: `n` =
      1, 2, 1, 2, 3, 2, 3, 4, 3, 4, 5, 4, 5, 6, 5, 6, 7, 6, 7, 8, 7, 8, 9, 8, 9, 10, 9, 10. It starts `7 + 1`, `7 + 2`,
      `7 + 1`, `7 + 2`, `7 + 3`, `7 + 2`, and ends `7 + 8`, `7 + 9`, `7 + 10`, `7 + 9`, `7 + 10`.
- [ ] Subtraction and division walk the same way, with `m` fixed and `n` moving: `8 − 7`, `9 − 7`, `8 − 7`, ... and
      `7 ÷ 7`, `14 ÷ 7`, `7 ÷ 7`, ....
- [ ] With gaps in `operands`, such as 1, 2, 5, 10, 11, the walk steps through the values in order: 1, 2, 1, 2, 5, 2,
      5, 10, 5, 10, 11, 10, 11.
- [ ] The screen shows how far through the walk he is, such as "Practice: 5 of 28", which goes back when the walk
      falls back.

## Answering

- [ ] Each question allows the task's `max_timeout`, the same for every question in the walk. The timer bar and the
      judging of answers work as in the quiz.
- [ ] A right answer plays the correct sound and moves on. The question with its answer, such as `7 + 2 = 9`, stays on
      screen above the next question and fades away over 3 seconds after that question is shown. *Changed in
      implementation:* It moves on at once, with no pause, and the progress shows the next question's place.
- [ ] A wrong answer or a timeout plays its sound and falls back. The right answer is never shown, and the next
      question has no earlier answer above it. *Changed in implementation:* The page says "Not quite" or "Time ran
      out" for 1 second, clears any answer still fading above the question, and shows the progress going back, then
      asks the next question.
- [ ] Falling back starts the walk again `practice_fallback` values of `n` below the one he missed, or from the first
      `n` when there are not that many below it, with a single step up and back, as at the beginning. With the
      default of 3 and `n` from 1 to 10, missing `7 + 3` starts again at `7 + 1`, and missing `7 + 8` goes on `7 + 5`,
      `7 + 6`, `7 + 5`, `7 + 6`, `7 + 7`, `7 + 6`, `7 + 7`, `7 + 8`, and so on to the end. There is no limit on how many
      times it falls back.
- The fallback counts values of `n`, not numbers, so with `n` of 1, 2, 5, 10, and 11, falling back 3 from 11 starts
  again at 2.

## Policy file and task editing

- [ ] An arithmetic task body may set `practice_fallback`, a whole number 1 or more, which defaults to 3. Any other
      value fails the load, naming the task and the field.
- [ ] The portal's arithmetic task page and the MCP task write tools can set and clear `practice_fallback`. The page
      has a Practice Fallback box under the other settings, empty with the placeholder 3 when the file leaves it out,
      and an empty box is not a problem. An empty box on save removes the field, and `update_task` with `null` does
      the same.

## Records

- [ ] Practice answers count in no figures: not the attempt figures of S035.1, the facts page of S035.2, or the
      all-time figures and weights of S037. *Changed in implementation:* An attempt's figures come from its last run,
      as when spelling practice starts a new run, so once practice is entered they show the new run, with no
      questions, until he answers one. The run he left shows on the attempt page under its own heading.
- [ ] The attempt page lists each practice walk under a Practice heading, with its `m`, and each question, his answer,
      the outcome, and the time taken, as the quiz table does. *Changed in implementation:* Each walk has its own
      heading, such as "Walk 1: m = 7, Addition, finished" (or "left early", or "in progress"), and a table with the
      quiz table's columns and a Step column, such as "5 of 28". Practice questions do not link to the facts page,
      which does not count them.

# Notes

Depends on S037 for the weights that choose `m`, and on S005.2 as the model for starting and leaving practice.

Without the right answer, the next step is one more or one less than the last answer when the `n` values are
contiguous, which he can work out if he is paying attention. Falling back is there to get him back into that sequence,
not to punish, and falling back only a few values stops the low `n` values getting most of the practice, as starting
again from the beginning did. Only the last answer stays on screen, and only briefly, because most questions are asked
three times and a full table on screen would leave little to remember.

Choosing `m` includes this attempt's answers, unlike the quiz draws in S037, so practice turns to what he has just been
finding hard.

The walk for subtraction and division is untried with him. It is kept the same as addition until there is data to say
otherwise. Practice may later become a task type of its own.

Out of scope: choosing `m` by hand, and a practice timeout of its own.

Sized at 8 against S005.2 (5), which added spelling practice with its own screen and audio sequence. This adds the
walk and its fallback, the choice of `m` from S037's weights, the fading answer, a body field in the editor and MCP
tools, and keeping practice out of the figures while showing it on the attempt page.

# Implementation

## Files Added

- `policy/arithmetic_practice.py`: the walk (`length`, `index_at`, `restart`) and `choose_m`, which picks the number to practise from his record.
- `tests/test_arithmetic_practice.py`: the walk and its fallback, the choice of `m`, entering and leaving practice, the server's actions, the page script in the Node harness, the attempt page's walks, and `practice_fallback`.

## Files Changed

- `policy/arithmetic.py`: `practice_fallback` in the settings (`Settings.can_practice` for the 5-operand rule), and the `Session` methods that enter practice (`begin_walk`), issue a walk's question (`practice_question`), and judge its answer (`practice_answer`). The quiz and the walk share the judging in `_outcome`. Closing what is showing also ends a walk in progress.
- `policy/arithmetic_page.py`: the `practice`, `practice_question`, and `practice_answer` requests, the Practice buttons and confirmation, the earlier answer above the question, and the script that runs a walk.
- `policy/quiz.py`: `WeightedList.nth` and `index_of`, to find the value at a place in the list and a value's place without listing a range.
- `policy/quiz_page.py`, `policy/spelling_page.py`: the Practice button and confirmation styles moved from the spelling page into the shared quiz shell, so both pages use one copy.
- `policy/arithmetic_facts.py`: the attempt report lists each practice walk under `practice`.
- `policy/attempt_figures.py`: its description says practice walks are never in an attempt's figures.
- `policy/number_lists_admin.py`: `practice_fallback` is one of an arithmetic task's settings, so the portal's save, the new-task page, and the MCP write tools all take it, and an empty value removes it.
- `policy/mcp_writes.py`: the setting description for `create_task` and `update_task` names `practice_fallback`.
- `policy/portal/src/arithmetic.ts`, `pages/Arithmetic.tsx`, `labels.ts`: the Practice Fallback box, with its default as the placeholder and never a problem when empty.
- `policy/portal/src/pages/Attempt.tsx`: the Practice section, with a heading and a table for each walk.
- `docs/hierarchical-policy.md`, `README.md`: the field, practice mode, and how a walk is stored.
- Tests: `tests/page_harness.js` (a snapshot also records an element's inline style), `tests/test_arithmetic.py` (a bad `practice_fallback` fails the load), `tests/test_arithmetic_admin.py` and `tests/test_mcp_writes.py` (setting and clearing it), and the portal's `arithmetic.test.tsx`, `facts.test.tsx`, and `test/portal.tsx`.

## Files Removed

None.

## Change Summary

**Where practice is kept.** A walk is stored on the attempt's `detail` under `practice`, never among its `questions`. Everything that works out a figure reads `questions` only: the attempt figures, the facts page, the all-time ledger and weights, and the trends. So practice counts in none of them without any change to that code. Entering practice starts a new run on the attempt, as spelling practice does, so the quiz is at zero from then on, a reload lands on zero, and the run he left stays in the record. Each walk records its `run`, `m`, `length`, `fallback`, the position of the `next` question, how it `ended` (`finished`, or `left` when he reloaded, gave up, or went back to the quiz), and its questions.

**The walk.** A walk's whole state is one number, the position of the next question, from 0 to `3N − 3`. The `n` asked at a position, and where a miss starts again (`3 × max(0, index − practice_fallback)`), follow from the position and the index of `n` among the task's values, which `WeightedList.nth` and `index_of` find without listing a range. The walk's `n` values are always the stored settings' `operands`, which cannot change within a run. A miss, a timeout, and a late answer all fall back, judged by the same rule as the quiz and against the same half-second allowance.

**Choosing `m`.** `choose_m` adds the weights of an `m`'s facts with every `n` in `operands`, from his whole record for the client group and operation, with no attempt left out. A fact with no figures weighs 1, so an `m` with none is worth `N` and is never listed, which keeps a task with a huge `first` fast. Totals are compared after rounding to 9 places, so equal totals added in different orders still tie, and a tie is broken at random. Entering practice stores the closed question before choosing, so the choice counts it.

**Requests and page.** `practice` enters, `practice_question` issues the walk's next question with its own timer, and `practice_answer` judges it. They never reach the code that passes an attempt. The walk uses the quiz's question screen, timer bar, and answer box. A right answer moves on at once and its question and answer appear above the next question and fade with an inline transition restarted for each question. A miss clears that line at once, says "Not quite" or "Time ran out" for a second, and goes back. The reply to a miss carries no answer.

**Choices the story left open.** These are written into the Behaviour items as *Changed in implementation* or *Added in implementation*: a never-asked fact weighs 1 in choosing `m`, so an `m` he has never been asked can be chosen over ones he has answered well; the walk's right answers move on with no pause and its misses pause for a second; the end of the walk returns to the start screen and waits for Start; the Practice buttons are hidden during a walk; and the attempt page's walk headings and Step column.

Tests: the full suite passed (2260 tests, of which 67 are in the new `tests/test_arithmetic_practice.py`; two policy-load cases for `practice_fallback` were added to `tests/test_arithmetic.py` after that run and pass on their own), and the portal's 369 tests, its type check, and a production build pass.

Not checked in a browser. The page's script is tested in the Node harness, and the portal in jsdom and by a production build, so the Practice button's position, the fade, and the new attempt page section have not been looked at on screen.

## Suggested Acceptance Testing

### Acceptance test cases for S039

Set up an arithmetic task with a pass cooldown of 0, such as `first: [{ value: 7 }]`, `operands: [{ from: 1, to: 10 }]`, `operation: addition`, `max_timeout: 10s`, `min_timeout: 4s`, and `correct_answers_required: 20`, open it as the child, and sign in to the parent pages.

1. **The walk.** Press Practice on the start screen, confirm, and answer every question right. Check the questions run `7 + 1`, `7 + 2`, `7 + 1`, `7 + 2`, `7 + 3`, `7 + 2`, and on to `7 + 8`, `7 + 9`, `7 + 10`, `7 + 9`, `7 + 10` (28 questions), with "Practice: n of 28" counting up, each right answer left above the next question and fading over about 3 seconds, and the Practice buttons gone. At the end check the start screen says practice is done, shows `0 / 20 correct`, and asks nothing until Start. Covers The walk and the end of practice.
2. **Falling back.** In a new walk, answer wrong at `7 + 3`, and check the next question is `7 + 1`, the count goes back, "Not quite" shows for a second, and the right answer is never shown. In another, get to `7 + 8` and let it time out, and check the walk goes on `7 + 5`, `7 + 6`, `7 + 5`, `7 + 6`, `7 + 7`, `7 + 6`, `7 + 7`, `7 + 8`. Miss the same question several times in a row. Covers Answering.
3. **Gaps, other operations, and the fallback setting.** Set `operands` to `1, 2, 5, 10, 11` and check the walk steps 1, 2, 1, 2, 5, 2, 5, 10, 5, 10, 11, 10, 11, and that missing 11 starts again at 2. Change the operation to subtraction and division and check `8 − 7`, `9 − 7`, `8 − 7` and `7 ÷ 7`, `14 ÷ 7`, `7 ÷ 7`. Set `practice_fallback: 1` and check a miss at `7 + 8` starts at `7 + 7`. Covers The walk and the fallback checks.
4. **Offering practice.** Give `operands` four values and check neither screen has a Practice button. Give it five, including a range such as `{ from: 1, to: 5 }`, and check both screens do. Covers Offering practice.
5. **Entering, leaving, and the attempt.** Answer a few quiz questions, leave one showing, and press Practice on the question screen. Check the confirmation appears with the timer still running, "No, keep going" returns to the question with what you typed, and Enter in the answer box never opens it. Confirm, and check that in the attempt page the question that was showing is a timeout and the attempt stays in progress. Reload mid-walk and check you land on the start screen at `0 / 20 correct`. Make the task the only required one (a past `due_date`) and check Practice still works and "Try a different task" keeps the attempt. Give up on an optional task during a walk and check the attempt is abandoned. Covers Offering practice.
6. **Choosing `m`.** Set `first` to `{ from: 6, to: 8 }`. Over several attempts answer the 7s wrong or slowly and the 6s and 8s right, then check Practice walks the 7s. Then in a new attempt with nothing newly missed, press Practice with a question showing, and check the walk is for that question's `m`. Set `first` to 6 to 8 with no history and press Practice several times to see each of 6, 7, and 8 chosen. Covers Choosing `m`.
7. **Records.** Before and after a walk, note a fact's row on the facts page and the attempt's figures. Check neither changed because of the walk, and in the Attempts list the attempt's figures show the new run. Open `/parent/attempts/<id>` and check the Practice section lists each walk with its `m`, a Step column, and each question's answer, outcome, and time taken. Covers Records.
8. **Setting and clearing `practice_fallback`.** In the portal, check the Practice Fallback box is empty with the placeholder 3, type 2 and Save, check the file has `practice_fallback: 2`, then empty the box and Save and check the line is gone. Type 0 or `x`, Save, and check the policy refuses it naming `practice_fallback`. Put `practice_fallback: 0` in the file and run `dw check`. Ask the MCP agent to set it to 2 and then clear it with `null`. Covers Policy file and task editing.
