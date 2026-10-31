"""make up keeps a value the shell already exported."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _show(env: dict[str, str]) -> tuple[str, str]:
    completed = subprocess.run(
        ["make", "show-env"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=True,
    )
    names, ca_path = completed.stdout.splitlines()
    return names, ca_path


def test_an_exported_parent_names_wins_over_the_env_file():
    env = os.environ.copy()
    env["PARENT_NAMES"] = "localhost,127.0.0.1"
    names, _ca_path = _show(env)
    assert names == "localhost,127.0.0.1"


def test_an_unset_parent_names_comes_from_the_env_file():
    env = os.environ.copy()
    env.pop("PARENT_NAMES", None)
    names, ca_path = _show(env)
    assert names == "127.0.0.1"
    assert ca_path == "./data/ca"


def test_up_loads_the_env_file_without_replacing_the_shell():
    recipe = (ROOT / "Makefile").read_text(encoding="utf-8").split("up:\n", 1)[1]
    assert recipe.startswith("\t$(load_env);")
