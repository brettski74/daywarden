Ticket: S036
Title: MCP Server
Status: Draft
Story Points: 
Last Updated: 2026-11-17 20:01:01
---

<!--
Follow "Writing stories" in AGENTS.md. Above all, say each thing once.
Delete these comments, and any optional section left empty, when writing the story.
-->

# User Voice

As a [user], I want [something] so that [reason].

# Scenarios

<!--
Optional. Short narratives of a user reaching a goal across several features. They state no rules; the rules are
in Behaviour. Leave this section out when Behaviour says it all.
-->

## [Scenario name]

[Who does what, and what they see, in a few sentences.]

# Behaviour

<!--
Grouped by area. A checkbox for each thing a reviewer can check through the policy file, the data directory, the
web pages, or the command line, with its example inside it. A plain bullet for detail that is not a check of its
own. A sentence under a heading may define terms its checks use.
-->

## [Area]

- [ ] [Something a reviewer can see, such as: dragging a word onto a row adds it to the end of that row.]
- [ ] [Behaviour inherited from another story, as one check: saving works as in Snnn.]
- [Detail that is not a check of its own, such as an icon name or a list of accepted values.]

# Child stories

<!-- Epics only. -->

| Ticket | Title | Points |
| --- | --- | --- |
| Sxxx.1 | [First child] | 8 |
| Sxxx.2 | [Second child] | 5 |

# Notes

<!-- Optional. Dependencies, design and implementation hints, what is out of scope, and sizing. Never Behaviour. -->
I want a streamable HTTP MCP server. The MCP server should enable an AI agent to create new tasks, new sentence pools, set up site groups, client groups, time windows, quotas and other configuration, as well as read the details of existing configuration and modify it. The MCP server should be configurable to allow controls over CRUD operations on each entity class, so an administrator could limit access to only allow read access on site groups, client groups and attempts data but read, update and create access to task configuration.

The MCP server should also be able to read usage and attempts details to help answer questions 

Authentication needs to be resolved. The current security controls do not include any kind of RBAC or more granular control other than access or no access to the entire parent portal. It also only supports a simple authentication scheme with relatively short-lived session keys issued from a CSPRNG. While I think we could probably build some kind of browser initiated authentication that passes a session key or similar back to the agent, I suspect that the short-lived nature of the current session keys may be a problem. I need some advice on appropriate authentication systems for use with an MCP server. I'm ok with the user having to periodically re-authenticate, but I think the current 15 minute idle-timeout would make the reauthentication become an unwelcome interruption.

The story should enumerate the set of tools that will be exposed to the agent and the set of permissions that apply to each of them. The UI will need a page for managing the configuration of the MCP server. I think this also should be backed by a configuration file somewhere, but should be separate from the policy.yaml file. Maybe another configuration file in the config directory for the mcp server configuration.