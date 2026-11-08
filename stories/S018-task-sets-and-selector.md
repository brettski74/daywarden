Ticket: S018
Title: Open any task, choose the next one, and score each task once
Status: Done
Story Points: 21
Last Updated: 2026-11-07 17:05:00
---

# User Voice

As a parent, I want the revision rules to decide which tasks my child is offered and which ones earn credit, without
stopping him from doing extra practice. If he bookmarks a task and wants to do it again, or wants to start with a
subject he feels confident about, he should be able to. A repeat should not earn extra credit, and doing the tasks in a
different order should not lose him any.

As a child, when I want to try a different task, I want to pick which one from a list instead of being sent to
whichever one the computer chooses.

# Use Cases

## UC1 - Extra practice from a bookmark

- He has bookmarked the spelling task and opens it directly, after already passing it today.
- The quiz opens and he can do it as many times as he likes.
- Those repeats do not add to today's score. They do not start a cooldown, count as a skip day, count toward
  `max_passes`, or clear a due date.
- The same applies to a task that is cooling down, a task at its `max_passes` limit, and a task whose
  `available_from` date has not arrived yet. None of them is offered by the picker or the selector, but the URL works.

## UC2 - Choosing a different task

- He is partway through a quiz and presses "Try a different task".
- When more than one task is available, he sees a list and chooses one. The list includes the task he just left, so he
  can change his mind and go back to it.
- Going back to the task he gave up within an hour carries on the same attempt, with the progress he had. After an
  hour it is a fresh attempt.
- When only one is available, he goes straight to it.
- When the task he is on is the only required task, he cannot put it down. That is the same as today.
- Finishing a quiz and pressing "Next task" still goes to the picker, so by default he gets whatever task the system
  picks, which keeps his revision varied.

## UC3 - Easier tasks first

- Parts of speech is required today. Addition and spelling are not required. The rule needs 2 tasks.
- He opens spelling and then addition from bookmarks and passes both. His score stays 0, because parts of speech is
  still outstanding.
- He then tries parts of speech and fails it. It has a one-day failure cooldown, so it is no longer required today.
- His score becomes 2 for spelling and addition, and the rule passes.

## UC4 - Not enough tasks left

- He has passed or tried everything he can today and is still short of the rule.
- Repeating a task does not help.
- He asks a parent. The parent records a parent check from `/attempts`, and each check adds one point.

## UC5 - The parent sees where the day stands

- The parent opens `/attempts` for the child's group.
- The page shows today's score, the required tasks still outstanding, the potential tasks still available, and any
  passes that are waiting for the required tasks to be cleared.
- Each attempt in the list says whether it was required, potential, practice, or a parent check.

# Acceptance Criteria

## The task sets

The rules use four sets of tasks, worked out for one client group on one household day.

- **Configured tasks** are every task in the policy assigned to his client group, other than `parent_check`. Cooldowns,
  dates, and limits do not matter.
- **Required tasks** are tasks that meet one or both of these conditions:
  - `due_date` is today or earlier, and the group has never passed the task.
  - The skip days since the last pass have reached `max_skips`. The skip days are counted as they are today.
- **Potential tasks** are the tasks that are not required and that either have no `available_from` or have an
  `available_from` of today or earlier.
- **Available tasks** are the required tasks while there are any, and otherwise the potential tasks. The picker picks
  from this set and the selector lists it.

The required and potential sets, and so the available set, always leave out:

- a task in its pass or failure cooldown,
- a task that has reached `max_passes`,
- a task the group has already passed today.

In each of these rules, a pass, failure, or abandonment means one that is not practice. Practice is defined under
"Practice attempts".

- [x] The picker at `/tasks/next` picks only from the available tasks. While any task is required, it sends him only to
  a required task. Its order is unchanged: a task never passed comes first, then the task whose last pass is oldest,
  and tied tasks take turns.
- [x] A task with `pass_cooldown: 0` that he passed earlier today is not offered again today by the picker or the
  selector.
- [x] A task whose `due_date` is today, and that the group has never passed, is offered as required. A task the group
  passed before its due date is not required on or after that date.
- [x] A task whose skip days since its last pass have reached `max_skips` is offered as required. Once he passes it, it
  is no longer required.
- [x] A task that would be required but is in a cooldown, has reached `max_passes`, or was passed today is neither
  required nor offered.
- [x] A task whose `available_from` is in the future is not offered by the picker or the selector, including when
  nothing else is available.
- [x] When the available set is empty, `/tasks/next` and the selector both say "There is nothing to revise right
  now."

## Direct task URLs

The task pages are not special to the household rules. Ideally the browser does not send the policy server's requests
to the proxy at all, which S019 makes easy. When the browser does send them, the proxy forwards every request for the
policy server without asking for a decision, as described under "The proxy". Which task he may open, and whether it
counts, is decided by the task site itself.

- [x] He can open the page of any configured task directly, for example from a bookmark, and do the quiz. This
  includes a task he passed today, a task in a cooldown, a task at `max_passes`, a task before its `available_from`,
  and an optional task while a required task is outstanding. The task site serves the page, its quiz requests, and its
  audio. It does not send him to the picker.
- [x] A `parent_check` task's URL still does not open a page, and nothing a child sends records a parent check.
- [x] A task name that is not in the policy, or a task that is not assigned to his client group, sends him to the
  picker.

## The proxy

- [x] The proxy treats every name in `PARENT_NAMES` as bypassed, the same as a host in `config/bypass.txt`, except
  `localhost`, `127.0.0.1`, and `::1`. The two lists are merged, and a request whose host matches either one is
  forwarded without a decision, on any port. This includes while the policy service is down.
- [x] A forwarded request whose host is in `PARENT_NAMES` carries the child's address to the policy server, as an
  allowed request does now. This holds whether the host matched `PARENT_NAMES`, `config/bypass.txt`, or both. The task
  pages and the selector then know which child is asking. For example, with `garden` in `PARENT_NAMES` and in
  `bypass.txt`, and his browser sending `https://garden:8090/tasks/next` through the proxy, he is sent to one of his
  own tasks, not told there is nothing to revise. A bypassed host that is not in `PARENT_NAMES` is forwarded as it is
  now, without his address.
- [x] With the policy server's names removed from `config/bypass.txt` and kept in `PARENT_NAMES`, the task pages,
  the picker, the selector, and the parent pages such as `/usage` and `/attempts` all open through the proxy at any
  time, including during school hours and at bedtime in the sample policy. None of them is redirected or denied.
- [x] A change to `PARENT_NAMES` takes effect after `dw restart`, as it does now for the certificate. `dw reload`
  names the proxy among the services that still have the old settings. A change to `bypass.txt` still takes effect
  on the next request.
- [x] `config/bypass.txt` and the configuration directory stay read-only to the containers. Nothing writes to
  `bypass.txt` at startup. The merge happens in the proxy's memory. A first install still writes this machine's names
  into `bypass.txt`, as it does now.
- [x] `dw check`, and the check in `dw reload`, `dw restart`, and `dw up`, warn about each name in `PARENT_NAMES`,
  other than `localhost`, `127.0.0.1`, and `::1`, that `bypass.txt` does not match. The warning says that the name
  only bypasses the proxy until the next restart picks up a change. It is a warning, not an error, and nothing is
  refused.
- [x] The decision service has no task-site handling of its own. It no longer allows a task page that the household
  rules would deny or redirect, and it no longer redirects a request for a task page to the picker or to another task.
  A policy-server URL that reaches the decision API, for example from a test, is judged by the household rules like
  any other URL.
- [x] A rule that redirects to `revision_task` gets him to an available task, chosen the way the picker chooses. The
  redirect can name the task directly, as it does now, or go through the picker. Either is acceptable, and this story
  does not require the current behaviour to change. When nothing is available, he ends up on the page that says
  "There is nothing to revise right now."
- [x] Remembering the page he was sent away from, and going back to it after a pass, works as it does now.
- [x] With the sample `.env`, `config/bypass.txt`, and `config/policy.yaml`, a redirect to revision during school hours
  opens a task, and every direct task URL in this story opens.

## Practice attempts

An attempt is **required**, **potential**, or **practice**, depending on which set the task was in when he started the
attempt. Practice means the task was in neither the required set nor the potential set.

- [x] A practice attempt is stored. A practice pass shows "Well done" like any other pass, including the return to the
  page he was sent away from.
- [x] A practice attempt adds nothing to today's score.
- [x] A practice pass does not start a pass cooldown, count toward `max_passes`, clear a due date, or reset skip days.
  A practice failure or give-up does not start a failure cooldown and is not a skip day. For example, he passes
  spelling with `failure_cooldown: 1`, then fails a practice attempt the same day, and spelling is offered as usual
  tomorrow.
- [x] An attempt stays in the set it started in until it finishes. Coming back to it, or a `dw reload` while it is in
  progress, does not change its set.

## Today's score

The score is what `tasks_required` compares against `required`.

- [x] A passed attempt that was required scores one point on the household day it passed.
- [x] A passed attempt that was potential scores one point on the day it passed, but only while there are no required
  tasks. While a required task is outstanding, it waits and scores nothing.
- [x] No task scores more than once on a household day, whatever mix of required, potential, and practice passes it
  has.
- [x] Each parent check recorded from `/attempts` scores one point on the day it was recorded, even when several are
  recorded the same day and even while a required task is outstanding.
- [x] The scenario in UC3 works through the proxy. With parts of speech due today and `failure_cooldown: 1`, addition
  and spelling with no limits, and `tasks_required` of 2, YouTube is redirected to revision after spelling and
  addition are passed. It is allowed once parts of speech has been failed.
- [x] In the same setup, passing parts of speech instead of failing it gives a score of 3, and YouTube is allowed.
- [x] In the same setup with no `failure_cooldown` on parts of speech, failing it leaves the score at 0 and YouTube is
  still redirected. A parent check then adds 1, and a second parent check makes it 2 and YouTube is allowed.
- [x] A `dw reload` that gives a not-yet-passed task a due date of today makes that task required. The waiting
  potential points stop counting on the next decision, until that task has been passed or is in a cooldown.
- [x] Attempts stored before this version of daywarden is installed are kept, and are treated as Required from the
  first start of the new version. They count for cooldowns, skip days, `max_passes`, and due dates as they do now. A
  pass from earlier on the day of the upgrade scores one point, and no task scores more than once a day.
- [x] A `dw reload` never changes the set of an attempt already stored, finished or not. A task that becomes required
  after he passed it as a potential task today stays a potential pass.

## The task selector

- [x] A new page, the task selector at `/tasks/choose`, lists the available tasks, in the same order the picker would
  try them.
- [x] When exactly one task is available, the selector sends him straight to it.
- [x] When more than one task is available, the selector lists them by task name, and each one opens that task.
- [x] When nothing is available, the selector says "There is nothing to revise right now."
- [x] The selector never leaves out an available task, including the one he just gave up and any others he gave up
  earlier.
- [x] A task named `choose` is opened at `/tasks/work/choose`, the same way a task named `next` is opened today.
- [x] Opening the selector does not move on the picker's turn order.

## Try a different task, and Next task

- [x] After he confirms "Try a different task" on a quiz, the attempt is given up and he goes to the selector, not to
  a task the picker chose. This includes the give-up review that some quizzes show first.
- [x] After a give-up, the selector lists every available task, including the one he just left.
- [x] When the task he left is the only available task, the selector sends him straight back to it. When nothing is
  available, he sees "There is nothing to revise right now."

- [x] Giving up the only available required task is still refused with "This task has to be finished before another
  one." The attempt stays in progress.
- [x] A potential or practice attempt can always be given up, including while a required task is outstanding. The
  selector then lists the available tasks, which are the required ones while any are outstanding.
- [x] "Next task" on the end screen of a quiz still goes to the picker, which chooses from the available set as it
  does today. It is shown only when the available set is not empty, and "All done for now" is shown otherwise.

## Coming back to a task he gave up

These rules apply to an attempt that was abandoned by giving up. A give-up that ended in a pass or a failure, which a
few quizzes allow when closing the open question decides the result, is finished and is not reopened.

- [x] When he opens a task within an hour of giving it up, on the household day the attempt started, the abandoned
  attempt is reopened and carries on. This works whatever way he opens it: the selector, the picker, "Next task", or a
  bookmark. His count, run, and earlier answers are as they were when he gave up. The question that was showing when
  he gave up stays a timeout, as it would after a reload.
- [x] The hour is the quiz's existing idle limit, counted from the give-up. Coming back more than an hour after the
  give-up, or on a later household day, starts a new attempt, and the given-up attempt stays abandoned.
- [x] Only the task's most recent attempt is reopened, and only if no newer attempt of that task has been started.
- [x] A reopened attempt is in progress again. It is no longer an abandonment, so it is not a skip day and does not
  count toward `max_skips`. If he gives up on it again, it is abandoned again and the hour starts again from that
  give-up.
- [x] A reopened attempt keeps the set it started in.
- [x] The parent attempt page for a reopened attempt shows when he gave up and when he came back, each time it
  happened.

## An attempt belongs to one day

- [x] An attempt left in progress, for example when he closed the tab partway through a quiz, is resumed only on the
  household day it started. Today it is resumed on any later day.
- [x] When he opens that task on a later household day, the old attempt is closed as unfinished, and a fresh attempt
  starts in the set the task is in now. This happens whatever way he opens the task.
- [x] Once the household day it started has ended, an unfinished attempt counts as a skip day for the day it started,
  the same as giving up would have. This holds whether or not he opens the task again, so closing the browser does not
  dodge `max_skips`. For example, a task with `max_skips: 1` that he started and left open on Monday is required on
  Tuesday.
- [x] Like an abandonment, an unfinished attempt scores nothing, starts no cooldown, and does not count toward
  `max_passes`. An unfinished practice attempt has no effect at all, like any practice attempt.
- [x] An unfinished attempt and a give-up or failure on the same day are still one skip day.
- [x] The parent attempts page shows the outcome of an attempt from an earlier household day that was never finished
  as Unfinished, whether or not he has opened the task again since. This includes attempts left open before this
  change.
- [x] Opening the task is what makes this check. A quiz already on the screen when the household day ends carries on,
  and a pass scores on the day it passes.

## The parent attempts page

- [x] Each attempt on `/attempts`, and the attempt page it opens, says whether the attempt is Required, Potential,
  Practice, or Parent check. An attempt stored before this version was installed is shown as Required.
- [x] For the chosen client group, `/attempts` shows today's score, the required tasks still outstanding, the
  potential tasks still available, and the potential passes that are waiting on required tasks.
- [x] The score shown is the one YouTube decisions use for that group at that moment.

## Documentation

- [x] `docs/hierarchical-policy.md` describes the four task sets, practice attempts, the score, the selector, coming
  back to a given-up task, unfinished attempts, and direct task URLs. It says that `pass_cooldown: 0` no longer offers
  a task again on the day it was passed, and that an unfinished attempt is a skip day. Its descriptions of
  `due_date`, `max_skips`, `max_passes`, and the picker match this story.
- [x] The README and `.env` notes say that the names in `PARENT_NAMES` are also the policy server's names that the
  proxy forwards without a decision. `config/bypass.txt` is for other hosts, but may also include the policy server. This
  may even be advisable since `config/bypass.txt` is read on every request, whereas `PARENT_NAMES` only applies after a
  restart.
- [x] The documentation advises applying policy changes and upgrades overnight, while the child is not using the
  computer, and says why.

# Notes

## Decisions made while refining

- While any task is required, the available set is only the required tasks. Potential tasks are reached by direct URL
  until then, and they still earn their points once the required set is empty.
- Practice attempts affect nothing. They are stored and shown to the parent so extra work is visible.
- `due_date` keeps its current meaning: required from that date until the group has passed the task once, at any time.
  Only a pass that is not practice counts.
- The rule that he cannot give up the only required task stays.
- Going back to a task within an hour of giving it up carries on the same attempt. The hour is the same idle limit the
  quizzes already use to expire a run.
- An attempt belongs to the household day it started. One left open is closed as unfinished when the task is next
  opened on a later day, and a fresh attempt starts. An attempt keeps the set it started in.
- An attempt left unfinished is a skip day for the day it started, from the next day on, the same as giving up.
  Otherwise closing the browser would be a way round `max_skips`.
- Parent checks score every time they are recorded, including several in one day and while required tasks are
  outstanding. They remain the way to give credit when he cannot reach the count himself.
- The policy server is protected from the household rules at the proxy, by treating the names in `PARENT_NAMES` as
  bypassed, instead of by task-site handling in the decision service. This is a stop-gap until S019, and a browser
  that skips the proxy for those names is still the ideal. The names stay in `bypass.txt` as well, because that list
  applies on the next request and `PARENT_NAMES` only after a restart.
- The `max_skips` rule is read as "the skip days since the last pass have reached `max_skips`", which is what the code
  does now. The wording "has not been met" in the original request was taken as a slip.

## Assumptions

- "Configured tasks" means tasks assigned to his client group. A task assigned only to another group is not his to
  practise, because attempts are kept per group.
- An attempt's set is taken when the attempt starts, and the attempt is stored with it. It does not change.
- No attempt is resumed on a later household day, so a practice attempt left open never gets in the way of a counted
  attempt the next day.
- A pass scores on the household day it passed. That is almost always the day it started. The exception is a quiz that
  is still on the screen when the day ends.
- The selector is only offered from "Try a different task". The picker stays the default everywhere else, including
  the redirect to `revision_task` and "Next task", so his revision keeps its variety. The selector can still be opened
  directly at `/tasks/choose`.
- The selector does not leave out tasks he has given up. The current way of skipping tasks already given up in this
  visit is no longer needed.

## Out of scope

- A proxy configuration URL that tells the browser not to send the policy server's requests to the proxy at all is a
  later story, S019. Until then, `bypass.txt` and the proxy's `PARENT_NAMES` bypass let them through.
- Writing missing `PARENT_NAMES` into `bypass.txt` automatically, other than on a first install, is not part of this
  story. The configuration directory stays read-only to the containers.

## Edge cases worth knowing

- A name the browser uses for the policy server that is in neither `PARENT_NAMES` nor `bypass.txt` is not bypassed.
  It is judged by the household rules, and a rule that redirects it to `revision_task` sends the browser round in a
  loop. Such a name is also missing from the certificate, so the browser warns about it anyway. The fix is to add it
  to both.
- A name added to `PARENT_NAMES` without a restart is not bypassed until the restart. A name added to `bypass.txt` is
  bypassed at once. That is why the names belong in both places, and why `dw check` warns when one is missing from
  `bypass.txt`.
- Because the policy server is never judged by the rules, its task pages open at any time, including at bedtime.
  Revision at bedtime is not a reward, so this is accepted.
- As the code reads today, the proxy forwards a host on the bypass list without the child's address, so in the sample
  setup the task site would not know which child was asking. This was found by reading the code, not by trying it.
  The policy server's names now carry his address whichever list they matched. Other bypassed hosts keep working as
  they do now.

- The sample policy has no `failure_cooldown` on any task. Failing a required task there leaves it required, so the
  waiting potential points do not count until he passes it or a parent records parent checks. This matches the rules,
  but a parent who wants the UC3 escape needs to set a failure cooldown on the hard task.
- Giving up does not start a cooldown, so giving up a required task never clears the required set. It does count as a
  skip day, as it does now, unless he comes back to the attempt within the hour. Closing the browser instead of giving
  up ends the same way once the day is over.
- Within one household day, the required set can only shrink, unless the parent reloads the policy. So a
  `tasks_required` rule that holds stays true until the day ends, apart from a reload that adds a required task.
- A reload partway through the day that makes tasks required can make him do more tasks than he would have otherwise.
  For example, he has passed spelling as a potential task. A reload then makes spelling and two new tasks required.
  Spelling was passed today, so it is not required, but its point waits until both new tasks are passed. That is three
  tasks where two would have done. This is accepted rather than handled. A parent can make up for it with a parent
  check, and the documentation advises applying policy changes and upgrades overnight, outside the child's hours.
- Once he has passed every task he can, or every remaining task is cooling down, nothing he does adds points that day.
  Only parent checks do.

## Size

This is one story at 21 points. Compared with the 14-point reference, it adds a new page, a new way of scoring, a stored
set on every attempt, reopening a given-up attempt, and closing attempts left open on an earlier day. It moves the
policy server's protection from the decision service to the proxy's bypass, which deletes more code than it adds.
The way a redirect to `revision_task` picks its task can stay as it is. Many existing selection, task-page, and
decision tests change or go, because a direct URL is no longer redirected.

That is at the top of 21, and arguably a little over. It is kept as one story by choice, because S016 was a 21-point
story that fit comfortably in one session. If it had to be split, the first part would be the task sets, direct URLs,
the proxy change, practice, and scoring, and the second would be the selector, "Try a different task", coming back to
a given-up task, and the parent page summary.

# Implementation

## Files Added/Changed/Removed

Changed:

- `policy/tasks.py`: each attempt is stored with its task set (`required`, `potential`, `practice`, or
  `parent_check`) and the times it was given up and carried on. A new `unfinished` outcome has no finish time. A
  database from before this change is upgraded in place the first time a service opens it, and its attempts become
  Required. `task_sets` works out the configured, required, potential, and available tasks. A task passed today is no
  longer offered, and practice attempts are left out of cooldowns, skip days, `max_passes`, and due dates. An attempt
  left in progress is a skip day for the day it started. `day_score` is the new score. `AttemptStore.open` carries on
  today's attempt, reopens one given up within the hour, or closes one left from an earlier day as unfinished.
  `AttemptStore.history` reads a group's attempts without their quiz detail, for the score and the sets.
- `policy/selection.py`: the decision-time task handling (`apply_task_selection`, `may_open`, the visit cookie, and the
  "reopen required" rule) is gone. It now orders the available tasks for the picker and the selector, and decides
  whether an attempt may be given up from its set. Adds `/tasks/choose`, and serves a task named `choose` under
  `/tasks/work/`.
- `policy/task_page.py`: any configured task opens at its own URL. Adds the selector. "Try a different task" goes to the
  selector. A task name that is not his goes to the picker. Audio is served for any configured task.
- `policy/engine.py`: `revision_task` is always the picker. A policy-server URL is judged like any other.
  `tasks_required` passes the policy's tasks to the ledger so it can score.
- `policy/usage.py`: `successes` scores with `day_score`.
- `policy/quiz_page.py`: "Next task" is shown while the available set is not empty.
- `policy/spelling_page.py`: "Continue" on the missed words screen always goes to the selector.
- `policy/review.py`: `/attempts` shows today's score, the required tasks outstanding, the potential tasks available,
  and the passes waiting. Each attempt shows its set, an attempt left open on an earlier day shows as Unfinished, and
  the attempt page lists each give-up and return. A parent check is stored in the parent check set.
- `policy/app.py`: passes the tasks to `/attempts`, and no longer passes the attempt store to the decision.
- `policy/check.py`: `--parent-names` warns about each name in `PARENT_NAMES`, other than the loopback names, that
  `bypass.txt` does not match. The warning is printed even with `--quiet`.
- `proxy/bypass.py`, `proxy/addon.py`: the names in `PARENT_NAMES`, other than `localhost`, `127.0.0.1`, and `::1`, are
  bypassed, and a request for one of them carries the child's address in `X-Daywarden-Client`, whichever list matched.
- `docker-compose.yml`: the proxy gets `PARENT_NAMES`.
- `bin/daywarden-lib.sh`: the policy check is given `PARENT_NAMES` from `.env`.
- `.env`, `config/bypass.txt`: notes on the policy server's names. The sample `bypass.txt` adds `garden.bakuna.net`.
- `README.md`, `docs/hierarchical-policy.md`: the task sets, practice, the score, the picker and the selector, direct
  task URLs, coming back to a given-up task, unfinished attempts, the proxy bypass of `PARENT_NAMES`, and the advice to
  apply changes and upgrades overnight.
- `tests/test_task_selection.py`: rewritten for this story.
- `tests/test_bypass.py`, `tests/test_policy_check.py`, `tests/test_enforce_decisions.py`, `tests/recording_origin.py`,
  `tests/recording-origin.compose.yml`: the `PARENT_NAMES` bypass, the child's address, and the check warning.
- `tests/test_dw.py`, `tests/test_policy_hostname.py`, `tests/test_return_to_page.py`, `tests/test_arithmetic.py`,
  `tests/test_spelling.py`, `tests/test_skip_counting.py`, `tests/test_parts_of_speech_quiz.py`,
  `tests/test_task_catalogue.py`: updated for the picker redirect, the selector, and the new rules.

## Change Summary

The proxy now keeps the household rules away from the policy server: every name in `PARENT_NAMES` is forwarded without
a decision and tells the policy server which child is asking. With that, the decision service lost all of its task-site
handling, and a redirect to `revision_task` always goes through the picker.

The policy server works out four task sets for a client group each time it needs them. The picker and the new selector
offer only the available set, but any configured task opens from its own URL. Each attempt records the set it started
in. Practice attempts are stored and shown, and count for nothing. The score counts required passes at once, potential
passes once nothing is required, each task at most once a day, and every parent check.

"Try a different task" goes to the selector. Opening a task within an hour of giving it up carries on that attempt. An
attempt belongs to the household day it started: one left open is a skip day for that day and is closed as unfinished
when the task is next opened.

Existing databases are upgraded in place on the first start, and their attempts become Required.

## Suggested Acceptance Testing

### S018 acceptance test cases

Setup for most cases: run daywarden with the sample `.env`, `config/bypass.txt`, and `config/policy.yaml`, sign in to
`/attempts` as a parent in one browser, and use the child computer's browser through the proxy for the rest.

1. **Upgrade keeps old attempts.** Before installing, note a group's attempts on `/attempts`. Install this version and
   run `dw restart`. The same attempts are listed, each with Set "Required", and today's score shown at the top counts
   each task passed today once.
2. **UC3 through the proxy.** In `policy.yaml`, give `parts_of_speech` `due_date` of today and `failure_cooldown: 1`,
   leave `sums` and `spelling` with no limits, keep `tasks_required` at 2, and `dw reload`. In the evening window, open
   YouTube: it redirects to revision and lands on parts of speech. Open the spelling and sums task URLs directly and pass
   both. YouTube still redirects, and `/attempts` shows score 0, parts_of_speech outstanding, and spelling and sums
   waiting. Fail parts of speech. YouTube now plays, and the score is 2.
3. **Passing the hard task.** Repeat case 2 on a fresh day (or after removing today's attempts with `rm-attempts`), but
   pass parts of speech instead. The score is 3, and YouTube plays.
4. **Parent checks make up the count.** Repeat case 2 with no `failure_cooldown` on parts of speech. After failing it,
   YouTube still redirects and the score is 0. Record a parent check on `/attempts`: the score is 1. Record another:
   the score is 2, and YouTube plays.
5. **Repeats count for nothing.** Pass a task, then open its URL again from a bookmark and pass it again. "Well done"
   shows as usual. On `/attempts` the second attempt is Practice, and the score did not change. Next day the task is
   offered as usual.
6. **Direct URLs open anything configured.** Open, by URL, a task passed today, one in its cooldown, one at
   `max_passes`, one whose `available_from` is in the future, and an optional task while a required task is
   outstanding. Each opens and runs its quiz, including spelling audio. On `/attempts` the first four are Practice and
   the last is Potential.
7. **Task pages are never blocked.** During school hours and at bedtime in the sample policy, open `/tasks/next`,
   `/tasks/choose`, a task URL, `/usage`, and `/attempts` on the policy server. None is redirected or denied.
8. **Try a different task.** With several tasks available, start one and confirm "Try a different task". The browser
   lands on `/tasks/choose`, which lists every available task by name, including the one just left. Each link opens
   that task.
9. **Coming back within the hour.** Answer a few questions, give up, then pick the same task from the selector within
   an hour. The quiz shows the same count, and the attempt page on `/attempts` shows when he gave up and when he came
   back. Give up and come back again: both pairs of times are listed.
10. **After the hour.** Give up a task and open it again more than an hour later. A new attempt starts at 0, and the
    old one stays abandoned on `/attempts`.
11. **The only required task.** Make one task due today and try "Try a different task" on it. It says "This task has
    to be finished before another one." and the attempt stays in progress. With a second task due today, giving up the
    first goes to the selector, which lists only the two required tasks.
12. **Optional tasks can be put down.** While a task is required, open an optional task by URL and give it up. It is
    abandoned, and the selector sends him straight to the required task.
13. **One task left.** With only one task available, give it up. The selector opens that task again straight away. When
    nothing is available, `/tasks/next` and `/tasks/choose` both say "There is nothing to revise right now."
14. **Next task.** Pass a quiz while other tasks are available: "Next task" goes to the picker, which opens a task. Pass
    the last available task: "All done for now" is shown instead.
15. **`pass_cooldown: 0`.** Set a task's `pass_cooldown` to 0 and pass it. The picker and selector no longer offer it
    today, and they do tomorrow.
16. **Unfinished attempts.** Give a task `max_skips: 1`. Open it and close the tab without finishing. Next day,
    `/attempts` shows yesterday's attempt as Unfinished, and the picker sends him to that task as required. Opening it
    starts a fresh Required attempt.
17. **A reload that makes a task due.** Pass an optional task, then give another task a due date of today and
    `dw reload`. The score drops by that point and `/attempts` lists the pass as waiting, until the new task is passed.
    The earlier pass still shows as Potential.
18. **`PARENT_NAMES` without `bypass.txt`.** Remove the policy server's names from `config/bypass.txt`, keep them in
    `PARENT_NAMES`, and run `dw check`. It warns about each name and says it only bypasses the proxy until the next
    restart picks up a change. `dw up`, `dw restart`, and `dw reload` show the same warning and carry on. The task
    pages, the picker, the selector, `/usage`, and `/attempts` still open through the proxy, at any time.
19. **The child's address on a bypassed name.** With `garden` in both lists, open `https://garden:8090/tasks/next`
    through the proxy from the child's computer. It opens one of his tasks, not "There is nothing to revise right now."
20. **A `PARENT_NAMES` change needs a restart.** Add a new name for this machine to `PARENT_NAMES` only, and run
    `dw reload`. It names the proxy among the services with old settings. Until `dw restart`, that name is judged by the
    rules. After it, the name is forwarded. A name added to `bypass.txt` is forwarded at once.
21. **Loopback names are not bypassed.** With `localhost` in `PARENT_NAMES`, a request through the proxy for
    `http://localhost/` is still decided by the rules.
22. **The policy service down.** Stop the decisions container. Pages on the policy server's names are still forwarded
    by the proxy (they then fail to load because the service is down), while other sites get the 403 page.
23. **A task named `choose`.** Add a task named `choose`. It opens at `/tasks/work/choose`, and `/tasks/choose` is
    still the selector.
24. **Parent check URL.** Open a `parent_check` task's URL as the child. No page opens, he is sent to the picker, and no
    attempt is stored.
25. **A task that is not his.** Open a task name that is not in the policy, and one assigned only to another client
    group. Both send him to the picker.
26. **The attempts page summary.** On `/attempts` for the younger group, check that the score matches what YouTube
    decisions do, and that the required, potential, and waiting lists match the tasks above. Each attempt shows Required,
    Potential, Practice, or Parent check.
27. **Documentation.** `docs/hierarchical-policy.md` and the README describe the task sets, practice, the score, the
    selector, coming back, unfinished attempts, direct URLs, the `PARENT_NAMES` bypass, and applying changes overnight.
