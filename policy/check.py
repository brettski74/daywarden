"""Check the household policy without applying it: python -m policy.check

``dw check``, ``dw reload``, ``dw restart``, ``dw up``, and the start at boot
run this in the policy image, so the check is made by the code the services
run. It loads POLICY_FILE the way the decisions service does, including the
spelling word lists under DAYWARDEN_DATA_DIR, with no previous policy, and
changes nothing.

A good policy prints the summary the decisions service logs when it loads
one, then any warnings, and exits 0. A policy with errors prints a count
line, every error, then any warnings, to stderr, and exits 1. A missing
policy file is an error. ``--host-dir`` names the host directory mounted at
/etc/daywarden, so each error shows the path the parent edits.

Run with: python -m policy.check [--host-dir DIR] [--refused TEXT] [--quiet]
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from policy.clock import HouseholdClock, machine_zone, named_zone
from policy.hierarchy import ConfigError, Policy, load, require_yaml
from policy.selection import picker_url

CONFIG_MOUNT = "/etc/daywarden"
DEFAULT_POLICY_FILE = CONFIG_MOUNT + "/policy.yaml"


def policy_file() -> Path:
    return Path(os.environ.get("POLICY_FILE", DEFAULT_POLICY_FILE))


def load_required(
    path: Path,
    previous: Policy | None = None,
    *,
    warn: Callable[[str], None],
    task_data: bool = True,
) -> Policy:
    """Load the policy for a check or a reload. A missing file is an error here."""
    root = require_yaml(path)
    if not root.is_file():
        raise ConfigError(f"{root}: the policy file does not exist")
    return load(root, previous=previous, warn=warn, task_data=task_data)


def shown(text: str, host_dir: str | None) -> str:
    """Return ``text`` with the configuration mount written as the host directory."""
    if host_dir and text.startswith(CONFIG_MOUNT + "/"):
        return host_dir.rstrip("/") + text[len(CONFIG_MOUNT) :]
    return text


def error_lines(problems: Sequence[str], warnings: Sequence[str], host_dir: str | None, after: str = "") -> list[str]:
    """Return the count line, each error, then the warnings."""
    count = len(problems)
    head = f"dw: the policy has {count} error{'' if count == 1 else 's'}."
    lines = [f"{head} {after}" if after else head]
    lines += [shown(problem, host_dir) for problem in problems]
    return lines + warning_lines(warnings, host_dir)


def warning_lines(warnings: Sequence[str], host_dir: str | None) -> list[str]:
    if not warnings:
        return []
    return ["Warnings:", *(f"  {shown(warning, host_dir)}" for warning in warnings)]


def household_zone(timezone: str | None, localtime: Path):
    """Return the zone for timezone, or the machine zone, and a phrase for the log."""
    if timezone:
        return named_zone(timezone), f"timezone {timezone}"
    return machine_zone(localtime=localtime), "timezone of this machine"


def machine_localtime() -> Path:
    return Path(os.environ.get("MACHINE_LOCALTIME", "/etc/localtime"))


def summary_lines(policy: Policy | None, clock: HouseholdClock, source: str) -> list[str]:
    """Return what the decisions service logs about the policy it loaded."""
    lines = [f"household {source}; local time is {clock.local().isoformat(timespec='seconds')}"]
    if policy is None:
        return lines + ["no policy loaded"]
    lines += [
        f"task pages are {picker_url(policy)}",
        f"usage buckets are {span(policy.bucket_length)}",
        f"entry {policy.entry}",
    ]
    for group in policy.client_groups:
        lines.append(f"client group {group.name}: {', '.join(group.ips) or 'no address'}")
    lines.append("client group default: addresses in no configured group")
    for group in sorted(policy.site_groups, key=lambda item: item.priority):
        lines.append(f"site group {group.name}: priority {group.priority}, {len(group.patterns)} patterns")
    lines.append("site group default: urls that match no configured group")
    return lines


def span(seconds: int) -> str:
    """Return a short duration such as 2h, 5m, or 90s."""
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m policy.check", description="Check the household policy.")
    parser.add_argument("--host-dir", help="the host directory mounted at /etc/daywarden, for the paths shown")
    parser.add_argument("--refused", default="", help="text added to the count line, such as Nothing was reloaded.")
    parser.add_argument("--quiet", action="store_true", help="print nothing for a good policy")
    args = parser.parse_args(argv)
    warnings: list[str] = []
    try:
        policy = load_required(policy_file(), warn=warnings.append)
    except ConfigError as error:
        print("\n".join(error_lines(error.problems, warnings, args.host_dir, args.refused)), file=sys.stderr)
        return 1
    if not args.quiet:
        zone, source = household_zone(policy.timezone, machine_localtime())
        print("\n".join(summary_lines(policy, HouseholdClock(zone), source) + warning_lines(warnings, args.host_dir)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
