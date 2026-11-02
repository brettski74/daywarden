# smartproxy

Household explicit proxy. `make up` starts mitmproxy with a certificate authority that stays on disk across container restarts.

## Start

```sh
make up
```

`make down` stops the stack and removes the containers. The CA directory and the policy database stay on disk.

The proxy listens as a normal HTTP proxy. Clients use `PROXY_PORT` from `.env` on the machine that is running Compose.

Every request is sent to the policy service (the Compose service `decisions`) as `POST /v1/decisions`, unless the host is listed in `config/bypass.txt`. The policy service classifies the URL into one site group and the source address into one client group, then walks the rule set named by `entry`. A deny becomes a small HTML page with status `403`. A redirect becomes status `302` with a `Location` header. If the policy service is down, or its answer is not allow, deny, or redirect, the proxy responds `403`. Hosts on the bypass list are forwarded either way.

## The policy file

`config/policy.yaml` is the household policy. The decisions service loads it each time it starts. Edit the file, then run `docker compose restart decisions`. The observations service reads the same file when it starts, so restart that too (`docker compose restart observations`) when an edit changes which traffic is counted. If the file is missing, the service starts with nothing loaded and denies requests.

The file names client groups, site groups, time windows, quotas, and rule sets. `entry` is the rule set where a decision starts. `hostname` is the DNS name external clients use to open the policy server. It is a host, not a URL. Leave it out to use the hostname of the machine running Compose, read from that machine's `/etc/hostname`. The name inside the decisions container is not used. Set it when that name is not the one in the browser's address bar. `port` is the port those clients use. Leave it out to use `POLICY_PORT`. Set it when a reverse proxy presents the pages on a different port. A redirect to the `revision_task` token is `https://<hostname>:<port>/tasks/<name>`, and port 443 is left off. The file does not contain a `revision_task` URL. `timezone` is an IANA name. The sample sets `America/Toronto`. Delete that line to use the timezone of the machine running Compose, which is read from that machine's `/etc/localtime`.

An address that belongs to no client group is the implicit client group `default`. A URL that matches no site group is the implicit site group `default`. Neither group is written in the file. This file grants access only to the younger child's group, so an address in `default` is denied with "No rule granted access.", including a school site.

## Clients

One client group is the computers that share a schedule. The sample enrols the younger child at `192.168.1.40`. That address is a placeholder: replace it with the computer's DHCP reservation, written as an IP or a DNS name. DNS names are looked up once, when the service starts. If a name does not resolve then, the group keeps the addresses it resolved to last time. Restart the decisions service after the reservation changes. The older child is not in the file. A comment there says how to add them.

## Site groups

A site group has a name, a unique integer priority, and glob patterns. Groups are tried lowest priority number first, and the first match wins, so Classroom at priority 10 is picked before a wider pattern at priority 20. Two groups cannot share a priority.

A pattern that contains `://` is matched against the whole URL, without its `#fragment`. Any other pattern is matched against the host only. Matching ignores case. `*` matches any run of characters, including `/`, and `?` matches one character. `*.youtube.com` matches `www.youtube.com` but not `youtube.com`, so list both if you need both.

What remains after every configured group misses is the implicit site group `default`. It has no priority and no patterns, and it is not written in the file.

School is a starter list of Classroom hosts and the Google hosts a Classroom session loads. It is allowed at any time for the younger child, and it has no quota. It is not every school site, and it is not all of Google. Entertainment is YouTube. Monday to Thursday, bedtime denies, school hours redirect to revision, and the evening continues only when today's revision count has reached 2. A `2h` quota then allows the request or denies it. Friday, Saturday, and Sunday are in the file as a starting suggestion, with a wider evening. The implicit `default` site group uses those same hours and the same revision count, and it has no time quota. The school hosts and the policy server named by `hostname` are listed again in `config/bypass.txt`. Edit the two files together. Nothing copies one into the other.

## Rules

Rules live in named rule sets. A site group does not own a list of them. A rule has a `condition` and two optional actions, `when_true` and `when_false`. An omitted action is `continue`. An action is `continue`, `deny` with a message, `redirect` to an absolute `http` or `https` URL or the token `revision_task`, `allow`, or `evaluate` of another rule set. `allow`, `deny`, and `redirect` stop the walk. `evaluate` uses the other set's decision. If the set named by `entry` only continues, the request is denied with "No rule granted access."

A `time_window` condition names a window defined once under `time_windows`. The window is true when the household-local clock is inside any of its periods. The start counts and the end does not, so `07:00–15:00` and `15:00–19:00` do not both match at 15:00. Write clocks as quoted strings, `"07:00"` or `"0700"`. `days` is a weekday, a range such as `monday-thursday`, or a list of those. Leave the day off a period to mean every day. An end clock earlier than the start finishes the next day: Saturday `22:00–07:00` includes Saturday night and Sunday morning, and does not include Saturday morning.

A `tasks_required` condition carries `required`, a count of passed revision tasks. It is true when this client group has at least that many passes stored for the household-local date. One pass on that date adds one. The count resets at local midnight. Another client group's passes do not count. A different count on a different day is a different rule under a different window.

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
{ "action": "redirect", "status": 302, "location": "https://garden:8090/tasks/next" }
```

When the household has an eligible revision task, that location is `https://<hostname>:<port>/tasks/<name>` for the task chosen for the client group. The sample has no tasks yet, so the location is `https://garden:8090/tasks/next`, and that page says there is nothing to revise. A rule that allows the policy server is what lets the page load after the redirect. The host does not have to be on the proxy bypass list.

A task with `type: arithmetic` is a timed quiz on that page: one large question, an answer box, and a timer bar that shrinks as he gets more right. Its `body` sets the operation, `max_timeout`, `min_timeout`, `correct_answers_required`, and weighted `operands`, and a bad body fails the load. The sound effects are the audio files in `policy/static/sounds/correct/`, `incorrect/`, and `timeout/`, one chosen at random per answer. Add or remove a file there and rebuild the policy image. See [docs/hierarchical-policy.md](docs/hierarchical-policy.md#arithmetic-tasks) for the fields, the timing rules, and the stored record.

A task with `type: skip_counting` shows a row of numbers that count up or down by the same step, with blank boxes to fill in. He gets three tries per question, worth 1, 0.5, and 0.25 points. With `maximum_questions` set, an attempt that runs out of questions without enough points is a failure. Every field has a default, so `body: {}` is a working task. Each difference may set its own `minimum_value` and `maximum_value`. The defaults keep counting by 2 under 100. See [docs/hierarchical-policy.md](docs/hierarchical-policy.md#skip-counting-tasks) for the fields, the configuration checks, and the scoring.

## Decision and observation logs

Each decision is appended to `/tmp/decisions.jsonl` inside the `decisions` container. An entry holds the request the proxy sent, the household-local time, the client group and the site group (either of which may be `default`), the rule set and rule that decided, and the decision returned.

A forwarded response is also reported to `POST /v1/observations`. Each report has the client IP, the absolute URL, the time, and how many body bytes have moved since the previous report. A short transfer is one report. A long one is reported about once a minute while bytes are still moving, and once more when it finishes. A connection that sits open without new bytes is not reported again. Denied and redirected requests are not reported. If the observation service is down, the page is still allowed, denied, or redirected as already decided. A report is filed under the classified client group and site group, including `default`, and under each quota whose rule set accepts it. School traffic stays on the school site group and does not move the entertainment quota.

An allow remembers that flow. A later report cuts it only when a clock assumption or a volume ceiling from that allow has run out, and the access rules no longer allow the request. The clock covers a window that was evaluated, a task count that was met (until midnight), and a time quota whose true branch was taken. Volume is the byte balance at the limit plus grace, and only for a `volume_remaining` check that was taken. A quota that is only metered does not cut the stream. The defaults are five minutes and `1M`. A quota's own grace wins on that quota, and zero grace stops at the limit. The household `time_grace` is what a window or a task count adds. An empty answer, a timeout, a report with no recorded allow, or any other answer leaves the transfer running. A new request is still refused at the limit, before any of this grace.

## Usage report

A parent opens `https://<this machine>:8090/usage` in a browser. The port is `POLICY_PORT` in `.env`. The same port serves the attempt review and the task pages. The page is HTTPS. The certificate is signed by the household CA below, for the names in `PARENT_NAMES`, and it lasts 30 days. It is replaced on the next start when 3 days or less remain, or when a configured name is missing from it. A browser that does not trust the CA gets a warning. Plain HTTP does not return the page.

Choose a site group, a client group, or a quota. `default` is in both group lists. A site group also needs a client group, and shows the last 14 household-local days for that pair: the clock times each bucket covered, the time that bucket represents, and the bytes. A bucket that has not ended is listed and left out of the counted time. A day with no traffic says no usage. School traffic, which the entertainment quota does not accept, is listed the same way. A client-group view shows those buckets for every site group. A quota view is today's balance for one client group: ended time against the time limit, and stored bytes against the byte limit. A limit of zero is shown as zero. Leave the client group on "All client groups" and the page lists each client group that has a balance, including `default`. The clock is the household timezone.

Add a parent account after the stack is up. The password is read once. It is stored as an Argon2id hash and it is not written into `config/policy.yaml`.

```sh
docker compose exec decisions python -m policy.accounts ada
```

Type the password and press Enter. Running the command again for the same username replaces the password and ends that account's sessions. With no account, the page stays closed and shows no usage. A session ends after 15 minutes without an accepted request, or 180 minutes from sign-in, whichever comes first. `PARENT_IDLE` and `PARENT_LIFETIME` in `.env` change those limits. Each value is a duration such as `15m` or `3h`. A value that is not a positive duration stops the service at startup. The attempt review at `/attempts` uses the same sign-in. Choose a client group to see that group's attempts, newest first: the task, the household-local start and finish, the outcome, and the duration. Open an attempt to read the answers that were stored. Record a parent check there to store a pass for a client group. The child has no page that records one.

## Certificate authority

The CA is created the first time the proxy starts and reused after that. The directory is `CA_VOLUME_PATH` in `.env` (default `data/ca`).

Copy this PEM certificate out of that directory:

```text
data/ca/mitmproxy-ca-cert.pem
```

The name stays `mitmproxy-ca-cert.pem` when `CA_VOLUME_PATH` changes. Do not copy `mitmproxy-ca.pem`; that file also holds the private key.

Installing the certificate, and pointing Firefox or Chromium at the proxy, is written up in [docs/child-computer.md](docs/child-computer.md). Both of those computers run Arch Linux. Firefox is the one they use.

## Configuration

`.env` sets the listen port, the policy-page port, and the CA directory. A value you have already exported wins, so `PARENT_NAMES="localhost,127.0.0.1" make up` uses that list. `make show-env` prints the names and the CA directory `up` will use:

| Variable | Meaning |
| --- | --- |
| `PROXY_PORT` | Port on this machine that clients use |
| `POLICY_PORT` | Port on this machine for the policy pages, over HTTPS. The container still binds HTTPS on 8443 |
| `PARENT_NAMES` | DNS names and IP addresses on the parent certificate |
| `PARENT_IDLE` | Idle limit for a parent session. Defaults to `15m` |
| `PARENT_LIFETIME` | Lifetime of a parent session from sign-in. Defaults to `180m` |
| `CA_VOLUME_PATH` | Directory that holds the CA, and the parent page key, across container restarts |

If you point `CA_VOLUME_PATH` somewhere new, create that directory and own it before the first start, so the certificate is readable by you.

| File | Meaning |
| --- | --- |
| `config/policy.yaml` | Household policy: client groups, site groups, windows, quotas, and rule sets. `default` is the implicit group for an address or a URL that matches nothing configured |
| `config/bypass.txt` | Host globs that are forwarded without asking, including while the policy service is down. The sample lists the school hosts and the policy server named by `hostname` |

## Maintenance

Maintenance commands are scripts in `bin/`, run on the machine running Compose. Each one runs its job inside the decisions container, against the same database and policy file as the service, so the stack has to be up. Link them onto your `PATH` once:

```sh
ln -s "$PWD"/bin/rm-attempts ~/bin/
```

`rm-attempts` removes stored task attempts, for example to try a task again without waiting out its cooldown. `rm-attempts --help` lists every option. `--client`, `--task`, and `--type` may each be given more than once; several values for one filter match any of them, and different filters must all match. `--older-than` and `--newer-than` take an age such as `30m`, `2h`, or `7d`, measured from the finish, or from the start of an attempt still in progress. Without `--yes` it only lists what matches. With no filter it refuses unless given `--all`.

```sh
rm-attempts --client younger --task sums
rm-attempts --client younger --task sums --yes
rm-attempts --type arithmetic --newer-than 2h --yes
```

A removed attempt is gone from `/attempts`. A removed pass no longer counts toward today's `tasks_required` and no longer starts a cooldown. A removed failure or abandonment is no longer a skip day. The change takes effect on the next request, with no restart.

## Tests

```sh
python -m pytest
```

Most tests start Compose, so Docker has to be available. They use their own port, CA directory, and policy volume, and they do not touch `data/ca`. The policy service image is built on each `up`, so the tests always run the current code. The policy unit tests import the service code. Install `policy/requirements.txt` first. Parent sign-in hashes passwords with Argon2id.
