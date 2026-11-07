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


UP = ["up", "-d", "--wait", "--wait-timeout", "180"]
DOWN_FOR_RESTART = ["down", "--remove-orphans"]
CHECK = ["python", "-m", "policy.check", "--host-dir", "config"]


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
    for command in ("up", "down", "reload", "restart", "check", "status", "enable", "disable"):
        assert f"\n  {command} " in done.stdout
    assert host.calls("docker") == []


def test_an_unknown_command_prints_the_usage_to_stderr_with_status_2(host):
    done = host.dw("frobnicate")
    assert done.returncode == 2
    assert done.stdout == ""
    assert "dw: unknown command: frobnicate" in done.stderr
    assert "usage: dw COMMAND" in done.stderr


@pytest.mark.parametrize("command", ["up", "reload", "restart", "check"])
def test_an_extra_argument_is_a_usage_error(host, command):
    host.all_running()
    done = host.dw(command, "--now")
    assert done.returncode == 2
    assert f"dw: {command} takes no arguments." in done.stderr
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
    assert _compose(host) == [CHECK_BEFORE_UP, UP]
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
    assert _compose(host) == [CHECK_BEFORE_UP, UP]
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
    assert host.dw("status").stdout.splitlines()[-3:] == [
        "  decisions     not running",
        "  observations  not running",
        "  proxy         not running",
    ]


def test_check_on_a_running_daywarden_uses_the_decisions_container_and_changes_nothing(host):
    host.all_running()
    done = host.dw("check")
    assert done.returncode == 0, done.stderr
    assert _compose(host) == [_exec_check()]
    assert host.state.get("recreated") is None and host.state.get("reloaded") is None


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
    assert _compose(host)[-1][-2:] == ["--host-dir", shown]


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
    assert done.stdout == "daywarden restarted.\n"
    assert _compose(host) == [CHECK_BEFORE_RESTART, DOWN_FOR_RESTART, UP]
    assert host.state["recreated"] == {"decisions": 1, "observations": 1, "proxy": 1}


def test_restart_with_a_broken_policy_stops_nothing(host):
    host.all_running()
    host.state["policy_errors"] = BROKEN
    done = host.dw("restart")
    assert done.returncode == 1
    assert done.stderr.startswith("dw: the policy has 2 errors. Nothing was restarted.\n")
    assert _compose(host) == [CHECK_BEFORE_RESTART]
    assert host.state.get("recreated") is None
    assert host.state["running"] == {"decisions": "healthy", "observations": "healthy", "proxy": "healthy"}


def test_restart_starts_a_stopped_daywarden_and_says_it_was_not_running(host):
    done = host.dw("restart")
    assert done.returncode == 0, done.stderr
    assert done.stdout == "daywarden was not running, so it was started. daywarden is up.\n"
    assert host.state["running"] == {"decisions": "healthy", "observations": "healthy", "proxy": "healthy"}


def test_restart_brings_back_a_service_stopped_by_hand(host):
    host.state["running"] = {"decisions": "healthy", "proxy": "healthy"}
    done = host.dw("restart")
    assert done.returncode == 0, done.stderr
    assert host.state["running"] == {"decisions": "healthy", "observations": "healthy", "proxy": "healthy"}


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
        "The decisions and observations services are using the reloaded policy.\n"
    )
    assert _compose(host) == [
        _exec_check("--quiet", "--refused", "Nothing was reloaded."),
        _reload("decisions"),
        _reload("observations"),
        ["config", "--hash", "*"],
    ]
    assert host.state["reloaded"] == ["decisions", "observations"]
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
