Ticket: S046
Title: Password Rules
Status: Refined
Story Points: 13
Last Updated: 2026-11-20 23:17:01
---

# User Voice

As whoever runs Daywarden, I want to set rules for how long, how new, and how hard to guess a parent's password must
be, so that a stolen copy of the database or a guessed password does not hand over the household's controls.

# Behaviour

## Settings in .env

Each rule is off while its setting is not set. The settings are read at startup like `PARENT_IDLE`, so a change needs
`dw restart`. A value that is set but not valid stops the service with a message that names the setting.

- [ ] `.env.sample` and `README.md`'s Configuration table describe each setting, and say that a rule is off when its
      setting is left out:
  - `PASSWORD_MIN_LENGTH`: the fewest characters a password may have, a whole number from 1 to 200.
  - `PASSWORD_HISTORY`: how many recent passwords a new one must differ from, a whole number from 1 to 20. The
    current password counts as one, so `1` refuses only the current password.
  - `PASSWORD_ATTACKER` and `PASSWORD_CRACK_TIME`: the attacker a password must hold out against, and for how long.
- [ ] `PASSWORD_ATTACKER` is one of these names, matched without regard to case. The guess rates assume the attacker
      has a copy of the database and is guessing against its Argon2id hashes. README's table gives each rate.
  - `script-kiddie`, a motivated script kiddie: 100 guesses a second.
  - `identity-thief`, a tech-savvy identity thief: 10,000 a second.
  - `crime-ring`, an organised crime ring: 1,000,000 a second.
  - `government`, a government intelligence agency: 1,000,000,000 a second.
- [ ] `PASSWORD_CRACK_TIME` is a whole number above 0 followed by `s`, `m`, `h`, `d`, or `y`, such as `72h`, `365d`,
      or `10y`. A year is 365.24219 days.
- [ ] `dw restart` stops with a message naming the setting for `PASSWORD_MIN_LENGTH=0`, `PASSWORD_MIN_LENGTH=201`,
      `PASSWORD_HISTORY=abc`, `PASSWORD_HISTORY=21`, `PASSWORD_ATTACKER=hacker`, `PASSWORD_CRACK_TIME=10w`, and either
      of `PASSWORD_ATTACKER` or `PASSWORD_CRACK_TIME` set without the other. The message for an unknown attacker lists
      the four names.

## The rules

A password is refused if it breaks any rule that is on. The empty-password and 200-character limits of S044.2 still
apply as they do now.

- [ ] Length: with `PASSWORD_MIN_LENGTH=12`, an 11-character password is refused, and a 12-character one passes this
      rule.
- [ ] History: with `PASSWORD_HISTORY=3`, a password that is the same as the current password or either of the two
      before it is refused. The fourth-newest passes this rule. Any difference counts, so `Tulip-Garden-7` after
      `Tulip-Garden-8` passes this rule.
- [ ] Every password that is set, including one set with `--force`, is added to the account's history. Only the newest
      `PASSWORD_HISTORY` passwords are kept, and none older than the current one are kept while the rule is off.
      Lowering the setting and restarting drops the older ones, so raising it again later does not bring them back.
      Removing an account removes its history.
- [ ] Every request to set a password does the same hashing work: one Argon2id hash of the new password and one
      check against each of `PASSWORD_HISTORY` stored hashes. An account with fewer stored hashes is checked against
      a dummy hash for each one missing. With `PASSWORD_HISTORY=5`, a change on an account with one stored password
      takes as long as on one with five, whether the password is refused or saved.
- [ ] Strength: with `PASSWORD_ATTACKER=identity-thief` and `PASSWORD_CRACK_TIME=1y`, a password is refused when
      zxcvbn's estimate of the guesses it needs, divided by 10,000 a second, comes to less than a year. `correct horse`
      is refused, and four uncommon words passes this rule.
- [ ] The username and email address of the account count as known words for zxcvbn, so `ada` and `ada2026!` score
      as easy for the account `ada`. On the Account page the current password is also a known word, so after
      `Summer2025!Picnic` the password `Summer2026!Picnic` is refused as too easy to guess, even though the history
      rule lets it pass.
- [ ] Existing passwords that break a rule still sign in. The rules are checked only when a password is set.

## Account page

Changing a password works as in S044.2, with these additions.

- [ ] As the new password is typed, a line under it says which rules it breaks and how to fix it, using the account's
      known words, and Save stays available. For example "Use at least 12 characters. This one has 9." and "An
      identity thief could guess this in about 3 days. It needs to hold out for 1 year. Make it longer, such as by
      adding another word or two." The line names no rule that is off, and says nothing when every rule passes.
- [ ] Save with a password that breaks length or strength is refused on the page before anything is sent, with the
      same advice in the status bar. Nothing changes, and the current password still signs in.
- [ ] Once the page has sent the passwords, nothing it sees can tell a wrong current password from a new password the
      service refused under a rule. Both get the same answer, with the same timing, the same delay S044.2 gives a
      wrong current password, and the same hashing work as above. So a wrong current password is still checked
      against the history and the strength rule, and a refusal under a rule waits as a wrong current password does.
      The status bar says "Your password was not changed. Learn more", where Learn more links to the Account section
      of the Password help page below. This replaces S044.2's message for a wrong current password. It is the answer to a password in the history, which the page
      cannot check itself. It is also the answer to a password that breaks length or strength because the page's own
      check was turned off, such as by sending the request with `curl` or editing the script in the browser's
      developer tools.
- [ ] The portal never accepts a password the service would refuse for length or strength. Where the portal's zxcvbn
      gives a different estimate from the service's, the portal asks for 5% more guesses than the service does.

## Reset password page

Resetting by email works as in S044.2, with these additions.

- [ ] The page checks length and strength as the new password is typed, and on Save, as the Account page does. The
      page knows no username, email address, or current password, so it uses no known words.
- [ ] Once the page has sent a password, nothing it sees can tell a saved password from a link that is not valid or a
      password the service refused under a rule. All three get the same answer, with the same timing and the same
      work as above, so an invalid link is also checked against `PASSWORD_HISTORY` dummy hashes. The sign-in screen
      opens with "Try signing in with your new password. If it does not work, learn more", where learn more links to
      the Reset section of the Password help page below. This replaces S044.2's message after Save.
- [ ] A refused password does not use the link. The same link, while it is still valid, then saves a password that
      passes, and the account signs in with it. A link still stops working only when it is used for a successful
      change, replaced, or out of time, as in S044.2.

## Password help page

- [ ] `/parent/password-help` explains, in general terms, why the service may not have changed a password. It works
      with no session, with the portal's sign-in look, and is refused over plain HTTP like every parent address. It
      says nothing about any account or request, so every visitor sees the same page. It has two sections, each with
      its own address, and each Learn more link above opens at its own section.
  - Account, `/parent/password-help#account`: "Your password was not changed. Either the current password was wrong,
    or the new password does not meet this household's password rules."
  - Reset, `/parent/password-help#reset`: "If your link was still valid and your new password meets this household's
    password rules, it is saved. If you cannot sign in with it, either the link had stopped working or the password was
    refused. Open your link again to try another password, or ask for a new link with Forgot password."
  - Both sections end with the same advice: "A password used recently, or one close to the username or email address,
    is refused. A longer password, such as one with another word or two, usually passes."
- [ ] The page lists the rules that are on, in the words the Account page uses as a password is typed, such as "At
      least 12 characters" and "Different from your last 3 passwords". These come from the settings, not from any
      account, so they tell a visitor nothing that `.env` does not.
- [ ] The page links back to the Account page, which opens the sign-in screen first when no session is signed in.

## dw-account

- [ ] `dw-account add --password` and `dw-account update --password` refuse a password that breaks a rule, using the
      username and email address as known words, and ask for the password again at a terminal. They name each rule
      broken, with the advice the Account page gives as the password is typed. For history, the message is "You have
      used this password recently. Choose one you have not used for your last 3 passwords." Anyone who can run
      `dw-account` can already set any password, so this tells them nothing new. Without a terminal, they print the reason and exit with status 1, and nothing changes.
- [ ] With `--force`, both set the password without checking the rules, and still add it to the history.
      `--force` without `--password` is an error. `dw-account help` and `--help` describe `--force`.

## Service log

- [ ] Each password change the service refuses on the Account page or from a valid reset link adds a line to
      `dw logs`. The line names the account, where the request came from, and every reason it was refused, such as
      "password for ada refused on the Account page: current password wrong, used within the last 3 passwords". The line never holds the
      password, any part of it, or the strength estimate. A reset link that is not valid has no account, so no rule is
      checked and no line is added.

## Documentation

- [ ] `README.md`'s Parent accounts section describes the rules, the attacker names, what the strength estimate means,
      and `--force`.

# Notes

- zxcvbn libraries. On the server, the `zxcvbn` package on PyPI is a port of Dropbox's zxcvbn 4.4.2. In the portal,
  the `zxcvbn` 4.4.2 npm package uses the same algorithm and dictionaries. If they agree on a corpus of test passwords,
  the 5% margin is not needed, and the implementation summary should say so. `@zxcvbn-ts/core` is maintained, but its
  scores differ more from the server's.
- The zxcvbn dictionaries are about 800 KB. Bundle them with the portal, because it loads nothing from outside the
  parent port, and load them only on the Account and Reset password pages.
- The service and the portal need the rule settings, but not the history. Send the settings with the data the two
  pages already load. The Reset password page loads them without a session.
- History is kept as Argon2id hashes, each with its own salt, so each check costs one full hash. A change costs
  `PASSWORD_HISTORY` + 1 hashes, which is why the setting stops at 20.
- An invalid reset link has no account, so it has no known words. To keep its timing the same as a valid link's,
  the service should still run zxcvbn with stand-in known words of a similar size. Argon2id dominates the time
  anyway.
- Out of scope: making an account with a weak password change it at sign-in, and measuring how close a new password
  is to old ones other than the current password. Only hashes of the old ones are kept.
- Sizing: about the effort of S044.2's Account and Reset pages without email, plus settings, a history table, and
  two zxcvbn libraries kept in step. 13.
