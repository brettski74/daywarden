Ticket: S048
Title: Deploy to an Environment
Status: In Progress
Story Points: 5
Last Updated: 2026-11-27 01:24:35
---

# User Voice

As whoever runs Daywarden, I want one command that copies the latest package to a named environment and installs it
there, so that deploying is quicker, less tedious, and the same every time.

# Behaviour

An **environment** is defined in `GLOSSARY.md`. A version's *directory* is `~/daywarden-<version>/` in the
environment user's home.

## Environments file

- [ ] `deploy/environments.ini` defines the environments, one section each. Git ignores it, `make dist` does not
      package it, and the committed `deploy/environments.ini.sample` names no real machine.
  - An environment takes `host` (required, which may be an alias from `~/.ssh/config`), `user`, `port`, and `keep`.
  - The `[settings]` section takes `default`, the environment used when none is named, and `user`, used by every
    environment that has no `user` of its own.
  - With no `user` in either place, ssh chooses it as it usually would. Passwords are never read from the file.
- [ ] `make deploy ENV=prod` deploys to `[prod]`, and `make deploy` deploys to the default.
- [ ] An unknown name, or no `ENV` with no default, fails and lists the configured environments. A missing file fails
      and says to copy the sample. A section with no `host`, a setting it does not know, or a `port` or `keep` that is
      not a whole number in range fails and names the problem. `port` is 1 to 65535 and `keep` is at least 1. None of
      these connects to anything.
- `ENV` and `VERSION` count only when given on the `make` command line, not when the shell happens to export them.

## Choosing the package

- [ ] The newest package in `dist/` is deployed. `VERSION=20261122-072721` deploys that one instead.
- [ ] An empty or missing `dist/`, or a `VERSION` with no package in `dist/`, fails before connecting, even when the
      environment already has that version's directory. `make deploy` never builds a package.
- [ ] The environment, `user@host`, version, and package age are shown, and the deploy carries on without asking.

## Deploying

- [ ] A password is asked for once, and every step uses that one connection.
- [ ] The package is copied to the user's home, expanded into the version's directory, and the copy is removed.
- [ ] Deploying a version whose directory is already there says so, skips the copy, and installs from it again. A
      directory left by an interrupted deploy is replaced, not reused. So is one unpacked by hand.
- [ ] `install.sh` runs at a terminal, so its questions can be answered, with the `PATH` a login there has.
- [ ] If `install.sh` fails, or the restart question is answered no, `make deploy` fails, removes no old version, and
      keeps the version's directory for the next try.
- [ ] After a successful install, `dw status` from the environment is shown. Its result does not make the deploy
      fail, and nothing runs `dw up` or `dw enable`.

## Cleaning up

- [ ] After a successful install, the `keep` newest version directories (3 when not set) and the installed version's
      are kept. The others are removed, with any package copy left for them and their `daywarden-policy` and
      `daywarden-proxy` images, and each removal is listed. `~/daywarden` and other names are never touched.
- [ ] An image or directory that cannot be removed is a warning, and the deploy still succeeds.

## Documentation

- [ ] `README.md` describes the environments file and `make deploy`.

# Notes

- Out of scope: building the package, a dry run, cleaning up without deploying, deploying to several environments at
  once, running from an automation server, and undoing database changes when an older version is installed.
- The installer's own checks and questions are those of S014.

# Implementation

## Files Added

- `deploy/push.py`: `make deploy`.
- `deploy/environments.ini.sample`: the committed sample of the environments file.
- `tests/test_deploy.py`: the deploy against fake `ssh`, `scp`, and `docker`, with a temporary directory as the
  environment's home.
- `GLOSSARY.md`: defines **Environment**.

## Files Changed

- `Makefile`: the `deploy` target.
- `.gitignore`: ignores `deploy/environments.ini`.
- `README.md`: the "Deploying with make deploy" section.

## Change Summary

`deploy/push.py` reads the environments file and picks the package before it connects. It then opens one ssh
`ControlMaster` connection, which every later `ssh` and `scp` shares, and closes it when it ends. The system `ssh`
and `scp` are used, so `~/.ssh/config`, keys, and password prompts work as they usually do. No SSH library was added.

A package is unpacked beside its place and moved there when whole, with a `.unpacked` file inside. Only a directory
with that file is reused.

`install.sh` is started through the user's interactive login shell. Without it, a command run over ssh may miss
`~/bin` on the `PATH`, and the installer would warn about it wrongly. The other remote commands run under `sh`.

## Suggested Acceptance Testing

### Acceptance test cases for S048

1. **First deploy.** Copy the sample to `deploy/environments.ini`, set `uat` to a real machine and its user, run
   `make dist`, then `make deploy`. Answer the questions. Covers Deploying and "Choosing the package".
2. **Again, and refused.** With daywarden running there, run `make deploy` and answer `n` to the restart question,
   then run it again and answer `y`. Covers the existing directory and failed install checks.
3. **Cleaning up.** With four or more versions deployed, or with `keep = 1`, deploy the newest and then an older one
   with `VERSION=`. Compare `ls ~` and `docker images` there. Covers Cleaning up, apart from the warnings, which the
   automated tests cover.
4. **Mistakes.** Try `ENV=nope`, no `default`, no `host`, a misspelt setting, `keep = 0`, no environments file, a
   `VERSION` with no package, and an empty `dist/`. Covers "Environments file" and the failures in "Choosing the
   package".
5. **Documentation.** Read the README section, and check that `git status` does not show `deploy/environments.ini`.
