# Hierarchical policy

Status: agreed on 2026-10-26 and built by [S008](../stories/done/S008-hierarchical-policy.md).

This note describes the household policy model.

# Model

Rules are the structure. Site groups, client groups, time windows, and quotas are named values a rule can test. Nesting has no required order. The engine walks the list it was given.

Before any rule runs, the request is classified once.

- **Site group.** The configured site groups are tried in priority order, lowest number first. The first group whose pattern matches is the request's site group. A group named `default` is not written in the file. It is the group that remains after every configured group has failed to match. It has no priority and no patterns. It is never consulted while configured groups are still being tried, so a low priority number on some other group cannot hide the groups that follow it.
- **Client group.** The address is looked up in the configured client groups. It belongs to at most one of them. An address in none of them belongs to the implicit client group `default`. That group is not written in the file. It has no address list.

`default` is a reserved name in both of those namespaces. Defining a site group or a client group with that name is a load error. In a `site_group` condition it means the implicit site group. In a `client_group` condition it means the implicit client group. Other namespaces may still use the spelling.

A request always has both attributes. Rules test those attributes. They do not run the pattern match or the address match again. A rule set that never mentions client group still runs for every address, and the address is still recorded against whichever client group it fell into, including `default`.

Usage is recorded against that same pair. A site does not match one group in the rules and a different group in the log. Counting the same traffic against several limits is a quota's job, and it is explicit.

## Namespaces

Site groups, client groups, time windows, quotas, rule sets, and tasks are six namespaces. A name is unique inside its own namespace. The same spelling may be used in two namespaces. A field that expects a site group accepts only a site group. The same rule applies to client groups, time windows, quotas, rule sets, and tasks.

References are resolved after every included file has been read. A name that resolves to nothing is a load error. A second definition of the same name in the same namespace is a load error. A later file does not extend or replace an earlier definition.

## Site groups

A configured site group has a name, a unique integer priority, and a list of glob patterns. The name `default` is reserved for the implicit remainder and cannot be used here. Pattern matching stays as it is:

- A pattern containing `://` is matched against the absolute URL with the fragment removed.
- Any other pattern is matched against the host only.
- Matching ignores case. `*` matches any run of characters, including `/`. `?` matches one character.
- `*.youtube.com` matches `www.youtube.com` and does not match `youtube.com`.

Overlapping patterns are expected. A narrower group is given a lower priority number than the wider group it sits inside, and the first match wins. The implicit `default` group is what remains. It is not a configured group whose patterns were ignored, and it is not placed in the priority list.

A `site_group` condition is true when the request's classified site group is one of the groups the rule names. That includes `default`.

## Client groups

A client group is a named set of addresses. It has no priority. An address is an IP or a DNS name. DNS names are resolved when the policy is loaded. If a name does not resolve, the group keeps the addresses stored by the last load that did resolve it. Resolved addresses are compared in their canonical form, so an IPv4 address and the IPv4-mapped IPv6 form of the same address are the same address.

The group is not a user account. Which person sits at the machine is out of scope. There is no separate sign-in for the child. Quotas, revision counts, and task assignments hang off the client group the address belongs to.

An address listed twice is a load error. That includes two entries in one group, the same address in two groups, and two DNS names that resolve to one address. Client groups are explicit lists of machines on this network. Overlap is not a narrowing the way a glob can be, and the load fails rather than picking a winner.

The implicit `default` client group holds every address that belongs to no configured group. Every such address shares that one group: one revision count, one set of task assignments, and one balance on each quota. An unknown computer is refused when no rule grants access to `default`. That is the ordinary fall-through under rules. It does not need a final deny written out. A policy can also name `default` and handle it on purpose.

The household has one IANA timezone. It defines "now" and "today" for every group. Leave it unset to use the timezone of the machine running the service.

## Time windows

A time window has a name and one or more periods, written in that one definition. Using the name again is a load error.

Each period has a start, an end, and an optional day constraint. The window is true when the household-local time falls inside any period.

The end is the next moment after the start at which the clock shows the end time, plus any extra days. The start is included and the end is excluded. There is no way to place the end before the start, and there is no empty period.

- An end clock later than the start falls on the same day. At 15:00, a period ending at 15:00 is a different case, below. A period of `15:00–19:00` contains 15:00 and does not contain 19:00.
- An end clock earlier than the start falls on the next day. Saturday `22:00–07:00` contains Saturday 23:30 and Sunday 06:30, and does not contain Saturday 06:30. The named day is the day the period starts.
- An end clock equal to the start falls 24 hours later. Friday `14:00–14:00` is Friday 14:00 through Saturday 14:00, not including Saturday 14:00. It is not an empty period.

An end may add whole days with a `+n` suffix, where `n` is a whole number of zero or more. Omitted, it means `+0`. A negative `n` is a load error. The suffix adds `n` times 24 hours after the moment above. Friday `14:00` through Sunday `14:00` is start `14:00`, end `14:00+1`, day Friday: the base end is Saturday 14:00, and one extra day moves it to Sunday 14:00. Friday 14:00 through Sunday 18:00 is end `18:00+2`. The `+0` end would be Friday 18:00, and two extra days move it to Sunday 18:00.

The period starts only on a day the day constraint names. Saturday 10:00 is inside the Friday `18:00+2` period because it sits between Friday 14:00 and Sunday 18:00. It is not a second start. A period with no day constraint can start on any day. An empty day list is rejected. A multi-day period with no day constraint starts every day, so the spans overlap and the window is true more often than a Friday-only span. The day constraint belongs on a multi-day period.

Day names may be written as a range. `monday-thursday` is Monday, Tuesday, Wednesday, and Thursday. `friday-tuesday` is Friday, Saturday, Sunday, Monday, and Tuesday. The range walks forward through the week and wraps. A range whose two ends are the same day, such as `friday-friday`, is a load error. Write `friday`.

`day` and `days` are the same constraint. `days` is the form the model stores. `day` is the convenience for a single weekday name, and it does not accept a range. Specifying both is a load error. Neither means every day.

Clock values are `HH:MM` or `HHMM`, written as quoted strings. The loader rejects anything else.

An unquoted `0700` is not a clock. In YAML 1.1 a leading zero marks octal, and a full parser produces the integer 448. PyYAML's `safe_load` does that. Unquoted `14:00` is sexagesimal, 14×60, and the same loader produces 840. Unquoted `7:00` produces 420. Unquoted `07:00` and `00:00` happened to stay strings in that loader, because the sexagesimal rule requires the hour to start with 1–9. That accident is not something to rely on. An integer that arrived from an unquoted clock is a load error, not a time.

## Quotas

A quota has a name, a rule set that decides whether traffic accrues, a grace for each side, and optional limits. Time is a duration such as `2h`, `120m`, or `7200s`. A bare number is rejected, so a bucket count cannot sneak in. Bytes use a case-sensitive suffix:

| Written | Bytes |
| --- | --- |
| `720b` | 720 |
| `720k` | 720 × 1,024 |
| `720M` | 720 × 1,024 × 1,024 |
| `720G` | 720 × 1,024³ |
| `720T` | 720 × 1,024⁴ |

`m` on a duration is minutes. `M` on a size is megabytes. `720MB`, `720KB`, and a bare number are rejected.

A quota does not have to set either limit. It can exist only as an accrual point for traffic its rule set accepts. A missing time limit is a time limit of zero. A missing byte limit is a byte limit of zero. `time_remaining` is true only when ended time is strictly under the time limit. `volume_remaining` is true only when stored bytes are strictly under the byte limit. Against a limit of zero both are false, including when nothing has accrued yet. A rule that checks the missing side always takes its false branch.

Rejecting that at load time, when a rule checks a side whose limit is zero, is worth doing but is not required. The runtime result is already a failed check.

The balance is stored per client group, including the implicit `default` group. Two client groups that reference one quota each have their own remaining time and bytes. A single shared pool is out of scope. The rule set on the quota is the place a pool can be introduced later, without putting one in now.

Balances reset at household-local midnight. Unused time and unused bytes do not carry into the next day. Other reset periods are out of scope.

### What accrues

Accrual is decided by the quota's rule set, evaluated on its own when an observation arrives.

The rule set returns a decision. For accrual that decision is read before the access path turns a top-level continue into a deny:

| Decision of the quota's rule set | Accrues to this client group's balance |
| --- | --- |
| `allow` | yes |
| `continue` | yes |
| `deny` | no |
| `redirect` | no |

`allow` and `continue` both accrue because a rule set can be used in two places. In the access path, `allow` authorizes and `continue` means the question is still open. On the quota, both mean "this traffic belongs here." A set that only classifies should continue when it matches and deny when it does not. A set that also authorizes may allow. If that same set is evaluated from the access rules, the allow authorizes the request as well as classifying it. That double duty is available on purpose. A classify-only set should not allow, or a caller that evaluates it will open the site.

Falling off the end of the quota's rule set is a continue, so it accrues. With omitted actions defaulting to continue, this is the sharp edge: a rule that names the entertainment sites and does not deny the false branch accrues school traffic too. The false branch continued, continue accrues, and there is no later rule inside that set to deny. A quota rule set that means "these sites and no others" denies the false branch, or ends in an explicit deny.

```yaml
entertainment_meter:
  - condition: site_group
    group: entertainment
    when_true: { action: continue }
    when_false: { action: deny, message: "Not entertainment." }
```

Several quotas may accrue the same observation. Each quota's rule set is evaluated separately. That is the explicit way to count one transfer toward two limits. Overlapping site patterns do not do it, because classification has already picked one site group.

Every observation has a client group and a site group, each of which may be the implicit `default`. Accrual uses that client group's balance. A quota rule set that continues for `default` records the traffic there. It does not disappear.

Denied and redirected access decisions produce no observation. The addon arms metering only for a flow it is forwarding. The proxy's own `403` or `302` is not upstream traffic and is not reported. A redirect causes the browser to make a new request. That request is classified and decided on its own. If it is forwarded, that later observation is what can accrue, and it accrues according to the quota rule sets and the new URL. The revision-task host accrues to a quota only when that quota's rule set says so for the task URL.

The measuring rules already built stay in force for whatever the rule set accepts:

- The day is cut into buckets of `bucket_length`. The default is five minutes. The length divides a 24-hour day and is aligned to local midnight. The length is household-wide.
- Time accrued is the sum of ended buckets. An open bucket does not add its length yet. A bucket keeps the length it was opened with. Changing the bucket length does not resize a quota or rewrite ended buckets.
- Bytes accrued include a bucket that has not ended. There is one byte meter, the bytes on the observation.
- Yesterday's usage is not counted today. Another client group's usage is not counted.
- School and any other traffic that no quota accepts is still stored against its client group and site group. The usage report does not depend on a quota existing.
- `time_remaining` and `volume_remaining` use the limits above. Grace is not added to either test. A new transfer is refused once the limit is reached, while the balance is still inside the grace. A zero limit refuses the new transfer immediately.

These do not break the finished accounting behaviour. The change is what an observation is filed under. It is filed once under the classified client group and site group, and again under each quota whose rule set returns allow or continue. Bucket length, ended buckets for time, open buckets for bytes, local midnight, and per-identity balances all stay.

### Grace

Each quota has a time grace and a volume grace. A new transfer is judged against the limit. Grace is not part of `time_remaining` or `volume_remaining`.

Built-in defaults are five minutes and `1M`. `1M` is 1,048,576 bytes. A household that wants different defaults sets `time_grace` and `volume_grace` once in the configuration. A quota may set either grace itself. The quota's value wins. An explicit zero is allowed and means the in-progress cut sits on the limit. A negative grace is a load error.

An allow records the flow. The record keeps the client group, the site group, and the URL from that approval, plus the earliest time a clock assumption on the walk runs out, plus a volume ceiling for each `volume_remaining` check whose true branch was taken. The decision document stays allow, deny, or redirect. The proxy sends the flow id. It does not learn the quotas or the windows.

These clock assumptions are the ones the walk actually evaluated:

- A `time_window`, whether it was true or false. A true window lasts until the period covering the request ends. A false window lasts until its next start. The household `time_grace` is added to that moment. The earlier of several windows is the one that is kept.
- A `tasks_required` check that was true. It lasts until the next local midnight, plus the household `time_grace`. A check that was false does not, because the count only goes up until the day resets.
- A `time_remaining` check that was true. It lasts until the bucket end at which ended time reaches that quota's limit plus that quota's own `time_grace`. The open bucket counts its full length at its end. That is the soonest a busy stream can exhaust the grace. A quiet gap makes the real moment later, and the next look moves the time forward. A check that was false does not schedule a quota deadline.

The stored time is the earliest of those. A `volume_remaining` check that was true stores the quota and the byte balance at its limit plus its volume grace. Bytes are not turned into a time, because they depend on how fast the transfer runs. The ceiling is the client group's balance, shared with its other transfers. A check whose true branch was not taken is not recorded. A quota the transfer accrues to, and that the access path did not require, does not cut it. A limit of zero never makes `time_remaining` or `volume_remaining` true, so that side is not a deadline and not a ceiling.

The access rules run when the request starts. They run again only when an observation finds the clock at the stored time, or a stored ceiling already reached. The re-walk uses the client group and the site group from the approval, and the policy loaded at that moment. The URL stays on the record. Allow replaces the time and the ceilings, and the transfer continues. Deny or redirect cuts. A redirect cannot be applied to a body that is already streaming, so it is a cut. A missing record is not a cut: a bypass and a report with no flow id both leave the transfer running.

The addon posts observations while bytes move, about once a minute and again when the flow ends. The observation response carries the cut. The service answers `{"action":"cut"}` on HTTP 200. The addon stops that transfer. The report sent as the flow ends can still say cut, and the addon does not tear down a transfer that has already finished. A timeout, a connection error, an empty body, or any response that is not that instruction leaves the transfer running. Failure is not a cut. A failed observation never changes a decision already taken. The decision path fails closed, and metering fails open.

A policy edit does not disturb a transfer until that stored time or a volume ceiling is reached. A change to who is in a client group, or which hosts are in a site group, is not applied to the transfer even then. Forcing every live transfer to classify and walk again on its next observation is left for later. A new request is still refused at the limit, without waiting for the grace, when a rule checks that side. During the grace, a new request already follows the flipped rule.

## Tasks

A task has a name, unique in the task namespace, the common attributes below, and a `body` with the settings its type needs. Each type's subsection after this one describes its body.

The same type may appear on more than one task. `parts-of-speech-1` and `parts-of-speech-2` keep separate sentences, dates, and attempt history. Attempts are rows, not part of this file. Editing a task does not delete them. S003.1 is the catalogue. S009 moves the household day off local midnight. Until then the day starts at midnight.

### Editing a task from the parent portal

Each task has a page in the parent portal, at `/parent/tasks/<name>`. Saving it rewrites that task in whichever file defines it, including a file brought in by `include`. Only the fields that changed are rewritten. The file's comments, its layout, and every other entry stay exactly as they were, and a cleared field is removed from the file. So the `decisions` service mounts the config directory writable. The other services still mount it read-only. Each file it writes keeps its owner and mode.

Before anything is written, the whole policy is checked with the changed file and with any spelling words already in their new pools, exactly as `dw check` would. A save that would not load is refused, and nothing changes. A good save is applied to every service as `dw reload` applies it, and committed to the config history as the signed-in parent, such as `2026-11-08 21:15 -0500 brett: saved task spelling`. A save first commits any hand edits it finds in the config directory, as `<time> hand edits found before a portal save`, when they pass the check, and refuses to save when they do not. A file changed on the server since the page was opened is not saved over: the page has to be reloaded first.

### Common task attributes

Every task takes these fields, whatever its type. Any other field on a task fails the load, and the previous policy stays in force.

| Field | Default | Value |
| --- | --- | --- |
| `type` | Required | The kind of task: `arithmetic`, `skip_counting`, `parts_of_speech`, `spelling`, or `parent_check`. |
| `group` or `groups` | Required | The client group the task is assigned to with `group`, or a list of one or more with `groups`. Use one of the two, not both. `default` means the implicit client group. |
| `pass_cooldown` | 1 | Household days after a pass before the task is offered again. A task is never offered again on the day it was passed, so 0 and 1 both mean the next day, and leaving it out is the same as 1. |
| `failure_cooldown` | No wait | Household days after a failure before the task is offered again. |
| `available_from` | Available now | The first household day the task can be offered in yyyy-mm-dd format. |
| `due_date` | No due date | The household day from which the task is required, until the group has passed it once, at any time. A practice pass does not count. Use yyyy-mm-dd format |
| `max_skips` | No limit | The number of skip days since the last pass at which the task becomes required. A skip is counted at most once per day. |
| `max_passes` | No limit | The maximum number of times that the task may be successfully completed by the group. Once the task has been completed enough times, it's educational value is assumed to have diminished to the point that it is not worth the child repeating it again. Practice passes do not count, and the task still opens from a bookmark. |
| `body` | `{}` | The settings for the task's type. A mapping. |

Dates are household dates written `2026-10-31`. Cooldowns, `max_skips`, and `max_passes` are whole numbers, zero or more. Leaving out an optional field leaves that rule off. The load fails for a missing required field, an unknown client group, a group listed twice, a date in another form, and a negative or fractional number. The error names the task and the field.

A cooldown of N days ends N day boundaries after the household day the attempt finished. 0 is the same day, and 1 is the next day. Only the group's last finished attempt counts. A pass starts `pass_cooldown`, a failure starts `failure_cooldown`, and an abandonment starts neither. A task passed today is not offered again today, whatever its `pass_cooldown`.

A skip day is a household day on which the group failed or abandoned the task, or started an attempt and left it unfinished. Several failures, abandonments, or unfinished attempts on one day are one skip day. An unfinished attempt counts for the day it started, from the next day on, whether or not he opens the task again, so closing the browser is not a way round `max_skips`. The count starts again from zero after each pass. The task becomes required once the skip days since the last pass, before today, reach `max_skips`, so a skip earlier today does not count until tomorrow. A `max_skips` of 0 makes the task required on every day it is offered.

Practice attempts, described below, count for none of these rules: they start no cooldown, are not skip days, do not count toward `max_passes`, and do not clear a due date.

A task is offered to a group only when it is assigned to that group, today is on or after `available_from`, the group has fewer than `max_passes` passes, the cooldown has ended, and the group has not passed it today. A task that is not offered is never required, so a task at its pass limit, still cooling down, or passed today, is not required by its due date or its skip days. A pass that finishes after `max_passes` was lowered is still recorded. A `max_passes` of 0 never offers the task.

`available_from`, `due_date`, `max_skips`, and `max_passes` do nothing on a task whose type is `parent_check`. That type is never required. Assignment and cooldowns still apply to it.

```yaml
tasks:
  term-4-spelling:
    type: spelling
    groups: [younger, older]
    pass_cooldown: 1
    failure_cooldown: 0
    available_from: 2026-10-05
    due_date: 2026-12-11
    max_skips: 2
    max_passes: 20
```

This spelling task is first offered on 5 October. After a pass it rests until the next day. After a failure it can be tried again at once. Two skip days since the last pass make it required, and from 11 December it is required until the group has passed it. After 20 passes it is not offered again. `younger` and `older` each keep their own cooldowns, skip days, and passes, so a pass by `older` does nothing for `younger`.

### Task sets

The rules use four sets of tasks, worked out for one client group on one household day.

- **Configured tasks** are every task assigned to the group, other than `parent_check`, whatever their dates, cooldowns, and limits.
- **Required tasks** are the offered tasks that are due and never passed, or whose skip days since the last pass have reached `max_skips`.
- **Potential tasks** are the other offered tasks. A task whose `available_from` is still in the future is never offered.
- **Available tasks** are the required tasks while there are any, and otherwise the potential tasks.

Each attempt is stored with the set its task was in when the attempt started: **required**, **potential**, or **practice**. Practice means the task was in neither the required set nor the potential set, such as a repeat of a task passed today, a task cooling down, a task at `max_passes`, or a task before its `available_from`. An attempt stays in the set it started in until it finishes, including through a reload. A parent check is stored in its own set, **parent check**.

### Today's score

The score is what `tasks_required` compares with `required`.

- A required pass scores one point on the household day it passed.
- A potential pass scores one point on the day it passed, but only while no task is required. While a required task is outstanding, the point waits. It counts once the required tasks have been passed, or are cooling down after a failure.
- No task scores more than once on a household day, whatever mix of required, potential, and practice passes it has.
- A practice pass scores nothing.
- Each parent check scores one point on the day it was recorded, even several in one day, and even while a required task is outstanding.

So he can do the easier tasks first. With parts of speech due today, spelling and addition not required, and `tasks_required` of 2, passing spelling and addition scores nothing yet. If parts of speech has `failure_cooldown: 1` and he fails it, it is no longer required today, and the score becomes 2. Passing it instead makes the score 3. Without a failure cooldown, a failed task stays required, and only parent checks add to the score that day. A reload that makes another task required stops the waiting points counting again until that task is cleared. Once every task he can do is passed or cooling down, nothing he does adds a point that day. Only a parent check does.

Attempts stored before task sets existed are treated as required. They count for cooldowns, skip days, `max_passes`, and due dates as they did, and a pass from earlier on the day of the upgrade scores one point.

### The picker and the selector

`/tasks/next` is the picker. It opens an available task. It prefers a task that has never been passed, then the one whose last pass is oldest. Candidates that tie rotate in name order. A redirect to `revision_task`, and "Next task" on the end screen of a quiz, go to the picker, so his revision keeps its variety. "Next task" is shown only while a task is available, and "All done for now" otherwise.

`/tasks/choose` is the task selector. It lists the available tasks by name, in the order the picker would try them, and each one opens that task. When exactly one task is available it opens that task straight away. Opening it does not move the picker's rotation. When nothing is available, the picker and the selector both say "There is nothing to revise right now." A task named `next` or `choose` is served at `/tasks/work/next` or `/tasks/work/choose`.

### Direct task URLs

Any configured task opens at its own URL, such as a bookmark of `https://garden:8084/tasks/spelling`, whatever the task sets say: a task passed today, cooling down, at `max_passes`, before its `available_from`, or optional while a required task is outstanding. The page serves its quiz requests and its audio too. A name that is not a task, a task assigned to another client group, and a `parent_check` task send him to the picker. Nothing a child sends records a parent check.

### Try a different task

"Try a different task" gives up the attempt and opens the selector, which lists every available task, including the one he just left. Spelling shows its missed words first, and "Continue" goes to the selector. A required attempt cannot be given up while its task is the only required task. The page says "This task has to be finished before another one." and the attempt stays in progress. A potential or practice attempt can always be given up.

### Coming back to a task he gave up

When he opens a task within an hour of giving it up, on the household day the attempt started, the given-up attempt carries on, however he opens it: the selector, the picker, "Next task", or a bookmark. His count, run, and earlier answers are as he left them, and the question showing when he gave up stays a timeout. The hour is the quizzes' idle limit, counted from the give-up. Only the task's newest attempt is carried on. A carried-on attempt is in progress again, so it is not a skip day, and it keeps the set it started in. Giving it up again starts the hour again. After the hour, or on a later day, a new attempt starts. A give-up that ended in a pass or a failure, which spelling and skip counting allow when closing the open question decides the result, is finished and is not carried on. The parent's attempt page lists each time he gave the attempt up and came back.

### An attempt belongs to one day

An attempt left in progress, for example when he closed the tab partway through, carries on only on the household day it started. When he opens that task on a later day, the old attempt is closed as unfinished and a new one starts in the set the task is in now. Like an abandonment, an unfinished attempt scores nothing, starts no cooldown, and does not count toward `max_passes`, and it is a skip day for the day it started. A quiz already on the screen when the day ends carries on, and a pass scores on the day it passes. `/parent/attempts` shows an attempt from an earlier day that was never finished as Unfinished.

### Parent checks and the attempts page

An authenticated parent records a `parent_check` pass for a client group from `/parent/attempts` in the parent portal. That pass scores one point and is listed with the group's other attempts. The child has no request that records one. For the chosen client group, `/parent/attempts` shows today's score, which is the one the rules use at that moment, the required tasks still outstanding, the potential tasks still available, and the potential passes waiting on the required tasks. Each attempt there, and the attempt page it opens, says whether it was Required, Potential, Practice, or a Parent check.

### Arithmetic tasks

A task with `type: arithmetic` is a timed quiz. Its `body` is checked when the file is loaded. A bad body fails the load, the previous policy stays in force, and the error names the task and the field.

| Field | Required | Value |
| --- | --- | --- |
| `operation` | Yes | `addition`. Subtraction, multiplication, and division arrive with S004.3 to S004.5. |
| `max_timeout` | Yes | The time for the first question. A duration greater than zero. |
| `min_timeout` | Yes | The time once `correct_answers_required - 1` answers are right. Greater than zero and no longer than `max_timeout`. |
| `correct_answers_required` | Yes | The number of right answers that pass the attempt. 1 or more. |
| `operands` | Yes | The weighted list the right-hand number `n` is drawn from, and `m` too when `first` is left out. |
| `first` | No | A weighted list for the left-hand number `m` only, such as a single `7` to drill the seven times table. An empty list is an error. |

A duration is a whole number with `h`, `m`, `s`, or `ms`, such as `10s` or `7500ms`. A bare number such as `10` is an error. Each list entry has a `weight`, a whole number 1 or more, and either one `value` or an inclusive `from` and `to`. Every number in a range gets the full weight. Operands are whole numbers, 0 or more. A value may appear once in a list. A repeated value, overlapping ranges, `from` above `to`, an entry with both `value` and `from`, and any other field are errors. `first` and `operands` are separate lists, so the same value may appear in both with different weights.

```yaml
tasks:
  sums:
    type: arithmetic
    group: younger
    pass_cooldown: 1
    body:
      operation: addition
      max_timeout: 10s
      min_timeout: 4s
      correct_answers_required: 20
      operands:
        - { value: 1, weight: 5 }
        - { value: 2, weight: 7 }
        - { from: 3, to: 9, weight: 10 }
        - { value: 10, weight: 5 }
```

`m` and `n` are drawn independently. A question is the ordered pair, so `6 + 7` and `7 + 6` are different questions. None of the last three questions in the attempt is asked again while another question is possible. After `k` right answers the time allowed is `max_timeout * (min_timeout / max_timeout) ^ (k / (correct_answers_required - 1))`. Wrong answers and timeouts do not shorten it.

The server issues each question, times it from that moment, and judges the answer. An answer it receives more than half a second after the time allowed is a timeout, whatever it says. When the timer bar runs out, the page sends what is in the box: the right answer is correct, and anything else is a timeout. Reaching `correct_answers_required` passes the attempt at that answer. Wrong answers never fail it.

Progress is stored on the attempt as each answer is recorded. A reload records the question that was showing as a timeout and returns to the start screen with the same count. Coming back more than an hour after the last page load, question, or answer starts the same attempt again from zero, with the task settings in force then. The earlier questions stay in the record as an expired run. A run in progress keeps the settings it started with when the policy file is edited.

The attempt `detail` holds `settings`, `runs`, `questions`, and `last_activity`. Each question has its `run`, `m`, `n`, the `question` as shown, the `expected` answer, his `answer`, the `outcome` (`correct`, `incorrect`, or `timeout`), `allowed_ms`, `taken_ms`, and the household-local `issued` time.

The quiz talks to the server by posting to its own task URL, `?do=visit`, `?do=question`, and `?do=answer`, so the rule that lets the task page load also lets the quiz run. A plain GET of the page changes nothing on the attempt. A revision redirect also catches the browser's background requests, such as favicons and telemetry, and a browser that follows one fetches the task page without showing it. Only the page's own `?do=visit`, sent when it loads in a tab, counts as a reload.

### Skip counting tasks

A task with `type: skip_counting` shows a row of numbers that count up or down by the same step, with some boxes left blank for him to fill in. Its `body` is checked when the file is loaded, the same way as an arithmetic body. Every field is optional.

| Field | Default | Value |
| --- | --- | --- |
| `sequence_length` | 8 | Numbers in each sequence, 4 to 12. |
| `completed` | 3 | Numbers filled in, 2 to `sequence_length - 1`. |
| `consecutive` | `true` | When true, at least two filled-in numbers are next to each other. |
| `multiples_only` | `false` | When true, every number is a multiple of the difference's size, for a difference that does not set its own. |
| `difference` | 2, 5, 10, 25, 100, and their negatives, weight 1 each, with the maximums below | The weighted list of common differences. A negative difference counts down. |
| `minimum_value` | 1 | The lowest number in a box, for a difference that does not set its own. It may be zero or negative. |
| `maximum_value` | 999 | The highest number in a box, for a difference that does not set its own. Greater than `minimum_value`. |
| `timeout` | `3m` | The time for each question, a duration as for arithmetic. |
| `correct_answers_required` | Worked out below | The points needed to pass. 1 or more. |
| `minimum_questions` | `correct_answers_required` | Questions he must finish before the attempt can pass or fail early. |
| `maximum_questions` | Not set | Questions after which the attempt ends. Without it, the attempt cannot fail. |

When `correct_answers_required` is left out, it is the larger of 8 and `ceil(0.8 × minimum_questions)`, or 8 when `minimum_questions` is also left out, and no more than `maximum_questions`. `minimum_questions` then defaults to `correct_answers_required`.

`difference` entries follow the arithmetic `operands` rules, except that values may be negative and zero is not allowed. A range that includes 0 is an error, so both directions are two ranges, such as `{ from: -5, to: -1 }` and `{ from: 1, to: 5 }`. An entry may also set its own `minimum_value`, `maximum_value`, and `multiples_only`, which replace the body's for every difference in that entry, such as `{ value: 2, weight: 1, maximum_value: 99 }` or `{ value: 25, weight: 1, multiples_only: true }`. Any of the three an entry leaves out comes from the body. Its maximum must be greater than its minimum. An entry's range may go outside the body's. Each box is wide enough for the longest number any difference allows.

The default list caps counting by 2 at 99, by 5 at 199, and by 10 at 499, in both directions. Counting by 25 and 100 uses `maximum_value`. Counting by 25 and -25 always starts on a multiple of 25. The other defaults use the body's `multiples_only`. When `maximum_value` is lower than a cap, the lower one wins, so a parent who narrows the range is never overridden by a default they did not write. Every default difference uses `minimum_value`. A `minimum_value` at or above a cap fails the load, and the error says to write a difference list. The load also fails when `minimum_questions` or `correct_answers_required` is more than `maximum_questions`. It fails when one difference allows fewer than 3 distinct sequences in its range, with the error naming that difference. It fails when all the differences together allow fewer sequences than `maximum_questions`, or than the larger of `correct_answers_required` and `minimum_questions` when there is no maximum. Counting by 100 with 8 numbers between 1 and 999 starts anywhere from 1 to 299. With `multiples_only` it can only start on 100 or 200, so the load fails.

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
        - { value: 2, weight: 3, maximum_value: 60 }
        - { value: 5, weight: 2 }
        - { value: -2, weight: 3, maximum_value: 60 }
        - { value: -5, weight: 2 }
      minimum_questions: 10
      maximum_questions: 15
      timeout: 2m
```

Each question draws a difference, leaving out the differences of the last two questions, and the rest keep their weights. With two differences they alternate. With one, every question uses it. The start is drawn evenly from every start that keeps the sequence in range, leaving out the last two starts used with that difference. The filled-in positions are drawn evenly from every set that meets `consecutive`.

He has three tries. A right answer scores 1 point on the first try, 0.5 on the second, and 0.25 on the third. After a wrong try the page says how many boxes are wrong. After the second, the boxes he got right lock in black and the wrong ones turn red. A wrong third try scores 0 and shows the answer for 10 seconds. Enter skips ahead after 3 seconds. The timer runs for the whole question and is not reset by a try. When it runs out, the page sends what is in the boxes: every box right scores for the try he was on, and anything else is a timeout. The server judges each try from its own clock, with the same half-second allowance as arithmetic, and refuses a fourth try or a try with a blank box.

The attempt passes when his points reach `correct_answers_required` and at least `minimum_questions` questions are finished. With `maximum_questions`, it fails when that many are finished without a pass, or once at least `minimum_questions` are finished and full marks on every question left could not reach the points. A failure uses `failure_cooldown` and counts as a skip day. Without `maximum_questions` the attempt never fails. A question left showing on a reload or a give-up is a timeout. When that is what passes or fails the attempt, the pass or failure is recorded rather than an abandonment.

The attempt `detail` holds `settings`, `runs`, `last_activity`, and `questions`. Each question has its `run`, `difference`, `start`, the full `sequence`, the `filled` positions, every try in `tries` (his `entries` in the blank boxes left to right, the number `wrong`, whether it was `expired`, and `received_ms` from issue), the `outcome`, the `correct_try`, the `points`, `allowed_ms`, and the household-local `issued` time. Resume and expiry work as for arithmetic.

### Parts of speech tasks

A task with `type: parts_of_speech` lists sentences, and for each one says which of its words are nouns, verbs, adjectives, or any other part of speech the parent wants him to practise. Its `body` is checked when the file is loaded. On the task page he drags the words of each sentence into a table with one row per part of speech.

| Field | Default | Value |
| --- | --- | --- |
| `sentences` | Required | A list of one or more sentences. There is no upper limit. |
| `timeout` | `90s` | The time for each sentence that does not set its own. A duration greater than zero, as for arithmetic. |
| `correct_answers_required` | 70% of the number of sentences, rounded up | The points needed to pass. A whole number from 1 to the number of sentences. Each sentence is worth up to 1 point. |

Each sentence has these fields.

| Field | Default | Value |
| --- | --- | --- |
| `sentence` | Required | The sentence text, with at least one word in it. |
| `parts` | Required | A mapping from part of speech name to a list of words from the sentence. At least one part. |
| `timeout` | The body's `timeout` | The time for this sentence only, so a long sentence can be given longer. |

```yaml
tasks:
  parts-of-speech-1:
    type: parts_of_speech
    group: younger
    pass_cooldown: 21
    failure_cooldown: 1
    body:
      sentences:
        - sentence: "The quick, brown fox jumped over the lazy dog."
          parts:
            noun: [fox, dog]
            verb: [jumped]
            adjective: [quick, brown, lazy]
        - sentence: "Dry the dishes with a dry towel."
          timeout: 2m
          parts:
            verb: ["dry[1]"]
            noun: [dishes, towel]
            adjective: ["dry[2]"]
```

The fox sentence gets the default 90 seconds and the dry sentence 2 minutes. With two sentences and no `correct_answers_required`, he needs 2 points to pass. The default is worked out in whole numbers: 10 sentences need 7 points, 5 need 4, 3 need 3, and 1 needs 1.

Part names are the parent's choice, such as `noun`, `proper noun`, or `Doing words`. Each is a row of his table, shown as written and in the order written. A name is at most 20 characters, and two names in one sentence may not differ only in case, such as `Noun` and `noun`. Each sentence lists only the parts it asks about, so one sentence can ask for nouns and verbs and the next for adjectives and adverbs. Words left out of the table belong in no row, and he should leave them out too. A part may be `[]`, which shows a row where nothing belongs. A sentence must still list at least one word somewhere.

A word is a run of letters and digits. An apostrophe (`'` or `’`) or a hyphen with a letter or digit on both sides joins the runs either side into one word, so `don't`, `o'clock`, `well-known`, and `café` are each one word. Spaces, commas, full stops, quotation marks, dashes, and an apostrophe at the start or end of a word, as in `the dogs' bowls`, are punctuation. Punctuation is shown in the sentence as written but is never sorted. Words are compared without regard to case, and `’` is the same as `'`, so `Dry` at the start of a sentence and `dry` later on are two occurrences of the same word, and `don't` in the table matches `don’t` in the sentence.

An entry in a part's list is one word from the sentence, optionally followed by occurrence numbers in square brackets. Occurrences count from 1 in sentence order. `dry` is the same as `dry[1]`. `dry[2]` is the second `dry`, and `the[1,2]` puts both occurrences of `the` in one part. Spaces around the word, the brackets, and the numbers are ignored. Each occurrence may be listed once in the whole table, so a word that appears twice can be listed at most twice. Phrases such as `ice cream` cannot be one entry. List the words separately or leave them out.

In YAML, quote an entry with brackets or a comma inside `[...]`, as in `["dry[1]"]` or `["the[1,2]"]`. A block list needs no quotes:

```yaml
          parts:
            verb:
              - dry[1]
```

YAML reads an unquoted `yes`, `no`, `on`, `off`, or number as something other than text, so write `["yes"]` or `["3"]` for those words. A part with nothing after it, such as `adverb:` on its own, is not a list. Write `adverb: []`.

The load fails, and the previous policy stays in force, for any of these. The error names the task, the sentence number, and the part and entry where there is one, such as `task 'parts-of-speech-1': body.sentences entry 2: parts.adjective: "dry[3]": the sentence has only 2 of "dry"`.

- A missing or empty `sentences`, a sentence without `sentence` or `parts`, an empty `parts`, a sentence with no words in it, or a sentence whose parts are all empty.
- An unknown field on the body or on a sentence, or a field of the wrong type, including a part that is not a list.
- An entry that is not text, that is not a single word, or whose word is not in the sentence.
- An occurrence number that is zero, not a whole number, larger than the number of times the word appears, or repeated in one entry, such as `dry[1,1]`.
- Malformed brackets, such as `dry[]`, `dry[1-2]`, `dry[1`, `dry]1[`, or `[1]` with no word.
- One occurrence listed twice, in one part or in two, including `dry` and `dry[1]` together. The error names every part that lists it.
- A part name that is empty, longer than 20 characters, or the same as another in that sentence apart from case.
- A `timeout` of zero or a bare number, on the body or on a sentence.
- A `correct_answers_required` that is not a whole number from 1 to the number of sentences.

A run asks every sentence once, in an order shuffled when the run starts. The start screen shows his points out of the number of sentences, the pass mark, and the sentence number, such as "0 / 10 points", "7 points to pass", and "Sentence 1 of 10". The question screen says "Sort the words into the table" above the sentence in large text, with the table, a feedback line, a large Submit button, and a timer bar under it. The table's rows are the sentence's parts, in the order written.

He sorts with the mouse. An unsorted word turns light grey under the pointer. Pressing on it and moving starts a drag: a copy follows the pointer, the word stays shaded in the sentence, and the row under the pointer, label included, turns light blue. Dropping on a row adds the word to the end of that row's comma-separated list. Dropping anywhere else flies the copy back to its word in about 0.6 seconds. A sorted word does not highlight in the sentence and can only be moved from its cell: to another row, back to its own row (nothing changes), or out of the table, which unsorts it. Two occurrences of a word, such as the two `dry`s, are separate words. There is no keyboard way to sort a word.

Submit or Enter, with the focus anywhere, sends the table. Neither does anything while the table is empty, while it is the same as his last wrong try, during a drag or a flight, while a try is waiting for the server, while "Correct!" or "Next Question" is showing, or while the "Try a different task" confirmation is open. The server refuses those same submissions without using a try, and also refuses a word that is not in the sentence, a part that is not in its table, a word in two parts, and a try for a sentence that is not open.

A wrong word is one he sorted into a different part from the one the task lists, including a word the task lists under no part. A missed word is one the task lists that he has not sorted. A try with neither is correct and scores 1 point on the first try, 0.5 on the second, and 0.25 on the third. It shows "Correct!", plays a `correct/` sound, and moves on after about a second. A wrong first or second try plays an `incorrect/` sound and says how many words are in the wrong row and how many he missed, such as "2 words are in the wrong row. You missed 1 word. Try again." After the first try it does not say which. After a wrong second try, every wrong word turns red where he can pick it up: a word in the wrong row in its cell, and a missed word in the sentence. Words he sorted correctly stay black and can still be moved. A red word stays red while dragged, turns royal blue when dropped anywhere other than where it was on the second try (a row, or back in the sentence), and is red again if put back there. A black word stays black wherever it goes. A reload brings the red words back. A wrong third try scores 0, plays an `incorrect/` sound, and shows "Not quite. Here is the answer."

When a sentence finishes wrong, on a wrong third try or a timeout, the table shows the answer: each row lists the words that belong in it, in sentence order, in black text on pale green for a word he had in that row, pale red for a word he had in another row, and pale orange for a word he did not sort. A word he sorted that belongs in no row, such as `the` under `noun`, is struck through on pale red at the end of the row he put it in. The sentence goes back to plain black.

Each sentence's deadline is fixed when the server issues it: its `timeout` plus the half-second network allowance. Tries and reloads do not move it. When the timer bar empties, the page sends the table as it stands, even when it is empty or unchanged, and a word being dragged goes back where it came from. A correct table then scores the points for the try he is on. Anything else is a timeout: 0 points, a `timeout/` sound, "Time ran out. Here is the answer.", and the answer in the table. A try the server receives after the deadline is a timeout whatever it holds, and is still recorded. After "Not quite." or a timeout, nothing can be dragged, the timer bar is hidden, and "Next Question" replaces Submit. It is greyed out for 3 seconds, then the button or Enter moves on. Left alone, the next sentence comes after 15 seconds.

A page load does not close the open sentence. After a reload before its deadline, Start brings back the same sentence with the time left, the tries used, his last submitted table, and the message from his last wrong try. Sorting he had not submitted is lost. Coming back after the deadline closes it as a timeout, and the next sentence follows. Coming back more than an hour after his last activity starts a new run on the same attempt, as for arithmetic, with a new order. A give-up that S003.2 allows closes the open sentence as a timeout and is always an abandonment, whatever his points and on whichever sentence. A give-up S003.2 refuses leaves the open sentence open with its deadline still running.

The run ends after the last sentence, even when a pass is out of reach. Points at or above `correct_answers_required` are a pass, which counts toward today's revision and shows "Well done". Anything less is a failure: the failure cooldown and a skip day apply, and the page says "The sentences are finished" with his points and the pass mark, such as "6.25 / 10 points. You needed 7 to pass."

The page is told the sentence as words and the text between them, the part names, the try number, the time allowed and left, and the progress. While the sentence is open it is never told which part a word belongs in. Only the response to a wrong second try, and the sentence brought back after one, say which words are wrong and missed (`wrong_words` and `missed_words`). Only a finished wrong sentence's response carries the `answer`: for each word, the `part` it belongs in, the part he had it in (`placed`), and `had` (`right`, `other`, `missed`, `extra`, or `null`). The attempt `detail` holds `settings`, `runs` (each with its sentence `order`), `last_activity`, and `questions`. Each question has its `run`, its `index` in the task's `sentences`, the `sentence`, its `parts` in order, the `words` with the `part` each belongs in (or `null`), every try in `tries` (his `placements`, the `wrong` and `missed` counts, the `wrong_words` and `missed_words` by position, whether it was `expired`, and `received_ms` from issue), the `outcome`, the `correct_try`, the `points`, `allowed_ms`, and the household-local `issued` time. Attempt details keep their keys in the order written, so the stored settings keep the rows in order.

### Spelling tasks

A task with `type: spelling` plays a recorded word, and he types it into a large box. The words are audio files the parent puts in directories under the household data directory. On the host that is `DAYWARDEN_DATA_DIR` in `.env`, `$HOME/daywarden` by default. It is mounted into the `decisions` container at `/var/lib/daywarden/data`, writable so that the parent portal's task page can move and retire words. Everything the service moves or creates there keeps the host user as its owner. The `observations` container does not mount it, so it checks the spelling fields but not the recordings. `make up` creates it when it is missing. A plain `docker compose up` refuses to start without it rather than creating it owned by root. Every field is optional.

| Field | Default | Value |
| --- | --- | --- |
| `current_dir` | `spelling/current` | The words he is learning now, relative to the data directory. |
| `revision_dir` | `spelling/revision` | Older words for revision, relative to the data directory. |
| `alphabet_dir` | `spelling/alphabet` | Letter recordings for practice mode, relative to the data directory. |
| `attic_dir` | `spelling/attic` | Retired words, relative to the data directory. Never asked. It may be missing. The parent portal creates it the first time it retires a word. |
| `timeout` | `30s` | Typing time for each word, not counting audio. A duration as for arithmetic. |
| `maximum_replays` | 3 | "Repeat word" clicks allowed per word. 0 or more. |
| `maximum_sentence_plays` | 2 | "Use in a sentence" clicks allowed per word. 0 or more. |
| `current_required` | Every word in `current_dir` | Current words he must spell right. 0 up to the number of current words. |
| `revision_required` | 5, or every revision word when there are fewer | Revision words he must spell right. 0 up to the number of revision words. |
| `letter_pause` | `0ms` | Practice mode's pause between letters while spelling a word out. A duration, `0ms` or more. |
| `word_pause` | `300ms` | Practice mode's pause between the word and its spelling, both ways. A duration, `0ms` or more. |

Each word is one recording named `<word>.<ext>`, spoken clearly on its own, with an optional `<word>.sentence.<ext>` of a sentence that uses it. Audio is `.mp3`, `.wav`, `.ogg`, `.opus`, or `.m4a`, and the two files of a word may use different formats. The file name is the spelling: letters, `-`, and `'`, up to 22 characters. Homographs add a number, such as `read.1.opus` and `read.2.opus`, each with its own sentence clip. Both are spelled `read`. Names are matched without regard to case, and the word clip's casing is the one shown. Hidden files and other files, such as notes, are ignored. `bin/cut-clips` cuts one recording of a whole list into files named this way. See [Recording spelling clips](../README.md#recording-spelling-clips).

```yaml
tasks:
  weekly-spelling:
    type: spelling
    group: younger
    pass_cooldown: 1
    body:
      timeout: 25s
      current_required: 8
      revision_required: 4
```

The alphabet directory holds one recording per character, named for it: `a.<ext>` to `z.<ext>`, `dash.<ext>` for `-`, and `apostrophe.<ext>` for `'`, matched without regard to case. Every letter is required. `dash` and `apostrophe` are required only when a word in either pool uses that character. Other files are ignored.

The load fails, naming the task and the field or the file, for an unknown field, a bare-number or zero `timeout`, a bare-number or negative `letter_pause` or `word_pause`, a directory path that is absolute or uses `..`, a directory the body names that does not exist, a badly formed audio file name, two word clips or two sentence clips for one word (`rope.opus` and `rope.mp3`), a sentence clip with no word clip, a word in more than one of the current, revision, and attic pools (`attic_dir: rope.opus is also in current_dir; a word belongs to one pool`), a target above its pool's size, no work at all (no current words and `revision_required` of 0), a missing alphabet directory, a character with no recording, or two recordings of one character (`a.opus` and `a.mp3`). A default word directory that does not exist is an empty pool. The attic is read with the same file-name rules as the other two pools, and words are compared by entry key, ignoring case, so `read.1` and `read.2` may be in different pools.

The directories are read when the policy loads and again whenever a run starts, so new recordings are used from the next run without a restart. Recording lengths are kept in memory and read again only for a new or changed file. A run keeps a copy of its words, targets, and queue on the attempt, so a file changed during a run does not disturb it. A word moved to the other pool or retired to the attic during a run still plays for the rest of that run, because a clip not found in the pool the run expected is looked for in the other pool and the attic. A directory that goes bad after the load keeps the last list that read cleanly, and the service logs why.

A run asks every current word and `revision_required` revision words drawn at random, shuffled together. A right spelling, ignoring case and spaces at either end, scores for its own pool. A missed current word goes to the back of the queue while the current score is short of `current_required`. A missed revision word, while the revision score is short, is replaced at the back by a different revision word that is not right yet and not already waiting, or by the same word when there is no other. A word that will come back is not shown on screen. A word that will not come back is shown with the feedback. The attempt passes when every current word has been asked and both targets are met, so a target of 7 out of 10 still asks the last three words. There is no failure.

The word plays when the question appears. The box and the two buttons stay disabled, and the timer does not start, until it ends. Each "Repeat word" or "Use in a sentence" pauses the timer, keeps what he has typed, and disables the controls while the clip plays. A button turns grey once its limit is reached, and for the sentence when the word has none. The server allows the word clip, `timeout`, and half a second for the network, and adds a clip's length for each replay it accepts. Every play, the first included, also gets 1.5 seconds for the browser to fetch and start the clip, because the page's timer only runs after the clip has finished. It refuses a replay past the limit. An answer after that time is a timeout. When he passes or gives up, any words he missed in the attempt are listed in three columns until he presses "Continue" or Enter.

A small "Practice" button sits at the bottom right of the start and question screens. It asks "Start practice mode? Your current quiz progress will be reset." While it asks, the question's timer keeps running. "Yes, practice" closes any question showing as a timeout and starts a new run on the same attempt, so both scores go back to zero. Earlier answers stay on the attempt. Practice is always allowed, even for a task he has to finish. It never abandons the attempt, records a skip day, or passes the attempt. Practice walks every current word, plus each revision word he missed anywhere in the attempt, once each in random order. Each word is shown in large letters with "Practice: 3 of 12" at the top. The page plays the word, then spells it letter by letter, three times, saying the word before and after each spelling. `letter_pause` (no pause by default) separates the letters, and `word_pause` (300 ms by default) separates the word and its spelling, both before and after. A change to either takes effect from the next time he enters practice. "Next" stays grey until the sequence ends. Then "Say and spell the word until you know it." appears and "Next" turns blue and takes the focus, so Enter moves on. The last word's button says "Start quiz", which starts the new run's first question. A reload during practice returns to the start screen of the new run. "Try a different task" works as it does elsewhere.

Audio is served from `<task URL>/audio/<token>.<ext>` and `<token>.sentence.<ext>`, so the rule that lets the task page load lets the audio through. The token is 32 characters whatever the word, and only the server can read the word back from it. Letter clips are served from `<task URL>/audio/alphabet.<file>`.

The attempt `detail` holds `settings`, `runs`, `last_activity`, and `questions`. Each run also records `current_total`, `current_required`, `revision_required`, its `words`, and its `queue`. A run started by practice also records the words practised, in order, as `practice`. Each question has its `run`, entry `key` (such as `read.1`), the `word`, the `pool`, whether a `sentence` clip was available, `word_replays`, `sentence_plays`, his `answer`, the `outcome`, whether a missed word was `requeued`, `timeout_ms`, `allowed_ms` including audio, `received_ms` from issue, and the household-local `issued` time. Resume and expiry work as for arithmetic.

### Sound sets

Each outcome plays one sound, chosen at random from that outcome's directory in the policy image: `policy/static/sounds/correct/`, `incorrect/`, and `timeout/`. Every audio file in the directory is equally likely. Audio is `.mp3`, `.wav`, `.ogg`, `.opus`, or `.m4a`. Any other file, such as an attribution note, is never played. Adding or removing a sound is a file change in that directory. It takes effect when the policy image is rebuilt and the service restarts. A set with no audio plays nothing for that outcome, and the service logs a warning naming that set when it starts. The files are served at `/static/sounds/<set>/<file>` on the task host, which the proxy forwards without a decision like the task pages. A new sound stops the one before it. The page has no mute control.

## Rule sets

A rule set has a name, unique in the rule-set namespace, and an ordered list of rules. `entry` names the rule set where access decisions start. The name is required. If it is missing, or it does not name a rule set, the load fails.

Any rule set can be evaluated with no parent. The access path does that for `entry`. A quota does it for its own rule set, and then interprets the decision with the accrual table instead of the access rule below.

## Rules

A rule has a `condition`, the parameters of that condition, and two optional actions, `when_true` and `when_false`. An omitted action is `continue`.

Every rule returns one decision:

| Decision | Meaning |
| --- | --- |
| `continue` | Still unsure. If another rule follows in this set, evaluate it. If this was the last rule, the set's decision is continue. |
| `allow` | The request is allowed. Terminal. |
| `deny` | The request is refused, with a message. Terminal. The message is required. |
| `redirect` | The request is redirected. The location is an absolute `http` or `https` URL, or the token `revision_task`. Terminal. |
| `evaluate` | This rule's decision is the decision of the named rule set, or of the inline list. One of those, not both. |

`allow`, `deny`, and `redirect` are terminal wherever they are produced. A later rule does not run. A parent does not run. `evaluate` substitutes the child set's decision, including when that decision is continue. A child continue is acted on like any other continue: the next rule in the parent set runs, or the parent set itself returns continue when there is no next rule.

A continue that reaches a caller with no parent becomes a deny on the access path. The message is "No rule granted access." That applies to `entry` and to any other rule set evaluated as an access decision with no parent. A continue returned to a parent is not that case. The parent still has rules of its own, or itself returns continue to its parent.

A quota's evaluation is not an access decision. It uses the accrual table, so a continue stays a continue and accrues.

There is no `on_fallthrough`. A shared set that allows school and otherwise defers is a set whose false branch continues. The caller writes whatever should happen next after the `evaluate`. A caller that wants an allow when the shared set did not decide puts that allow on the following rule.

```yaml
allow_school:
  - condition: site_group
    group: school
    when_true: { action: allow }

# when_false is continue. The caller proceeds.
- condition: always
  when_true: { action: evaluate, ruleset: allow_school }
- condition: time_window
  window: younger_evening
  when_true: { action: evaluate, ruleset: younger_evening_sites }
```

If `allow_school` allows, the request is allowed. If it continues, `younger_evening` runs. If that continues as well and nothing follows, the set returns continue. At the top of the access path that continue is a deny.

An inline list has no name of its own. Logs identify it by the path of the rule that contains it. A named set is how a list is defined once and used in more than one place. A cycle in `evaluate` is a load error.

`revision_task` is replaced with a concrete absolute URL before the answer leaves the policy service. The scheme is always `https`. The host is the household `hostname`, or the hostname of the machine running Compose when that is left out. That name is read from the machine's `/etc/hostname`, not from the container's own hostname. The port is the household `port`, or the published policy port (`POLICY_PORT`) when that is left out. Port 443 is left off the URL. The URL is the task picker, `https://<hostname>:<port>/tasks/next`, which opens an available task for the client group, or says there is nothing to revise. The addon sees only `allow`, `deny`, or `redirect`.

The policy service has no special handling for its own pages. The proxy forwards every request for a name in `PARENT_NAMES`, other than `localhost`, `127.0.0.1`, and `::1`, without asking for a decision, the same as a host in `config/bypass.txt`, and adds the child's address as `X-Daywarden-Client`, so the task pages know which child is asking. That holds at any time, including at bedtime, and while the policy service is down. The proxy reads `PARENT_NAMES` when it starts, so list the same names in `bypass.txt`, which it reads on every request. `dw check` warns about a name in `PARENT_NAMES` that `bypass.txt` does not match. A name the browser uses for the policy server that is in neither list is judged by the rules like any other URL, and a redirect to `revision_task` then loops. That name is missing from the certificate too, so add it to both. The policy file does not set a `revision_task` URL. A file that still sets one fails to load. Rules still redirect to the token `revision_task`.

### Back to the page he was sent away from

The proxy sends the request's `Sec-Fetch-Dest` and `Accept` headers with each decision request, as `sec_fetch_dest` and `accept`, when the browser sent them. The decision log records them with the rest of the request.

A request is remembered for its source address when all of these hold:

- The rule that decided it redirected to `revision_task`. A redirect to an absolute URL written in the policy file, an allow, and a deny are not remembered and do not change what is remembered.
- The method is `GET`.
- It is a page load. `Sec-Fetch-Dest: document` is a page load, and any other `Sec-Fetch-Dest`, such as `image`, `script`, `empty`, or `iframe`, is not. A request with no `Sec-Fetch-Dest` is a page load when its `Accept` header includes `text/html`. Browsers leave `Sec-Fetch-Dest` off plain `http` requests, so those are judged by `Accept`.
- The URL is not on the policy server, so the task pages and `/tasks/next` are never remembered, even when one task page is redirected to another.

The address is normalized the way client groups are matched, and each address keeps one URL: a later remembered request replaces it. The client group does not matter, so two computers in one group, or a computer in the `default` group, each have their own. The URL, the household day it was remembered on, and the time are stored in the policy database (`return_pages`), so a restart does not lose them. Hosts on the proxy bypass list never reach the policy service, so they are never remembered.

When an attempt passes on a quiz page, the service takes the URL remembered for the address the task page sees, which is `X-Daywarden-Client` when the proxy forwarded the page. A URL remembered on an earlier household day is not used. It decides that URL for that address with the same rules the proxy would use at that moment. An allow is sent back with the pass, and the "Well done" screen shows "Going back to <host>", a "Go now" button, and "Next task" when another task is available. The page opens the URL in the same tab after 5 seconds, or at once on "Go now" or Enter. "Next task" stops the countdown. When the URL would be redirected or denied, or nothing is remembered, "Well done" is unchanged. On a spelling pass with missed words, the countdown starts when "Continue" brings up "Well done". A failure, a give-up, and a `parent_check` pass forward nothing, and they leave the URL in place.

The return is an ordinary request through the proxy, decided like any other. When the proxy allows exactly the remembered URL for that address, by the forward or because he opened it himself, the URL is forgotten. Opening it from "Well done" again needs a new redirect.

### Conditions

| Condition | Parameters | True when |
| --- | --- | --- |
| `time_window` | `windows`: one or more time-window names | The request time falls inside any named window. |
| `site_group` | `groups`: one or more site-group names | The request's site group is one of those names. |
| `client_group` | `groups`: one or more client-group names | The request's client group is one of those names. |
| `tasks_required` | `required`: a whole number, zero or more | The classified client group's passes for the local date are at least `required`. The `default` client group has its own count. |
| `time_remaining` | `quota`: a quota name | That client group's ended time on the quota is strictly under the quota's time limit. A limit of zero is never under. |
| `volume_remaining` | `quota`: a quota name | That client group's stored bytes on the quota are strictly under the quota's byte limit. A limit of zero is never under. |
| `always` | none | Always. |

`group` is accepted where `groups` is stored, and `window` where `windows` is stored. Each is the convenience for a single name. The model stores a list. Specifying both the singular and the plural is a load error. An empty list is a load error.

`tasks_required` compares today's score, described under [Today's score](#todays-score), with `required`. The score is read from the attempt rows for this client group whose outcome is `pass` and whose finish falls on the household day. The count resets at local midnight. Another client group's passes do not count. Failure and giving up do not increment it. A required count of zero is true for every client group, including `default`.

There is no per-weekday count. A different count on a different day is a different rule under a different window. Per-weekday targets inside a spelling task stay on that task.

A parameter that belongs to another condition is a load error. An unknown condition is a load error. An unknown name is a load error.

On an `always` rule the false action is never used. Leave it out and it defaults to continue.

## Proxy configuration

`proxy_configuration` is optional, and may be in any file of the configuration, once. It decides which hosts the proxy auto-configuration file sends direct, so a browser opens them without the proxy:

```yaml
proxy_configuration:
  direct:
    local_subnets: false
    local_domains: false
    extra: ["*.home.arpa", 10.8.0.0/16]
```

`direct` holds five switches, `localhost`, `plain_host_names`, `policy_server`, `local_subnets`, and `local_domains`, each `true` or `false`, and an `extra` list. A switch left out is on, and the whole section left out means every switch on and no `extra`. Each `extra` item is a host name, a host glob with `*` and `?` as in `config/bypass.txt`, a domain written with a leading dot that also covers every name under it, an IPv4 or IPv6 address, or a subnet in CIDR form. An unknown key, a switch that is not `true` or `false`, and an item that is none of those forms, such as `10.8.0.0/33` or `http://nas/`, are load errors, listed with the rest. What each switch covers is in [docs/child-computer.md](child-computer.md#proxy). The decisions never see a direct host, so no rule applies to it.

## Decision log

A decision log line names the client group and the site group, each of which may be `default`, and names the rule set and rule index that produced the decision. Inline sets use their path. The line also carries the allow, deny, or redirect that was returned to the addon. When a top-level continue became a deny, the line says that.

# Illustration

This sketch is the shape, not a proposed household policy. The younger client group gets reading before school and reading plus YouTube in the evening. The older client group has a longer weekend span and a larger quota. An address in neither group is the client group `default`. Nothing in `household` grants access to `default`, so those requests fall off the end and are denied. Sites that match no configured pattern are the site group `default`, and the same fall-through denies them unless some rule that did run allows every site.

```yaml
entry: household
timezone: America/Toronto
# The name external clients use to open the policy server.
hostname: policy.home
# Set port when a reverse proxy changes the port. The default is the published policy port.
bucket_length: 5m
time_grace: 5m
volume_grace: 1M

client_groups:
  younger:
    addresses: ["younger.lan"]
  older:
    addresses: ["older.lan", "older-tablet.lan"]

site_groups:
  school:
    priority: 10
    patterns:
      - classroom.google.com
      - docs.google.com
  reading:
    priority: 20
    patterns:
      - "*.wikipedia.org"
      - "*.wikimedia.org"
  entertainment:
    priority: 30
    patterns:
      - "*.youtube.com"
      - youtube.com
      - youtu.be

time_windows:
  younger_before_school:
    periods:
      - start: "07:00"
        end: "08:30"
        days: monday-friday
  younger_evening:
    periods:
      - start: "15:00"
        end: "18:00"
        days: monday-thursday
      - start: "12:00"
        end: "18:00"
        days: friday-sunday
  older_weekend:
    periods:
      - start: "14:00"
        end: "18:00+2"
        day: friday
  weekday_bedtime:
    periods:
      - start: "20:00"
        end: "07:00"
        days: monday-thursday

quotas:
  younger_entertainment:
    time: 30m
    ruleset: entertainment_meter
  older_entertainment:
    time: 2h
    ruleset: entertainment_meter

rule_sets:
  household:
    - condition: client_group
      group: younger
      when_true: { action: evaluate, ruleset: younger }
    - condition: client_group
      group: older
      when_true: { action: evaluate, ruleset: older }

  entertainment_meter:
    - condition: site_group
      group: entertainment
      when_true: { action: continue }
      when_false: { action: deny, message: "Not entertainment." }

  allow_school:
    - condition: site_group
      group: school
      when_true: { action: allow }

  younger:
    - condition: always
      when_true: { action: evaluate, ruleset: allow_school }
    - condition: time_window
      window: younger_before_school
      when_true: { action: evaluate, ruleset: younger_reading }
    - condition: time_window
      window: younger_evening
      when_true: { action: evaluate, ruleset: younger_evening_sites }
    - condition: always
      when_true: { action: deny, message: "It's bedtime." }

  younger_reading:
    - condition: site_group
      group: reading
      when_true: { action: allow }
      when_false: { action: deny, message: "That site is closed before school." }

  younger_evening_sites:
    - condition: site_group
      group: reading
      when_true: { action: allow }
    - condition: site_group
      group: entertainment
      when_true: { action: evaluate, ruleset: younger_youtube }
    - condition: always
      when_true: { action: deny, message: "That site is closed this evening." }

  younger_youtube:
    - condition: tasks_required
      required: 1
      when_false: { action: redirect, location: revision_task }
    - condition: time_remaining
      quota: younger_entertainment
      when_true: { action: allow }
      when_false: { action: deny, message: "Time is up for today." }

  older:
    - condition: always
      when_true: { action: evaluate, ruleset: allow_school }
    - condition: time_window
      window: older_weekend
      when_true: { action: evaluate, ruleset: older_weekend_sites }
    - condition: always
      when_true: { action: deny, message: "It's bedtime." }

  older_weekend_sites:
    - condition: site_group
      groups: [reading, entertainment]
      when_false: { action: deny, message: "That site is closed this weekend." }
    - condition: site_group
      group: reading
      when_true: { action: allow }
    - condition: tasks_required
      required: 2
      when_false: { action: redirect, location: revision_task }
    - condition: time_remaining
      quota: older_entertainment
      when_true: { action: allow }
      when_false: { action: deny, message: "Time is up for today." }
```

`entertainment_meter` denies on a false site-group test so the shared quota does not accrue every forwarded request. The deny message is unused on the accrual path. It is there because an explicit deny requires a message, including when the same set is later evaluated for access.

`younger_youtube` omits `when_true` on the task rule. That defaults to continue, so a passed test falls through to the time check. The quota sets no byte limit, so a `volume_remaining` check against it would always fail. The illustration does not make that check. `older` and `younger` share `allow_school`. School returns allow and stops. Anything else returns continue, and the caller's next rule runs.

The Monday-to-Thursday entertainment schedule from the problem statement is the same nest: a bedtime deny, a school-hours redirect, an outside-the-evening deny, then tasks, then quota. A Friday-to-Sunday span can be the `+2` period instead of three copied rules.

# Files

YAML is the authoring format. Named rule sets are the reuse mechanism. The loader rejects YAML anchors and aliases.

Clock times are quoted, as in the illustration. Household keys and entity definitions may appear in any file, including a file brought in by `include`. Each one appears once in the whole configuration. A second `bucket_length`, a second `entry`, or a second definition of the same name is a load error. The loader does not let a later file override an earlier one. Duplicate keys inside one file are the same error. The parser must notice them. A YAML loader that quietly keeps the last copy is not acceptable here.

`entry` is required somewhere in that configuration. A configuration that never sets it fails to load.

A file may name other files or directories:

```yaml
include:
  - clients.yaml
  - sites.yaml
  - children
```

Paths are relative to the file that contains the `include`. A directory include loads the `*.yaml` and `*.yml` files in that directory, in lexicographic order, and does not walk into subdirectories. A subdirectory is included by a path or by an `include` in one of those files. The loader remembers each file by its canonical path. A file that is already loaded is skipped, including when the includes form a cycle. That is the same idea as an include guard. It is not an error. A cycle in `evaluate` is a different thing and is still a load error, because a rule cycle does not terminate.

The load is atomic. Every file is parsed, the namespaces are merged, and references are checked. Any error rejects the whole load and leaves the policy already loaded in force. A missing root file also keeps the policy already loaded. At start there is none, so nothing is allowed until the file is there. A missing included path, when the root file is present, is an error. The root file's name must end in `.yaml` or `.yml`. Any other name is a load error that names the file, whether or not it exists.

A load that fails lists every error it can find, not only the first, so every mistake can be fixed in one pass. Every file is read. Each top-level setting, client group, site group, time window and each of its periods, quota, rule set and each of its rules, and task is checked on its own, and a mistake in one does not hide a mistake in another. Within a period or a task, each field is checked on its own too, so a bad start clock and a bad weekday, or a bad `timeout` and a bad question count, are both listed. An item with an error still counts as defined, so a rule that names it does not get a second "unknown" error. Every instance of a whole-policy problem is listed: each pair of site groups that share a priority, each address in two client groups, each `evaluate` cycle, and a missing `entry` beside the rest. A YAML syntax error stops only the file it is in. Includes named only in that file cannot be found, so they are not read. Each error appears once, starts with its file and line, such as `config/policy.yaml:42:5:`, and the errors are sorted by file, in the order the policy includes them, then by line. A DNS name that does not resolve is a warning, listed after the errors. It is not an error.

## Applying an edit

`dw reload` applies an edit to the running decisions, observations, and autoconfig services, without restarting a container. It checks the policy first, with the same code the services run, and changes nothing while there is an error. A good policy is used for the next request through the proxy, and the next fetch of the proxy auto-configuration file. That covers every setting in the policy files: time windows, rules, site group patterns, client group addresses, quotas, tasks, `hostname`, `timezone`, `bucket_length`, and `proxy_configuration`. A reload keeps:

- **Attempts in progress.** A quiz run keeps the questions, words, deadlines, and tries it started with, and it is scored and recorded as it would be after `dw down` and `dw up` with the same edit. The next attempt that starts uses the new task settings. A task the edit adds can be started, and one it removes is no longer offered.
- **Transfers already running.** A download or video keeps the deadline and byte ceiling recorded when it was allowed. A reload does not make it walk the rules early. When it reaches them, it is walked again with the reloaded policy, using the client group and site group from its approval.
- **Sessions.** A parent signed in to the parent pages stays signed in.
- **Usage.** Usage recorded before the reload counts against the reloaded limits. A new `bucket_length` closes the buckets open at the moment of the reload, as a restart with the new length would.

A DNS name that does not resolve keeps the addresses it had before the reload. A missing `policy.yaml` is refused, as any other error is. `dw check` runs the same check and changes nothing. `dw up`, `dw restart`, and the start at boot run it before they start anything, so a broken policy cannot start daywarden into a crash loop.

`config/bypass.txt` is read by the proxy on every request, and spelling recordings when a quiz run starts, so neither needs a reload or a restart. A change to `.env` or `docker-compose.yml`, and a newly installed version, change the containers themselves, and they need `dw restart`. `dw reload` names the services still running with the old settings. A change to `PARENT_NAMES` is one of those, and the proxy is among the services named.

Apply policy changes and upgrades overnight, while the child is not using the computer. A reload never changes the set of an attempt already stored, but it can make a task required partway through the day, and a potential pass he has already made then waits on that task. For example, he has passed spelling as a potential task, and a reload makes spelling and two new tasks required. Spelling was passed today, so it is not required, but its point waits until both new tasks are passed: three tasks where two would have done. A parent check makes up for it. An upgrade restarts the services, so a quiz on the screen reloads.

# Usage report

The report can be sliced by site group, by client group, or by quota. A quota slice is still per client group, because that is whose balance it is. Selecting a quota without a client group shows each client group's balance for it, including `default`.

`default` is a real slice for both kinds of group. Traffic that matched no configured group is visible there. An observation still answers success when the policy service is only recording it. Metering does not turn into a refusal.

# Other fixed rules

- The decision API is `allow`, `deny` with `403` and a message, or `redirect` with `302` and an absolute URL.
- Glob matching, as listed under site groups.
- The household timezone, local midnight, and DNS resolution at load time.
- Start-inclusive, end-exclusive periods, including the one-midnight rule for an end clock that is earlier than the start.
- One point per task per day, for the classified client group and the local date, as described under [Today's score](#todays-score).
- Bucket length, ended buckets for time, stored bytes for volume, and no banking across midnight. Byte suffixes are `b`, `k`, `M`, `G`, and `T`.
- A policy file that fails to load does not replace the policy already loaded.
- Unknown keys are rejected.

# Later, and not required for the rule engine

- **Cutting a live transfer** is [S008.6](../stories/S008.6-cut-transfer.md). The thresholds are above. The addon stops the flow when the observation response is `{"action":"cut"}`. Any failure to get that response leaves the transfer alone. A household day that starts at a clock other than midnight is [S009](../stories/S009-household-day-boundary.md), and it is not part of the cut. This is not required for the rule engine.
- **Applying a policy edit to a transfer already in flight.** The cut re-walks when a recorded deadline or ceiling is reached, and it keeps the groups from the approval. A flag that makes every live transfer walk again on its next observation, including a fresh classification, is not built.
- **A shared quota pool** across client groups. Balances stay per client group.
- **Any scoring other than the score described under [Today's score](#todays-score).**
- **A proxy configuration URL** that tells the browser not to send the policy server's requests to the proxy at all. That is [S019](../stories/S019-proxy-configuration-url.md). Until then, `config/bypass.txt` and the proxy's `PARENT_NAMES` bypass let them through.

# Where the work lives

[S008](../stories/done/S008-hierarchical-policy.md) built the policy loader, the rule engine, the usage ledger, the usage report, and the household sample. [S008.6](../stories/S008.6-cut-transfer.md) is the live-transfer cut. It is not required for the rule engine.

[S003](../stories/S003-revision-tasks.md) assigns tasks to a client group and feeds `tasks_required`. [S007.2](../stories/S007.2-edit-policy.md) edits these entities and rule sets. [S007.3](../stories/S007.3-edit-tasks.md) assigns tasks to a client group.