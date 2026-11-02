# Hierarchical policy

Status: agreed on 2026-10-26. Nothing here is implemented yet. [S008](../stories/S008-hierarchical-policy.md) is the work that brings the running policy service up to this design. Nothing in this design is constrained by an existing deployment. The first household to run it is this one, and the examples in this workspace are rewritten as part of S008. A translator from the current TOML file is not a deliverable.

This note answers why `config/policy.toml` uses `[[groups.rules.windows]]` and `[[groups.rules.weekdays]]`, then describes the replacement.

# What those labels mean today

`[[groups.rules.windows]]` and `[[groups.rules.weekdays]]` are not conditions, and they do not change any rule that follows them. They are TOML's way of hanging a list of child tables off the rule defined immediately above.

A `[[groups]]` table starts a site group. Each `[[groups.rules]]` under it appends one rule to that group. Each `[[groups.rules.windows]]` appends one time period to that rule's `windows` list. Each `[[groups.rules.weekdays]]` appends one weekday override to that rule's `weekdays` list. The next `[[groups.rules]]` starts a new rule with empty lists of its own.

| Child table | Used by | What it holds |
| --- | --- | --- |
| `[[groups.rules.windows]]` | `time_window` | One period: `start`, `end`, and optional `days`. |
| `[[groups.rules.weekdays]]` | `tasks_complete` | A different required count for one named weekday. |

A `time_window` rule is true when the household-local time falls inside any period attached to that rule. The Monday-to-Thursday bedtime block and the Friday-to-Sunday bedtime block in the sample are two periods on the first entertainment rule. Later rules do not inherit them. A `tasks_complete` rule does not read those periods. Its weekday rows, when present, only replace `required` on the named weekdays.

# Why that shape runs out

A request is placed in exactly one site group, and that group owns the only rule list the request will see. The list is the same for every source address. A client record supplies a name, a revision count, and a usage ledger. It does not supply rules.

A time check can pick an action for the sites already in the group. It cannot pick a different set of sites at a different time. Reading sites and YouTube can share a rule list only by living in one group, in which case they are treated the same at 07:30 and at 16:00. They can be treated differently only by living in two groups, in which case each group has one list that applies all day.

The quota size lives on the site group as well. Each client has a separate balance against that shared size. The size does not vary by client.

# Proposed model

Rules are the structure. Site groups, client groups, time windows, and quotas are named values a rule can test. A rule does not belong to a site group. Nesting has no required order. The engine walks the list it was given.

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

Accrual is decided by the quota's rule set, evaluated on its own when an observation arrives. It is not decided by the site group that owns a quota field, because a quota no longer lives on a site group.

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

The access rules run when the request starts. They run again only when an observation finds the clock at the stored time, or a stored ceiling already reached. The re-walk uses the client group and the site group from the approval, and the policy loaded at that moment. The URL stays on the record. Allow replaces the time and the ceilings, and the transfer continues. Deny or redirect cuts. A redirect cannot be applied to a body that is already streaming, so it is a cut. A missing record is not a cut: a bypass, a report with no flow id, and the TOML ledger all leave the transfer running.

The addon posts observations while bytes move, about once a minute and again when the flow ends. The observation response carries the cut. The service answers `{"action":"cut"}` on HTTP 200. The addon stops that transfer. The report sent as the flow ends can still say cut, and the addon does not tear down a transfer that has already finished. A timeout, a connection error, an empty body, or any response that is not that instruction leaves the transfer running. Failure is not a cut. A failed observation never changes a decision already taken. The decision path fails closed, and metering fails open.

A policy edit does not disturb a transfer until that stored time or a volume ceiling is reached. A change to who is in a client group, or which hosts are in a site group, is not applied to the transfer even then. Forcing every live transfer to classify and walk again on its next observation is left for later. A new request is still refused at the limit, without waiting for the grace, when a rule checks that side. During the grace, a new request already follows the flipped rule.

## Tasks

A task has a name, unique in the task namespace, a `type`, a `pass_cooldown` in whole household days, and one or more client groups. `group` names one. `groups` names several. The name `default` is allowed here and means the implicit client group. An unknown client group is a load error.

`failure_cooldown`, `available_from`, `due_date`, `max_skips`, and `max_passes` are optional. Leaving one out leaves that rule off. An omitted failure cooldown does not make a failure wait. Dates are household dates written `2026-10-31`. Cooldowns, skip limits, and pass caps are whole numbers, zero or more. `body` is a mapping of whatever the quiz type needs. This layer stores it and does not interpret it.

The same type may appear on more than one task. `parts-of-speech-1` and `parts-of-speech-2` keep separate sentences, dates, and attempt history. Attempts are rows, not part of this file. Editing a task does not delete them. S003.1 is the catalogue. S009 moves the household day off local midnight. Until then the day starts at midnight.

`available_from`, `due_date`, `max_skips`, and `max_passes` do nothing on a task whose type is `parent_check`.

The picker offers an eligible task other than `parent_check`. While any of those tasks is required, it offers only a required one. It prefers a task that has never been passed, then the one whose last pass is oldest. Candidates that tie rotate in name order. Giving up abandons the attempt when the task is not required, and when it is required only if another required task is eligible. The only required task stays in progress. An authenticated parent records a `parent_check` pass for a client group from `/attempts`. That pass counts toward `tasks_required` and is listed with the group's other attempts. The child has no request that records one.

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

### Sound sets

Each outcome plays one sound, chosen at random from that outcome's directory in the policy image: `policy/static/sounds/correct/`, `incorrect/`, and `timeout/`. Every audio file in the directory is equally likely. Audio is `.mp3`, `.wav`, `.ogg`, `.opus`, or `.m4a`. Any other file, such as an attribution note, is never played. Adding or removing a sound is a file change in that directory. It takes effect when the policy image is rebuilt and the service restarts. A set with no audio plays nothing for that outcome, and the service logs a warning naming that set when it starts. The files are served at `/static/sounds/<set>/<file>` on the task host. A rule that allows the task page, or redirects to `revision_task`, allows them too. A new sound stops the one before it. The page has no mute control.

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

`revision_task` is replaced with a concrete absolute URL before the answer leaves the policy service. The scheme is always `https`. The host is the household `hostname`, or the hostname of the machine running Compose when that is left out. That name is read from the machine's `/etc/hostname`, not from the container's own hostname. The port is the household `port`, or the published policy port (`POLICY_PORT`) when that is left out. Port 443 is left off the URL. When a revision task is eligible for the classified client group, the URL is `https://<hostname>:<port>/tasks/<name>` for the chosen task. When nothing is eligible, the URL is `https://<hostname>:<port>/tasks/next`, and that page says there is nothing to revise. A request for a task the child is not meant to open is sent to one he is. The addon sees only `allow`, `deny`, or `redirect`. The policy file does not set a `revision_task` URL. A file that still sets one fails to load. Rules still redirect to the token `revision_task`.

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

`tasks_required` is a count of passes. One stored pass scores one point. The count is the attempt rows for this client group whose outcome is `pass` and whose finish falls on the household day. A different scoring system is out of scope. The count resets at local midnight. Another client group's passes do not count. Failure and giving up do not increment it. A required count of zero is true for every client group, including `default`.

Weekday overrides on the old `tasks_complete` condition are not part of this model. A different count on a different day is a different rule under a different window. Per-weekday targets inside a spelling task stay on that task.

A parameter that belongs to another condition is a load error. An unknown condition is a load error. An unknown name is a load error.

On an `always` rule the false action is never used. Leave it out and it defaults to continue.

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

The load is atomic. Every file is parsed, the namespaces are merged, and references are checked. Any error rejects the whole load and leaves the previously stored policy in force. A missing root file means the service keeps the policy it stored last time. A missing included path, when the root file is present, is an error.

# Usage report

The report can be sliced by site group, by client group, or by quota. A quota slice is still per client group, because that is whose balance it is. Selecting a quota without a client group shows each client group's balance for it, including `default`.

`default` is a real slice for both kinds of group. Traffic that matched no configured group is visible there. An observation still answers success when the policy service is only recording it. Metering does not turn into a refusal.

The current report is one client and one site group. This view is wider. The report is expected to change to match.

# What this keeps

- The decision API stays `allow`, `deny` with `403` and a message, or `redirect` with `302` and an absolute URL.
- Glob matching, as listed under site groups.
- The household timezone, local midnight, and DNS resolution at load time.
- Start-inclusive, end-exclusive periods, including the one-midnight rule for an end clock that is earlier than the start.
- One completion, one point, for the classified client group and the local date.
- Bucket length, ended buckets for time, stored bytes for volume, and no banking across midnight. Byte suffixes in this design are `b`, `k`, `M`, `G`, and `T`. The older `KB` / `MB` spelling is not the spelling of this file.
- A policy file that fails to load does not replace the stored policy.
- Unknown keys are rejected.

# Later, and not required for the rule engine

- **Cutting a live transfer** is [S008.6](../stories/S008.6-cut-transfer.md). The thresholds are above. The addon stops the flow when the observation response is `{"action":"cut"}`. Any failure to get that response leaves the transfer alone. A household day that starts at a clock other than midnight is [S009](../stories/S009-household-day-boundary.md), and it is not part of the cut. This is not required for the rule engine.
- **Applying a policy edit to a transfer already in flight.** The cut re-walks when a recorded deadline or ceiling is reached, and it keeps the groups from the approval. A flag that makes every live transfer walk again on its next observation, including a fresh classification, is not built.
- **A shared quota pool** across client groups. Balances stay per client group.
- **Any scoring other than one point per completed task.**
- **A proxy bypass list** so some hosts still work when the policy service is down. That list would live on the proxy, not in this policy. It is useful, and it is not part of this design. Sending every request to the policy service is acceptable.

# Where the work lives

[S008](../stories/S008-hierarchical-policy.md) replaces the policy loader, the rule engine, the usage ledger, the usage report, and the household sample. [S008.6](../stories/S008.6-cut-transfer.md) is the live-transfer cut. It is not required for the rule engine.

[S003](../stories/S003-revision-tasks.md) assigns tasks to a client group and feeds `tasks_required`. [S007.2](../stories/S007.2-edit-policy.md) edits these entities and rule sets. [S007.3](../stories/S007.3-edit-tasks.md) assigns tasks to a client group.

No compatibility layer is required for the current TOML shape, the current rule rows, or the current report. S001 and S002 stay the record of what was built. They are not the model to extend.
