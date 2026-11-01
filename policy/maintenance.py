"""Maintenance commands for the household server.

Run them inside the decisions container, where they read the same
``POLICY_DB`` and ``POLICY_FILE`` as the service:

    docker compose exec decisions python -m policy.maintenance --help

A command that removes stored data lists what it matched and removes
nothing until it is given ``--yes``. It refuses to run with no filter
unless it is given ``--all``.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import TextIO

from policy.tasks import PARENT_CHECK, Attempt, AttemptStore

_AGE = re.compile(r"^(\d+)([mhd])$")
_AGE_UNITS = {"m": "minutes", "h": "hours", "d": "days"}


@dataclass(frozen=True)
class AttemptFilter:
    """Which attempts a command acts on. Empty means that filter is not used."""

    clients: frozenset[str] = frozenset()
    tasks: frozenset[str] = frozenset()
    types: frozenset[str] = frozenset()
    older_than: timedelta | None = None
    newer_than: timedelta | None = None

    @property
    def empty(self) -> bool:
        return not (self.clients or self.tasks or self.types or self.older_than or self.newer_than)


def parse_age(text: str) -> timedelta:
    """Return an age such as ``30m``, ``2h``, or ``7d``."""
    match = _AGE.fullmatch(text.strip())
    if match is None or int(match.group(1)) == 0:
        raise argparse.ArgumentTypeError(f"{text!r} is not an age like 30m, 2h, or 7d")
    return timedelta(**{_AGE_UNITS[match.group(2)]: int(match.group(1))})


def task_type(attempt: Attempt, task_types: Mapping[str, str]) -> str | None:
    """Return the type of the task this attempt is on, or None when the policy file has no such task."""
    found = task_types.get(attempt.task)
    if found is None and attempt.task == PARENT_CHECK:
        return PARENT_CHECK
    return found


def select_attempts(
    attempts: Sequence[Attempt],
    chosen: AttemptFilter,
    *,
    now: datetime,
    zone: tzinfo,
    task_types: Mapping[str, str],
) -> list[Attempt]:
    """Return the attempts every filter matches.

    Several values for one filter match any of them. The age of an attempt
    is measured from its finish, or from its start while it is in progress.
    A stored time without an offset is read in ``zone``.
    """
    found = []
    for attempt in attempts:
        if chosen.clients and attempt.client_group not in chosen.clients:
            continue
        if chosen.tasks and attempt.task not in chosen.tasks:
            continue
        if chosen.types and task_type(attempt, task_types) not in chosen.types:
            continue
        age = now - _aware(attempt.finished_at or attempt.started_at, zone)
        if chosen.older_than is not None and age <= chosen.older_than:
            continue
        if chosen.newer_than is not None and age >= chosen.newer_than:
            continue
        found.append(attempt)
    return found


def main(argv: Sequence[str] | None = None, *, now: datetime | None = None, out: TextIO | None = None) -> int:
    """Run one maintenance command and return the exit status."""
    parser = _parser()
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.command is None:
        parser.print_help(out or sys.stdout)
        return 2
    return args.run(parser, args, now or datetime.now(timezone.utc), out or sys.stdout)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m policy.maintenance",
        description="Maintenance commands for the household server.",
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    remove = commands.add_parser(
        "remove-attempts",
        help="remove stored task attempts, so a task can be tried again",
        description=(
            "Remove stored task attempts. Several values for one filter match any of them, "
            "and different filters must all match. Nothing is removed without --yes."
        ),
    )
    remove.add_argument("--client", action="append", default=[], metavar="GROUP", help="client group")
    remove.add_argument("--task", action="append", default=[], metavar="NAME", help="task name")
    remove.add_argument(
        "--type",
        action="append",
        default=[],
        metavar="TYPE",
        help="task type in the policy file, such as arithmetic",
    )
    remove.add_argument(
        "--older-than",
        type=parse_age,
        metavar="AGE",
        help="finished more than AGE ago, or started for one in progress: 30m, 2h, 7d",
    )
    remove.add_argument(
        "--newer-than",
        type=parse_age,
        metavar="AGE",
        help="finished less than AGE ago, or started for one in progress: 30m, 2h, 7d",
    )
    remove.add_argument("--all", action="store_true", help="match every attempt when no filter is given")
    remove.add_argument(
        "--yes",
        action="store_true",
        help="remove the matching attempts instead of only listing them",
    )
    remove.set_defaults(run=_remove_attempts)
    return parser


def _remove_attempts(parser: argparse.ArgumentParser, args: argparse.Namespace, now: datetime, out: TextIO) -> int:
    chosen = AttemptFilter(
        frozenset(args.client),
        frozenset(args.task),
        frozenset(args.type),
        args.older_than,
        args.newer_than,
    )
    if chosen.empty and not args.all:
        parser.error("remove-attempts needs a filter, or --all to match every attempt")
    task_types, zone = _household(need_types=bool(chosen.types))
    database = Path(os.environ.get("POLICY_DB", "/var/lib/smartproxy/policy.sqlite3"))
    if not database.is_file():
        print(f"no policy database at {database}", file=sys.stderr)
        return 1
    for name in sorted(chosen.types):
        if name not in task_types.values() and name != PARENT_CHECK:
            print(f"no task in the policy file has type {name}", file=out)
    with AttemptStore(database) as store:
        matched = select_attempts(store.everything(), chosen, now=now, zone=zone, task_types=task_types)
        if not matched:
            print("no attempts match", file=out)
            return 0
        _print_attempts(matched, out)
        if not args.yes:
            print(f"{_count(len(matched))} would be removed. Run again with --yes to remove them.", file=out)
            return 0
        removed = store.remove([attempt.id for attempt in matched])
    print(f"removed {_count(removed)}", file=out)
    return 0


def _household(*, need_types: bool) -> tuple[dict[str, str], tzinfo]:
    """Return each task's type and the household timezone from the policy file.

    A policy file that will not load is fatal only when ``--type`` needs it.
    """
    # Imported here so --help does not load the policy loader.
    from policy.clock import machine_zone, named_zone
    from policy.hierarchy import ConfigError, load

    localtime = Path(os.environ.get("MACHINE_LOCALTIME", "/etc/localtime"))
    policy_file = Path(os.environ.get("POLICY_FILE", "/etc/smartproxy/policy.yaml"))
    policy = None
    try:
        policy = load(policy_file, warn=lambda message: print(message, file=sys.stderr))
    except ConfigError as exc:
        if need_types:
            raise SystemExit(f"--type needs the policy file, and it did not load: {exc}") from exc
        print(f"the policy file did not load, so the machine timezone is used: {exc}", file=sys.stderr)
    if policy is None and need_types:
        raise SystemExit(f"--type needs the policy file, and there is none at {policy_file}")
    if policy is None:
        return {}, machine_zone(localtime=localtime)
    zone = named_zone(policy.timezone) if policy.timezone else machine_zone(localtime=localtime)
    return {task.name: task.type for task in policy.tasks}, zone


def _print_attempts(attempts: Sequence[Attempt], out: TextIO) -> None:
    rows = [("id", "client group", "task", "outcome", "started", "finished")]
    for attempt in attempts:
        rows.append(
            (
                str(attempt.id),
                attempt.client_group,
                attempt.task,
                attempt.outcome,
                _when(attempt.started_at),
                "" if attempt.finished_at is None else _when(attempt.finished_at),
            )
        )
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    for row in rows:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip(), file=out)


def _when(moment: datetime) -> str:
    return moment.replace(tzinfo=None).isoformat(sep=" ", timespec="minutes")


def _count(number: int) -> str:
    return "1 attempt" if number == 1 else f"{number} attempts"


def _aware(moment: datetime, zone: tzinfo) -> datetime:
    return moment.replace(tzinfo=zone) if moment.tzinfo is None else moment


if __name__ == "__main__":
    sys.exit(main())
