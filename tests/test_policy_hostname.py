"""S003.4: task URLs use the policy server's hostname and published port."""

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy.engine import decide  # noqa: E402
from policy.hierarchy import ConfigError, load  # noqa: E402
from policy.task_page import NOTHING, respond_task  # noqa: E402
from policy.tasks import AttemptStore  # noqa: E402

ZONE = ZoneInfo("America/Toronto")
YOUNGER = "192.0.2.40"
OLDER = "192.0.2.50"
YOUTUBE = "https://www.youtube.com/watch?v=abc"

OPEN = """\
entry: open
rule_sets:
  open:
    - condition: always
      when_true: { action: allow }
"""


def _file(directory: Path, text: str) -> Path:
    path = directory / "policy.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _load(directory: Path, text: str):
    loaded = load(_file(directory, text))
    assert loaded is not None
    return loaded


def _at() -> datetime:
    return datetime(2026, 10, 31, 16, 0, tzinfo=ZONE)


def _house(hostname: str | None, port: str | None, tasks: str) -> str:
    host = "" if hostname is None else f"hostname: {hostname}\n"
    published = "" if port is None else f"port: {port}\n"
    return f"""\
entry: gate
timezone: America/Toronto
{host}{published}client_groups:
  younger:
    addresses: ["192.0.2.40"]
  older:
    addresses: ["192.0.2.50"]
tasks:
{tasks}
rule_sets:
  gate:
    - condition: always
      when_true: {{ action: redirect, location: revision_task }}
"""


def _location(page) -> str | None:
    for name, value in page.headers:
        if name == "location":
            return value
    return None


def test_an_eligible_task_uses_the_hostname_and_the_published_port(tmp_path, monkeypatch):
    monkeypatch.setenv("POLICY_PORT", "8090")
    policy = _load(
        tmp_path,
        _house(
            "garden",
            None,
            """\
  sums:
    type: spelling
    group: younger
    pass_cooldown: 0
  words:
    type: spelling
    group: older
    pass_cooldown: 0
""",
        ),
    )
    with AttemptStore(":memory:") as store:
        younger = decide(policy, client_ip=YOUNGER, url=YOUTUBE, at=_at(), attempts=store)
        older = decide(policy, client_ip=OLDER, url=YOUTUBE, at=_at(), attempts=store)
        page = respond_task(
            policy,
            store,
            method="GET",
            path="/tasks/next",
            client_ip=YOUNGER,
            cookie=None,
            now=_at(),
        )
    assert younger.decision["location"] == "https://garden:8090/tasks/sums"
    assert older.decision["location"] == "https://garden:8090/tasks/words"
    assert page.status == 302
    assert _location(page) == "https://garden:8090/tasks/sums"


def test_nothing_eligible_lands_on_the_picker(tmp_path, monkeypatch):
    monkeypatch.setenv("POLICY_PORT", "8090")
    policy = _load(
        tmp_path,
        _house(
            "garden",
            None,
            """\
  later:
    type: spelling
    group: younger
    pass_cooldown: 0
    available_from: 2026-11-01
""",
        ),
    )
    picker = "https://garden:8090/tasks/next"
    with AttemptStore(":memory:") as store:
        sent = decide(policy, client_ip=YOUNGER, url=YOUTUBE, at=_at(), attempts=store)
        follow = decide(policy, client_ip=YOUNGER, url=picker, at=_at(), attempts=store)
        page = respond_task(
            policy,
            store,
            method="GET",
            path="/tasks/next",
            client_ip=YOUNGER,
            cookie=None,
            now=_at(),
        )
    assert sent.decision == {"action": "redirect", "status": 302, "location": picker}
    assert follow.decision == {"action": "allow"}
    assert page.status == 200
    assert NOTHING in page.body


def test_an_omitted_hostname_uses_the_operating_system_name(tmp_path, monkeypatch):
    monkeypatch.setenv("POLICY_PORT", "8090")
    monkeypatch.setenv("MACHINE_HOSTNAME", str(tmp_path / "no-such-hostname"))
    monkeypatch.setattr("policy.selection.socket.gethostname", lambda: "lounge")
    policy = _load(
        tmp_path,
        _house(
            None,
            None,
            """\
  sums:
    type: spelling
    group: younger
    pass_cooldown: 0
""",
        ),
    )
    assert policy.hostname is None
    with AttemptStore(":memory:") as store:
        trace = decide(policy, client_ip=YOUNGER, url=YOUTUBE, at=_at(), attempts=store)
    assert trace.decision["location"] == "https://lounge:8090/tasks/sums"


def test_an_omitted_hostname_uses_the_compose_hosts_name_not_the_containers(tmp_path, monkeypatch):
    monkeypatch.setenv("POLICY_PORT", "8090")
    monkeypatch.setattr("policy.selection.socket.gethostname", lambda: "1c45a70451e1")
    host_file = tmp_path / "hostname"
    host_file.write_text("study\n", encoding="utf-8")
    monkeypatch.setenv("MACHINE_HOSTNAME", str(host_file))
    policy = _load(
        tmp_path,
        _house(
            None,
            None,
            """\
  sums:
    type: spelling
    group: younger
    pass_cooldown: 0
""",
        ),
    )
    with AttemptStore(":memory:") as store:
        trace = decide(policy, client_ip=YOUNGER, url=YOUTUBE, at=_at(), attempts=store)
    assert trace.decision["location"] == "https://study:8090/tasks/sums"
    host_file.write_text("not a host\n", encoding="utf-8")
    with AttemptStore(":memory:") as store:
        fallen = decide(policy, client_ip=YOUNGER, url=YOUTUBE, at=_at(), attempts=store)
    assert fallen.decision["location"] == "https://1c45a70451e1:8090/tasks/sums"


def test_port_443_is_left_off_and_a_set_port_overrides_the_published_one(tmp_path, monkeypatch):
    monkeypatch.setenv("POLICY_PORT", "8090")
    plain = _load(
        tmp_path,
        _house(
            "garden",
            "443",
            """\
  sums:
    type: spelling
    group: younger
    pass_cooldown: 0
""",
        ),
    )
    proxied = _load(
        tmp_path,
        _house(
            "garden",
            "8443",
            """\
  sums:
    type: spelling
    group: younger
    pass_cooldown: 0
""",
        ),
    )
    with AttemptStore(":memory:") as store:
        standard = decide(plain, client_ip=YOUNGER, url=YOUTUBE, at=_at(), attempts=store)
        reverse = decide(proxied, client_ip=YOUNGER, url=YOUTUBE, at=_at(), attempts=store)
    assert standard.decision["location"] == "https://garden/tasks/sums"
    assert ":443" not in standard.decision["location"]
    assert reverse.decision["location"] == "https://garden:8443/tasks/sums"


@pytest.mark.parametrize(
    "hostname",
    [
        "https://garden",
        "garden:8090",
        "garden/tasks",
        "garden name",
        '""',
        '" "',
    ],
)
def test_a_bad_hostname_is_a_load_error_and_the_previous_policy_stays(tmp_path, hostname):
    previous = load(_file(tmp_path, "hostname: garden\n" + OPEN))
    assert previous is not None
    assert previous.hostname == "garden"
    bad = _file(tmp_path, f"hostname: {hostname}\n" + OPEN)
    with pytest.raises(ConfigError, match="hostname"):
        load(bad, previous=previous)
    assert previous.hostname == "garden"
    assert previous.entry == "open"


@pytest.mark.parametrize("port", ["0", "65536", "1.5", "true", "-1", "nope", '""'])
def test_a_bad_port_is_a_load_error_and_the_previous_policy_stays(tmp_path, port):
    previous = load(_file(tmp_path, "port: 443\n" + OPEN))
    assert previous is not None
    assert previous.port == 443
    bad = _file(tmp_path, f"port: {port}\n" + OPEN)
    with pytest.raises(ConfigError, match="port must be a whole number from 1 to 65535"):
        load(bad, previous=previous)
    assert previous.port == 443
    assert previous.entry == "open"


def test_a_file_that_sets_revision_task_fails_to_load(tmp_path):
    previous = load(_file(tmp_path, OPEN))
    bad = _file(tmp_path, 'revision_task: "http://192.168.1.10:8080/tasks/next"\n' + OPEN)
    with pytest.raises(ConfigError, match="revision_task is not set in the policy file"):
        load(bad, previous=previous)
    assert previous is not None
    assert previous.entry == "open"
    assert previous.rule_set("open")[0].when_true.kind == "allow"
