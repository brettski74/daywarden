"""S014: install.sh checks the machine, installs ~/daywarden, and upgrades it."""

import time

import pytest

from hostfakes import NEWER, ROOT, Host, make_package

LINKED = ("dw", "rm-attempts", "add-parent", "cut-clips")


@pytest.fixture
def host(tmp_path):
    (tmp_path / "machine").mkdir()
    return Host(tmp_path / "machine")


@pytest.fixture
def package(tmp_path):
    return make_package(tmp_path)


@pytest.fixture
def newer(tmp_path):
    (tmp_path / "newer").mkdir()
    return make_package(tmp_path / "newer", NEWER)


def _env_value(path, key):
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    raise AssertionError(f"{key} is not in {path}")


def _server_lines(bypass_text):
    """The non-comment lines of bypass.txt that are not school hosts."""
    school = {line for line in (ROOT / "config" / "bypass.txt").read_text(encoding="utf-8").splitlines() if "." in line}
    return [line for line in bypass_text.splitlines() if line and not line.startswith("#") and line not in school]


def _compose_verbs(host):
    """The compose subcommand of each docker compose call, such as up or down."""
    verbs = []
    for call in host.calls("docker"):
        if call[1:2] == ["compose"]:
            rest = call[2:]
            while rest and rest[0] in ("--project-directory", "--progress"):
                rest = rest[2:]
            verbs.append(rest[0])
    return verbs


def _compose_calls(host, verb):
    return [found for found in _compose_verbs(host) if found == verb]


# First install


def test_a_first_install_creates_the_layout_links_the_commands_and_does_not_start(host, package):
    done = host.install(package)
    assert done.returncode == 0, done.stderr + done.stdout
    root = host.root
    for path in ("docker-compose.yml", ".env", ".env.sample", "config/policy.yaml.sample", "config/bypass.txt.sample"):
        assert (root / path).is_file(), path
    assert (root / "VERSION").read_text(encoding="utf-8").strip() == "20261105-184500"
    assert (root / "ca").is_dir() and (root / "data").is_dir()
    assert (root / "lib" / "policy" / "clips.py").is_file()
    assert (root / "lib" / "policy" / "requirements.txt").is_file()
    assert not (root / "lib" / "policy" / "portal").exists()
    assert (root / "config" / "policy.yaml").read_bytes() == (ROOT / "config" / "policy.yaml").read_bytes()
    assert _env_value(root / ".env", "CA_VOLUME_PATH") == "${HOME}/daywarden/ca"
    assert _env_value(root / ".env", "DAYWARDEN_DATA_DIR") == "${HOME}/daywarden/data"
    for name in LINKED:
        link = host.home / "bin" / name
        assert link.is_symlink() and link.resolve() == root / "bin" / name
    assert ["docker", "load", "--input", str(package / "images.tar")] in host.calls("docker")
    assert _compose_calls(host, "up") == []
    assert host.state["running"] == {}
    assert "Next steps:" in done.stdout
    assert "Run dw enable to start daywarden at boot." in done.stdout


def _task_files():
    return sorted(path.name for path in (ROOT / "config" / "tasks.d").iterdir() if path.suffix in (".yaml", ".yml"))


def test_a_first_install_creates_the_task_files_the_sample_policy_includes(host, package):
    done = host.install(package)
    assert done.returncode == 0, done.stderr + done.stdout
    tasks = host.root / "config" / "tasks.d"
    assert _task_files()
    for name in _task_files():
        assert (tasks / name).read_bytes() == (ROOT / "config" / "tasks.d" / name).read_bytes()
        assert (tasks / f"{name}.sample").read_bytes() == (tasks / name).read_bytes()
        assert f"~/daywarden/config/tasks.d/{name}" in done.stdout


def test_an_upgrade_that_keeps_the_policy_adds_no_task_file_beside_the_households_own(host, package, newer):
    assert host.install(package).returncode == 0
    tasks = host.root / "config" / "tasks.d"
    dropped, *others = _task_files()
    (tasks / dropped).unlink()
    if others:
        (tasks / others[0]).write_text("tasks: {}\n", encoding="utf-8")
    done = host.install(newer)
    assert done.returncode == 0, done.stderr
    assert not (tasks / dropped).exists()
    assert (tasks / f"{dropped}.sample").read_bytes() == (ROOT / "config" / "tasks.d" / dropped).read_bytes()
    if others:
        assert (tasks / others[0]).read_text(encoding="utf-8") == "tasks: {}\n"
    assert "Kept unchanged: ~/daywarden/.env, ~/daywarden/config/policy.yaml, ~/daywarden/config/bypass.txt." in done.stdout


def test_a_first_install_names_this_machine_in_parent_names_and_bypass(host, package):
    done = host.install(package)
    assert done.returncode == 0, done.stderr
    assert _env_value(host.root / ".env", "PARENT_NAMES") == "tundra,localhost,127.0.0.1"
    bypass = (host.root / "config" / "bypass.txt").read_text(encoding="utf-8")
    assert _server_lines(bypass) == ["tundra"]
    assert "classroom.google.com" in bypass.splitlines()
    assert (host.root / ".env.sample").read_bytes() == (host.root / ".env").read_bytes()
    assert (host.root / "config" / "bypass.txt.sample").read_bytes() == bypass.encode()


def test_a_search_suffix_that_resolves_here_is_added_and_one_that_does_not_is_skipped(host, package):
    (host.etc / "resolv.conf").write_text("search bakuna.net elsewhere.net\nnameserver 192.0.2.1\n", encoding="utf-8")
    host.state["dns"] = {"tundra.bakuna.net": ["192.0.2.10"]}
    done = host.install(package)
    assert done.returncode == 0, done.stderr
    assert _env_value(host.root / ".env", "PARENT_NAMES") == "tundra,tundra.bakuna.net,localhost,127.0.0.1"
    assert _server_lines((host.root / "config" / "bypass.txt").read_text(encoding="utf-8")) == ["tundra", "tundra.bakuna.net"]
    assert "Added tundra.bakuna.net" in done.stdout
    assert "Skipped tundra.elsewhere.net: does not resolve" in done.stdout


def test_a_name_on_loopback_or_on_another_machine_is_skipped_with_the_reason(host, package):
    (host.etc / "resolv.conf").write_text("search hosts.lan\ndomain bakuna.net\nsearch v6.lan\n", encoding="utf-8")
    host.state["dns"] = {
        "tundra.hosts.lan": ["127.0.1.1"],
        "tundra.bakuna.net": ["192.168.12.5"],
        "tundra.v6.lan": ["2001:db8::10"],
    }
    host.state["interfaces"] = [["eth0", "192.0.2.10/24"], ["eth0", "2001:db8::10/64"]]
    done = host.install(package)
    assert done.returncode == 0, done.stderr
    assert _env_value(host.root / ".env", "PARENT_NAMES") == "tundra,tundra.v6.lan,localhost,127.0.0.1"
    assert "Skipped tundra.hosts.lan: resolves only to loopback (127.0.1.1)" in done.stdout
    assert "Skipped tundra.bakuna.net: resolves to 192.168.12.5, not this machine" in done.stdout


def test_a_repeated_or_empty_suffix_is_used_once(host, package):
    (host.etc / "resolv.conf").write_text("search Bakuna.NET bakuna.net. .\ndomain bakuna.net\n", encoding="utf-8")
    host.state["dns"] = {"tundra.bakuna.net": ["192.0.2.10"]}
    done = host.install(package)
    assert done.returncode == 0, done.stderr
    assert _env_value(host.root / ".env", "PARENT_NAMES") == "tundra,tundra.Bakuna.NET,localhost,127.0.0.1"
    assert [call for call in host.calls("getent")] == [["getent", "ahosts", "tundra.Bakuna.NET"]]


def test_a_lookup_that_hangs_is_given_up_after_about_two_seconds(host, package):
    (host.etc / "resolv.conf").write_text("search slow.lan\n", encoding="utf-8")
    host.state["slow"] = ["tundra.slow.lan"]
    started = time.monotonic()
    done = host.install(package)
    assert done.returncode == 0, done.stderr
    assert time.monotonic() - started < 15
    assert "Skipped tundra.slow.lan: the lookup took longer than 2 seconds" in done.stdout
    assert _env_value(host.root / ".env", "PARENT_NAMES") == "tundra,localhost,127.0.0.1"


def test_no_resolv_conf_means_only_the_hostname(host, package):
    (host.etc / "resolv.conf").unlink()
    done = host.install(package)
    assert done.returncode == 0, done.stderr
    assert _env_value(host.root / ".env", "PARENT_NAMES") == "tundra,localhost,127.0.0.1"
    assert host.calls("getent") == []


# Start at boot on a first install


def test_answering_yes_to_start_at_boot_enables_without_starting(host, package):
    done = host.install(package, input="y\n")
    assert done.returncode == 0, done.stderr + done.stdout
    assert host.state["systemd"]["enabled"] is True
    assert host.state["linger"] == "yes"
    assert host.unit.is_file()
    assert host.state["systemd"]["active"] == "inactive"
    assert host.state["running"] == {}
    assert "Run dw enable" not in done.stdout


@pytest.mark.parametrize("answer", ["\n", "no\n", ""])
def test_anything_but_yes_to_start_at_boot_leaves_it_disabled(host, package, answer):
    done = host.install(package, input=answer)
    assert done.returncode == 0, done.stderr
    assert host.state["systemd"]["enabled"] is False
    assert not host.unit.exists()


def test_without_a_user_manager_the_boot_question_is_skipped_with_the_advice(host, package):
    host.state["systemd"]["user_manager"] = False
    done = host.install(package, input="y\n")
    assert done.returncode == 0, done.stderr
    assert "Start daywarden automatically at boot?" not in done.stdout
    assert "cannot be reached with systemctl --user" in done.stdout
    assert "log in as tester directly, such as over ssh, and run dw enable" in done.stdout
    assert host.state["systemd"]["enabled"] is False


# Upgrades


def test_an_upgrade_keeps_the_configuration_and_replaces_everything_else(host, package, newer):
    assert host.install(package).returncode == 0
    root = host.root
    edits = {
        root / ".env": "PROXY_PORT=3128\n",
        root / "config" / "policy.yaml": "entry: mine\n",
        root / "config" / "bypass.txt": "mine.example\n",
    }
    for path, text in edits.items():
        path.write_text(text, encoding="utf-8")
    (root / ".env.sample").write_text("stale\n", encoding="utf-8")
    (root / "bin" / "dw").write_text("stale\n", encoding="utf-8")
    (root / "docker-compose.yml").write_text("stale\n", encoding="utf-8")
    host.forget_calls()
    done = host.install(newer)
    assert done.returncode == 0, done.stderr
    for path, text in edits.items():
        assert path.read_text(encoding="utf-8") == text
    assert (root / "VERSION").read_text(encoding="utf-8").strip() == NEWER
    assert f"daywarden-policy:{NEWER}" in (root / "docker-compose.yml").read_text(encoding="utf-8")
    assert (root / ".env.sample").read_text(encoding="utf-8") != "stale\n"
    assert (root / "bin" / "dw").read_bytes() == (ROOT / "bin" / "dw").read_bytes()
    assert "Kept unchanged: ~/daywarden/.env, ~/daywarden/config/policy.yaml, ~/daywarden/config/bypass.txt" in done.stdout
    assert "Start daywarden automatically at boot?" not in done.stdout
    assert "Next steps:" not in done.stdout


@pytest.mark.parametrize("answer", ["n\n", "\n", ""])
def test_a_running_daywarden_is_not_touched_unless_the_restart_is_accepted(host, package, newer, answer):
    assert host.install(package).returncode == 0
    host.all_running()
    compose_file = (host.root / "docker-compose.yml").read_bytes()
    host.forget_calls()
    done = host.install(newer, input=answer)
    assert done.returncode != 0
    assert "Daywarden is running. Restart it to finish the upgrade? [y/N]" in done.stdout
    assert "Nothing was changed" in done.stderr
    assert (host.root / "VERSION").read_text(encoding="utf-8").strip() == "20261105-184500"
    assert (host.root / "docker-compose.yml").read_bytes() == compose_file
    assert all(call[1] != "load" for call in host.calls("docker"))
    assert _compose_calls(host, "down") == [] and _compose_calls(host, "up") == []
    assert set(host.state["running"]) == {"decisions", "observations", "proxy", "autoconfig"}


def test_accepting_the_restart_installs_then_restarts_the_stack(host, package, newer):
    assert host.install(package).returncode == 0
    host.all_running()
    host.forget_calls()
    done = host.install(newer, input="y\n")
    assert done.returncode == 0, done.stderr + done.stdout
    assert (host.root / "VERSION").read_text(encoding="utf-8").strip() == NEWER
    assert [verb for verb in _compose_verbs(host) if verb in ("run", "up", "down")] == ["run", "down", "up"]
    assert f"daywarden restarted on {NEWER}, and every service is healthy." in done.stdout
    assert host.state["running"] == {"decisions": "healthy", "observations": "healthy", "proxy": "healthy", "autoconfig": "healthy"}


def test_a_restart_that_does_not_come_back_healthy_fails_with_the_new_files_in_place(host, package, newer):
    assert host.install(package).returncode == 0
    host.all_running()
    host.state["up_fails"] = {"proxy": "unhealthy"}
    done = host.install(newer, input="yes\n")
    assert done.returncode == 1
    assert "proxy (unhealthy)" in done.stderr
    assert "did not come back healthy" in done.stdout
    assert (host.root / "VERSION").read_text(encoding="utf-8").strip() == NEWER


def test_a_stopped_daywarden_is_upgraded_without_asking_or_starting(host, package, newer):
    assert host.install(package).returncode == 0
    host.forget_calls()
    done = host.install(newer)
    assert done.returncode == 0, done.stderr
    assert "Restart it" not in done.stdout
    assert _compose_calls(host, "up") == []


def test_an_upgrade_rewrites_the_service_of_an_enabled_daywarden_without_asking(host, package, newer):
    assert host.install(package, input="y\n").returncode == 0
    host.unit.write_text("stale\n", encoding="utf-8")
    reloads = host.state["systemd"].get("reloads", 0)
    done = host.install(newer, input="n\n")
    assert done.returncode == 0, done.stderr
    assert "Start daywarden automatically at boot?" not in done.stdout
    assert host.state["systemd"]["enabled"] is True
    assert "ExecStart=" in host.unit.read_text(encoding="utf-8")
    assert host.state["systemd"]["reloads"] == reloads + 1


def test_an_upgrade_of_a_disabled_daywarden_writes_no_service(host, package, newer):
    assert host.install(package).returncode == 0
    assert host.install(newer).returncode == 0
    assert not host.unit.exists()


# Dependency checks


def test_a_stopped_daemon_and_missing_compose_are_both_reported_and_nothing_changes(host, package):
    host.state["daemon"] = "down"
    host.state["compose"] = False
    done = host.install(package)
    assert done.returncode == 1
    assert "docker compose (the Compose v2 plugin) is not installed." in done.stderr
    assert "Fix: sudo pacman -S docker-compose" in done.stderr
    assert "The Docker daemon is not running" in done.stderr
    assert "sudo systemctl enable --now docker.service" in done.stderr
    assert not host.root.exists()
    assert list((host.home / "bin").iterdir()) == []
    assert all(call[1] != "load" for call in host.calls("docker"))


def test_a_user_outside_the_docker_group_is_told_to_join_it(host, package):
    host.state["daemon"] = "denied"
    done = host.install(package)
    assert done.returncode == 1
    assert "sudo usermod -aG docker tester, then log out and back in" in done.stderr
    assert not host.root.exists()


def test_missing_docker_is_reported_with_the_pacman_command(tmp_path, package):
    (tmp_path / "machine").mkdir()
    host = Host(tmp_path / "machine", without=("docker",))
    done = host.install(package)
    assert done.returncode == 1
    assert "docker is not installed.\n  Fix: sudo pacman -S docker\n" in done.stderr
    assert not host.root.exists()


def test_warnings_are_given_with_advice_and_the_install_finishes(host, package):
    host.state["systemd"]["docker_boot"] = []
    host.state["listening"] = [8080]
    host.path = host.path.replace(f"{host.home / 'bin'}:", "")
    done = host.install(package)
    assert done.returncode == 0, done.stderr
    assert "Neither docker.service nor docker.socket is enabled at boot" in done.stdout
    assert "Fix: sudo systemctl enable docker.service" in done.stdout
    assert "Port 8080 (PROXY_PORT) is already in use by another program" in done.stdout
    assert "Port 8090" not in done.stdout
    assert "~/bin is not on the PATH" in done.stdout
    assert 'export PATH="$HOME/bin:$PATH"' in done.stdout
    assert (host.root / "VERSION").is_file()
    assert sorted(path.name for path in host.home.iterdir()) == ["bin", "daywarden"]


def test_the_ports_come_from_the_installed_env_and_a_running_daywarden_is_not_reported(host, package, newer):
    assert host.install(package).returncode == 0
    env = host.root / ".env"
    env.write_text(env.read_text(encoding="utf-8").replace("PORT_BASE=8080", "PORT_BASE=9080") + "PROXY_PORT=3128\n", encoding="utf-8")
    host.all_running()
    host.state["ports"] = {"proxy": "0.0.0.0:3128->8080/tcp", "decisions": "0.0.0.0:9084->8443/tcp", "autoconfig": ""}
    host.state["listening"] = [3128, 9084, 9088]
    done = host.install(newer, input="n\n")
    assert "already in use" not in done.stdout
    host.state["running"] = {}
    done = host.install(newer)
    assert "Port 3128 (PROXY_PORT) is already in use" in done.stdout
    assert "Port 9084 (POLICY_PORT) is already in use" in done.stdout
    assert "Port 9088 (PROXY_CONFIG_PORT) is already in use" in done.stdout
    assert "change PORT_BASE or PROXY_CONFIG_PORT in ~/daywarden/.env" in done.stdout


def test_a_new_install_sets_port_base_and_not_the_three_ports(host, package):
    assert host.install(package).returncode == 0
    assert _env_value(host.root / ".env", "PORT_BASE") == "8080"
    lines = (host.root / ".env").read_text(encoding="utf-8").splitlines()
    assert not [line for line in lines if line.startswith(("PROXY_PORT=", "POLICY_PORT=", "PROXY_CONFIG_PORT="))]


def test_a_first_install_warns_about_each_default_port_in_use(host, package):
    host.state["listening"] = [8084, 8088]
    done = host.install(package)
    assert done.returncode == 0, done.stderr
    assert "Port 8080" not in done.stdout
    assert "Port 8084 (POLICY_PORT) is already in use" in done.stdout
    assert "Port 8088 (PROXY_CONFIG_PORT) is already in use" in done.stdout


def test_an_upgrade_leaves_the_port_settings_of_an_existing_env_alone(host, package, newer):
    assert host.install(package).returncode == 0
    env = host.root / ".env"
    old = env.read_text(encoding="utf-8").replace("PORT_BASE=8080\n", "PROXY_PORT=8080\nPOLICY_PORT=8090\n")
    env.write_text(old, encoding="utf-8")
    host.state["listening"] = [8090]
    done = host.install(newer)
    assert done.returncode == 0, done.stderr
    assert env.read_text(encoding="utf-8") == old
    assert "Port 8090 (POLICY_PORT) is already in use" in done.stdout


def test_ports_that_cannot_be_used_are_a_warning(host, package):
    assert host.install(package).returncode == 0
    env = host.root / ".env"
    env.write_text(env.read_text(encoding="utf-8").replace("PORT_BASE=8080", "PORT_BASE=65530"), encoding="utf-8")
    done = host.install(package)
    assert done.returncode == 0, done.stderr
    assert "PORT_BASE 65530 puts PROXY_CONFIG_PORT at 65530+8 = 65538, above 65535. dw up will refuse to start." in done.stdout


def test_a_command_in_bin_that_daywarden_did_not_install_stops_the_install(host, package):
    (host.home / "bin" / "dw").write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
    done = host.install(package)
    assert done.returncode == 1
    assert "~/bin/dw is already there, and daywarden did not install it." in done.stderr
    assert (host.home / "bin" / "dw").read_text(encoding="utf-8") == "#!/bin/sh\necho mine\n"
    assert not host.root.exists()


def test_root_is_refused(host, package):
    host.state["uid"] = 0
    done = host.install(package)
    assert done.returncode == 1
    assert "do not run this as root" in done.stderr
    assert host.calls("docker") == []


def test_a_package_for_another_architecture_names_both(host, package):
    (package / "ARCH").write_text("riscv64\n", encoding="utf-8")
    done = host.install(package)
    assert done.returncode == 1
    assert "built for riscv64, but this machine is" in done.stderr
    assert not host.root.exists()


def test_the_install_works_from_any_directory(host, package):
    elsewhere = host.tmp / "elsewhere"
    elsewhere.mkdir()
    done = host.install(package, cwd=elsewhere)
    assert done.returncode == 0, done.stderr
    assert list(elsewhere.iterdir()) == []


# cut-clips and its environment


def test_without_python_cut_clips_is_skipped_and_says_to_run_install_again(tmp_path, package):
    (tmp_path / "machine").mkdir()
    host = Host(tmp_path / "machine", without=("python3",))
    done = host.install(package)
    assert done.returncode == 0, done.stderr
    assert "python3 is not installed, so cut-clips will not work." in done.stdout
    assert "Fix: sudo pacman -S python, then run install.sh again" in done.stdout
    assert not (host.root / "venv").exists()
    clips = host.run(host.home / "bin" / "cut-clips", "--help")
    assert clips.returncode == 1
    assert "cut-clips: its Python environment in" in clips.stderr
    assert "Run install.sh again." in clips.stderr
    assert "Traceback" not in clips.stderr


def test_ffmpeg_without_opus_is_a_warning(host, package):
    host.state["ffmpeg"] = "aac-only"
    done = host.install(package)
    assert done.returncode == 0, done.stderr
    assert "ffmpeg is not installed, or cannot encode Opus (libopus)" in done.stdout
    assert "Fix: sudo pacman -S ffmpeg" in done.stdout


def _venv_builds(host):
    return [call for call in host.calls("python3") if call[1:3] == ["-m", "venv"]]


def test_the_environment_is_built_once_and_rebuilt_when_requirements_or_python_change(host, package, newer):
    assert host.install(package).returncode == 0
    assert len(_venv_builds(host)) == 1
    pip = [call for call in host.calls("venv-python") if call[1:3] == ["-m", "pip"]]
    assert pip and pip[0][-1] == str(host.root / "lib" / "policy" / "requirements.txt")
    host.forget_calls()
    assert host.install(newer).returncode == 0
    assert _venv_builds(host) == []
    requirements = newer / "lib" / "policy" / "requirements.txt"
    requirements.write_text(requirements.read_text(encoding="utf-8") + "rich==14.0.0\n", encoding="utf-8")
    assert host.install(newer).returncode == 0
    assert len(_venv_builds(host)) == 1
    host.forget_calls()
    host.state["python_version"] = "3.15.0"
    assert host.install(newer).returncode == 0
    assert len(_venv_builds(host)) == 1


def test_an_unreachable_pypi_is_reported_and_everything_else_is_installed(host, package):
    host.state["pypi"] = "down"
    done = host.install(package)
    assert done.returncode == 0, done.stderr
    assert "Could not find a version that satisfies the requirement" in done.stderr
    assert "The cut-clips environment could not be built" in done.stdout
    assert "then run install.sh again" in done.stdout
    assert not (host.root / "venv").exists()
    assert (host.home / "bin" / "dw").is_symlink()
    host.state["pypi"] = "up"
    again = host.install(package)
    assert again.returncode == 0, again.stderr
    assert (host.root / "venv" / ".daywarden-build").is_file()
    host.forget_calls()
    elsewhere = host.tmp / "recordings"
    elsewhere.mkdir()
    clips = host.run(host.home / "bin" / "cut-clips", "take.m4a", "--out", "clips", cwd=elsewhere)
    assert clips.returncode == 0, clips.stderr
    assert host.calls("venv-python")[-1] == ["venv-python", "-m", "policy.clips", "take.m4a", "--out", "clips"]
    assert host.state["clips_cwd"] == str(elsewhere)
    assert host.state["clips_path"].split(":")[0] == str(host.root / "lib")


def test_a_broken_environment_makes_cut_clips_say_so(host, package):
    assert host.install(package).returncode == 0
    host.state["venv_works"] = False
    clips = host.run(host.home / "bin" / "cut-clips", "--help")
    assert clips.returncode == 1
    assert clips.stderr == f"cut-clips: its Python environment in {host.root}/venv is missing or broken. Run install.sh again.\n"
