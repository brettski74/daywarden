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

The file names client groups, site groups, time windows, quotas, and rule sets. `entry` is the rule set where a decision starts. `revision_task` is the absolute URL substituted for the `revision_task` token. `timezone` is an IANA name. The sample sets `America/Toronto`. Delete that line to use the timezone of the machine running Compose, which is read from that machine's `/etc/localtime`.

An address that belongs to no client group is the implicit client group `default`. A URL that matches no site group is the implicit site group `default`. Neither group is written in the file. This file grants access only to the younger child's group, so an address in `default` is denied with "No rule granted access.", including a school site.

## Clients

One client group is the computers that share a schedule. The sample enrols the younger child at `192.168.1.40`. That address is a placeholder: replace it with the computer's DHCP reservation, written as an IP or a DNS name. DNS names are looked up once, when the service starts. If a name does not resolve then, the group keeps the addresses it resolved to last time. Restart the decisions service after the reservation changes. The older child is not in the file. A comment there says how to add them.

## Site groups

A site group has a name, a unique integer priority, and glob patterns. Groups are tried lowest priority number first, and the first match wins, so Classroom at priority 10 is picked before a wider pattern at priority 20. Two groups cannot share a priority.

A pattern that contains `://` is matched against the whole URL, without its `#fragment`. Any other pattern is matched against the host only. Matching ignores case. `*` matches any run of characters, including `/`, and `?` matches one character. `*.youtube.com` matches `www.youtube.com` but not `youtube.com`, so list both if you need both.

What remains after every configured group misses is the implicit site group `default`. It has no priority and no patterns, and it is not written in the file.

School is a starter list of Classroom hosts and the Google hosts a Classroom session loads. It is allowed at any time for the younger child, and it has no quota. It is not every school site, and it is not all of Google. Entertainment is YouTube. Monday to Thursday, bedtime denies, school hours redirect to revision, and the evening continues only when today's revision count has reached 2. A `2h` quota then allows the request or denies it. Friday, Saturday, and Sunday are in the file as a starting suggestion, with a wider evening. The implicit `default` site group uses those same hours and the same revision count, and it has no time quota. The school hosts and the host of `revision_task` are listed again in `config/bypass.txt`. Edit the two files together. Nothing copies one into the other.

## Rules

Rules live in named rule sets. A site group does not own a list of them. A rule has a `condition` and two optional actions, `when_true` and `when_false`. An omitted action is `continue`. An action is `continue`, `deny` with a message, `redirect` to an absolute `http` or `https` URL or the token `revision_task`, `allow`, or `evaluate` of another rule set. `allow`, `deny`, and `redirect` stop the walk. `evaluate` uses the other set's decision. If the set named by `entry` only continues, the request is denied with "No rule granted access."

A `time_window` condition names a window defined once under `time_windows`. The window is true when the household-local clock is inside any of its periods. The start counts and the end does not, so `07:00–15:00` and `15:00–19:00` do not both match at 15:00. Write clocks as quoted strings, `"07:00"` or `"0700"`. `days` is a weekday, a range such as `monday-thursday`, or a list of those. Leave the day off a period to mean every day. An end clock earlier than the start finishes the next day: Saturday `22:00–07:00` includes Saturday night and Sunday morning, and does not include Saturday morning.

A `tasks_required` condition carries `required`, a count of successful revision tasks. It is true when this client group has at least that many stored for the household-local date. The count resets at local midnight. Real completions are not recorded yet, so it stays zero unless a test or an administrator writes one. A different count on a different day is a different rule under a different window.

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
{ "action": "redirect", "status": 302, "location": "http://192.168.1.10:8080/tasks/next" }
```

## Decision and observation logs

Each decision is appended to `/tmp/decisions.jsonl` inside the `decisions` container. An entry holds the request the proxy sent, the household-local time, the client group and the site group (either of which may be `default`), the rule set and rule that decided, and the decision returned.

A forwarded response is also reported to `POST /v1/observations`. Each report has the client IP, the absolute URL, the time, and how many body bytes have moved since the previous report. A short transfer is one report. A long one is reported about once a minute while bytes are still moving, and once more when it finishes. A connection that sits open without new bytes is not reported again. Denied and redirected requests are not reported. If the observation service is down, the page is still allowed, denied, or redirected as already decided. A report is filed under the classified client group and site group, including `default`, and under each quota whose rule set accepts it. School traffic stays on the school site group and does not move the entertainment quota.

## Usage report

A parent opens `http://<this machine>:8090/usage` in a browser. The port is `REPORT_PORT` in `.env`.

Choose a site group, a client group, or a quota. `default` is in both group lists. A site group also needs a client group, and shows the last 14 household-local days for that pair: the clock times each bucket covered, the time that bucket represents, and the bytes. A bucket that has not ended is listed and left out of the counted time. A day with no traffic says no usage. School traffic, which the entertainment quota does not accept, is listed the same way. A client-group view shows those buckets for every site group. A quota view is today's balance for one client group: ended time against the time limit, and stored bytes against the byte limit. A limit of zero is shown as zero. Leave the client group on "All client groups" and the page lists each client group that has a balance, including `default`. The clock is the household timezone.

Export `PARENT_PASSWORD` before `make up`. A later change needs `docker compose up -d decisions`, so the container is created again. The password is not written into `config/policy.yaml` and it is not stored in the database. With no password, the page stays closed and shows no usage. This gate is temporary. Parent sign-in replaces it. Leave the password set while that port is reachable on the household network.

## Certificate authority

The CA is created the first time the proxy starts and reused after that. The directory is `CA_VOLUME_PATH` in `.env` (default `data/ca`).

Copy this PEM certificate out of that directory:

```text
data/ca/mitmproxy-ca-cert.pem
```

The name stays `mitmproxy-ca-cert.pem` when `CA_VOLUME_PATH` changes. Do not copy `mitmproxy-ca.pem`; that file also holds the private key.

Installing the certificate, and pointing Firefox or Chromium at the proxy, is written up in [docs/child-computer.md](docs/child-computer.md). Both of those computers run Arch Linux. Firefox is the one they use.

## Configuration

`.env` sets the listen port, the usage-report port, and the CA directory:

| Variable | Meaning |
| --- | --- |
| `PROXY_PORT` | Port on this machine that clients use |
| `REPORT_PORT` | Port on this machine for the usage report |
| `CA_VOLUME_PATH` | Directory that holds the CA across container restarts |

If you point `CA_VOLUME_PATH` somewhere new, create that directory and own it before the first start, so the certificate is readable by you.

| File | Meaning |
| --- | --- |
| `config/policy.yaml` | Household policy: client groups, site groups, windows, quotas, and rule sets. `default` is the implicit group for an address or a URL that matches nothing configured |
| `config/bypass.txt` | Host globs that are forwarded without asking, including while the policy service is down. The sample lists the school hosts and the task-site host |

## Tests

```sh
python -m pytest
```

Most tests start Compose, so Docker has to be available. They use their own port, CA directory, and policy volume, and they do not touch `data/ca`. The policy service image is built on each `up`, so the tests always run the current code. Tests named `test_policy_*` that do not start Compose need only the standard library.
