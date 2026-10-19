#!/bin/bash
# mitmproxy's entrypoint maps its user onto the CA directory owner, then
# refuses to start when that group id is not already in the image. Create the
# group first. The key and certificate stay in the mounted directory.

set -o errexit
set -o pipefail
set -o nounset

confdir=/home/mitmproxy/.mitmproxy
mkdir -p "$confdir"

if [[ -f "$confdir/mitmproxy-ca.pem" ]]; then
  owner_source="$confdir/mitmproxy-ca.pem"
else
  owner_source="$confdir"
fi

gid="$(stat -c '%g' "$owner_source")"
if ! getent group "$gid" >/dev/null; then
  groupadd -o -g "$gid" mitmproxy-volume
fi

exec /usr/local/bin/docker-entrypoint.sh "$@"
