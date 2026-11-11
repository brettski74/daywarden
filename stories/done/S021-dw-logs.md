Ticket: S021
Title: Show daywarden's logs with dw logs
Status: Done
Story Points: 8
Last Updated: 2026-11-08 15:20:00
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

- [x] `dw logs` shows the last 100 lines of each of the four services: decisions, observations, proxy, and autoconfig.
  Each line is prefixed with the service name, as `docker compose logs` does.
- [x] `dw logs` works from any directory, including through a symlink in `~/bin`, and acts on the same daywarden as
  the other `dw` commands.
- [x] `dw logs <service> [<service> ...]` shows only the named services. An unknown name is a usage error with status
  2 that lists the valid names, including `boot`.
- [x] `dw logs` works with a port mistake in `.env`, such as a bad `PORT_BASE`, because it opens no port.
- [x] When the Docker daemon is not answering, `dw logs` says so and exits 1.

## Options

The option names match `docker compose logs`, so a parent who knows one knows the other.

- [x] `-f` or `--follow` keeps printing new lines as they are logged, until the parent presses Ctrl-C. Ctrl-C ends
  `dw logs` without an error message.
- [x] `-n N` or `--tail N` shows the last N lines of each service instead of 100. `--tail all` shows everything. A
  value that is neither a whole number nor `all` is a usage error with status 2.
- [x] `--since WHEN` shows only lines logged since then. WHEN is a duration such as `10m` or `2h`, or a date and time
  such as `2026-11-08T13:00`. With `--since` and no `--tail`, every line since then is shown, not only the last 100.
  An invalid WHEN gives an error that names the value and exits non-zero. It does not fall back to showing everything.
- [x] `-t` or `--timestamps` puts the time each line was logged in front of it.
- [x] Options and service names can be given in any order, such as `dw logs decisions -f` and
  `dw logs -f decisions`.
- [x] An unknown option is a usage error with status 2.
- [x] `dw logs -h` or `dw logs --help` lists the options and the service names, and exits 0.

## The start-at-boot log

- [x] `dw logs boot` shows what the daywarden user service logged, the same lines as
  `journalctl --user -u daywarden`.
- [x] `-f`, `-n`/`--tail`, and `--since` work with `boot` the same way they do for the services. Its lines always
  carry a time, so `-t` changes nothing.
- [x] `boot` cannot be combined with other service names. That is a usage error with status 2 that says to run
  `dw logs boot` on its own.
- [x] `dw logs` with no names does not include `boot`.
- [x] When the user service has logged nothing, such as when daywarden has never been enabled at boot, `dw logs boot`
  says so and mentions `dw enable`.
- [x] When this user's systemd manager cannot be reached, as in a `su` session, `dw logs boot` says the boot log
  cannot be read and gives the same advice `dw enable` gives.
- [x] `dw status` and the failed-start message from `dw up` point to `dw logs boot` instead of
  `journalctl --user -u daywarden`.

## When daywarden is stopped

- [x] When daywarden's containers exist but are stopped, such as after `dw down --keep`, or after a `dw up` in
  which a service crashed, `dw logs` shows what they logged.
- [x] With `-f` and every container stopped, `dw logs` shows what they logged and then returns. It does not wait
  forever for lines that cannot come.
- [x] When daywarden has no containers, such as after `dw down`, `dw logs` says there is nothing to show because
  `dw down`, `dw restart`, and a reboot remove the containers and what they logged, and mentions `--keep`. It
  exits 1.
- [x] When some named services have a container and others do not, `dw logs` shows the ones that do and names the ones
  that do not.

## Keeping the containers with --keep

- [x] `dw down --keep` stops every daywarden container without removing it, stops the user service as `dw down`
  does, and says that the containers were kept, so `dw logs` can still show what they logged, and that `dw down`
  removes them.
- [x] A kept container keeps everything in it, not only its log. For example, the decisions container still holds
  `/tmp/decisions.jsonl` with the decisions from before the stop, and the next `dw up` carries on appending to it.
- [x] After `dw down --keep`, `dw status` shows every service not running, and `dw logs` shows what each service
  logged before the stop.
- [x] `dw down` after `dw down --keep` removes the kept containers, as `dw down` always does.
- [x] `dw up` after `dw down --keep` starts daywarden with the policy checked first, as usual. A service whose
  settings did not change keeps its earlier lines, so `dw logs` shows the lines from before the stop followed by the
  new ones.
- [x] `dw restart --keep` checks the policy before stopping anything, as `dw restart` does. It then stops every
  container, starts daywarden again, waits until every service is healthy, and prints `daywarden restarted.`.
- [x] After `dw restart --keep`, `dw logs` shows the lines each service logged before the restart, followed by
  the new ones.
- [x] `dw restart --keep` still applies a changed `.env` and a newly installed image. A service that had to be
  recreated for that loses its earlier lines, and `dw restart --keep` names each such service, saying what it
  logged before the restart is gone.
- [x] `dw restart --keep` on a stopped daywarden starts it, as `dw restart` does.
- [x] Any argument to `dw down` or `dw restart` other than `--keep` is a usage error with status 2.
- [x] The shutdown at reboot, through the user service, still removes the containers. That is unchanged by this story.

## The decision log line

- [x] Each decision line in `dw logs decisions` says what was decided, right after `decision`: `allow`, `deny`, or
  `redirect`. For example,
  `decision deny GET https://www.youtube.com/watch?v=abc (video) for kids at 2026-11-08T19:42:10-05:00 by evening rule 2`.
- [x] A redirect line ends with where the browser was sent, such as
  `... by evening rule 2 to https://garden:8084/tasks?return=...`.
- [x] A request that no rule decided is shown as `deny` with `by no rule`.
- [x] The decision is unchanged. Only the log line gains the outcome and, for a redirect, the target.

## make logs

- [x] `make logs` runs `bin/dw logs` on the checkout, for the local dev stack. `make logs ARGS="-f decisions"` passes
  the options and service names through.
- [x] `make help` lists `logs` with a one-line description.

## Help and documentation

- [x] `dw help` lists `logs` with a one-line description, and says that `down` and `restart` take `--keep`.
- [x] `docs/child-computer.md` uses `dw logs decisions` and `dw logs autoconfig` instead of `docker compose logs`.
- [x] `README.md` describes `dw logs` under "Running it with dw" and in "Decision and observation logs", including the
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

# Implementation

## Files Added/Changed/Removed

Added: nothing.

Changed:

- `bin/dw`: the new `logs` command. It parses `-f`/`--follow`, `-n`/`--tail` (also `-n5` and `--tail=5`),
  `--since` (also `--since=10m`), `-t`/`--timestamps`, bundles such as `-ft`, and `-h`/`--help`, in any order with the
  service names. It checks the names and the `--tail` value, and refuses `boot` with other names. For the services it
  checks that Docker answers, finds which services have a container, says when there is nothing to show or names the
  services with no container, and runs `docker compose logs` with `--tail 100` unless `--tail` or `--since` is given.
  `boot` runs `journalctl --user -u daywarden.service`, with `-n` as `--lines`, `--tail all` or a bare `--since` as
  `--no-tail`, a `--since` duration given a leading `-`, and the `T` of a date and time replaced by a space. Ctrl-C
  ends a follow with status 0 and no message. `down` and `restart` take `--keep`. `restart --keep` records each
  service's container ID, runs `docker compose stop`, then `up` with `--remove-orphans`, and names each service whose
  ID changed. `dw status` and the help point to `dw logs boot`, and the help lists `logs` and `--keep`.
- `bin/daywarden-lib.sh`: `dw_container_ids` lists the container of each service, running or stopped.
  `dw_start_checked` passes its arguments to `docker compose up`. The failed user-service start points to
  `dw logs boot`.
- `bin/daywarden-service`: the stop leaves the containers in place when none is running. `dw down --keep` stops the
  containers before it stops the user service, so the service's stop no longer removes them. The shutdown at reboot,
  with daywarden running, still removes them.
- `policy/app.py`: `decision_line` builds the decisions service's log line. It has the outcome after `decision`, and a
  redirect ends with ` to <location>`. The decision and the JSONL entry are unchanged.
- `Makefile`: `make logs`, with `ARGS` passed through.
- `aliases`: `logs` is `dw logs -f decisions`.
- `README.md`, `docs/child-computer.md`: `dw logs`, its options and `boot`, the outcome on the decision line, `--keep`,
  and `dw logs boot` for the start at boot.
- `tests/hostfakes.py`: a fake `journalctl`. The fake `docker compose` has `stop`, reuses a stopped container on `up`
  unless its settings changed, gives each new container a new ID, answers `ps -a -q` with no service, and shows the
  logs of several services with their prefixes. A follow can wait until Ctrl-C, as Compose and journalctl do.
  `Host.start_dw` starts `dw` in its own process group, so a test can press Ctrl-C.
- `tests/test_dw.py`: `dw logs` and its options, usage errors, help, Docker not answering, a port mistake, stopped
  containers, no containers, some services with no container, Ctrl-C, `boot` and its options, the empty journal, the
  missing user manager, `down --keep`, `restart --keep` and its recreated services, the user service's stop with kept
  containers, and the new `--keep` usage errors and boot-log messages.
- `tests/test_engine.py`: the decision line for allow, deny, a redirect with its location, and no rule, through the
  app.
- `tests/test_make_targets.py`: `make logs` with and without `ARGS`.
- `tests/test_reload_stack.py`: against a real stack, a request through the proxy shows in `dw logs decisions` with its
  outcome, `dw down --keep` keeps it, `dw logs -f` returns with every container stopped, `dw up` starts the same
  containers, and `dw restart --keep` keeps the line and `/tmp/decisions.jsonl`.

Removed: nothing.

## Change Summary

`dw logs` shows the last 100 lines of each of the four services from any directory, with the options of
`docker compose logs`. `dw logs boot` shows what the start at boot logged, and `dw status` points to it when the last
start failed. Each decision line now starts with `allow`, `deny`, or `redirect`, and a redirect line ends with where it
sent the browser, so `dw logs decisions | grep deny` lists the blocked requests.

`dw down --keep` stops daywarden without removing its containers, so `dw logs` still shows what they logged, and the
next `dw up` starts the same containers. `dw restart --keep` does the same across a restart. It still applies a changed
`.env` or a new image, and it names each service that had to be recreated for that, because what it logged is gone.
Without `--keep`, `dw down` and `dw restart` are unchanged.

One finding differs from the proposed design. Compose 5.4 does not return from `docker compose logs -f` when every
container it follows has stopped. It waits for lines that cannot come. The Compose-backed test caught this. `dw logs -f`
now leaves out `--follow` when none of the services it shows is running, says so on stderr, and returns after the lines
they logged.

## Suggested Acceptance Testing

### S021 acceptance test cases

1. With daywarden running, open a blocked site on a child's computer. Run `dw logs decisions` from your home directory.
   The site's line says `decision deny`, its site group and client group, and the rule. `dw logs decisions | grep deny`
   keeps only the blocked requests.
2. Open a site that a rule redirects to the task page. Its line in `dw logs decisions` says `decision redirect` and ends
   with ` to ` and the task page URL. A site that no rule decides shows `deny` and `by no rule`.
3. Run `dw logs -f decisions`, browse on the child's computer, and watch the lines arrive. Press Ctrl-C. `dw logs` ends
   with no error message, and `echo $?` prints 0. Do the same with `dw logs -f`, which follows all four services.
4. Run `dw down --keep`. It says the containers were kept and that `dw down` removes them. `dw status` shows every
   service not running. `dw logs` shows what each service logged, including the decision from case 1.
5. After `dw down --keep`, run `dw logs -f`. It shows the lines, says none of the services is running, and returns by
   itself.
6. Run `dw up` after `dw down --keep`. It checks the policy and starts. `dw logs decisions` shows the earlier lines,
   then the new start-up lines.
7. Run `dw restart --keep`. It prints `daywarden restarted.`. `dw logs decisions` still shows the lines from before the
   restart.
8. Change `PORT_BASE` in `.env` and run `dw restart --keep`. It names each service that was recreated, such as the
   proxy, and says what they logged before the restart is gone. A service it does not name still shows its earlier
   lines in `dw logs`. Put `PORT_BASE` back and run `dw restart`.
9. Run `dw down` after `dw down --keep`. Then `dw logs` says there is nothing to show because daywarden has no
   containers, mentions `--keep`, and exits 1. `dw restart` without `--keep` also removes what was logged.
10. Run `dw logs boot`. On a machine where daywarden was never enabled at boot, it says the user service has logged
    nothing and mentions `dw enable`. Where it was enabled, it shows the same lines as `journalctl --user -u daywarden`.
11. Run `dw logs boot` in a `su` session as the daywarden user. It says the start-at-boot log cannot be read and gives
    the same advice as `dw enable`.
12. Enable at boot with a broken `policy.yaml` and reboot, or stop Docker so the start fails. `dw status` says the last
    start failed and points to `dw logs boot`, which shows the policy errors or that Docker did not answer.
13. Run `dw logs -n 5 decisions`, `dw logs --tail all decisions`, `dw logs --since 10m`,
    `dw logs --since 2026-11-08T13:00`, and `dw logs -t proxy`. Each shows 5 lines, every line, lines from the last 10
    minutes, lines since that time, and a time in front of each line.
14. Run `dw logs boot -n 5`, `dw logs boot --since 1h`, and `dw logs -f boot`. They work as for the services. Ctrl-C ends
    the follow quietly.
15. Run `dw logs decisions -f` and `dw logs -f decisions`. Both follow the decisions.
16. Run `dw logs squid`, `dw logs boot decisions`, `dw logs -n ten`, and `dw logs --colour`. Each is a usage error with
    status 2. The first lists the names, including `boot`. The second says to run `dw logs boot` on its own.
17. Run `dw logs --since yesterday`. It names the value, shows nothing, and exits non-zero.
18. Run `dw logs -h`. It lists the options and the service names and exits 0. `dw help` lists `logs` and says `down`
    and `restart` take `--keep`.
19. Stop one service by hand with `docker compose stop observations` and then `docker compose rm -f observations` from
    the daywarden directory. `dw logs` shows the other three and says observations has no container.
    `dw logs observations` says there is nothing to show. Run `dw up` to bring it back.
20. Set `PORT_BASE=nope` in `.env`. `dw logs decisions` still works. Put it back.
21. Stop Docker. `dw logs` says the Docker daemon is not answering and exits 1.
22. Run `dw down --now` and `dw restart --keep --now`. Both are usage errors with status 2.
23. With daywarden enabled at boot and running, reboot. After the reboot, `dw logs` shows only lines from after the
    boot, because the shutdown removed the containers.
24. In the checkout, run `make logs` and `make logs ARGS="-f decisions"`. `make help` lists `logs`.
25. Read `README.md` under "Running it with dw", "Decision and observation logs", and "Start at boot", and
    `docs/child-computer.md` under "Check". They use `dw logs` and describe `--keep` and `dw logs boot`.
