Ticket: S029
Title: Date Pickers for Dates
Status: Done
Story Points: 5
Last Updated: 2026-11-10 22:20:00
---

# User Voice

As a parent, I want to pick a task's Available From and Due Date from a calendar, so that I can see which day of the
week a date falls on, and do not have to type it in exactly the form the policy file needs.

# Behaviour

## The date fields

The date fields are Available From and Due Date in S023.2's Dates group, on every task page.

- [ ] Each date field keeps its text box and its `yyyy-mm-dd` placeholder, with a calendar button beside it that has
      the Lucide `calendar` icon and the label and title "Choose Available From" or "Choose Due Date".
- [ ] Typing a date in the box still works, and saving writes it to the policy file as before. A space at either end
      is ignored.
- [ ] A box holding text that is not a real day, such as `2026-11-31`, `10/11/2026`, or `2026-1-5`, shows "Not a
      date. Use yyyy-mm-dd, such as 2026-10-31." under the box and blocks Save as in S025. An empty box is not a
      problem. It leaves the rule off, as in S023.2. *Changed in implementation:* the message wraps within the Dates
      group's width instead of widening the group, and so does every other problem shown under a setting's box.
- [ ] A date set from the calendar is an edit like a typed one. The field is marked as changed, and the Unsaved
      changes marker, Save, Ctrl+S, and the unsaved-changes prompt work as in S023.2. Picking the date that is already
      saved is not a change.

## The calendar

- [ ] The calendar button, or Alt+Down in the box, opens the calendar under the box, over the rest of the page, with
      the shared expand animation. The button again, Escape, or a click outside closes it the same way and leaves the
      field as it was. Escape puts the focus back on the calendar button. Opening one date field's calendar closes the
      other's. *Changed in implementation:* when the content pane has more room above the box than below and too
      little below for the calendar, it opens above the box, unfolding upwards. When it would run past the right edge
      of the content pane, its right edge lines up with the calendar button instead.
- [ ] The calendar shows the month and year, such as November 2026, between previous and next month buttons with the
      Lucide `chevron-left` and `chevron-right` icons. Under them, the days of that month sit in a grid of weeks
      headed Sun to Sat, with weeks starting on Sunday. Days of the months either side are left blank.
- [ ] It opens on the month of the date in the box, with that day selected. When the box is empty or not a date, it
      opens on the month of the household's today, with no day selected.
- [ ] The household's today is marked in the grid. It is the household day in the policy's `timezone`, not the
      browser's date. With `timezone: Pacific/Kiritimati` in the policy file and the browser's computer in Toronto,
      the mark is a day ahead of the computer's calendar from 05:00 Toronto time onwards in winter.
- [ ] Hovering a day shows its full date as its title, such as Tuesday 10 November 2026.
- [ ] Clicking a day puts it in the box as `yyyy-mm-dd`, closes the calendar, and puts the focus in the box.
- [ ] Today, at the foot of the calendar, puts the household's today in the box and closes the calendar. Clear,
      beside it, empties the box and closes the calendar.
- [ ] Opening the calendar focuses the selected day, or the marked day when none is selected. The left and right
      arrows move a day, and the up and down arrows move a week, into the next or previous month when they cross its
      edge. Home and End move to the start and end of the week. Page Up and Page Down move a month, and with Shift
      they move a year, so Page Down from 31 January lands on the last day of February. Enter or Space picks the
      focused day as a click does. Tab and Shift+Tab move among the month buttons, the focused day, Today, and Clear,
      and stay inside the calendar.
- [ ] The calendar's colours, including the selected day, the today mark, hover, and the focus ring, come from the
      theme, and it opens and closes at once when the browser asks for reduced motion, as in `docs/parent-portal.md`.

## Everywhere

- [ ] `docs/parent-portal.md` says under Editing pages that every editable field that holds a date is a `yyyy-mm-dd`
      text box with this calendar, and the Parent Portal section of `AGENTS.md` says so in one line.

# Notes

Depends on S023.2 for the date fields and the save, and on S025 for problems that block Save.

S027's New task page shows the same common fields, disabled until the name and type are locked in, and disables them
during a rename. Whichever of S027 and this story is built second gives those fields the calendar, with the calendar
button disabled whenever its box is.

Design hints:

- One `DateField` component in `policy/portal/src/components/`, opening and closing with `useExpander()` as
  `MultiSelect` does. The calendar can open above the box when there is no room below it in the content pane.
- The task page's data gains the household's today from `HouseholdClock.today()`, so S009's day boundary moves the
  mark and the Today button without a change here.
- The page's date check uses the same rule as `_calendar_day` in `policy/hierarchy.py`: four digits, two, and two,
  making a real day. The service's check on save stays as it is.
- No date-picker package is added. The calendar is small, and a package would bring its own styles and colours.

Out of scope:

- The browser's own `<input type="date">`. Its calendar ignores the theme and the shared animation, and it looks
  different in each browser.
- Showing dates in the browser's locale. Month and day names are in English.
- A check between Available From and Due Date, such as a due date before the task is available.
- Dates on pages that only show them, such as the attempts list.

Sizing: 5 points, with 14 checks. The calendar is one component about the size of `MultiSelect` plus a month grid and
its keys, with its Vitest tests. The rest is one field added to the task page's data and one new problem on the page.

# Implementation

## Files Added

- `policy/portal/src/dates.ts`: reading and writing `yyyy-mm-dd`, the not-a-date problem, the full date title, moving
  by days and months, and a month laid out in weeks from Sunday.
- `policy/portal/src/components/DateField.tsx`: the date box, its calendar button, and the calendar.
- `policy/portal/src/dates.test.ts`: which texts are dates, the month and year moves at month ends and leap days, and
  the month grid.
- `policy/portal/src/dateField.test.tsx`: the date fields on a task page: typing, the problem and Save, opening and
  closing, picking, Today and Clear, the keys, and the Tab trap.

## Files Changed

- `policy/task_admin.py`, `policy/app.py`: `TaskAdmin` takes `today`, the household clock's `today()`, and every
  task page's data carries it as `today`.
- `policy/task_create.py`: the new task page's data carries `today` too.
- `policy/portal/src/pages/Task.tsx`: Available From and Due Date are `DateField`s, and a date problem holds Save with
  "Fix the problems marked on the page first."
- `policy/portal/src/styles/layout.css`: the date field and calendar layout. A setting's problem no longer widens its
  group.
- `policy/portal/src/styles/theme.css`: the `--calendar-selected-bg`, `--calendar-selected-text`, and
  `--calendar-today-mark` roles.
- `policy/portal/src/test/portal.tsx`, `policy/portal/src/newTask.test.tsx`: the fixtures carry `today`, and the new
  task page's calendar button is disabled with its box.
- `tests/test_task_admin.py`: the task pages and the new task page carry the household's today in the policy's
  timezone, either side of midnight in Kiritimati.
- `docs/parent-portal.md`, `AGENTS.md`: date fields under Editing pages.

## Files Removed

None.

## Change Summary

`DateField` renders its label, its box with the calendar button, and its problem as one row of a settings grid, as the
other fields there do. The calendar is a `dialog` holding a `grid` table of day buttons, with a roving tab stop on the
focused day. Opening the calendar sends an event on the document, and any other open calendar closes when it hears
one, so the rule holds however the second calendar is opened. Clicks on the calendar and its button keep it open.
Anything else closes it, including the box itself.

Days are computed in UTC with the full year set, so neither the browser's timezone nor a year below 100 can shift a
day. The household's today comes only from the page's data, so the mark, the first month shown, and Today follow the
policy's `timezone` and a later day boundary.

The page checks a date as `_calendar_day` does, ASCII digits only and a real day from year 1, and the service's check
on save is unchanged. The service trims a date before writing it, so a box with spaces at either end sends them and
the file gets the trimmed date.

The opening day is focused with `preventScroll`. Without it the browser scrolls the clipped calendar to the day while
it unfolds, and it opens bottom first.

## Suggested Acceptance Testing

### Acceptance test cases for S029

1. **Pick and save.** Rebuild the decisions image and restart the stack. Open a task page with an empty Due Date. Check
   the boxes, buttons, and titles, then open the calendar, read the month, the weekday headings, the blanks, today's
   mark, and a day's title. Click a day, check the box, its mark, and Unsaved changes, then save with Ctrl+S and read
   the date in the policy file. Pick the same date again and check nothing is marked. Covers the date fields' first
   and last checks, and the calendar's look, opening day, title, and click checks.
2. **Keys.** Put `2026-01-31` in Due Date, press Alt+Down, and walk the keys: Page Down, Shift+Page Down, the arrows,
   Home, End, Page Up, and Shift+Page Up. Press Enter, then reopen and pick with Space. Open it again and Tab and
   Shift+Tab round the calendar. Covers the keyboard check.
3. **Closing and the other field.** Open each calendar and close it with its button, Escape, and a click on another
   box, checking the box is unchanged and where the focus goes. Open Available From, then click Due Date's button.
   Use Today and Clear. Put a date far from today in the box and check the calendar opens on it, then type
   `nonsense` and check it opens on today's month. Covers the open and close, Today and Clear, and opening day
   checks.
4. **Not a date.** Type `2026-11-31`, `10/11/2026`, and `2026-1-5` in turn, then ` 2026-11-30 ` with spaces. Check the
   message, Save's title, and Ctrl+S's refusal for the first three, and that the last one saves. Empty the box and
   save, and check the rule is gone from the file. Covers the typing and problem checks.
5. **Household today.** Set `timezone: Pacific/Kiritimati` in the policy and `make reload`. With the computer in
   Toronto, open a task page's calendar before and after 05:00 local time, and check today's mark and Today move a
   day ahead of the computer's calendar at 05:00. Covers the household today check.
6. **Room and theme.** Make the browser window short, so the Dates group sits near the bottom of the content pane,
   and check the calendar opens above the box. Narrow the window, and check the calendar stays inside the pane on
   the right. Turn on reduced motion in the operating system, and check the calendar opens and closes at once. Look
   at the selected day, today's mark, hover, and the focus ring. Covers the theme and motion check, and the
   *Changed in implementation* note on opening.
7. **New task page and docs.** On Create New Task, check both date boxes and their calendar buttons are disabled
   until the name and type are locked in, and again during a rename of a saved task. Read Editing pages in
   `docs/parent-portal.md` and the Parent Portal section of `AGENTS.md`. Covers Everywhere and the S027 note.
