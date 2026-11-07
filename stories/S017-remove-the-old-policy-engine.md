Ticket: S017
Title: Remove the old policy engine
Status: Draft
Story Points: 8
Last Updated: 2026-11-06 22:47:00
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
