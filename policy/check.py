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

``--parent-names`` is ``PARENT_NAMES`` from ``.env``. Each of those names,
other than the loopback ones, that ``bypass.txt`` does not match is a
warning, printed even with ``--quiet``. The proxy bypasses those names
anyway, but only reads ``PARENT_NAMES`` when it starts.

Run with: python -m policy.check [--host-dir DIR] [--refused TEXT] [--quiet] [--parent-names NAMES]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from policy.clock import HouseholdClock, machine_zone, named_zone
from policy.hierarchy import ConfigError, Policy, load, require_yaml
from policy.selection import picker_url, proxy_config_url

CONFIG_MOUNT = "/etc/daywarden"
DEFAULT_POLICY_FILE = CONFIG_MOUNT + "/policy.yaml"
LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})


def policy_file() -> Path:
    return Path(os.environ.get("POLICY_FILE", DEFAULT_POLICY_FILE))


def bypass_file() -> Path:
    return Path(os.environ.get("BYPASS_PATH", CONFIG_MOUNT + "/bypass.txt"))


def bypass_warnings(parent_names: str, bypass: Path) -> list[str]:
    """Return a warning for each policy-server name that the bypass list does not match.

    The proxy matches hosts the same way: globs, ignoring case, against the
    whole host name.
    """
    try:
        text = bypass.read_text(encoding="utf-8")
    except OSError:
        text = ""
    patterns = [line.split("#", 1)[0].strip() for line in text.splitlines()]
    globs = [_glob(pattern) for pattern in patterns if pattern]
    warnings = []
    for token in parent_names.split(","):
        name = token.strip().strip("[]").lower().rstrip(".")
        if not name or name in LOOPBACK_NAMES:
            continue
        if any(glob.fullmatch(name) for glob in globs):
            continue
        warnings.append(
            f"{bypass}: {name} is in PARENT_NAMES and not in this list. The proxy reads PARENT_NAMES only "
            f"when it starts, so {name} only bypasses the proxy until the next restart picks up a change. "
            "Add it here as well."
        )
    return warnings


def _glob(pattern: str) -> re.Pattern[str]:
    return re.compile("".join(".*" if char == "*" else "." if char == "?" else re.escape(char) for char in pattern.lower()))


def load_required(
    path: Path,
    previous: Policy | None = None,
    *,
    warn: Callable[[str], None],
    task_data: bool = True,
    overrides: Mapping[Path, str] | None = None,
) -> Policy:
    """Load the policy for a check or a reload. A missing file is an error here."""
    root = require_yaml(path)
    if not root.is_file():
        raise ConfigError(f"{root}: the policy file does not exist")
    return load(root, previous=previous, warn=warn, task_data=task_data, overrides=overrides)


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
    direct = policy.proxy_configuration
    lines += [
        f"proxy configuration is {proxy_config_url(policy)}",
        f"proxy configuration direct entries: {', '.join(direct.switched_on()) or 'none'}",
        f"proxy configuration extra direct entries: {', '.join(item.text for item in direct.extra) or 'none'}",
    ]
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
    parser.add_argument("--quiet", action="store_true", help="print only warnings for a good policy")
    parser.add_argument("--parent-names", help="PARENT_NAMES from .env, checked against bypass.txt")
    args = parser.parse_args(argv)
    warnings: list[str] = []
    names = [] if args.parent_names is None else bypass_warnings(args.parent_names, bypass_file())
    try:
        policy = load_required(policy_file(), warn=warnings.append)
    except ConfigError as error:
        lines = error_lines(error.problems, [*warnings, *names], args.host_dir, args.refused)
        print("\n".join(lines), file=sys.stderr)
        return 1
    if not args.quiet:
        zone, source = household_zone(policy.timezone, machine_localtime())
        lines = summary_lines(policy, HouseholdClock(zone), source) + warning_lines([*warnings, *names], args.host_dir)
        print("\n".join(lines))
    elif names:
        print("\n".join(warning_lines(names, args.host_dir)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
