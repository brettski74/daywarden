"""The household's password rules, from .env (S046).

Each rule is off while its setting is not set. ``PASSWORD_MIN_LENGTH`` is the
fewest characters, ``PASSWORD_HISTORY`` how many recent passwords a new one
must differ from, counting the current one, and ``PASSWORD_ATTACKER`` with
``PASSWORD_CRACK_TIME`` the strength rule: zxcvbn's estimate of the guesses,
at the attacker's rate against the Argon2id hashes in a stolen database, must
last at least that long. The settings are read at startup, and one that is
set but not valid stops the service with a message that names it.

The rules apply only when a password is set. The history needs the stored
hashes, so only the service and ``dw-account`` check it. The portal checks
length and strength as the parent types, with the same wording, in
``policy/portal/src/passwordRules.ts``, from the settings ``public`` gives.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Mapping, NamedTuple

from policy.password_strength import estimate_guesses

LONGEST_HISTORY = 20
LONGEST_MINIMUM = 200
YEAR_SECONDS = 365.24219 * 86400
_UNITS = {"s": (1, "second"), "m": (60, "minute"), "h": (3600, "hour"), "d": (86400, "day"), "y": (YEAR_SECONDS, "year")}
_CRACK_TIME = re.compile(r"0*([1-9][0-9]*)([smhdy])\Z", re.IGNORECASE)


class Attacker(NamedTuple):
    name: str
    # As it reads inside a sentence: "an identity thief could guess this in about 3 days".
    label: str
    rate: int


ATTACKERS = {
    attacker.name: attacker
    for attacker in (
        Attacker("script-kiddie", "a motivated script kiddie", 100),
        Attacker("identity-thief", "an identity thief", 10_000),
        Attacker("crime-ring", "an organised crime ring", 1_000_000),
        Attacker("government", "a government intelligence agency", 1_000_000_000),
    )
}


class Broken(NamedTuple):
    """One rule a new password breaks."""

    rule: str
    # For the service log, which never holds the password or the estimate.
    reason: str
    # For the parent, as the Account page and dw-account say it.
    advice: str


@dataclass(frozen=True)
class PasswordRules:
    min_length: int | None = None
    history: int | None = None
    attacker: Attacker | None = None
    crack_seconds: float | None = None
    # The setting in words, such as "1 year" for 1y.
    crack_time: str | None = None

    @property
    def strength(self) -> bool:
        return self.attacker is not None and self.crack_seconds is not None

    @property
    def depth(self) -> int:
        """How many stored hashes each new password is checked against: 0 while the history rule is off."""
        return self.history or 0

    @property
    def kept(self) -> int:
        """How many of an account's passwords are kept, the current one included."""
        return self.history or 1

    def problems(self, password: str, known: list[str] | tuple[str, ...] = ()) -> list[Broken]:
        """Return the length and strength rules password breaks, with known as the account's known words."""
        found = []
        if self.min_length is not None and len(password) < self.min_length:
            found.append(
                Broken(
                    "length",
                    f"shorter than {self.min_length} characters",
                    f"Use at least {self.min_length} characters. This one has {len(password)}.",
                )
            )
        if self.strength:
            guesses = estimate_guesses(password, known)
            seconds = guesses / self.attacker.rate
            if seconds < self.crack_seconds:
                found.append(
                    Broken(
                        "strength",
                        "too easy to guess",
                        f"{_capital(self.attacker.label)} could guess this in {span(seconds)}. "
                        f"It needs to hold out for {self.crack_time}. Make it longer, such as by adding another word or two.",
                    )
                )
        return found

    def reused(self) -> Broken:
        """The history rule, broken."""
        if self.history == 1:
            return Broken(
                "history",
                "the same as the current password",
                "You have used this password recently. Choose one that is not your current password.",
            )
        return Broken(
            "history",
            f"used within the last {self.history} passwords",
            f"You have used this password recently. Choose one you have not used for your last {self.history} passwords.",
        )

    def lines(self) -> list[str]:
        """Each rule that is on, as the Password help page lists it."""
        found = []
        if self.min_length is not None:
            found.append(f"At least {self.min_length} characters")
        if self.history == 1:
            found.append("Different from your current password")
        elif self.history is not None:
            found.append(f"Different from your last {self.history} passwords")
        if self.strength:
            found.append(f"Hard enough to guess that {self.attacker.label} would need at least {self.crack_time}")
        return found

    def public(self) -> dict:
        """The settings the portal checks with, and the help page's lines. Nothing about any account."""
        strength = None
        if self.strength:
            strength = {
                "attacker": self.attacker.name,
                "label": self.attacker.label,
                "rate": self.attacker.rate,
                "seconds": self.crack_seconds,
                "time": self.crack_time,
            }
        return {"min_length": self.min_length, "history": self.history, "strength": strength, "lines": self.lines()}

    def summary(self) -> str:
        """One line for the service log at startup."""
        if not self.lines():
            return "password rules are off"
        return "password rules: " + "; ".join(line[0].lower() + line[1:] for line in self.lines())


_PIECE = re.compile(r"[a-z]+|[0-9]+")


def known_words(username: str | None, email: str | None, current: object = None) -> list[str]:
    """The words a new password must not lean on: the username, the address, and the current password.

    zxcvbn matches a known word only as a whole, so each is followed by its
    runs of letters and of digits, such as summer, 2025, and picnic for
    Summer2025!Picnic, all in lower case. Pieces shorter than 3 are left out. The portal's
    knownWords makes the same list in the same order, which zxcvbn ranks by.
    """
    found: list[str] = []
    for word in (username, email, current if isinstance(current, str) else None):
        if not word:
            continue
        lower = word.lower()
        pieces = [piece for piece in _PIECE.findall(lower) if len(piece) >= 3]
        for piece in [lower, *pieces]:
            if piece not in found:
                found.append(piece)
    return found


def span(seconds: float) -> str:
    """Say a length of time roughly, as the portal's passwordRules.ts does: "about 3 days"."""
    if seconds < 1:
        return "less than a second"
    for limit, size, unit in (
        (60, 1, "second"),
        (3600, 60, "minute"),
        (86400, 3600, "hour"),
        (YEAR_SECONDS, 86400, "day"),
        (1e6 * YEAR_SECONDS, YEAR_SECONDS, "year"),
    ):
        if seconds < limit:
            count = math.floor(seconds / size + 0.5)
            return f"about {count:,} {unit}{'' if count == 1 else 's'}"
    return "more than a million years"


def password_rules(environ: Mapping[str, str]) -> PasswordRules:
    """Return the rules in environ. A setting that is set but not valid raises SystemExit naming it."""
    minimum = _whole(environ, "PASSWORD_MIN_LENGTH", LONGEST_MINIMUM)
    history = _whole(environ, "PASSWORD_HISTORY", LONGEST_HISTORY)
    named = _value(environ, "PASSWORD_ATTACKER")
    crack = _value(environ, "PASSWORD_CRACK_TIME")
    attacker = None
    if named is not None:
        attacker = ATTACKERS.get(named.lower())
        if attacker is None:
            names = list(ATTACKERS)
            raise SystemExit(
                f"PASSWORD_ATTACKER must be one of {', '.join(names[:-1])}, or {names[-1]}, not {named}"
            )
    seconds = words = None
    if crack is not None:
        match = _CRACK_TIME.match(crack)
        if match is None:
            raise SystemExit(
                f"PASSWORD_CRACK_TIME must be a whole number above 0 followed by s, m, h, d, or y, such as 72h, 365d, or 10y, not {crack}"
            )
        count = int(match.group(1))
        size, unit = _UNITS[match.group(2).lower()]
        seconds = count * size
        words = f"{count:,} {unit}{'' if count == 1 else 's'}"
    if (named is None) != (crack is None):
        missing, given = ("PASSWORD_CRACK_TIME", "PASSWORD_ATTACKER") if crack is None else ("PASSWORD_ATTACKER", "PASSWORD_CRACK_TIME")
        raise SystemExit(f"{missing} is not set, but {given} is. Set both to turn on the strength rule, or neither.")
    return PasswordRules(minimum, history, attacker, seconds, words)


def _value(environ: Mapping[str, str], name: str) -> str | None:
    """A setting, or None when it is missing or empty. Compose passes an unset setting as empty."""
    value = environ.get(name)
    if value is None or value.strip() == "":
        return None
    return value.strip()


def _whole(environ: Mapping[str, str], name: str, most: int) -> int | None:
    value = _value(environ, name)
    if value is None:
        return None
    if not value.isascii() or not value.isdigit() or not 1 <= int(value) <= most:
        raise SystemExit(f"{name} must be a whole number from 1 to {most}, not {value}")
    return int(value)


def _capital(text: str) -> str:
    return text[0].upper() + text[1:]
