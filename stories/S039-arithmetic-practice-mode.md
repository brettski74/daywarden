Ticket: S039
Title: Arithmetic practice mode
Status: Refined
Story Points: 8
Last Updated: 2026-11-18 05:04:43
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
- [ ] Starting, confirming, and leaving practice work as in S005.2: a confirmation that quiz progress will be reset,
      a question showing is closed as a timeout, practice continues the same attempt, it is allowed when the task is
      the only required one, it never passes the attempt, scores nothing, and never marks it abandoned, and coming
      back after leaving resumes on the start screen with the score at zero.
- [ ] Practice ends when he reaches the end of the walk, which starts a new quiz run on the same attempt from zero, or
      when he gives up through "Try a different task" as usual.

## The walk

The walk is for one `m`, through the task's `n` values in increasing order, going two up and one down. It starts and
ends with a single step up and back, so the first and last `n` are each asked twice and every other `n` three times.
With `N` values of `n` the walk has `3N − 2` questions.

- [ ] `m` is the value in `first` (or in `operands` when there is no `first`) whose facts with the task's `n` values
      have the highest total Weight on the S037 facts page at that moment, including this attempt's answers so far.
      A tie is broken at random. A task with `first` of 6 to 8 where most of the 7s show a miss or slow boost
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
      screen above the next question and fades away over 5 seconds after that question is shown.
- [ ] A wrong answer or a timeout plays its sound and falls back. The right answer is never shown, and the next
      question has no earlier answer above it.
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
- [ ] The portal's arithmetic task page and the MCP task write tools can set and clear `practice_fallback`.

## Records

- [ ] Practice answers count in no figures: not the attempt figures of S035.1, the facts page of S035.2, or the
      all-time figures and weights of S037.
- [ ] The attempt page lists each practice walk under a Practice heading, with its `m`, and each question, his answer,
      the outcome, and the time taken, as the quiz table does.

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
