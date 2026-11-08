Ticket: S021
Title: Show daywarden's logs with dw logs
Status: Draft
Story Points: 
Last Updated: 2026-11-08 10:55:00
---

# User Voice

As a parent, I want to see what daywarden has been doing with one `dw` command, without changing to the daywarden
directory and remembering the `docker compose logs` options. When a site is blocked unexpectedly or a service will not
start, the logs are the first thing I look at.

# Use Cases

## UC1 - See why a site was blocked

- The parent runs `dw logs decisions` and sees the recent decisions, including the one for the site in question.

## UC2 - Watch while testing

- The parent runs `dw logs` with a follow option, browses on a child's computer, and watches the decisions arrive.

## UC3 - A service will not start

- `dw status` shows a service is not healthy. The parent runs `dw logs` for that service and sees why.

# Acceptance Criteria

- [ ] `dw logs` shows the recent logs of every daywarden service, and works from any directory.
- [ ] `dw logs <service>` shows the logs of one or more named services. An unknown service name is a usage error that
  lists the service names.
- [ ] Options for following the logs and for how many lines or how far back to show.
- [ ] `dw logs` works while daywarden is stopped, showing what the stopped containers logged, and says when there is
  nothing to show.
- [ ] `dw help` lists `logs` with a one-line description.
- [ ] The documentation that says to run `docker compose logs` uses `dw logs` instead.

# Notes

To be refined later.

## Points to work out in refinement

- Which options to support, and whether they match the `docker compose logs` option names, such as `-f`, `--tail`,
  and `--since`.
- Whether to include the logs of the user service at boot, from `journalctl --user -u daywarden`.
- Whether to add `make logs` for the local dev stack.
- Whether there is a filter worth adding, such as decisions for one client group or one host.
