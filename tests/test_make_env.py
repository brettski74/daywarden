"""make up keeps a value the shell already exported."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _show(env: dict[str, str]) -> tuple[str, str, str]:
    completed = subprocess.run(
        ["make", "--no-print-directory", "show-env"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=True,
    )
    names, ca_path, data_dir = completed.stdout.splitlines()
    return names, ca_path, data_dir


def test_an_exported_parent_names_wins_over_the_env_file():
    env = os.environ.copy()
    env["PARENT_NAMES"] = "localhost,127.0.0.1"
    names, _ca_path, _data_dir = _show(env)
    assert names == "localhost,127.0.0.1"


def test_the_data_directory_defaults_under_home_and_an_exported_one_wins():
    env = os.environ.copy()
    env.pop("DAYWARDEN_DATA_DIR", None)
    env["HOME"] = "/home/example"
    assert _show(env)[2] == "/home/example/daywarden"
    env["DAYWARDEN_DATA_DIR"] = "/srv/daywarden"
    assert _show(env)[2] == "/srv/daywarden"
