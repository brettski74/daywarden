"""S046: dw-account add --password and update --password under the household's password rules, and --force."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_dw_account import dw_account, listing, signs_in  # noqa: E402
from test_mcp_server import PASSWORD  # noqa: E402

LONG = {"PASSWORD_MIN_LENGTH": "12"}
HISTORY = {"PASSWORD_HISTORY": "3"}
STRENGTH = {"PASSWORD_ATTACKER": "identity-thief", "PASSWORD_CRACK_TIME": "1y"}
STRONG = "marble kestrel saffron lantern"


@pytest.fixture
def database(tmp_path):
    """A database with Ada, the first admin, whose password was set before any rule was on."""
    path = tmp_path / "policy.sqlite3"
    added = dw_account(path, "add", "--role", "admin", "--password", "ada", stdin=PASSWORD + "\n")
    assert added.returncode == 0, added.stderr
    return path


def test_add_refuses_a_password_that_breaks_a_rule_without_a_terminal(database):
    refused = dw_account(database, "add", "--password", "nana", stdin="short\n", env=LONG)
    assert refused.returncode == 1
    assert refused.stderr == "Use at least 12 characters. This one has 5.\nNothing was added.\n"
    assert listing(database) == ["ada admin no email"]


def test_the_username_and_address_are_known_words(database):
    refused = dw_account(database, "add", "--email", "nana@example.net", "--password", "nana", stdin="nana2026!\n", env=STRENGTH)
    assert refused.returncode == 1
    assert refused.stderr.startswith("An identity thief could guess this in about ")
    assert "It needs to hold out for 1 year. Make it longer, such as by adding another word or two.\nNothing was added." in refused.stderr
    added = dw_account(database, "add", "--email", "nana@example.net", "--password", "nana", stdin=STRONG + "\n", env=STRENGTH)
    assert added.returncode == 0, added.stderr


def test_update_names_every_rule_broken_including_the_history(database):
    refused = dw_account(database, "update", "--password", "ada", stdin=PASSWORD + "\n", env={**LONG, **HISTORY})
    assert refused.returncode == 1
    assert refused.stderr == (
        "Use at least 12 characters. This one has 11.\n"
        "You have used this password recently. Choose one you have not used for your last 3 passwords.\n"
        "Nothing was changed.\n"
    )
    assert signs_in(database, "ada", PASSWORD)


def test_force_sets_a_password_that_breaks_the_rules_and_adds_it_to_the_history(database):
    forced = dw_account(database, "update", "--password", "--force", "ada", stdin="short\n", env={**LONG, **HISTORY})
    assert forced.returncode == 0, forced.stderr
    assert signs_in(database, "ada", "short")
    for used in ("short", PASSWORD):
        refused = dw_account(database, "update", "--password", "ada", stdin=used + "\n", env=HISTORY)
        assert refused.returncode == 1
        assert "You have used this password recently." in refused.stderr
    added = dw_account(database, "add", "--password", "--force", "nana", stdin="x\n", env=LONG)
    assert added.returncode == 0, added.stderr
    assert signs_in(database, "nana", "x")


@pytest.mark.parametrize("args", [("add", "--force", "--email", "nana@example.net", "nana"), ("update", "--force", "ada")])
def test_force_without_password_is_an_error(database, args):
    refused = dw_account(database, *args)
    assert refused.returncode == 2
    assert "--force sets a password, so it needs --password" in refused.stderr
    assert listing(database) == ["ada admin no email"]


def test_help_describes_force(tmp_path):
    path = tmp_path / "policy.sqlite3"
    for args in (("help",), ("add", "--help"), ("update", "--help")):
        shown = dw_account(path, *args)
        assert shown.returncode == 0
        assert "--force" in shown.stdout


def test_a_setting_that_is_not_valid_stops_the_command(database):
    refused = dw_account(database, "list", env={"PASSWORD_HISTORY": "21"})
    assert refused.returncode == 1
    assert "PASSWORD_HISTORY must be a whole number from 1 to 20, not 21" in refused.stderr


def test_at_a_terminal_a_refused_password_is_asked_for_again(database):
    pty = pytest.importorskip("pty")
    env = {**os.environ, "PYTHONPATH": str(ROOT), "POLICY_DB": str(database), **LONG}
    primary, secondary = pty.openpty()
    process = subprocess.Popen(
        [sys.executable, "-m", "policy.accounts", "update", "--password", "ada"],
        stdin=secondary, stdout=secondary, stderr=secondary, env=env, cwd=ROOT, start_new_session=True,
    )
    os.close(secondary)
    seen = b""

    def answer(prompt: bytes, text: str) -> None:
        nonlocal seen
        while prompt not in seen:
            seen += os.read(primary, 1024)
        seen = seen.split(prompt, 1)[1]
        os.write(primary, text.encode() + b"\n")

    answer(b"Password: ", "short")
    answer(b"Password again: ", "short")
    while b"Choose another password" not in seen:
        seen += os.read(primary, 1024)
    assert b"Use at least 12 characters. This one has 5." in seen
    answer(b"Password: ", "long-enough-now")
    answer(b"Password again: ", "long-enough-now")
    assert process.wait(timeout=30) == 0
    os.close(primary)
    assert signs_in(database, "ada", "long-enough-now")
