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

# Refuse to listen if the addon cannot be loaded. An empty proxy would
# forward every request.
python3 -c '
import importlib.util
import sys
sys.path.insert(0, "/opt/daywarden")
spec = importlib.util.spec_from_file_location("daywarden_addon", "/opt/daywarden/addon.py")
if spec is None or spec.loader is None:
    raise SystemExit("daywarden addon could not be loaded")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
if not getattr(module, "addons", None):
    raise SystemExit("daywarden addon did not register")
'

exec /usr/local/bin/docker-entrypoint.sh "$@"
