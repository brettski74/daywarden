Ticket: S036
Title: MCP Server
Status: Refined
Story Points: 42
Last Updated: 2026-11-17 20:51:02
---

# User Voice

As a parent, I want an AI agent to read and change the household's tasks, sentence pools, and policy, and to answer
questions from the attempts and usage, within limits I set, so that I can manage Daywarden by asking for what I want
instead of editing every page and file myself.

# Scenarios

## A new times table

The parent turns the MCP server on at `/parent/settings/mcp` and grants tasks create, read, and update. In Claude Code
they add `https://garden:8084/mcp`. The agent opens the browser, the parent signs in to the portal and approves, and
the agent is connected. Asked "how is he doing at the six times table, and set up a seven times task like it", the agent
reads the trend for `arithmetic/times-6` and its missed facts, reads that task, and creates `arithmetic/times-7` with
the same settings. The parent sees the new task in Task Administration, the commit in the config history, and the
write in the MCP activity log. The next week the agent is still connected without signing in again. If the parent
leaves it unused for 30 days, the connection lapses and the next use opens the browser again.

# Behaviour

## Done

- [ ] S036.1 to S036.3 are done.

# Child stories

| Ticket | Title | Points |
| --- | --- | --- |
| S036.1 | MCP server, sign-in, settings page, and read tools | 21 |
| S036.2 | Task and sentence pool write tools | 8 |
| S036.3 | Policy write tools | 13 |

# Notes

**Authentication.** The MCP authorization spec is OAuth 2.1: the MCP endpoint is a resource server, the agent runs
the authorization-code flow with PKCE in the browser, and holds a short access token and a rotating refresh token.
Daywarden is its own authorization server. The portal session is used only to approve a connection on a consent page,
so the 15-minute idle limit never interrupts the agent. Re-approval happens when a refresh token goes unused past its
idle limit or reaches its lifetime. Long-lived pasted tokens were considered and not chosen: they live in the agent's
config file and have no browser flow.

**Permissions.** One matrix in `config/mcp.yaml` applies to every connected agent. Each parent account has the same
standing, as in S007.1, and the matrix limits what agents can do, not what parents can do. Per-connection narrowing
is out of scope.

**Clients.** Claude Code and other agents running on a household machine can connect. An agent whose MCP calls come
from a cloud service, such as a claude.ai connector, cannot reach a household address and is out of scope. The
agent's machine must trust the household CA, for Node-based agents through `NODE_EXTRA_CA_CERTS`.

S036.2 and S036.3 both depend on S036.1 and not on each other. S036.3 builds the policy write path that S007.2 has
not built yet. S007.2's pages should reuse it.
