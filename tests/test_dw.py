"""S014: dw, add-parent, rm-attempts, and the user service on an installed daywarden."""

import pytest

from hostfakes import Host, make_package


@pytest.fixture
def host(tmp_path):
    (tmp_path / "machine").mkdir()
    machine = Host(tmp_path / "machine")
    done = machine.install(make_package(tmp_path))
    assert done.returncode == 0, done.stderr
    machine.forget_calls()
    machine.elsewhere = machine.tmp / "elsewhere"
    machine.elsewhere.mkdir()
    return machine


def _compose(host):
    """Each docker compose call, without docker and the project directory."""
    calls = []
    for call in host.calls("docker"):
        if call[1:2] == ["compose"]:
            assert call[2:4] == ["--project-directory", str(host.root)]
            calls.append(call[4:])
    return calls


def _systemctl_user(host):
    return [call[2:] for call in host.calls("systemctl") if call[1:2] == ["--user"]]


# Usage


@pytest.mark.parametrize("args", [(), ("help",), ("--help",), ("-h",)])
def test_the_usage_lists_every_command(host, args):
    done = host.dw(*args)
    assert done.returncode == 0
    for command in ("up", "down", "status", "enable", "disable"):
        assert f"\n  {command} " in done.stdout
    assert host.calls("docker") == []


def test_an_unknown_command_prints_the_usage_to_stderr_with_status_2(host):
    done = host.dw("frobnicate")
    assert done.returncode == 2
    assert done.stdout == ""
    assert "dw: unknown command: frobnicate" in done.stderr
    assert "usage: dw COMMAND" in done.stderr


def test_an_extra_argument_is_a_usage_error(host):
    done = host.dw("up", "--now")
    assert done.returncode == 2
    assert "dw: up takes no arguments." in done.stderr
    assert _compose(host) == []


@pytest.mark.parametrize("missing", [".env", "docker-compose.yml"])
def test_a_missing_install_file_says_to_run_install_again(host, missing):
    (host.root / missing).unlink()
    done = host.dw("up")
    assert done.returncode == 1
    assert done.stderr == f"dw: daywarden is not installed in {host.root}: {missing} is missing. Run install.sh again.\n"


# up, down, status


def test_up_creates_the_directories_and_waits_for_health_from_any_directory(host):
    (host.root / "ca").rmdir()
    (host.root / "data").rmdir()
    done = host.dw("up", cwd=host.elsewhere)
    assert done.returncode == 0, done.stderr
    assert (host.root / "ca").is_dir() and (host.root / "data").is_dir()
    assert _compose(host) == [["up", "-d", "--wait", "--wait-timeout", "180"]]
    assert list(host.elsewhere.iterdir()) == []
    assert _systemctl_user(host) == [["show-environment"], ["is-enabled", "daywarden.service"]]


def test_a_variable_in_the_environment_wins_over_env(host):
    ca = host.tmp / "other-ca"
    done = host.dw("up", env={"CA_VOLUME_PATH": str(ca)})
    assert done.returncode == 0, done.stderr
    assert ca.is_dir()


def test_up_names_each_service_that_did_not_become_healthy_and_shows_why(host):
    host.state["up_fails"] = {"observations": "unhealthy", "proxy": "starting"}
    host.state["logs"] = {"observations": "ConfigError: policy.yaml:3: no such rule set"}
    done = host.dw("up")
    assert done.returncode == 1
    assert "dw: these services did not become healthy: observations (unhealthy), proxy (starting)" in done.stderr
    assert "The last lines observations logged:\n  ConfigError: policy.yaml:3: no such rule set\n" in done.stderr
    assert "proxy logged" not in done.stderr


def test_up_and_down_go_through_the_user_service_when_enabled(host):
    host.state["systemd"]["enabled"] = True
    done = host.dw("up")
    assert done.returncode == 0, done.stderr
    assert ["start", "daywarden.service"] in _systemctl_user(host)
    assert host.state["systemd"]["active"] == "active"
    host.forget_calls()
    done = host.dw("down")
    assert done.returncode == 0, done.stderr
    assert _compose(host) == [["down"]]
    assert ["stop", "daywarden.service"] in _systemctl_user(host)
    assert host.state["running"] == {}
    assert host.state["systemd"]["enabled"] is True


def test_up_on_a_running_enabled_daywarden_brings_back_a_stopped_service(host):
    host.state["systemd"].update(enabled=True, active="active")
    host.state["running"] = {"decisions": "healthy", "observations": "healthy"}
    done = host.dw("up")
    assert done.returncode == 0, done.stderr
    assert _compose(host) == [["up", "-d", "--wait", "--wait-timeout", "180"]]
    assert host.state["running"]["proxy"] == "healthy"


def test_a_failed_user_service_start_is_reported(host):
    host.state["systemd"].update(enabled=True, start_fails=True)
    done = host.dw("up")
    assert done.returncode == 1
    assert "journalctl --user -u daywarden" in done.stderr


def test_down_stops_containers_started_outside_the_user_service(host):
    host.state["systemd"]["enabled"] = True
    host.all_running()
    done = host.dw("down")
    assert done.returncode == 0, done.stderr
    assert _compose(host) == [["down"]]
    assert ["stop", "daywarden.service"] not in _systemctl_user(host)
    assert host.state["running"] == {}


def test_status_of_a_healthy_stack_exits_zero(host):
    host.all_running()
    done = host.dw("status", cwd=host.elsewhere)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert lines[0] == f"daywarden 20261105-184500, in {host.root}"
    assert "Start at boot: disabled" in lines
    assert "Last start through the user service: no failure" in lines
    assert lines[-3:] == ["  decisions     healthy", "  observations  healthy", "  proxy         healthy"]


def test_status_of_a_stopped_or_partly_healthy_stack_exits_non_zero(host):
    done = host.dw("status")
    assert done.returncode == 1
    assert done.stdout.splitlines()[-3:] == [
        "  decisions     not running",
        "  observations  not running",
        "  proxy         not running",
    ]
    host.state["running"] = {"decisions": "healthy", "observations": "unhealthy", "proxy": "starting"}
    done = host.dw("status")
    assert done.returncode == 1
    assert done.stdout.splitlines()[-2:] == ["  observations  unhealthy", "  proxy         starting"]


def test_status_shows_enabled_and_a_failed_start(host):
    host.state["systemd"].update(enabled=True, active="failed")
    host.state["daemon"] = "down"
    done = host.dw("status")
    assert done.returncode == 1
    assert "Start at boot: enabled" in done.stdout
    assert "Last start through the user service: failed. See journalctl --user -u daywarden." in done.stdout
    assert "The Docker daemon is not answering." in done.stdout


# enable and disable


def test_enable_turns_on_lingering_writes_the_service_and_does_not_start(host):
    done = host.dw("enable")
    assert done.returncode == 0, done.stderr
    assert host.state["linger"] == "yes"
    assert host.state["systemd"]["enabled"] is True
    assert host.state["systemd"]["active"] == "inactive"
    unit = host.unit.read_text(encoding="utf-8")
    assert f'ExecStart="{host.root}/bin/daywarden-service" start' in unit
    assert f'ExecStop="{host.root}/bin/daywarden-service" stop' in unit
    assert "Type=oneshot" in unit and "RemainAfterExit=yes" in unit and "WantedBy=default.target" in unit
    assert ["daemon-reload"] in _systemctl_user(host)
    assert "Turned on lingering for tester" in done.stdout
    assert "Enabled daywarden at boot." in done.stdout
    assert "Run dw up to start it." in done.stdout
    assert _compose(host) == []
    again = host.dw("enable")
    assert again.returncode == 0
    assert again.stdout == "daywarden is already enabled at boot. Nothing changed.\n"


def test_enable_on_a_running_daywarden_tracks_it_without_restarting(host):
    host.all_running()
    done = host.dw("enable")
    assert done.returncode == 0, done.stderr
    assert ["start", "daywarden.service"] in _systemctl_user(host)
    assert _compose(host) == []
    assert "No container was restarted." in done.stdout
    host.forget_calls()
    assert host.dw("down").returncode == 0
    assert _compose(host) == [["down"]]
    assert ["stop", "daywarden.service"] in _systemctl_user(host)


def test_enable_warns_when_docker_does_not_start_at_boot_and_still_enables(host):
    host.state["systemd"]["docker_boot"] = []
    done = host.dw("enable")
    assert done.returncode == 0, done.stderr
    assert "neither docker.service nor docker.socket is enabled at boot" in done.stdout
    assert "Fix: sudo systemctl enable docker.service" in done.stdout
    assert host.state["systemd"]["enabled"] is True


def test_enable_and_disable_need_the_user_manager(host):
    host.state["systemd"]["user_manager"] = False
    for command in ("enable", "disable"):
        done = host.dw(command)
        assert done.returncode == 1
        assert "cannot be reached with systemctl --user" in done.stderr
        assert "log in as tester directly, such as over ssh, and run dw enable" in done.stderr
    assert not host.unit.exists()


def test_enable_fails_when_lingering_cannot_be_turned_on(host):
    host.state["linger_fails"] = True
    done = host.dw("enable")
    assert done.returncode == 1
    assert "Fix: sudo loginctl enable-linger tester" in done.stderr
    assert host.state["systemd"]["enabled"] is False


def test_disable_leaves_a_running_daywarden_and_lingering_alone(host):
    assert host.dw("enable").returncode == 0
    host.all_running()
    host.forget_calls()
    done = host.dw("disable")
    assert done.returncode == 0, done.stderr
    assert host.state["systemd"]["enabled"] is False
    assert host.state["linger"] == "yes"
    assert "loginctl disable-linger" in done.stdout
    assert _compose(host) == []
    assert ["stop", "daywarden.service"] not in _systemctl_user(host)
    assert host.calls("loginctl") == []
    again = host.dw("disable")
    assert again.stdout == "daywarden is already disabled at boot. Nothing changed.\n"


# The user service


def test_the_service_start_gives_up_when_docker_does_not_answer(host):
    host.state["daemon"] = "down"
    done = host.run(host.root / "bin" / "daywarden-service", "start", env={"DAYWARDEN_DOCKER_WAIT": "1"})
    assert done.returncode == 1
    assert "the Docker daemon did not answer within 1 seconds" in done.stderr
    assert _compose(host) == []


def test_the_service_starts_and_stops_the_stack_directly(host):
    service = host.root / "bin" / "daywarden-service"
    assert host.run(service, "start").returncode == 0
    assert host.run(service, "stop").returncode == 0
    assert _compose(host) == [["up", "-d", "--wait", "--wait-timeout", "180"], ["down", "--timeout", "20"]]
    assert _systemctl_user(host) == []


def test_a_service_stop_without_docker_does_nothing_and_succeeds(host):
    host.state["daemon"] = "down"
    done = host.run(host.root / "bin" / "daywarden-service", "stop")
    assert done.returncode == 0
    assert _compose(host) == []


# Commands in the decisions container


def test_add_parent_runs_the_account_command_in_the_decisions_container(host):
    host.all_running()
    done = host.run(host.home / "bin" / "add-parent", "ada", cwd=host.elsewhere)
    assert done.returncode == 0, done.stderr
    assert _compose(host) == [["exec", "-T", "decisions", "python", "-m", "policy.accounts", "ada"]]


@pytest.mark.parametrize("command", ["add-parent", "rm-attempts"])
def test_a_container_command_passes_help_through(host, command):
    host.all_running()
    assert host.run(host.home / "bin" / command, "--help").returncode == 0
    assert _compose(host)[-1][-1] == "--help"


@pytest.mark.parametrize("command", ["add-parent", "rm-attempts"])
def test_a_container_command_says_when_daywarden_is_not_running(host, command):
    done = host.run(host.home / "bin" / command, "--help")
    assert done.returncode == 1
    assert done.stderr == "daywarden is not running. Start it with dw up.\n"
    assert _compose(host) == []
