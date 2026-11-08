"""make reload, make restart, make check, and make help on the local dev stack."""

import shutil

import pytest

from hostfakes import ROOT, SERVICES, Host

COPIED = ("Makefile", "docker-compose.yml", "bin/dw", "bin/daywarden-lib.sh")
BROKEN = ["config/policy.yaml:3:1: unknown setting timezon"]


@pytest.fixture
def host(tmp_path):
    (tmp_path / "machine").mkdir()
    machine = Host(tmp_path / "machine")
    (machine.tools / "make").symlink_to(shutil.which("make"))
    machine.root = machine.tmp / "checkout"
    for name in COPIED:
        target = machine.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    (machine.root / ".env").write_text(f"CA_VOLUME_PATH={machine.tmp / 'ca'}\n", encoding="utf-8")
    return machine


def _make(host, *targets):
    return host.run("make", "--no-print-directory", *targets, cwd=host.root)


def _compose(host):
    return [call[4:] for call in host.calls("docker") if call[1:2] == ["compose"]]


def test_up_and_down_start_and_stop_every_service_on_the_ports_dw_uses(host):
    env = host.root / ".env"
    env.write_text(env.read_text(encoding="utf-8") + "PORT_BASE=9080\n", encoding="utf-8")
    done = _make(host, "up")
    assert done.returncode == 0, done.stderr
    assert host.state["running"] == {service: "healthy" for service in SERVICES}
    assert {key: host.state["up_env"][key] for key in ("PROXY_PORT", "POLICY_PORT", "PROXY_CONFIG_PORT")} == {
        "PROXY_PORT": "9080",
        "POLICY_PORT": "9084",
        "PROXY_CONFIG_PORT": "9088",
    }
    assert "Proxy configuration URL: http://tundra:9088/proxy.pac" in done.stdout
    done = _make(host, "down")
    assert done.returncode == 0, done.stderr
    assert host.state["running"] == {}


def test_reload_applies_the_policy_to_every_service_without_restarting_a_container(host):
    host.all_running()
    done = _make(host, "reload")
    assert done.returncode == 0, done.stderr
    assert "The decisions, observations, and autoconfig services are using the reloaded policy." in done.stdout
    assert host.state["reloaded"] == ["decisions", "observations", "autoconfig"]
    assert not [call for call in _compose(host) if call[:1] in (["up"], ["down"])]


def test_reload_with_a_broken_policy_lists_the_errors_and_reloads_nothing(host):
    host.all_running()
    host.state["policy_errors"] = BROKEN
    done = _make(host, "reload")
    assert done.returncode != 0
    assert "dw: the policy has 1 error. Nothing was reloaded." in done.stderr
    assert BROKEN[0] in done.stderr
    assert "reloaded" not in host.state


def test_restart_replaces_every_container_and_waits_for_health(host):
    host.all_running()
    done = _make(host, "restart")
    assert done.returncode == 0, done.stderr
    assert "daywarden restarted." in done.stdout
    calls = [call[0] for call in _compose(host) if call[:1] in (["up"], ["down"])]
    assert calls == ["down", "up"]
    assert host.state["running"] == {service: "healthy" for service in SERVICES}


def test_restart_with_a_broken_policy_stops_nothing(host):
    host.all_running()
    host.state["policy_errors"] = BROKEN
    done = _make(host, "restart")
    assert done.returncode != 0
    assert "dw: the policy has 1 error. Nothing was restarted." in done.stderr
    assert host.state["running"] == {service: "healthy" for service in SERVICES}


def test_restart_of_a_stopped_stack_starts_it(host):
    done = _make(host, "restart")
    assert done.returncode == 0, done.stderr
    assert "daywarden was not running, so it was started." in done.stdout
    assert host.state["running"] == {service: "healthy" for service in SERVICES}


def test_check_lists_every_error_and_starts_nothing(host):
    host.state["policy_errors"] = BROKEN
    done = _make(host, "check")
    assert done.returncode != 0
    assert BROKEN[0] in done.stderr
    assert host.state["running"] == {}


def test_an_exported_value_wins_over_the_env_file(host):
    ca = host.tmp / "exported-ca"
    done = host.run("make", "--no-print-directory", "check", cwd=host.root, env={"CA_VOLUME_PATH": str(ca)})
    assert done.returncode == 0, done.stderr
    assert ca.is_dir()
    assert not (host.tmp / "ca").exists()


def _phony_targets(host) -> set[str]:
    database = _make(host, "-pq", "help").stdout
    for line in database.splitlines():
        if line.startswith(".PHONY:"):
            return set(line.split(":", 1)[1].split())
    raise AssertionError("make -p printed no .PHONY line")


def test_help_describes_every_target_and_runs_nothing(host):
    done = _make(host, "help")
    assert done.returncode == 0, done.stderr
    described = {}
    for line in done.stdout.splitlines():
        name, _, description = line.strip().partition(" ")
        described[name] = description.strip()
    assert set(described) == _phony_targets(host)
    assert all(described.values()), described
    assert host.calls() == []
