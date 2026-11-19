Ticket: S042
Title: Arithmetic required practice
Status: Done
Story Points: 5
Last Updated: 2026-11-19 12:00:00
---

# User Voice

As a parent, I want to require a practice walk before he starts the quiz on an arithmetic task, so that he warms up on
the facts before they count. Practice stays optional on every task where I do not ask for it.

# Behaviour

A *finished walk* is a practice walk of S039 that he took to its end. A walk he left early, by reloading, giving up, or
going back to the quiz, is not finished.

## Policy file and task editing

- [ ] An arithmetic task body may set `practice_required: true`. It defaults to `false`, and a task that leaves it out
      or sets it `false` behaves exactly as in S039, with practice optional. A value that is not `true` or `false`
      fails the load, naming the task and the field.
- [ ] `practice_required: true` on a task with fewer than 5 values in `operands`, where S039 offers no Practice button,
      fails the load, naming the task and the field.
- [ ] The portal's arithmetic task page has a Practice Required checkbox under the other settings, unticked when the
      file leaves the field out. Saving a ticked box writes `practice_required: true`. Saving an unticked box removes
      the field. Saving works as in S039 for `practice_fallback`. Ticking it with fewer than 5 operand values is
      refused on Save, naming `practice_required`, as any other value the policy load refuses is.
- [ ] The MCP `create_task` and `update_task` tools can set `practice_required`, and `update_task` with `null` removes
      it.

## Before practice

- [ ] On a task with `practice_required: true`, a new attempt's start screen shows Start disabled, with the message
      "Practise first", and Practice as the main button in the place Start has. Pressing Start does nothing, and Enter
      does not start the quiz.
- [ ] The quiz cannot be started another way while practice is owed. Reloading the page, or opening the task again,
      shows the same locked start screen, and no question is asked until a walk is finished.
- [ ] Pressing Practice while practice is owed starts the walk at once, with no confirmation, because there is no quiz
      progress to reset and no quiz to keep going with. Practice works as in S039 in every other way: it is allowed when the task is the only required
      one, it never passes the attempt or marks it abandoned, and a walk plays as there. "Try a different task" and
      give-up work as before and are not blocked by the requirement.

## After practice

- [ ] When he reaches the end of a walk, the page returns to the start screen as in S039, with "Practice done. Start the
      quiz when you are ready." and `0 / n correct`, now with Start enabled and focused. The quiz's first question is
      asked when he presses Start.
- [ ] Leaving a walk early keeps Start disabled. He must start another walk and finish it.
- [ ] The requirement is once per attempt. Reloading, or coming back to an attempt that has a finished walk, shows
      Start enabled and does not ask for another walk. A new attempt of the same task, such as after a pass, a
      give-up, or the next day, is locked again.
- [ ] Once Start is pressed the quiz runs as in S004.1, and the Practice button, where S039 offers it, is available on
      the question screen as before. Entering practice again later is optional and has no effect on the requirement.

## Records

- [ ] The attempt page lists the walks as in S039, so a finished walk is one headed "finished". No new figures or
      sections appear, and the attempt's figures and the facts page are unchanged by the requirement.

# Notes

Depends on S039 for the walk, the Practice button, its confirmation, and the end-of-walk screen. The requirement is
checked by the server as well as the page, so a request for the quiz's first question is refused while practice is owed
and no attempt can start the quiz around the locked button.

The finished walk is found from the walk records S039 already stores on the attempt (`ended` of `finished`), so no new
stored state is needed.

Out of scope: requiring more than one walk, requiring a minimum score within the walk (the walk has no failure), a
daily rather than per-attempt requirement, and choosing `m` by hand.

Sized at 5 against S039 (8), which built the walk itself. This adds a policy field and its load check, a checkbox and
MCP setting, a server refusal, and a locked start screen state.

# Implementation

## Files Added

- `tests/test_arithmetic_required_practice.py`: the setting and its load checks, the server refusing the quiz while practice is owed, unlocking and relocking, the page script in the Node harness, and the portal and MCP saves.

## Files Changed

- `policy/arithmetic.py`: `practice_required` in the settings and its load checks, `Session.practice_owed`, and `PracticeOwed`, which `issue` raises while a finished walk is owed.
- `policy/arithmetic_page.py`: the locked start screen (disabled Start, "Practise first", Practice as the main button), the script that unlocks it when a walk ends, and the refusal of a question request while practice is owed.
- `policy/number_lists_admin.py`, `policy/mcp_writes.py`: `practice_required` is one of an arithmetic task's settings, so the portal save and the MCP write tools take it.
- `policy/portal/src/arithmetic.ts`, `labels.ts`, `pages/Arithmetic.tsx`: the Practice Required checkbox.
- `docs/hierarchical-policy.md`: the field.
- Tests: `tests/test_arithmetic_admin.py` (the page's settings include the new one) and the portal's `arithmetic.test.tsx`.

## Files Removed

None.

## Change Summary

The requirement is worked out from the walk records S039 already stores: practice is owed while the task sets `practice_required` and no walk on the attempt has `ended` of `finished`. No new stored state was added. Because walks live on the attempt, the requirement is once per attempt, survives a reload or an hour's gap, and starts again on a new attempt. `Session.issue` raises `PracticeOwed`, a `StaleQuestion`, so the page answers a question request the way it answers a stale one, with a reload, and the quiz cannot be started around the disabled button.

On the locked start screen Practice takes the `big` button style and Start is disabled. When a walk ends the script enables Start, hides the message, and puts Practice back to its small corner place, as in S039's end-of-walk screen.

The portal sends the box as the text `true`, and an unticked box sends nothing, which removes the field. A file that says `false` keeps its `false` when the box is unticked. The save of a task with fewer than 5 operand values is refused by the policy load, as for a bad `practice_fallback`, so the page shows no separate problem.

Tests: the full suite passed (2457 tests) and the portal's 427 tests, its type check, and a production build pass. The one portal test that failed in an earlier parallel run (`facts.test.tsx`) passed alone and on rerun. Not checked in a browser: the locked start screen, and the checkbox's position, are tested in the Node harness and jsdom only.

## Suggested Acceptance Testing

### Acceptance test cases for S042

Set up an arithmetic task as in S039's test cases, with `operands: [{ from: 1, to: 10 }]`, `first: [{ value: 7 }]`, and a pass cooldown of 0.

1. **Locked start.** Add `practice_required: true`, open the task as the child, and check the start screen says "Practise first", Start is disabled, Practice is the large main button, and Enter or clicking Start asks nothing. Reload and check it is the same, then press Practice and check the walk starts at once with no confirmation. Covers Before practice.
2. **Finishing a walk.** Press Practice, confirm, and answer the whole walk right, then again with some misses. Check the "Practice done" screen has Start enabled and focused, and Start asks the first question. Reload, and check Start stays enabled. Covers After practice.
3. **Leaving early.** Start a walk, reload part way, and check Start is still disabled. Start another and finish it, and check Start is enabled. Covers After practice.
4. **A new attempt.** Set `correct_answers_required: 1`, practise, pass the quiz, then open the task for a new attempt and check it is locked again. Covers After practice.
5. **Give up and optional practice.** While locked, use "Try a different task" and give-up, and check they work as before. After unlocking, enter practice again from the question screen and leave it, and check the quiz still starts. Covers Before practice and After practice.
6. **Default and policy checks.** Remove the field and check practice is optional as in S039. Set `practice_required: yes`, then `true` with `operands` of 1 to 4, and run `dw check` to see each fail naming `practice_required`. Covers Policy file and task editing.
7. **Portal and MCP.** On the arithmetic task page, check Practice Required is unticked, tick it and Save, and check the file has `practice_required: true`. Untick and Save, and check the line is gone. Tick it with 4 operand values and check the Save is refused naming it. Ask the MCP agent to set it true and then clear it with `null`. Covers Policy file and task editing.
8. **Records.** After a locked attempt with a finished walk, open `/parent/attempts/<id>` and check the walk is headed "finished" and no new figures or sections appear. Covers Records.
