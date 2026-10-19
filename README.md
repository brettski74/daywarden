# smartproxy

Household explicit proxy. `make up` starts mitmproxy with a certificate authority that stays on disk across container restarts.

## Start

```sh
make up
```

`make down` stops the stack and removes the containers. The CA directory and the policy database stay on disk.

The proxy listens as a normal HTTP proxy. Clients use `PROXY_PORT` from `.env` on the machine that is running Compose.

Every request is sent to the policy service (the Compose service `decisions`) as `POST /v1/decisions`, unless the host is listed in `config/bypass.txt`. Until the rule engine exists, the policy service answers every request with `config/decision.json`. A deny becomes a small HTML page with status `403`. A redirect becomes status `302` with a `Location` header. If the policy service is down, or its answer is not one of those three decisions, the proxy responds `403`. Hosts on the bypass list are forwarded either way.

## Clients and the household timezone

`config/policy.toml` names the household computers and sets the household timezone. The policy service loads it into its SQLite database (the `policy-data` volume) each time it starts, so edit the file and then run `docker compose restart decisions`. If the file is missing, the service keeps using what it stored last time.

Each client is a display name and an `address`, which is the computer's DHCP reservation written as an IP or a DNS name. DNS names are looked up once, when the service starts. If a name does not resolve then, the client keeps the IPs it resolved to last time. A computer that is not listed still gets the household rules. Listing it gives the decision log a name to show, and later stories hang that computer's revision tasks and usage off the same record.

`household.timezone` is an IANA name such as `America/Toronto`. It decides what "today" and "now" mean for every rule. Leave it out to use the timezone of the machine running Compose, which is read from that machine's `/etc/localtime`.

Each decision is appended to `/tmp/decisions.jsonl` inside the `decisions` container. An entry holds the request the proxy sent, the client name (or `null`), the household-local time, and the decision returned.

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
| `config/policy.toml` | Household timezone and the client computers |
| `config/decision.json` | The decision the policy service returns until the rule engine replaces it |
| `config/bypass.txt` | Host globs that are forwarded without asking, including while the policy service is down |

`config/decision.json` is one of:

```json
{ "action": "allow" }
{ "action": "deny", "status": 403, "message": "Time is up for today." }
{ "action": "redirect", "status": 302, "location": "http://192.168.1.10:8080/tasks/next" }
```

The policy service reads that file on every request. A redirect location is an absolute `http` or `https` URL.

## Tests

```sh
python -m pytest
```

Most tests start Compose, so Docker has to be available. They use their own port, CA directory, and policy volume, and they do not touch `data/ca`. The policy service image is built on each `up`, so the tests always run the current code. Tests named `test_policy_*` that do not start Compose need only the standard library.
