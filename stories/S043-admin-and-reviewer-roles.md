Ticket: S043
Title: Admin and Reviewer Roles
Status: Draft
Story Points: 13
Last Updated: 2026-11-19 16:12:20
---

# User Voice

As a parent who runs Daywarden, I want to give another adult, such as the other parent, a grandparent, or a tutor, a
reviewer account, so that they can review the children's work and record parent checks without being able to change
tasks, assets, policy, or the MCP server.

# Scenarios

## A grandparent reviews the week

The admin runs `bin/add-parent --role reviewer nana` on the host and gives the password to the grandparent. Nana signs
in and sees only Attempts and Usage in the sidebar. She opens the younger child's spelling trend, drills into Tuesday's
attempt, then into the arithmetic facts grid, and records a parent check for the reading the child did on paper. A
link to a task page that the admin sent her opens a message that the page is for admins. Later she connects her AI
agent through the consent page. The agent can read the attempts and usage, but its calls to edit a task are refused.

# Behaviour

## Roles and accounts

Every parent account has one role, `admin` or `reviewer`. An admin can use everything the portal and the MCP server
offer. A reviewer has read-only access to attempts and usage data. Recording a parent check is the one exception.
Documentation below sets out this rule for future work.

- [ ] After upgrading a stack that already has parent accounts, `bin/add-parent --list` lists every existing account
      as `admin`. Each one signs in and sees every sidebar group and page as before. Their sessions and the MCP
      connections they approved carry on through the upgrade.
- [ ] `bin/add-parent USERNAME` adds a new account as `admin`, as it does today.
      `bin/add-parent --role reviewer USERNAME` adds a new account as `reviewer`. Both read the password once, as
      S007.1 does.
- [ ] `bin/add-parent USERNAME` for an existing account replaces its password as before and keeps its role.
      `bin/add-parent --role ... USERNAME` for an existing account is refused with a message pointing to `--set-role`,
      and changes nothing.
- [ ] `bin/add-parent --set-role reviewer USERNAME` and `--set-role admin USERNAME` change an existing account's role
      without asking for a password. They print the account's new role. They end that account's sessions, so every
      tab it has open must sign in again. An unknown username is refused with a message, and nothing is added.
- [ ] Making the only admin a reviewer is refused: "ada is the only admin. Add another admin first." Nothing changes.
- [ ] A role other than `admin` or `reviewer` is refused with a message listing the two roles. Nothing changes.
- [ ] `bin/add-parent --list` prints one line per account with its username and role, in username order, and asks for
      no password. `bin/add-parent --help` describes `--role`, `--set-role`, and `--list`.

## What a reviewer sees in the portal

- [ ] At the bottom of the sidebar, the signed-in line names the role, such as "Signed in as nana (reviewer)" or
      "Signed in as ada (admin)".
- [ ] For a reviewer, the sidebar holds Attempts and the Usage group (Minutes, Bytes, Requests) only. Task
      Administration, Asset Administration, Policy, and Settings are not shown. For an admin, the sidebar is unchanged.
- [ ] A reviewer has all of Attempts as S035 and its children built it: the overview and its filters, each task's
      trend, the arithmetic facts grid and its shadings, and each attempt's page. Every link between those pages
      works.
- [ ] A reviewer records a parent check from the Attempts page as S007.1 and S007.4 do. Afterwards, the client group's
      revision count includes it, the same as when an admin records it.
- [ ] A reviewer has all of Usage as S030 built it: Minutes and Bytes with every filter, opening a line's top hosts,
      and the Requests table with its filters and paging.
- [ ] A reviewer can choose any saved usage preset on the Usage and Requests pages. Saving and deleting presets
      change data the household shares, so the reviewer does not see Save preset or Delete preset. An admin's
      presets work as before.
- [ ] A reviewer who opens an admin page by its address, by typing it, from a bookmark, or from a link an admin sent,
      sees the frame with "This page is for admins. You are signed in as nana, a reviewer." in the content pane.
      Nothing from the page is loaded. This holds for every page under `/parent/tasks/`, `/parent/new-task`,
      `/parent/assets/`, `/parent/policy/`, and `/parent/settings/mcp` with its activity log. The MCP consent page
      below is the one exception.
- [ ] Signing in as a reviewer with `next` set to an admin page lands on that page's message, in the frame. Signing in
      with no `next` opens Attempts, for either role.
- [ ] A reviewer's browser that opens an admin data address, such as `/parent/api/tasks` or
      `/parent/api/policy/quotas`, gets a 403 with a message that the address is for admins and no household data.
      The 403 for a closed portal, with no parent account, is unchanged. Unknown `/parent/api/` addresses are still a
      JSON 404 for both roles.
- [ ] Opening an attempt or the facts grid as a reviewer makes no request to an admin data address. The browser's
      network panel shows no 403 while the reviewer uses the Attempts and Usage pages.

## What a reviewer's MCP agent can do

The MCP server keeps one `config/mcp.yaml` for the household. A connection approved by a reviewer gets the
permissions that file grants to `attempts` and `usage` only. Every other class is refused for it, whatever the file
grants. The limit follows the approving account's role at the time of each call.

- [ ] A reviewer can open the consent page, `/parent/settings/mcp/connect?request=<id>`, and approve or deny an agent
      as S036.1 describes. The page lists only the permissions the connection will have, such as `attempts: read` and
      `usage: read`, and says that a reviewer's agent can only read attempts and usage.
- [ ] When `mcp.yaml` grants neither `attempts: read` nor `usage: read`, the consent page tells a reviewer that there
      is nothing a reviewer's agent could use, and Approve is disabled. Deny still works.
- [ ] Claude Code connected through a reviewer's approval lists only the tools in the `attempts` and `usage` classes
      that `mcp.yaml` grants: `list_attempts`, `get_attempt`, `get_task_trend`, `get_arithmetic_facts`, `get_usage`,
      and `list_requests`. Each one answers as it does for an admin's connection.
- [ ] A reviewer's agent that calls any other tool by name, such as `update_task` or `get_household`, is refused with
      "This needs an admin's approval." The MCP activity log shows the call as refused, with the agent and the parent
      who approved it.
- [ ] After `bin/add-parent --set-role reviewer ada`, the next call from an agent that Ada approved as an admin is
      limited as above, with no new approval needed. After `--set-role admin`, it gets everything `mcp.yaml` grants.
- [ ] On the MCP page, an admin sees a reviewer's connection with the role in Approved By, such as "nana (reviewer)",
      and can revoke it as any other.

## Documentation

`docs/parent-portal.md` gains an Access control section. It is the reference for deciding which role a future page,
data address, or MCP tool is open to, so a later story can follow it without asking again.

- [ ] The section states each role's purpose:
  - **Admin.** Runs the system. An admin can use every page, data address, and MCP tool, now and in the future.
    Nothing is ever closed to admins.
  - **Reviewer.** Reviews the children's work and is not involved in running the system. A reviewer reads attempts
    and usage data with every drill-down. The one thing a reviewer changes is recording a parent check, for work
    done outside the system.
- [ ] The section gives the rule for new functionality, with examples from this story:
  - New functionality is admin-only by default.
  - It is open to reviewers only when it reads attempts or usage data and changes nothing. A new drill-down page, a
    new chart of attempts, or a new usage filter is open to reviewers.
  - Anything that creates, changes, or deletes stored data is admin-only. This holds even when the data is about
    attempts or usage, as saving a usage preset or removing attempts is.
  - Anything that reads how the system is set up is admin-only, even read-only: tasks, assets such as pools and
    recordings, policy, and MCP settings.
  - A new reviewer write, like the parent check, needs a story that names it as an exception. The section lists every
    such exception, and the parent check is the first.
- [ ] The section says where the role is enforced, and that new functionality must handle each one:
  - The service's list of data addresses open to reviewers. An address not on the list answers 403 to a reviewer.
  - The reviewer sidebar.
  - The not-available message for admin page addresses.
  - The MCP classes a reviewer's agent may use: `attempts` and `usage`, and read only. A new tool in those classes
    that changes data, or a new class, is admin-only unless its story says otherwise under the rule above.
  - Links and buttons on reviewer pages. A page open to reviewers shows no link to an admin page and no button for
    an admin action to a reviewer. The not-available message is a safety net, not a design.
- [ ] The section says that the service's checks are what protect the data. Hiding a link or a button is for a tidy
      page, not for security, and every check is tested for both roles.
- [ ] The Sessions and data section of `docs/parent-portal.md`, and its sidebar groups, describe the 403 for admin
      data addresses and the reviewer sidebar.
- [ ] The Parent Portal summary in `AGENTS.md` gains one bullet with the rule. Everything works for admins. Reviewers
      get read-only attempts and usage data, plus the parent check. New functionality is admin-only unless it fits
      that rule, and `docs/parent-portal.md` has the details.
- [ ] `README.md` explains the two roles in a sentence each where it describes `bin/add-parent`, and shows
      `--role`, `--set-role`, and `--list`.

# Notes

- Depends on S007.1 (accounts and sessions), S007.4 (portal frame and sidebar), S030 (usage), S035 (attempts),
  and S036 (MCP server). Rule 4 of "When to make a story an epic" names an upgrade of stored household data as a risk
  of its own. Here that upgrade is one column added to the accounts table with `admin` as its default, and it is
  accepted by the first check under Roles and accounts. That does not justify a separate child.
- Implementation hints:
  - Store the role on `parent_accounts`. `Accounts.accept` returns the role with the username.
    `/parent/api/session` returns both. The layout loader uses the role to build the sidebar, and does not load the
    task list for a reviewer.
  - Enforce on the service, not only in the portal. Give `PortalGate` an admin check that every admin endpoint uses,
    in `portal.py` and in `mcp_server.py`. List the endpoints reviewers may use, rather than the ones they may not,
    so a new endpoint is admin-only unless someone decides otherwise. Reviewer endpoints are the session, login,
    logout, attempts (list, trend, facts, one attempt), parent check, usage (minutes, bytes, requests), presets, and
    the consent page's GET and POST.
  - Admin-only endpoints include every task, new-task, pool, policy, recording, week, and task audio endpoint, and
    the MCP settings, revoke, and activity endpoints.
  - For MCP, combine `mcp.yaml`'s grants with a reviewer mask of `attempts` and `usage` when tools are listed and
    when each call is checked. Read the approving account's role per call.
- Decided while refining: roles are set only on the host with `bin/add-parent`. Admin pages are hidden from reviewers,
  not shown read-only. A reviewer may approve an agent, limited as above. Approving an agent gives no reviewer access
  beyond their own. A spelling task's Words pages count as modifying the task and are admin-only. Saving and deleting
  usage presets are admin-only under the read-only rule.
- Out of scope: a portal page for managing accounts, deleting accounts, more roles or per-child reviewers, and limits
  on host tools such as `bin/rm-attempts` and `bin/cut-clips`. Anyone with the host is an admin.
- Sizing: 13 points, against the reference of 14 points and 39 checks. The work is wide but shallow. It adds a role
  column and its upgrade, three CLI options, a role check across about fifty endpoints with tests for both roles, a
  sidebar and not-available page in the portal, and the MCP mask on listing and calling tools. Checking happens in
  the browser for two accounts and in Claude Code for two connections.
