"""S014: dw, add-parent, rm-attempts, and the user service on an installed daywarden."""

import os
import signal

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


UP = ["up", "-d", "--wait", "--wait-timeout", "180"]
URL = ["exec", "-T", "autoconfig", "python", "-m", "policy.autoconfig", "--url"]
SAID_URL = "Proxy configuration URL: http://tundra:8088/proxy.pac\n"
ALL_HEALTHY = {"decisions": "healthy", "observations": "healthy", "proxy": "healthy", "autoconfig": "healthy"}
DOWN_FOR_RESTART = ["down", "--remove-orphans"]
NAMES = "tundra,localhost,127.0.0.1"
CHECK = ["python", "-m", "policy.check", "--host-dir", "config", "--parent-names", NAMES]


def _run_check(*extra):
    """The policy check in a new container, as dw runs it while daywarden is down or about to start."""
    return ["--progress", "quiet", "run", "--rm", "--no-deps", "-T", "--quiet-build", "decisions", *CHECK, *extra]


def _exec_check(*extra):
    return ["exec", "-T", "decisions", *CHECK, *extra]


def _reload(service):
    return ["exec", "-T", service, "python", "-m", "policy.reload", "--service", service, "--host-dir", "config"]


CHECK_BEFORE_UP = _run_check("--quiet", "--refused", "daywarden was not started.")
CHECK_BEFORE_RESTART = _run_check("--quiet", "--refused", "Nothing was restarted.")
BROKEN = ["config/policy.yaml:3:1: unknown setting timezon", "config/policy.yaml:9:5: site groups 'a' and 'b' both have priority 1"]


# Usage


@pytest.mark.parametrize("args", [(), ("help",), ("--help",), ("-h",)])
def test_the_usage_lists_every_command(host, args):
    done = host.dw(*args)
    assert done.returncode == 0
    for command in ("up", "down", "reload", "restart", "check", "status", "logs", "enable", "disable"):
        assert f"\n  {command} " in done.stdout
    assert "down --keep" in done.stdout and "restart --keep" in done.stdout
    assert host.calls("docker") == []


def test_an_unknown_command_prints_the_usage_to_stderr_with_status_2(host):
    done = host.dw("frobnicate")
    assert done.returncode == 2
    assert done.stdout == ""
    assert "dw: unknown command: frobnicate" in done.stderr
    assert "usage: dw COMMAND" in done.stderr


@pytest.mark.parametrize("command", ["up", "reload", "check"])
def test_an_extra_argument_is_a_usage_error(host, command):
    host.all_running()
    done = host.dw(command, "--now")
    assert done.returncode == 2
    assert f"dw: {command} takes no arguments." in done.stderr
    assert _compose(host) == []


@pytest.mark.parametrize("command", ["down", "restart"])
@pytest.mark.parametrize("args", [("--now",), ("--keep", "--now"), ("-k",), ("keep",)])
def test_down_and_restart_take_only_keep(host, command, args):
    host.all_running()
    done = host.dw(command, *args)
    assert done.returncode == 2
    assert f"dw: {command} takes no arguments other than --keep." in done.stderr
    assert _compose(host) == []
    assert host.state["running"] == ALL_HEALTHY


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
    assert _compose(host) == [CHECK_BEFORE_UP, UP, URL]
    assert done.stdout == "daywarden is up.\n" + SAID_URL
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
    host.state["running"] = {"decisions": "healthy", "observations": "healthy", "proxy": "healthy"}
    done = host.dw("up")
    assert done.returncode == 0, done.stderr
    assert _compose(host) == [CHECK_BEFORE_UP, UP, URL]
    assert host.state["running"]["autoconfig"] == "healthy"


def test_a_failed_user_service_start_is_reported(host):
    host.state["systemd"].update(enabled=True, start_fails=True)
    done = host.dw("up")
    assert done.returncode == 1
    assert "dw: the daywarden user service did not start. See dw logs boot." in done.stderr


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
    assert lines[-5:] == [
        "Proxy configuration URL: http://tundra:8088/proxy.pac",
        "  decisions     healthy",
        "  observations  healthy",
        "  proxy         healthy",
        "  autoconfig    healthy",
    ]


def test_status_of_a_stopped_or_partly_healthy_stack_exits_non_zero(host):
    done = host.dw("status")
    assert done.returncode == 1
    assert done.stdout.splitlines()[-4:] == [
        "  decisions     not running",
        "  observations  not running",
        "  proxy         not running",
        "  autoconfig    not running",
    ]
    host.state["running"] = {"decisions": "healthy", "observations": "unhealthy", "proxy": "starting", "autoconfig": "healthy"}
    done = host.dw("status")
    assert done.returncode == 1
    assert done.stdout.splitlines()[-3:] == ["  observations  unhealthy", "  proxy         starting", "  autoconfig    healthy"]
    host.all_running()
    host.state["running"]["autoconfig"] = "unhealthy"
    assert host.dw("status").returncode == 1


def test_status_shows_enabled_and_a_failed_start(host):
    host.state["systemd"].update(enabled=True, active="failed")
    host.state["daemon"] = "down"
    done = host.dw("status")
    assert done.returncode == 1
    assert "Start at boot: enabled" in done.stdout
    assert "Last start through the user service: failed. See dw logs boot." in done.stdout
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
    assert _compose(host) == [CHECK_BEFORE_UP, UP, ["down", "--timeout", "20"]]
    assert _systemctl_user(host) == []


def test_the_service_start_refuses_a_broken_policy_so_the_start_fails(host):
    host.state["policy_errors"] = BROKEN
    done = host.run(host.root / "bin" / "daywarden-service", "start")
    assert done.returncode == 1
    assert "dw: the policy has 2 errors. daywarden was not started.\n" + "\n".join(BROKEN) in done.stderr
    assert _compose(host) == [CHECK_BEFORE_UP]
    assert host.state["running"] == {}


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


# check


def test_check_on_a_stopped_daywarden_runs_in_a_new_container_and_starts_nothing(host):
    done = host.dw("check", cwd=host.elsewhere)
    assert done.returncode == 0, done.stderr
    assert done.stdout == "household timezone Australia/Sydney\n"
    assert _compose(host) == [_run_check()]
    assert host.state["running"] == {}
    assert host.dw("status").stdout.splitlines()[-4:] == [
        "  decisions     not running",
        "  observations  not running",
        "  proxy         not running",
        "  autoconfig    not running",
    ]


def test_check_on_a_running_daywarden_uses_the_decisions_container_and_changes_nothing(host):
    host.all_running()
    done = host.dw("check")
    assert done.returncode == 0, done.stderr
    assert _compose(host) == [_exec_check()]
    assert host.state.get("recreated") is None and host.state.get("reloaded") is None


def test_check_is_given_parent_names_from_env_even_while_the_containers_have_the_old_list(host):
    host.all_running()
    env = host.root / ".env"
    env.write_text(env.read_text().replace(f"PARENT_NAMES={NAMES}", "PARENT_NAMES=tundra,tundra.lan"))
    done = host.dw("check")
    assert done.returncode == 0, done.stderr
    [call] = _compose(host)
    assert call[call.index("--parent-names") + 1] == "tundra,tundra.lan"


@pytest.mark.parametrize("running", [False, True])
def test_check_lists_every_error_and_exits_1(host, running):
    if running:
        host.all_running()
    host.state["policy_errors"] = BROKEN
    done = host.dw("check")
    assert done.returncode == 1
    assert done.stderr == "dw: the policy has 2 errors.\n" + "\n".join(BROKEN) + "\n"


@pytest.mark.parametrize(
    ("config_dir", "shown"),
    [("./config", "config"), ("conf.d", "conf.d"), ("{root}/mine", "mine"), ("/srv/daywarden", "/srv/daywarden")],
)
def test_check_names_the_configuration_directory_as_the_parent_writes_it(host, config_dir, shown):
    done = host.dw("check", env={"DAYWARDEN_CONFIG_DIR": config_dir.format(root=host.root)})
    assert done.returncode == 0, done.stderr
    call = _compose(host)[-1]
    assert call[call.index("--host-dir") + 1] == shown


# up with a broken policy


@pytest.mark.parametrize("running", [False, True])
def test_up_with_a_broken_policy_starts_nothing(host, running):
    if running:
        host.all_running()
    before = dict(host.state["running"])
    host.state["policy_errors"] = BROKEN
    done = host.dw("up")
    assert done.returncode == 1
    assert done.stderr == "dw: the policy has 2 errors. daywarden was not started.\n" + "\n".join(BROKEN) + "\n"
    assert _compose(host) == [CHECK_BEFORE_UP]
    assert host.state["running"] == before


# restart


def test_restart_checks_then_replaces_every_container_and_waits_for_health(host):
    host.all_running()
    done = host.dw("restart")
    assert done.returncode == 0, done.stderr
    assert done.stdout == "daywarden restarted.\n" + SAID_URL
    assert _compose(host) == [CHECK_BEFORE_RESTART, DOWN_FOR_RESTART, UP, URL]
    assert host.state["recreated"] == {"decisions": 1, "observations": 1, "proxy": 1, "autoconfig": 1}


def test_restart_with_a_broken_policy_stops_nothing(host):
    host.all_running()
    host.state["policy_errors"] = BROKEN
    done = host.dw("restart")
    assert done.returncode == 1
    assert done.stderr.startswith("dw: the policy has 2 errors. Nothing was restarted.\n")
    assert _compose(host) == [CHECK_BEFORE_RESTART]
    assert host.state.get("recreated") is None
    assert host.state["running"] == ALL_HEALTHY


def test_restart_starts_a_stopped_daywarden_and_says_it_was_not_running(host):
    done = host.dw("restart")
    assert done.returncode == 0, done.stderr
    assert done.stdout == "daywarden was not running, so it was started. daywarden is up.\n" + SAID_URL
    assert host.state["running"] == ALL_HEALTHY


def test_restart_brings_back_a_service_stopped_by_hand(host):
    host.state["running"] = {"decisions": "healthy", "proxy": "healthy"}
    done = host.dw("restart")
    assert done.returncode == 0, done.stderr
    assert host.state["running"] == ALL_HEALTHY


def test_restart_reports_a_service_that_does_not_become_healthy_as_up_does(host):
    host.all_running()
    host.state["up_fails"] = {"proxy": "unhealthy"}
    host.state["logs"] = {"proxy": "address already in use"}
    done = host.dw("restart")
    assert done.returncode == 1
    assert "dw: these services did not become healthy: proxy (unhealthy)" in done.stderr
    assert "The last lines proxy logged:\n  address already in use\n" in done.stderr


def test_restart_while_enabled_leaves_the_user_service_active_and_down_still_stops_it(host):
    host.state["systemd"].update(enabled=True, active="failed")
    host.all_running()
    done = host.dw("restart")
    assert done.returncode == 0, done.stderr
    assert ["start", "daywarden.service"] in _systemctl_user(host)
    assert "Last start through the user service: no failure" in host.dw("status").stdout
    host.forget_calls()
    assert host.dw("down").returncode == 0
    assert _compose(host) == [["down"]]
    assert host.state["running"] == {}


# reload


def test_reload_checks_then_reloads_both_services_without_touching_a_container(host):
    host.all_running()
    done = host.dw("reload")
    assert done.returncode == 0, done.stderr
    assert done.stdout == (
        "household timezone Australia/Sydney\n"
        "The decisions, observations, and autoconfig services are using the reloaded policy.\n"
    )
    assert _compose(host) == [
        _exec_check("--quiet", "--refused", "Nothing was reloaded."),
        _reload("decisions"),
        _reload("observations"),
        _reload("autoconfig"),
        ["config", "--hash", "*"],
    ]
    assert host.state["reloaded"] == ["decisions", "observations", "autoconfig"]
    assert host.state.get("recreated") is None


def test_reload_with_a_broken_policy_reloads_nothing(host):
    host.all_running()
    host.state["policy_errors"] = BROKEN
    done = host.dw("reload")
    assert done.returncode == 1
    assert done.stderr == "dw: the policy has 2 errors. Nothing was reloaded.\n" + "\n".join(BROKEN) + "\n"
    assert host.state.get("reloaded") is None


@pytest.mark.parametrize(
    ("refusing", "said", "reloaded"),
    [
        ("decisions", "", []),
        ("observations", "the decisions service is using the reloaded policy, and the observations service is not", ["decisions"]),
        (
            "autoconfig",
            "the decisions and observations services are using the reloaded policy, and the autoconfig service is not",
            ["decisions", "observations"],
        ),
    ],
)
def test_a_service_that_refuses_the_reload_is_named_and_dw_exits_1(host, refusing, said, reloaded):
    host.all_running()
    host.state["reload_refused"] = {refusing: f"dw: the policy has 1 error. The {refusing} service did not reload."}
    done = host.dw("reload")
    assert done.returncode == 1
    assert f"The {refusing} service did not reload." in done.stderr
    assert said in done.stderr
    assert host.state.get("reloaded", []) == reloaded


def test_reload_names_the_services_a_changed_env_would_change_and_restarts_nothing(host):
    host.all_running()
    host.state["config_hash"] = {"proxy": "new-proxy", "decisions": "new-decisions"}
    done = host.dw("reload")
    assert done.returncode == 0, done.stderr
    assert "Warning: .env or docker-compose.yml has changed since these containers were created" in done.stdout
    assert "Still running with the old settings: decisions, proxy. Run dw restart to apply the changes." in done.stdout
    assert host.state.get("recreated") is None
    assert not any(call[0] in ("up", "down", "restart") for call in _compose(host))


@pytest.mark.parametrize(("errors", "said"), [([], "dw up will use this policy."), (BROKEN, "once these errors are fixed")])
def test_reload_on_a_stopped_daywarden_checks_says_so_and_starts_nothing(host, errors, said):
    host.state["policy_errors"] = errors
    done = host.dw("reload")
    assert done.returncode == 1
    assert "daywarden is not running, so nothing was reloaded." in done.stderr
    assert said in done.stderr
    assert _compose(host) == [_run_check("--quiet", "--refused", "Nothing was reloaded.")]
    assert host.state["running"] == {}


def test_reload_with_the_observations_service_stopped_says_so(host):
    host.state["running"] = {"decisions": "healthy", "proxy": "healthy"}
    done = host.dw("reload")
    assert done.returncode == 1
    assert "The observations service is not running. dw up starts it with this policy." in done.stderr
    assert host.state["reloaded"] == ["decisions"]


def test_reload_with_the_autoconfig_service_stopped_says_so(host):
    host.state["running"] = {"decisions": "healthy", "observations": "healthy", "proxy": "healthy"}
    done = host.dw("reload")
    assert done.returncode == 1
    assert "The autoconfig service is not running. dw up starts it with this policy." in done.stderr
    assert host.state["reloaded"] == ["decisions", "observations"]


# Ports from PORT_BASE


def _set_env(host, **settings):
    """Replace the installed .env's port lines with these settings."""
    lines = [line for line in (host.root / ".env").read_text().splitlines() if not line.startswith("PORT_BASE=")]
    lines += [f"{key}={value}" for key, value in settings.items()]
    (host.root / ".env").write_text("\n".join(lines) + "\n")


def _ports(host):
    return {key: host.state["up_env"][key] for key in ("PROXY_PORT", "POLICY_PORT", "PROXY_CONFIG_PORT")}


def test_the_ports_default_to_the_block_from_8080(host):
    _set_env(host)
    assert host.dw("up").returncode == 0
    assert _ports(host) == {"PROXY_PORT": "8080", "POLICY_PORT": "8084", "PROXY_CONFIG_PORT": "8088"}


@pytest.mark.parametrize("command", ["up", "restart"])
def test_port_base_moves_every_port_and_a_port_set_on_its_own_wins(host, command):
    _set_env(host, PORT_BASE="9080")
    done = host.dw(command)
    assert done.returncode == 0, done.stderr
    assert _ports(host) == {"PROXY_PORT": "9080", "POLICY_PORT": "9084", "PROXY_CONFIG_PORT": "9088"}
    assert done.stdout.endswith("Proxy configuration URL: http://tundra:9088/proxy.pac\n")
    _set_env(host, PORT_BASE="9080", POLICY_PORT="8090")
    assert host.dw(command).returncode == 0
    assert _ports(host) == {"PROXY_PORT": "9080", "POLICY_PORT": "8090", "PROXY_CONFIG_PORT": "9088"}
    assert host.dw(command, env={"PROXY_CONFIG_PORT": "7000"}).returncode == 0
    assert _ports(host)["PROXY_CONFIG_PORT"] == "7000"


@pytest.mark.parametrize(
    ("settings", "said"),
    [
        ({"PORT_BASE": "80x"}, "PORT_BASE must be a whole number from 1 to 65535, such as 8080, not '80x'."),
        ({"PORT_BASE": "65530"}, "PORT_BASE 65530 puts PROXY_CONFIG_PORT at 65530+8 = 65538, above 65535."),
        ({"PORT_BASE": "8080", "PROXY_PORT": "8088"}, "PROXY_PORT and PROXY_CONFIG_PORT are both 8088. Each port must be different."),
        ({"PORT_BASE": "8080", "POLICY_PORT": "70000"}, "POLICY_PORT must be a whole number from 1 to 65535, not '70000'."),
    ],
)
@pytest.mark.parametrize(("command", "refused"), [("up", "daywarden was not started."), ("restart", "Nothing was restarted.")])
def test_ports_that_cannot_be_used_are_refused_and_nothing_starts_or_stops(host, settings, said, command, refused):
    host.all_running()
    _set_env(host, **settings)
    done = host.dw(command)
    assert done.returncode == 1
    assert done.stderr == f"dw: the ports in {host.root}/.env cannot be used. {refused}\n  {said}\n"
    assert _compose(host) == []
    assert host.state["running"] == ALL_HEALTHY


def test_down_still_stops_daywarden_with_ports_that_cannot_be_used(host):
    host.all_running()
    _set_env(host, PORT_BASE="nope")
    assert host.dw("down").returncode == 0
    assert host.state["running"] == {}


def test_a_new_port_base_makes_reload_name_the_services_that_need_a_restart(host):
    assert host.dw("up").returncode == 0
    _set_env(host, PORT_BASE="9080")
    done = host.dw("reload")
    assert done.returncode == 0, done.stderr
    assert "Still running with the old settings: autoconfig, decisions, proxy. Run dw restart to apply the changes." in done.stdout
    assert host.dw("restart").returncode == 0
    assert "Warning" not in host.dw("reload").stdout


def test_status_of_a_stopped_daywarden_names_the_url_from_this_machine(host):
    _set_env(host, PORT_BASE="9080")
    done = host.dw("status")
    assert "Proxy configuration URL: http://tundra:9088/proxy.pac" in done.stdout.splitlines()
    assert ["exec", "-T", "autoconfig"] not in [call[:3] for call in _compose(host)]


def test_status_of_a_running_daywarden_asks_the_service_for_the_url(host):
    host.all_running()
    host.state["config_url"] = "http://tasks.example:8088/proxy.pac"
    done = host.dw("status")
    assert "Proxy configuration URL: http://tasks.example:8088/proxy.pac" in done.stdout.splitlines()
    assert URL in _compose(host)


# logs (S021)

LOG_CHECKS = [["ps", "-a", "-q", service] for service in ("decisions", "observations", "proxy", "autoconfig")]
EVERY_SERVICE = ["decisions", "observations", "proxy", "autoconfig"]
NOTHING_TO_SHOW = (
    "  dw down, dw restart, and a reboot remove the containers and what they logged.\n"
    "  dw down --keep and dw restart --keep keep them.\n"
)


def _logs_calls(host):
    return [call for call in _compose(host) if call[:1] == ["logs"]]


def _journalctl(host):
    return [call[1:] for call in host.calls("journalctl")]


def test_logs_shows_the_last_100_lines_of_every_service_from_any_directory(host):
    host.all_running()
    host.state["logs"] = {"decisions": "decision deny GET https://www.youtube.com/ (video) for kids", "proxy": "listening"}
    done = host.dw("logs", cwd=host.elsewhere)
    assert done.returncode == 0, done.stderr
    assert _compose(host) == [*LOG_CHECKS, ["logs", "--tail", "100", *EVERY_SERVICE]]
    assert done.stdout.splitlines() == [
        "decisions-1  | decision deny GET https://www.youtube.com/ (video) for kids",
        "observations-1  | observations said nothing",
        "proxy-1  | listening",
        "autoconfig-1  | autoconfig said nothing",
    ]
    assert done.stderr == ""
    assert host.calls("journalctl") == []
    assert list(host.elsewhere.iterdir()) == []


def test_logs_of_named_services_shows_only_those(host):
    host.all_running()
    done = host.dw("logs", "proxy", "decisions")
    assert done.returncode == 0, done.stderr
    assert _logs_calls(host) == [["logs", "--tail", "100", "proxy", "decisions"]]


@pytest.mark.parametrize(
    ("args", "options"),
    [
        (("-f",), ["--follow", "--tail", "100"]),
        (("--follow",), ["--follow", "--tail", "100"]),
        (("-n", "5"), ["--tail", "5"]),
        (("--tail", "5"), ["--tail", "5"]),
        (("-n5",), ["--tail", "5"]),
        (("--tail=5",), ["--tail", "5"]),
        (("--tail", "all"), ["--tail", "all"]),
        (("--since", "10m"), ["--since", "10m"]),
        (("--since=2h",), ["--since", "2h"]),
        (("--since", "2026-11-08T13:00", "-n", "20"), ["--tail", "20", "--since", "2026-11-08T13:00"]),
        (("-t",), ["--tail", "100", "--timestamps"]),
        (("--timestamps",), ["--tail", "100", "--timestamps"]),
        (("-ft",), ["--follow", "--tail", "100", "--timestamps"]),
    ],
)
def test_logs_passes_the_options_on_as_docker_compose_logs_takes_them(host, args, options):
    host.all_running()
    done = host.dw("logs", *args)
    assert done.returncode == 0, done.stderr
    assert _logs_calls(host) == [["logs", *options, *EVERY_SERVICE]]


@pytest.mark.parametrize("args", [("decisions", "-f", "-n", "3"), ("-f", "decisions", "-n", "3"), ("-n", "3", "-f", "decisions")])
def test_logs_takes_options_and_names_in_any_order(host, args):
    host.all_running()
    done = host.dw("logs", *args)
    assert done.returncode == 0, done.stderr
    assert _logs_calls(host) == [["logs", "--follow", "--tail", "3", "decisions"]]


@pytest.mark.parametrize(
    ("args", "said"),
    [
        (("-n", "ten"), "dw: --tail takes a whole number of lines, or all, not 'ten'."),
        (("--tail", "-5"), "dw: --tail takes a whole number of lines, or all, not '-5'."),
        (("--tail=1.5",), "dw: --tail takes a whole number of lines, or all, not '1.5'."),
        (("-n",), "dw: -n needs a value."),
        (("--since",), "dw: --since needs a value."),
        (("--colour",), "dw: logs has no option --colour."),
        (("-x",), "dw: logs has no option -x."),
        (
            ("decisions", "squid"),
            "dw: logs has no service named 'squid'. The names are decisions, observations, proxy, autoconfig, and boot.",
        ),
        (("boot", "decisions"), "dw: boot cannot be combined with other names. Run dw logs boot on its own."),
        (("proxy", "boot"), "dw: boot cannot be combined with other names. Run dw logs boot on its own."),
    ],
)
def test_a_logs_usage_mistake_exits_2_and_shows_nothing(host, args, said):
    host.all_running()
    host.state["journal"] = ["daywarden-service started"]
    done = host.dw("logs", *args)
    assert done.returncode == 2
    assert done.stdout == ""
    assert done.stderr == f"{said}\nRun dw logs --help for the options and the service names.\n"
    assert host.calls("docker") == [] and host.calls("journalctl") == []


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_logs_help_lists_the_options_and_the_names(host, flag):
    done = host.dw("logs", "decisions", flag)
    assert done.returncode == 0
    for option in ("-f, --follow", "-n, --tail N", "--since WHEN", "-t, --timestamps", "-h, --help"):
        assert option in done.stdout
    for name in (*EVERY_SERVICE, "boot"):
        assert f"\n  {name} " in done.stdout
    assert host.calls("docker") == []


def test_an_invalid_since_names_the_value_and_shows_nothing(host):
    host.all_running()
    done = host.dw("logs", "--since", "yesterday")
    assert done.returncode == 1
    assert done.stdout == ""
    assert '"yesterday"' in done.stderr


def test_logs_works_with_ports_that_cannot_be_used(host):
    host.all_running()
    _set_env(host, PORT_BASE="nope")
    done = host.dw("logs", "decisions")
    assert done.returncode == 0, done.stderr
    assert done.stdout == "decisions-1  | decisions said nothing\n"


def test_logs_says_when_the_docker_daemon_is_not_answering(host):
    host.state["daemon"] = "down"
    done = host.dw("logs")
    assert done.returncode == 1
    assert done.stderr == "dw: the Docker daemon is not answering, so the logs cannot be read.\n"
    assert _compose(host) == []


def test_logs_of_stopped_containers_shows_what_they_logged_and_a_follow_returns(host):
    host.state["exited"] = list(EVERY_SERVICE)
    host.state["logs"] = {"observations": "Traceback: ConfigError"}
    host.state["follow_waits"] = True
    done = host.dw("logs", "-f")
    assert done.returncode == 0, done.stderr
    assert _logs_calls(host) == [["logs", "--tail", "100", *EVERY_SERVICE]]
    assert "observations-1  | Traceback: ConfigError" in done.stdout.splitlines()
    assert done.stderr == "dw: none of these services is running, so there are no new lines to follow.\n"
    assert host.dw("logs").stderr == ""


def test_a_follow_with_one_service_running_follows(host):
    host.state["running"] = {"decisions": "healthy"}
    host.state["exited"] = ["observations"]
    done = host.dw("logs", "-f", "observations", "decisions")
    assert done.returncode == 0, done.stderr
    assert _logs_calls(host) == [["logs", "--follow", "--tail", "100", "observations", "decisions"]]


def test_logs_with_no_containers_says_there_is_nothing_to_show_and_mentions_keep(host):
    done = host.dw("logs")
    assert done.returncode == 1
    assert done.stdout == ""
    assert done.stderr == "dw: there is nothing to show, because daywarden has no containers.\n" + NOTHING_TO_SHOW
    assert _logs_calls(host) == []


@pytest.mark.parametrize(
    ("names", "said"),
    [(("observations",), "observations has no container"), (("observations", "autoconfig"), "observations and autoconfig have no containers")],
)
def test_logs_of_named_services_with_no_container_say_so(host, names, said):
    host.state["running"] = {"decisions": "healthy", "proxy": "healthy"}
    done = host.dw("logs", *names)
    assert done.returncode == 1
    assert done.stderr == f"dw: there is nothing to show, because {said}.\n" + NOTHING_TO_SHOW
    assert _logs_calls(host) == []


def test_logs_shows_the_services_that_have_a_container_and_names_the_others(host):
    host.state["running"] = {"decisions": "healthy"}
    host.state["exited"] = ["proxy"]
    done = host.dw("logs")
    assert done.returncode == 0, done.stderr
    assert _logs_calls(host) == [["logs", "--tail", "100", "decisions", "proxy"]]
    assert done.stderr == "dw: observations and autoconfig have no containers, so nothing is shown for them.\n"
    done = host.dw("logs", "decisions", "autoconfig")
    assert done.stderr == "dw: autoconfig has no container, so nothing is shown for it.\n"
    assert done.stdout == "decisions-1  | decisions said nothing\n"


@pytest.mark.parametrize("names", [(), ("boot",)])
def test_ctrl_c_ends_a_follow_quietly(host, names):
    host.all_running()
    host.state["journal"] = ["Started daywarden household proxy."]
    host.state["follow_waits"] = True
    following = host.start_dw("logs", "-f", *names)
    try:
        for line in following.stdout:
            if line == "following\n":
                break
        os.killpg(following.pid, signal.SIGINT)
        _, stderr = following.communicate(timeout=20)
    finally:
        if following.poll() is None:
            os.killpg(following.pid, signal.SIGKILL)
    assert following.returncode == 0
    assert stderr == ""


# logs boot


def test_logs_boot_shows_the_user_service_journal(host):
    host.state["journal"] = ["Nov 08 06:00:01 tundra daywarden-service[812]: dw: the policy has 1 error. daywarden was not started."]
    done = host.dw("logs", "boot", cwd=host.elsewhere)
    assert done.returncode == 0, done.stderr
    assert done.stdout == host.state["journal"][0] + "\n"
    assert _journalctl(host)[-1] == ["--user", "-u", "daywarden.service", "--no-pager", "--lines", "100"]
    assert _compose(host) == []


@pytest.mark.parametrize(
    ("args", "options"),
    [
        (("-f",), ["--follow", "--lines", "100"]),
        (("-n", "5"), ["--lines", "5"]),
        (("--tail", "all"), ["--no-tail"]),
        (("--since", "10m"), ["--no-tail", "--since", "-10m"]),
        (("--since", "1h30m", "-n", "4"), ["--lines", "4", "--since", "-1h30m"]),
        (("--since", "2026-11-08T13:00"), ["--no-tail", "--since", "2026-11-08 13:00"]),
        (("--since", "2026-11-08"), ["--no-tail", "--since", "2026-11-08"]),
        (("-t",), ["--lines", "100"]),
    ],
)
def test_logs_boot_passes_the_options_on_as_journalctl_takes_them(host, args, options):
    host.state["journal"] = ["Started daywarden household proxy."]
    done = host.dw("logs", *args, "boot")
    assert done.returncode == 0, done.stderr
    assert _journalctl(host)[-1] == ["--user", "-u", "daywarden.service", "--no-pager", *options]


def test_logs_boot_says_when_the_user_service_has_logged_nothing(host):
    done = host.dw("logs", "boot")
    assert done.returncode == 1
    assert done.stdout == ""
    assert "dw: the daywarden user service has logged nothing." in done.stderr
    assert "dw enable" in done.stderr


def test_logs_boot_needs_the_user_manager(host):
    host.state["systemd"]["user_manager"] = False
    done = host.dw("logs", "boot")
    assert done.returncode == 1
    assert done.stderr.startswith("dw: the start-at-boot log cannot be read.\n")
    assert "log in as tester directly, such as over ssh, and run dw enable" in done.stderr
    assert host.calls("journalctl") == []


# down --keep and restart --keep (S021)

UP_KEEPING = [*UP, "--remove-orphans"]
ALL_EXITED = sorted(EVERY_SERVICE)


def test_down_keep_stops_the_containers_and_keeps_them_for_logs(host):
    host.state["systemd"]["enabled"] = True
    assert host.dw("up").returncode == 0
    host.forget_calls()
    done = host.dw("down", "--keep")
    assert done.returncode == 0, done.stderr
    assert _compose(host) == [["stop"]]
    assert ["stop", "daywarden.service"] in _systemctl_user(host)
    assert done.stdout == (
        "daywarden is down.\n"
        "Its containers were kept, so dw logs can still show what they logged. dw down removes them.\n"
    )
    assert host.state["running"] == {} and host.state["exited"] == ALL_EXITED
    status = host.dw("status")
    assert status.returncode == 1
    assert status.stdout.splitlines()[-4:] == [f"  {service:<13} not running" for service in EVERY_SERVICE]
    logs = host.dw("logs")
    assert logs.returncode == 0, logs.stderr
    assert len(logs.stdout.splitlines()) == 4


def test_the_user_service_stop_leaves_kept_containers_and_still_removes_running_ones(host):
    service = host.root / "bin" / "daywarden-service"
    host.state["exited"] = list(EVERY_SERVICE)
    done = host.run(service, "stop")
    assert done.returncode == 0, done.stderr
    assert "nothing to stop" in done.stdout
    assert _compose(host) == []
    assert host.state["exited"] == list(EVERY_SERVICE)
    host.all_running()
    assert host.run(service, "stop").returncode == 0
    assert _compose(host) == [["down", "--timeout", "20"]]
    assert host.state["running"] == {} and host.state["exited"] == []


def test_down_after_down_keep_removes_the_kept_containers(host):
    assert host.dw("up").returncode == 0
    assert host.dw("down", "--keep").returncode == 0
    host.forget_calls()
    done = host.dw("down")
    assert done.returncode == 0, done.stderr
    assert done.stdout == "daywarden is down.\n"
    assert _compose(host) == [["down"]]
    assert host.state["exited"] == []
    assert host.dw("logs").returncode == 1


def test_up_after_down_keep_checks_the_policy_and_starts_the_same_containers(host):
    assert host.dw("up").returncode == 0
    ids = dict(host.state["ids"])
    assert host.dw("down", "--keep").returncode == 0
    host.forget_calls()
    done = host.dw("up")
    assert done.returncode == 0, done.stderr
    assert _compose(host) == [CHECK_BEFORE_UP, UP, URL]
    assert host.state["ids"] == ids
    assert host.state["recreated"] == {service: 1 for service in EVERY_SERVICE}
    assert host.state["running"] == ALL_HEALTHY


def test_restart_keep_checks_stops_and_starts_the_same_containers(host):
    assert host.dw("up").returncode == 0
    ids = dict(host.state["ids"])
    host.forget_calls()
    done = host.dw("restart", "--keep")
    assert done.returncode == 0, done.stderr
    assert done.stdout == "daywarden restarted.\n" + SAID_URL
    assert _compose(host) == [CHECK_BEFORE_RESTART, *LOG_CHECKS, ["stop"], UP_KEEPING, *LOG_CHECKS, URL]
    assert host.state["ids"] == ids
    assert host.state["running"] == ALL_HEALTHY


def test_restart_keep_recreates_and_names_the_services_whose_settings_changed(host):
    assert host.dw("up").returncode == 0
    _set_env(host, PORT_BASE="9080")
    done = host.dw("restart", "--keep")
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines()[:3] == [
        "Recreated because .env, docker-compose.yml, or the image changed: decisions, proxy, autoconfig.",
        "  What they logged before the restart is gone.",
        "daywarden restarted.",
    ]
    assert host.state["recreated"] == {"decisions": 2, "observations": 1, "proxy": 2, "autoconfig": 2}
    assert _ports(host) == {"PROXY_PORT": "9080", "POLICY_PORT": "9084", "PROXY_CONFIG_PORT": "9088"}


def test_restart_keep_names_a_recreated_service_even_when_it_does_not_become_healthy(host):
    assert host.dw("up").returncode == 0
    host.state["config_hash"] = {"proxy": "new-proxy"}
    host.state["up_fails"] = {"proxy": "unhealthy"}
    done = host.dw("restart", "--keep")
    assert done.returncode == 1
    assert "Recreated because .env, docker-compose.yml, or the image changed: proxy." in done.stdout
    assert "dw: these services did not become healthy: proxy (unhealthy)" in done.stderr
    assert "daywarden restarted." not in done.stdout


def test_restart_keep_starts_a_stopped_daywarden(host):
    done = host.dw("restart", "--keep")
    assert done.returncode == 0, done.stderr
    assert done.stdout == "daywarden was not running, so it was started. daywarden is up.\n" + SAID_URL
    assert host.state["running"] == ALL_HEALTHY


def test_restart_keep_with_a_broken_policy_stops_nothing(host):
    host.all_running()
    host.state["policy_errors"] = BROKEN
    done = host.dw("restart", "--keep")
    assert done.returncode == 1
    assert done.stderr.startswith("dw: the policy has 2 errors. Nothing was restarted.\n")
    assert _compose(host) == [CHECK_BEFORE_RESTART]
    assert host.state["running"] == ALL_HEALTHY
