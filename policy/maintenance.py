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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path, PurePosixPath
from typing import TextIO

from policy.spelling_words import Figures
from policy.tasks import Attempt, AttemptStore

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


def select_attempts(
    attempts: Sequence[Attempt],
    chosen: AttemptFilter,
    *,
    now: datetime,
    zone: tzinfo,
) -> list[Attempt]:
    """Return the attempts every filter matches.

    Several values for one filter match any of them. A task name matches
    attempts of any type, and a type matches the type stored on each attempt. The age of an attempt
    is measured from its finish, or from its start while it is in progress.
    A stored time without an offset is read in ``zone``.
    """
    found = []
    for attempt in attempts:
        if chosen.clients and attempt.client_group not in chosen.clients:
            continue
        if chosen.tasks and attempt.task not in chosen.tasks:
            continue
        if chosen.types and attempt.task_type not in chosen.types:
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
        help="task type stored with each attempt, such as arithmetic",
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
    stats = commands.add_parser(
        "word-stats",
        help="list how often each spelling word was asked, spelled right, and spelled wrong",
        description=(
            "List each client group's spelling word figures and the weight each word would have as a "
            "revision word. Changes nothing. Each filter may be given more than once and matches any of "
            "its values, and different filters must all match."
        ),
    )
    stats.add_argument("--client", action="append", default=[], metavar="GROUP", help="client group")
    stats.add_argument("--word", action="append", default=[], metavar="WORD", help="entry key, such as rope or read.1")
    stats.add_argument(
        "--pool",
        action="append",
        default=[],
        metavar="DIRECTORY",
        help="every word with a recording in this pool directory, such as spelling/revision, asked yet or not",
    )
    stats.add_argument(
        "--task",
        action="append",
        default=[],
        metavar="NAME",
        help="every word in the current, revision, or attic directory of this spelling task, asked yet or not",
    )
    stats.add_argument(
        "--sort",
        action="append",
        default=[],
        type=parse_sort,
        metavar="COLUMN",
        help=(
            "order the rows by client, word, attempts, correct, incorrect, run, or weight, smallest first. "
            "Add - after the name, such as weight-, for largest first. Each --sort adds a term after the "
            "earlier ones. Rows left level are ordered by client group then word"
        ),
    )
    stats.set_defaults(run=_word_stats)
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
    zone = _household_zone()
    database = Path(os.environ.get("POLICY_DB", "/var/lib/daywarden/policy.sqlite3"))
    if not database.is_file():
        print(f"no policy database at {database}", file=sys.stderr)
        return 1
    with AttemptStore(database) as store:
        matched = select_attempts(store.everything(), chosen, now=now, zone=zone)
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


def _word_stats(parser: argparse.ArgumentParser, args: argparse.Namespace, now: datetime, out: TextIO) -> int:
    database = Path(os.environ.get("POLICY_DB", "/var/lib/daywarden/policy.sqlite3"))
    if not database.is_file():
        print(f"no policy database at {database}", file=sys.stderr)
        return 1
    try:
        pooled = _words_in(args.pool, args.task)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    wanted = {word.lower() for word in args.word}
    with AttemptStore(database) as store:
        figures = store.words.all_figures()
    if pooled is not None:
        # Every word in the named pools or tasks is listed, asked yet or not, for each client group.
        for group in _stats_groups(figures, args.client):
            for word in pooled:
                figures.setdefault((group, word), Figures())
    rows = [("client group", "word", "attempts", "correct", "incorrect", "run", "weight")]
    for (group, word), found in _sorted_figures(figures, args.sort):
        if args.client and group not in args.client:
            continue
        if wanted and word not in wanted:
            continue
        if pooled is not None and word not in pooled:
            continue
        rows.append(
            (group, word, str(found.attempts), str(found.correct), str(found.incorrect), str(found.run), f"{found.weight:.3f}")
        )
    if len(rows) == 1:
        print("no word figures match", file=out)
        return 0
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    for row in rows:
        cells = [cell.ljust(width) if column < 2 else cell.rjust(width) for column, (cell, width) in enumerate(zip(row, widths))]
        print("  ".join(cells).rstrip(), file=out)
    return 0


_SORT_KEYS = {
    "client": lambda group, word, found: group,
    "word": lambda group, word, found: word,
    "attempts": lambda group, word, found: found.attempts,
    "correct": lambda group, word, found: found.correct,
    "incorrect": lambda group, word, found: found.incorrect,
    "run": lambda group, word, found: found.run,
    "weight": lambda group, word, found: found.weight,
}


def parse_sort(text: str) -> tuple[str, bool]:
    """Return a sort column and whether it is descending, from ``weight``, ``weight-``, or ``-weight``."""
    name = text.strip()
    descending = name.endswith("-") or name.startswith("-")
    name = name.strip("-")
    if name not in _SORT_KEYS:
        raise argparse.ArgumentTypeError(
            f"{text!r} is not one of {', '.join(_SORT_KEYS)}, optionally followed by - for largest first"
        )
    return name, descending


def _sorted_figures(figures: dict, terms: Sequence[tuple[str, bool]]) -> list:
    """Return the figures ordered by each sort term in turn, then by client group and word."""
    ordered = sorted(figures.items())
    for name, descending in reversed(terms):
        key = _SORT_KEYS[name]
        ordered.sort(key=lambda item: key(item[0][0], item[0][1], item[1]), reverse=descending)
    return ordered


def _stats_groups(figures: dict, chosen: Sequence[str]) -> list[str]:
    """Return the client groups to list never-asked words for: those named, else the policy's and any with figures."""
    if chosen:
        return list(dict.fromkeys(chosen))
    groups = {group for group, _word in figures}
    try:
        groups |= {each.name for each in _load_policy().client_groups}
    except ValueError:
        pass
    return sorted(groups)


def _words_in(pools: Sequence[str], tasks: Sequence[str]) -> set[str] | None:
    """Return the folded keys of the words in any named pool directory and any named task's directories.

    None means neither filter was given. With both, a word must be in both.
    Raises ``ValueError`` naming a pool directory that does not exist, or a
    task that is not a spelling task in the policy.
    """
    if not pools and not tasks:
        return None
    from policy.spelling import ALL_POOLS, data_root, entry_keys, parse_settings

    root = data_root()
    in_pools: set[str] | None = None
    if pools:
        in_pools = set()
        for name in pools:
            directory = root / PurePosixPath(name)
            if not directory.is_dir():
                raise ValueError(f"no pool directory {name}")
            in_pools |= entry_keys(directory)
    in_tasks: set[str] | None = None
    if tasks:
        policy = _load_policy()
        in_tasks = set()
        for name in tasks:
            found = [task for task in policy.tasks if task.name == name and task.type == "spelling"]
            if not found:
                raise ValueError(f"no spelling task {name} in the policy")
            settings = parse_settings(found[0].document())
            for pool in ALL_POOLS:
                directory = root / settings.directory(pool)
                if directory.is_dir():
                    in_tasks |= entry_keys(directory)
    return in_pools & in_tasks if in_pools is not None and in_tasks is not None else (in_pools if in_pools is not None else in_tasks)


def _load_policy():
    from policy.hierarchy import ConfigError, load

    policy_file = Path(os.environ.get("POLICY_FILE", "/etc/daywarden/policy.yaml"))
    try:
        policy = load(policy_file, warn=lambda message: print(message, file=sys.stderr))
    except ConfigError as exc:
        raise ValueError(f"the policy file did not load: {exc}") from exc
    if policy is None:
        raise ValueError("the policy file did not load")
    return policy


def _household_zone() -> tzinfo:
    """Return the household timezone from the policy file, or the machine's when it does not load."""
    # Imported here so --help does not load the policy loader.
    from policy.clock import machine_zone, named_zone
    from policy.hierarchy import ConfigError, load

    localtime = Path(os.environ.get("MACHINE_LOCALTIME", "/etc/localtime"))
    policy_file = Path(os.environ.get("POLICY_FILE", "/etc/daywarden/policy.yaml"))
    policy = None
    try:
        policy = load(policy_file, warn=lambda message: print(message, file=sys.stderr))
    except ConfigError as exc:
        print(f"the policy file did not load, so the machine timezone is used: {exc}", file=sys.stderr)
    if policy is None or not policy.timezone:
        return machine_zone(localtime=localtime)
    return named_zone(policy.timezone)


def _print_attempts(attempts: Sequence[Attempt], out: TextIO) -> None:
    rows = [("id", "client group", "type", "task", "outcome", "started", "finished")]
    for attempt in attempts:
        rows.append(
            (
                str(attempt.id),
                attempt.client_group,
                attempt.task_type,
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
