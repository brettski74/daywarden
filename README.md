# daywarden

Household explicit proxy. `make up` starts mitmproxy with a certificate authority that stays on disk across container restarts, the policy service, and the proxy auto-configuration file that browsers fetch.

## Start

```sh
make up
```

`make up` and `make down` run `bin/dw up` and `bin/dw down` on this checkout, so they check the policy first and use the same ports. `make down` stops the stack and removes the containers. The CA directory and the policy database stay on disk.

`make reload`, `make restart`, and `make check` run `bin/dw reload`, `bin/dw restart`, and `bin/dw check` on this checkout. They are described under [The policy file](#the-policy-file). `make logs` runs `bin/dw logs`, and `make logs ARGS="-f decisions"` passes the options and service names through. `make restart` also rebuilds the policy image, so it picks up changes to the code under `policy/`. `make reload` and `make check` run in the containers that are already running, so they use the code those containers were built from. `make help` lists every target and what it does.

The proxy listens as a normal HTTP proxy. Clients use `PROXY_PORT` on the machine that is running Compose, `PORT_BASE` from `.env`, 8080 by default. A browser can be given the configuration URL, `http://<this machine>:<PROXY_CONFIG_PORT>/proxy.pac`, instead, such as `http://garden:8088/proxy.pac`. `dw up` and `dw status` print it. See [docs/child-computer.md](docs/child-computer.md) for each browser.

Every request is sent to the policy service (the Compose service `decisions`) as `POST /v1/decisions`, unless the host is listed in `config/bypass.txt` or is one of the policy server's own names in `PARENT_NAMES`. The policy service classifies the URL into one site group and the source address into one client group, then walks the rule set named by `entry`. A deny becomes a small HTML page with status `403`. A redirect becomes status `302` with a `Location` header. If the policy service is down, or its answer is not allow, deny, or redirect, the proxy responds `403`. Hosts on the bypass list are forwarded either way.

## The policy file

`config/policy.yaml` is the household policy. Edit it, then run `dw reload` (`bin/dw reload` in a clone). On an installed machine, each version it applies is kept in the [config history](#config-history). It checks the whole policy and lists every error it finds, each with its file and line, such as `config/policy.yaml:42:5: unknown setting timezon`, and changes nothing until they are all fixed. A good policy is used for the next request through the proxy, and no container restarts. A quiz in progress, a download or video already running, a parent signed in to the parent pages, and the usage recorded so far all carry on. A running transfer keeps the deadline and byte ceiling recorded when it was allowed, and is walked again with the reloaded policy when it reaches them. `dw check` checks the policy and changes nothing. `dw up` and the start at boot check it first, so a broken policy does not start daywarden.

`config/bypass.txt` is read on every request, and spelling recordings whenever a quiz run starts, so neither needs a reload or a restart. A change to `.env` or `docker-compose.yml`, such as `PORT_BASE`, `PARENT_NAMES`, or `OBSERVATION_INTERVAL`, needs `dw restart`, which checks the policy and then replaces every container. `dw reload` warns when that is needed and names the services still running with the old settings. See [Applying an edit](docs/hierarchical-policy.md#applying-an-edit) for the details.

Apply policy changes and upgrades overnight, while the child is not using the computer. A reload partway through the day can make a task required after he has already started his revision, and his passes since then can then wait on that task before they count. An upgrade restarts the services, and a quiz on the screen reloads.

`dw check`, `dw reload`, and `dw up` refuse a missing policy file. A service started another way, such as `make up`, starts with nothing loaded and denies requests. `POLICY_FILE`, set in `.env`, points both services at another file. It is the path inside the containers, where the configuration directory is `/etc/daywarden`, and it defaults to `/etc/daywarden/policy.yaml`. Its name must end in `.yaml` or `.yml`. Any other name stops both services at start with an error that names the file.

The file names client groups, site groups, time windows, quotas, and rule sets. `entry` is the rule set where a decision starts. `hostname` is the DNS name external clients use to open the policy server. It is a host, not a URL. Leave it out to use the hostname of the machine running Compose, read from that machine's `/etc/hostname`. The name inside the decisions container is not used. Set it when that name is not the one in the browser's address bar. `port` is the port those clients use. Leave it out to use `POLICY_PORT`. Set it when a reverse proxy presents the pages on a different port. A redirect to the `revision_task` token is the task picker, `https://<hostname>:<port>/tasks/next`, and port 443 is left off. The file does not contain a `revision_task` URL. `timezone` is an IANA name. The sample sets `America/Toronto`. Delete that line to use the timezone of the machine running Compose, which is read from that machine's `/etc/localtime`.

An address that belongs to no client group is the implicit client group `default`. A URL that matches no site group is the implicit site group `default`. Neither group is written in the file. This file grants access only to the younger child's group, so an address in `default` is denied with "No rule granted access.", including a school site.

## Clients

One client group is the computers that share a schedule. The sample enrols the younger child at `192.168.1.40`. That address is a placeholder: replace it with the computer's DHCP reservation, written as an IP or a DNS name. DNS names are looked up once, when the service starts. If a name does not resolve then, the group keeps the addresses it resolved to last time. Restart the decisions service after the reservation changes. The older child is not in the file. A comment there says how to add them.

## Site groups

A site group has a name, a unique integer priority, and glob patterns. Groups are tried lowest priority number first, and the first match wins, so Classroom at priority 10 is picked before a wider pattern at priority 20. Two groups cannot share a priority.

A pattern that contains `://` is matched against the whole URL, without its `#fragment`. Any other pattern is matched against the host only. Matching ignores case. `*` matches any run of characters, including `/`, and `?` matches one character. `*.youtube.com` matches `www.youtube.com` but not `youtube.com`, so list both if you need both.

What remains after every configured group misses is the implicit site group `default`. It has no priority and no patterns, and it is not written in the file.

School is a starter list of Classroom hosts and the Google hosts a Classroom session loads. It is allowed at any time for the younger child, and it has no quota. It is not every school site, and it is not all of Google. Entertainment is YouTube. Monday to Thursday, bedtime denies, school hours redirect to revision, and the evening continues only when today's revision count has reached 2. A `2h` quota then allows the request or denies it. Friday, Saturday, and Sunday are in the file as a starting suggestion, with a wider evening. The implicit `default` site group uses those same hours and the same revision count, and it has no time quota. The school hosts are listed again in `config/bypass.txt`, with the policy server's names. Edit the two files together. Nothing copies one into the other.

## Rules

Rules live in named rule sets. A site group does not own a list of them. A rule has a `condition` and two optional actions, `when_true` and `when_false`. An omitted action is `continue`. An action is `continue`, `deny` with a message, `redirect` to an absolute `http` or `https` URL or the token `revision_task`, `allow`, or `evaluate` of another rule set. `allow`, `deny`, and `redirect` stop the walk. `evaluate` uses the other set's decision. If the set named by `entry` only continues, the request is denied with "No rule granted access."

A `time_window` condition names a window defined once under `time_windows`. The window is true when the household-local clock is inside any of its periods. The start counts and the end does not, so `07:00–15:00` and `15:00–19:00` do not both match at 15:00. Write clocks as quoted strings, `"07:00"` or `"0700"`. `days` is a weekday, a range such as `monday-thursday`, or a list of those. Leave the day off a period to mean every day. An end clock earlier than the start finishes the next day: Saturday `22:00–07:00` includes Saturday night and Sunday morning, and does not include Saturday morning.

A `tasks_required` condition carries `required`, a count of passed revision tasks. It is true when this client group's score for the household-local date is at least that many. A task that is required, because it is due or has been skipped too often, scores one point when he passes it. Any other task he is offered scores one point too, but only once no task is required, so he can do the easier ones first and they count when the hard one is passed or tried. No task scores twice in a day, and a task he opens from a bookmark when it is not on offer, such as a repeat, is practice and scores nothing. Each parent check recorded on `/parent/attempts` scores one point. The count resets at local midnight. Another client group's passes do not count. A different count on a different day is a different rule under a different window. See [Tasks](docs/hierarchical-policy.md#tasks) for the task sets and the score.

A `time_remaining` condition names a quota. It is true when today's ended usage for this client group on that quota is strictly under the quota's `time`. The sample entertainment quota is `2h`. `120m` and `7200s` are the same limit. A bare number is rejected. Usage is measured in buckets (`bucket_length`, five minutes when it is left out). The length has to divide a 24-hour day, so two, five, and ten minutes are accepted and seven minutes is rejected. Buckets are aligned to household-local midnight. A bucket counts toward the time limit only after its end time has passed, and it contributes the length stored on that bucket. Changing the bucket length does not change a stored quota, and a bucket that has already ended keeps its length. The new length takes effect when the decisions service loads the file. That load closes a bucket that is still open: its length becomes the seconds from its start to the load. The next bucket starts at the load and ends at the next midnight boundary of the new length, so it can be shorter. Every bucket after that boundary is the full new length. Forwarded traffic writes these buckets. The sample does not set a byte limit.

```yaml
- condition: time_window
  window: bedtime
  when_true: { action: deny, message: "It's bedtime." }
- condition: tasks_required
  required: 2
  when_false: { action: redirect, location: revision_task }
- condition: time_remaining
  quota: entertainment
  when_true: { action: allow }
  when_false: { action: deny, message: "Time is up for today." }
```

The three answers the proxy sees are:

```json
{ "action": "allow" }
{ "action": "deny", "status": 403, "message": "Time is up for today." }
{ "action": "redirect", "status": 302, "location": "https://garden:8084/tasks/next" }
```

That location is the task picker. It opens the task chosen for the client group, at `https://<hostname>:<port>/tasks/<type>/<name>`, or says "There is nothing to revise right now." The proxy forwards every request for the policy server's names in `PARENT_NAMES` without asking the rules, and sends the child's address with it, so the task pages, the picker, and the parent pages open at any time, including at bedtime. Any task assigned to his client group opens from a bookmark, even one that is not on offer. "Try a different task" opens the task selector at `/tasks/choose`, which lists the tasks on offer, then After These and Extra Practice for the tasks that count later or not at all. A quiz that doesn't count right now is purple and says so. Going back to a task he gave up, within the hour, carries on where he left it.

An `arithmetic` task is a timed quiz on that page: one large question, an answer box, and a timer bar that shrinks as he gets more right. Its `body` sets the operation, `max_timeout`, `min_timeout`, `correct_answers_required`, and weighted `operands`, and a bad body fails the load. The sound effects are the audio files in `policy/static/sounds/correct/`, `incorrect/`, and `timeout/`, one chosen at random per answer. Add or remove a file there and rebuild the policy image. See [docs/hierarchical-policy.md](docs/hierarchical-policy.md#arithmetic-tasks) for the fields, the timing rules, and the stored record.

A `skip_counting` task shows a row of numbers that count up or down by the same step, with blank boxes to fill in. He gets three tries per question, worth 1, 0.5, and 0.25 points. With `maximum_questions` set, an attempt that runs out of questions without enough points is a failure. Every field has a default, so `body: {}` is a working task. Each difference may set its own `minimum_value` and `maximum_value`. The defaults keep counting by 2 under 100. See [docs/hierarchical-policy.md](docs/hierarchical-policy.md#skip-counting-tasks) for the fields, the configuration checks, and the scoring.

A `parts_of_speech` task lists as many sentences as you like, each with a `parts` table that maps part of speech names you choose, such as `noun`, `verb`, or `Doing words`, to words from that sentence. Words left out of the table belong in no row. A word that appears twice is told apart by its occurrence number, such as `dry[1]` and `dry[2]`, or `the[1,2]` for both, and words are matched without regard to case. Quote an entry with brackets inside `[...]`, as in `["dry[1]"]`, and quote `yes`, `no`, `on`, `off`, and numbers so YAML keeps them as words. Each sentence gets `90s` unless the body or the sentence sets another `timeout`, and the pass mark defaults to 70% of the sentences, rounded up. A mistake fails the load and names the task, the sentence, the part, and the entry. He drags each word into its row with the mouse and gets three tries per sentence, worth 1, 0.5, and 0.25 points, with a count of wrong and missed words after a wrong try. After a wrong second try the wrong and missed words turn red, and after a wrong third try or a timeout the table shows the answer, coloured by where he had each word. Every sentence is asked once per run in a shuffled order, and the run ends after the last one: enough points is a pass, and anything less is a failure. A reload brings back the open sentence on its original deadline. See [docs/hierarchical-policy.md](docs/hierarchical-policy.md#parts-of-speech-tasks) for the fields, the word rules, the timer, and the scoring.

A `spelling` task plays recordings of words, and he types each one. The recordings live on the host in `DAYWARDEN_DATA_DIR` (`$HOME/daywarden` by default, set in `.env`), in `spelling/current` for this week's words and `spelling/revision` for older ones. Name each file after the word, such as `rope.opus`, and add `rope.sentence.opus` for a sentence that uses it. `spelling/alphabet` needs one recording of each letter, `a.opus` to `z.opus`, plus `dash.opus` and `apostrophe.opus` when a word uses `-` or `'`. Practice mode uses them to spell each word out loud. New or replaced files are used from the next quiz run without a restart. `make up` creates the directory if it is missing. See [docs/hierarchical-policy.md](docs/hierarchical-policy.md#spelling-tasks) for the file names, the fields, and the rules. [Recording spelling clips](#recording-spelling-clips) shows how to record a whole list in one take and cut it into files.

### Back to the page he was sent away from

When a rule sends a page load to `revision_task`, the policy service remembers that URL for the computer that asked, by its IP address. The whole URL is kept, including the path and query string. Each computer keeps only the last such page, so two computers in the same client group each have their own. Only a `GET` that opens a page counts: `Sec-Fetch-Dest: document`, or, for a plain `http` request without `Sec-Fetch-Dest`, an `Accept` header that includes `text/html`. Images, scripts, background fetches, other methods, allows, denies, redirects to a URL written in the policy file, the policy server's own pages, and hosts on the bypass list are never remembered. The URL is kept in the policy database, so it survives `docker compose restart decisions`.

When a quiz passes on that computer, the policy service decides the remembered URL again with the rules as they stand. If that is now an allow, "Well done" says "Going back to www.youtube.com" and opens the page in the same tab 5 seconds later. "Go now" or Enter opens it straight away. "Next task" is still offered when another task is available, and choosing it stops the countdown and keeps the URL for a later pass. If the URL would still be redirected or denied, for example when `tasks_required` needs another pass or the quota is used up, "Well done" is unchanged. A failure, a give-up, and a `parent_check` recorded on `/parent/attempts` send him nowhere.

The URL is forgotten when the proxy allows that exact URL from that computer, whether he got there from "Well done" or typed it himself, and when the household day ends. A computer whose address changes starts with nothing remembered. See [docs/hierarchical-policy.md](docs/hierarchical-policy.md#back-to-the-page-he-was-sent-away-from) for the details.

## Decision and observation logs

`dw logs decisions` shows one line for each request the proxy asked about. The line says what was decided, the site group and client group, the household-local time, and the rule that decided. A redirect also says where it sent the browser:

```text
decisions-1  | decision deny GET https://www.youtube.com/watch?v=abc (video) for kids at 2026-11-08T19:42:10-05:00 by evening rule 2
decisions-1  | decision redirect GET https://games.example/ (games) for kids at 2026-11-08T19:43:02-05:00 by evening rule 3 to https://garden:8084/tasks/next
decisions-1  | decision deny GET https://elsewhere.example/ (default) for kids at 2026-11-08T19:44:15-05:00 by no rule
```

A request that no rule decided is a `deny` `by no rule`. `dw logs decisions | grep deny` lists the blocked requests, and `grep` on a host name or a client group narrows it the same way. `dw logs -f decisions` watches the decisions arrive while someone browses. `dw logs` with no names shows the last 100 lines of every service, and `dw logs --help` lists the options, which are the ones `docker compose logs` takes: `-f`, `-n` or `--tail`, `--since`, and `-t`.

The lines are kept in the containers, so `dw down`, `dw restart`, and a reboot remove them. To keep them while you work out a problem, use `dw down --keep`, which stops the containers without removing them, or `dw restart --keep`, which keeps each container whose settings and image did not change and names any that had to be recreated. `dw logs` shows what a stopped container logged, and the next `dw up` carries on from it. `dw logs boot` shows what the start at boot logged.

Each decision is also appended to `/tmp/decisions.jsonl` inside the `decisions` container. An entry holds the request the proxy sent, the household-local time, the client group and the site group (either of which may be `default`), the rule set and rule that decided, and the decision returned.

A forwarded response is also reported to `POST /v1/observations`. Each report has the client IP, the absolute URL, the time, and how many body bytes have moved since the previous report. A short transfer is one report. A long one is reported about once a minute while bytes are still moving, and once more when it finishes. A connection that sits open without new bytes is not reported again. Denied and redirected requests are not reported. If the observation service is down, the page is still allowed, denied, or redirected as already decided. A report is filed under the classified client group and site group, including `default`, and under each quota whose rule set accepts it. School traffic stays on the school site group and does not move the entertainment quota.

An allow remembers that flow. A later report cuts it only when a clock assumption or a volume ceiling from that allow has run out, and the access rules no longer allow the request. The clock covers a window that was evaluated, a task count that was met (until midnight), and a time quota whose true branch was taken. Volume is the byte balance at the limit plus grace, and only for a `volume_remaining` check that was taken. A quota that is only metered does not cut the stream. The defaults are five minutes and `1M`. A quota's own grace wins on that quota, and zero grace stops at the limit. The household `time_grace` is what a window or a task count adds. An empty answer, a timeout, a report with no recorded allow, or any other answer leaves the transfer running. A new request is still refused at the limit, before any of this grace.

## Parent portal

A parent opens `https://<this machine>:8084/parent/` in a browser. The port is `POLICY_PORT`, `PORT_BASE+4`, and `/` on that port opens the portal too. The same port serves the task pages. The portal is HTTPS. The certificate is signed by the household CA below, for the names in `PARENT_NAMES`, and it lasts 30 days. It is replaced on the next start when 3 days or less remain, or when a configured name is missing from it. A browser that does not trust the CA gets a warning. Plain HTTP does not return the portal.

The portal opens on a sign-in screen. After sign-in, every page has a sidebar down the left with the pages, who is signed in, and Sign out. Drag the sidebar's right edge, or focus it and use the arrow keys, to make it wider or narrower. The chevron at its top folds it to a thin strip. The browser remembers both. Each page has a context bar at the top for its choices, and a status bar at the bottom that says which timezone the times are in. Every page and every choice on it has its own address, so a page can be bookmarked, reloaded, or sent to the other parent. The old addresses, such as `/attempts?client=younger` and `/attempts/42`, open the same page in the portal, and `/usage` opens the usage graph. Sign out ends the session on the service. See [docs/parent-portal.md](docs/parent-portal.md) for how the portal is built.

### Usage

Usage in the sidebar expands into Minutes and Bytes, at `/parent/usage/minutes` and `/parent/usage/bytes`. Each draws a line graph of usage over a date range. The context bar chooses which client groups, site groups, and quotas to count, with nothing chosen counting all of them, and Group by draws one line per client group, site group, or quota, or one Total line. `default` is in both group lists. Site groups and quotas cannot be chosen together, because the usage by quota is not kept per site group. The date range is Today, Yesterday, This week, This month, Past week, Past month, Previous week, Previous month, or Custom days. Weeks run Sunday to Saturday, and every day and time is the household timezone. A range of two days or less has a point per hour, up to 92 days a point per day, and longer a point per week. Minutes counts the buckets that have ended, as the quota balance does. Bytes counts every stored bucket, labelled in KB, MB, GB, or TB. A line adds every stored row it covers, so traffic to two site groups in the same bucket, or counted by two quotas, counts twice. The legend gives each line's total, and pointing at a line, or focusing it and using the arrow keys, says the value at a point. Every choice is in the page address. Save preset keeps the choices under a name for both parents. Default is what Minutes and Bytes open with, every group by client group over the past week until a preset is saved over it. A preset keeps a relative range such as Past week by name, so it always shows the week to now. The old `/usage` address opens Minutes.

### Attempts

Attempts in the sidebar opens `/parent/attempts`, which is also the portal home. Choose a client group in the context bar to see where the day stands: today's score, the required tasks still outstanding, the potential tasks still available, and the passes waiting on the required tasks. Below that are the group's attempts, newest first: the task's name and type, whether it was Required, Potential, Practice, or a Parent check, the household-local start and finish, the outcome, and the duration. An attempt left open on an earlier day is Unfinished. Open an attempt by its task name, such as `/parent/attempts/42`, to read the answers that were stored. Record parent check in the context bar stores a pass for the client group on show. The child has no page that records one.

### Tasks

Task Administration in the sidebar lists every task by name, with its type in brackets where two tasks share a name. Open one, such as `/parent/tasks/spelling/spelling`, to change its client groups, cooldowns, limits, and dates. Leave a box empty to leave that rule off. A spelling task's page also has its spelling settings and its word list, with a Pool pull-down in the context bar to show Current and revision words, either one, or the Attic. Click a word to hear it, and Play beside it to hear its sentence. Change a word's pool to move it between Current and Revision, or out of the Attic. Retire is the only way into the attic: it asks first, then moves the word's recordings into `spelling/attic` at once. Nothing is ever deleted, except that a recording kept from the browser replaces the word's old one.

Each word has three recording buttons: Re-record word and sentence, Re-record word, and Re-record sentence. Each opens a dialog that records from the computer's microphone, which the browser asks for the first time. Press any key, wait for "Get ready…" to turn into the recording indicator half a second later, so the key itself is not recorded, then say each line it shows with a pause after it, and press Enter to stop. Nothing needs typing while recording. The service cuts the take as `bin/cut-clips` would, with the same defaults, and plays each clip with what it is meant to be, such as `Playing: rope (word)`. Keep (K) it, Junk (J) it as noise and hear the next clip, Discard (D) it as a poor take of the item, mark the item Missing (M) to try the same clip for the next item, Replay (R) it, or go Back (B). The Advanced section changes the cut settings, and Cut cuts the same take again without recording it again. Confirm writes the kept clips into the word's own pool directory as `<word>.opus` and `<word>.sentence.opus`, replacing an older recording of that kind in any format, such as `rope.mp3`. Cancel changes nothing. Takes and clips waiting for Confirm are kept in `.recordings` in the data directory, and anything left there for a day is removed. If the parent session ends while recording, the dialog keeps the take: sign in again in another tab and press Upload.

The Directories group has a pull-down for each of the Current Pool, Revision Pool, Attic, and Alphabet directories, listing every directory under `spelling/` in the data directory. New directory…, at the end of each, makes a directory there at once, such as `year-4/current`, and chooses it. Save makes the task use the chosen directories. A save that would leave the task with nothing to ask, such as two new, empty pools, is refused, and the page lists the words in the chosen directories so they can be filled from the Words menu.

The Words menu in the spelling page's context bar has three ways to set up words, each at its own address such as `/parent/tasks/spelling/spelling/words/replace-current`. Replace Current is the weekly change, made in one go. Add to Current and Add to Revision add a batch of words to that pool and move no word that is not listed. A task has one setup in progress at a time, and choosing another asks before throwing it away. Opening one while the page shows unsaved directories sets up the words in those directories, and its Apply saves them with the words. A new spelling task has the Words menu as soon as its name and type are locked in, so new directories can be filled before the task is saved: each Apply puts the words in place and comes back to Create New Task, and Save writes the task once both pools have words. Type or paste the words under Add words, such as `rope`, `read.1`, or `don't`, and press Check. Commas, spaces, and new lines all separate words, and any run of them counts as one separator, so a list copied from an email or a class posting, such as `(rope, cat, dog)`, can be pasted as it is. Anything that is not a letter is trimmed from the very start and end of the pasted text, such as those brackets, but not from between the words: a word with anything else in it, such as `rope2` or `cat;dog`, or a word listed twice, is refused naming its line, to be tidied by hand. Curly apostrophes, as in `don’t`, are taken as plain ones. The list shows where each word is now (New, Current, Revision, or Attic) and whether it has a word clip and a sentence clip. Type a sentence for each word in its box. The sentence is only a prompt for recording, and is never written into a pool or a policy file. A plain `read`, when the pools have `read.1` and `read.2`, asks which of them belong to the week, or offers a new number. Change a word with its pencil button, and remove it with its cross. Save, or Ctrl+S, keeps the list on the service, so reloading the page or coming back later carries on. Record all prompts every word, each followed by its sentence, and Record missing prompts only the pieces with no clip yet. The review steps through the lines and the clips together, showing the line expected, such as `3 of 18: rope (sentence)`, with the same keys as above. Each row also has the three recording buttons. Kept clips wait with the setup, in `.weeks` in the data directory, and nothing in the pools changes until Apply. Apply waits until every word has a word clip, then in one step moves each listed word into the mode's pool, and for Replace Current moves last week's current words that are not on the list to revision. It writes the kept clips into that pool in place of older ones, and gives an existing plain `read` the next free number, with its sentence, when the list adds a new `read.1`. When the new pools would not load with the task's targets, Apply is refused and the Targets box changes them in the same step. Cancel asks first, then throws the setup away and leaves the pools as they were.

A parts of speech task's page has its Timeout and Correct Answers Required, then each sentence as a table like the one he sorts, with the sentence on top and a row per part of speech. Drag a word into a row as he does, or Tab to it and press Enter to choose its row from a menu. The pencil edits the sentence. Sorted words still in the new text keep their rows, and the rest are named under it. Each row's name is a box, Enter moves to the next and adds a row after the last, and Enter in an empty one removes it. Add sentence, or Alt+N, adds a sentence with the rows of the one above. A name that is not a part of speech, such as `Subject`, is a warning. An empty name, a sentence with no words or nothing sorted, or no sentences at all stop the save until fixed. A save writes only the sentences that changed, with their names tidied, so `Nouns` is written `noun`.

Save in the context bar, or Ctrl+S, saves every change on the page. The task is rewritten in whichever policy file defines it, with its comments and layout kept, checked as `dw check` would, and applied to every service as `dw reload` would. A save the policy would refuse is refused, and the status bar says why. A change made by hand on the server since the page opened stops the save until the page is reloaded. Leaving the page with unsaved changes asks first. See [Editing a task from the parent portal](docs/hierarchical-policy.md#editing-a-task-from-the-parent-portal).

### Parent accounts

Add a parent account after the stack is up. The password is read once. It is stored as an Argon2id hash and it is not written into `config/policy.yaml`.

```sh
docker compose exec decisions python -m policy.accounts ada
```

`bin/add-parent ada` does the same from any directory, and is what an installed daywarden uses (see [Installing on another machine](#installing-on-another-machine)).

Type the password and press Enter. Running the command again for the same username replaces the password and ends that account's sessions. With no account, the portal stays closed and shows no usage or attempts. A session ends after 15 minutes without an accepted request, or 180 minutes from sign-in, whichever comes first. A portal tab left open does nothing by itself, so it does not keep a session going. After a session ends, the next click shows the sign-in screen, and signing in opens the page that was clicked. An action such as Record parent check is not repeated by the sign-in. Press it again. `PARENT_IDLE` and `PARENT_LIFETIME` in `.env` change those limits. Each value is a duration such as `15m` or `3h`. A value that is not a positive duration stops the service at startup.

## Certificate authority

The CA is created the first time the proxy starts and reused after that. The directory is `CA_VOLUME_PATH` in `.env` (default `data/ca`).

Copy this PEM certificate out of that directory:

```text
data/ca/mitmproxy-ca-cert.pem
```

The name stays `mitmproxy-ca-cert.pem` when `CA_VOLUME_PATH` changes. Do not copy `mitmproxy-ca.pem`; that file also holds the private key.

Installing the certificate, and pointing Firefox or Chromium at the proxy, is written up in [docs/child-computer.md](docs/child-computer.md). Both of those computers run Arch Linux. Firefox is the one they use.

## Configuration

`.env` sets the ports, the policy server's names, and the CA directory. A value you have already exported wins, so `PARENT_NAMES="localhost,127.0.0.1" make up` uses that list. `make show-env` prints the names and the CA directory `up` will use:

| Variable | Meaning |
| --- | --- |
| `PORT_BASE` | The first of a block of 10 ports on this machine, 8080 when it is left out. The proxy is on `PORT_BASE`, the policy pages on `PORT_BASE+4`, and the auto-configuration file on `PORT_BASE+8`, so the defaults are 8080, 8084, and 8088 |
| `PROXY_PORT` | Port on this machine that clients use for the proxy. Leave it out to use `PORT_BASE`. Set, it wins over `PORT_BASE` |
| `POLICY_PORT` | Port on this machine for the policy pages, over HTTPS. Leave it out to use `PORT_BASE+4`. The container still binds HTTPS on 8443 |
| `PROXY_CONFIG_PORT` | Port on this machine for the proxy auto-configuration file, `/proxy.pac` and `/wpad.dat`, over plain HTTP. Leave it out to use `PORT_BASE+8` |
| `PARENT_NAMES` | DNS names and IP addresses on the parent certificate. They are also the policy server's names that the proxy forwards without a decision, other than `localhost`, `127.0.0.1`, and `::1`. The proxy reads them on `dw restart` |
| `PARENT_IDLE` | Idle limit for a parent session. Defaults to `15m` |
| `PARENT_LIFETIME` | Lifetime of a parent session from sign-in. Defaults to `180m` |
| `CA_VOLUME_PATH` | Directory that holds the CA, and the parent page key, across container restarts |

If you point `CA_VOLUME_PATH` somewhere new, create that directory and own it before the first start, so the certificate is readable by you.

`dw up` and `dw restart` work out the three ports from `PORT_BASE`, and so do `make up` and the start at boot, because Compose cannot add numbers. A bare `docker compose up` uses the ports for `PORT_BASE` 8080. `dw up` and `dw restart` refuse a `PORT_BASE` that is not a whole number, one that puts a port above 65535, and two ports set to the same number, and start or stop nothing. A change to `PORT_BASE` needs `dw restart`. `install.sh` warns about each of the three ports that another program is using, and leaves the port settings in an existing `.env` alone. An install from before `PORT_BASE` that sets `PROXY_PORT=8080` and `POLICY_PORT=8090` keeps those ports. Delete both lines and run `dw restart` to move the policy pages to 8084.

| File | Meaning |
| --- | --- |
| `config/policy.yaml` | Household policy: client groups, site groups, windows, quotas, rule sets, and which hosts the proxy auto-configuration file sends direct. `default` is the implicit group for an address or a URL that matches nothing configured |
| `config/bypass.txt` | Host globs that are forwarded without asking, including while the policy service is down. It is for other hosts, such as the school hosts in the sample, but list the policy server's names here as well: this file is read on every request, while `PARENT_NAMES` applies only after a restart. `dw check` warns about a name in `PARENT_NAMES` this file does not match |

### Direct entries and bypass.txt

The proxy auto-configuration file, `http://<this machine>:<PROXY_CONFIG_PORT>/proxy.pac`, tells a browser which hosts to open directly, without the proxy. Those are the direct entries. `config/bypass.txt` is different: it lists hosts that the browser does send to the proxy, and that the proxy forwards without asking the policy. A direct entry never reaches the proxy at all, so nothing is logged or decided for it. A host in `bypass.txt` is still seen by the proxy.

The direct entries are on by default. The `proxy_configuration` section of `config/policy.yaml` turns each one off, and adds more under `extra`:

```yaml
proxy_configuration:
  direct:
    localhost: true          # localhost, *.localhost, 127.0.0.0/8, and ::1
    plain_host_names: true   # a host name with no dot, such as printer
    policy_server: true      # PARENT_NAMES, hostname, and this machine's own names and addresses
    local_subnets: true      # an IP address inside a subnet of this machine's real interfaces
    local_domains: true      # each search domain of this machine, and every name under it
    extra:
      - "*.home.arpa"        # a host glob, with * and ? as in bypass.txt
      - .lan.example         # a domain, and every name under it
      - nas.example.net      # one host name
      - 10.8.0.0/16          # an IPv4 or IPv6 subnet, or one address
```

A switch left out is on. `extra` items go direct even when every switch is off. Neither the switches nor `extra` change `bypass.txt`, and the proxy treats a host in `extra` like any other if a browser sends it anyway. `dw check` lists each mistake in the section with its file and line, and the summary that `dw check` and `dw reload` print names the configuration URL, the switches that are on, and the `extra` items. `dw reload` applies a change to the next fetch of the file, and no container restarts. A browser fetches the file again only when it starts or is told to. See [docs/child-computer.md](docs/child-computer.md#when-a-browser-fetches-the-file).

**A direct entry takes a site outside the policy.** A LAN site that a browser opens directly is not decided, and bedtime and quotas do not apply to it. Turn off `local_subnets` and `local_domains` to keep a LAN media server under the policy. The direct entries do not stop a child going direct to the internet: the firewall rule in [docs/child-computer.md](docs/child-computer.md#opnsense-rule-tips) does.

The `autoconfig` service serves the file. It uses the host's network, so it sees this machine's own interfaces, and reads them and the search domains on every fetch. With it stopped, the proxy and the policy pages keep working, and a browser that already has the file keeps using it.

## Maintenance

Maintenance commands are scripts in `bin/`, run on the machine running Compose. Each one runs its job inside the decisions container, against the same database and policy file as the service, so the stack has to be up. Link them onto your `PATH` once:

```sh
ln -s "$PWD"/bin/rm-attempts ~/bin/
```

`rm-attempts` removes stored task attempts, for example to try a task again without waiting out its cooldown. `rm-attempts --help` lists every option. `--task` matches a task name of any type, and `--type` matches the type stored with each attempt, so together they match one task, and `--type` works even when the policy file does not load. `--client`, `--task`, and `--type` may each be given more than once; several values for one filter match any of them, and different filters must all match. `--older-than` and `--newer-than` take an age such as `30m`, `2h`, or `7d`, measured from the finish, or from the start of an attempt still in progress. Without `--yes` it only lists what matches. With no filter it refuses unless given `--all`.

```sh
rm-attempts --client younger --task sums
rm-attempts --client younger --task sums --yes
rm-attempts --type arithmetic --newer-than 2h --yes
```

A removed attempt is gone from `/parent/attempts`. A removed pass no longer counts toward today's `tasks_required` and no longer starts a cooldown. A removed failure or abandonment is no longer a skip day. The change takes effect on the next request, with no restart.

## Recording spelling clips

`bin/cut-clips` cuts a recording of several letters, words, or sentences into separate clips at the pauses, and asks you to name each one. It runs on the machine running Compose, not in a container. It needs `ffmpeg` built with `libopus` (`ffplay`, which comes with it, for `--play`) and the Python packages in `policy/requirements.txt`, which include `pydub` and `audioop-lts`:

```sh
sudo pacman -S ffmpeg
make venv
ln -s "$PWD"/bin/cut-clips ~/bin/
```

`make venv` installs the packages into `.venv` in the repository, once (see [Tests](#tests)). The tool uses `.venv` when it is there, otherwise `python3`. Set `PYTHON` to use another interpreter, such as `PYTHON=~/venvs/daywarden/bin/python cut-clips ...`.

Record a take in any format ffmpeg reads, such as `.wav`, `.mp3`, `.m4a`, `.ogg`, `.opus`, `.flac`, or `.webm`. Say each item clearly, then pause for a second or more before the next one. A shorter pause, such as the gaps between the words of a sentence, stays inside one clip. Keep the room quiet, and keep coughs and bumps away from the items.

Check what the tool finds before naming anything. `--list` prints each clip's number, start time, and length, and how many short sounds it ignored, and writes nothing:

```sh
cut-clips alphabet.m4a --list
```

Before it looks for clips, the tool brings the whole recording to an even perceived loudness, so clips from different takes, rooms, or microphones play at the same volume. It measures the loudness of the whole take (EBU R128, in LUFS) and applies one gain to all of it, so a quiet item stays as much quieter than its neighbours as you said it. The first line it prints shows the loudness it measured, the gain, and the loudness it reached, such as `Loudness -29.4 LUFS, raised 11.4 dB to -18.0 LUFS.` `--loudness` sets the target (default `-18`, from `-40` to `-10`). If the gain would push a peak, such as a plosive "p", above -1 dBFS, a limiter holds back just that peak instead of turning the whole take down, and the line ends `with peaks limited to -1 dBFS`. A take that is silent or shorter than 0.4 s cannot be measured and is left as it is. `--no-normalize` cuts the take at the loudness it was recorded.

If the count is wrong, tune the detection and list again:

- Two items run together: pause longer when recording, or lower `--min-silence` (default `700` ms, at least `200`).
- One item is split in two, such as a sentence at a breath: raise `--min-silence`.
- A soft ending such as the "s" in "ess" is cut short, or a quiet item is missing: raise `--threshold` (default `35`, in decibels below the loudest point). Background noise counted as a clip: lower it.
- A real item is ignored as a short sound: lower `--min-speech` (default `150` ms).

A take with no item in it, only room noise however loud, has no clips: the loudest moment must be at least 15 dB above the quietest tenth of the take.

Then cut the take into a pool directory and name each clip as it is offered:

```sh
cut-clips alphabet.m4a --out ~/daywarden/spelling/alphabet --play
```

The tool prints how many clips it found, then asks for each name in order: `Clip 3 of 28 at 0:05.20 (0.48 s):`. With `--play` it plays each clip first, and `?` plays it again. Each name writes `<name>.opus`. An empty name skips the clip. `--bitrate` sets the Opus bitrate (default `32k`). Each clip keeps a guard of the recording either side of the speech, faded in over the leading guard and out over the trailing one so clips join without clicks. `--guard` sets its length (default `100` ms, at least `10`). The fade always lasts the whole guard and never touches the speech, so a shorter guard gives tighter joins and a quicker fade. A guard longer than the pause between items can pick up the faded edge of the next item.

Names follow the spelling pool rules, and a name the policy would refuse is explained and asked for again:

| Recording | Name | File |
| --- | --- | --- |
| A letter of the alphabet, for practice mode | `a` to `z`, `dash` for `-`, `apostrophe` for `'` | `a.opus`, `dash.opus` |
| A word | the spelling | `rope.opus`, `don't.opus` |
| One of two words spelled the same | the spelling and a number | `read.1.opus`, `read.2.opus` |
| A sentence that uses a word | the word's name and `.sentence` | `rope.sentence.opus`, `read.2.sentence.opus` |

Leave off the extension. If `rope.opus` is already there, the tool asks before replacing it. If another file is already the clip for `rope`, such as `rope.mp3` or `Rope.opus`, it asks before replacing that, and removes the old file once the new one is written. Answering no asks for the name again. The question is `[y]es/[N]o/[a]lways/ne[v]er`, and pressing Enter means no. Answer `a` (always) or `v` (never) to give the same answer to every later replace question in the run, including in later recordings. The tool then prints `Replacing b.opus.` or `Keeping b.opus.` instead of asking. After never, it asks for another name, and an empty name skips the clip.

Clips are written to a hidden file and renamed into place, so a quiz starting at the same moment never sees half a clip. Ctrl-C or end of input stops the tool and keeps the clips already written. At the end it prints how many clips it wrote and skipped, and warns about anything in the directory that would stop the policy loading, such as `rope.sentence.opus` with no `rope.opus`.

To cut several recordings, such as a week's words recorded in two takes, give them all at once. Each is cut in turn, in the order given, with the same options:

```sh
cut-clips words-1.m4a words-2.m4a sentences.m4a --out ~/daywarden/spelling/current
```

Each recording starts with `Recording 2 of 3: words-2.m4a` and its own loudness line, clip count, and summary. The last line totals the clips written from all of them. With `--list`, each recording is listed under its own heading. If any recording does not exist, the tool stops before cutting anything, so a typo does not cost you a session of naming. A file ffmpeg cannot read is reported and skipped, and the rest are still cut, with an exit status of 1. Ctrl-C or end of input stops the whole run and says how many recordings were not cut. The pool warnings are checked once, after the last recording, so a `rope.sentence` from the first recording is not reported when `rope` comes in a later one.

## Installing on another machine

The stack can run on another Arch Linux machine on the local network, without a clone of this repository or a container registry. Build a package here, on a machine with Docker:

```sh
make dist
```

That builds the policy image and a proxy image with the addon copied in, saves both into the package, and writes `dist/daywarden-<version>.tar.gz`. The version is the build time, such as `20261105-184500`, and the images are tagged with it. The package holds the repository's `config/policy.yaml` and `config/bypass.txt` as they are now, and `.env` with the CA and data directories moved under `~/daywarden`. It does not change `make up` or this repository's `.env`, and it does not check for uncommitted changes.

Copy the tarball to the target, unpack it, and run the installer as the user who will run daywarden, not as root:

```sh
scp dist/daywarden-20261105-184500.tar.gz tundra:
ssh tundra
tar -xzf daywarden-20261105-184500.tar.gz
cd daywarden-20261105-184500
./install.sh
```

The installer checks everything first and changes nothing if something it needs is missing. Docker, the `docker compose` plugin, a running Docker daemon this user can reach without `sudo`, `git`, for the [config history](#config-history), a package built for this machine's CPU architecture, and no file of its own in `~/bin` named like one of the commands below are required. Each problem is printed with the command that fixes it, such as `sudo pacman -S docker-compose`. Docker not enabled at boot, no user systemd manager (in a `su` session), a port from `.env` already in use, worked out from `PORT_BASE` as `dw` does, `~/bin` missing from the `PATH`, and a missing `python3` or Opus-capable `ffmpeg` are warnings: the install carries on. It never edits `~/.bashrc`. It then loads the images and lays out:

| Path | On install |
| --- | --- |
| `~/daywarden/docker-compose.yml`, `VERSION` | Always replaced |
| `~/daywarden/.env` | Created only if missing. Never overwritten |
| `~/daywarden/config/policy.yaml`, `config/bypass.txt` | Created only if missing. Never overwritten |
| `~/daywarden/config/tasks.d/*.yaml`, the task files the sample `policy.yaml` includes | Created only along with a new `policy.yaml`, and only if missing. Never overwritten |
| `~/daywarden/.env.sample`, `config/*.sample`, `config/tasks.d/*.sample` | Always replaced with the package's copy |
| `~/daywarden/config/.git`, `config/.gitignore` | The [config history](#config-history). Created only if missing |
| `~/daywarden/ca/` | The CA, created by the first `dw up` |
| `~/daywarden/data/` | Recordings, such as `data/spelling/current` |
| `~/daywarden/bin/`, `lib/` | Always replaced. The commands, and the Python source `cut-clips` runs |
| `~/daywarden/venv/` | The `cut-clips` environment, built from PyPI |
| `~/bin/dw`, `rm-attempts`, `add-parent`, `cut-clips` | Links into `~/daywarden/bin` |

On a first install, `PARENT_NAMES` in the new `.env`, and the policy-server lines in `bypass.txt`, are this machine's hostname, each `<hostname>.<suffix>` for the search suffixes in `/etc/resolv.conf` that resolves to an address on this machine, `localhost`, and `127.0.0.1`. The summary lists each name it added, and each it skipped with the reason, such as `tundra.bakuna.net: resolves to 192.168.12.5, not this machine`. Add other names or IP addresses for this machine to `PARENT_NAMES` by hand. The household database stays in the Compose volume `daywarden_policy-data`, which reinstalling, `dw down`, and `dw up` keep. The new machine starts with its own CA and no accounts: point the child computers at its configuration URL, or its proxy port, and give them `~/daywarden/ca/mitmproxy-ca-cert.pem`, as in [docs/child-computer.md](docs/child-computer.md).

### Running it with dw

```sh
dw up          # check the policy, start, wait until every service is healthy, and print the configuration URL
dw status      # version, start at boot, the configuration URL, and each service. Exits 0 only when all are healthy
dw reload      # check config/policy.yaml and apply it to every service without restarting a container
dw check       # check the policy and list every error. Changes nothing
dw restart     # check the policy, then replace every container. Applies .env changes and a new version
dw down        # stop and remove the containers. The CA, database, configuration, and recordings stay
dw logs        # the last 100 lines of each service. dw logs -f decisions follows the decisions
dw logs boot   # what the start at boot logged
add-parent ada
```

`dw logs` takes service names, `decisions`, `observations`, `proxy`, and `autoconfig`, and the options of `docker compose logs`: `-f` to follow until Ctrl-C, `-n 20` or `--tail all` for more or fewer lines, `--since 10m` or `--since 2026-11-08T13:00`, and `-t` for the time of each line. It works with a port mistake in `.env`, and it shows what stopped containers logged. When none of the services it shows is running, `-f` shows what they logged and returns, because no new lines can come. `dw down`, `dw restart`, and a reboot remove the containers and what they logged. `dw down --keep` and `dw restart --keep` keep them. See [Decision and observation logs](#decision-and-observation-logs).

A broken policy stops `dw up` and `dw restart` before anything is started or stopped, with `dw: the policy has 2 errors. daywarden was not started.` (or `Nothing was restarted.`) and every error. A running daywarden keeps running with the policy it had. `dw restart` on a stopped daywarden starts it, the same as `dw up`. Whether a parent stays signed in across `dw restart` is the same as across `dw down` and `dw up`.

`dw` works from any directory and always acts on `~/daywarden`. As with `make up`, a variable already in the environment wins over `.env`. `rm-attempts` and `add-parent` run in the decisions container and say `daywarden is not running. Start it with dw up.` when it is not.

### Start at boot

`dw enable` writes the systemd user service `~/.config/systemd/user/daywarden.service`, enables it, and turns on lingering for this user (`loginctl enable-linger`), so daywarden starts at boot without anyone logging in. No `sudo` is needed. It does not start a stopped daywarden, and a running one keeps running and is tracked by the service. While enabled, `dw up` and `dw restart` also start the service, and `dw down` stops it. At boot the service waits up to two minutes for Docker, then checks the policy. If Docker does not answer, or the policy has an error, `dw status` says the last start failed and `dw logs boot` says why. `dw logs boot` takes `-f`, `-n`, and `--since`, and shows the same lines as `journalctl --user -u daywarden`. The shutdown at reboot removes the containers, as `dw down` does. Docker itself must start at boot: `sudo systemctl enable docker.service`. A container that crashes comes back by itself, but Docker does not start daywarden on its own after a reboot: that is only up to `dw enable`.

`dw disable` stops daywarden starting at boot. It does not stop a running daywarden, and it leaves lingering on, because other user services may need it. `loginctl disable-linger` turns that off. A first install asks whether to enable start at boot. An upgrade keeps the current setting.

### Upgrading

Run the newer package's `./install.sh` the same way, overnight if you can, while the child is not using the computer. `.env`, `policy.yaml`, and `bypass.txt` are kept byte for byte, and the new copies land beside them as `.sample` files, so `diff ~/daywarden/.env ~/daywarden/.env.sample` shows what changed. If daywarden is running, the installer asks `Daywarden is running. Restart it to finish the upgrade? [y/N]` before it changes anything. Anything but `y` stops with nothing changed. A yes installs the files, then runs `dw restart`. If the new version refuses the policy, the restart stops before anything is stopped, and the old version keeps running until the policy is fixed and `dw restart` is run again. The config history is kept, and the new `.sample` files make no commit.

Upgrading to the version where a task is its type and its name (S012) needs two steps by hand. First rewrite the tasks in `policy.yaml` and `tasks.d` so that each key under `tasks:` is a task type with its tasks under it, and the `type:` field is gone, as in `config/tasks.d` and [docs/hierarchical-policy.md](docs/hierarchical-policy.md#tasks). A file still in the old layout fails to load. Then start with a fresh, empty database, because attempts stored before this version have no type: stop daywarden, remove the `policy-data` volume, which holds every stored attempt, the usage buckets, and the parent accounts, and start it again, such as `docker compose down -v` then `make up`, or `dw down`, `docker volume rm daywarden_policy-data`, and `dw up` on an installed machine. Add the parent account again as in [Parent accounts](#parent-accounts). A database made before this version is not detected, converted, or refused, and running on one is not supported.

### Config history

`~/daywarden/config` is a local git repository, so every version of `policy.yaml`, `bypass.txt`, and any included policy file can be got back. It has no remote, and nothing is pushed anywhere. The installer creates it, with the files as they are as its first version, and `dw up` creates it again if `config/.git` is removed. Its `.gitignore` leaves out editor leftovers, such as `policy.yaml~`, `.policy.yaml.swp`, and `.#policy.yaml`, and the `.sample` files every install rewrites.

After `dw reload`, `dw up`, or `dw restart` has applied the policy, any uncommitted change in the config directory is committed, and `dw` names the files, such as `Saved in the config history: policy.yaml.` The message is the time in the household's timezone, the user who ran it, and the command, such as `2026-11-08 21:15 -0500 blg: dw reload`. The author is that user at `daywarden.invalid`, and no git setup is needed: `dw` sets the name and email for each commit and changes nothing in `~/.gitconfig`. A policy with an error commits nothing, so a broken edit never becomes a version, and `dw check` never commits. If the commit fails, the reload still applies, and `dw` warns that the change is not in the history, and why.

To get an old version back:

```sh
cd ~/daywarden/config
git log --stat                         # find the version, such as 3f2a9c1
git show 3f2a9c1:policy.yaml           # read policy.yaml as it was then
git checkout 3f2a9c1 -- policy.yaml    # put that version back
dw reload                              # check and apply it
```

The reload commits the restored file as a new version, so the later versions stay in `git log` too.

A save on a parent portal task page is committed the same way, as the parent who signed in, such as `2026-11-08 21:15 -0500 brett: saved task spelling`. When the save finds hand edits that have not been committed, it commits them first as `<time> hand edits found before a portal save`, then the save. Hand edits that fail the check stop the save until they are fixed on the server. Everything the portal writes stays owned by the user who installed daywarden.

In a clone of this repository, `config/` is already inside the repository's own history, so `make up` and `dw up` make no repository of their own there, and say so. Commit changes to `config/` as with any other file in the clone.

The recordings under `~/daywarden/data` are not part of this history.

### Cutting clips on the installed machine

`cut-clips` takes the same options as `bin/cut-clips`, with the recordings under `~/daywarden/data`. Clips are used from the next quiz run, without a restart:

```sh
cut-clips take.m4a --out ~/daywarden/data/spelling/current --play
```

It runs in `~/daywarden/venv`, which the installer builds with `python3 -m venv` and rebuilds only when the requirements or the system Python version change. If that environment is missing, for example because PyPI could not be reached, `cut-clips` says so: run `install.sh` again.

## Tests

```sh
make test
make test ARGS="tests/test_clips.py -q"
```

The tests run in a virtual environment at `.venv`, which is not committed. The first `make test` (or `make venv`) creates it and installs `requirements-dev.txt`: the policy service's `policy/requirements.txt`, including `argon2-cffi` for parent sign-in, plus `pytest`. After that, runs start straight away. The venv is reinstalled only when a requirements file changes. If it breaks after a system Python upgrade, run `rm -rf .venv && make venv`. To run something else with the same packages, use `.venv/bin/python`, such as `.venv/bin/python -m pytest -x`.

Most tests start Compose, so Docker has to be available. They use their own port, CA directory, and policy volume, and they do not touch `data/ca`. The policy service image is built on each `up`, so the tests always run the current code. Tests that need `ffmpeg` or `node` are skipped when those are not installed.

`make test` also runs the parent portal's own tests, with Vitest, and its type check. When Node is installed, it first installs the portal's npm packages from `policy/portal/package-lock.json` into `policy/portal/node_modules`, once, and again only when the lock file changes. `make portal-deps` does that step on its own. To work on the portal with the stack up, run `npm run dev` in `policy/portal` and open `http://localhost:5173/parent/`. Its data requests go to the HTTPS parent port. The decisions image builds the portal itself, so neither the image nor an installed package needs Node.
