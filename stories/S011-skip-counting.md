Ticket: S011
Title: Skip counting
Status: Refined
Story Points: 8
Last Updated: 2026-11-01 17:47:00
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
- A question is a row of `sequence_length` large boxes in the centre of the screen. All of the boxes fit on one line.
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
- Tab, Shift+Tab, and clicking move between boxes as usual. Read-only boxes do not take focus.

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
| `multiples_only` | `false` | When true, every number in a sequence is a multiple of the difference's size. |
| `difference` | 2, 5, 10, 25, 100, -2, -5, -10, -25, and -100, each with weight 1 | The weighted list of common differences, described below. |
| `minimum_value` | 1 | The lowest number allowed in any box. A whole number. It may be zero or negative. |
| `maximum_value` | 999 | The highest number allowed in any box. A whole number greater than `minimum_value`. |
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

- [ ] A body with no fields loads with the defaults: 8 numbers, 3 filled in, consecutive, any start, the ten default differences with equal weight, values from 1 to 999, a 3-minute timeout, 8 points required, a minimum of 8 questions, and no maximum.
- [ ] Each row of the defaults table under Configuration gives the `correct_answers_required` and `minimum_questions` shown there.
- [ ] A `sequence_length` of 3 or 13, a `completed` of 1, a `completed` equal to `sequence_length`, a `maximum_value` not greater than `minimum_value`, a `timeout` of `0s` or a bare number, and an unknown field are each rejected, with the task and field named.
- [ ] A difference of 0, or a range from -5 to 5, is rejected. Negative values and ranges such as -5 to -1 are accepted.
- [ ] A repeated difference, overlapping ranges, a weight of zero, and an entry with both `value` and `from` are each rejected, as for arithmetic operands.
- [ ] `minimum_questions` greater than `maximum_questions`, and `correct_answers_required` greater than `maximum_questions`, are each rejected.
- [ ] Counting by 100 with 8 numbers between 1 and 999 is accepted without `multiples_only`. With `multiples_only: true` it is rejected, naming the difference 100.
- [ ] The default `difference` list with `sequence_length: 12` is rejected, naming the difference 100.
- [ ] A configuration whose differences allow 14 distinct sequences in total is rejected with `maximum_questions: 15` and accepted with `maximum_questions: 14`. With no maximum, it is rejected when `correct_answers_required` or `minimum_questions` is 15.
- [ ] Invalid configuration fails the policy load and leaves the previous policy in force.

## Drawing questions

- [ ] Every number in every drawn sequence is within `minimum_value` and `maximum_value`, and each number is the previous one plus the drawn difference. A long run of draws, including negative differences and negative minimum values, checks this.
- [ ] With the default `minimum_value` of 1 and negative differences, no number in any sequence is zero or negative.
- [ ] With `minimum_value: -50` and `maximum_value: 50`, a large sample includes sequences that cross zero counting up and sequences that cross zero counting down, and the answer boxes accept negative answers.
- [ ] With `multiples_only: true`, every number in every sequence is a multiple of the difference's size. With it false, a large sample includes starts that are not multiples.
- [ ] Exactly `completed` positions are filled in. With `consecutive: true`, every question has at least two adjacent filled-in positions. With `consecutive: false`, a large sample includes questions with no adjacent filled-in positions.
- [ ] With three or more differences, no question uses a difference used by either of the two questions before it. With the last two differences left out, a large sample of the next difference follows the remaining weights within a stated tolerance.
- [ ] With two differences, questions alternate between them. With one, every question uses it.
- [ ] No question repeats the start of either of the last two questions that had the same difference.
- [ ] The question sent to the browser has the filled-in values and positions and does not include the blank boxes' values.

## Entering and trying

- [ ] When a question appears, the leftmost blank box has focus. Filled-in boxes are read-only and black. Blank boxes are editable and show typed digits in royal blue.
- [ ] Letters and other symbols do not appear in a box. A minus sign appears only as the first character.
- [ ] Enter with other blank boxes moves focus to the next blank box to the right, and wraps from the rightmost blank box to the leftmost. Enter when the focused box is the only blank does nothing. Enter with no blanks submits.
- [ ] A correct first try scores 1 point and plays a sound from `correct/`. The next question appears after about 1 second.
- [ ] A wrong first try plays a sound from `incorrect/` and says how many boxes are wrong. All of his entries stay editable and blue, and nothing marks which ones are wrong. A correct second try then scores 0.5 points.
- [ ] A wrong second try plays a sound from `incorrect/` and says how many boxes are incorrect. The correct boxes become read-only and black, and the incorrect ones stay editable and turn red. A red box turns blue when he changes it. A correct third try then scores 0.25 points.
- [ ] A wrong third try plays a sound from `incorrect/`, scores 0, and shows the correct answer.
- [ ] The server refuses a fourth try, and refuses a submission with a blank box that is not from the timer running out. Neither uses a try.
- [ ] The timer keeps running through every try and message. It is not reset by a submission.

## Timer and server timing

- [ ] When the timer runs out with every box correct, the answer scores the points for the try he was on: 1, 0.5, or 0.25. A test covers each try.
- [ ] When the timer runs out with any box blank or wrong, the question is a timeout. It scores 0, plays a sound from `timeout/` and never one from `incorrect/`, and shows the correct answer.
- [ ] A try the server receives within `timeout` plus 0.5 seconds is judged on its values. A correct try received after that is a timeout and is still recorded. A test drives the server's clock.

## Showing the correct answer

- [ ] After a wrong third try or a timeout, every box shows its correct value. Missed boxes show the correct value in green with a thick border and his wrong entry struck through. A box left blank shows only the correct value.
- [ ] The correct answer shows for 10 seconds and then the next question appears on its own. Enter moves on after 3 seconds and does nothing before then. Keys pressed during this time are not carried into the next question.

## Finishing

- [ ] With no minimum or maximum, the attempt passes on the answer that brings his points to `correct_answers_required`, such as 1 + 1 + 0.5 + 0.25 + ... reaching 8. It records a pass at that moment and increments today's revision count.
- [ ] With `minimum_questions: 10` and 8 points reached after 9 questions, the attempt passes when the 10th question is finished, whatever it scores.
- [ ] With `maximum_questions: 15` and fewer than the required points after 15 finished questions, the attempt is a failure. The failure cooldown and skip day from S003.1 apply.
- [ ] With `minimum_questions: 10`, `maximum_questions: 15`, and 8 points required, 2.75 points after 10 questions ends the attempt as a failure straight away, because 5 more full marks would only reach 7.75. 3 points after 10 questions keeps it going.
- [ ] With only `maximum_questions: 15` and 8 points required, the attempt passes on the answer that reaches 8 points, even when that is well before the 15th question.
- [ ] With only `maximum_questions: 15` and 8 points required, 2.75 points after 10 questions ends the attempt as a failure straight away. 3 points after 10 questions keeps it going.
- [ ] With only `maximum_questions: 10`, so that 8 points and 8 questions are the defaults, three wrong answers to start do not end the attempt. It keeps going to question 8, and fails then if a pass is no longer possible.
- [ ] With `minimum_questions: 12`, `maximum_questions: 15`, and 8 points required, 1 point after 10 questions keeps the attempt going to the 12th question, and it fails then.
- [ ] With no `maximum_questions`, wrong answers and timeouts never make the attempt fail.
- [ ] The progress line shows points with quarter points, such as "5.75 / 8 points", and "Question 6", or "Question 6 of 15" when `maximum_questions` is set.
- [ ] The failure screen shows his points and offers "Next task" or "All done for now" as the "Well done" screen does.

## Resume, give-up, and record

- [ ] Reloading after a wrong first try records that question as a timeout with 0 points. The start screen shows the same points and question number, and the next question is a new one.
- [ ] Coming back within an hour resumes the same points and question number. After more than an hour, a new run starts at zero points and zero questions on the same attempt, with the earlier questions kept as an expired run.
- [ ] "Try a different task" works as in S004.1, and a question showing when he gives up counts as a timeout.
- [ ] Each question is stored with its run, difference, start, sequence, filled-in positions, every try, outcome, correct try, points, time allowed, and issue time, and shows in the S003.3 attempt view.
- [ ] `docs/hierarchical-policy.md` describes the skip counting fields, their defaults, the configuration checks, and the scoring.

# Notes

Depends on S004.1 for the session shell, server timing, sound sets, resume, and give-up, and on S003.2 for the task picker and give-up rules. The shell's question and answer handling is single-box today, so this story either generalises the shell or builds a sibling page that shares its timing, sound, and resume code.

Unlike arithmetic, this task can fail, but only when `maximum_questions` is set. A required skip counting task without a maximum stays required until he passes it, as a required arithmetic task does.

The 1-second correct feedback, the 10-second correct-answer display, the 3-second wait before Enter can skip it, and the 0.5-second network allowance are constants in the code, not configuration.

Two-question lookbacks for differences and starts are the parent's choice for variety. The rule of at least 3 sequences for each difference guarantees a start is always available after leaving out the last two for that difference.
