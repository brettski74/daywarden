"""Ask the service in this container to reload the policy: python -m policy.reload

``dw reload`` runs this with ``docker compose exec`` in the decisions and the
observations containers, because each service accepts a reload only from
its own loopback address. For the decisions service it prints the summary
of the policy now in force, then any warnings. A refused reload prints the
count line and every error to stderr and exits 1, and the service keeps the
policy it had.

Run with: python -m policy.reload --service decisions|observations [--host-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

from policy.check import error_lines, warning_lines

TIMEOUT_SECONDS = 60


def port_for(service: str) -> int:
    if service == "decisions":
        return int(os.environ.get("PORT", "8090"))
    return int(os.environ.get("OBSERVATION_PORT", "8091"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m policy.reload", description="Reload the household policy.")
    parser.add_argument("--service", choices=("decisions", "observations"), required=True)
    parser.add_argument("--host-dir", help="the host directory mounted at /etc/daywarden, for the paths shown")
    args = parser.parse_args(argv)
    request = urllib.request.Request(f"http://127.0.0.1:{port_for(args.service)}/v1/reload", data=b"", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            answer = json.loads(response.read())
    except (OSError, ValueError) as error:
        print(f"dw: the {args.service} service did not answer the reload: {error}", file=sys.stderr)
        return 1
    warnings = answer.get("warnings", [])
    if not answer.get("reloaded"):
        after = f"The {args.service} service did not reload and keeps the policy it had."
        print("\n".join(error_lines(answer.get("errors", []), warnings, args.host_dir, after)), file=sys.stderr)
        return 1
    if args.service == "decisions":
        print("\n".join(answer.get("summary", []) + warning_lines(warnings, args.host_dir)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
