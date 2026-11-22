/**
 * The household's password rules, checked as the parent types (S046).
 *
 * The service sends the settings with the data the Account and Reset password
 * pages load, and checks every rule again when a password is sent. This file
 * says the length and strength rules the way `policy/password_rules.py` does,
 * word for word, and makes the same known words in the same order. The
 * history rule needs the stored hashes, so only the service checks it.
 *
 * zxcvbn 4.4.2 here and the service's port agree on every password the tests
 * try (`tests/test_password_strength.py`), so the portal asks for no more
 * guesses than the service does, apart from one part in a billion for the
 * rounding of the two kinds of number. zxcvbn and its 800 KB of dictionaries
 * load only on the two pages that check passwords.
 */

export type Strength = { attacker: string; label: string; rate: number; seconds: number; time: string };
export type PasswordRules = { min_length: number | null; history: number | null; strength: Strength | null; lines: string[] };
/** zxcvbn's estimate of the guesses a password needs, with the account's known words. */
export type Estimate = (password: string, known: string[]) => number;

export const NO_RULES: PasswordRules = { min_length: null, history: null, strength: null, lines: [] };
/** zxcvbn reads only this many characters, as the service's does. Its l33t matching takes seconds on a long random password. */
export const READ = 100;
const YEAR_SECONDS = 365.24219 * 86400;
const ROUNDING = 1 + 1e-9;

/** Load zxcvbn when the strength rule is on. */
export async function loadEstimate(rules: PasswordRules): Promise<Estimate | null> {
  if (!rules.strength) return null;
  const { default: zxcvbn } = await import("zxcvbn");
  return (password, known) => zxcvbn(Array.from(password).slice(0, READ).join(""), known).guesses;
}

/** The username, the address, and the current password, each followed by its runs of letters and of digits, as the service makes them. */
export function knownWords(username: string | null, email: string | null, current: string | null = null): string[] {
  const found: string[] = [];
  for (const word of [username, email, current]) {
    if (!word) continue;
    const lower = word.toLowerCase();
    const pieces = (lower.match(/[a-z]+|[0-9]+/g) ?? []).filter((piece) => piece.length >= 3);
    for (const piece of [lower, ...pieces]) if (!found.includes(piece)) found.push(piece);
  }
  return found;
}

/** Say a length of time roughly: "about 3 days". */
export function span(seconds: number): string {
  if (seconds < 1) return "less than a second";
  const steps: [number, number, string][] = [
    [60, 1, "second"],
    [3600, 60, "minute"],
    [86400, 3600, "hour"],
    [YEAR_SECONDS, 86400, "day"],
    [1e6 * YEAR_SECONDS, YEAR_SECONDS, "year"],
  ];
  for (const [limit, size, unit] of steps) {
    if (seconds < limit) {
      const count = Math.floor(seconds / size + 0.5);
      return `about ${count.toLocaleString("en-US")} ${unit}${count === 1 ? "" : "s"}`;
    }
  }
  return "more than a million years";
}

/** Each length or strength rule password breaks, with how to fix it. Empty when it passes them all. */
export function ruleProblems(password: string, rules: PasswordRules, estimate: Estimate | null, known: string[]): string[] {
  const found: string[] = [];
  const length = Array.from(password).length;
  if (rules.min_length !== null && length < rules.min_length) {
    found.push(`Use at least ${rules.min_length} characters. This one has ${length}.`);
  }
  const strength = rules.strength;
  if (strength && estimate) {
    const seconds = estimate(password, known) / strength.rate;
    if (seconds < strength.seconds * ROUNDING) {
      const label = strength.label.charAt(0).toUpperCase() + strength.label.slice(1);
      found.push(
        `${label} could guess this in ${span(seconds)}. It needs to hold out for ${strength.time}. ` +
          "Make it longer, such as by adding another word or two.",
      );
    }
  }
  return found;
}
