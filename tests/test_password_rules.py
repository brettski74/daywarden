"""S046: the household's password rules on the Account page, the Reset password page, and at startup."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from asgi import call  # noqa: E402
from policy import accounts as accounts_module  # noqa: E402
from policy.accounts import Accounts  # noqa: E402
from policy.password_rules import PasswordRules, YEAR_SECONDS, known_words, password_rules, span  # noqa: E402
from policy.store import PolicyStore  # noqa: E402
from test_mcp_server import PASSWORD, service  # noqa: E402,F401 - service is the fixture
from test_password_reset import (  # noqa: E402,F401 - app and outbox are fixtures
    NOT_CHANGED,
    SAVED,
    app,
    change,
    outbox,
    requested,
    save,
    sign_in,
)

STRONG = "marble kestrel saffron lantern"


@pytest.fixture
def ruled(app, service, monkeypatch):
    """Restart the service with these rule settings, as dw restart does after .env changes."""

    def restart(**settings):
        for name in ("PASSWORD_MIN_LENGTH", "PASSWORD_HISTORY", "PASSWORD_ATTACKER", "PASSWORD_CRACK_TIME"):
            monkeypatch.delenv(name, raising=False)
        for name, value in settings.items():
            monkeypatch.setenv(name, value)
        from test_mcp_server import at
        from test_password_reset import NOW

        made = service.state.remake()
        at(made, NOW)
        return made

    return restart


class Work:
    """Counts the Argon2id hashes and checks the service does."""

    def __init__(self, hasher):
        self.hasher = hasher
        self.hashes = 0
        self.checks = 0

    def hash(self, password):
        self.hashes += 1
        return self.hasher.hash(password)

    def verify(self, digest, password):
        self.checks += 1
        return self.hasher.verify(digest, password)

    def take(self):
        found = (self.hashes, self.checks)
        self.hashes = self.checks = 0
        return found


@pytest.fixture
def work(monkeypatch):
    found = Work(accounts_module._HASHER)
    monkeypatch.setattr(accounts_module, "_HASHER", found)
    return found


def changed(app, cookie, current, password):
    status, body = change(app, cookie, current=current, password=password)
    return status == 200


def history_rows(app, username):
    with PolicyStore(app.state.database) as store:
        return store.connection.execute(
            "SELECT COUNT(*) FROM password_history JOIN parent_accounts ON parent_accounts.id = account_id WHERE username = ?",
            (username,),
        ).fetchone()[0]


# Settings


def test_each_rule_is_off_until_its_setting_is_set():
    rules = password_rules({"PASSWORD_MIN_LENGTH": "", "PASSWORD_HISTORY": " "})
    assert rules == PasswordRules()
    assert rules.public() == {"min_length": None, "history": None, "strength": None, "lines": []}
    assert rules.summary() == "password rules are off"


def test_the_settings_are_read_with_the_attacker_in_any_case():
    rules = password_rules(
        {"PASSWORD_MIN_LENGTH": "12", "PASSWORD_HISTORY": "3", "PASSWORD_ATTACKER": "Identity-Thief", "PASSWORD_CRACK_TIME": "1y"}
    )
    assert (rules.min_length, rules.history, rules.attacker.rate, rules.crack_seconds) == (12, 3, 10_000, YEAR_SECONDS)
    assert rules.lines() == [
        "At least 12 characters",
        "Different from your last 3 passwords",
        "Hard enough to guess that an identity thief would need at least 1 year",
    ]
    assert password_rules({"PASSWORD_HISTORY": "1"}).lines() == ["Different from your current password"]
    for text, seconds, words in (("72h", 72 * 3600, "72 hours"), ("365d", 365 * 86400, "365 days"), ("10y", 10 * YEAR_SECONDS, "10 years"), ("90s", 90, "90 seconds")):
        found = password_rules({"PASSWORD_ATTACKER": "government", "PASSWORD_CRACK_TIME": text})
        assert (found.crack_seconds, found.crack_time) == (seconds, words)


@pytest.mark.parametrize(
    ("settings", "named"),
    [
        ({"PASSWORD_MIN_LENGTH": "0"}, "PASSWORD_MIN_LENGTH must be a whole number from 1 to 200, not 0"),
        ({"PASSWORD_MIN_LENGTH": "201"}, "PASSWORD_MIN_LENGTH must be a whole number from 1 to 200, not 201"),
        ({"PASSWORD_HISTORY": "abc"}, "PASSWORD_HISTORY must be a whole number from 1 to 20, not abc"),
        ({"PASSWORD_HISTORY": "21"}, "PASSWORD_HISTORY must be a whole number from 1 to 20, not 21"),
        (
            {"PASSWORD_ATTACKER": "hacker", "PASSWORD_CRACK_TIME": "1y"},
            "PASSWORD_ATTACKER must be one of script-kiddie, identity-thief, crime-ring, or government, not hacker",
        ),
        ({"PASSWORD_ATTACKER": "government", "PASSWORD_CRACK_TIME": "10w"}, "PASSWORD_CRACK_TIME must be a whole number above 0"),
        ({"PASSWORD_ATTACKER": "government", "PASSWORD_CRACK_TIME": "0y"}, "PASSWORD_CRACK_TIME must be a whole number above 0"),
        ({"PASSWORD_ATTACKER": "government"}, "PASSWORD_CRACK_TIME is not set, but PASSWORD_ATTACKER is."),
        ({"PASSWORD_CRACK_TIME": "1y"}, "PASSWORD_ATTACKER is not set, but PASSWORD_CRACK_TIME is."),
    ],
)
def test_a_setting_that_is_not_valid_stops_the_service_naming_it(ruled, settings, named):
    with pytest.raises(SystemExit, match=named.replace(".", r"\.")):
        ruled(**settings)


def test_the_service_log_names_the_rules_at_startup(ruled, capsys):
    ruled(PASSWORD_MIN_LENGTH="12", PASSWORD_ATTACKER="crime-ring", PASSWORD_CRACK_TIME="10y")
    assert (
        "password rules: at least 12 characters; hard enough to guess that an organised crime ring would need at least 10 years"
        in capsys.readouterr().out
    )


def test_the_pages_load_the_settings_and_nothing_about_an_account(ruled):
    made = ruled(PASSWORD_MIN_LENGTH="12", PASSWORD_HISTORY="3", PASSWORD_ATTACKER="identity-thief", PASSWORD_CRACK_TIME="1y")
    public = {
        "min_length": 12,
        "history": 3,
        "strength": {"attacker": "identity-thief", "label": "an identity thief", "rate": 10000, "seconds": YEAR_SECONDS, "time": "1 year"},
        "lines": [
            "At least 12 characters",
            "Different from your last 3 passwords",
            "Hard enough to guess that an identity thief would need at least 1 year",
        ],
    }
    assert json.loads(call(made, "GET", "/parent/api/password-reset")[1])["rules"] == public
    assert json.loads(call(made, "GET", "/parent/api/account", cookie=sign_in(made))[1])["rules"] == public


# The rules on the Account page


def test_the_length_rule(ruled, capsys):
    made = ruled(PASSWORD_MIN_LENGTH="12")
    cookie = sign_in(made)
    assert change(made, cookie, password="a" * 11) == (400, NOT_CHANGED)
    assert "password for ada refused on the Account page: shorter than 12 characters" in capsys.readouterr().out
    assert sign_in(made, "ada", PASSWORD) is not None
    assert change(made, cookie, password="b" * 12)[0] == 200
    assert sign_in(made, "ada", "b" * 12) is not None


def test_the_history_rule_refuses_the_newest_passwords_and_passes_any_other(ruled):
    made = ruled(PASSWORD_HISTORY="3")
    cookie = sign_in(made)
    assert changed(made, cookie, PASSWORD, "Tulip-Garden-8")
    assert changed(made, cookie, "Tulip-Garden-8", "Tulip-Garden-9")
    # Now the current one and the two before it.
    for used in ("Tulip-Garden-9", "Tulip-Garden-8", PASSWORD):
        assert change(made, cookie, current="Tulip-Garden-9", password=used) == (400, NOT_CHANGED)
    # Any difference counts.
    assert changed(made, cookie, "Tulip-Garden-9", "Tulip-Garden-7")
    # The first password is now the fourth newest.
    assert changed(made, cookie, "Tulip-Garden-7", PASSWORD)
    assert sign_in(made, "ada", PASSWORD) is not None


def test_only_the_newest_are_kept_and_lowering_the_setting_drops_the_older_ones_for_good(ruled):
    made = ruled(PASSWORD_HISTORY="3")
    cookie = sign_in(made)
    for current, new in ((PASSWORD, "pass-two"), ("pass-two", "pass-three"), ("pass-three", "pass-four")):
        assert changed(made, cookie, current, new)
    assert history_rows(made, "ada") == 3
    made = ruled()
    assert history_rows(made, "ada") == 1
    made = ruled(PASSWORD_HISTORY="3")
    cookie = sign_in(made, "ada", "pass-four")
    assert changed(made, cookie, "pass-four", "pass-three")


def test_with_the_rule_off_only_the_current_password_is_kept(ruled):
    made = ruled()
    cookie = sign_in(made)
    assert changed(made, cookie, PASSWORD, "pass-two")
    assert changed(made, cookie, "pass-two", PASSWORD)
    assert history_rows(made, "ada") == 1


def test_removing_an_account_removes_its_history(ruled):
    made = ruled(PASSWORD_HISTORY="5")
    with PolicyStore(made.state.database) as store:
        accounts = Accounts(store.connection, rules=password_rules({"PASSWORD_HISTORY": "5"}))
        accounts.update("nana", password="pass-two")
        assert history_rows(made, "nana") == 2
        accounts.remove("nana")
        assert store.connection.execute("SELECT COUNT(*) FROM password_history WHERE account_id NOT IN (SELECT id FROM parent_accounts)").fetchone()[0] == 0


def test_every_change_does_the_same_hashing_work(ruled, work):
    made = ruled(PASSWORD_HISTORY="5")
    ada = sign_in(made)
    for current, new in ((PASSWORD, "pass-two"), ("pass-two", "pass-three"), ("pass-three", "pass-four"), ("pass-four", "pass-five")):
        assert changed(made, ada, current, new)
    bee = sign_in(made, "bee")
    work.take()
    # One check of the current password, one hash, and five history checks, whatever the outcome.
    assert change(made, ada, current="pass-five", password="pass-two") == (400, NOT_CHANGED)
    assert work.take() == (1, 6)
    assert change(made, bee, current="wrong", password="pass-six") == (400, NOT_CHANGED)
    assert work.take() == (1, 6)
    assert changed(made, bee, PASSWORD, "pass-six")
    assert work.take() == (1, 6)
    assert changed(made, ada, "pass-five", "pass-six")
    assert work.take() == (1, 6)


def test_with_the_history_rule_off_a_change_checks_no_history(ruled, work):
    made = ruled()
    cookie = sign_in(made)
    work.take()
    assert changed(made, cookie, PASSWORD, "pass-two")
    assert work.take() == (1, 1)


def test_the_strength_rule(ruled, capsys):
    made = ruled(PASSWORD_ATTACKER="identity-thief", PASSWORD_CRACK_TIME="1y")
    cookie = sign_in(made)
    assert change(made, cookie, password="correct horse") == (400, NOT_CHANGED)
    log = capsys.readouterr().out
    assert "password for ada refused on the Account page: too easy to guess" in log
    assert "correct horse" not in log
    assert changed(made, cookie, PASSWORD, STRONG)


def test_the_username_address_and_current_password_are_known_words(ruled, capsys):
    made = ruled(PASSWORD_HISTORY="3", PASSWORD_ATTACKER="identity-thief", PASSWORD_CRACK_TIME="1y")
    cookie = sign_in(made)
    for easy in ("ada", "ada2026!"):
        assert change(made, cookie, password=easy) == (400, NOT_CHANGED)
    assert changed(made, cookie, PASSWORD, "Summer2025!Picnic")
    capsys.readouterr()
    assert change(made, cookie, current="Summer2025!Picnic", password="Summer2026!Picnic") == (400, NOT_CHANGED)
    # Refused as too easy to guess, not as used before.
    assert "password for ada refused on the Account page: too easy to guess\n" in capsys.readouterr().out
    # With any other current password, the same new one passes.
    assert PasswordRules(attacker=made_attacker(), crack_seconds=YEAR_SECONDS, crack_time="1 year").problems(
        "Summer2026!Picnic", known_words("ada", "ada@example.net")
    ) == []


def made_attacker():
    from policy.password_rules import ATTACKERS

    return ATTACKERS["identity-thief"]


def test_a_wrong_current_password_is_still_checked_against_every_rule_and_logged_with_each_reason(ruled, capsys):
    made = ruled(PASSWORD_MIN_LENGTH="12", PASSWORD_HISTORY="3")
    cookie = sign_in(made)
    assert change(made, cookie, current="wrong", password=PASSWORD) == (400, NOT_CHANGED)
    log = capsys.readouterr().out
    assert (
        "password for ada refused on the Account page: current password wrong, shorter than 12 characters, used within the last 3 passwords"
        in log
    )
    assert PASSWORD not in log


def test_existing_passwords_that_break_a_rule_still_sign_in(ruled):
    made = ruled(PASSWORD_MIN_LENGTH="40", PASSWORD_ATTACKER="government", PASSWORD_CRACK_TIME="100y")
    assert sign_in(made, "ada", PASSWORD) is not None


# The rules on the Reset password page


def test_a_refused_reset_leaves_the_link_working(ruled, outbox, capsys):
    made = ruled(PASSWORD_MIN_LENGTH="12", PASSWORD_HISTORY="2")
    token = requested(made, outbox)
    capsys.readouterr()
    assert save(made, token, "short")[:2] == (200, SAVED)
    assert save(made, token, PASSWORD)[:2] == (200, SAVED)
    log = capsys.readouterr().out
    assert "password for ada refused from a reset link: shorter than 12 characters" in log
    assert "password for ada refused from a reset link: shorter than 12 characters, used within the last 2 passwords" in log
    assert sign_in(made, "ada", PASSWORD) is not None
    assert save(made, token, "long-enough-now")[:2] == (200, SAVED)
    assert sign_in(made, "ada", "long-enough-now") is not None
    # Used now.
    assert save(made, token, "another-long-one")[:2] == (200, SAVED)
    assert sign_in(made, "ada", "another-long-one") is None


def test_a_link_that_is_not_valid_gets_the_same_answer_and_work_and_no_log_line(ruled, outbox, work, capsys):
    made = ruled(PASSWORD_HISTORY="4", PASSWORD_ATTACKER="identity-thief", PASSWORD_CRACK_TIME="1y")
    token = requested(made, outbox)
    capsys.readouterr()
    work.take()
    assert save(made, "0" * 64, "short")[:2] == (200, SAVED)
    assert work.take() == (1, 4)
    assert "refused" not in capsys.readouterr().out
    assert save(made, token, "short")[:2] == (200, SAVED)
    assert work.take() == (1, 4)
    assert "password for ada refused from a reset link: too easy to guess" in capsys.readouterr().out
    assert save(made, token, STRONG)[:2] == (200, SAVED)
    assert work.take() == (1, 4)
    assert sign_in(made, "ada", STRONG) is not None


def test_a_reset_uses_the_username_and_address_as_known_words(ruled, outbox):
    made = ruled(PASSWORD_ATTACKER="identity-thief", PASSWORD_CRACK_TIME="1y")
    token = requested(made, outbox)
    save(made, token, "ada2026!")
    assert sign_in(made, "ada", "ada2026!") is None
    assert sign_in(made, "ada", PASSWORD) is not None


# What the parent is told


def test_the_advice_names_each_rule_broken_and_how_to_fix_it():
    rules = password_rules(
        {"PASSWORD_MIN_LENGTH": "12", "PASSWORD_HISTORY": "3", "PASSWORD_ATTACKER": "identity-thief", "PASSWORD_CRACK_TIME": "1y"}
    )
    length, strength = rules.problems("correct h")
    assert length.advice == "Use at least 12 characters. This one has 9."
    assert strength.advice.startswith("An identity thief could guess this in about ")
    assert strength.advice.endswith(" It needs to hold out for 1 year. Make it longer, such as by adding another word or two.")
    assert rules.reused().advice == "You have used this password recently. Choose one you have not used for your last 3 passwords."
    assert rules.problems(STRONG) == []


def test_a_length_is_counted_in_characters():
    assert PasswordRules(min_length=3).problems("日本😀") == []


@pytest.mark.parametrize(
    ("seconds", "said"),
    [
        (0.4, "less than a second"),
        (1, "about 1 second"),
        (59.4, "about 59 seconds"),
        (90, "about 2 minutes"),
        (3 * 86400 + 3600, "about 3 days"),
        (YEAR_SECONDS * 1.4, "about 1 year"),
        (YEAR_SECONDS * 12_345, "about 12,345 years"),
        (YEAR_SECONDS * 2e6, "more than a million years"),
    ],
)
def test_a_time_is_said_roughly(seconds, said):
    assert span(seconds) == said


def test_known_words_take_in_their_pieces():
    assert known_words("Ada", "ada.lovelace@example.net", "Summer2025!Picnic") == [
        "ada",
        "ada.lovelace@example.net",
        "lovelace",
        "example",
        "net",
        "summer2025!picnic",
        "summer",
        "2025",
        "picnic",
    ]
    assert known_words("jo", None, None) == ["jo"]


# The Password help page


def test_the_help_page_opens_with_no_session_over_https_only_and_is_no_place_to_return_to(app):
    status, body, _headers = call(app, "GET", "/parent/password-help")
    assert (status, "<title>Daywarden</title>" in body) == (200, True)
    status, body, _headers = call(app, "GET", "/parent/password-help", scheme="http")
    assert status != 200 and "Open this page over HTTPS." in body
    status, body, _headers = call(
        app, "POST", "/parent/api/login", json_body={"username": "ada", "password": PASSWORD, "next": "/parent/password-help"}
    )
    assert (status, json.loads(body)["next"]) == (200, "/parent/")
