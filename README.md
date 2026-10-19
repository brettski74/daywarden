# smartproxy

Household explicit proxy. `make up` starts mitmproxy with a certificate authority that stays on disk across container restarts.

## Start

```sh
make up
```

`make down` stops the stack and removes the containers. The CA directory stays on disk.

The proxy listens as a normal HTTP proxy. Clients use `PROXY_PORT` from `.env` on the machine that is running Compose.

Every request is sent to the decision stub as `POST /v1/decisions`, unless the host is listed in `config/bypass.txt`. The stub answers with `config/decision.json`. The file shipped here allows every request. A deny becomes a small HTML page with status `403`. A redirect becomes status `302` with a `Location` header. If the stub is down, or its answer is not one of those three decisions, the proxy responds `403`. Hosts on the bypass list are forwarded either way.

A forwarded response is also reported to `POST /v1/observations`. Each report has the client IP, the absolute URL, the time, and how many body bytes have moved since the previous report. A short transfer is one report. A long one is reported about once a minute while bytes are still moving, and once more when it finishes. A connection that sits open without new bytes is not reported again. Denied and redirected requests are not reported. If the observation service is down, the page is still allowed, denied, or redirected as already decided. The service in this repo only records the calls. The ledger that stores them comes later.

## Certificate authority

The CA is created the first time the proxy starts and reused after that. The directory is `CA_VOLUME_PATH` in `.env` (default `data/ca`).

Copy this PEM certificate out of that directory:

```text
data/ca/mitmproxy-ca-cert.pem
```

The name stays `mitmproxy-ca-cert.pem` when `CA_VOLUME_PATH` changes. Do not copy `mitmproxy-ca.pem`; that file also holds the private key.

Installing the certificate on a child computer is a separate step. Both of those computers run Arch Linux.

## Configuration

`.env` is the only file to edit for the listen port and the CA directory:

| Variable | Meaning |
| --- | --- |
| `PROXY_PORT` | Port on this machine that clients use |
| `CA_VOLUME_PATH` | Directory that holds the CA across container restarts |

If you point `CA_VOLUME_PATH` somewhere new, create that directory and own it before the first start, so the certificate is readable by you.

| File | Meaning |
| --- | --- |
| `config/decision.json` | The decision the stub returns until the policy service replaces it |
| `config/bypass.txt` | Host globs that are forwarded without asking, including while the stub is down |

`config/decision.json` is one of:

```json
{ "action": "allow" }
{ "action": "deny", "status": 403, "message": "Time is up for today." }
{ "action": "redirect", "status": 302, "location": "http://192.168.1.10:8080/tasks/next" }
```

The stub reads that file on every request. A redirect location is an absolute `http` or `https` URL.

## Tests

```sh
python -m pytest
```

The tests start Compose, so Docker has to be available. They use their own port and CA directory, and they do not touch `data/ca`.
