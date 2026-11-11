Ticket: S024
Title: Extra practice on the task selector, practice colours, and the favicon on task pages
Status: Done
Story Points: 13
Last Updated: 2026-11-09 19:20:00
---

# User Voice

As a child, when I've finished my tasks for today, or I want another go at one I've already done, I want to find it in
the task list myself instead of needing a bookmark. I also want to see at a glance which tasks count toward my
internet time and which ones don't.

As a parent, I want him to be able to practise any of his tasks whenever he likes, without that practice being
mistaken for, or counted as, the revision that earns his internet time.

As a parent, I want the task pages to show the Daywarden owl in the browser tab, as the parent pages do, so they are
easy to find among his tabs.

# Use Cases

## UC1 - Practice after everything is done

- He has passed every available task today. The last quiz's end screen says "All done for now" and shows an
  "Extra Practice" link.
- The link opens the selector. It says "There is nothing to revise right now.", and the Extra Practice section beneath
  is already open. It shows its note and a purple button for each of his tasks, including the ones he passed today.
- He opens spelling. The quiz has a light purple tint and purple buttons, and near the top it says "Practice: this
  won't count toward internet time today."
- He passes, and sees "Well done" as usual. Nothing is added to today's score, as in S018.

## UC2 - A required task is outstanding

- Parts of speech and sums are due today, so they are required. Spelling is optional and open today. Skip counting
  was passed yesterday and is in its pass cooldown.
- He confirms "Try a different task" on parts of speech, and the selector opens. It lists parts of speech and sums as
  blue buttons.
- Below them is a collapsed "After These" heading. Clicking it opens the section. It shows the note "These count once
  the tasks above are done." and a teal spelling button.
- Below that is a collapsed "Extra Practice" heading. Clicking it shows the practice note and a purple skip counting
  button.
- He opens spelling from After These. The quiz is in the purple palette and says "This counts once your other tasks
  are done." He passes. As in S018, the pass waits and scores once parts of speech and sums are no longer required.

## UC3 - One task left

- Only sums is available. He passed spelling and skip counting earlier today.
- He opens the selector. Instead of jumping straight into sums, it shows sums as a blue button, with Extra Practice
  collapsed beneath it.
- On another day, when there are no After These or Extra Practice tasks, the selector jumps straight to the one
  available task, as it does today.

## UC4 - A bookmarked practice task

- He opens a bookmark to spelling after already passing it today.
- The quiz is in the purple palette and shows the practice line, exactly as if he had opened it from Extra Practice.

## UC5 - The favicon

- Every task page shows the Daywarden owl in its browser tab, as the parent pages do.
- When a site is blocked, the proxy's "Not allowed" page shows the owl too.

# Acceptance Criteria

## The selector's sections

The selector at `/tasks/choose` has up to three sections, worked out for his client group on the household day, using
the task sets from S018:

- **The main list** is the available tasks, as it is today.
- **After These** is the potential tasks while any task is required. When no task is required, the potential tasks
  are the available tasks and are in the main list, so After These is empty.
- **Extra Practice** is every configured task that is neither required nor potential, other than a task whose
  `available_from` date has not arrived. In practice that is each task passed today, in a pass or failure cooldown,
  or at `max_passes`.

- [ ] The main list is unchanged: the available tasks in the order the picker would try them, as blue buttons, under
  "Choose a task".
- [ ] While any task is required and any potential task exists, an "After These" heading sits below the main list.
  Expanded, it shows the note "These count once the tasks above are done." above a teal button for each potential
  task, in the picker's order.
- [ ] When any task belongs in Extra Practice, an "Extra Practice" heading sits below the main list and After These.
  Expanded, it shows the note "Practice is just for fun. It doesn't count toward your internet time today." above a
  purple button for each of those tasks, in alphabetical order by task name.
- [ ] A section with no tasks in it is not shown, heading included.
- [ ] Each configured task whose `available_from` has arrived, or that has none, appears in exactly one section. A
  task passed today, a task in its pass cooldown, a task in its failure cooldown, and a task at `max_passes` each
  appear under Extra Practice.
- [ ] A task whose `available_from` is in the future is in no section. Its URL still opens it as practice, as in S018.
- [ ] A `parent_check` task, and a task not assigned to his client group, are in no section.
- [ ] White text on the teal and purple buttons meets WCAG AA contrast (4.5:1), as the blue buttons do.

## Expanding and collapsing

- [ ] Clicking the After These or Extra Practice heading expands the section, and clicking it again collapses it.
  Each heading shows whether it is open, for example with a chevron that turns.
- [ ] Each heading can be reached with Tab and toggled with Enter or Space. Screen readers hear whether it is expanded.
  The buttons in a collapsed section cannot be reached with Tab.
- [ ] Expanding and collapsing animate over 500ms with swing easing, the same timing and curve as the parent portal.
  When the browser asks for reduced motion, the change is instant.
- [ ] Both sections start collapsed each time the page opens. The exception is Extra Practice, which starts expanded
  when the main list and After These are both empty. Whether a section was open is not remembered across page loads.

## When the selector jumps, and the nothing-to-revise page

- [ ] When exactly one task is available and After These and Extra Practice are both empty, the selector jumps
  straight to that task, as it does today. When either section has a task, the selector shows the page instead.
- [ ] After "Try a different task" on the only available task, the selector shows the page with that task and the
  other sections when they have tasks, and otherwise jumps straight back to it, as it does today.
- [ ] When nothing is available and Extra Practice is empty, the selector and the picker at `/tasks/next` both show
  only "There is nothing to revise right now.", as they do today.
- [ ] When nothing is available and Extra Practice has tasks, the selector and the picker both show "There is nothing
  to revise right now." with the Extra Practice section expanded beneath it.
- [ ] When any task is available, the picker still sends him straight to a task, chosen as it is today. The new
  sections change neither the picker's choice nor its turn order, and they do not change where a redirect to
  `revision_task` lands.

## Opening a task from a section

- [ ] Opening a task from any section is the same as opening its URL. Its attempt is Required, Potential, or Practice
  according to the S018 rules, and is shown that way in the parent portal's attempts. A task opened from After These
  is Potential, and a task opened from Extra Practice is Practice.

## The "All done for now" end screen

- [ ] When a quiz end screen shows "All done for now" and Extra Practice has tasks, it also shows an "Extra Practice"
  link that opens the selector, with Extra Practice expanded. This applies to "Well done" and to every other end
  screen that shows "All done for now".
- [ ] When Extra Practice is empty, the link is not shown.
- [ ] After a pass that is counting down to go back to the page he was sent away from, pressing the Extra Practice
  link opens the selector instead, as pressing "Next task" stays on the task site today.

## Quiz pages that don't count right now

An attempt **counts right now** when it is Required, or when it is Potential and no task is required. It **doesn't
count right now** when it is Practice, or when it is Potential while a task is required. This is decided when the
quiz page loads.

- [ ] A quiz whose attempt doesn't count right now uses the practice palette. The accent colours are purple, including
  the Start, Next Question, Next task, and Go now buttons, the Extra Practice link, the timer bar, and each quiz's
  highlights, selections, and drag tiles. The page background has a light purple tint. The green and red that mark
  right and wrong answers do not change. Text meets WCAG AA contrast on the tinted background.
- [ ] A Practice attempt's quiz shows "Practice: this won't count toward internet time today." near the top of every
  screen: the start screen, each question, the end screens, and any give-up review.
- [ ] A Potential attempt's quiz, opened while a task is required, shows "This counts once your other tasks are done."
  in the same place.
- [ ] A quiz whose attempt counts right now looks exactly as it does today, with the standard palette and no line.
- [ ] The palette and line follow the attempt, not how he reached it. A bookmark to a task passed today, a link under
  Extra Practice, and typing the task's URL all give the practice palette and line. A bookmark to an optional task
  while a task is required gives the purple palette and the "counts once" line, the same as After These.
- [ ] A Potential attempt opened while a task was required, given up, and carried on within the hour after the
  required tasks are cleared shows the standard palette and no line, because it now counts.
- [ ] This applies to every quiz type: arithmetic, parts of speech, skip counting, and spelling. It includes the
  spelling missed-words screen after a give-up.
- [ ] The selector, the picker's pages, and the plain revision task page use the standard palette.

## The favicon

- [ ] Every page the task site serves to the child shows the Daywarden owl as its tab icon, the same icon the parent
  portal uses. That includes the selector, the picker's "There is nothing to revise right now." page, each quiz type
  in both palettes, the spelling missed-words screen, the plain revision task page, and `/quiz`.
- [ ] The icon is served by the policy server without a parent session. Through the proxy, it loads at any time,
  including during school hours and at bedtime in the sample policy, because the policy server's names are forwarded
  without a decision (S018). Fetching it records nothing and changes no attempt.
- [ ] The proxy's "Not allowed" page shows the owl. The icon is embedded in the page, so showing it makes no request to
  the blocked site or to the policy server.
- [ ] The parent portal's favicon and touch icon are unchanged.

## Documentation

- [ ] `docs/hierarchical-policy.md` describes the selector's three sections and which tasks go in each, when the
  selector jumps straight to a task, the Extra Practice link on the "All done for now" screen, and the practice
  palette and lines on quiz pages that don't count right now.

# Notes

## Decisions made while refining

- Extra Practice lists only tasks that really would be practice, so its note is always true. Optional tasks waiting on
  required tasks would count later, so they get their own section, After These, between the main list and Extra
  Practice. "After These" was chosen over the policy term "Potentials" because the child reads it.
- Extra Practice can be reached from the selector, from the "nothing to revise" page that the picker and the selector
  both show, and from the "All done for now" end screen. It is not linked from end screens that offer "Next task".
- The selector no longer jumps straight to the only available task when it has other sections to show.
- The selector's buttons have three colours: blue for the main list, teal for After These, and purple for Extra
  Practice.
- The quiz pages have two palettes: the standard one for attempts that count right now, and one shared purple palette
  for attempts that don't, both Practice and waiting Potential. So a teal After These button opens a purple quiz. This
  is accepted to keep the three sections distinct on the selector.
- The practice palette changes the accent colours and tints the page background. Right and wrong stay green and red.
- Sections start collapsed, except that Extra Practice opens by itself when nothing is listed above it. Their state is
  not remembered.
- Expanding and collapsing borrow the portal's 500ms swing timing. The child pages are still not part of the portal,
  and nothing else from the portal's design applies to them.
- Tasks whose `available_from` has not arrived are left out of Extra Practice, so nothing shows before the parent
  means it to.
- After These is in the picker's order, as the main list is. Extra Practice is alphabetical.
- The favicon goes on every task page and on the proxy's "Not allowed" page.

## Approach

- The child pages' colours are written out in each page module today: `task_page.py`, `quiz_page.py`,
  `arithmetic_page.py`, `parts_of_speech_page.py`, `skip_counting_page.py`, and `spelling_page.py`, about 47 values
  in all. This story moves them into one shared set of CSS custom properties for the child pages. The standard
  palette and the practice palette are two sets of values for those properties, and one attribute on the page picks
  between them, for example `data-palette="practice"` on `<html>`. A later quiz type gets both palettes by using the
  properties. This is the "different stylesheet swapped in for a non-counting task" the parent asked for. These
  properties belong to the child pages only and are separate from the portal's theme.
- The task pages set an empty icon (`<link rel="icon" href="data:,">`) on purpose. That dates from S004.1, when the
  household rules redirected the browser's own favicon request to the task page. Since S018 the policy server's names
  are forwarded without a decision, so a real icon is safe. The task pages can link to the portal's
  `/parent/favicon.png`, which is served without a session, or to a copy at the task site's root. The proxy runs in its
  own image, so its "Not allowed" page needs its own copy, embedded as a `data:` URI. A smaller cut of the 64×64 owl
  keeps that page light.
- `TaskSets` already holds the configured, required, and potential tasks, so the sections need no new rules about
  which task is which. Only the future `available_from` exclusion is new.
- The automated tests cover which tasks are in each section and in what order, when the selector jumps, the
  nothing-to-revise page with and without practice tasks, the end-screen link, which palette and line each kind of
  attempt gets, and the icon being served without a session. The animation, the colours, the contrast, and keyboard
  use are checked in a browser.

## Edge cases worth knowing

- Passing the last available task puts that task into Extra Practice, because it was passed today. So the "All done
  for now" screen after a pass nearly always shows the Extra Practice link.
- A quiz already on the screen keeps the palette it loaded with. If the required tasks are cleared while a waiting
  Potential quiz is open, for example by a `dw reload`, the page stays purple until it is loaded again. The pass still
  scores correctly, as in S018.
- An optional task passed from After These waits for its point, exactly as in S018. The selector changes no scoring.
- The only required task still cannot be given up, and its quiz has no route to the selector. That is unchanged.
- A name for the policy server that is in neither `PARENT_NAMES` nor `config/bypass.txt` is judged by the household
  rules (the S018 edge case). The icon request may then be redirected, and the owl does not show. Nothing is recorded,
  because a plain GET of a task page changes nothing.

## Out of scope

- Any change to which attempts score, or to the task sets from S018.
- Remembering whether a section was expanded.
- Any change to the parent portal, other than nothing breaking.
- Linking the selector from end screens that show "Next task".

## Size

13 points. The sections are a contained change to the selector and the picker's nothing-to-revise page, built on the
task sets S018 already computes, plus a small collapsible widget with the portal's motion. The largest part is the
palette. It means pulling about 47 colours across six page modules into shared properties, adding the practice line
to every quiz, and checking all four quiz types in both palettes in a browser. The favicon is small. Overall this is
close to the 14-point reference work of S006.1 to S006.3, and well inside one session, so it stays one story.

# Implementation

## Files Added/Changed/Removed

Added:

- `policy/child_page.py`: the child pages' palette (standard and practice custom properties, and the 500ms swing
  motion), the shared `<head>` with the owl icon, the counting lines, and which attempts don't count right now.
- `policy/static/favicon.png`: a copy of the portal's 64×64 owl, served at `/favicon.png`.
- `proxy/deny_page.py`: the "Not allowed" page, now with the owl embedded as a `data:` URI.
- `proxy/favicon.png`: a 32×32 cut of the owl for that page.
- `tests/test_extra_practice.py`: the sections, the jumps, the nothing-to-revise page, the palette and line on every
  quiz type, the end-screen link, and the icons.

Changed:

- `policy/selection.py`: `Sections`, `sections()`, and `extra_practice()`. After These uses the picker's ordering.
- `policy/task_page.py`: the selector's three sections with collapsible headings, the picker's and selector's
  nothing-to-revise page with Extra Practice open, the new jump rule, and the counting line passed to each quiz and
  to the spelling give-up review.
- `policy/quiz_page.py`: the shell uses the palette properties, takes the counting line, shows the "Extra Practice"
  end-screen link, and `ending()` returns `practice`.
- `policy/arithmetic_page.py`, `policy/parts_of_speech_page.py`, `policy/skip_counting_page.py`,
  `policy/spelling_page.py`: colours moved to the palette properties, and each page takes the counting line. The
  spelling missed-words page after a give-up uses the shared head and line.
- `policy/app.py`: `GET /favicon.png`, without a session, on both listeners.
- `policy/review.py`: `/quiz` links the owl.
- `proxy/addon.py`: uses `deny_page.deny_body`.
- `tests/page_harness.js`: a screen's `querySelector` finds the element by class in the page source, and a snap
  records `href`.
- `tests/test_task_selection.py`: three tests updated for the selector no longer jumping when After These or Extra
  Practice has a task.
- `tests/test_spelling.py`: the missed-words page keeps the practice palette and line.
- `docs/hierarchical-policy.md`, `README.md`: the selector's sections, the jump rule, the end-screen link, the practice
  palette and lines, and the icons.

Removed: none.

## Change Summary

The selector at `/tasks/choose` now lists the available tasks as blue buttons under "Choose a task", then a collapsed
"After These" section of teal buttons for potential tasks while any task is required, then a collapsed "Extra
Practice" section of purple buttons, in name order, for every other task of his whose `available_from` has arrived.
Headings are buttons with `aria-expanded` and a turning chevron. A collapsed section is `inert`, so Tab skips its
buttons. The open and close animate `grid-template-rows` over 500ms with swing easing, and are instant with reduced
motion. A page brought back from the browser's history goes back to how the server sent it. The selector jumps
straight to a task only when it is the only one and both other sections are empty. When nothing is available, the
picker and the selector show "There is nothing to revise right now." with Extra Practice open beneath, when it has a
task. The picker's choice and rotation are unchanged.

Quiz end screens with no next task show an "Extra Practice" link to the selector when Extra Practice has a task. It
stops the countdown back to the page he was sent from, as "Next task" does.

About 47 colours across the six child page modules are now custom properties in `policy/child_page.py`. A practice
attempt, or a potential attempt while a task is required, gets `data-palette="practice"` on `<html>`: purple accents,
a `#f7f3fd` page tint, and right and wrong unchanged. It also gets a line at the top of every screen: "Practice: this
won't count toward internet time today." or "This counts once your other tasks are done." Contrast was checked: white
on blue 4.8:1, on teal 5.5:1, on purple 7.1:1, and the green, red, and muted text on the tint 4.6:1 or more.

Every task page and `/quiz` links `/favicon.png`, which the policy server serves without a session. The proxy's "Not
allowed" page embeds a 32×32 owl, about 5 KB, so it requests nothing.

## Suggested Acceptance Testing

### Acceptance test cases for S024

1. With two tasks due today, one optional task, and one task passed yesterday with `pass_cooldown: 2`, give up one of
   the due tasks. The selector lists the two due tasks as blue buttons, then collapsed "After These" and "Extra
   Practice" headings. Expand each one. After These shows "These count once the tasks above are done." and a teal
   button for the optional task. Extra Practice shows the practice note and a purple button for the cooling-down task.
2. Open the optional task from After These. The quiz is purple on a light purple page, and says "This counts once your
   other tasks are done." at the top. Pass it. The parent portal's attempts show it as Potential, and today's score
   does not rise until the due tasks are passed.
3. Open the cooling-down task from Extra Practice. The quiz is purple and says "Practice: this won't count toward
   internet time today." on the start screen, each question, and the end screen. Pass it. The parent portal shows a
   Practice attempt and the score does not change.
4. Pass every available task today. The last "Well done" says "All done for now" with a purple "Extra Practice"
   button. Press it. The selector says "There is nothing to revise right now." with Extra Practice already open and a
   button for every task, including the ones passed today, in alphabetical order.
5. Open `/tasks/next` directly in the same state. It shows the same nothing-to-revise page with Extra Practice open.
6. Open a bookmark to a task passed today. It is purple with the practice line, exactly as from Extra Practice.
7. Open a required task. It looks as it did before this story: blue, no tint, no line.
8. Check each quiz type in the purple palette: arithmetic, parts of speech (drag a word and watch the highlight and
   the drop row turn purple, while red marks after a second wrong try stay red), skip counting (typed numbers are
   purple, and right and wrong answers are still green and red), and spelling (the Repeat word button and timer bar
   are purple).
9. In a practice spelling quiz, miss a word, then give up. The "Words to practise" screen is purple with the practice
   line at the top.
10. With only one task available and one passed earlier today, open `/tasks/choose`. It shows that task as a blue
    button with Extra Practice collapsed beneath, instead of jumping to it. With no task passed or cooling down, it
    jumps straight to the task as before.
11. On the selector, Tab to each heading and press Enter, then Space. Each toggles and its chevron turns. While a
    section is collapsed, Tab skips its buttons. A screen reader announces each heading as expanded or collapsed.
12. Watch a section open and close: it slides over half a second. Turn on reduced motion in the system or browser,
    and it changes at once.
13. Open a section, follow one of its buttons, then press Back. The selector shows its sections collapsed again.
14. Give up a task opened from After These, pass the remaining due tasks, and reopen the given-up task within the
    hour. It carries on with the standard palette and no line.
15. Add a task with `available_from` in the future. It is in no section. Its URL still opens it, as practice.
16. Add a `parent_check` task and a task for another client group. Neither appears in any section.
17. Check the browser tab icon: the owl shows on the selector, the nothing-to-revise page, every quiz in both palettes,
    the spelling missed-words screen, a plain worksheet task page, and `/quiz`, during school hours and at bedtime.
18. Visit a blocked site. The "Not allowed" page shows the owl in its tab.
19. Open the parent portal. Its favicon and touch icon are unchanged.
20. After a pass that counts down to go back to a blocked page, with no next task, press "Extra Practice" before the
    countdown ends. The selector opens and the browser does not go back.
