Ticket: S045
Title: Capitalisation help
Status: Refined
Story Points: 5
Last Updated: 2026-11-20 18:20:00
---

# User Voice

As a child, I want to open a page that tells me where capital letters go, with an example of each, and then go back to
the sentence I was answering, so that I can check a rule when I am not sure and still finish the sentence.

# Behaviour

## The Help button

- [ ] The capitalisation start screen and question screen show a smaller "Help" button at the bottom right, in the
      place and style of the Practice button on spelling and arithmetic tasks (S005.2). It is not shown on the answer
      screen after a sentence ends, or on the end screen.
- [ ] Help works for every `capitalisation` task. A task's body may have `help_points`, a list of one or more of
      `first_word`, `i`, `people`, `pets`, `places`, `days`, `months`, `holidays`, `titles`, `capitals`, and
      `many_rules`, to show only those points. The page shows them in the fixed order below whatever order the list
      has, and with no `help_points` it shows every point. An empty list, a point not named here, or a point listed
      twice stops the policy loading, with a message naming `help_points`. *Added in implementation:* it is set on the parent portal's capitalisation task page, which has a check box for each point under "Help points", with Save held until at least one is chosen. Choosing every point removes the field. The MCP `create_task` and `update_task` tools take `help_points` too.

## The help page

- [ ] Clicking "Help" covers the sentence, his clicked words, and Submit with the help page. Nothing of the sentence
      can be seen or clicked while the help page is open, and Submit and Enter do not submit a try.
- [ ] The help page is in moderately large text, larger than the page's small print and smaller than the sentence, with a
      heading such as "Where do capital letters go?" and one point for each of these places the task shows, in this order:
      the first word of a sentence, the word "I", names of people, names of pets, names of places (towns, countries,
      streets), days of the week, months of the year, holidays, titles used with a name (such as Dr or Mr), and
      short names made of capitals (such as NASA). Each point is a short sentence a grade 3 reader can follow.
- [ ] Each point comes with an example sentence spelled correctly, with its capitals. The capitalised word that shows
      that point is in blue, in the blue of a clicked word, and every other word in the example is black. An example
      has no capital other than the one it shows, except the first word of the sentence, which is black unless the
      point is the first word, and a name that has to follow a title. The example for a point is never built on its
      first word, except the first-word point. For days of the week, "We are going to the zoo on Tuesday." shows
      `Tuesday` in blue and `We` in black.
- The examples are fixed in the page:
  - first word: "The dog ran home." (`The` blue)
  - "I": "Can I have a snack?" (`I` blue, `Can` black)
  - people: "We saw Mia at the park." (`Mia` blue)
  - pets: "Our dog is called Rex." (`Rex` blue)
  - places: "We drove to Sydney today." (`Sydney` blue)
  - days: "We are going to the zoo on Tuesday." (`Tuesday` blue)
  - months: "My birthday is in May." (`May` blue)
  - holidays: "We eat cake at Christmas." (`Christmas` blue)
  - titles: "We saw Dr Patel today." (`Dr` blue, `Patel` black because it is a name that has to follow the title)
  - short names made of capitals: "My uncle works for NASA." (`NASA` blue)
  - many rules can be in one sentence: "On Tuesday, Mia and I flew to Sydney." (`On`, `Tuesday`, `Mia`, `I`, `Sydney` all blue)
- [ ] The page scrolls when it does not fit the screen, with the "Back to my sentence" button always visible.

## Returning to the sentence

- [ ] A large "Back to my sentence" button, Escape, or clicking "Help" again closes the help page. The same
      sentence is there with the words he had clicked still blue, his tries unchanged, and the last hint as before.
- [ ] He can open and close help as many times as he likes during a sentence. Opening help is not a try, scores
      nothing, and changes no pass or fail count. Nothing about it is recorded in the attempt.
- [ ] Reloading with help open brings back the same sentence with help closed, as a reload does in S040.1.

## The timer

- [ ] The timer bar keeps running while help is open, and it is shown on the help page so he can see it. The
      parent gives a longer `timeout` (such as `180s`) on a task whose pool needs help time.
- [ ] When the bar empties with help open, the help page closes and the answer shows as a timeout, with his clicks as
      they stood, as in S040.1.

# Notes

Depends on S040.1 for the page. The help text and the examples are fixed in the page. A parent cannot edit them, and
they do not depend on the task's pools. Which points show is the task's `help_points`.

The timer is not paused. A pause would need the server to know about help, and a parent could not tell from the
attempt how long he really took. A longer `timeout` gives the same time to read with no new rules. If it turns out to
be too little, a pause is the next step, as its own story.

The page needs no keyboard way to click words, as in S040.1. Help has Escape and Enter on the focused "Back to my
sentence" button because it is a plain button.

Sized as a small change to one page. It adds a button, one overlay with fixed text, and a Chromium test that opens and
closes help during a sentence with words clicked, and across a timeout.

# Implementation

## Files Added

None.

## Files Changed

- `policy/capitalisation_page.py`: the Help button, the help overlay with its fixed text and examples, and the script that opens and closes it.
- `policy/capitalisation.py`: the `help_points` field and its checks.
- `policy/capitalisation_admin.py`, `policy/task_admin.py`, `policy/mcp_writes.py`: the task page data and save for `help_points`, and the MCP setting.
- `policy/portal/src/pages/PartsOfSpeech.tsx`, `pages/Task.tsx`, `partsOfSpeech.ts`, `capitalisationTask.test.tsx`: the Help points check boxes.
- `docs/hierarchical-policy.md`: the `help_points` field.
- `tests/test_capitalisation.py`: tests for `help_points`, and a Chromium test that opens and closes help during a sentence and across a timeout.

## Files Removed

None.

## Change Summary

Help is built into the capitalisation page only. It is a `practice`-class button, so it sits where the Practice button does on spelling and arithmetic. The help text and examples are fixed in `_HELP_POINTS`. The overlay sits above the page but leaves the timer bar showing. Its body scrolls, and "Back to my sentence" sits in a footer that stays visible. Help is a pure client-side overlay, so nothing about it reaches the server or the attempt, and a reload shows the sentence with help closed.

The Enter handler ignores Enter while help is open, so Enter on the focused "Back to my sentence" button works as a plain button. `submit()` refuses a try while help is open. A timeout closes help before the try is sent. The "many rules" example is added as an eleventh point after the ten places.

### Acceptance test cases for S045

1. Start a `capitalisation` task. Check the Help button on the start screen and the question screen, and that it is gone on the answer screen and the end screen. Covers The Help button.
2. During a sentence, click some words, open help, and read the page, including the order of the points and the blue words. Try clicking the sentence, Submit, and Enter, then close help with the button, Escape, and Help again. Covers The help page and Returning to the sentence.
3. Shrink the browser window so the help page scrolls, and check that "Back to my sentence" stays visible. Covers The help page.
4. Set `timeout` to a short value and let the bar empty with help open. Covers The timer.
5. Reload with help open. Covers Returning to the sentence.
6. On a capitalisation task's portal page, untick some Help points and Save, then open help on the child's page: only the ticked points show, in page order. Untick all and check Save is held. Tick all and check `help_points` leaves the policy file. Also give a task `help_points: [people, first_word, i]` by hand and open help: only those three points show, in page order. Then try `help_points: []`, `[dogs]`, and a repeated point, and check each stops the policy loading. Covers the `help_points` check.
