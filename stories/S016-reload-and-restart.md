Ticket: S016
Title: Reload the configuration and restart daywarden with dw
Status: Draft
Story Points: 21
Last Updated: 2026-11-06 22:47:00
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
