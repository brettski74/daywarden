"""S046: the service's zxcvbn estimate agrees with the portal's zxcvbn 4.4.2, run in Node."""

import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from conftest import needs_node  # noqa: E402
from policy.password_rules import known_words  # noqa: E402
from policy.password_strength import READ, estimate_guesses  # noqa: E402

PORTAL_ZXCVBN = ROOT / "policy" / "portal" / "node_modules" / "zxcvbn"
SCRIPT = """
const zxcvbn = require(process.argv[1]);
const cases = JSON.parse(require("fs").readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(cases.map(([password, known]) => zxcvbn(password, known).guesses)));
"""


def corpus() -> list[tuple[str, list[str]]]:
    """Passwords of every kind zxcvbn matches, with and without known words, including the spots where the two ports differed."""
    from zxcvbn.frequency_lists import FREQUENCY_LISTS

    rng = random.Random(46)
    words = FREQUENCY_LISTS["english_wikipedia"][:2000] + FREQUENCY_LISTS["passwords"][:1000] + FREQUENCY_LISTS["surnames"][:300]
    odd = ["😀", "👍🏽", "日本", "İ", "ß", "Ω", "٣٤", "é", " ", "𝔘𝔫𝔦"]
    known = [[], known_words("ada", "ada@example.net"), known_words("nana", "nana@example.net", "Summer2025!Picnic")]
    found = [
        ("correct horse", []),
        ("Summer2026!Picnic", known[2]),
        ("ada2026!", known[1]),
        ("orchid_quixotic_summer_Saffron6151", known[2]),
        ("emoji😀😀pass", known[1]),
        ("t u t t u1905٣٤", known[1]),
        ("12/25/1999", []),
        ("zxcvbnm,./", []),
        ("aaaaaaaaaaaa", []),
    ]
    for _ in range(600):
        parts = []
        for _ in range(rng.randint(1, 5)):
            word = rng.choice(words)
            twist = rng.random()
            if twist < 0.2:
                word = word.capitalize()
            elif twist < 0.3:
                word = word.replace("a", "@").replace("o", "0").replace("e", "3")
            elif twist < 0.35:
                word = word[::-1]
            elif twist < 0.4:
                word = word * 2
            parts.append(word)
        password = rng.choice(["", "-", " ", "_", ".", "!", "1"]).join(parts)
        tail = rng.random()
        if tail < 0.2:
            password += str(rng.randint(1900, 2040))
        elif tail < 0.3:
            password += "%02d/%02d/%d" % (rng.randint(1, 12), rng.randint(1, 28), rng.randint(1950, 2030))
        elif tail < 0.35:
            password += rng.choice(["qwerty", "asdfgh", "1234", "abcd", "9876"])
        if rng.random() < 0.1:
            password += rng.choice(odd)
        found.append((password[:200], rng.choice(known)))
    return found


@needs_node
def test_the_service_and_the_portal_estimate_the_same_guesses():
    if not PORTAL_ZXCVBN.is_dir():
        pytest.skip("the portal's npm packages are not installed")
    cases = corpus()
    # The portal reads only the first READ characters too.
    sent = [("".join(list(password)[:READ]), known) for password, known in cases]
    done = subprocess.run(
        ["node", "-e", SCRIPT, str(PORTAL_ZXCVBN)], input=json.dumps(sent), capture_output=True, text=True, check=True, timeout=120
    )
    portal = json.loads(done.stdout)
    for (password, known), theirs in zip(cases, portal):
        ours = estimate_guesses(password, known)
        assert ours == pytest.approx(theirs, rel=1e-12), (password, known)


def test_only_the_first_100_characters_are_read():
    assert estimate_guesses("Tulip-Garden-7" * 7 + "x" * 100) == estimate_guesses(("Tulip-Garden-7" * 7 + "x" * 100)[:READ])
