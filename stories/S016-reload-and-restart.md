Ticket: S016
Title: Reload the configuration and restart daywarden with dw
Status: Done
Story Points: 21
Last Updated: 2026-11-07 12:35:00
---

# User Voice

As a parent, I want to apply a change to the household policy while the children are online, without dropping their
connections or losing a quiz they are in the middle of. I also want a broken edit refused before it can take anything
down. When I do need a full restart, I want one command that does it quickly and safely.

# Use Cases

## UC1 - Change the policy while a child is online

- The parent edits `config/policy.yaml`, for example moving bedtime or raising a quota, and runs `dw reload`.
- The next request through the proxy is decided by the new policy. No container restarts, so connections that are
  open stay open.
- A download or video stream already running is treated as any running transfer is treated after a policy edit
  today. It is not disturbed until the deadline or byte ceiling recorded when it was allowed is reached. Then its rules
  are walked again with the reloaded policy.
- The parent stays signed in to the parent pages.

## UC2 - A mistake in the edit is refused

- The parent saves a policy with several mistakes, such as two site groups with the same priority, a misspelled
  setting, and a broken include.
- `dw reload` lists every problem it can find, each with its file, line, and what is wrong. It changes nothing. The
  previous policy stays in force.
- The parent fixes all of them in one pass and runs `dw reload` again. It does not take one run per mistake.

## UC3 - A task changes while a child is doing it

- A child is partway through a spelling or arithmetic attempt. The parent changes that task's settings, adds a new task,
  or changes how many tasks are required, and runs `dw reload`.
- The attempt in progress carries on as it would after `dw down` and `dw up` with the same change, but without the
  page losing its connection while containers restart.
- The next attempt that starts uses the new settings.

## UC4 - A change that needs new containers

- The parent changes `.env`, for example `PROXY_PORT`, `PARENT_NAMES`, or `OBSERVATION_INTERVAL`, and runs
  `dw reload`.
- `dw reload` still reloads the policy. It also names the services whose containers would change and says that
  `dw restart` applies the change.

## UC5 - Restart everything

- The parent runs `dw restart` after an upgrade, after a `.env` change, or because something looks wrong.
- The policy is checked first. A broken policy stops the restart before anything is stopped.
- Every container is replaced and `dw restart` waits until every service is healthy, as `dw up` does.
- If daywarden was not running, `dw restart` starts it, the same as `dw up`.

## UC6 - Check an edit without applying it

- The parent edits the policy and runs `dw check` before deciding when to apply it.
- `dw check` reports errors, or reports the summary of the policy it would load. It changes nothing, whether daywarden
  is running or not.
- `dw up` runs the same check, so a broken policy cannot start daywarden into a crash loop.

# Acceptance Criteria

## dw check

- [ ] `dw check` takes no arguments. An extra argument is a usage error with status 2.
- [ ] With a valid policy, `dw check` prints the summary described under `dw reload` and exits 0. It reloads nothing,
  and no container starts, stops, or restarts.
- [ ] With errors in the policy, `dw check` prints `dw: the policy has N errors.` (`1 error` for one), then every
  error as described under "Reporting every error". It exits 1.
- [ ] `dw check` works the same with daywarden running and with daywarden stopped. With it stopped, `dw status`
  afterwards still shows every service not running.
- [ ] `dw check` refuses exactly what `dw reload` refuses and warns about exactly what `dw reload` warns about.

## Reporting every error

These apply to `dw check` and to the check in `dw reload`, `dw restart`, `dw up`, and the start at boot. Stopping at
the first error does not meet this story. A parent must be able to fix every mistake the checker can find from a
single run.

- [ ] One run lists every error the checker can find, not only the first. For example, take a policy with all of these
  mistakes at once: a misspelled top-level setting, a client group with an address that is not an IP or a hostname,
  two site groups with the same priority, a period with an illegal clock, a rule that names a rule set that does not
  exist, a quota with a negative grace, and a task with a setting its task type rejects. One `dw check` lists all
  seven, and the count line says 7.
- [ ] Errors in different items are each reported. An item is a top-level setting, a client group, a site group, a
  time window or one of its periods, a quota, a rule set or one of its rules, or a task.
- [ ] Two independent mistakes in the same item are both reported where the checker can tell them apart. For example,
  a task with an invalid timeout and an invalid question count, or a period with a bad start clock and a bad weekday,
  lists both.
- [ ] An error in an included file does not hide errors in `policy.yaml` or in other included files. Every file is
  checked, and each error names the file it is in.
- [ ] A YAML syntax error stops the checking of that file only. The checker reports the syntax error and the errors in
  every other file it could read. Includes named only by a file that does not parse cannot be found, so they are not
  checked. That is expected.
- [ ] A mistake does not cause false knock-on errors. A rule set, group, window, quota, or task that has an error still
  counts as defined, so a rule that names it does not also get a "does not exist" error.
- [ ] Every instance of a whole-policy problem is reported. Three pairs of site groups that share a priority give
  three errors. Two addresses that each appear in two client groups give two errors. A missing `entry` is reported
  alongside the other errors, not instead of them.
- [ ] Each error appears once, even when the file it is in is included from more than one place.
- [ ] Each error begins with the file path as the parent sees it on the host, relative to the daywarden directory,
  such as `config/policy.yaml:42:`, followed by the line and what is wrong. It does not show the path inside a
  container, such as `/etc/daywarden/policy.yaml`.
- [ ] Errors are listed in file order, then line order, with the files in the order the policy includes them.
- [ ] Warnings, such as a DNS name that does not resolve, are listed after the errors, under their own heading, and do
  not count as errors.
- [ ] Spelling tasks whose word lists cannot be read from the data directory are each reported, alongside every other
  error.
- [ ] When a broken policy stops the decisions or observations service at start, its log lists the same errors.

## dw up

- [ ] `dw up` checks the policy before starting anything. With an error, it prints the same message as `dw check` with
  `daywarden was not started.`, exits 1, and no service is started.
- [ ] With an error in the policy, `dw up` on a running daywarden leaves it running with the previous policy and
  starts nothing.
- [ ] Starting daywarden at boot through the user service runs the same check. A broken policy shows as a failed
  start in `dw status`, and `journalctl --user -u daywarden` shows the error.

## Same enforcement as dw down and dw up

This story adds ways to load the policy. It does not change how the policy is enforced. `dw restart` is a more
convenient, and possibly faster, `dw down && dw up`. `dw reload` has the same effect on policy enforcement as
`dw down && dw up` with the same policy, but it restarts no container. That means less downtime, and it does not apply
`.env` changes.

- [ ] For any policy change, the decisions after `dw reload` are the same as after `dw down && dw up`, except for
  differences that come from containers restarting, such as dropped connections.
- [ ] For any policy and `.env` change, `dw restart` leaves daywarden in the same state as `dw down && dw up`.
- [ ] Neither command changes the decision engine, the observations service's cut logic, or the proxy addon's
  enforcement.

## dw reload

- [ ] `dw help` lists `reload`, `restart`, and `check` with a one-line description of each.
- [ ] `dw reload` takes no arguments. An extra argument is a usage error with status 2, as for the other commands.
- [ ] With a valid policy, `dw reload` reports that the decisions and observations services are using the reloaded
  policy. It exits 0.
- [ ] `dw reload` prints the same summary the decisions service logs at start: the timezone, the task page address,
  each client group with its addresses, and each site group with its priority. A DNS name in a client group shows the
  addresses it resolved to.
- [ ] After `dw reload`, `docker ps` shows that no daywarden container restarted. Each container's uptime continues
  from before the reload.
- [ ] A change to a time window, a rule, a site group pattern, a client group address, or a quota applies to the next
  request through the proxy after `dw reload` returns.
- [ ] A change in an included file or included directory is reloaded with `policy.yaml`.
- [ ] A download or video stream that started before the reload is not dropped by the reload. It follows the existing
  rule for a policy edit: it is not disturbed until the deadline or byte ceiling recorded at its approval is reached.
  At that point it is walked again with the reloaded policy, using the client group and site group from its approval,
  and is cut only if that walk no longer allows it. A reload does not make a running transfer walk the rules early.
- [ ] A reload that changes a quota's limit applies the new limit to today's usage. The usage page shows the usage
  recorded before the reload against the new limit.
- [ ] A reload that changes the bucket length closes the buckets that are open at the moment of the reload, as a
  restart with the new length would. Usage recorded before the reload is not lost.
- [ ] A reload that changes the household timezone moves the household day and the clock in the decisions log to the
  new zone from the next request.
- [ ] A signed-in parent stays signed in across a reload. The usage page and the attempts pages keep working without
  signing in again.
- [ ] A quiz attempt in progress at the reload keeps its questions, words, deadlines, and tries. It can be finished,
  and it is scored and recorded as it would be after `dw down && dw up` with the same change. Its page does not lose
  its connection.
- [ ] After a reload, the next attempt that starts uses the reloaded task settings. A task added by the reload can be
  started. A task removed by the reload is not offered.
- [ ] A change to `hostname` in the policy changes the task page addresses the proxy redirects to from the next
  request.
- [ ] Running `dw reload` twice in a row with no change in between succeeds both times and changes nothing a user can
  see.
- [ ] No web address can trigger a reload. A request from the child's computer, through the proxy or straight to the
  policy port, cannot cause one.

## dw reload with a broken policy

- [ ] When the policy has errors, `dw reload` prints `dw: the policy has N errors. Nothing was reloaded.`, then every
  error as described under "Reporting every error". It exits 1.
- [ ] After a refused reload, the proxy still decides with the previous policy, and no container has restarted.
- [ ] The errors that `dw reload` refuses include at least: YAML that does not parse, a missing `entry`, a rule set
  that names a rule set that does not exist, two site groups with the same priority, the same address in two client
  groups, an include that does not exist, and a task whose settings the task type rejects.
- [ ] A spelling task whose word list cannot be read from the data directory is refused, as it is at start.
- [ ] A client group DNS name that does not resolve is a warning, not an error. `dw reload` prints the warning and
  reloads. The group keeps the addresses that name had before the reload.
- [ ] A missing `config/policy.yaml` is refused. It does not leave daywarden with no policy.

## dw reload and changes that need dw restart

- [ ] When `.env` or `docker-compose.yml` has changed in a way that would change a container, `dw reload` still
  reloads the policy. It then prints a warning that those changes have not been applied, names the services still
  running with the old settings, and says that `dw restart` applies them. It does not restart or recreate any
  container, and it exits 0.
- [ ] After that warning, the old `.env` settings stay in force. For example, the proxy still listens on the old
  `PROXY_PORT` until `dw restart`.
- [ ] When `.env` and `docker-compose.yml` are unchanged, `dw reload` says nothing about a restart.

## dw reload while daywarden is not running

- [ ] With daywarden stopped, `dw reload` checks the policy and reports any errors. It then says that daywarden is not
  running, so nothing was reloaded, and that `dw up` will use this policy. It exits 1 and starts no service.

## dw restart

- [ ] `dw restart` takes no arguments. An extra argument is a usage error with status 2.
- [ ] `dw restart` checks the policy before stopping anything. With an error, it prints the same message as
  `dw reload` with `Nothing was restarted.`, and exits 1. The running daywarden keeps running with the previous policy.
- [ ] With a valid policy and daywarden running, `dw restart` replaces every daywarden container, waits until every
  service is healthy, and prints `daywarden restarted.`. `docker ps` shows that each container is new.
- [ ] `dw restart` applies a changed `.env`, such as a new `PROXY_PORT` or `PARENT_NAMES`, and a newly installed image.
- [ ] With daywarden stopped, `dw restart` starts it the same way `dw up` does and says that daywarden was not
  running.
- [ ] With one service stopped by hand, `dw restart` brings every service up healthy.
- [ ] A service that does not become healthy is reported the same way `dw up` reports it: the service names and the
  last lines the first failed service logged. `dw restart` exits 1.
- [ ] With daywarden enabled at boot, `dw status` after `dw restart` shows that the last start through the user service
  did not fail. `dw down` afterwards still stops every container.
- [ ] After `dw restart`, parent accounts, the CA, the parent certificate, usage, and task attempts are all still
  there, as after `dw down` and `dw up`. Whether a parent stays signed in across `dw restart` is not part of this
  story. It is whatever `dw down` and `dw up` do.
- [ ] `dw restart` is no slower than `dw down` followed by `dw up` on the same machine.

## Documentation

- [ ] `README.md` and `docs/hierarchical-policy.md` say that a policy change needs `dw reload`, and say what a reload
  keeps: attempts in progress, flows already running, sessions, and usage. They also say that `bypass.txt` and the
  spelling clips are read when used, so they need neither a reload nor a restart, and which changes need
  `dw restart`.

# Notes

## Proposed design

**Check.** A new `python -m policy.check` loads `POLICY_FILE` with the same `hierarchy.load` the services use,
including task data, and passes in no previous policy. It prints either the summary or every error, then the
warnings, and exits 0 or 1. Running it in the image ensures the check uses the same code as the running services. With
the stack up, `dw` runs it with `docker compose exec -T decisions`. With the stack down, `dw` runs it with
`docker compose run --rm --no-deps -T decisions`, which publishes no ports and starts nothing else.

**Collecting errors.** Today the loader raises `ConfigError` at the first problem. `hierarchy.py` has about 110
raise sites, and the task type validators in `tasks.py`, `spelling.py`, `arithmetic.py`, `parts_of_speech.py`, and
`skip_counting.py` have about 110 more. Rewriting each raise site is not the intent. The loader collects errors at
item boundaries instead:

- `_Build` gains an error list. Each item is parsed inside its own `try`. A `ConfigError` or validator `ValueError` is
  recorded with the item's file and line, and the loader moves on to the next item.
- An item that failed is still registered under its name, marked as broken, so references to it resolve and do not
  add knock-on errors. The whole-policy checks, such as duplicate priorities, duplicate addresses, unknown rule sets,
  and a missing `entry`, run on whatever did parse, and record every instance.
- Where an item has independent fields, such as a task's settings or a period's clocks and weekdays, its parser checks
  each field and records each failure. Validators that can stop at a field boundary should do so.
- Files are read in include order. A YAML syntax error is recorded for that file, and the other files are still read.
  PyYAML cannot carry on past a syntax error, and writing a more forgiving parser is not part of this story.
- After everything is read, a non-empty list raises one `ConfigError` that carries every error, sorted as the
  acceptance criteria describe. `str()` of it joins them one per line, so the service start log and existing tests
  that match on one message still work.
- The container paths are mapped back to host paths for display. `dw` passes the host directory that is mounted at
  `/etc/daywarden`, and the checker rewrites that prefix.

The tests for this must use policies with several mistakes and assert that each mistake is listed. A test that sees
only the first error passing is not enough.

**Apply.** Both services keep the loaded policy in one holder that is swapped as a whole, so a request sees either
the old policy or the new one and never a mix:

- Decisions: `create_app` closes over `hierarchy_policy`, `clock`, and `ledger`. These move into a state object that
  every route reads at the start of a request. The reload re-runs `hierarchy.load(previous=current)`, then
  `install_length(..., clock.local())`, then swaps the holder. It runs on the event-loop thread, because the SQLite
  connection belongs to that thread.
- Observations: `_hierarchical` returns the policy that `listen` captures. That also moves into a holder. The
  threaded server reads it once per report.
- Each service re-reads the file itself, so a file edited between the check and the apply is checked again. A
  service that fails the second load keeps its previous policy, and `dw reload` reports which service did not reload
  and exits 1.

**Trigger.** The proposed trigger is a `POST /v1/reload` on the plain HTTP listener of each service. Each service
accepts it only from `127.0.0.1` and returns 404 to any other peer. `dw reload` runs a small client inside each
container with `docker compose exec`. The plain HTTP port is reachable from the proxy container across the compose
network. The proxy resolves `decisions` on that network, so a child's request for `http://decisions:8090/...` reaches
the service whenever the policy allows that site. That is why the loopback check is required, not optional. The alternative is SIGHUP through `docker compose kill -s HUP`. It was not
chosen because uvicorn has no SIGHUP handler and Python's default action ends the process. One missed handler
would turn a reload into a crash, and a signal cannot report success or failure to `dw`.

**Changes that need a restart.** `docker compose config --hash '*'` gives the configuration hash of each service.
Compose stores the hash of each running container in the `com.docker.compose.config-hash` label. Any service whose
two hashes differ needs `dw restart`.

**Restart.** `docker compose up -d --force-recreate --remove-orphans --wait --wait-timeout 180` replaces every
container in dependency order in one Compose call. It applies `.env` and image changes, starts a stopped stack, and
does not take down the network. That makes it the expected replacement for `down` and `up`. `docker compose restart`
is not used, because it ignores `.env` changes and does not wait for health. While enabled at boot, `dw restart` then
runs `systemctl --user start`, as `dw up` does, so the user service shows active. If the automated test shows
force-recreate is not faster than `down` and `up`, fall back to calling `cmd_down` and `cmd_up` with the policy check
in front.

**Check in dw up and at boot.** `dw_compose_up` in `daywarden-lib.sh` is shared by `dw up`, `dw restart`, and
`daywarden-service start`, so the check goes there, in front of the Compose call. At boot it runs after the wait for
Docker.

## Order

S017 comes first. It removes the second policy path from `create_app` and the observations service, so this story
makes one path reloadable.

## What is already live and needs no reload

- `config/bypass.txt` is read by the proxy on every request.
- Spelling clips and word lists in the data directory are read when a quiz run starts.

## Out of scope

- Reloading `.env` without new containers. Ports, mounts, and environment variables are fixed when a container is
  created.
- Any change to how the policy is enforced. That includes making live transfers walk the rules again, or classify
  again, on their next observation after a reload. `docs/hierarchical-policy.md` already lists that as left for later.
  The observations service only swaps in the reloaded policy for the re-walks it already does.
- Reloading automatically when the file changes. S007.2, the policy editor, would call the same reload after saving.
- Recovering from a YAML syntax error inside the same file. That would need a parser of our own.

## Decided in refinement

- `dw restart` checks the policy before stopping anything.
- `dw check` is its own command, and `dw up` checks the policy first too.
- `dw reload` with daywarden stopped exits 1, because nothing was reloaded.
- When `.env` or `docker-compose.yml` has changed, `dw reload` only warns that `dw restart` is needed. It never
  recreates a container itself, because recreating the proxy drops every open connection.
- The checker reports every error it can find in one run. It does not stop at the first.
- Scope is loading, reloading, restarting, and checking the policy. Enforcement behaves after `dw reload` as after
  `dw down && dw up`, and running transfers keep the existing deadline and ceiling rule.
- `dw reload` must keep parents signed in. `dw restart` neither must keep them signed in nor must sign them out.

## Sizing

21 points. The parts are:

- About 8 points for collecting every error: the item-level collection in the loader, the field-level checks in the
  task validators, the host path mapping, and tests with several mistakes per policy.
- About 6 points for the live reload, with S017 done first: moving the decisions and observations state into
  swappable holders, the loopback reload endpoint, `dw reload` with the config-hash comparison, and Compose-backed
  tests. Those tests show a reload under an open stream and a quiz in progress, and a refused reload leaving the old
  decision in force. Without S017 it is about 8, because the second policy branch in both services would also have to
  be made reloadable or refused.
- About 5 points for `dw check`, `dw restart`, the check in `dw up` and at boot, and their host-fake cases in
  `test_dw.py`.

The parts add up to about 19, which rounds to 21 on the Fibonacci scale. With about 60 acceptance criteria, it is over the guide of about 50 for one story, and above the S006 reference
work of 14 points and 39 criteria. It could be split into an epic. S016.1 would check the policy and report every
error, through `dw check` and the check in `dw up` and at boot. S016.2 would add `dw reload` and `dw restart`.
S016.1 can be accepted on its own through `dw check` and `dw up`, and S016.2 builds on it without rewriting it.

# Implementation

## Files Added/Changed/Removed

Added:

- `policy/problems.py`: `Problems`, a `ValueError` that carries several problems, and `Collector`, which checks
  independent parts and raises them together.
- `policy/check.py`: `python -m policy.check`. It loads the policy as the decisions service does and prints the summary,
  or a count line, every error, and the warnings. It also holds the summary lines the decisions service logs, and the
  mapping from `/etc/daywarden` to the host directory.
- `policy/reload.py`: `python -m policy.reload`. `dw reload` runs it inside each container to ask that service to
  reload.
- `tests/test_policy_check.py`: policies with several mistakes, each of which must be listed, and the check command.
- `tests/test_reload.py`: the decisions and observations reload endpoints in-process. Covers decisions, the loopback
  rule, refusals, includes, timezone, hostname, quota, bucket length, sessions, a quiz in progress, and a running transfer.
- `tests/test_reload_stack.py`: the real `bin/dw` against its own Compose project. Covers `dw check`, `dw reload`
  without a container restart, a refused reload, a request from the proxy container, the `.env` warning, and
  `dw restart` against `dw down` and `dw up`.
- `tests/test_make_targets.py`: `make reload`, `make restart`, `make check`, and `make help` on a copy of the checkout,
  against the fake `docker` from `tests/hostfakes.py`.

Changed:

- `policy/hierarchy.py`: the loader records errors per file, per item, and per field, and checks the whole policy on
  whatever parsed. A failed item still counts as defined. Errors are sorted by file in include order, then by line, and
  raised as one `ConfigError`. A client group address must be an IP address or a host name. Each rule keeps where it is
  written.
- `policy/arithmetic.py`, `policy/spelling.py`, `policy/parts_of_speech.py`, `policy/skip_counting.py`: each body field is
  checked on its own, and every problem is raised together. A parts of speech body checks each sentence on its own.
- `policy/app.py`: the policy, clock, and zone are held in one `Holder` that a reload swaps whole. Each route reads it
  once. `POST /v1/reload` is accepted only over plain HTTP from 127.0.0.1 or ::1. Any other peer gets 404. A failed
  start logs every error.
- `policy/observations.py`: the policy is read once per report, under the report lock. The same loopback-only
  `POST /v1/reload` is added.
- `bin/dw`: adds `reload`, `restart`, and `check`. `up` checks the policy first.
- `bin/daywarden-lib.sh`: adds `dw_check_policy`, `dw_config_dir`, `dw_make_dirs`, `dw_start_checked`,
  `dw_stale_services`, which compares `docker compose config --hash` with each container's label, and
  `dw_track_with_user_service`. `dw_compose_up` checks the policy before starting.
- `bin/daywarden-service`: the start at boot checks the policy.
- `deploy/install.sh`: an upgrade of a running daywarden runs `dw restart` instead of `dw down` and `dw up`.
- `docker-compose.yml`: comment only.
- `Makefile`: `make reload`, `make restart`, and `make check` run `bin/dw` on the checkout, for the local dev stack.
  `make help` lists every target with the description written on its line.
- `README.md`, `docs/hierarchical-policy.md`: how to apply an edit, what a reload keeps, what needs `dw restart`, and
  how errors are reported. The README also describes the new make targets.
- `tests/hostfakes.py`, `tests/test_dw.py`, `tests/test_install.py`: the fake `docker compose` answers `run`,
  `exec` of the check and the reload, and `config --hash`. Adds host-fake cases for every new `dw` path.

Removed: nothing.

## Change Summary

The policy loader no longer stops at the first error. It reads every file, parses each item, and checks each field
of a period, a task, a quota, and a site group on its own. A failed item is still registered by name, so references to
it raise no knock-on errors. The whole-policy checks report every instance: each duplicate priority, each shared
address, each `evaluate` cycle, each unknown reference, and a missing `entry`. A YAML syntax error stops only its own
file. The errors come back sorted and de-duplicated in one `ConfigError`. `str()` of it lists them one per line, so
existing callers and tests still work. The four task-type validators raise every field problem together. The loader
places each one at the line of the body field it names.

`python -m policy.check` runs in the policy image. `dw` runs it with `docker compose exec` in the running decisions
container, or with `docker compose --progress quiet run --rm --no-deps -T --quiet-build decisions` when daywarden is
down or about to start. `dw` passes `--host-dir`, the configuration directory as written from the daywarden directory,
so errors read `config/policy.yaml:42:5: ...`.

Each service keeps its policy in one holder that a reload replaces in one assignment. The decisions service reloads on
its event-loop thread. It re-reads the file, installs the bucket length at the current household time, and rebuilds
the household clock from the new timezone. The observations service swaps under the lock its reports already take.
Neither changes enforcement. Running transfers keep their recorded deadline and ceiling, and the re-walk at that
point uses the swapped policy. `dw reload` checks first, then reloads decisions, then observations. Each service loads
the file again itself, so a file changed between the steps is checked again. It then compares Compose config hashes
and names the services still running with old settings.

`dw restart` checks the policy, then runs `docker compose down --remove-orphans` and starts the stack, waiting for
health as `dw up` does. The proposed `up --force-recreate` was measured at 24.2 s against 21.8 s for `dw down` and
`dw up`. Following the fallback in the design, a restart is down and up with the check run once at the front. The
end-to-end test asserts that a restart is no slower than `dw down` and `dw up`, with 2 seconds of tolerance for timing
noise.

On the local dev stack, `make reload`, `make restart`, and `make check` run the same `bin/dw` commands on the
checkout. Because of `pull_policy: build`, `make restart` rebuilds the policy image. `make reload` and `make check`
run inside the containers that are already up. A stack started before S016 has no `policy.check` in its image, so
it needs one `make restart` before `make reload` and `make check` work. `make help` reads the `## description` on
each target line. A test fails if a phony target has no description.

Two choices go beyond the letter of the story. An upgrade through `install.sh` now runs `dw restart`, so a policy the
new version refuses leaves the old version running. A client group address that is neither an IP address nor a host
name is now a load error. Before, it was only a DNS warning. The acceptance criteria name it as an error.

The full suite passes, including the Docker stacks: 1153 tests, with none skipped.

## Suggested Acceptance Testing

### Acceptance test cases for S016

1. With daywarden running and a child online, edit `config/policy.yaml` to allow a site that is denied, or to move a
   time window. Run `dw reload`. It prints the summary (timezone, task page address, each client group with its
   addresses, each site group with its priority), then
   `The decisions and observations services are using the reloaded policy.`, and exits 0. The next request through the
   proxy is decided by the new policy. `docker ps` shows the same uptime for every daywarden container as before.
2. Put these mistakes into the policy at once: a misspelled top-level setting such as `timezon:`, a client group
   address such as `"not an address"`, two site groups with the same priority, a period with `start: "25:00"`, a rule
   with `evaluate` of a rule set that does not exist, a quota with `time_grace: -5m`, and an arithmetic task with
   `correct_answers_required: 0`. Run `dw reload`. It prints `dw: the policy has 7 errors. Nothing was reloaded.` and
   seven lines, each starting `config/policy.yaml:<line>:<column>:`, in line order. It exits 1. The proxy still
   decides with the old policy. Fix all seven in one pass and run `dw reload` again. It succeeds.
3. Start an arithmetic quiz on a child's computer and answer one question. Change that task's
   `correct_answers_required`, add a new task, remove another, and run `dw reload`. The quiz page keeps working.
   Finishing it scores against the old count. The next attempt uses the new count. The new task can be opened, and
   the removed one is no longer offered.
4. Start a long download or video that a quota allows. Change the policy so that site is denied, and run `dw reload`.
   The transfer keeps running until its recorded deadline or byte ceiling. It is then cut, or kept if the new policy
   still allows it.
5. Sign in to `https://<host>:<POLICY_PORT>/usage`, run `dw reload`, then refresh `/usage` and `/attempts`. They open
   without signing in again.
6. Stop daywarden with `dw down`, break the policy, and run `dw up`. It prints
   `dw: the policy has N errors. daywarden was not started.` and every error, then exits 1. `dw status` shows every
   service not running. Start daywarden with a good policy, break it again, and run `dw up`. It refuses the same way,
   and daywarden keeps running with the previous policy.
7. With daywarden running, change `PROXY_PORT` or `PARENT_NAMES` in `.env` and run `dw reload`. It reloads, then warns
   that `.env` or `docker-compose.yml` has changed, names the services still running with the old settings, and
   says to run `dw restart`. It exits 0. The proxy still listens on the old port.
8. Run `dw restart`. It prints `daywarden restarted.` after every service is healthy. `docker ps` shows new
   containers, and the proxy now listens on the new `PROXY_PORT`. Parent accounts, the CA, usage, and attempts are
   all still there.
9. Break the policy and run `dw restart`. It prints `dw: the policy has N errors. Nothing was restarted.`, exits 1,
   and the running containers keep running.
10. Run `dw down`, then `dw restart`. It starts daywarden and says it was not running. Stop one service with
    `docker compose stop observations` and run `dw restart`. Every service comes back healthy.
11. With daywarden stopped, run `dw check`. It prints the summary and exits 0, or prints every error and exits 1.
    `dw status` afterwards still shows every service not running. Run `dw check` again with daywarden running. It
    gives the same answer, and no container restarts.
12. With daywarden stopped, run `dw reload`. It checks the policy, says
    `daywarden is not running, so nothing was reloaded. dw up will use this policy.`, exits 1, and starts nothing.
13. With daywarden enabled at boot, put an error in the policy and run `systemctl --user restart daywarden`, or reboot.
    `dw status` shows the last start through the user service failed, and `journalctl --user -u daywarden` shows the
    count line and every error. Fix the policy and run `dw restart`. `dw status` then shows no failure, and `dw down`
    stops every container.
14. Add `include: [extra]` with a file in `config/extra/` that defines a site group. Run `dw reload`. Requests to that
    site are classified into the new group. Edit only the included file and reload again. The change applies.
15. Put an error in an included file and another in `policy.yaml`. `dw check` lists both, each with its own file.
    Make one included file a YAML syntax error. `dw check` reports the syntax error and the errors in every other file.
16. Raise a quota's limit after some usage today and run `dw reload`. The usage page shows today's usage against the
    new limit, and a site that was over the limit is allowed again.
17. Change `timezone` and run `dw reload`. The next lines in `docker compose logs decisions` use the new zone.
    Change `hostname` and reload. The next redirect to the task pages uses the new host.
18. Add a client group address that is a DNS name that does not resolve. `dw reload` lists it under `Warnings:` and
    still reloads. A name that resolved before keeps its addresses.
19. Move `config/policy.yaml` away and run `dw reload`. It is refused with
    `config/policy.yaml: the policy file does not exist`, and the old policy stays in force. Put it back.
20. Point a spelling task's `current_dir` at a directory that does not exist under the data directory. `dw reload`
    and `dw check` list it beside any other errors.
21. Run `dw reload` twice with no change in between. Both succeed, and nothing a user can see changes.
22. From a child's computer, through the proxy, POST to `http://decisions:8090/v1/reload`, and POST to
    `https://<host>:<POLICY_PORT>/v1/reload`. Neither reloads anything. `docker compose logs decisions` shows no
    `reloaded` line.
23. Change `bucket_length` and run `dw reload`. Usage recorded before the reload is still on the usage page, and new
    buckets use the new length.
24. Run `dw help`. It lists `reload`, `restart`, and `check`, each with a one-line description. Run `dw reload now`,
    `dw restart now`, and `dw check now`. Each is a usage error with status 2.
25. Upgrade a running daywarden with a newer package's `./install.sh` and answer `y`. It runs `dw restart`, and
    daywarden comes back healthy on the new version.
26. Read the "Policy file" and "Running it with dw" sections of `README.md`, and "Applying an edit" in
    `docs/hierarchical-policy.md`. They say a policy change needs `dw reload`, what a reload keeps, that
    `bypass.txt` and spelling clips need neither a reload nor a restart, and that `.env` changes need `dw restart`.
27. In the repository, with the local stack up through `make up`, run `make restart`. It rebuilds the policy image,
    prints `daywarden restarted.` once every service is healthy, and `docker ps` shows new containers. With the stack
    down, `make restart` starts it and says it was not running.
28. Edit `config/policy.yaml` and run `make reload`. It prints the summary and
    `The decisions and observations services are using the reloaded policy.`, and `docker ps` shows no container
    restarted. Break the policy and run `make reload` and `make restart`. Each lists every error, ends with
    `Nothing was reloaded.` or `Nothing was restarted.`, and make reports the failure. The stack keeps running.
29. Run `make check` with the stack up and with it down. It gives the same answer as `bin/dw check` and starts
    nothing.
30. Run `make help`. It lists every target, including `reload`, `restart`, `check`, and `help`, each with a one-line
    description. Plain `make` still starts the stack, as `make up` does.
