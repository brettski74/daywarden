Ticket: S046
Title: Password Rules
Status: Refined
Story Points: 13
Last Updated: 2026-11-20 23:55:00
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
- [ ] *Added in implementation:* zxcvbn reads only the first 100 characters of a password, in the service and the
      portal alike. On a random 200-character password it takes about 4 seconds in the service and 8 in the browser.
      So two passwords that share their first 100 characters get the same strength estimate.
- [ ] The username and email address of the account count as known words for zxcvbn, so `ada` and `ada2026!` score
      as easy for the account `ada`. On the Account page the current password is also a known word, so after
      `Summer2025!Picnic` the password `Summer2026!Picnic` is refused as too easy to guess, even though the history
      rule lets it pass. *Changed in implementation:* each known word also counts its runs of 3 or more letters or
      digits, such as `summer`, `2025`, and `picnic`. zxcvbn matches a known word only as a whole, so without the runs
      `Summer2026!Picnic` would pass as `Summer2025!Picnic`'s neighbour.
- [ ] Existing passwords that break a rule still sign in. The rules are checked only when a password is set.

## Account page

Changing a password works as in S044.2, with these additions.

- [ ] Once typing in the new password pauses for 1 second, advice under it says which rules it breaks and how to fix it, using the account's
      known words, and Save stays available. For example "Use at least 12 characters. This one has 9." and "An
      identity thief could guess this in about 3 days. It needs to hold out for 1 year. Make it longer, such as by
      adding another word or two." Each broken rule is on its own line, and on the Account page the advice may run
      wider than the password fields. It names no rule that is off, and says nothing when every rule passes.
      The advice stays as it was until the next pause, and Save checks the password as it is without waiting.
      *Changed in implementation:* Save on the Account page is still S044.2's Change password button.
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
      *Changed in implementation:* the two agree on every password tested, so there is no 5% margin. The portal asks
      for one part in a billion more, which covers how the two round their numbers.

## Reset password page

Resetting by email works as in S044.2, with these additions.

- [ ] The page checks length and strength as the new password is typed, and on Save, as the Account page does. The
      page knows no username, email address, or current password, so it uses no known words. *Changed in
      implementation:* the page has no status bar, so a refused Save shows the advice above Save, where it shows
      S044.2's refusals.
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
- [ ] *Added in implementation:* with no parent account, the page shows the closed portal message, as Forgot password
      and Reset password do. With no rule on, it says "No password rules are turned on. A password is 1 to 200
      characters."

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

# Implementation

## Files Added

- `policy/password_rules.py`: the four settings and their startup checks, the attackers, the length and strength
  checks with their advice and log reasons, the help page's lines, the known words, and the rough time ("about 3 days").
- `policy/password_strength.py`: zxcvbn's guess estimate from the PyPI port, made to agree with the npm zxcvbn 4.4.2.
- `policy/portal/src/passwordRules.ts`: the portal's length and strength checks, known words, and rough time, in the
  same words, and the lazy load of zxcvbn.
- `policy/portal/src/pages/PasswordHelp.tsx`: the Password help page.
- `policy/portal/src/components/RuleAdvice.tsx`: the advice under a new password, one line per broken rule.
- `policy/portal/src/useSettled.ts`: a value that follows a field only once typing pauses for 1 second.
- `policy/portal/src/components/HelpMessage.tsx`: a service message whose last words link to a help page.
- `policy/portal/src/passwordRules.test.tsx`: the Account, Reset password, and Password help pages under the rules.
- `tests/test_password_rules.py`: settings, each rule on both pages, the history, the equal hashing work, the log
  lines, and the help page's address.
- `tests/test_dw_account_rules.py`: `dw-account` under the rules, with and without a terminal, and `--force`.
- `tests/test_password_strength.py`: the service's estimate against the portal's zxcvbn run in Node, on 600 passwords.

## Files Changed

- `policy/accounts.py`: the `password_history` table, filled and trimmed at startup and on every password set;
  `screen_password`, the equal hashing work; the Account page's change and the reset split into a lookup, the work,
  and the write; `dw-account` checks the rules, asks again at a terminal, and takes `--force`.
- `policy/account_pages.py`: both POSTs check every rule, give the one answer for each refusal, and log refusals;
  both GETs send `rules`.
- `policy/app.py`: reads the rules at startup and logs them.
- `policy/portal.py`: Password help is no page to return to after a sign-in.
- `policy/requirements.txt`: `zxcvbn==4.5.0`.
- `policy/portal/package.json`, `package-lock.json`: `zxcvbn` 4.4.2 and `@types/zxcvbn` 4.4.5.
- `policy/portal/src/pages/Account.tsx`, `Reset.tsx`, `Login.tsx`: the advice line, the refusal before sending, and
  Learn more.
- `policy/portal/src/api.ts`, `routes.tsx`, `styles/layout.css`: `rules` in the reset setting, the route, and the
  styles.
- `docker-compose.yml`: passes the four settings to the decisions service.
- `.env.sample`, `README.md`, `docs/parent-portal.md`: the rules, the attackers, `--force`, the help page, and the
  data the pages load.
- `tests/test_password_reset.py`: S044.2's answers replaced by S046's.

## Files Removed

None.

## Change Summary

The rules are one frozen `PasswordRules`, read from `.env` once at startup, like the email settings. An empty value
counts as unset, because Compose passes an unset setting as empty. The service and `dw-account` each read it.

History is a table of Argon2id hashes, newest last, including the current password. At startup the service adds any
current password that is missing, such as one set before S046, and keeps only the newest `PASSWORD_HISTORY` per
account, or one while the rule is off. Every password set goes through one `_set_hash`, which adds and trims. An
`Accounts` made without rules, as tests make it to look at the database, never trims.

`screen_password` is the one place a new password is hashed. It does the same Argon2id work for every request: the
current-password check (Account page only, with sign-in's work for a missing or over-long one), one hash, and one check
against each of `PASSWORD_HISTORY` stored hashes, with the dummy hash for each one missing. It runs zxcvbn too. None of
it stops early. It runs on a worker thread, since 20 history checks would hold up the event loop for about a second.
The database parts stay on the event loop, where the SQLite connection lives. The Account page checks every rule
before it answers, even when the current password is wrong. The Reset password page still answers at once and does
the lookup, the work, and the write afterwards, as in S044.2. An invalid link runs zxcvbn with random stand-in words
the size of a username and address. A refused reset no longer deletes the token, and the write uses the token only if
it is still the same row.

The two zxcvbn libraries first disagreed on about 6% of a test corpus. There were four causes, each fixed in
`password_strength.py` without forking the package. The port fixes the reference year at 2017. It sees an emoji as one
character where JavaScript sees two UTF-16 units. Its search for the cheapest sequence of matches visits shorter
sequences in insertion order, not ascending order, so it keeps candidates the JavaScript drops. Its `\d` and
`isupper` accept every script's digits and capitals. After the fixes, the two agree to within 3e-16 on over 6,000
passwords, so the 5% margin is not needed. `@zxcvbn-ts/core` was not used, as the notes advise. zxcvbn 4.5.0 is the
PyPI version: it is 4.4.28 plus a length guard.

Known words include the runs of letters and digits in each word, in the same order on both sides, because zxcvbn ranks
a known word by its place in the list.

The portal's zxcvbn is a dynamic `import()`, so its 820 KB file is built separately and loaded only by the Account and
Reset password loaders, and only while the strength rule is on.

The pages were checked in jsdom, not in a browser. The running stack on this machine was left alone.

## Suggested Acceptance Testing

### Acceptance test cases for S046

1. **Settings.** Try each bad value in the Settings check, one at a time with `dw restart`, and read the message. Set
   `PASSWORD_MIN_LENGTH=12`, `PASSWORD_HISTORY=3`, `PASSWORD_ATTACKER=Identity-Thief`, and `PASSWORD_CRACK_TIME=1y`,
   `dw restart`, and check the rules line in `dw logs decisions`. Read `.env.sample` and README's Configuration table.
   Covers Settings in .env.
2. **Account page.** With those settings, sign in as `ada`. In New password, type a 9-character password, then
   `correct horse`, then `ada2026!`, then four uncommon words, and read the line each time. Press Change password with
   `correct horse`. Nothing should be sent, and the advice should show in the status bar. Change to
   `Summer2025!Picnic`, then try `Summer2026!Picnic` with that as the current password. Covers the Length, Strength,
   and known-word checks, and the Account page.
3. **One answer, and the log.** On the Account page, try a wrong current password with a strong new one, the right
   current password with the current password as the new one, and both wrong together. Each says "Your password was
   not changed. Learn more". Follow Learn more. Then send a weak password with
   `curl -k -b 'parent_session=<cookie>' -H 'Content-Type: application/json' -d '{"current":"…","password":"short","again":"short"}' https://<name>:<POLICY_PORT>/parent/api/account/password`.
   Check `dw logs decisions` for one line per refusal, each with all its reasons and no password. Covers the Account
   page's equal answer and Service log.
4. **History.** With `PASSWORD_HISTORY=3`, change through `Tulip-Garden-8`, `Tulip-Garden-9`, then try each of the
   last three passwords, then `Tulip-Garden-7`, then the fourth newest. Set `PASSWORD_HISTORY=1` with `dw restart`, then
   3 again, and reuse a password that had been dropped. Remove an account with `dw-account remove`. Covers the History
   checks.
5. **Reset page.** With email on, ask for a link for `ada`, open it, type a weak password and read the line, press
   Save (refused on the page), send a password from the history with `curl` to `/parent/api/password-reset/save` with
   the link's token, then save a strong password from the page and sign in with it. Also save from a link that is not
   valid. Each Save shows "Try signing in with your new password. If it does not work, learn more", and the log has a
   line only for the valid link's refusal. Covers Reset password page and the log's invalid-link case.
6. **Equal timing.** With `PASSWORD_HISTORY=20`, time several Account page changes with `curl -w '%{time_total}'` for
   an account with one stored password and one with many, refused and saved. Covers the equal hashing work.
7. **Password help.** Signed out, open `/parent/password-help`, `#account`, and `#reset`, follow Back to the Account
   page, and try plain HTTP. Change the settings and reload to see the list follow them. Covers Password help page.
8. **dw-account.** With the rules on, run `dw-account add --password`, and `update --password` with a weak password, a
   recent one, and a strong one, both at a terminal and piped (`printf 'short\n' | dw-account update --password ada`,
   status 1). Then `update --password --force ada` with a weak one, then `update --password ada` with the same
   (refused as recent), then `dw-account update --force ada` (usage error), and `dw-account help`. Covers dw-account.
9. **Old passwords and documentation.** Raise `PASSWORD_MIN_LENGTH` above an existing password's length, `dw restart`,
   and sign in with it. Read README's Parent accounts and Password rules. Covers the existing-password check and
   Documentation.
