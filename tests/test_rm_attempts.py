"""S010.1: rm-attempts runs remove-attempts in the decisions container from the host."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "rm-attempts"


def _run(tmp_path: Path, *args: str) -> list[str]:
    """Run rm-attempts through a symlink, from another directory, with a docker that records its arguments."""
    fake = tmp_path / "fake-bin"
    fake.mkdir()
    record = tmp_path / "docker-args"
    docker = fake / "docker"
    docker.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{record}"\n', encoding="utf-8")
    docker.chmod(0o755)
    linked = fake / "rm-attempts"
    linked.symlink_to(SCRIPT)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    env = {**os.environ, "PATH": f"{fake}:{os.environ['PATH']}"}
    subprocess.run(
        ["rm-attempts", *args],
        cwd=elsewhere,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=30,
        check=True,
    )
    return record.read_text(encoding="utf-8").splitlines()


def test_the_arguments_reach_remove_attempts_in_the_decisions_container(tmp_path):
    argv = _run(tmp_path, "--client", "younger", "--task", "two words", "--yes")
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
