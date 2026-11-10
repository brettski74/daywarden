"""Order the available tasks, pick one, and say where the task pages live.

The picker and the selector both use the available set from
``policy.tasks.task_sets``. The selector also lists the potential tasks
waiting on required ones, as After These, and every other task he could
practise, as Extra Practice. Inside a set, a task that has never been passed
comes before one that has, and the oldest pass comes next. Equal candidates
are ordered by name and then rotated, so the order of requests does not
leave one of them at the back forever. Only the picker moves the rotation.

Giving up a required attempt is refused while its task is the only
required task. Any other attempt can be given up.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from policy.hierarchy import Policy
from policy.tasks import (
    PARENT_CHECK,
    REQUIRED,
    Attempt,
    AttemptStore,
    Task,
    TaskSets,
    last_pass,
    task_sets,
)

_TURNS = """
CREATE TABLE IF NOT EXISTS task_turns (
    client_group TEXT PRIMARY KEY,
    turn INTEGER NOT NULL
);
"""

PICKER_PATH = "/tasks/next"
CHOOSER_PATH = "/tasks/choose"
_RESERVED = (PICKER_PATH, CHOOSER_PATH)
MEDIA_SEGMENT = "/audio/"
# The Compose defaults: PORT_BASE 8080, and the policy pages and the
# auto-configuration file 4 and 8 above it.
DEFAULT_PROXY_PORT = 8080
DEFAULT_PUBLISHED_PORT = 8084
DEFAULT_PROXY_CONFIG_PORT = 8088
# Compose mounts the machine's /etc/hostname here. The container's own
# hostname is an id such as 1c45a70451e1, which clients do not use.
HOST_HOSTNAME = Path("/etc/host-hostname")


def published_port() -> int:
    """Return the port external clients use when the policy file omits ``port``.

    That is ``POLICY_PORT``, the host port Compose publishes onto the
    container's HTTPS listener. It is not the port the process binds. An
    unset variable uses the Compose default, 8084.
    """
    return _port_setting("POLICY_PORT", DEFAULT_PUBLISHED_PORT)


def proxy_port() -> int:
    """Return ``PROXY_PORT``, the host port browsers use for the proxy."""
    return _port_setting("PROXY_PORT", DEFAULT_PROXY_PORT)


def proxy_config_port() -> int:
    """Return ``PROXY_CONFIG_PORT``, the host port that serves the proxy auto-config file."""
    return _port_setting("PROXY_CONFIG_PORT", DEFAULT_PROXY_CONFIG_PORT)


def proxy_config_url(policy: Policy) -> str:
    """Return the proxy auto-config URL a browser is given."""
    return f"http://{task_host(policy)}:{proxy_config_port()}/proxy.pac"


def _port_setting(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    if not raw.isdecimal():
        raise ValueError(f"{name} must be a whole number from 1 to 65535")
    value = int(raw)
    if not 1 <= value <= 65535:
        raise ValueError(f"{name} must be a whole number from 1 to 65535")
    return value


def machine_hostname(path: Path | None = None) -> str | None:
    """Return the hostname of the machine running Compose, when that file is mounted.

    The file is one line, the contents of the host's ``/etc/hostname``. A
    missing file, or a line that is not a host name, returns None so the
    caller can fall back to the name of this process's machine.
    """
    if path is None:
        target = Path(os.environ.get("MACHINE_HOSTNAME", str(HOST_HOSTNAME)))
    else:
        target = path
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    name = lines[0]
    if any(char.isspace() for char in name) or any(char in name for char in ":/\\?#"):
        return None
    return name


def task_host(policy: Policy) -> str:
    """Return the host external clients use for the policy server.

    A configured ``hostname`` wins. Otherwise the name is the host machine's
    ``/etc/hostname`` when Compose has mounted it, and the name reported by
    this process when that file is absent.
    """
    if policy.hostname:
        return policy.hostname
    mounted = machine_hostname()
    if mounted:
        return mounted
    name = socket.gethostname().strip()
    return name or "localhost"


def task_port(policy: Policy) -> int:
    """Return the port external clients use for the policy server."""
    if policy.port is not None:
        return policy.port
    return published_port()


def task_origin(policy: Policy) -> str:
    """Return ``https://host`` or ``https://host:port`` for the policy server.

    The scheme is always https. Port 443 is left off.
    """
    host = task_host(policy)
    port = task_port(policy)
    if port == 443:
        return f"https://{host}"
    return f"https://{host}:{port}"


def picker_url(policy: Policy) -> str:
    """Return the task picker on the policy server."""
    return task_origin(policy) + PICKER_PATH


def chooser_url(policy: Policy) -> str:
    """Return the task selector on the policy server."""
    return task_origin(policy) + CHOOSER_PATH


def task_page_path(name: str) -> str:
    """Return the path of one task on the policy server.

    ``/tasks/next`` is the picker and ``/tasks/choose`` the selector. A task
    with either name is served under ``/tasks/work/``.
    """
    path = "/tasks/" + quote(name, safe="")
    if path in _RESERVED:
        return "/tasks/work/" + quote(name, safe="")
    return path


def task_page_url(policy: Policy, name: str) -> str:
    """Return the absolute URL of one task on the policy server."""
    return task_origin(policy) + task_page_path(name)


def task_media_path(name: str) -> str:
    """Return the path a task's own audio files are served under, ending in ``/``."""
    return task_page_path(name) + MEDIA_SEGMENT


def task_media_from_path(path: str) -> tuple[str, str] | None:
    """Return the task name and file name in a ``/tasks/<name>/audio/<file>`` path, or None."""
    for prefix in ("/tasks/work/", "/tasks/"):
        if not path.startswith(prefix):
            continue
        name, found, file_name = path[len(prefix) :].partition(MEDIA_SEGMENT)
        name = unquote(name)
        if found and name and "/" not in name and file_name and "/" not in file_name:
            return name, file_name
    return None


def same_task_site(url: str, policy: Policy) -> bool:
    """Return whether url is an https request for this policy server."""
    left = urlsplit(url)
    if left.scheme.lower() != "https":
        return False
    return (left.hostname or "").lower() == task_host(policy).lower() and _port_matches(
        left.port, task_port(policy)
    )


def _port_matches(url_port: int | None, configured: int) -> bool:
    if configured == 443:
        return url_port in {None, 443}
    return url_port == configured


def task_name_from_path(path: str) -> str | None:
    """Return the task name in a task-site path, or None for the picker, the selector, or another path."""
    if path in _RESERVED:
        return None
    for prefix in ("/tasks/work/", "/tasks/"):
        if path.startswith(prefix):
            name = unquote(path[len(prefix) :])
            if name and "/" not in name:
                return name
            return None
    return None


def configured_task(tasks: Sequence[Task], name: str, client_group: str) -> Task | None:
    """Return the task of this name when it is assigned to this group and is not ``parent_check``."""
    task = next((item for item in tasks if item.name == name), None)
    if task is None or task.type == PARENT_CHECK or client_group not in task.groups:
        return None
    return task


def may_abandon(attempt: Attempt, task: Task, sets: TaskSets) -> bool:
    """Return whether this attempt may be given up.

    A required attempt may not be given up while its task is the only
    required task. A potential or practice attempt always may.
    ``parent_check`` is not a child task, so it is not abandoned from a
    child page.
    """
    if task.type == PARENT_CHECK:
        return False
    if attempt.task_set != REQUIRED:
        return True
    if all(other.name != task.name for other in sets.required):
        return True
    return any(other.name != task.name for other in sets.required)


def ordered_tasks(
    sets: TaskSets,
    client_group: str,
    attempts: Sequence[Attempt],
    *,
    turn: int = 0,
) -> tuple[tuple[Task, ...], int]:
    """Return the available tasks in the order the picker tries them, and how many tie for first.

    Each run of equal candidates is in name order, rotated by ``turn``.
    """
    return _in_picker_order(sets.available, client_group, attempts, turn)


def _in_picker_order(
    tasks: Sequence[Task], client_group: str, attempts: Sequence[Attempt], turn: int
) -> tuple[tuple[Task, ...], int]:
    ranked = sorted(tasks, key=lambda task: (_rank(task, client_group, attempts), task.name))
    groups: list[list[Task]] = []
    for task in ranked:
        if groups and _rank(groups[-1][0], client_group, attempts) == _rank(task, client_group, attempts):
            groups[-1].append(task)
        else:
            groups.append([task])
    turn = max(turn, 0)
    ordered: list[Task] = []
    for group in groups:
        shift = turn % len(group)
        ordered.extend(group[shift:] + group[:shift])
    return tuple(ordered), len(groups[0]) if groups else 0


def choose_task(
    tasks: Sequence[Task],
    client_group: str,
    today: date,
    attempts: Sequence[Attempt],
    *,
    turn: int = 0,
) -> tuple[Task | None, int]:
    """Return the task the picker opens, and how many candidates tied for it.

    The tie count is zero when nothing is available.
    """
    ordered, ties = ordered_tasks(task_sets(tasks, client_group, today, attempts), client_group, attempts, turn=turn)
    if not ordered:
        return None, 0
    return ordered[0], ties


def picked_task_url(policy: Policy, client_group: str, today: date, store: AttemptStore) -> str | None:
    """Return the task URL the picker opens, advancing the rotation when the pick was tied.

    None means nothing is available. The caller then shows the
    plain-language page instead of redirecting.
    """
    task, ties = choose_task(
        policy.tasks,
        client_group,
        today,
        store.history(client_group),
        turn=read_turn(store, client_group),
    )
    if task is None:
        return None
    if ties > 1:
        advance_turn(store, client_group)
    return task_page_url(policy, task.name)


@dataclass(frozen=True)
class Sections:
    """What the selector lists.

    ``main`` is the available tasks in picker order. ``after`` is the
    potential tasks while any task is required, in picker order.
    ``practice`` is every other configured task whose ``available_from``
    has arrived, in name order.
    """

    main: tuple[Task, ...]
    after: tuple[Task, ...]
    practice: tuple[Task, ...]


def extra_practice(sets: TaskSets, today: date) -> tuple[Task, ...]:
    """Return the configured tasks that are neither required nor potential, leaving out any not available yet."""
    return tuple(
        sorted(
            (
                task
                for task in sets.configured
                if task not in sets.required
                and task not in sets.potential
                and (task.available_from is None or task.available_from <= today)
            ),
            key=lambda task: task.name,
        )
    )


def sections(policy: Policy, client_group: str, today: date, store: AttemptStore) -> Sections:
    """Return the selector's sections, without moving the rotation."""
    history = store.history(client_group)
    sets = task_sets(policy.tasks, client_group, today, history)
    turn = read_turn(store, client_group)
    main, _ties = ordered_tasks(sets, client_group, history, turn=turn)
    after: tuple[Task, ...] = ()
    if sets.required:
        after, _ties = _in_picker_order(sets.potential, client_group, history, turn)
    return Sections(main, after, extra_practice(sets, today))


def read_turn(store: AttemptStore, client_group: str) -> int:
    """Return how many tied picks this client group has already taken."""
    _ensure_turns(store.connection)
    row = store.connection.execute(
        "SELECT turn FROM task_turns WHERE client_group = ?",
        (client_group,),
    ).fetchone()
    return 0 if row is None else int(row[0])


def advance_turn(store: AttemptStore, client_group: str) -> None:
    """Record that a tied pick was used, so the next tie moves on."""
    _ensure_turns(store.connection)
    with store.connection:
        row = store.connection.execute(
            "SELECT turn FROM task_turns WHERE client_group = ?",
            (client_group,),
        ).fetchone()
        nxt = 1 if row is None else int(row[0]) + 1
        store.connection.execute(
            "INSERT INTO task_turns (client_group, turn) VALUES (?, ?) "
            "ON CONFLICT(client_group) DO UPDATE SET turn = excluded.turn",
            (client_group, nxt),
        )


def _rank(task: Task, client_group: str, attempts: Sequence[Attempt]) -> tuple[int, str]:
    """Sort never-passed tasks first, then the oldest pass."""
    found = last_pass(task.name, client_group, attempts)
    if found is None or found.finished_at is None:
        return (0, "")
    return (1, found.finished_at.isoformat())


def _ensure_turns(connection) -> None:
    connection.executescript(_TURNS)
