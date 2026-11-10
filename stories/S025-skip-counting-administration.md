Ticket: S025
Title: Skip counting administration and the weighted number table
Status: Draft
Story Points: 13
Last Updated: 2026-11-10 00:40:00
---

# User Voice

As a parent, I want to set up a skip counting task on its task page, with its settings in boxes and its differences
in a table I can fill in from the keyboard, so that changing what he counts by, or how far, does not mean hand-writing
YAML lists of `{ value: 5, weight: 2, maximum_value: 199 }`.

# Scenarios

## Counting by 2s and 5s

The task uses the default list. The parent removes every row except 2 and 5, so the note about the default list goes.
He clicks in the 5 row's Weight box, types `2`, and presses Enter. That was the last row, so Enter adds an empty one
with the focus in From. He types `-2`, Enter, `-5`, Tab, Tab, `2`, Enter, and Enter again in the new empty row, which
removes it and puts the focus on Add row. Ctrl+S saves the four differences, and the child's next run counts only by
2s and 5s.

# Behaviour

## The page

- [ ] For a `skip_counting` task, `/parent/tasks/<name>` shows below the divider, in place of the "not built yet"
      message, the task's settings, then the Differences table (`difference`).
- [ ] The settings are in two groups, each label's title being its field name, as in S023.2:
      - **Questions:** Sequence Length (`sequence_length`), Completed (`completed`), Minimum Value (`minimum_value`),
        Maximum Value (`maximum_value`), Consecutive (`consecutive`), and Multiples Only (`multiples_only`).
      - **Session:** Timeout (`timeout`), Correct Answers Required (`correct_answers_required`), Minimum Questions
        (`minimum_questions`), and Maximum Questions (`maximum_questions`).
- [ ] An empty box shows its default from S011 as its placeholder: `8`, `3`, `1`, `999`, `3m`, and `None` for Maximum
      Questions.
- [ ] Empty Correct Answers Required shows the default S011 works out from the minimum and maximum questions now on
      the page, and follows them as they change. Maximum Questions `5` shows `5`. Minimum Questions `12` shows `10`.
      Empty Minimum Questions shows the Correct Answers Required in force, typed or shown as the placeholder.
- [ ] Consecutive and Multiples Only are checkboxes showing the value in force, so Consecutive is ticked when the file
      leaves it out. Changing one writes it. Changing it back is no change, and the field is written as it was, or
      left out.
- [ ] The status bar shows how many differences there are, such as "6 differences.", or "Default list of 10
      differences.", and how many have problems.
- [ ] Save, Ctrl+S, the unsaved-changes prompt, the refusal after a hand edit of the policy file, and the config
      history commit work as in S023.2.

## The weighted number table

This is one table component. S026 uses it for the arithmetic number lists with the first three columns only.

- [ ] Each entry in the list is a row, in the policy file's order. The columns are From, To, and Weight, then Min,
      Max, and Multiples Only, then the row's remove button. A `value` entry shows its number in From with To empty. A
      `from`/`to` range shows both. Each column header's title is the field it writes, such as `from` or
      `minimum_value`.
- [ ] Empty Weight shows `1` as its placeholder and is written as `weight: 1`.
- [ ] Empty Min and Max show the task's Minimum Value and Maximum Value as now on the page as their placeholders, and
      follow them. Multiples Only is a pull-down of "Task's (No)", Yes, and No, where the first names the task's
      setting as now on the page. Empty Min and Max, and the task's setting, are not written on the row.
- [ ] Add row, under the table, adds an empty row at the bottom and focuses its From box.
- [ ] The remove button removes its row at once, without asking.
- Lucide icons: `square-plus` for Add row and `square-minus` for Remove row. The remove button's label and title are
  "Remove row".
- Rows cannot be reordered.

## The keyboard in the table

A row is empty when every box in it is empty and Multiples Only is on the task's setting.

- [ ] Tab and Shift+Tab move through a row's boxes, its pull-down, and its remove button as usual. Tab past the end of
      the last row, when it is not empty, adds an empty row and focuses its From box.
- [ ] Enter in any box of a row moves the focus to the next row's From box with its contents selected, so typing
      replaces them. In the last row, when it is not empty, Enter adds an empty row and focuses its From box.
- [ ] When the focus leaves an empty row, by Tab, Shift+Tab, Enter, or a click elsewhere, the row is removed. Enter in
      an empty last row puts the focus on Add row. Tab and Shift+Tab go on to the control they were moving to, so
      Tab out of an empty last row reaches the control after the table.
- [ ] A row that becomes empty in the middle of the table, by clearing its boxes, is removed the same way when the
      focus leaves it.

## Problems

A row's problems show under it. A problem anywhere on the page blocks Save as in S007.3: Save is disabled, its title
says to fix the problems marked on the page first, and Ctrl+S says the same in the status bar.

- [ ] A row is marked with each of these that applies: From is empty while something else in the row is not, such as
      "From is needed."; a box that is not a whole number; To below From; a Weight below 1; Max not above Min,
      where an empty Min or Max stands for the task's Minimum Value or Maximum Value, so with the task's 1 to 999 a
      Max of `0`, or a Min of `1000`, is marked; and a number already in another row of the same table, such
      as "5 is also in row 2." A range counts every number in it, so 3 to 9 and 7 to 12 clash on 7.
- [ ] A difference of 0, or a range that includes 0, is marked "0 is not a difference. Write one range below zero and
      another above it." Negative differences, Min, and Max are accepted.
- [ ] A table with no rows is a problem shown under it, "Add a difference, or use the default list."
- [ ] The checks that need the whole task, such as "counting by 100 allows only 2 sequences of 8 numbers", and a
      setting outside its range, such as Sequence Length `13`, come from the policy check when Save is pressed. The
      save is refused and the status bar lists each error, as in S023.2. The errors name the entry by its number in
      the table, as `difference entry 5`.

## The default list

- [ ] A task with no `difference` field shows the default list from S011 as rows: ±2, ±5, ±10, ±25, and ±100, each of
      weight 1, with Max showing each cap, such as `99` for 2, and Yes for Multiples Only on 25 and -25. A note above
      the table says the task uses the default list. A cap follows Maximum Value as changed on the page, as S011's
      defaults do, so Maximum Value `150` shows Max `150` for 5 and 10.
- [ ] While the default rows are unchanged, saving writes no `difference` field. Changing, adding, or removing any row
      takes the note away, and saving then writes the whole list as shown.
- [ ] A task with its own list has "Use the default list" beside Add row. It puts the default rows back, with the
      note, and saving then removes the `difference` field. With the default rows already shown, the button is not
      shown.

## Saving

- [ ] The settings are written in the task's `body`. Clearing one removes its line, so the S011 default applies.
- [ ] A changed list is written whole, as a block list with one flow mapping per row, in table order, such as
      `- { from: 3, to: 9, weight: 10, maximum_value: 99 }`. Keys come in the order `value` or `from` and `to`, then
      `weight`, `minimum_value`, `maximum_value`, and `multiples_only`. A row whose To is empty or equal to From is
      written with `value`. An unchanged list keeps its text exactly. Comments inside a changed list are lost. `dw
      check` passes on the result.
- [ ] Until saved, a changed setting or box is marked, and a new row is marked as a whole. After a save no marks
      remain, and the page shows the file as written, so a To equal to From is shown empty.
- [ ] The child's next run uses the saved settings. A run in progress keeps the settings it started with, as in S011.

# Notes

Depends on S023.2 for the task page, saving, the policy check, and the config history, and on S007.3 for the changes
to `policy/task_edit.py` that replace a list in a task's body.

The table is a portal component, such as `policy/portal/src/components/WeightedTable.tsx`. The page passes it the
columns to show and the rules for its numbers: whether negatives are allowed, whether 0 is a problem, and any check
of its own, such as S026's divide-by-zero. The keyboard rules, the row checks, the clash check over ranges, and the
default Correct Answers Required have Vitest tests. The whole-list write and the default list are tested in Python.

The service sends the default list with the page, worked out by the same code in `policy/skip_counting.py` that the
loader uses, so the page and the loader cannot disagree. The page applies the caps to Maximum Value itself as it
changes.

The policy check stays the one judge of a save. The page's checks only catch, on the row where they happen, the
mistakes a parent is most likely to make while typing.

Out of scope: creating and deleting tasks, reordering rows, showing each row's share of the draws, and a preview of a
question.

Sizing: the settings and saving are like the parts of speech settings in S007.3, about 3 points, because S023.2 and
S007.3 built the save path and the list rewrite. The table, with its keyboard rules, its row checks, and its tests, is
about 5. The default list, the per-row Min, Max, and Multiples Only, and the placeholders that follow the page add
about 5, which makes 13. It has 31 checks.
