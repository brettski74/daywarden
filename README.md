# smartproxy

Household explicit proxy. `docker compose up` starts mitmproxy with a certificate authority that stays on disk across container restarts.

## Start

```sh
docker compose up -d
```

The proxy listens as a normal HTTP proxy. Clients use `PROXY_PORT` from `.env` on the machine that is running Compose. Nothing in this stack asks for an authorization decision yet.

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

## Tests

```sh
python -m pytest
```

The tests start Compose, so Docker has to be available. They use their own port and CA directory, and they do not touch `data/ca`.
