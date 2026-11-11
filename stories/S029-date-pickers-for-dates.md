Ticket: S029
Title: Date Pickers for Dates
Status: Refined
Story Points: 5
Last Updated: 2026-11-10 18:20:00
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
      problem. It leaves the rule off, as in S023.2.
- [ ] A date set from the calendar is an edit like a typed one. The field is marked as changed, and the Unsaved
      changes marker, Save, Ctrl+S, and the unsaved-changes prompt work as in S023.2. Picking the date that is already
      saved is not a change.

## The calendar

- [ ] The calendar button, or Alt+Down in the box, opens the calendar under the box, over the rest of the page, with
      the shared expand animation. The button again, Escape, or a click outside closes it the same way and leaves the
      field as it was. Escape puts the focus back on the calendar button. Opening one date field's calendar closes the
      other's.
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
