Ticket: S041
Title: MCP Test Proxy Request
Status: Refined
Story Points: 8
Last Updated: 2026-11-18 10:15:00
---

# User Voice

As a parent working with an AI agent, I want the agent to ask what the proxy would do with a request, at a time I
choose and with the day's progress and quota balances I choose, so that the agent can check and debug the policy it
reads and edits without anyone having to try it on a child's device.

# Scenarios

## Why is the game site open on Saturday evening

The parent says the game site stays open after the evening window ends. The agent calls `test_proxy_request` for the
child's address and the game site's URL at 19:30 on the Saturday, then again with `tasks_completed` of 0 and of 3, and
with a quota's `seconds_used` just below and above its limit. From the rule set and rule index in each answer it sees
which rule let the request through, and proposes the fix with the policy write tools of S036.3.

# Behaviour

## The tool

- [ ] Claude Code lists `test_proxy_request` only while `config/mcp.yaml` grants `rule_sets: [read]`. With that
      permission removed, the tool is gone from the list, and a call to it returns "This needs rule_sets: read." It
      is shown in the activity log as refused, as in S036.1. A successful call is not listed in the activity log, as
      for the other read tools.
- [ ] The request is described with the fields of a real decision request, `client_ip`, `method`, and `url`, all
      required, and the optional fetch metadata `sec_fetch_dest`, `accept`, `sec_fetch_mode`, `sec_fetch_site`,
      `sec_fetch_user`, and `sec_purpose`. A missing or malformed field, such as `client_ip` of `not-an-ip`, is
      refused with the message the decisions service gives for it.
- [ ] The answer is what the proxy would do for the same request with the same policy. A request from a client address
      in a group, for a URL in a site group, gives the same action, status, message, or redirect location as the
      proxy gives that address in a browser. This holds for allow, deny, and each kind of redirect, including the one
      to the revision task.
- [ ] A client address in no client group is judged as `default`, and a URL in no site group as `default`, as the
      proxy does.

## The time

- [ ] `at` is an optional ISO 8601 time. Left out, the household's date and time now is used.
- [ ] An `at` with no offset is read as household-local time. An `at` with an offset is converted to household time.
      The same address and URL give an allow at `at` of `2026-11-14T16:30` and a deny at `2026-11-14T19:30` when a
      time window ends at 19:00, and the answer names the household-local time it used.
- [ ] An `at` that is not an ISO 8601 time is refused with a message saying so.
- [ ] A time at a household day boundary, such as 00:30 when the household day starts at 04:00 (S009), counts the
      earlier day's `tasks_completed` and quota balances, as the proxy does at that time.

## The test fixture

The test never reads the household's real usage, so only what the call gives affects the answer. Anything the call
leaves out counts as 0.

- [ ] `tasks_completed` is the number of revision tasks the client group has completed on the household day of `at`.
      A rule that needs `tasks_required: 2` holds with `tasks_completed` of 2 and fails with 1 or with it left out,
      whatever the child has really done today.
- [ ] `quotas` maps a quota's name to `seconds_used` and `bytes_used`, its balance on that day. A rule
      `time_remaining` for a quota whose time limit is 3600 holds with `seconds_used` of 3599 and fails with 3600,
      and `volume_remaining` does the same with `bytes_used` and the byte limit. A quota named that the policy does
      not have is refused with the names the policy does have.
- [ ] `tasks_completed` and `quotas` apply to the client group the request is judged as. A call cannot set them for
      another group.
- [ ] Two calls with different fixtures, one after the other, do not affect each other, and neither affects the
      child's real counts. After a call with `tasks_completed` of 5, the child's quiz pages, the usage graph, and
      the attempts pages show no change.

## Nothing leaks to the proxy path

- [ ] A real request through the proxy is judged only from the child's real usage, whatever the agent has tested. After
      a test that ends in an allow with `tasks_completed` of 5, the same request in a browser from that address is
      still denied until the child really has 5.
- [ ] `/v1/decisions` and the proxy accept no `tasks_completed`, `quotas`, or `at` from a request. They are ignored,
      as any other unknown field is, and a request that includes them is judged on the real time and real usage. The
      proxy's `occurred_at` works as before.
- [ ] A test records no usage for any client group, site group, or quota. After a test that ends in an allow, the
      usage graph, the request table, and every quota's balance are unchanged for every client group and site group,
      including the ones the test named.
- [ ] A test leaves no other trace in the child's data. It adds no row to the request history, the decision log, `dw
      logs decisions`, or the saved transfers, and it records no return-to-page address.

## The answer

- [ ] The answer gives the action and what goes with it, which are the status and message for a deny and the
      location for a redirect, the household-local time used, the client group and site group the request was
      classified into, the rule set and the rule's number in it that decided, and a sentence saying what the proxy
      would do, such as "Blocked with 403: the evening window has ended." A request no rule decided gives the
      default deny, and the answer says that no rule matched, with no rule set or number.
- [ ] For an allow, the answer says when the proxy would look at the request again, `recheck_at` as a household-local
      time, or says it has none, so the agent can see which clock the allow depends on.
- [ ] The rule set and number are the same as those `list_rule_sets` shows, so the agent can find the rule. A rule
      inside another rule's branch is named as the engine names it, such as `entry rule 3 then`.

# Notes

Depends on S036.1, for the tool list and permissions, and on the engine's `judge` and `Ledger`. The tool calls the
same `parse_request` and `judge` that `/v1/decisions` uses, so the two cannot differ, with a ledger made from the
call's arguments in place of the usage store. The fixture is the only new input to `judge`, and nothing in the HTTP
decisions path builds one. Automated tests must cover each leak check above, in particular that `/v1/decisions` ignores
the fixture fields.

Out of scope: testing a proposed, unsaved policy, which the policy write tools' dry run covers in S036.3; tasks other
than the count of revision tasks completed, and the child's real usage, as inputs to the fixture; testing a transfer
already in progress or the volume ceiling of an allow.

Sized at 8: one tool over existing engine functions, a fixture ledger, and tests, with no new page.
