"""S023.1: the git history of the config directory, kept by install.sh and dw."""

import os
import re
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from hostfakes import NEWER, Host, make_package

IDENTITY = "tester <tester@daywarden.invalid>"
BROKEN = ["config/policy.yaml:3:1: unknown client group 'nobody'"]


@pytest.fixture
def host(tmp_path):
    (tmp_path / "machine").mkdir()
    machine = Host(tmp_path / "machine")
    done = machine.install(make_package(tmp_path))
    assert done.returncode == 0, done.stderr
    machine.config = machine.root / "config"
    machine.all_running()
    return machine


def _git(host, *args):
    done = host.run("git", *args, cwd=host.config)
    assert done.returncode == 0, done.stderr
    return done.stdout


def _subjects(host):
    return _git(host, "log", "--format=%s").splitlines()


def _tracked(host):
    return sorted(_git(host, "ls-files").splitlines())


def _status(host):
    return _git(host, "status", "--porcelain", "--ignored=no")


def _edit(host, name="policy.yaml", old="", new="# edited by hand\n"):
    path = host.config / name
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace(old, new, 1) if old else text + new, encoding="utf-8")


# Created by install.sh


def test_a_fresh_install_commits_the_config_once_without_the_samples(host):
    assert _tracked(host) == [".gitignore", "bypass.txt", "policy.yaml"]
    assert _status(host) == ""
    subjects = _subjects(host)
    assert len(subjects) == 1
    assert subjects[0].endswith(" tester: install.sh")
    assert _git(host, "remote") == ""
    assert {path.stat().st_uid for path in host.config.rglob("*")} == {os.getuid()}


def test_commits_need_no_git_identity_and_leave_the_global_config_alone(tmp_path):
    (tmp_path / "machine").mkdir()
    machine = Host(tmp_path / "machine")
    global_config = "[commit]\n\tgpgsign = true\n[core]\n\thooksPath = /nonexistent\n"
    (machine.home / ".gitconfig").write_text(global_config, encoding="utf-8")
    done = machine.install(make_package(tmp_path))
    assert done.returncode == 0, done.stderr
    machine.config = machine.root / "config"
    machine.all_running()
    _edit(machine)
    assert machine.dw("reload").returncode == 0
    assert _git(machine, "log", "--format=%an <%ae> %cn <%ce>").splitlines() == [f"{IDENTITY} {IDENTITY}"] * 2
    assert (machine.home / ".gitconfig").read_text(encoding="utf-8") == global_config
    assert not (machine.home / ".config" / "git").exists()


def test_an_install_without_git_stops_with_the_pacman_command(tmp_path):
    (tmp_path / "machine").mkdir()
    machine = Host(tmp_path / "machine", without=("git",))
    done = machine.install(make_package(tmp_path))
    assert done.returncode == 1
    assert "git is not installed." in done.stderr
    assert "Fix: sudo pacman -S git" in done.stderr
    assert not machine.root.exists()


def test_an_upgrade_keeps_the_history_and_a_new_sample_makes_no_commit(host, tmp_path):
    _edit(host)
    assert host.dw("reload").returncode == 0
    before = _git(host, "log", "--format=%H %s")
    (tmp_path / "newer").mkdir()
    newer = make_package(tmp_path / "newer", NEWER)
    sample = newer / "config" / "policy.yaml"
    sample.write_text(sample.read_text(encoding="utf-8") + "# new in this version\n", encoding="utf-8")
    done = host.install(newer, input="y\n")
    assert done.returncode == 0, done.stderr + done.stdout
    assert "# new in this version" in (host.config / "policy.yaml.sample").read_text(encoding="utf-8")
    assert _git(host, "log", "--format=%H %s") == before
    assert _status(host) == ""


def test_an_upgrade_of_an_install_with_no_history_starts_one(host):
    _edit(host)
    _remove_history(host)
    host.state["running"] = {}
    done = host.install(make_package(host.tmp.parent, NEWER))
    assert done.returncode == 0, done.stderr
    assert len(_subjects(host)) == 1
    assert "# edited by hand" in _git(host, "show", "HEAD:policy.yaml")


# Committed by dw


def test_reload_commits_a_hand_edit_with_the_time_the_user_and_the_command(host):
    _edit(host, old="timezone: America/Toronto", new="timezone: America/Toronto\n# quieter weekends")
    done = host.dw("reload")
    assert done.returncode == 0, done.stderr
    assert "Saved in the config history: policy.yaml." in done.stdout
    subject = _subjects(host)[0]
    match = re.fullmatch(r"(\d{4}-\d\d-\d\d \d\d:\d\d) ([+-]\d{4}) tester: dw reload", subject)
    assert match, subject
    offset = datetime.now(ZoneInfo("America/Toronto")).strftime("%z")
    assert match.group(2) == offset
    diff = _git(host, "show", "--format=", "HEAD")
    changed = [line for line in diff.splitlines() if line[:1] in "+-" and not line.startswith(("+++", "---"))]
    assert changed == ["+# quieter weekends"]
    assert _status(host) == ""


def test_reload_with_nothing_changed_adds_no_commit(host):
    done = host.dw("reload")
    assert done.returncode == 0, done.stderr
    assert "config history" not in done.stdout
    assert len(_subjects(host)) == 1


def test_a_broken_edit_is_not_committed_until_it_is_fixed(host):
    _edit(host)
    host.state["policy_errors"] = BROKEN
    done = host.dw("reload")
    assert done.returncode == 1
    assert _status(host) == " M policy.yaml\n"
    assert len(_subjects(host)) == 1
    host.state["policy_errors"] = []
    assert host.dw("reload").returncode == 0
    assert _subjects(host)[0].endswith("tester: dw reload")
    assert _status(host) == ""


@pytest.mark.parametrize("running", [True, False])
def test_check_never_commits(host, running):
    if not running:
        host.state["running"] = {}
    _edit(host)
    assert host.dw("check").returncode == 0
    assert _status(host) == " M policy.yaml\n"


def test_a_reload_on_a_stopped_daywarden_commits_nothing(host):
    host.state["running"] = {}
    _edit(host)
    assert host.dw("reload").returncode == 1
    assert _status(host) == " M policy.yaml\n"


@pytest.mark.parametrize("command", ["up", "restart", "reload"])
def test_an_edit_to_bypass_is_committed_by_up_restart_and_reload(host, command):
    if command == "up":
        host.state["running"] = {}
    _edit(host, "bypass.txt", new="homework.example\n")
    done = host.dw(command)
    assert done.returncode == 0, done.stderr
    assert "Saved in the config history: bypass.txt." in done.stdout
    assert _subjects(host)[0].endswith(f"tester: dw {command}")
    assert _status(host) == ""


def test_a_broken_policy_on_up_commits_nothing(host):
    host.state["running"] = {}
    host.state["policy_errors"] = BROKEN
    _edit(host)
    assert host.dw("up").returncode == 1
    assert _status(host) == " M policy.yaml\n"


def test_a_reload_that_only_reaches_the_decisions_service_still_commits(host):
    host.state["running"] = {"decisions": "healthy", "proxy": "healthy"}
    _edit(host)
    done = host.dw("reload")
    assert done.returncode == 1
    assert "The observations service is not running." in done.stderr
    assert _subjects(host)[0].endswith("tester: dw reload")


def test_restoring_an_old_version_and_reloading_adds_a_new_commit(host):
    original = (host.config / "policy.yaml").read_text(encoding="utf-8")
    _edit(host, new="# first change\n")
    assert host.dw("reload").returncode == 0
    _edit(host, new="# second change\n")
    assert host.dw("reload").returncode == 0
    first = _git(host, "rev-list", "--max-parents=0", "HEAD").strip()
    _git(host, "checkout", first, "--", "policy.yaml")
    assert host.dw("reload").returncode == 0
    assert (host.config / "policy.yaml").read_text(encoding="utf-8") == original
    assert _git(host, "show", "HEAD:policy.yaml") == original
    assert len(_subjects(host)) == 4
    assert "# second change" in _git(host, "show", "HEAD~1:policy.yaml")


def test_editor_leftovers_are_never_committed(host):
    leftovers = ["policy.yaml~", ".policy.yaml.swp", ".#policy.yaml", "#policy.yaml#"]
    for name in leftovers:
        (host.config / name).write_text("leftover\n", encoding="utf-8")
    _edit(host)
    assert host.dw("reload").returncode == 0
    assert _tracked(host) == [".gitignore", "bypass.txt", "policy.yaml"]
    assert _status(host) == ""


def _remove_history(host):
    for path in sorted((host.config / ".git").rglob("*"), reverse=True):
        path.unlink() if path.is_file() or path.is_symlink() else path.rmdir()
    (host.config / ".git").rmdir()


def test_up_starts_a_new_history_when_git_was_removed(host):
    _edit(host)
    _remove_history(host)
    host.state["running"] = {}
    done = host.dw("up")
    assert done.returncode == 0, done.stderr
    assert "Started the config history in ~/daywarden/config." in done.stdout
    assert len(_subjects(host)) == 1
    assert _subjects(host)[0].endswith("tester: dw up")
    assert "# edited by hand" in _git(host, "show", "HEAD:policy.yaml")
    assert _status(host) == ""


def test_a_new_file_such_as_an_included_policy_is_committed(host):
    (host.config / "tasks").mkdir()
    (host.config / "tasks" / "spelling.yaml").write_text("tasks: {}\n", encoding="utf-8")
    assert host.dw("reload").returncode == 0
    assert "tasks/spelling.yaml" in _tracked(host)


# A commit that fails


def test_a_commit_that_fails_warns_and_the_reload_still_applies(host):
    hook = host.config / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'No space left on device' >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    _edit(host)
    done = host.dw("reload")
    assert done.returncode == 0, done.stderr
    assert host.state["reloaded"] == ["decisions", "observations", "autoconfig"]
    assert "Warning: this change to ~/daywarden/config is not in the config history, because git could not commit it:" in done.stderr
    assert "  No space left on device" in done.stderr
    assert len(_subjects(host)) == 1


def test_a_lock_held_by_another_writer_is_waited_for(host):
    lock = host.config / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    threading.Timer(1.0, lock.unlink).start()
    _edit(host)
    done = host.dw("reload")
    assert done.returncode == 0, done.stderr
    assert "Warning" not in done.stderr
    assert _subjects(host)[0].endswith("tester: dw reload")


def test_a_lock_that_is_never_released_is_reported(host):
    (host.config / ".git" / "index.lock").write_text("", encoding="utf-8")
    _edit(host)
    done = host.dw("reload")
    assert done.returncode == 0, done.stderr
    assert "is not in the config history, because git could not add it:" in done.stderr
    assert "index.lock" in done.stderr
