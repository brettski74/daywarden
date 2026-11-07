Ticket: S017
Title: Remove the old policy engine
Status: Done
Story Points: 8
Last Updated: 2026-11-06 23:25:00
---

# User Voice

As the maintainer, I want the YAML policy to be the only policy daywarden has ever appeared to have. A person reading
the code, the tests, the database schema, or the documentation should find one policy format, one engine, and one
usage ledger. They should have no reason to suspect another existed unless they read the git history.

# Use Cases

## UC1 - A new reader finds one policy

- Someone new to the code reads `policy/`, `proxy/`, `tests/`, the compose file, the database schema, the README, and
  `docs/`. Nothing there names, describes, or hints at another policy format, another rule engine, another usage
  ledger, or the tables they used.

## UC2 - The household starts on fresh volumes

- The parent stops the running stack with `docker compose down -v`, which removes the `policy-data` volume, installs
  the new build, and starts it with `dw up`.
- The CA and the data directory are bind mounts on the host, so they are kept. The children's computers keep trusting
  the proxy, and the spelling recordings are still there.
- The database is new. The parent adds the parent accounts again with `add-parent`. Usage, attempts, and sessions
  start empty.

## UC3 - Only a YAML policy is accepted

- `POLICY_FILE` points at a YAML policy, as it does by default.
- Any other path is a load error that names the file. There is no fallback to another engine.

## UC4 - The proxy tests keep their full coverage

- The proxy addon tests still check every decision document the proxy has to handle: allow, deny, redirect, and the
  malformed documents the rule engine never produces.
- They get those documents from a stub decision service that exists only in the tests, not from a switch in the
  production decisions service.

# Acceptance Criteria

## The running service

- [ ] After `docker compose down -v` and `dw up` with the household `config/policy.yaml`, every service is healthy.
- [ ] Decisions through the proxy match the household policy for an allowed site, a denied site, and a site
  redirected to the task pages.
- [ ] A parent account added with `add-parent` signs in. The usage page records new usage. A task attempt is recorded
  and listed on the attempts page.
- [ ] The CA kept across `down -v` is still the one the proxy uses. A child's computer that trusted it before still
  loads HTTPS pages through the proxy without a certificate warning.
- [ ] `dw down` and `dw up` after that keep the accounts, usage, and attempts, as before.
- [ ] A `POLICY_FILE` that does not end in `.yaml` or `.yml` stops the decisions and observations services at start
  with an error that names the file and says the policy must be YAML. It does not fall back to anything.
- [ ] `docker compose config` shows neither `DECISION_FILE` nor `DECISION_STUB` on any service.
- [ ] The decisions service log at start shows only the policy summary.

## What is removed

- [ ] The old policy loader, rule engine, site group and client directory classes, the single-file decision stub,
  the old one-client usage page, the old observation ledger, and every `PolicyStore` method that read or wrote the old
  engine's tables are deleted, along with any code only they use.
- [ ] Helpers the YAML policy still uses stay, such as address normalization and DNS resolution, the bucket placement
  and day-length checks, the decision request parsing and the decision log, and the shared report formatting.
- [ ] The database schema creates only the tables daywarden uses. The schema statements and migrations that created
  the old engine's tables are gone. There is no code that looks for those tables or drops them.
- [ ] The tests that only covered the old engine are deleted. A test of live behaviour that happened to use the old
  engine, such as parent sign-in, the policy service stack, or a DNS-named client, is moved to a YAML policy so the
  behaviour stays covered.

## No trace left

- [ ] Searching the repository for `toml`, ignoring case, finds nothing outside `stories/done/`,
  `implementation_plan.md`, and `.git`.
- [ ] No code, test, fixture, comment, docstring, compose comment, schema statement, or document outside those places
  names or describes another policy format, another engine, another ledger, or the old engine's tables. Wording that
  only makes sense beside the old engine is rewritten, such as "old", "older", "previous engine", "still", "the YAML
  path", or "a TOML path is".
- [ ] Names that only make sense beside the old engine are renamed for what they are. `respond_hierarchy` becomes the
  usage page's `respond`. `_hierarchical` in the observations service is named for loading the policy. `yaml_mode`
  and its branches are gone. `hierarchy.py`, `hierarchy_settings`, and the "hierarchical policy" document keep their
  names, because they describe the model's nested rule sets, not a contrast with another model.

## The proxy tests

- [ ] The proxy addon tests in `test_enforce_decisions.py`, `test_report_observations.py`, and
  `test_child_computer.py` use a test-only stub decision service in place of the decisions service. A test still
  chooses the next decision document, including malformed ones.
- [ ] Every proxy behaviour those tests covered before is still covered: allow, deny, redirect, an unrecognized
  document, an unavailable decision service, bypass, and the observation reports.
- [ ] The full test suite passes.

# Notes

## What the old engine is

- **The switch.** `policy/app.py` and `policy/observations.py` choose the old engine when `POLICY_FILE` does not end
  in `.yaml` or `.yml`. That branch, `_announce_stored`, the old `/usage` page branch, and the old observation
  `record` path in `observations.py` go.
- **Its modules.** `policy/config.py` (the loader, the only user of `tomllib`), `policy/rules.py`,
  `policy/groups.py`, the `Client` and `ClientDirectory` parts of `policy/clients.py`, `context_for`, `decide`,
  `answer`, `answer_from_store`, `completed_today`, `consumed_today`, `observed_today`, and `household_decision` in
  `policy/decisions.py`, and `load_report`, `respond`, and the helpers only they use in `policy/report.py`. Check every
  symbol for a remaining caller before deleting it. `normalize_ip`, `resolve_address`, `place`, `require_day_length`,
  `parse_request`, `log_entry`, `DecisionLog`, `parse_form`, and the `format_*` helpers are known to be shared.
- **Its storage.** Every `PolicyStore` method that reads or writes data serves only the old engine: `timezone`,
  `clients`, `revision_task`, `groups`, `task_completions`, `set_task_completions`, `bucket_length`, `bucket_for`,
  `bucket_regimes`, `mark_bucket`, `consumed_seconds`, `observed_bytes`, `buckets_between`, and `save_household`.
  All of them go, and so do the migrations in `store.py` that created their tables. The other modules already create
  their own tables with `CREATE TABLE IF NOT EXISTS` on the shared connection, and `policy/accounts.py` creates the
  parent tables the same way. `PolicyStore` is left opening that connection and setting its pragmas. If the
  schema-version check still earns its place, the migration list starts again at version 1 with whatever the store
  still owns. Otherwise it goes too.
- **The stub.** `DECISION_STUB`, `DECISION_FILE`, `tests/decision-stub.compose.yml`, and `decision.json` handling.
  The replacement is a small stub decision service in `tests/`, run in place of `decisions` by a test-only Compose
  override, the way `tests/origin` stands in for a website. It answers `POST /v1/decisions` with a document the test
  writes. It answers the observations path and `/health` too, if the stacks need them.

## Existing databases

Nothing in the code handles a database created by an earlier build. Every existing stack starts on a fresh
`policy-data` volume: the household's with `docker compose down -v` before the upgrade, and a development stack the
same way. `dw down` does not remove volumes, so the reviewer runs `docker compose --project-directory ~/daywarden
down -v` for the installed stack, or `docker compose down -v` in the repository.

## Tests

The test files built for the old engine are `test_policy_rules.py`, `test_policy_groups.py`, `test_policy_clients.py`,
`test_policy_buckets.py`, `test_policy_decisions.py`, `test_policy_service.py`, `test_policy_report.py`,
`test_policy_volume.py`, `test_policy_quota.py`, and `test_policy_tasks.py`. Some tests in those files cover behaviour
that is still live under another name, such as address normalization, DNS resolution keeping the last good
addresses, request parsing, and the policy surviving a recreated container. Keep those and move them to YAML, or
confirm an existing YAML test already covers them. `test_parent_signin.py`, `test_cut.py`, and `test_usage.py` each
have a few tests or assertions on the old path. Many other tests only unset `DECISION_STUB` or set `DECISION_FILE` in
their environment. Drop those lines. Test names and docstrings that mention the old engine, such as
`test_the_toml_ledger_answers_empty` and the docstring of `test_hierarchy.py`, go or are reworded.

## Order

Do this before S016. S016 changes `create_app` and `observations.main` to reload the policy. Without the old branch,
there is one policy path to make reloadable.

## Out of scope

- The completed stories under `stories/done/` and `implementation_plan.md`. They are the record of what was built and
  planned, and they stay as they are.

## Sizing

8 points. Most of it is deletion. The work is in the stub decision service and the three proxy stacks moved onto it,
in sorting about ten test files into delete or move to YAML, in the renames and the trace sweep, and in a full-suite
run that proves nothing live lost its coverage.

# Implementation

## Files Added/Changed/Removed

Removed:

- `policy/config.py`, `policy/rules.py`, `policy/groups.py`.
- `tests/decision-stub.compose.yml`.
- `tests/test_policy_rules.py`, `tests/test_policy_groups.py`, `tests/test_policy_clients.py`,
  `tests/test_policy_buckets.py`, `tests/test_policy_decisions.py`, `tests/test_policy_report.py`,
  `tests/test_policy_volume.py`, `tests/test_policy_quota.py`, `tests/test_policy_tasks.py`.

Added:

- `tests/decision_stub.py`: the test-only decision service. It answers `POST /v1/decisions` with the bytes of
  `next-decision.json` in the stack's configuration directory, read on each request, answers 500 when that file is
  missing, answers `GET /health`, and logs each request and answer to `/tmp/decisions.jsonl`.
- `tests/stub-decisions.compose.yml`: runs `tests/decision_stub.py` as the `decisions` service's command, in the same
  image and with the same health check.
- `tests/test_addresses.py`: address normalization and DNS resolution, moved from the deleted client tests.
- `tests/test_buckets.py`: bucket placement and day-length checks, written against `place` and `require_day_length`.

Changed:

- `policy/app.py`: one policy path. The `yaml_mode` switch, the `DECISION_FILE` and `DECISION_STUB` settings,
  `_announce_stored`, and the old `/usage` branch are gone. `_start_hierarchy` is `_load_policy`, and
  `_announce_hierarchy` is `_announce_policy`.
- `policy/observations.py`: `record`, `_clock`, and the old ledger path are gone. `_hierarchical` is `_load_policy`.
  `status_for(policy, usage, body)` and `listen(policy, usage, ...)` take the policy and the ledger directly.
- `policy/hierarchy.py`: `require_yaml`, which `load` and both services call first. It also holds `REVISION_TASK`,
  `absolute_http_url`, and `DEFAULT_BUCKET_SECONDS`, which used to live in the deleted modules or the store.
- `policy/engine.py`: site group pattern matching (`matches`) and `UNCONFIGURED_TASK_MESSAGE` moved here, the only
  place they are used.
- `policy/store.py`: `PolicyStore` only opens the shared connection and sets its pragmas. Every data method, the
  migration list, and the schema-version check are gone.
- `policy/clients.py`: `Client` and `ClientDirectory` are gone. `normalize_ip` and `resolve_address` stay.
- `policy/decisions.py`: only `DecisionRequest`, `parse_request`, `log_entry`, and `DecisionLog` remain.
  `log_entry(raw)` records a refused request as `{"request": ..., "decision": null}`.
- `policy/report.py`: `load_report`, the old `respond`, its chooser, `ordered_groups`, and the per-day byte-limit line
  are gone. `respond_hierarchy` is `respond`. `BYTE_UNITS` moved here from the deleted loader.
- `policy/usage.py`: imports the default bucket length from `policy.hierarchy`, and its docstring no longer mentions
  the other ledger.
- `docker-compose.yml`: no `DECISION_FILE`, and the header comment describes one policy.
- `tests/policy.compose.yml`: the DNS name for the test client group resolves in `observations` too.
- `tests/test_policy_service.py`: rewritten as a YAML policy-service stack test.
- `tests/test_enforce_decisions.py`, `tests/test_report_observations.py`, `tests/test_child_computer.py`: use the stub
  decision service and `next-decision.json`. They no longer write a policy file.
- `tests/test_engine.py`: pattern matching and request parsing tests moved here, plus tests for refusing a policy
  file that is not YAML.
- `tests/test_parent_signin.py`: the sign-in tests use the usage page with a YAML policy.
- `tests/test_usage_report.py`: byte-limit display tests, moved from the deleted volume tests.
- `tests/test_usage.py`, `tests/test_cut.py`, `tests/test_spelling.py`, `tests/test_hierarchy.py`: removed the
  old-ledger tests, the old docstring, and the old `observations` call signatures.
- `tests/test_arithmetic.py`, `tests/test_attempt_review.py`, `tests/test_return_to_page.py`,
  `tests/test_skip_counting.py`, `tests/test_task_selection.py`: removed the `DECISION_FILE` and `DECISION_STUB`
  lines.
- `README.md`: `POLICY_FILE` must name a `.yaml` or `.yml` file.
- `docs/hierarchical-policy.md`: removed wording that only made sense beside the old model, such as rules belonging to
  a site group, a quota living on a site group, and a "stored" policy. Documented the `.yaml`/`.yml` rule.

## Change Summary

The YAML policy is the only policy. The decisions and observations services load `POLICY_FILE` through
`policy.hierarchy.load`. Before anything else, both services check the name. A path that does not end in `.yaml` or
`.yml` raises `ConfigError: <path>: the policy must be YAML, in a file ending in .yaml or .yml`, whether or not the
file exists, and the service stops before it opens the database. A missing YAML file behaves as before: decisions
denies everything and observations accepts and ignores reports.

The database schema is now whatever the modules that use it create with `CREATE TABLE IF NOT EXISTS`: parent
accounts, sessions, and parent checks in `policy.accounts`, attempts in `policy.tasks`, the usage ledger and transfers
in `policy.usage`, and return pages in `policy.returns`. The schema-version check is gone, because the store no longer
owns any tables. Nothing looks for the old engine's tables or drops them.

The proxy tests run `tests/decision_stub.py` in place of the decisions service through a test-only Compose override,
the same way `tests/origin` stands in for a website. A test writes the next decision document, including malformed
ones, to `next-decision.json`. The production decisions service has no switch for this.

Tests of live behaviour that used the old engine were moved, not lost:

- Address normalization and DNS resolution are in `test_addresses.py`.
- Pattern matching and request parsing are in `test_engine.py`.
- Bucket placement is in `test_buckets.py`.
- Byte-limit display is in `test_usage_report.py`.
- Parent sign-in uses the usage page with a YAML policy.
- The policy-service stack test covers the same live behaviour with a YAML policy: a DNS-named client group,
  household-local time in the log, site groups and rule sets deciding, a malformed request refused, observations
  filed and read by the quota, the usage page closed over plain HTTP, and stored usage surviving recreated containers.

The full suite has 1085 passing tests, including the Docker stacks, with none skipped. Searching for `toml`, ignoring
case, outside `stories/done/`, `implementation_plan.md`, and `.git`, finds only this story. It will stop finding
anything once this story moves to `stories/done/`.

`dist/` is git-ignored and still holds a package built before this change. Build a new one with `make dist` before
installing.

## Suggested Acceptance Testing

### Acceptance test cases for S017

1. Upgrade the household stack on fresh volumes. Run `make dist` and copy the new package to the household machine.
   Run `docker compose --project-directory ~/daywarden down -v`, run the new package's `./install.sh`, then `dw up`.
   `docker compose --project-directory ~/daywarden ps` shows `decisions`, `observations`, and `proxy` healthy.
2. On a child's computer that trusted the proxy before the upgrade, open an HTTPS site the policy allows. It loads with
   no certificate warning. `~/daywarden/ca` still holds the same `mitmproxy-ca-cert.pem` as before, and the spelling
   recordings are still under the data directory.
3. Run `add-parent <name>` and sign in at `https://<host>:<POLICY_PORT>/usage`. The sign-in works.
4. Through the proxy on a child's computer, open an allowed site, a denied site, and a site the household policy
   redirects to the task pages. You see the site, the deny page with the policy's message, and the task page.
5. After some browsing, open `/usage` and choose the child's client group. The new usage is listed for today. Complete
   or give up a task. `/attempts` lists that attempt.
6. Run `dw down`, then `dw up`. The parent account still signs in, and `/usage` and `/attempts` still show the earlier
   usage and attempt.
7. Copy `config/policy.yaml` to `config/policy.json`, set `POLICY_FILE=/etc/daywarden/policy.json` in `.env`, and run
   `dw up`. `decisions` and `observations` do not start. `docker compose logs decisions` and
   `docker compose logs observations` each end with
   `/etc/daywarden/policy.json: the policy must be YAML, in a file ending in .yaml or .yml`. Neither service allows
   anything. Repeat with a `POLICY_FILE` that names a file that does not exist, such as `policy.conf`. You see the
   same error. Remove the line from `.env` and run `dw up` again.
8. Set `POLICY_FILE=/etc/daywarden/policy.yml` after copying `policy.yaml` to `policy.yml`. Both services start and
   decide as in test 4. Remove the line again.
9. Run `docker compose config` in the repository, and in `~/daywarden`. Neither output contains `DECISION_FILE` or
   `DECISION_STUB`.
10. Run `docker compose logs decisions` after a fresh start. It shows the policy summary and the parent account line:
    `loading`, `household timezone ...`, `task pages are ...`, `usage buckets are ...`, `entry ...`, each
    `client group`, each `site group`, and the usage report line. There is no `client ...:`, `group ...:`, or
    `revision task placeholder` line.
11. In the repository, run
    `grep -ril toml . --exclude-dir=.git --exclude-dir=done --exclude-dir=dist --exclude-dir=.venv --exclude=implementation_plan.md 2>/dev/null`.
    It lists only `stories/S017-remove-the-old-policy-engine.md`, until that story moves to `stories/done/`. If it
    also lists files under `__pycache__` or `.pytest_cache`, those are caches left from an older checkout. Delete
    them and search again.
12. Read `policy/`, `proxy/`, `docker-compose.yml`, `README.md`, and `docs/`. Nothing describes another policy
    format, another engine, another usage ledger, or the old engine's tables. `policy/config.py`, `policy/rules.py`,
    and `policy/groups.py` no longer exist.
13. List `tests/`. The proxy tests use `tests/decision_stub.py` through `tests/stub-decisions.compose.yml`, and there is
    no `tests/decision-stub.compose.yml`. Run `make test`. The whole suite passes.
