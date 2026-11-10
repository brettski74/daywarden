# Implementation plan

Ticket: PLAN
Title: Household proxy, authorization, and revision tasks
Status: Refined
Last Updated: 2026-10-26 00:49:00
---

The policy model agreed on 2026-10-26 is [docs/hierarchical-policy.md](docs/hierarchical-policy.md). [S008](stories/S008-hierarchical-policy.md) replaces the policy model described later in this file. S003 and S007 follow that design. The sections below stay as the record of the plan that S000 through S002 implemented.

This plan turns `ProblemStatement.md` into software we can build in slices. Firewall configuration is out of scope. The younger child's computer is already forced through an explicit forward proxy. The older child's computer is not, until we choose to enrol them.

The first usable slice is a proxy that can allow a request, answer `403` with a message, or answer `302` to another URL. Time-of-day rules come next, then usage buckets, then real revision tasks. Arithmetic is the first quiz. Spelling and parts of speech follow. Setup is config files and, for spelling, recordings the parent makes. A browser quiz builder is later work. A parent can still review attempts and usage in the browser, behind a password.

## Recommendation

Use **mitmproxy** as the forward proxy, and build one **Python service** for policy decisions, usage accounting, revision tasks, and the parent pages.

mitmproxy is the open-source proxy that matches the three outcomes without us writing a proxy:

- In a request hook, set `flow.response` to `403` with a body and the request never leaves the house.
- Set `flow.response` to `302` with a `Location` header and the browser goes to the revision task.
- Leave the flow alone and mitmproxy connects upstream as a normal explicit proxy.

It is MIT-licensed, speaks the explicit proxy protocol browsers already use, intercepts TLS when the child machine trusts a local CA, and can watch response bytes while a transfer is still open. That last point is what the five-minute usage buckets need. A helper that only sees the request line cannot tell that a video response was still moving twenty minutes later.

The policy service is ours. Nothing surveyed can redirect YouTube to a parts-of-speech quiz because two revision tasks are still owed, then allow it after those tasks are passed, then stop it when the day's buckets are used up.

### What we reuse

| Piece | Role |
| --- | --- |
| [mitmproxy](https://mitmproxy.org/) | Explicit forward proxy, TLS interception, 403 / 302 / allow |
| Python 3 | Policy service, quiz pages, and the small mitmproxy addon |
| FastAPI | HTTP API and HTML pages |
| SQLite | Clients, rules, ledger, tasks, attempts |
| Docker Compose | Run the proxy and the policy service together |

### What we build

1. A thin mitmproxy addon. It asks the policy service what to do, enforces the answer, and reports that traffic happened.
2. A rule engine. Ordered site groups, glob patterns, time of day, task completion, and usage quota.
3. A bucket ledger. Configurable bucket length, default five minutes.
4. A revision-task runtime, then arithmetic, spelling, and parts of speech.
5. Parent review, then parent editing.

### Surveyed and not adopted as the core

**Squid** is the serious alternative. An external ACL helper plus [`deny_info`](https://www.squid-cache.org/Doc/config/deny_info/) can return `403` or a `302` to a URL that includes the helper's message. A [`url_rewrite_program`](https://wiki.squid-cache.org/Features/Redirectors) can emit `302:URL` directly. An ICAP REQMOD service can return an encapsulated `403` or `302` in one round trip, which is how commercial filters have driven Squid for years. We would still write the same policy service. We do not start with Squid because `access.log` is written when the transaction ends, so a long video would not fill intermediate buckets until the connection closed, and `ssl_bump` plus ICAP is a lot of machinery for one household. If mitmproxy fights with a particular browser, Squid plus a small ICAP adapter in front of the same decision API is the fallback. The decision API below is deliberately proxy-agnostic. OPNsense ships a Squid plugin, and we still do not run the proxy there. The firewall should keep doing firewall work. The quiz service does not belong on it, and the plugin cannot watch a transfer while it is still open.

**Envoy `ext_authz`** can do the same three outcomes: HTTP 200 allows the request, and a denied response carries a status, body, and headers, including `302` and `Location`. Envoy can run as a dynamic forward proxy. Operating Envoy, its TLS secrets, and a dynamic forward-proxy cluster is more platform than this problem needs.

**e2guardian** filters in explicit, transparent, or ICAP mode. It has URL lists, time-of-day blocking, and TLS inspection. It does not have a callback that picks a quiz for a source IP, and it does not keep a daily bucket quota tied to task completion. The maintained line is bug fixes. Worth remembering if we later want phrase filtering. Not a base to fork.

**Caddy `forwardproxy`** is an experimental explicit proxy with static allow/deny ACLs. It does not ask an external service for a per-request `302`.

**DNS tools** (Pi-hole, AdGuard Home, Citadel) can block names on a schedule. They never see the HTTP request, so they cannot return `403` or `302`, and they cannot tell a Classroom URL from the rest of a Google host once the browser uses its own encrypted DNS. Citadel's per-device daily budget is a useful reference for the ledger, not a component to embed.

**TubeTimeout** and **OpenAppFilter** show how other people metered YouTube: on the router, by host, with nftables or OpenWrt. TubeTimeout even takes over DHCP. Both can block. Neither can send the browser to a quiz. They also confirm the hole we already expected: a file saved locally is invisible after the download. Firewall work stays out of scope. We treat those projects as evidence, not as dependencies.

### YouTube traffic, as far as public notes go

Playback is not one request. The page loads from `youtube.com`, media segments come from `*.googlevideo.com` (often `/videoplayback`), and the player posts watch-time beacons to `/api/stats/watchtime` about every 10 seconds at first and then about every 40 seconds. A five-minute bucket that marks itself when any of that traffic appears will fill during ordinary watching. It will also fill if the child starts a video and walks away, which matches the problem statement. It will not notice a video that was downloaded inside the quota and watched later from disk. Byte totals are stored from the start so a volume rule can be added after we have seen real traffic. That rule is its own story and is not required for the first working setup.

## Architecture

```
child browser
    |  explicit HTTP proxy, TLS intercepted with our CA
    v
mitmproxy + addon
    |  POST /v1/decisions          (fail closed, except the bypass list)
    |  POST /v1/observations       (fail open: never block a page because metering failed)
    v
policy service
    |-- site groups and rules
    |-- bucket ledger
    |-- task catalogue, attempts, quiz pages
    |-- parent pages
    v
SQLite
```

The addon stays dumb. It does not know what a weekday or a quiz is. The policy service returns a finished decision, including the concrete task URL when the answer is a redirect.

### Decision API

`POST /v1/decisions`

```json
{
  "client_ip": "192.168.1.40",
  "method": "GET",
  "url": "https://www.youtube.com/watch?v=abc",
  "occurred_at": "2026-10-18T15:04:00-04:00"
}
```

One of:

```json
{ "action": "allow" }
{ "action": "deny", "status": 403, "message": "Time is up for today." }
{ "action": "redirect", "status": 302, "location": "http://192.168.1.10:8080/tasks/next" }
```

The addon turns a deny into a small HTML page so the browser shows the message, and turns a redirect into a `302` with `Location`. Decisions are made from the request headers, before the body is forwarded.

`POST /v1/observations`

```json
{
  "client_ip": "192.168.1.40",
  "url": "https://rr1.googlevideo.com/videoplayback?id=1",
  "occurred_at": "2026-10-18T15:09:00-04:00",
  "bytes": 250000
}
```

The addon sends an observation when a request starts, another about once a minute while that flow is still transferring bytes, and a final one when the flow ends. An idle connection does not generate observations. A failed observation is logged and ignored.

### Why TLS interception is in scope

An HTTPS request arrives at an explicit proxy as `CONNECT www.youtube.com:443`. The proxy can refuse the tunnel, but it cannot answer that `CONNECT` with a page redirect to a quiz. The browser only understands a `302` on the decrypted HTTP request inside the tunnel. Host-only rules would be enough to block YouTube. They are not enough to send him to a revision task. So the child's browser trusts a CA we generate, and mitmproxy issues per-host certificates from it.

Consequences, accepted:

- Apps that pin certificates will fail through this proxy. The target is a browser.
- The task site and an unconditional allow list (Classroom and the pieces of Google it actually loads) are configured as a bypass on the addon. Those hosts keep working when the policy service is down. Everything else fails closed with `403`.
- QUIC (HTTP/3 over UDP/443) skips an HTTP proxy entirely. Chrome will use it for YouTube if UDP/443 is open. Closing that bypass is firewall work and stays out of scope, but the setup notes will name it as a dependency. The same is true of a second network path (phone hotspot, raw IPv6 that never hits the proxy).

### The OPNsense box

The household firewall and router is OPNsense. The DHCP reservations that identify each computer already live there. Configuring that box is still out of scope. It is the right place for the jobs this proxy cannot do, and the wrong place to run the proxy.

What OPNsense is for, aimed at a host alias for the younger child's reserved IP:

- Keep the static DHCP mapping. That address is the client identity in our config.
- Deny that host a direct path to the internet, so the explicit proxy is the way out. The problem statement says this is already done.
- Block UDP/443 from that host, so Chrome cannot sneak YouTube out over QUIC. A reject is kinder than a silent drop on a LAN, because the browser falls back to TCP sooner.
- Apply the same idea to IPv6 for that host, if IPv6 is enabled on the LAN. A reservation that only pins IPv4 does not pin IPv6.

What OPNsense is not for:

- Bedtime and revision rules. Firewall schedules can only pass or block. They cannot answer `302` and send him to a quiz. Those rules stay in the policy service.
- Hosting mitmproxy, the policy service, or the quizzes. A custom app on the firewall is a bigger blast radius than this household needs.

When the older child is enrolled, the same alias pattern is how their computer would be brought under the proxy. Until then, their host stays off that alias.

## Policy model

**Client.** Source IP address, plus a display name. The household has one IANA timezone. Every machine in the house already has a DHCP reservation on the OPNsense box, so a child's IP stays put. There are two children. The first configuration enrols the younger child's reserved IP only. The older child is a second client row we can add later, with their own tasks, revision count, and usage ledger. Site rules (hours, patterns, quota size) are household-wide in this version. Two children with different bedtimes would be a new story. Until the older child is enrolled, their computer should not be sent to this proxy: an unenrolled IP that does arrive is still judged by the household rules, and a revision redirect would find no task assigned to them.

**Site group.** A name, a priority, a list of patterns, and an ordered list of rules. Lower priority is tested first. The first group whose pattern matches owns the request. One group is the default and matches when nothing else does. A request that matches nothing, and no default group, is denied.

**Patterns.** Glob, not regular expressions. `*` matches any run of characters, including slashes. `?` matches one character. The match is case-insensitive. A pattern that contains `://` is matched against the absolute URL with the fragment removed. A pattern without `://` is a host glob (`*.youtube.com`, `youtu.be`).

**Rule.** A condition and two actions, `when_true` and `when_false`. Each action is one of:

- `continue` (default)
- `deny`, with a message
- `redirect`, either to an absolute URL or to the token `revision_task`
- `allow`, which authorizes the request and stops

The first action other than `continue` wins. If the list runs out, the request is denied. An always-allowed group ends in an unconditional allow, so it does not fall off the end.

**Conditions** in the first version:

| Condition | True when |
| --- | --- |
| `time_window` | Local time falls inside the window. Windows may name weekdays, and a window may cross midnight. |
| `tasks_complete` | Successful revisions completed today by this client is at least N. N may differ by weekday, with a default. |
| `quota_remaining` | Today's consumed time for this client and this group is still under the group's configured duration. The duration is a length of time, such as `2h`. Buckets are how that time is measured, not how it is configured. |
| `volume_remaining` | Today's stored bytes for this client and this group are still under the group's byte limit. KB, MB, GB, and TB are powers of 1,024. The bytes are the ones already on today's buckets, including a bucket that has not ended. A group with no byte limit makes the condition true. The sample policy does not turn this on. |
| `always` | Always true. Used to allow or deny unconditionally. |

`revision_task` is resolved by the policy service to `https://<hostname>:<port>/tasks/<name>` before the answer is returned. The addon only ever sees an absolute URL. The chosen task comes from the tasks assigned to that source IP.

The Monday-to-Thursday entertainment example is five rules, not special code:

1. Window `00:00–07:00`: true means deny, false means continue.
2. Window `07:00–15:00`: true means redirect to a revision task, false means continue.
3. Window `15:00–19:00`: true means continue, false means deny. This catches `19:00–24:00`.
4. Tasks complete, at least 2: true means continue, false means redirect to a revision task.
5. Quota remaining: true means allow, false means deny with a "time is up" message.

Different days are different windows on those same rules. "The rest of the internet" is another group with the same kinds of rules and no quota rule. Classroom is a higher-priority group whose only rule is allow. Usage is still recorded for Classroom, because metering is per group and does not depend on a quota being configured.

## Accounting model

The day is cut into buckets of a configurable length. The default is five minutes. A bucket is keyed by client, site group, local date, and bucket index. Each bucket remembers the length it was created with.

A group's time quota is configured as a duration in ordinary units: seconds, minutes, or hours. `2h` and `120m` are the same quota. The configuration never stores a bucket count. Changing the bucket length does not change any configured quota, and it does not rewrite buckets that have already been counted. Those keep the length they had. A quota specified as a raw number without a trailing unit of measure suffix will assume that it is a number of seconds.

Any observation in a bucket marks it. A marked bucket adds its own length to the consumed time only after its end time has passed, so a request in the first seconds of a bucket does not consume that time until the bucket closes. The open bucket is not part of the total yet. `quota_remaining` is true while consumed time is strictly below the configured duration. With a `2h` quota and five-minute buckets, 23 ended buckets are 115 minutes and the quota remains. 24 ended buckets are 120 minutes and the quota is exhausted. If the bucket length is later set to ten minutes, the quota is still `2h`. New buckets are ten minutes each. The 23 buckets already counted still contribute five minutes each.

There is no banking across days. The ledger and the revision count both reset at local midnight. Minutes left unused today are gone tomorrow. Revision tasks completed yesterday do not count today, even if he never used the internet after finishing them. A requirement of two tasks means two passes on that local date before the entertainment rules will allow the quota to be used. Bytes are stored on each observation. `volume_remaining` reads that same `byte_count`. The sample policy leaves the condition off until a parent sets a limit from real totals.

An already-open transfer is not cut the moment the quota flips. The next request is denied. YouTube's segment and heartbeat requests make that enough for ordinary playback. Killing a live stream is a possible later story, not part of the first ledger.

## Revision tasks

Tasks are assigned to a source IP. A redirect asks for the next eligible task: assigned to that IP, and not still inside its cooldown. Ties go to the task that was passed least recently. A task never passed comes first.

Cooldown is measured in local midnights. A task completed today with a one-day cooldown is available again tomorrow, not 24 hours after the click. A parts-of-speech quiz can set a shorter cooldown after a failed attempt than after a pass, so a failed quiz can return the next day while a passed one stays away for several weeks.

Giving up records an abandoned attempt. It does not count as a pass or a failure, and it does not satisfy the daily revision count. Only a pass increments today's count. Completing a task at 00:10 counts toward the new day.

The child cannot mark a task passed by hitting a URL. The server records a pass when the quiz's own completion rule is met, based on the child submitting correct answers. The temporary `parent_check` task is the exception: a parent records that pass, and the child still has no request that can do it.

Arithmetic, spelling, and parts of speech are three task types on that shared runtime. Their behaviour is specified in the stories. Spelling is complete only when all three of these are true: every word from this week's pool has been asked at least once, the required number from this week's pool are correct, and the required number from the revision pool are correct. A pass mark of 7 out of 10 does not skip the last three words. Until all three are met, the quiz keeps asking. Wrong this-week words are asked again only while that pool's correct count is still short of the pass mark.

Spelling audio is recorded by the parent. Each word needs the word spoken on its own, slowly and clearly, and one sentence that contains it. The alphabet clips for practice mode are recorded once and reused. Free local voices exist (Piper is fast and a bit flat; Kokoro sounds more natural; espeak-ng is clear at very slow speeds and sounds like a robot). Slowing a neural voice tends to smear it, which is the opposite of what a spelling test wants. Recording the week's list is the easier path, and the household already has the equipment. Generated speech stays in S005.4 for later.

## Build sequence

Each story is implementable on its own once the stories it depends on are done. Earlier slices are useful before later ones exist.

| Order | Stories | What the household can do afterwards |
| --- | --- | --- |
| 1 | S000.1, S000.2 | A browser using the proxy is allowed, given a `403`, or sent a `302`, according to a test double. Classroom hosts and the task host keep working if the decision service is down. |
| 2 | S000.4 | Written setup for the CA, the proxy setting, and the QUIC dependency. |
| 3 | S001.1 through S001.6 | Real rules. YouTube can be denied by time of day. Task and quota conditions already return an answer; the counts they read stay at zero until later stories. |
| 4 | S007.1, S000.3, S002.1, S002.2 | Five-minute buckets fill from real traffic, the quota rule starts denying, and a parent can see Classroom time after signing in. |
| 5 | S003.1, S003.2, S003.3 | Redirects land on a real task picker. A parent can record that the gate works, using a temporary "mark this practice item done" task if the quizzes are not built yet. |
| 6 | S004.1 through S004.5 | Arithmetic earns a real completion. |
| 7 | S005.1, S005.2, S005.3 | Spelling earns a completion, using recordings the parent supplies. Practice mode is in this slice. |
| 8 | S006.1 through S006.4 | Parts of speech, including a real failure. |
| Later | S005.4, S007.2, S007.3 | Generated spelling audio and browser editors for rules and quizzes. None of these are required to run the house. S002.3's volume condition is in; the sample policy does not turn it on. |

S004, S005, and S006 depend on S003 and not on each other. They can be built in any order. Arithmetic is first because it has no audio assets and no drag-and-drop.

## Story index

Epic points are the sum of their child estimates. Child estimates are Fibonacci, judged against each other, because this repository has no finished stories yet. The scale is in the next section.

Stories marked Later are kept so the work is not forgotten. They are not part of the initial build.

| Ticket | Title | Points | When |
| --- | --- | --- | --- |
| [S000](stories/S000-proxy-decision-loop.md) | Proxy decision loop | 13 | Initial |
| [S000.1](stories/S000.1-run-the-proxy.md) | Run mitmproxy with a local CA | 3 | Initial |
| [S000.2](stories/S000.2-enforce-decisions.md) | Enforce allow, 403, and 302 | 5 | Initial |
| [S000.3](stories/S000.3-report-observations.md) | Report traffic observations | 3 | Initial |
| [S000.4](stories/S000.4-child-computer-setup.md) | Document the child computer setup | 2 | Initial |
| [S001](stories/S001-authorization-rules.md) | Authorization rules | 21 | Initial |
| [S001.1](stories/S001.1-clients-and-timezone.md) | Clients and household timezone | 3 | Initial |
| [S001.2](stories/S001.2-site-groups.md) | Site groups and glob matching | 5 | Initial |
| [S001.3](stories/S001.3-rule-engine.md) | Rule engine and time windows | 5 | Initial |
| [S001.4](stories/S001.4-task-completion-condition.md) | Task-completion condition | 3 | Initial |
| [S001.5](stories/S001.5-quota-condition.md) | Quota-remaining condition | 3 | Initial |
| [S001.6](stories/S001.6-sample-household-policy.md) | Sample household policy | 2 | Initial |
| [S002](stories/S002-usage-accounting.md) | Usage accounting | 13 | Initial, except S002.3 |
| [S002.1](stories/S002.1-bucket-ledger.md) | Bucket ledger | 5 | Initial |
| [S002.2](stories/S002.2-usage-report.md) | Usage report | 3 | Initial |
| [S002.3](stories/S002.3-volume-limit.md) | Volume limit | 5 | Done; sample stays off |
| [S003](stories/S003-revision-tasks.md) | Revision task platform | 13 | Initial |
| [S003.1](stories/S003.1-task-catalogue.md) | Task catalogue, cooldown, and attempts | 5 | Initial |
| [S003.2](stories/S003.2-task-selection.md) | Task selection and give-up | 5 | Initial |
| [S003.3](stories/S003.3-attempt-review.md) | Parent review of attempts | 3 | Initial |
| [S004](stories/S004-arithmetic.md) | Arithmetic quizzes | 13 | Initial |
| [S004.1](stories/S004.1-arithmetic-shell.md) | Arithmetic session shell | 5 | Initial |
| [S004.2](stories/S004.2-addition.md) | Addition | 2 | Initial |
| [S026](stories/S026-arithmetic-administration.md) | Arithmetic administration, subtraction, multiplication, and division | 8 | Later |
| [S005](stories/S005-spelling.md) | Spelling quiz | 21 | Initial, except S005.4 |
| [S005.1](stories/S005.1-spelling-content.md) | Word pools, targets, and audio | 3 | Initial |
| [S005.2](stories/S005.2-spelling-quiz.md) | Spelling quiz flow | 8 | Initial |
| [S005.3](stories/S005.3-spelling-practice.md) | Spelling practice mode | 5 | Initial |
| [S005.4](stories/S005.4-spelling-speech.md) | Generate spelling audio | 5 | Later |
| [S006](stories/S006-parts-of-speech.md) | Parts of speech quiz | 17 | Initial |
| [S006.1](stories/S006.1-parts-of-speech-sentences.md) | Parts of speech sentences and configuration | 3 | Initial |
| [S006.2](stories/S006.2-parts-of-speech-quiz.md) | Parts of speech quiz | 8 | Initial |
| [S006.3](stories/S006.3-parts-of-speech-feedback.md) | Parts of speech red marks and answer | 3 | Initial |
| [S006.4](stories/S006.4-parts-of-speech-review.md) | Parts of speech attempt review | 3 | Initial |
| [S007](stories/S007-parent-administration.md) | Parent administration | 21 | Sign-in only |
| [S007.1](stories/S007.1-parent-sign-in.md) | Parent sign-in | 5 | Initial |
| [S007.2](stories/S007.2-edit-policy.md) | Edit clients, groups, and rules | 8 | Later |
| [S007.3](stories/S007.3-edit-tasks.md) | Edit tasks and assignments | 8 | Later |

Child estimates sum to 128. The initial build, leaving out the Later rows, sums to 102.

### Point scale

| Points | Meaning, relative to the other stories here |
| --- | --- |
| 1 | A few hours. One function and its tests. Not used yet. |
| 2 | About a day. A small vertical slice on top of something that already exists. |
| 3 | Two or three days. A single behaviour, some persistence, tests. |
| 5 | About a week. A vertical slice with real edge cases. |
| 8 | About two weeks. UI and rules that will need iteration. |
| 13 or 21 | An epic rollup, not a single piece of work. |

## Decisions

Recorded from the parent on 2026-10-18.

1. The younger child's browser will trust the proxy's certificate authority. TLS interception stays in the design.
2. Spelling does not finish early. He is asked every word from this week's pool at least once, and he must also reach both correct-counts. A pass mark below the size of the pool does not skip the remaining words.
3. Identity is the DHCP reservation. Both children have stable addresses. The schema holds more than one client. The first setup enrols the younger child only. The older child can be added later without a migration.
4. Nothing carries over midnight. Unused entertainment minutes expire. Yesterday's revision tasks do not satisfy today's requirement. The entertainment quota is usable only after today's required passes.
5. Config files are the setup path. A quiz builder and a policy editor in the browser are nice to have and are not part of the initial build. Usage reports and attempt review stay, behind a password, because those are records rather than authoring tools. Spelling words and sentences are recorded by the parent. Generated speech is later work.
6. Both children's computers run Arch Linux. Client setup is written for Arch. The proxy is still a Docker Compose service, and the machine that runs it is not assumed to be one of those computers.

## Assumptions still in force

These were not in the questions above. They stand until a story changes them.

- One policy service and one mitmproxy addon, run with Docker Compose. Python, FastAPI, SQLite, server-rendered pages, and a small amount of plain JavaScript for the quizzes.
- The household timezone is configurable. The default is the timezone of the machine running the service.
- There is no weekly cap in the first version.
- A time quota is stored as a duration in seconds, minutes, or hours. The bucket length is a separate setting. Changing the bucket length does not resize a quota and does not change the length already recorded on a counted bucket.
- Only a pass counts toward the daily revision number. A failed parts-of-speech quiz does not. Giving up does not.
- Cooldown is a whole number of local days. Zero means the task may be used again immediately.
- A pass is attributed to the local day on which the server records it.
- Parts-of-speech points are per sentence. A sentence scores 1, 0.5, or 0.25 when it is right on the first, second, or third try, and 0 otherwise. See S006.2. Words are tracked by their position in the sentence, so a repeated word can be placed twice.
- When an arithmetic task requires only one correct answer, the timeout is the configured maximum.
- Arithmetic timeouts shrink geometrically. After `k` correct answers, with `N` required and `N > 1`, the timeout is `Tmax * (Tmin / Tmax) ^ (k / (N - 1))`. It is `Tmax` before the first correct answer and `Tmin` when one more correct answer finishes the task.
- Subtraction and division draw weighted `m` and `n` the same way as addition and multiplication, then display `x − m` or `x ÷ m` where `x` is the sum or product.
- The multiplication sign on screen is `×` and the division sign is `÷`.
- The proxy does not tear down a transfer that is already in progress when the quota is reached.
- Parent pages require a signed-in parent from S007.1, and they are served over HTTPS. The certificate comes from the household CA, lasts 30 days, and is replaced when it will expire within 3 days or no longer covers the configured names. The session cookie is `Secure`. Accounts are a local username and an Argon2id password hash. A session lasts at most 15 minutes idle and 180 minutes from sign-in, unless the service sets other positive limits. Quiz pages do not use that session. The child must not be able to open the parent pages.
- Sound effects are short audio we generate or that we have the right to ship. They are not recordings of the words "correct" or "wrong".
- Volume limits and killing a live stream are later stories.

## Out of scope

- Configuring OPNsense: DHCP reservations, the host alias, denying that host a direct path out, and blocking its UDP/443. The setup notes name those jobs and do not include firewall commands. DNS filtering is not part of this design.
- Filtering by page text, image content, or SafeSearch rewriting.
- Accounts for the child, mobile-device management, and browser profiles.
- A custom proxy implementation, unless mitmproxy fails the S000 stories.
