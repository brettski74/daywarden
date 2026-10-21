# smartproxy

Household explicit proxy. `make up` starts mitmproxy with a certificate authority that stays on disk across container restarts.

## Start

```sh
make up
```

`make down` stops the stack and removes the containers. The CA directory and the policy database stay on disk.

The proxy listens as a normal HTTP proxy. Clients use `PROXY_PORT` from `.env` on the machine that is running Compose.

Every request is sent to the policy service (the Compose service `decisions`) as `POST /v1/decisions`, unless the host is listed in `config/bypass.txt`. The policy service puts the URL in a site group and runs that group's rules. A URL in no group is denied. A group with no rules is denied too. A deny becomes a small HTML page with status `403`. A redirect becomes status `302` with a `Location` header. If the policy service is down, or its answer is not one of those three decisions, the proxy responds `403`. Hosts on the bypass list are forwarded either way.

## Clients and the household timezone

`config/policy.toml` names the household computers and sets the household timezone. The policy service loads it into its SQLite database (the `policy-data` volume) each time it starts, so edit the file and then run `docker compose restart decisions`. If the file is missing, the service keeps using what it stored last time.

Each client is a display name and an `address`, which is the computer's DHCP reservation written as an IP or a DNS name. DNS names are looked up once, when the service starts. If a name does not resolve then, the client keeps the IPs it resolved to last time. A computer that is not listed still gets the household rules. Listing it gives the decision log a name to show, and later stories hang that computer's revision tasks and usage off the same record.

`household.timezone` is an IANA name such as `America/Toronto`. It decides what "today" and "now" mean for every rule. Leave it out to use the timezone of the machine running Compose, which is read from that machine's `/etc/localtime`.

## Site groups

`config/policy.toml` also holds the site groups, one `[[groups]]` table each, with a `name`, a `priority` and a list of glob `patterns`. They are stored in the same database and loaded at the same time as the clients. Groups are tried lowest priority number first, and the first group with a matching pattern wins, so a `classroom.google.com` group at priority 10 is picked before a `*.google.com` group at priority 20. Two groups cannot share a priority.

A pattern that contains `://` is matched against the whole URL, without its `#fragment`. Any other pattern is matched against the host only. Matching ignores case. `*` matches any run of characters, including `/`, and `?` matches one character. `*.youtube.com` matches `www.youtube.com` but not `youtube.com`, so list both if you need both.

One group may set `default = true`. It takes every URL that no other group matches, whatever its priority number, and its patterns are ignored. If there is no default group, a URL outside every group is denied with "This site is not in a configured group." The sample file has a single default group, `Everything else`, and no rules yet, so every site is denied until rules are added.

## Rules

Rules are `[[groups.rules]]` tables written under a group, in the order they should run. Each rule has a `condition` and two actions, `when_true` and `when_false`. An action is `continue`, `deny` with a message, `redirect` to an absolute `http` or `https` URL (or the token `revision_task`), or `allow`. The first action other than `continue` is the decision. If every rule continues, the request is denied.

`household.revision_task` is the absolute URL substituted for that token. Real task selection replaces it later. A rule that uses the token will not load while the setting is missing.

A `time_window` condition is true when the household-local clock is inside any of its windows. The start counts and the end does not, so `07:00–15:00` and `15:00–19:00` do not both match at 15:00. List `days` as weekday names, or leave `days` out to mean every day. A window may cross midnight: `22:00–07:00` on Saturday includes Saturday night and Sunday morning, and does not include Saturday morning.

A `tasks_complete` condition carries `required`, a count of successful revision tasks. It is true when this client has at least that many stored for the household-local date. A `[[groups.rules.weekdays]]` table sets a different count for one named weekday; every other day keeps `required`. The count is a number in the policy database. Real completions are not recorded yet, so it stays zero unless a test or an administrator writes one. `quota_remaining` is still treated as true.

```toml
[[groups.rules]]
condition = "time_window"
when_true = { action = "deny", message = "It's bedtime." }
when_false = { action = "continue" }

[[groups.rules.windows]]
start = "00:00"
end = "07:00"
days = ["monday", "tuesday", "wednesday", "thursday"]

[[groups.rules]]
condition = "tasks_complete"
required = 2
when_true = { action = "continue" }
when_false = { action = "redirect", location = "revision_task" }

[[groups.rules.weekdays]]
day = "wednesday"
required = 1
```

The three answers a rule can produce are:

```json
{ "action": "allow" }
{ "action": "deny", "status": 403, "message": "Time is up for today." }
{ "action": "redirect", "status": 302, "location": "http://192.168.1.10:8080/tasks/next" }
```

## Decision and observation logs

Each decision is appended to `/tmp/decisions.jsonl` inside the `decisions` container. An entry holds the request the proxy sent, the client name (or `null`), the household-local time, the site group (or `null`), and the decision returned.

A forwarded response is also reported to `POST /v1/observations`. Each report has the client IP, the absolute URL, the time, and how many body bytes have moved since the previous report. A short transfer is one report. A long one is reported about once a minute while bytes are still moving, and once more when it finishes. A connection that sits open without new bytes is not reported again. Denied and redirected requests are not reported. If the observation service is down, the page is still allowed, denied, or redirected as already decided. The service in this repo only records the calls. The ledger that stores them comes later.

## Certificate authority

The CA is created the first time the proxy starts and reused after that. The directory is `CA_VOLUME_PATH` in `.env` (default `data/ca`).

Copy this PEM certificate out of that directory:

```text
data/ca/mitmproxy-ca-cert.pem
```

The name stays `mitmproxy-ca-cert.pem` when `CA_VOLUME_PATH` changes. Do not copy `mitmproxy-ca.pem`; that file also holds the private key.

Installing the certificate, and pointing Firefox or Chromium at the proxy, is written up in [docs/child-computer.md](docs/child-computer.md). Both of those computers run Arch Linux. Firefox is the one they use.

## Configuration

`.env` is the only file to edit for the listen port and the CA directory:

| Variable | Meaning |
| --- | --- |
| `PROXY_PORT` | Port on this machine that clients use |
| `CA_VOLUME_PATH` | Directory that holds the CA across container restarts |

If you point `CA_VOLUME_PATH` somewhere new, create that directory and own it before the first start, so the certificate is readable by you.

| File | Meaning |
| --- | --- |
| `config/policy.toml` | Household timezone, the client computers, the site groups, and their rules |
| `config/bypass.txt` | Host globs that are forwarded without asking, including while the policy service is down |

## Tests

```sh
python -m pytest
```

Most tests start Compose, so Docker has to be available. They use their own port, CA directory, and policy volume, and they do not touch `data/ca`. The policy service image is built on each `up`, so the tests always run the current code. Tests named `test_policy_*` that do not start Compose need only the standard library.
