Ticket: S011
Title: Skip counting
Status: Done
Story Points: 8
Last Updated: 2026-11-01 19:04:00
---

# User Voice

As a child, I want to see a row of numbers that count up or down by the same step, with some boxes missing, and fill in the missing ones, so that I can practise skip counting by 2s, 5s, 10s, and more.

As a child, I want another go when I get some boxes wrong, with a bit more help each time, so that I can still work it out myself.

As a parent, I want each try to be worth fewer points than the one before it, I want to choose how many questions he must answer and how many he may have, and I want a session that runs out of questions without enough points to count as a failure.

# Use Cases

## Questions

- A question is a sequence of `sequence_length` whole numbers in an arithmetic progression. Each number is the one before it plus the common difference. A positive difference counts up. A negative difference counts down.
- Every number in the sequence, shown or blank, is between `minimum_value` and `maximum_value`, inclusive. Those two settings are the only limit on the numbers. With the default `minimum_value` of 1, no number is ever zero or negative, even when counting down. With a negative `minimum_value`, a sequence may cross zero in either direction, such as `6, 3, 0, -3, -6` or `-20, -10, 0, 10, 20`.
- `completed` of the numbers are filled in by the system. The rest are blank boxes for him to fill in.
- When `consecutive` is true, at least two of the filled-in numbers are next to each other. When it is false, the filled-in positions can be anywhere, and they may still be next to each other by chance.
- The filled-in positions are drawn at random. Every set of positions that meets the `consecutive` rule is equally likely.
- When `multiples_only` is true, the first number in the sequence is a multiple of the difference's size, so every number in the sequence is one too. Counting by 5s gives 5, 10, 15, but never 3, 8, 13. When it is false, the sequence can start on any number that keeps the whole sequence in range.
- A sequence is a difference and a start value. `5, 10, 15` and `15, 10, 5` are different sequences.

## Drawing a question

- The difference is drawn from the weighted `difference` list. Any difference used by either of the last two questions in this attempt is left out, and the others keep their relative weights.
- When fewer than three distinct differences are configured, the differences are cycled so that questions with the same difference are as far apart as possible. With two differences they alternate. With one, every question uses it.
- The start value is drawn evenly from every start that keeps the sequence in range and meets `multiples_only`. Starts used by the last two questions that had the same difference are left out. The configuration check below makes sure at least one start is always left.

## Screen

- The start screen says "Skip counting", shows his points so far, such as "0 / 8 points", and has a focused Start button, as in S004.1. No timer runs on the start screen.
- A question is a row of `sequence_length` large boxes in the centre of the screen. All of the boxes fit on one line. Above the row, a heading says "Skip Counting" and a line under it says "Fill in the missing numbers".
- A filled-in box is read-only and shows its number in black.
- A blank box can be typed in and shows what he types in royal blue (`#4169E1`).
- A box accepts digits and a minus sign as its first character, and nothing else. A box holding only `-` counts as blank. `013` is the number 13.
- Each box is wide enough for the longest number the configured range allows, including a minus sign.
- The top of the screen shows his points and the question number, such as "5.5 / 8 points" and "Question 6". When `maximum_questions` is set, it says "Question 6 of 20". Quarter points show as `.25` and `.75`, and whole points show no decimals.
- A timer bar at the bottom shrinks from full to empty over `timeout`.

## Entering an answer

- When a question appears, the leftmost blank box has focus.
- Enter while any other box is blank moves focus to the next blank box to the right. Past the rightmost blank box, it wraps to the leftmost blank box.
- Enter while the focused box is the only blank box does nothing.
- Enter with no blank boxes submits the answer. Every box must be correct for the answer to be correct.
- Tab, Shift+Tab, and clicking move between boxes as usual. Read-only boxes do not take focus. Tab and Shift+Tab cycle only through the page's own visible controls: the editable boxes and "Try a different task", plus Start, the confirmation buttons, or "Next task" when they are showing. Focus wraps round instead of moving to the browser's toolbar or address bar. Tabbing into a box that is not blank selects its whole contents, so typing replaces it. The arrow keys move the cursor for a smaller edit. Moving to a box with Enter, and the focus after a wrong try, select the same way. Clicking a box places the cursor where he clicked, as usual. A double-click or a drag selects text.

## Tries and points

- He has up to three tries at each question. A correct answer on the first try scores 1 point, on the second 0.5 points, and on the third 0.25 points.
- A wrong first try plays a sound from `incorrect/` and shows a message saying how many boxes are wrong, such as "2 boxes are wrong. Try again." His entries stay in the boxes, which are all still editable and blue. Nothing shows which boxes are wrong. Focus goes to the leftmost editable box.
- A wrong second try plays a sound from `incorrect/` and shows the same kind of message. Every box he got right becomes read-only and turns black. Every box he got wrong keeps his entry, stays editable, and turns red. Focus goes to the leftmost red box. A red box turns blue again once he changes it.
- A wrong third try plays a sound from `incorrect/`, scores 0 points, and shows the correct answer.
- A correct answer on any try plays a sound from `correct/`, shows that it was correct for about 1 second, and then the next question appears on its own.
- The timer runs for the whole question. It does not reset or pause when he submits a try or when a message is showing.

## Timer running out

- When the timer bar reaches zero, the browser sends whatever is in the boxes, including blanks.
- If every box is correct, it counts as a correct answer on the try he was on, scoring 1, 0.5, or 0.25 points, and plays a sound from `correct/`.
- Otherwise it is a timeout. It scores 0 points, plays a sound from `timeout/`, never one from `incorrect/`, and shows the correct answer.

## Showing the correct answer

- After a wrong third try or a timeout, the correct answer stays on screen for 10 seconds, then the next question appears on its own.
- Every box shows its correct value. Boxes that were right stay black. Each box he missed shows the correct value in green with a thick border, so it stands out without relying on colour alone. His wrong entry is shown struck through beside it. A box he left blank shows only the correct value.
- Enter moves on to the next question once the correct answer has been showing for at least 3 seconds. Enter before then does nothing.
- No timer runs while the correct answer is showing. The boxes cannot be edited, and keys pressed during this time are not carried into the next question.

## Finishing

- A question counts towards the question number once it is finished: correct, wrong on the third try, or timed out.
- The attempt passes when his points reach `correct_answers_required` and at least `minimum_questions` questions are finished. It passes at the moment the server records the answer that meets both conditions. The correct sound for that answer plays, and the "Well done" screen from S004.1 follows.
- A question scores at most 1 point, so the default `minimum_questions`, which equals `correct_answers_required`, never delays a pass. When `minimum_questions` is set higher, he keeps answering after reaching the points until that many questions are finished, and the attempt passes then.
- When `maximum_questions` is set and that many questions are finished without a pass, the attempt is a failure. The failure cooldown and skip day from S003.1 apply.
- When `maximum_questions` is set and at least `minimum_questions` are finished, the attempt fails as soon as full marks on every question left could no longer reach `correct_answers_required`. He is not asked questions that cannot change the result. Before `minimum_questions` are finished, he keeps answering even when he can no longer pass. With 8 points required and a maximum of 10, three wrong answers in a row do not end the attempt at question 4. It can end at question 8 at the earliest.
- When `maximum_questions` is left out, the attempt cannot fail. It ends when he passes or gives up.
- A failure screen says the questions are finished and shows his points, such as "6.25 / 8 points". It offers "Next task" or "All done for now" the same way the "Well done" screen does.

## Shared with the arithmetic shell

These work as S004.1 describes, with the differences noted:

- Server timing. The server records when it issued each question, and that starts the question's time. The browser is not sent the blank boxes' values with the question. A try, or the expired-timer submission, is in time when the server receives it no later than `timeout` plus 0.5 seconds. Anything later is a timeout, whatever it says, and is still recorded.
- The server counts the tries. A fourth try is refused. A submission that is not from the timer running out and has a blank box is refused and does not use a try.
- After a wrong try, the server's response gives the number of wrong boxes. After a wrong second try, it also gives which boxes were right. The full sequence is sent only when the question is finished.
- Sound sets. The `correct/`, `incorrect/`, and `timeout/` sets are shared with arithmetic, with one file chosen at random each time and a new sound stopping the one before it.
- Resume and expiry. Progress is saved as each try is recorded. Coming back within an hour resumes with the same points and question number. A question that was showing when he left counts as a timeout, whatever try he was on. Coming back after more than an hour starts a new run on the same attempt with zero points and zero questions finished.
- Settings. An attempt uses the task body stored on it when its run started.
- "Try a different task". It is the same small button, confirmation, and S003.2 behaviour. A question showing when he gives up counts as a timeout.

# Configuration

A skip counting task is a task from S003.1 with `type: skip_counting`. Its fields are in the task's `body`. Every field is optional.

| Field | Default | Value |
| --- | --- | --- |
| `sequence_length` | 8 | Numbers in each sequence. A whole number from 4 to 12. |
| `completed` | 3 | Numbers filled in by the system. A whole number from 2 to `sequence_length - 1`. |
| `consecutive` | `true` | When true, at least two filled-in numbers are next to each other. |
| `multiples_only` | `false` | When true, every number in a sequence is a multiple of the difference's size, for a difference that does not set its own. |
| `difference` | 2, 5, 10, 25, 100, -2, -5, -10, -25, and -100, each with weight 1, with the maximums described below | The weighted list of common differences, described below. |
| `minimum_value` | 1 | The lowest number allowed in a box, for a difference that does not set its own. A whole number. It may be zero or negative. |
| `maximum_value` | 999 | The highest number allowed in a box, for a difference that does not set its own. A whole number greater than `minimum_value`. |
| `timeout` | `3m` | The time allowed for each question. A duration greater than zero, written as in S004.1, such as `90s` or `3m`. |
| `correct_answers_required` | Worked out from the question limits, described below | The points needed to pass. A whole number, 1 or more. |
| `minimum_questions` | `correct_answers_required` | The number of questions he must finish before the attempt can pass or fail early. A whole number, 1 or more. |
| `maximum_questions` | Not set | The number of questions after which the attempt ends. A whole number, 1 or more. When it is not set, the attempt cannot fail. |

When `correct_answers_required` is left out, it is worked out first, from the fields as written:

- Let `n` be the larger of 8 and `ceil(0.8 × minimum_questions)`. When `minimum_questions` is also left out, `n` is 8.
- When `maximum_questions` is set, the default is the smaller of `n` and `maximum_questions`. Otherwise it is `n`.

Then, when `minimum_questions` is left out, it is `correct_answers_required`, whether that was written or worked out.

| Written | `correct_answers_required` | `minimum_questions` |
| --- | --- | --- |
| Neither, no maximum | 8 | 8 |
| `maximum_questions: 5` | 5 | 5 |
| `maximum_questions: 10` | 8 | 8 |
| `minimum_questions: 15` | 12 | 15 |
| `minimum_questions: 12` | 10 (`ceil(9.6)`) | 12 |
| `minimum_questions: 5` | 8 | 5 |
| `correct_answers_required: 6` | 6 | 6 |
| `minimum_questions: 15`, `maximum_questions: 20` | 12 | 15 |

Each `difference` entry has a `weight` and either one `value` or an inclusive `from`/`to` range, with the same rules as an arithmetic `operands` entry in S004.1, except:

- Values may be negative. A negative difference counts down.
- Zero is not a valid difference, because every number in the sequence would be the same. A `value` of 0, or a `from`/`to` range that includes 0, is invalid configuration. A parent who wants both directions writes two ranges, such as `{ from: -5, to: -1, weight: 1 }` and `{ from: 1, to: 5, weight: 1 }`. This rule is about the difference only. The numbers in a sequence may be zero or cross zero, as the Questions section says.
- An entry may set its own `multiples_only`, which replaces the body's for every difference in that entry, either way. Counting by 25s can start only on multiples of 25 while counting by 3s starts anywhere. Everything in this story that says `multiples_only` means that difference's setting, including the number of sequences a difference allows.
- An entry may set its own `minimum_value` and `maximum_value`. They replace the body's for every difference in that entry, such as `{ value: 2, weight: 1, maximum_value: 99 }` for a child who counts by 25s into the 500s but should keep his 2s under 100. The entry's maximum must be greater than its minimum. Its range may go outside the body's. Everything in this story that says `minimum_value` and `maximum_value` means that difference's range, including the number of sequences a difference allows. Each box is wide enough for the longest number any difference allows.

The default `difference` list caps the maximum and sets `multiples_only` as follows, with each negative difference set the same as the positive one:

| Difference | Maximum | `multiples_only` |
| --- | --- | --- |
| 2 | 99 | The body's |
| 5 | 199 | The body's |
| 10 | 499 | The body's |
| 25 | `maximum_value` | `true` |
| 100 | `maximum_value` | The body's |

When `maximum_value` is lower than a cap, the lower one is used. Every default difference uses `minimum_value`. A `minimum_value` at or above a cap is invalid configuration, and the error says to write a difference list.

These are invalid configuration:

- Any field outside its allowed values, or of the wrong type, or any field not listed above.
- `minimum_questions` greater than `maximum_questions`.
- `correct_answers_required` greater than `maximum_questions`, since he could never pass.
- A difference that allows fewer than 3 distinct sequences within `minimum_value` and `maximum_value` for the configured `sequence_length` and `multiples_only`. The error names the task and the difference.
- All differences together allowing fewer distinct sequences than `maximum_questions` when it is set, or fewer than the larger of `correct_answers_required` and `minimum_questions` when it is not.

For example, counting by 100 with `sequence_length: 8` spans 700, so with the default range of 1 to 999 a sequence can start anywhere from 1 to 299, which is 299 sequences. With `multiples_only: true`, it can only start on 100 or 200, which is 2 sequences, so the policy fails to load. The default `difference` list with `sequence_length: 12` is also invalid, because counting by 100 then spans 1,100, which does not fit in 1 to 999.

Invalid skip counting configuration fails the policy load, the same as invalid arithmetic configuration. The previous policy stays in force, and the error names the task and the field.

This example counts by 2s, 5s, and 10s, up or down, between 0 and 200, with 10 numbers in each sequence and 4 filled in. He must finish at least 10 questions with 8 points, and the attempt fails after 15 questions:

```yaml
tasks:
  skip-counting:
    type: skip_counting
    group: younger
    pass_cooldown: 1
    failure_cooldown: 0
    body:
      sequence_length: 10
      completed: 4
      minimum_value: 0
      maximum_value: 200
      difference:
        - { value: 2, weight: 3 }
        - { value: 5, weight: 2 }
        - { value: 10, weight: 1 }
        - { value: -2, weight: 3 }
        - { value: -5, weight: 2 }
        - { value: -10, weight: 1 }
      minimum_questions: 10
      maximum_questions: 15
      timeout: 2m
```

`correct_answers_required` is left out here. The larger of 8 and `ceil(0.8 × 10)` is 8, and the smaller of that and 15 is 8, so 8 points are required.

# Attempt Record

The attempt's `detail` from S003.1 holds `settings`, `runs`, and `last_activity` as S004.1 describes, and `questions`: every question issued in this attempt, in order. Each one has:

- the run number
- the difference and the start value
- the full sequence
- the positions that were filled in by the system
- each try: what he entered in every blank box as received, the number of wrong boxes, whether it came from the timer running out, and the time it was received in milliseconds from issue
- the outcome: `correct`, `incorrect`, or `timeout`
- the try that was correct, 1 to 3, for a `correct` outcome
- the points scored: 1, 0.5, 0.25, or 0
- the time allowed in milliseconds
- the household-local time the question was issued

His points are the sum of points for questions in the current run. The question number is the number of finished questions in the current run. The last two differences and the recent starts for each difference come from this list, across runs.

S003.3 already shows this record, so a parent can read it as soon as this story is done. A formatted review like S004.6 is a later story.

# Acceptance Criteria

## Configuration

- [x] A body with no fields loads with the defaults: 8 numbers, 3 filled in, consecutive, any start, the ten default differences with equal weight, values from 1 to 999, a 3-minute timeout, 8 points required, a minimum of 8 questions, and no maximum.
- [x] With the defaults, counting by 2 never goes above 99, by 5 above 199, or by 10 above 499, in either direction. Counting by 25 and 100 can go up to 999. With a `maximum_value` below a cap, the lower one is used.
- [x] With the defaults, every sequence counting by 25 or -25 is made of multiples of 25, and the other defaults include starts that are not multiples. A difference that sets `multiples_only` uses its own setting either way, and one that sets it true is checked for 3 sequences on that basis.
- [x] A difference with its own `minimum_value` and `maximum_value` draws every sequence within that range, while the other differences keep the body's. An entry range whose maximum is not above its minimum, or that allows fewer than 3 sequences, is rejected naming the entry. The boxes are wide enough for the widest range.
- [x] Each row of the defaults table under Configuration gives the `correct_answers_required` and `minimum_questions` shown there.
- [x] A `sequence_length` of 3 or 13, a `completed` of 1, a `completed` equal to `sequence_length`, a `maximum_value` not greater than `minimum_value`, a `timeout` of `0s` or a bare number, and an unknown field are each rejected, with the task and field named.
- [x] A difference of 0, or a range from -5 to 5, is rejected. Negative values and ranges such as -5 to -1 are accepted.
- [x] A repeated difference, overlapping ranges, a weight of zero, and an entry with both `value` and `from` are each rejected, as for arithmetic operands.
- [x] `minimum_questions` greater than `maximum_questions`, and `correct_answers_required` greater than `maximum_questions`, are each rejected.
- [x] Counting by 100 with 8 numbers between 1 and 999 is accepted without `multiples_only`. With `multiples_only: true` it is rejected, naming the difference 100.
- [x] The default `difference` list with `sequence_length: 12` is rejected, naming the difference 100.
- [x] A configuration whose differences allow 14 distinct sequences in total is rejected with `maximum_questions: 15` and accepted with `maximum_questions: 14`. With no maximum, it is rejected when `correct_answers_required` or `minimum_questions` is 15.
- [x] Invalid configuration fails the policy load and leaves the previous policy in force.

## Drawing questions

- [x] Every number in every drawn sequence is within `minimum_value` and `maximum_value`, and each number is the previous one plus the drawn difference. A long run of draws, including negative differences and negative minimum values, checks this.
- [x] With the default `minimum_value` of 1 and negative differences, no number in any sequence is zero or negative.
- [x] With `minimum_value: -50` and `maximum_value: 50`, a large sample includes sequences that cross zero counting up and sequences that cross zero counting down, and the answer boxes accept negative answers.
- [x] With `multiples_only: true`, every number in every sequence is a multiple of the difference's size. With it false, a large sample includes starts that are not multiples.
- [x] Exactly `completed` positions are filled in. With `consecutive: true`, every question has at least two adjacent filled-in positions. With `consecutive: false`, a large sample includes questions with no adjacent filled-in positions.
- [x] With three or more differences, no question uses a difference used by either of the two questions before it. With the last two differences left out, a large sample of the next difference follows the remaining weights within a stated tolerance.
- [x] With two differences, questions alternate between them. With one, every question uses it.
- [x] No question repeats the start of either of the last two questions that had the same difference.
- [x] The question sent to the browser has the filled-in values and positions and does not include the blank boxes' values.

## Entering and trying

- [x] When a question appears, the leftmost blank box has focus. Filled-in boxes are read-only and black. Blank boxes are editable and show typed digits in royal blue.
- [x] Letters and other symbols do not appear in a box. A minus sign appears only as the first character.
- [x] Enter with other blank boxes moves focus to the next blank box to the right, and wraps from the rightmost blank box to the leftmost. Enter when the focused box is the only blank does nothing. Enter with no blanks submits.
- [x] A correct first try scores 1 point and plays a sound from `correct/`. The next question appears after about 1 second.
- [x] A wrong first try plays a sound from `incorrect/` and says how many boxes are wrong. All of his entries stay editable and blue, and nothing marks which ones are wrong. A correct second try then scores 0.5 points.
- [x] A wrong second try plays a sound from `incorrect/` and says how many boxes are incorrect. The correct boxes become read-only and black, and the incorrect ones stay editable and turn red. A red box turns blue when he changes it. A correct third try then scores 0.25 points.
- [x] A wrong third try plays a sound from `incorrect/`, scores 0, and shows the correct answer.
- [x] The server refuses a fourth try, and refuses a submission with a blank box that is not from the timer running out. Neither uses a try.
- [x] The timer keeps running through every try and message. It is not reset by a submission.

## Timer and server timing

- [x] When the timer runs out with every box correct, the answer scores the points for the try he was on: 1, 0.5, or 0.25. A test covers each try.
- [x] When the timer runs out with any box blank or wrong, the question is a timeout. It scores 0, plays a sound from `timeout/` and never one from `incorrect/`, and shows the correct answer.
- [x] A try the server receives within `timeout` plus 0.5 seconds is judged on its values. A correct try received after that is a timeout and is still recorded. A test drives the server's clock.

## Showing the correct answer

- [x] After a wrong third try or a timeout, every box shows its correct value. Missed boxes show the correct value in green with a thick border and his wrong entry struck through. A box left blank shows only the correct value.
- [x] The correct answer shows for 10 seconds and then the next question appears on its own. Enter moves on after 3 seconds and does nothing before then. Keys pressed during this time are not carried into the next question.

## Finishing

- [x] With no minimum or maximum, the attempt passes on the answer that brings his points to `correct_answers_required`, such as 1 + 1 + 0.5 + 0.25 + ... reaching 8. It records a pass at that moment and increments today's revision count.
- [x] With `minimum_questions: 10` and 8 points reached after 9 questions, the attempt passes when the 10th question is finished, whatever it scores.
- [x] With `maximum_questions: 15` and fewer than the required points after 15 finished questions, the attempt is a failure. The failure cooldown and skip day from S003.1 apply.
- [x] With `minimum_questions: 10`, `maximum_questions: 15`, and 8 points required, 2.75 points after 10 questions ends the attempt as a failure straight away, because 5 more full marks would only reach 7.75. 3 points after 10 questions keeps it going.
- [x] With only `maximum_questions: 15` and 8 points required, the attempt passes on the answer that reaches 8 points, even when that is well before the 15th question.
- [x] With only `maximum_questions: 15` and 8 points required, 2.75 points after 10 questions ends the attempt as a failure straight away. 3 points after 10 questions keeps it going.
- [x] With only `maximum_questions: 10`, so that 8 points and 8 questions are the defaults, three wrong answers to start do not end the attempt. It keeps going to question 8, and fails then if a pass is no longer possible.
- [x] With `minimum_questions: 12`, `maximum_questions: 15`, and 8 points required, 1 point after 10 questions keeps the attempt going to the 12th question, and it fails then.
- [x] With no `maximum_questions`, wrong answers and timeouts never make the attempt fail.
- [x] The progress line shows points with quarter points, such as "5.75 / 8 points", and "Question 6", or "Question 6 of 15" when `maximum_questions` is set.
- [x] The failure screen shows his points and offers "Next task" or "All done for now" as the "Well done" screen does.

## Resume, give-up, and record

- [x] Reloading after a wrong first try records that question as a timeout with 0 points. The start screen shows the same points and question number, and the next question is a new one.
- [x] Coming back within an hour resumes the same points and question number. After more than an hour, a new run starts at zero points and zero questions on the same attempt, with the earlier questions kept as an expired run.
- [x] "Try a different task" works as in S004.1, and a question showing when he gives up counts as a timeout.
- [x] Each question is stored with its run, difference, start, sequence, filled-in positions, every try, outcome, correct try, points, time allowed, and issue time, and shows in the S003.3 attempt view.
- [x] `docs/hierarchical-policy.md` describes the skip counting fields, their defaults, the configuration checks, and the scoring.

# Notes

Depends on S004.1 for the session shell, server timing, sound sets, resume, and give-up, and on S003.2 for the task picker and give-up rules. The shell's question and answer handling is single-box today, so this story either generalises the shell or builds a sibling page that shares its timing, sound, and resume code.

Unlike arithmetic, this task can fail, but only when `maximum_questions` is set. A required skip counting task without a maximum stays required until he passes it, as a required arithmetic task does.

The 1-second correct feedback, the 10-second correct-answer display, the 3-second wait before Enter can skip it, and the 0.5-second network allowance are constants in the code, not configuration.

Two-question lookbacks for differences and starts are the parent's choice for variety. The rule of at least 3 sequences for each difference guarantees a start is always available after leaving out the last two for that difference.

# Implementation

## Files Added/Changed/Removed

- Added `policy/quiz.py`: what both quizzes share. It holds weighted lists, durations, and `QuizRecord`, which covers runs, the one-hour expiry, resume, and closing a question left showing. These moved out of `policy/arithmetic.py`.
- Added `policy/quiz_page.py`: the shared page shell. It holds the document skeleton, the common CSS, and the common script: `post`, `play`, "Try a different task" with its confirmation, and the end screen with "Next task" or "All done for now". It also holds `reload`, `json_response`, and `next_task_url`. These moved out of `policy/arithmetic_page.py`.
- Added `policy/skip_counting.py`: body validation and defaults, the sequence count checks, the difference, start, and filled-position draws, and the session (tries, points, and the pass or fail verdict).
- Added `policy/skip_counting_page.py`: the child-facing page, its script, and the `?do=visit`, `?do=question`, and `?do=answer` requests.
- Added `tests/test_skip_counting.py` (86 tests).
- Changed `policy/arithmetic.py` and `policy/arithmetic_page.py` to use the shared modules. Their behaviour and stored record are unchanged. `settle` now also returns how a give-up ends.
- Changed `policy/hierarchy.py` to check a `skip_counting` body when the policy is loaded.
- Changed `policy/task_page.py` to route by quiz type. A give-up records the pass or failure that closing the showing question decides, and otherwise an abandonment.
- Changed `docs/hierarchical-policy.md` and `README.md` to describe the skip counting fields, defaults, configuration checks, scoring, and record.

## Change Summary

A `skip_counting` body is checked at load. Each field is checked in turn, the defaults are worked out as the Configuration section describes, and the per-difference and total sequence counts are checked. An error raises `ConfigError` naming the task and the field. For example: `task 'count': body.difference entry 5: counting by 100 allows only 0 sequences of 12 numbers between 1 and 999; each difference needs at least 3`. The previous policy stays in force. Without `multiples_only`, the largest difference in a range is always the worst case, so only it is counted. With `multiples_only` the count is uneven, so every difference above `(maximum - minimum + 1) // (sequence_length + 2)` is counted. Below that size, three sequences are guaranteed. A brute-force test checks this against a naive count over 400 random configurations.

The difference draw leaves out the last two differences and walks the weighted list exactly, as the arithmetic draw does. With fewer than three differences, it leaves out only as many as still leaves one, so two alternate. The start is drawn evenly from a `range` of allowed starts, skipping the last two used with that difference. The filled positions are drawn evenly from every combination that meets `consecutive`. That is at most 924 combinations, for 12 numbers with 6 filled in.

The server records each try's entries, wrong count, expired flag, and time from issue. A try more than 0.5 seconds past the timeout is a timeout and is still recorded. A blank or `-` box is refused unless the timer ran out. A fourth try is refused with a reload, because the question is already finished. The answer response gives the wrong count, the right positions after a wrong second try, and the full sequence only once the question is finished. Points are summed per run. The attempt is finished as `pass` or `failure` as soon as the verdict is known. That includes a reload or give-up that closes the showing question and so finishes the run. For example, the 10th question timing out on a reload when `minimum_questions` is 10 and he already has 8 points passes the attempt.

The page builds one input per box. Given boxes are read-only, black, skipped by Tab, and ignore clicks. Blank boxes accept digits and a leading minus. Enter moves to the next blank to the right, wrapping round. Enter does nothing when the focused box is the only blank, and submits when there are none. The timer is set once per question. If it runs out while a try is in flight, the page sends the expired submission as soon as the wrong-try response arrives. The answer reveal draws static boxes. A missed box shows the answer in green with a 7 px border, and his entry struck through just under the box rather than beside it, so the row keeps its width and stays on one line. The font size scales with the number of boxes and the widest number, so 12 boxes of `-100` stay on one line at 480 px wide.

Checked in a real browser against a local server:

- **Entering numbers:** the leftmost blank had focus. `1a1-7x` typed as `117`, and a leading `-5` was kept. Given boxes were black and entries `rgb(65, 105, 225)`. Every Enter case behaved as specified.
- **Wrong tries:** a wrong first try said "1 box is wrong. Try again." and left everything editable and blue. A wrong second try locked the right boxes black and turned the wrong ones red. A red box turned blue when changed. A right second try scored 0.5 and moved on after 1.05 s.
- **Reveal:** a wrong third try showed the answer with the missed box in green, and Enter in the first 3 seconds did nothing. The reveal moved on by itself after 10.03 s.
- **Timer:** with every box right when the 12 s timer ran out, it scored a point. With blanks and one wrong box it was "Time ran out", and the blanks showed only the answer.
- **Resume:** a reload resumed at "1 / 8 points" and "Question 5".
- **Failure:** wrong answers on a task with a maximum of 10 ended at question 8 on "The questions are finished", "0.5 / 8 points", with "Next task" focused. The attempt was stored as `failure`.
- **Arithmetic regression:** the arithmetic page still started, scored, kept the give-up confirmation, and finished on "Well done".

The browser tool's own clicks and key presses never reached the page as real input, so the Start button and Enter key were driven through DOM events instead. Sounds were checked by URL in the tests and not listened to.

### Ranges for each difference (added after the first delivery)

Each `difference` entry may carry `minimum_value` and `maximum_value`. `policy.quiz.weighted` now accepts extra keys on an entry and passes the written mapping to the check. Skip counting records a `Bounds` range for each entry, and `Settings.range_for(difference)` returns it. The start draw, the 3-sequence check, the total sequence check, the box width, and the minus-sign keyboard hint all read those ranges. The default list caps 2, 5, and 10 at 99, 199, and 499, never above `maximum_value`. An entry may also set `multiples_only`, held on the same `Bounds` record. `Settings.bounds_for(difference)` returns the range and the flag together. The default list sets it for 25 and -25. `tests/test_skip_counting.py` has 11 more tests, 97 in all. They cover the default caps, the lower body maximum, an entry range on a single value and on a range, the width, the rejected entry ranges, and the question count using each range.

The question screen now has a "Skip Counting" heading and a "Fill in the missing numbers" line above the row. These are static text, so no test was added for them. They were checked in the browser.

The shared quiz script in `policy/quiz_page.py` now traps Tab and Shift+Tab. Both cycle through the page's visible, enabled, non-read-only buttons, inputs, and links, and wrap round, so focus no longer leaves for the browser's toolbar. Arithmetic gets the same behaviour. This is browser script, and the project has no JavaScript test harness, so it was checked in the browser instead:

- the start screen cycled between Start and "Try a different task"
- a skip counting question cycled through the editable boxes, skipping the read-only ones, then "Try a different task", in both directions
- an arithmetic question cycled between the answer box and "Try a different task"

The browser's own shortcuts, such as Ctrl+L, F6, and clicking the toolbar, still reach the browser. A page cannot block those.

Landing in a text box with Tab, Shift+Tab, or Enter selects its contents, and so does the focus after a wrong try. Enter only moves to blank boxes, so the selection matters there only for a box holding just `-`. Typing then replaces the minus sign. Nothing selects on the focus event itself, so a click places the cursor as usual. In the browser:

- every filled box Tab landed in had its whole contents selected
- Enter wrapping round to a `-` box selected it
- the first editable box after a wrong try was selected
- a click in the middle of `42` left a plain cursor at position 2

The full suite had 716 passing tests at first delivery, 86 of them new. The 18 failures are the same as before this change: the `config/policy.yaml` sample tests, the two database-upgrade tests, `test_make_env`, and the Docker proxy tests.

## Suggested Acceptance Testing

### Acceptance test cases for S011

1. Add the story's example task to `config/policy.yaml` (`sequence_length: 10`, `completed: 4`, 0 to 200, ±2, ±5, and ±10, `minimum_questions: 10`, `maximum_questions: 15`, `timeout: 2m`), rebuild, and open it from the child's computer. Confirm the start screen says "Skip counting", "0 / 8 points", and "Question 1 of 15", with Start focused. Press Enter and confirm a "Skip Counting" heading and "Fill in the missing numbers" above a row of 10 boxes on one line, 4 filled in black with at least two side by side, the leftmost blank focused, and the timer bar shrinking.
2. Press Tab and Shift+Tab repeatedly and confirm focus cycles only through the blank boxes and "Try a different task", never the filled-in boxes or the browser's toolbar. Tab into a box you have already typed in and confirm its number is selected, so typing replaces it, and that an arrow key lets you edit one digit instead. Type `-` in a box, press Enter until focus wraps back to it, and confirm the `-` is selected. Click in the middle of a number and confirm the cursor lands where you clicked with nothing selected. Type letters, symbols, and a minus sign after a digit, and confirm none of them appear. Type digits and confirm they show in royal blue. Press Enter with other blanks left and confirm focus jumps to the next blank to the right, wrapping round from the last. With one blank left, press Enter there and confirm nothing happens.
3. Fill every box with one wrong and press Enter. Confirm the `incorrect/` sound, "1 box is wrong. Try again.", every entry still blue and editable, nothing marking the wrong box, and the timer still running. Fix it and submit. Confirm "Correct!", the `correct/` sound, "0.5 / 8 points", and the next question after about a second.
4. Get a question wrong twice. On the second, confirm the right boxes turn black and read-only (Tab skips them) and the wrong ones turn red. Change a red box and confirm it turns blue. Submit a right third try and confirm 0.25 points.
5. Get a question wrong three times. Confirm the answer shows with your wrong boxes in green with a thick border and your entry struck through, the right boxes in black, and no timer bar. Press Enter straight away and confirm nothing happens. Press it again after 3 seconds and confirm the next question comes. On another question, wait and confirm it moves on by itself after about 10 seconds. Type during the reveal and confirm nothing carries into the next question.
6. Use a short `timeout` (such as `20s`). Fill every box right and let the timer run out without pressing Enter, and confirm it scores the point. Then let it run out with a blank box, and confirm "Time ran out", the `timeout/` sound and never an `incorrect/` one, and the answer shown, with the blank box showing only the right value.
7. With the example task (maximum 15, minimum 10, 8 points), answer the first 10 questions so you have 2.75 points, and confirm "The questions are finished" with "2.75 / 8 points" straight after the 10th, plus "Next task" or "All done for now". In `/attempts`, confirm the attempt is a `failure`, that `failure_cooldown` applies, and that a skip day is recorded.
8. Pass the task: reach 8 points with at least 10 questions finished. Confirm "Well done" appears at that answer, today's revision count goes up, and the attempt is a `pass`. With `minimum_questions: 10`, confirm that reaching 8 points at question 9 still needs a 10th question, whatever it scores.
9. Remove `maximum_questions` and get many wrong or let them time out. Confirm the attempt never fails, and the top shows "Question N" with no "of".
10. Reload after a wrong first try. Confirm the start screen keeps the points and shows the next question number, and the left question is stored as a `timeout` with 0 points and its one try. Leave for more than an hour and come back, and confirm "0 / 8 points" on the same attempt with the earlier questions kept in an expired run.
11. Click "Try a different task" during a question. Confirm the confirmation works as for arithmetic, that an optional task is abandoned, and that the question showing is stored as a `timeout`. Make the task the only required one and confirm the "has to be finished" note returns to the start screen with the points kept.
12. Set `minimum_value: -50` and `maximum_value: 50` with ±3 and ±5, and confirm sequences cross zero both ways and that typing `-15` scores as right. With the defaults, confirm no box ever shows zero or a negative number.
13. Set `multiples_only: true` and confirm every number is a multiple of the step. Set `consecutive: false` and confirm some questions have no two filled-in boxes side by side.
14. Load each bad body in turn and confirm each fails with the task and field named and the previous policy in force:
    - `sequence_length` of 3 or 13
    - `completed` of 1 or equal to `sequence_length`
    - `maximum_value` not above `minimum_value`
    - `timeout: 0s` and a bare `timeout: 90`
    - an unknown field
    - a difference of `0`, or the range `-5` to `5`
    - a repeated difference, overlapping ranges, a zero weight, and an entry with both `value` and `from`
    - `minimum_questions` above `maximum_questions`, and `correct_answers_required` above `maximum_questions`
    - `difference: [{ value: 100, weight: 1 }]` with `multiples_only: true`
    - the default list with `sequence_length: 12`
15. Load `body: {}` and confirm it works with the defaults: 8 numbers, 3 filled in, 1 to 999, 3 minutes, 8 points. Over a dozen questions, confirm counting by 2 stays under 100, by 5 under 200, and by 10 under 500, in both directions, while 25s and 100s can go higher. Confirm counting by 25 always lands on multiples of 25 (25, 50, 75, ...), while the others can start anywhere.
16. Give one difference its own range, such as `{ value: 2, weight: 1, maximum_value: 60 }` beside `{ value: 25, weight: 1 }`, and confirm the 2s stay at or under 60 while the 25s use the body range. Load `{ value: 10, weight: 1, maximum_value: 50 }` and confirm it fails naming that entry, because 8 numbers counting by 10 do not fit under 50. Set `multiples_only: true` on just one difference and confirm only that one sticks to multiples. Then set it true on the body and `false` on one entry, and confirm that entry starts anywhere.
17. Open a skip counting attempt in `/attempts/<id>`. Confirm each question shows its run, difference, start, sequence, filled positions, every try, outcome, correct try, points, time allowed, and issue time.
18. Run one arithmetic task end to end and confirm it behaves as before: start, answers, the give-up confirmation, and "Well done".
