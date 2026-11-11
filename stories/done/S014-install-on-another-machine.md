Ticket: S014
Title: Install daywarden on another machine
Status: Done
Story Points: 13
Last Updated: 2026-11-05 21:40:00
---

# User Voice

As the parent who runs the household server, I want to build one package on my development machine, copy it to an Arch Linux machine on the local network, and install it with one script. Then daywarden runs on that machine and can start by itself at boot. `dw up`, `dw down`, `dw status`, `dw enable`, `dw disable`, `rm-attempts`, `add-parent`, and `cut-clips` all work without a clone of the repository, a container registry, hand-typed `docker compose`, `python`, or `systemctl` commands, or any risk of overwriting the household's policy.

# Use Cases

## UC1 - Build the package

- `make dist`, run in the repository on a machine with Docker, builds the policy image and a proxy image, saves both into the package, and writes `dist/daywarden-<version>.tar.gz`. `dist/` is not committed.
- `<version>` is the local build time, `YYYYMMDD-HHMMSS`, such as `20261105-184500`. The images are tagged `daywarden-policy:<version>` and `daywarden-proxy:<version>`. The compose file in the package names those tags and has no `build:` entries, so the target never tries to build or pull a daywarden image.
- The proxy image is `mitmproxy/mitmproxy:12.2.3` with the addon from `proxy/` and its entrypoint copied in, so the installed compose file bind-mounts no source code. It behaves like the development proxy, including refusing to listen when the addon does not load.
- The tarball unpacks to one directory, `daywarden-<version>/`. It holds:
  - `install.sh`
  - the saved images
  - the compose file
  - the host scripts
  - the Python source `cut-clips` needs (the `policy` package) and `policy/requirements.txt`
  - the sample `.env`
  - the repository's `config/policy.yaml` and `config/bypass.txt` as they are when `make dist` runs
  - the CPU architecture the images were built for
- `make dist` does not check for uncommitted changes. It does not change `make up` or the repository's `.env`.

## UC2 - Check dependencies before changing anything

`./install.sh` runs as the parent's own user, from any directory. It refuses to run as root, because the install would land in `/root`. It runs every check below and prints every problem it finds, each with the command that fixes it on Arch, before it changes anything.

These checks are required. If any fails, the installer exits with an error and changes nothing:

- `docker` is installed. Advice: `sudo pacman -S docker`.
- `docker compose` (the Compose v2 plugin) is installed. Advice: `sudo pacman -S docker-compose`.
- The Docker daemon is running, and this user can reach it without `sudo`. Advice: `sudo systemctl enable --now docker.service`, or `sudo usermod -aG docker $USER`, then log out and back in.
- The machine's CPU architecture matches the architecture the images were built for. The message names both.
- No file in `~/bin` has the same name as an installed script (`dw`, `rm-attempts`, `add-parent`, or `cut-clips`) unless an earlier daywarden install put it there. The message names the file.

These checks are warnings. The installer prints them and carries on:

- Neither `docker.service` nor `docker.socket` is enabled at boot, so daywarden cannot start at boot. Advice: `sudo systemctl enable docker.service`.
- This user's systemd manager cannot be reached with `systemctl --user`, for example in a `su` session with no user runtime directory. `dw enable` will not work until it can. Advice: log in as this user directly, such as over `ssh`, and run `dw enable`.
- `PROXY_PORT` or `POLICY_PORT` is already in use by something other than daywarden. The ports come from the existing `~/daywarden/.env`, or from the sample when there is none. Ports held by a running daywarden are not reported.
- `~/bin` is not on the `PATH`. The advice shows the line to add to `~/.bashrc`, such as `export PATH="$HOME/bin:$PATH"`. The installer does not edit any shell start-up file.
- `python3` is not installed, so `cut-clips` will not work. Advice: `sudo pacman -S python`, then run `install.sh` again.
- `ffmpeg` is not installed, or cannot encode Opus (`libopus`), so `cut-clips` will not work. Advice: `sudo pacman -S ffmpeg`. `ffplay`, which `--play` uses, comes with it.

## UC3 - Upgrade a running server

- If any daywarden container is running, the installer asks `Daywarden is running. Restart it to finish the upgrade? [y/N]` after the checks pass and before it changes anything.
- Anything but `y` or `yes`, including an empty answer or the end of input, stops the install with an error, and nothing is changed.
- With a yes, the installer loads the new images and replaces the installed files. It runs `dw down` and then `dw up` and reports whether the stack came back healthy. If `dw up` fails, the installer exits with an error. The new files stay installed, so the parent can fix the configuration and run `dw up` again.
- If daywarden is not running, the installer does not ask and does not start it.
- An upgrade keeps the start-at-boot setting without asking. When daywarden is enabled, the installer rewrites the user service file from the package and reloads the user's systemd manager, so the next boot uses the new file.

## UC4 - Install the files

The layout on the target is:

| Path | On install |
| --- | --- |
| `~/daywarden/docker-compose.yml` | Always replaced |
| `~/daywarden/VERSION` | Always replaced. Holds the package version |
| `~/daywarden/.env` | Created only if missing. Never overwritten |
| `~/daywarden/.env.sample` | Always replaced |
| `~/daywarden/config/policy.yaml` | Copied only if missing. Never overwritten |
| `~/daywarden/config/policy.yaml.sample` | Always replaced |
| `~/daywarden/config/bypass.txt` | Copied only if missing. Never overwritten |
| `~/daywarden/config/bypass.txt.sample` | Always replaced |
| `~/daywarden/ca/` | Created if missing. The CA is generated there on the first `dw up` |
| `~/daywarden/data/` | Created if missing. Spelling recordings go under `data/spelling/` |
| `~/daywarden/lib/` | Always replaced. The Python source `cut-clips` runs |
| `~/daywarden/venv/` | Built or rebuilt as in UC7 |
| `~/bin/dw`, `~/bin/rm-attempts`, `~/bin/add-parent`, `~/bin/cut-clips` | Created, or replaced if an earlier install put them there |
| `~/.config/systemd/user/daywarden.service` | Written by `dw enable` (UC8). Rewritten by an upgrade when daywarden is enabled |

- `~/bin` is created if it is missing.
- On a first install, after the files are in place, the installer asks `Start daywarden automatically at boot? [y/N]`. A `y` or `yes` runs `dw enable`, which does not start daywarden now. Anything else, including an empty answer or the end of input, leaves it disabled. When the user's systemd manager cannot be reached, the installer skips the question and repeats the UC2 warning instead.
- The images are loaded into the local Docker image store. Older daywarden image tags are left in place.
- The sample `.env` sets `CA_VOLUME_PATH` to `${HOME}/daywarden/ca` and `DAYWARDEN_DATA_DIR` to `${HOME}/daywarden/data`. The other values match the repository's `.env`.
- On a first install, `PARENT_NAMES` in the new `.env` is `<host>,<qualified names>,localhost,127.0.0.1`, and the policy-server lines in the new `bypass.txt` are `<host>` and each qualified name. An existing `.env` or `bypass.txt` is not touched.
  - `<host>` is the target's hostname from `/etc/hostname`.
  - A qualified name is `<host>.<suffix>` for each search suffix in `/etc/resolv.conf`, taken from its `search` and `domain` lines in the order they appear. A suffix that does not apply is skipped. That includes one that is empty, or one whose name is already in the list, compared without regard to case.
  - A qualified name is kept only when it resolves, through the machine's normal resolver (as `getent hosts` does), to at least one address on one of this machine's non-loopback network interfaces. A name that does not resolve, resolves only to loopback, or resolves only to another machine's address is left out. Without this check, a stale DNS record would put another machine's name on the parent certificate.
  - Each lookup has a time limit of about two seconds, so a machine with no working DNS still installs promptly. A missing `/etc/resolv.conf`, or one with no search suffixes, means there are no qualified names. Either way the install carries on.
  - The install summary lists each qualified name it added and each one it skipped, with the reason. For example, `garden.bakuna.net: resolves to 192.168.12.5, not this machine`.
  - The `.sample` copies use the same substitution, so comparing a file with its sample shows only the parent's own changes.
- The household database stays in the Compose volume `daywarden_policy-data`. Reinstalling, `dw down`, and `dw up` keep it.
- At the end the installer prints a summary: the version installed, each configuration file it created, each one it kept, and any warnings again. On a first install it ends with the next steps:
  - Review `~/daywarden/.env` and `~/daywarden/config/policy.yaml`.
  - Add any other names or IP addresses for this machine to `PARENT_NAMES`.
  - Run `dw up`, then add a parent with `add-parent`.
  - Run `dw enable` to start daywarden at boot, unless it was enabled just now.
  - Copy `~/daywarden/ca/mitmproxy-ca-cert.pem` to the child computers.

## UC5 - Run the stack with dw

- `dw up` creates the CA and data directories named in `~/daywarden/.env` if they are missing, so Docker does not create them owned by root. It then starts the stack in the background and waits until every service is healthy. It exits with an error naming any service that did not become healthy. The same rule as `make up` applies: a variable already in the environment wins over `.env`.
- `dw down` stops the stack and removes its containers. The CA, the database volume, the configuration, and the recordings stay.
- When daywarden is enabled at boot, `dw up` and `dw down` start and stop it through the user service, as `systemctl --user start` and `stop` would, so systemd's view of it stays accurate. Enabling stays on, so after a `dw down` it still comes back at the next boot. The parent sees the same result and the same errors either way:
  - `dw up` on an enabled daywarden that is already running still brings up any service that is not running, and does not restart the healthy ones.
  - `dw down` always leaves no daywarden container running. That includes containers started before daywarden was enabled.
- `dw status` works whether daywarden is running or not. It exits 0 when all three services are running and healthy, and non-zero otherwise. It prints:
  - the installed version
  - whether daywarden is enabled or disabled at boot
  - whether the last start through the user service failed
  - each service (`decisions`, `observations`, `proxy`) as healthy, starting, unhealthy, or not running
- Every command works from any directory and acts on `~/daywarden`, never on the current directory.
- `dw`, `dw help`, `dw --help`, and `dw -h` print a usage listing `up`, `down`, `status`, `enable`, and `disable`, and exit successfully. An unknown command prints the usage to standard error and exits with status 2.
- If `~/daywarden/docker-compose.yml` or `~/daywarden/.env` is missing, `dw` says daywarden is not installed and to run `install.sh` again.
- `dw` is written so that more commands and switches can be added later without changing how these behave.

## UC6 - Maintenance commands in the container

- `rm-attempts` behaves as in S010.1. Its arguments reach `remove-attempts` in the installed decisions container unchanged.
- `add-parent USERNAME` adds or replaces a parent account in the installed decisions container, as `python -m policy.accounts USERNAME` does. It prompts for the password on the terminal.
- Both work from any directory, pass `--help` through, and work when standard input is not a terminal, as `rm-attempts` does today.
- If daywarden is not running, both print `daywarden is not running. Start it with dw up.` and exit with an error.

## UC7 - Cut clips on the host

- The installer builds a virtual environment at `~/daywarden/venv` with `python3 -m venv` and installs the pinned requirements from PyPI. It rebuilds the environment only when the requirements change, or when the system Python version is not the one the environment was built with, as happens after an Arch Python upgrade. Otherwise it leaves the environment alone.
- When `python3` is missing, the installer skips the environment and finishes the rest of the install with the warning from UC2.
- When the environment cannot be built, for example because PyPI cannot be reached, the installer reports the pip failure. It still installs everything else, finishes with a warning, and says to run `install.sh` again once the problem is fixed.
- `cut-clips` on the target takes the same arguments and behaves as `bin/cut-clips` does in the repository. `--help`, `--list`, `--out`, `--play`, and cutting several recordings all work. Relative recording paths and `--out` paths are relative to the current directory.
- When the environment is missing or broken, `cut-clips` says so and says to run `install.sh` again. It does not show a Python traceback. A missing or Opus-less `ffmpeg` gives the existing `cut-clips` message about installing an `ffmpeg` built with `libopus`.
- Clips written under `~/daywarden/data/spelling/current`, `revision`, or `alphabet` are used by the installed spelling quiz from the next quiz run, with no restart.

## UC8 - Start at boot

- `dw enable` sets daywarden to start at boot, with no `sudo`:
  - It writes `~/.config/systemd/user/daywarden.service`, reloads the user's systemd manager, and enables the service.
  - It turns on lingering for this user (`loginctl enable-linger`), so the service starts at boot without anyone logging in.
  - It does not start a stopped daywarden. A daywarden that is already running stays running, without a restart, and is now tracked by the service.
  - It prints what it did. Running it again when already enabled changes nothing and says so.
- `dw disable` disables the service, so daywarden does not start at the next boot. It does not stop a running daywarden. It leaves lingering on, because other user services may rely on it. It prints the command that turns lingering off (`loginctl disable-linger`). Running it again when already disabled changes nothing and says so.
- At boot, the service waits up to two minutes for the Docker daemon to answer before starting the stack, because a user service cannot be ordered after the system's `docker.service`. If Docker does not answer in that time, the start fails. `dw status` then shows that the last start failed, and `journalctl --user -u daywarden` shows why.
- The installed compose file's restart policy keeps a container that crashes while daywarden is running coming back. Docker does not start daywarden containers by itself when it starts. Whether daywarden runs after a boot depends only on `dw enable` and `dw disable`, not on whether it was running at shutdown.
- `dw enable` warns, with the `sudo systemctl enable docker.service` advice, when neither `docker.service` nor `docker.socket` is enabled at boot. It still enables daywarden. It exits with an error and the advice from UC2 when the user's systemd manager cannot be reached. It also exits with an error when lingering cannot be turned on, advising `sudo loginctl enable-linger $USER`.

# Acceptance Criteria

## Build and first install

- [ ] `make dist` writes `dist/daywarden-<version>.tar.gz` with a `YYYYMMDD-HHMMSS` version, and `make up` in the repository still starts the development stack as before.
- [ ] On a target with Docker and Compose but no daywarden, unpacking the tarball and running `./install.sh` creates the layout in UC4, loads both images, installs `dw`, `rm-attempts`, `add-parent`, and `cut-clips` into `~/bin`, and does not start the stack.
- [ ] After a first install, `PARENT_NAMES` in `~/daywarden/.env` and the policy-server lines in `~/daywarden/config/bypass.txt` name the target's hostname. `config/policy.yaml` is the policy that was in the repository when the package was built.
- [ ] Set up a target where `/etc/resolv.conf` has `search` with a suffix under which `<host>.<suffix>` resolves to this machine's LAN address, and a second suffix under which it does not resolve. After a first install:
  - `PARENT_NAMES` and `bypass.txt` include `<host>.<suffix>` for the first suffix and not the second.
  - The summary lists the second suffix's name as skipped, with the reason.
  - `https://<host>.<suffix>:8090/usage` opens without a certificate name warning in a browser that trusts the CA.
- [ ] A `<host>.<suffix>` that resolves only to another machine's address, or only to `127.0.0.1` or `127.0.1.1` through `/etc/hosts`, is left out and listed as skipped. With no network, or no search suffixes, the install finishes with only `<host>`, `localhost`, and `127.0.0.1`.

## Running the installed server

- [ ] `dw up` from any directory starts the stack, and it is healthy without any image pull or build. A child computer pointed at the target's proxy is allowed, denied, and redirected as the installed `policy.yaml` says. `https://<host>:8090/usage` shows the sign-in form under a certificate signed by the CA in `~/daywarden/ca`.
- [ ] `add-parent ada` from any directory prompts for a password, and that account can sign in on the usage page. `rm-attempts --help` from any directory shows the S010.1 options.
- [ ] `dw down` stops the stack. A later `dw up` keeps the parent account, the stored attempts, and the CA certificate.
- [ ] `dw status` with the stack up lists all three services as healthy, shows the version and whether daywarden is enabled at boot, and exits 0. After `dw down`, it lists them as not running and exits non-zero.
- [ ] `dw`, `dw help`, `dw --help`, and `dw -h` print the usage, listing `up`, `down`, `status`, `enable`, and `disable`, and exit 0. `dw frobnicate` prints the usage to standard error and exits 2. `dw up` with `~/daywarden/.env` removed says to run `install.sh` again.
- [ ] `rm-attempts` and `add-parent` with the stack stopped say daywarden is not running and to start it with `dw up`.

## Upgrades

- [ ] With a changed `~/daywarden/.env`, `config/policy.yaml`, and `config/bypass.txt`, installing a newer package leaves all three byte-for-byte unchanged. It replaces the `.sample` copies, the compose file, `VERSION`, and the scripts.
- [ ] With daywarden running, installing a newer package asks before restarting it. Answering `n`, or pressing Enter, stops the install with an error, and `VERSION`, the compose file, and the running containers are unchanged. Answering `y` installs the files and restarts the stack on the new images, and the stack is healthy.
- [ ] With daywarden stopped, installing a newer package does not ask and does not start it.
- [ ] Installing a newer package does not ask about start at boot and keeps the current setting. With daywarden enabled, it still starts at the next boot after the upgrade.

## Dependency checks

- [ ] With the Docker daemon stopped, or as a user outside the `docker` group, the installer reports the problem with the fix and exits with an error. `~/daywarden` and `~/bin` are unchanged. With `docker compose` also missing, both problems are reported in the same run.
- [ ] With `docker.service` and `docker.socket` both disabled at boot, a port from `.env` already in use by another program, or `~/bin` missing from the `PATH`, the installer prints a warning with advice for each and finishes the install. It does not edit `~/.bashrc` or any other shell file.
- [ ] With a file in `~/bin` named `dw` that daywarden did not install, the installer names it, exits with an error, and changes nothing.
- [ ] Running `./install.sh` as root refuses with an error.
- [ ] A package built for another CPU architecture refuses to install and names both architectures.

## Cutting clips

- [ ] With `python` and `ffmpeg` installed, `cut-clips --help` works from any directory and shows the same options as the repository's `bin/cut-clips`.
- [ ] `cut-clips take.m4a --out ~/daywarden/data/spelling/current` on the target names and writes clips. A spelling task in the installed `policy.yaml` then plays them from the next quiz run, with no restart.
- [ ] `cut-clips take.m4a --play --out ...` plays each clip through the target's speakers before asking for its name.
- [ ] Running `./install.sh` again with unchanged requirements does not rebuild `~/daywarden/venv`. After a package whose `policy/requirements.txt` changed, it does rebuild it.
- [ ] With `python` not installed, the installer warns that `cut-clips` needs it, gives the `pacman` command, and finishes the rest of the install. `dw up` works. `cut-clips` then says its environment is missing and to run `install.sh` again.
- [ ] With `ffmpeg` not installed, the installer warns and gives the `pacman` command. `cut-clips` gives the `libopus` `ffmpeg` message instead of a traceback.
- [ ] With PyPI unreachable on a first install, the installer reports the failure, finishes everything else, and ends with a warning to run `install.sh` again. Running it again with the network back builds the environment, and `cut-clips` works.

## Start at boot

- [ ] On a first install, answering `y` to `Start daywarden automatically at boot?` leaves daywarden stopped and enabled at boot in `dw status`. Pressing Enter leaves it disabled.
- [ ] After `dw enable` with daywarden stopped, rebooting the target with nobody logged in brings daywarden up. The proxy filters a child computer, and `dw status` shows all three services healthy once someone logs in.
- [ ] After `dw enable`, `dw down`, and a reboot, daywarden is up again.
- [ ] After `dw disable` with daywarden running, it keeps running. After a reboot it is not running until `dw up`.
- [ ] Running `dw enable` while daywarden is already running and disabled does not restart any container. A later `dw down` stops every container.
- [ ] Running `dw enable` twice, or `dw disable` twice, says the second time that nothing changed.
- [ ] With daywarden enabled and running, stopping one container with `docker kill` brings it back by itself. `dw up` also brings back a service that is not running, without restarting the others.
- [ ] With Docker disabled at boot, `dw enable` warns with the `sudo systemctl enable docker.service` advice. After a reboot, `dw status` shows that the last start failed, and `journalctl --user -u daywarden` says the Docker daemon did not answer.
- [ ] `dw disable` prints how to turn lingering off and does not turn it off.

# Notes

## Decisions made while refining

- **Install root:** `~/daywarden` holds the runtime files and the configuration. The spelling recordings move from the top of `~/daywarden` to `~/daywarden/data`. The repository's own `.env` and `make up` on the development machine are unchanged.
- **Transfer:** a tarball copied by hand. There is no ssh deploy and no registry.
- **Images:** every image is in the tarball and loaded with `docker load`. The proxy addon is baked into `daywarden-proxy`.
- **Versioning:** the build timestamp, with no dirty working tree check.
- **`.env`, `policy.yaml`, and `bypass.txt`:** each is created only when missing and is never overwritten. The newest copy from the package is always installed beside it as a `.sample` file.
- **The sample policy** is the repository's `config/policy.yaml` as it stands when `make dist` runs.
- **Qualified hostnames:** a first install also adds `<host>.<suffix>`, for each search suffix in `/etc/resolv.conf`, to `PARENT_NAMES` and `bypass.txt`. It is added only when the name resolves to one of this machine's own non-loopback addresses. IP addresses are not added automatically. The parent adds them by hand when they want them, as the next steps say.
- **`~/bin` on the `PATH`:** checked and advised on, never edited into shell files.
- **Upgrade:** ask before restarting a running stack. A no aborts with nothing changed.
- **Start at boot:** a systemd user service with lingering, managed by `dw enable` and `dw disable`, with no `sudo`. Arch's default polkit rules let a user turn on lingering for themselves. When enabled, `dw up` and `dw down` behave like `systemctl --user start` and `stop`. A first install asks about it, and an upgrade keeps the current setting. `dw status` is part of this story.
- **`cut-clips`** runs on the host, in a virtual environment built from PyPI at install time. Bundling wheels is not part of this story. They would have to match the target's Python version, which changes with Arch updates.

## Out of scope

- Moving garden's household data to the new machine. The new machine starts with a new CA, an empty database, no parent accounts, and no recordings. The child computers have to trust the new CA and point at the new proxy, as in `docs/child-computer.md`. Moving data is a later story.
- Uninstalling, removing old image versions, a container registry, an ssh deploy, and any `dw` command other than `up`, `down`, `status`, `enable`, and `disable`.
- A system-wide systemd service, which would need `sudo`.
- Installing the package on garden itself. Its compose project name and ports would collide with the development stack started by `make up`.

## Implementation notes

The repository's `bin/rm-attempts` and `bin/cut-clips` find the repository from their own path, and the development `.env` and compose file stay as they are. Where practical, the installed scripts and the repository scripts should share one implementation that is told which directory to act on, so the commands behave the same in both places.

The repository's `docker-compose.yml` keeps `restart: unless-stopped`, because garden relies on it to bring the development stack back after a reboot. Only the installed compose file changes its restart policy. `on-failure` is the likely choice. It has to be confirmed on a real reboot that Docker does not start `on-failure` containers by itself when the daemon starts. The containers' exit codes after a shutdown decide that. If Docker does start them, choose another policy or have the shutdown remove the containers. The acceptance criteria are the requirement, not the policy name.

The user service is `Type=oneshot` with `RemainAfterExit=yes`, so it shows as active while the stack is up. Its start and stop must call the compose start and stop directly, not `dw up` and `dw down`, which would call back into the service. At shutdown, the user manager may stop after Docker has already gone. A stop that cannot reach Docker must not hang the shutdown.

The qualified-name lookup should be tested with a stand-in `resolv.conf`, a fake resolver, and a fake list of interface addresses. The tests should cover a match, no answer, a loopback-only answer, another machine's address, a duplicate suffix, and a lookup that times out. They must not depend on the DNS of the machine running the tests.

Most of the installer's logic, and `dw enable`, `dw disable`, and `dw status`, can be tested with a temporary `HOME` and fake `docker`, `systemctl`, and `loginctl` commands on the `PATH`. The fakes record their calls and report a chosen state: daemon down, no Compose, running or stopped containers, an architecture, enabled or disabled, lingering on or off, or no user manager. Reboot behaviour is checked through the acceptance criteria. At least one test should build a package, install it into a temporary `HOME`, and bring the stack up from that install with Docker. It must not collide with a development stack on the same ports or with the same Compose project name.

`README.md` gets a section on installing on another machine. It covers:

- `make dist`, then copying and unpacking the tarball
- `./install.sh` and the layout it creates
- `dw up`, `dw down`, and `dw status`
- `dw enable`, `dw disable`, and lingering
- the upgrade prompt
- `cut-clips` paths under `~/daywarden/data`
- pointing the child computers at the new proxy and CA

# Implementation

## Files Added/Changed/Removed

- Added `deploy/build.py` (`make dist`) and `deploy/__init__.py`. It builds `daywarden-policy:<version>` and `daywarden-proxy:<version>`, stages the package, saves the images into it, and writes `dist/daywarden-<version>.tar.gz`.
- Added `deploy/install.sh`, the installer that goes into the package.
- Added `proxy/Dockerfile` and `proxy/.dockerignore`. The proxy image is the compose file's mitmproxy image with `proxy/` copied to `/opt/daywarden`.
- Added `bin/dw`, `bin/add-parent`, `bin/daywarden-service` (what the user service's `ExecStart` and `ExecStop` run), and `bin/daywarden-lib.sh`, the shell library they share with `rm-attempts` and `install.sh`.
- Changed `bin/rm-attempts` to use the library and to say `daywarden is not running. Start it with dw up.` when the decisions container is not running.
- Changed `bin/cut-clips` so that in an installed package it runs `lib/` with `venv/`, and says the environment is missing or broken instead of showing a traceback. In a clone it behaves as before.
- Changed `policy/observations.py` to shut down and exit 0 on SIGTERM.
- Changed `policy/accounts.py` so `--help` and `-h` print the usage and exit 0.
- Changed `Makefile` (adds `dist`), `.gitignore` (adds `dist/`), and `README.md` (adds "Installing on another machine", and mentions `bin/add-parent`).
- Added `tests/hostfakes.py`, `tests/test_install.py`, `tests/test_dw.py`, `tests/test_dist_build.py`, and `tests/test_install_stack.py`. Changed `tests/test_rm_attempts.py` and `tests/test_parent_signin.py`.

## Change Summary

**One implementation in both places.** Every host command finds its root as the directory above its own `bin/`. In a clone that is the repository. In an installed package it is `~/daywarden`. So `bin/dw` in the repository and `~/daywarden/bin/dw` are the same file. The installer copies the commands into `~/daywarden/bin/` and links `~/bin/dw`, `rm-attempts`, `add-parent`, and `cut-clips` to them. A link in `~/bin` that points into `~/daywarden/bin` is how the installer knows an earlier install put it there. Anything else with one of those names stops the install. `~/daywarden/bin/` is the one path that the UC4 table does not list.

**The package.** `deploy/build.py` turns the repository's `docker-compose.yml` into the installed one. It drops `build:`, sets the versioned image tags, sets `pull_policy: never` and `restart: on-failure`, removes the `./proxy` source mount, and moves the data directory default to `~/daywarden/data`. The repository's compose file, `.env`, and `make up` are unchanged. `env.sample` is the repository's `.env` with `CA_VOLUME_PATH` and `DAYWARDEN_DATA_DIR` moved under `~/daywarden`. `policy.yaml` and `bypass.txt` are copied verbatim. `ARCH` is read from the built image (`amd64` here). A full package is about 164 MB. The image layers that Docker saves are already gzip-compressed, so xz was tried and was only 0.4% smaller.

**The installer** refuses root, runs every check, prints each problem with its `pacman` or `systemctl` fix, and exits with nothing changed when a required check fails. When daywarden is running it asks before restarting, and a no stops it with nothing changed. It then loads the images, writes the layout, builds the venv, rewrites the user service when daywarden is enabled, restarts with `dw down` and `dw up` when it was running, and asks about start at boot on a first install. The summary lists what was created and kept, the names added and skipped, and the warnings again.

**Qualified names.** For each `search` and `domain` suffix in `/etc/resolv.conf`, `<host>.<suffix>` is looked up with `timeout 2 getent ahosts`. It is added when an address it resolves to is on a non-loopback interface (`ip -o addr`). Otherwise it is skipped with "does not resolve", "the lookup took longer than 2 seconds", "resolves only to loopback (...)", or "resolves to ..., not this machine". The policy-server lines in `bypass.txt` are found as the lines that equal one of the build machine's names in the package's `PARENT_NAMES`. The first one becomes this machine's names. On garden itself the installer added `garden.bakuna.net`.

**dw.** Each command is a `cmd_<name>` function in a `COMMANDS` list, so a new command is a new function and a new entry. `up` creates the CA and data directories, runs `docker compose up -d --wait`, and on failure names each unhealthy service and prints the last lines the first failed service logged. While daywarden is enabled, `up` also runs `systemctl --user start` and `down` runs `systemctl --user stop`, so the service state stays accurate. Compose still runs directly first, so the parent sees the same output and errors either way, and a missing service is brought back without restarting the healthy ones. The user service is `Type=oneshot` with `RemainAfterExit=yes`. `daywarden-service start` waits up to 120 seconds for Docker. `daywarden-service stop` does nothing, and succeeds, when Docker is not answering.

**Restart policy.** The installed stack uses `on-failure`. The end-to-end test confirms that after `docker stop` every container exits 0. On-failure does not restart a container that exited 0, so Docker does not start daywarden by itself when it starts. The decisions service and mitmproxy already exited 0. The observations service needed a SIGTERM handler. Docker 29 treats `docker kill` as a manual stop under every restart policy, including the development stack's `unless-stopped`, so a `docker kill` container stays down. A real crash, such as SIGKILL to the container's main process, is restarted. The acceptance tests below use the crash.

**Found while testing.** The shipped `policy.yaml` is garden's, and its `spelling` task has `revision_required: 10`. On a new machine with no recordings, the decisions service refuses that policy (`revision_dir: ... is not a directory`), so the first `dw up` fails until ten revision words and the alphabet are recorded, or the task is edited or removed. `dw up` now shows that log line. The end-to-end test records the clips first.

## Suggested Acceptance Testing

### Acceptance test cases for S014

Use a target Arch machine on the LAN with Docker and Compose, called `tundra` below. Build on garden.

1. On garden, run `make dist`. Confirm it writes `dist/daywarden-<YYYYMMDD-HHMMSS>.tar.gz`, that `git status` does not list `dist/`, and that `make up` still starts the development stack (`docker compose ps` healthy).
2. Copy the tarball to `tundra`, unpack it, and run `./install.sh` from inside the directory, as your own user. Answer Enter to the boot question. Confirm that `~/daywarden` holds `docker-compose.yml`, `VERSION`, `.env`, `.env.sample`, `config/policy.yaml` (the same as garden's `config/policy.yaml`), `config/*.sample`, `ca/`, `data/`, `bin/`, `lib/`, and `venv/`. Confirm that `~/bin` has links for `dw`, `rm-attempts`, `add-parent`, and `cut-clips`, that `docker images` shows both versioned images, and that no daywarden container is running.
3. Check `PARENT_NAMES` in `~/daywarden/.env` and the policy-server lines of `~/daywarden/config/bypass.txt`. Confirm they name `tundra` and each `tundra.<suffix>` the summary said it added, and that the summary lists every skipped name with its reason.
4. Record ten revision words and the alphabet with `cut-clips ... --out ~/daywarden/data/spelling/revision` and `.../alphabet`, or remove the `spelling` task from `~/daywarden/config/policy.yaml`. Then, from `/tmp`, run `dw up`. Confirm it reports all services healthy without pulling or building anything. (Without the recordings, confirm `dw up` fails and shows the `revision_dir` log line.)
5. Point a child computer at `tundra:8080`, with the new CA from `~/daywarden/ca/mitmproxy-ca-cert.pem`. Confirm requests are allowed, denied, and redirected as the installed `policy.yaml` says.
6. From any directory, run `add-parent ada` and type a password. Open `https://tundra:8090/usage` in a browser that trusts the new CA. Confirm there is no certificate warning and that `ada` can sign in. Repeat with each added `https://tundra.<suffix>:8090/usage`.
7. Run `dw status` with the stack up. Confirm it shows the version, `Start at boot: disabled`, and all three services healthy, and exits 0 (`echo $?`). Run `dw down`, then `dw status`. Confirm all three are not running and the exit status is non-zero.
8. Run `dw up` again. Confirm `ada` can still sign in, the attempts from earlier are still at `/attempts`, and `mitmproxy-ca-cert.pem` is unchanged.
9. Run `dw enable` with daywarden stopped. Confirm it reports turning on lingering, writing `~/.config/systemd/user/daywarden.service`, and enabling, that daywarden is still stopped, and that `dw status` shows `Start at boot: enabled`. Run `dw enable` again and confirm it says nothing changed.
10. Reboot `tundra` and do not log in. Confirm the child computer is filtered. Log in and confirm `dw status` shows all three healthy.
11. Run `dw down`, reboot, and confirm daywarden is up again.
12. With daywarden running, run `dw disable`. Confirm it keeps running, the output gives `loginctl disable-linger`, and `loginctl show-user $USER -p Linger` still says `yes`. Run `dw disable` again and confirm it says nothing changed. Reboot and confirm daywarden is not running until `dw up`.
13. With daywarden running and disabled, run `dw enable`. Confirm `docker ps` shows the same container start times as before. Then run `dw down` and confirm no daywarden container is left.
14. With daywarden enabled and running, crash the proxy with `sudo kill -9 $(docker inspect -f '{{.State.Pid}}' daywarden-proxy-1)`. Confirm it comes back by itself within a few seconds. `docker kill` does not work for this check, as the Change Summary explains. Then `docker stop daywarden-observations-1`, run `dw up`, and confirm only observations is started.
15. Edit `~/daywarden/.env`, `config/policy.yaml`, and `config/bypass.txt`. Build a newer package on garden and install it with daywarden stopped. Confirm it does not ask to restart and does not start daywarden, the three files are byte-for-byte unchanged, and the `.sample` files, compose file, `VERSION`, and scripts are new.
16. Start daywarden and install a newer package again. Answer `n`, then try again and press Enter. Each time, confirm it stops with an error, and that `VERSION`, the compose file, and the running containers are unchanged. Install again and answer `y`. Confirm it restarts on the new images (`docker ps` image tags) and reports healthy.
17. With daywarden enabled, install a newer package. Confirm it does not ask about boot, and that daywarden starts at the next boot.
18. Run `./install.sh` with the Docker daemon stopped (`sudo systemctl stop docker.service docker.socket`). Confirm it reports the problem with the fix and that `~/daywarden` and `~/bin` are unchanged. Repeat with `docker-compose` also uninstalled and confirm both problems are reported in one run. Repeat as a user outside the `docker` group.
19. Put your own file at `~/bin/dw` and run `./install.sh`. Confirm it names the file, exits with an error, and changes nothing.
20. Run `sudo ./install.sh`. Confirm it refuses.
21. Change the package's `ARCH` file to `arm64` and run `./install.sh`. Confirm it refuses and names both architectures.
22. Disable `docker.service` and `docker.socket`, start something on port 8080 (`python -m http.server 8080`), and remove `~/bin` from `PATH`. Run `./install.sh`. Confirm a warning with advice for each, that the install finishes, and that `~/.bashrc` is unchanged. Then run `dw enable` and confirm it warns about Docker at boot. Reboot, and confirm `dw status` shows the last start failed and `journalctl --user -u daywarden` says the Docker daemon did not answer.
23. Run `./install.sh` in a `su - youruser` session. Confirm it warns that the user's systemd manager cannot be reached and skips the boot question. Confirm `dw enable` there exits with the same advice.
24. Set up a resolv.conf suffix whose `tundra.<suffix>` resolves only to another machine, and another under which it resolves only to `127.0.1.1` through `/etc/hosts`. Do a first install into a fresh account. Confirm both are left out and listed as skipped. With the network unplugged, confirm the install finishes promptly with only `tundra`, `localhost`, and `127.0.0.1`.
25. From any directory, run `cut-clips --help`. Confirm it matches the repository's `bin/cut-clips --help`. Run `cut-clips take.m4a --list`, then `cut-clips take.m4a --play --out ~/daywarden/data/spelling/current`. Confirm each clip plays before its name is asked, and that a spelling quiz uses the clips on its next run without a restart.
26. Run `./install.sh` again with the same package. Confirm it says the cut-clips environment is up to date. Install a package whose `policy/requirements.txt` changed and confirm it rebuilds it.
27. With `python` uninstalled, run `./install.sh`. Confirm the warning and `pacman` command, that the install finishes, and that `dw up` works. Confirm `cut-clips` says its environment is missing and to run `install.sh` again.
28. With `ffmpeg` uninstalled, run `./install.sh` and confirm the warning. Confirm `cut-clips take.m4a --list` gives the `libopus` message and no traceback.
29. With PyPI blocked, do a first install. Confirm the pip failure is shown, everything else is installed, and it ends with a warning to run `install.sh` again. Unblock it, run `./install.sh` again, and confirm `cut-clips --help` works.
30. Run `dw`, `dw help`, `dw --help`, and `dw -h`. Confirm each prints the usage with `up`, `down`, `status`, `enable`, and `disable`, and exits 0. Run `dw frobnicate` and confirm the usage goes to standard error with exit status 2. Move `~/daywarden/.env` away, run `dw up`, and confirm it says to run `install.sh` again.
31. With daywarden stopped, run `rm-attempts --all` and `add-parent ada`. Confirm each says `daywarden is not running. Start it with dw up.` With it running, confirm `rm-attempts --help` shows the S010.1 options and `add-parent --help` shows its usage.
