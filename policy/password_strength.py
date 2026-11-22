"""zxcvbn's estimate of how many guesses a password needs, as the portal's zxcvbn 4.4.2 makes it (S046).

The service uses the ``zxcvbn`` package from PyPI, a port of Dropbox's
zxcvbn 4.4.2, and the portal uses the ``zxcvbn`` 4.4.2 npm package. Both have
the same dictionaries and matchers. Left as they are, they disagree in four
ways, and this module makes the port agree with the JavaScript:

- The port fixes the reference year for dates and recent years at 2017. The
  JavaScript uses the current year.
- JavaScript strings are UTF-16, so the JavaScript sees a character outside
  the Basic Multilingual Plane, such as an emoji, as two. The port sees one.
  The password and the known words are given to the port as UTF-16 code
  units, each a lone surrogate.
- The search for the cheapest sequence of matches visits shorter sequences
  first in the JavaScript, whose objects keep integer keys in order. The port
  visits them in the order they were stored, so it can keep a sequence the
  JavaScript drops. ``_sequence`` is the port's search with the keys in order.
- Python's ``\\d`` and ``str.isupper`` take in every script's digits and
  capitals, such as ``٣`` and ``Ω``. The JavaScript takes only 0 to 9 and A
  to Z.

Both read only the first ``READ`` characters. zxcvbn's l33t matching grows
with the square of the length, and a random 200-character password takes
seconds in either library. A password whose first 100 characters are easy to
guess is a repeat or the like, which is easy to guess whole too.

``tests/test_password_strength.py`` runs both on a corpus when Node is installed.
"""

from __future__ import annotations

import re
import threading
from datetime import date
from decimal import Decimal
from math import factorial, log

from zxcvbn import matching, scoring

# The portal's passwordRules.ts reads the same number of characters.
READ = 100
_LOCK = threading.Lock()
# matching.omnimatch reads the known words from this shared table.
_KNOWN = "user_inputs"


def estimate_guesses(password: str, known: list[str] | tuple[str, ...] = ()) -> float:
    """Return zxcvbn's estimate of the guesses password needs, with known as words an attacker would try first."""
    text = _utf16(password[:READ])
    words = [_utf16(word.lower()) for word in known if isinstance(word, str) and word != ""]
    with _LOCK:
        scoring.REFERENCE_YEAR = date.today().year
        dictionaries = matching.RANKED_DICTIONARIES
        dictionaries[_KNOWN] = matching.build_ranked_dict(words)
        try:
            found = matching.omnimatch(text, dictionaries)
            return float(_sequence(text, found)["guesses"])
        finally:
            dictionaries[_KNOWN] = {}


def _utf16(text: str) -> str:
    """Return text with each character outside the Basic Multilingual Plane as its two UTF-16 surrogates."""
    if all(ord(char) <= 0xFFFF for char in text):
        return text
    units = []
    for char in text:
        point = ord(char)
        if point <= 0xFFFF:
            units.append(char)
            continue
        point -= 0x10000
        units.append(chr(0xD800 + (point >> 10)))
        units.append(chr(0xDC00 + (point & 0x3FF)))
    return "".join(units)


def _sequence(password, matches, _exclude_additive=False):
    """scoring.most_guessable_match_sequence, visiting each prefix's sequences shortest first as the JavaScript does."""
    n = len(password)
    matches_by_j = [[] for _ in range(n)]
    for m in matches:
        matches_by_j[m["j"]].append(m)
    for lst in matches_by_j:
        lst.sort(key=lambda m1: m1["i"])
    optimal = {"m": [{} for _ in range(n)], "pi": [{} for _ in range(n)], "g": [{} for _ in range(n)]}

    def update(m, l):
        k = m["j"]
        pi = scoring.estimate_guesses(m, password)
        if l > 1:
            pi = pi * Decimal(optimal["pi"][m["i"] - 1][l - 1])
        g = factorial(l) * pi
        if not _exclude_additive:
            g += scoring.MIN_GUESSES_BEFORE_GROWING_SEQUENCE ** (l - 1)
        for competing_l in sorted(optimal["g"][k]):
            if competing_l > l:
                continue
            if optimal["g"][k][competing_l] <= g:
                return
        optimal["g"][k][l] = g
        optimal["m"][k][l] = m
        optimal["pi"][k][l] = pi

    def bruteforce_update(k):
        update(make_bruteforce_match(0, k), 1)
        for i in range(1, k + 1):
            m = make_bruteforce_match(i, k)
            for l in sorted(optimal["m"][i - 1]):
                if optimal["m"][i - 1][l].get("pattern", False) == "bruteforce":
                    continue
                update(m, l + 1)

    def make_bruteforce_match(i, j):
        return {"pattern": "bruteforce", "token": password[i : j + 1], "i": i, "j": j}

    def unwind(n):
        optimal_match_sequence = []
        k = n - 1
        l = None
        g = float("inf")
        for candidate_l in sorted(optimal["g"][k]):
            if optimal["g"][k][candidate_l] < g:
                l = candidate_l
                g = optimal["g"][k][candidate_l]
        while k >= 0:
            m = optimal["m"][k][l]
            optimal_match_sequence.insert(0, m)
            k = m["i"] - 1
            l -= 1
        return optimal_match_sequence

    for k in range(n):
        for m in matches_by_j[k]:
            if m["i"] > 0:
                for l in sorted(optimal["m"][m["i"] - 1]):
                    update(m, l + 1)
            else:
                update(m, 1)
        bruteforce_update(k)

    optimal_match_sequence = unwind(n)
    optimal_l = len(optimal_match_sequence)
    guesses = 1 if n == 0 else optimal["g"][n - 1][optimal_l]
    return {
        "password": password,
        "guesses": guesses,
        "guesses_log10": log(guesses, 10),
        "sequence": optimal_match_sequence,
    }


def _uppercase_variations(match):
    """scoring.uppercase_variations, counting only A to Z and a to z as the JavaScript does."""
    word = match["token"]
    if scoring.ALL_LOWER.match(word) or word.lower() == word:
        return 1
    for regex in (scoring.START_UPPER, scoring.END_UPPER, scoring.ALL_UPPER):
        if regex.match(word):
            return 2
    upper = sum(1 for char in word if "A" <= char <= "Z")
    lower = sum(1 for char in word if "a" <= char <= "z")
    return sum(scoring.nCk(upper + lower, i) for i in range(1, min(upper, lower) + 1))


class _JavaScriptDigits:
    """The re module, but \\d is 0 to 9 only, as in JavaScript. Python's also matches digits such as ٣."""

    def __getattr__(self, name):
        return getattr(re, name)

    @staticmethod
    def compile(pattern, flags=0):
        return re.compile(pattern.replace(r"\d", "[0-9]"), flags)


# A repeated part is scored by the same search.
matching.most_guessable_match_sequence = _sequence
scoring.uppercase_variations = _uppercase_variations
matching.re = scoring.re = _JavaScriptDigits()
matching.REGEXEN["recent_year"] = _JavaScriptDigits.compile(matching.REGEXEN["recent_year"].pattern)
