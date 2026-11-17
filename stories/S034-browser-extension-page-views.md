Ticket: S034
Title: Page views from a browser extension
Status: Draft
Story Points: 26
Last Updated: 2026-11-17 06:02:34
---

# User Voice

As a parent, I want to see each page my child views, with its title, including the pages a site such as YouTube moves
to without loading a new page, so that I can see which videos were watched and which pages were read, not only which
sites were open.

# Behaviour

## Done

- [ ] S034.1 and S034.2 are done.

# Child stories

| Ticket | Title | Points |
| --- | --- | --- |
| S034.1 | Spike: browser extension for page views | 5 |
| S034.2 | Page views from the browser extension | 21 |

# Notes

## Why

The proxy sees requests, not pages. S030.4 narrows the request list to page loads, but single-page sites such as
YouTube, TikTok, and Reddit load once and then change the address with scripted fetches. Two hours of clicking from
video to video on YouTube gives one page load. The Minutes graph still counts the time, but nothing says what was
watched.

A browser extension sees every address change in every tab, with the tab's title, through the browser's own
navigation and tab events. It needs no knowledge of any one site, so a site's internal changes do not break it.

## Split

S034.1 is a spike, because the extension's install, lock-down, and reporting path have unknowns that decide the shape
of S034.2: whether Firefox and Chromium will force-install a self-made extension on the children's Arch Linux
computers, how it reaches daywarden, and what daywarden can do when it is missing. S034.2 is refined from its findings.

## Options not taken

- **Injecting a script into pages through the proxy** would observe the same address changes without installing
  anything, but it changes what sites serve, must work around each site's Content Security Policy and Trusted Types,
  and can break pages. It is shelved until S034.2 is done, and is worth revisiting only if the extension leaves a gap
  that matters.
- **Reading one site's own reports**, such as YouTube's playback statistics requests, is cheap but needs a reader per
  site and breaks when the site changes. S034.1 checks what YouTube's reports carry, as a point of comparison only.

## Relation to S030

This epic sits outside S030. S030 reports what the proxy sees. This epic adds a second source on the child's computer.
How page views appear alongside the S030 request table is settled in S034.2.
