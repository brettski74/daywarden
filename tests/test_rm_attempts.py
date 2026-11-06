"""S010.1: rm-attempts runs remove-attempts in the decisions container from the host."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "rm-attempts"


def _run(tmp_path: Path, *args: str, running: bool = True) -> tuple[subprocess.CompletedProcess, list[str]]:
    """Run rm-attempts through a symlink, from another directory, with a docker that records its arguments.

    The fake answers ``docker ps`` with a decisions container when ``running``.
    """
    fake = tmp_path / "fake-bin"
    fake.mkdir()
    record = tmp_path / "docker-args"
    docker = fake / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        f'if [ "$1" = ps ]; then {"echo id-decisions" if running else "true"}; exit; fi\n'
        f'printf "%s\\n" "$@" > "{record}"\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)
    linked = fake / "rm-attempts"
    linked.symlink_to(SCRIPT)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    env = {**os.environ, "PATH": f"{fake}:{os.environ['PATH']}"}
    done = subprocess.run(
        ["rm-attempts", *args],
        cwd=elsewhere,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return done, record.read_text(encoding="utf-8").splitlines() if record.exists() else []


def test_the_arguments_reach_remove_attempts_in_the_decisions_container(tmp_path):
    done, argv = _run(tmp_path, "--client", "younger", "--task", "two words", "--yes")
    assert done.returncode == 0, done.stderr
    assert argv == [
        "compose",
        "--project-directory",
        str(ROOT),
        "exec",
        "-T",
        "decisions",
        "python",
        "-m",
        "policy.maintenance",
        "remove-attempts",
        "--client",
        "younger",
        "--task",
        "two words",
        "--yes",
    ]


def test_a_stopped_stack_is_reported_instead(tmp_path):
    done, argv = _run(tmp_path, "--all", running=False)
    assert done.returncode == 1
    assert done.stderr == "daywarden is not running. Start it with dw up.\n"
    assert argv == []
