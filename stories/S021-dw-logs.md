Ticket: S021
Title: Show daywarden's logs with dw logs
Status: Refined
Story Points: 8
Last Updated: 2026-11-08 14:30:00
---

# User Voice

As a parent, I want to see what daywarden has been doing with one `dw` command, without changing to the daywarden
directory and remembering the `docker compose logs` options. When a site is blocked unexpectedly or a service will not
start, the logs are the first thing I look at. When I need to stop or restart daywarden while I am still working out a
problem, I want to be able to keep what it logged.

# Use Cases

## UC1 - See why a site was blocked

- The parent runs `dw logs decisions` and sees the recent decisions, including the one for the site in question.
- Each decision line says whether the request was allowed, denied, or redirected, which client group and site group it
  was classified into, and which rule decided. A redirect also shows where it sent the browser, such as the task page.
- `dw logs decisions | grep deny` narrows the list to the blocked requests.

## UC2 - Watch while testing

- The parent runs `dw logs -f decisions`, browses on a child's computer, and watches the decisions arrive.
- `dw logs -f` with no service names watches every service at once.

## UC3 - A service will not start

- `dw up` or `dw status` shows a service is not healthy. The parent runs `dw logs` for that service and sees why.

## UC4 - Start at boot failed

- `dw status` says the last start through the user service failed, and points to `dw logs boot`.
- `dw logs boot` shows what the start at boot logged, such as the policy errors or Docker not answering.

## UC5 - Keep the containers, and their logs, across a stop or restart

- The parent is part-way through working out why a site was blocked and needs to stop daywarden, or apply a `.env`
  change with a restart.
- `dw down --keep` stops daywarden but keeps its containers, so `dw logs` still shows what they logged.
- `dw restart --keep` restarts daywarden and keeps what each service logged before the restart, except for a
  service that has to be recreated because its settings or image changed. `dw` names any such service.
- Without the switch, `dw down` and `dw restart` behave as they do today and remove the containers and their logs.

# Acceptance Criteria

## dw logs

- [ ] `dw logs` shows the last 100 lines of each of the four services: decisions, observations, proxy, and autoconfig.
  Each line is prefixed with the service name, as `docker compose logs` does.
- [ ] `dw logs` works from any directory, including through a symlink in `~/bin`, and acts on the same daywarden as
  the other `dw` commands.
- [ ] `dw logs <service> [<service> ...]` shows only the named services. An unknown name is a usage error with status
  2 that lists the valid names, including `boot`.
- [ ] `dw logs` works with a port mistake in `.env`, such as a bad `PORT_BASE`, because it opens no port.
- [ ] When the Docker daemon is not answering, `dw logs` says so and exits 1.

## Options

The option names match `docker compose logs`, so a parent who knows one knows the other.

- [ ] `-f` or `--follow` keeps printing new lines as they are logged, until the parent presses Ctrl-C. Ctrl-C ends
  `dw logs` without an error message.
- [ ] `-n N` or `--tail N` shows the last N lines of each service instead of 100. `--tail all` shows everything. A
  value that is neither a whole number nor `all` is a usage error with status 2.
- [ ] `--since WHEN` shows only lines logged since then. WHEN is a duration such as `10m` or `2h`, or a date and time
  such as `2026-11-08T13:00`. With `--since` and no `--tail`, every line since then is shown, not only the last 100.
  An invalid WHEN gives an error that names the value and exits non-zero. It does not fall back to showing everything.
- [ ] `-t` or `--timestamps` puts the time each line was logged in front of it.
- [ ] Options and service names can be given in any order, such as `dw logs decisions -f` and
  `dw logs -f decisions`.
- [ ] An unknown option is a usage error with status 2.
- [ ] `dw logs -h` or `dw logs --help` lists the options and the service names, and exits 0.

## The start-at-boot log

- [ ] `dw logs boot` shows what the daywarden user service logged, the same lines as
  `journalctl --user -u daywarden`.
- [ ] `-f`, `-n`/`--tail`, and `--since` work with `boot` the same way they do for the services. Its lines always
  carry a time, so `-t` changes nothing.
- [ ] `boot` cannot be combined with other service names. That is a usage error with status 2 that says to run
  `dw logs boot` on its own.
- [ ] `dw logs` with no names does not include `boot`.
- [ ] When the user service has logged nothing, such as when daywarden has never been enabled at boot, `dw logs boot`
  says so and mentions `dw enable`.
- [ ] When this user's systemd manager cannot be reached, as in a `su` session, `dw logs boot` says the boot log
  cannot be read and gives the same advice `dw enable` gives.
- [ ] `dw status` and the failed-start message from `dw up` point to `dw logs boot` instead of
  `journalctl --user -u daywarden`.

## When daywarden is stopped

- [ ] When daywarden's containers exist but are stopped, such as after `dw down --keep`, or after a `dw up` in
  which a service crashed, `dw logs` shows what they logged.
- [ ] With `-f` and every container stopped, `dw logs` shows what they logged and then returns. It does not wait
  forever for lines that cannot come.
- [ ] When daywarden has no containers, such as after `dw down`, `dw logs` says there is nothing to show because
  `dw down`, `dw restart`, and a reboot remove the containers and what they logged, and mentions `--keep`. It
  exits 1.
- [ ] When some named services have a container and others do not, `dw logs` shows the ones that do and names the ones
  that do not.

## Keeping the containers with --keep

- [ ] `dw down --keep` stops every daywarden container without removing it, stops the user service as `dw down`
  does, and says that the containers were kept, so `dw logs` can still show what they logged, and that `dw down`
  removes them.
- [ ] A kept container keeps everything in it, not only its log. For example, the decisions container still holds
  `/tmp/decisions.jsonl` with the decisions from before the stop, and the next `dw up` carries on appending to it.
- [ ] After `dw down --keep`, `dw status` shows every service not running, and `dw logs` shows what each service
  logged before the stop.
- [ ] `dw down` after `dw down --keep` removes the kept containers, as `dw down` always does.
- [ ] `dw up` after `dw down --keep` starts daywarden with the policy checked first, as usual. A service whose
  settings did not change keeps its earlier lines, so `dw logs` shows the lines from before the stop followed by the
  new ones.
- [ ] `dw restart --keep` checks the policy before stopping anything, as `dw restart` does. It then stops every
  container, starts daywarden again, waits until every service is healthy, and prints `daywarden restarted.`.
- [ ] After `dw restart --keep`, `dw logs` shows the lines each service logged before the restart, followed by
  the new ones.
- [ ] `dw restart --keep` still applies a changed `.env` and a newly installed image. A service that had to be
  recreated for that loses its earlier lines, and `dw restart --keep` names each such service, saying what it
  logged before the restart is gone.
- [ ] `dw restart --keep` on a stopped daywarden starts it, as `dw restart` does.
- [ ] Any argument to `dw down` or `dw restart` other than `--keep` is a usage error with status 2.
- [ ] The shutdown at reboot, through the user service, still removes the containers. That is unchanged by this story.

## The decision log line

- [ ] Each decision line in `dw logs decisions` says what was decided, right after `decision`: `allow`, `deny`, or
  `redirect`. For example,
  `decision deny GET https://www.youtube.com/watch?v=abc (video) for kids at 2026-11-08T19:42:10-05:00 by evening rule 2`.
- [ ] A redirect line ends with where the browser was sent, such as
  `... by evening rule 2 to https://garden:8084/tasks?return=...`.
- [ ] A request that no rule decided is shown as `deny` with `by no rule`.
- [ ] The decision is unchanged. Only the log line gains the outcome and, for a redirect, the target.

## make logs

- [ ] `make logs` runs `bin/dw logs` on the checkout, for the local dev stack. `make logs ARGS="-f decisions"` passes
  the options and service names through.
- [ ] `make help` lists `logs` with a one-line description.

## Help and documentation

- [ ] `dw help` lists `logs` with a one-line description, and says that `down` and `restart` take `--keep`.
- [ ] `docs/child-computer.md` uses `dw logs decisions` and `dw logs autoconfig` instead of `docker compose logs`.
- [ ] `README.md` describes `dw logs` under "Running it with dw" and in "Decision and observation logs", including the
  outcome on each decision line, `dw logs boot`, and that `dw down`, `dw restart`, and a reboot remove the logs unless
  `--keep` is used. The start-at-boot section points to `dw logs boot`.

# Notes

## Proposed design

**Command.** `cmd_logs` in `bin/dw` parses its own options, as the other commands do, then calls
`dw_compose logs` with the translated options and the service names. It calls `dw_prepare` but not
`dw_require_ports`. The default `--tail 100` is dropped when `--since` is given. Ctrl-C ends a follow with a trap that
exits 0 quietly. `-f` against stopped containers already returns in Compose, but it needs a test.

**Which containers exist.** `docker compose ps -a -q <service>` tells whether a service has a container, as
`dw_start_checked` already uses. With no containers at all, `dw logs` prints the "nothing to show" message instead of
calling Compose, which would print nothing.

**boot.** `journalctl --user -u daywarden` with `-f`, `-n N` and `--since`. Compose takes `--since 10m`, and journalctl
takes `--since -10m`, so a bare duration gets a leading `-`. An absolute time passes through, with the `T` replaced by
a space, because journalctl does not take the `T` form. `-n all` becomes journalctl's `--no-tail`. Check
`dw_user_manager` first. "Logged nothing" is journalctl printing `-- No entries --` or nothing, depending on version, so
check its output, not its exit status. On a machine whose journal is volatile, the user journal may be empty after a
reboot. That is expected and needs no handling beyond the "logged nothing" message.

**--keep.** `dw down --keep` runs `docker compose stop` instead of `down`. Containers have
`restart: unless-stopped`, so Docker does not restart stopped ones on its own. `dw restart --keep` runs the policy
check, `docker compose stop`, then `dw_start_checked`. `up` starts each stopped container whose settings and image are
unchanged, and recreates the others. To name the recreated services, record each service's container ID from
`docker compose ps -a -q` before the stop and compare after the start. The config hash alone does not catch an image
change. `dw restart` without the switch keeps `down --remove-orphans`. With the switch, pass `--remove-orphans` to
`up` instead.

**Decision line.** In `policy/app.py`, the line becomes
`decision <action> <method> <url> (<site group>) for <client group> at <time> by <where>`, with ` to <location>` after
a redirect. The action and location come from `trace.decision`. The JSONL entry in `/tmp/decisions.jsonl` already holds
the full decision and is unchanged.

**make logs.** `logs: ## ...` with `@bin/dw logs $(ARGS)`, following the pattern of the other `dw` targets.

**aliases.** The `logs` alias in `aliases` becomes `dw logs -f decisions`.

## Testing

- Host-fake cases in `tests/test_dw.py`, using `tests/hostfakes.py`. The fake `docker compose logs` needs to record
  its arguments and answer for several services. It also needs `stop`, which keeps the containers in `state` but marks
  them exited, and `up` needs to reuse a stopped container unless its config hash changed. A fake `journalctl` answers
  for `boot`. Cover the option translation, the usage errors, `boot` alone and combined, the user manager missing,
  no containers, some services missing, `--keep` on both commands, and the names of recreated services.
- A unit test of the decision line for allow, deny, a redirect with its location, and no rule.
- One case in a Compose-backed suite, such as `tests/test_reload_stack.py`: with a real stack, a request through the
  proxy gives a decision line with its outcome in `dw logs decisions`, `dw down --keep` followed by `dw logs`
  still shows it, and `dw restart --keep` keeps it.
- `make logs` joins the existing `tests/test_make_targets.py` cases against the fake `docker`.

## Decided in refinement

- The option names and short forms match `docker compose logs`: `-f`/`--follow`, `-n`/`--tail`, `--since`, and
  `-t`/`--timestamps`.
- The default is the last 100 lines of each service, rather than Compose's default of everything, because the decisions
  log of a container that has run for weeks is very long.
- The start-at-boot journal is included as the name `boot`, and `dw status` points to it.
- `make logs` is included for the local dev stack.
- No filter option. The decision line gains its outcome instead, so piping to `grep` finds denies, one host, or one
  client group.
- By default, `dw down` and `dw restart` keep removing the containers and their logs. `--keep` keeps the whole
  containers, so the logs stay readable through `dw logs`. The switch is named for what it keeps, the containers, not
  only the logs. Logs are not copied anywhere else.
- The switch is `--keep` on `dw down` and `dw restart`, rather than a separate `dw stop` command that mirrors
  `docker compose stop`. `dw restart` needs the switch too, and one switch on both commands is easier to remember.

## Out of scope

- Keeping the logs across a reboot. The shutdown through the user service still runs `docker compose down`. A later
  story could add a `.env` setting that makes the shutdown keep the containers too.
- Copying logs into the data directory, or keeping them after the containers are removed.
- Limiting how large the Docker logs grow, such as a `logging:` section with `max-size` in `docker-compose.yml`.
  Containers kept with `--keep`, or running for weeks, keep every line until they are removed. This is worth its
  own small story.
- Merging the services' lines into one time order. `docker compose logs` interleaves services as it reads them. `-t`
  shows the time of each line.
- Any change to what the proxy logs.

## Sizing

8 points. The parts are:

- About 3 points for `dw logs` itself: option parsing and translation, the usage errors, the "nothing to show" cases,
  `make logs`, the help text, and the documentation.
- About 2 points for `boot`: the journalctl translation, the empty and unreachable cases, and pointing `dw status` at it.
- About 2 points for `--keep` on `dw down` and `dw restart`, including naming recreated services, and the fake
  `docker compose stop` and reuse in `tests/hostfakes.py`.
- About 1 point for the outcome and redirect target on the decision line, and the Compose-backed case.

That is well under the S006 reference of 14 points and 39 acceptance criteria. With 43 acceptance criteria, many
of them small option and usage checks, it stays one story.
