Ticket: S026
Title: Arithmetic administration, subtraction, multiplication, and division
Status: Draft
Story Points: 8
Last Updated: 2026-11-10 00:40:00
---

# User Voice

As a parent, I want to choose an arithmetic task's operation from a list and set its timer and numbers on its task
page, so that moving him from addition to the seven times table is a few changes and a save.

As a child, I want to practise subtraction, multiplication, and division with the signs I see on paper, so that the
questions look like the ones at school.

# Behaviour

## The page

- [ ] For an `arithmetic` task, `/parent/tasks/<name>` shows below the divider, in place of the "not built yet"
      message, the task's settings, then the First (`first`) and Operands (`operands`) tables side by side.
- [ ] The settings are Operation (`operation`), a pull-down of Addition, Subtraction, Multiplication, and Division,
      then Max Timeout (`max_timeout`), Min Timeout (`min_timeout`), and Correct Answers Required
      (`correct_answers_required`). Each label's title is its field name, as in S023.2.
- [ ] The timeouts and Correct Answers Required are required. An empty one is a problem shown under it, and problems
      block Save as in S025.
- [ ] A line under the tables says how the chosen operation uses them, and follows the pull-down: "first + operand",
      "(first + operand) − first, and the answer is the operand", "first × operand", or "(first × operand) ÷ first,
      and the answer is the operand".
- [ ] The status bar shows how many problems there are, as in S025.
- [ ] Save, Ctrl+S, the unsaved-changes prompt, the refusal after a hand edit of the policy file, and the config
      history commit work as in S023.2.

## The number tables

- [ ] Both tables are S025's weighted number table with the From, To, and Weight columns only. Its rows, keyboard,
      problems, saving, and marks work as in S025, except that a negative number is a problem and 0 is accepted.
- [ ] Operands with no rows is a problem, "Add a number." First with no rows is not: a note under it says both numbers
      are then drawn from Operands, and saving leaves `first` out of the file, removing it when it was there.
- [ ] With Division chosen, a 0 in the list the first number is drawn from, which is First, or Operands when First is
      empty, marks its row "Division cannot divide by 0." The mark follows the pull-down and the First table.

## The operations

Every operation uses the session shell from S004.1 unchanged: the draws, timer, sounds, resume, give-up, and pass.
`m` is the first number drawn and `n` the second, as S004.1 defines them.

- [ ] `operation: multiplication` asks `m × n =`, with the multiplication sign `×` (U+00D7), not `x` or `*`. A draw of
      6 and 7 asks `6 × 7 =` and accepts only 42.
- [ ] `operation: subtraction` asks `(m + n) − m =`, with the minus sign `−` (U+2212), and expects `n`. A draw of 6 and
      7 asks `13 − 6 =` and accepts only 7. With First set to 7 alone, every question takes 7 away, such as
      `16 − 7 =`.
- [ ] `operation: division` asks `(m × n) ÷ m =`, with the division sign `÷` (U+00F7), not `/`, and expects `n`. A draw
      of 6 and 7 asks `42 ÷ 6 =` and accepts only 7. With First set to 7 alone, every question divides by 7. A 0 in
      Operands, with First free of 0, asks `0 ÷ 7 =` and accepts 0.
- [ ] A division task with a 0 in the list `m` is drawn from, as a `value` or inside a range, fails `dw check` and the
      load, naming the task and the field, and the previous policy stays in force.
- [ ] The start screen names each operation: Subtraction, Multiplication, or Division.
- [ ] A finished task of each operation is a pass and increments today's revision count, and its questions show in
      the attempt review as asked, such as `13 − 6 =`.
- [ ] `docs/hierarchical-policy.md` lists the four operations, where `m` and `n` appear in each, and the division
      rule.

# Notes

Depends on S025 for the weighted number table, and on S023.2 for the task page and saving.

This story replaces the drafts S004.3 to S004.5, which are removed. Each operation is one more entry in the operation
table in `policy/arithmetic.py`, as S004.1's implementation planned. Subtraction and division only change the question
text and the expected answer, so the draw, the weights, and the recent-question check still work on `m` and `n`. The
weights apply to `m` and `n`, never to the displayed sum or product. The divide-by-zero check goes in
`parse_settings`, and the page's mark is S025's table rule for a check of its own.

The weight of each operand is unchanged by the operation, so a task's lists stay valid when its operation changes,
except for a 0 that division refuses.

S004.6, the formatted arithmetic attempt review, is not part of this story.

Sizing: the page reuses S025's table and save path, so it is like the parts of speech settings in S007.3, about 3
points. The three operations were drafted at 2 points each. Built together on the existing operation table, with the
divide-by-zero check and the docs, they are about 5, which makes 8. It has 18 checks.
