Ticket: S015
Title: Return to the page he was sent away from
Status: Draft
Story Points: 8
Last Updated: 2026-11-05 22:21:00
---

# User Voice

As a child, I want to land back on the page I was trying to open once I have done enough revision, so that I do not have to remember and retype where I was going.

As a parent, I want the reward for finishing revision to arrive straight away, so that he links doing the work with getting the thing he asked for.

# Use Cases

## UC1 - Remember the page that sent him to revision

- He opens a page, such as `https://www.youtube.com/watch?v=abc123`, and the rules redirect him to `revision_task`.
- The policy service remembers that URL for the computer that asked, by its IP address, in full, including the path and query string. A fragment never reaches the proxy, so it is not part of the URL.
- A later page from the same computer that is also redirected to `revision_task` replaces it. Only the last one is kept for each computer.
- Each computer has its own remembered URL, even when two computers are in the same client group. A page blocked on one never replaces the other's, and is never opened on the other. A computer in the `default` client group is remembered by its address too.
- A computer whose IP address changes, such as through a new DHCP lease, is a new computer here. Its old address's URL is not used.
- The remembered URL is kept in the policy database, so it survives a restart of the `decisions` service.

## UC2 - Which requests are remembered

- Only a `GET` is remembered. A `POST`, `HEAD`, `PUT`, `DELETE`, or any other method is redirected as it is today, and the remembered URL does not change.
- Only a page load is remembered, not the images, scripts, and background fetches that page makes:
  - A request with `Sec-Fetch-Dest: document` is a page load. Any other `Sec-Fetch-Dest` value, such as `image`, `script`, `empty`, or `iframe`, is not.
  - Browsers leave `Sec-Fetch-Dest` off plain `http` requests. A request with no `Sec-Fetch-Dest` is a page load when its `Accept` header includes `text/html`.
- Only a redirect to `revision_task` is remembered. An allow, a deny, and a redirect to an absolute URL in the policy file do not change it.
- A request to the policy server itself, such as the task pages or `/tasks/next`, is never remembered, even when the policy service redirects it from one task to another.
- A host on the proxy bypass list never reaches the policy service, so it is never remembered.

## UC3 - Back to the page when revision is done

- When an attempt passes and the "Well done" screen shows, the policy service takes the URL remembered for the computer showing that screen. It decides that URL again for that computer's address, with the same rules the proxy would use at that moment.
- A pass on one computer forwards only that computer. Another computer in the same client group keeps its own remembered URL. The pass counts toward the whole group's `tasks_required`, so that computer's page may already be allowed. Reloading it there works as it does today, and the proxy then forgets it as UC5 describes.
- If that decision is an allow, the "Well done" screen says "Going back to www.youtube.com" with the host of the remembered URL. After 5 seconds the page opens the remembered URL in the same tab. A "Go now" button opens it straight away, and pressing Enter does the same.
- "Next task" is still shown when another task is eligible. Choosing it stops the countdown and opens the next task as today. The remembered URL is kept, so a later pass forwards him again.
- The proxy then decides that request as it would any other. Nothing about the return bypasses the rules.

## UC4 - Not done yet, or still not allowed

- If the remembered URL would still be redirected to `revision_task`, such as when `tasks_required` needs another pass, the "Well done" screen is unchanged. It shows "Next task" or "All done for now" as it does today.
- If the remembered URL would be denied, such as when the time quota is used up or a time window has closed, the "Well done" screen is unchanged.
- With no remembered URL, the "Well done" screen is unchanged.
- A failure, a give-up, and the spelling missed-words screen are unchanged. On a spelling pass with missed words, the countdown starts only when "Continue" brings up the "Well done" screen.
- A `parent_check` pass recorded from `/attempts` forwards nothing, because he is not on a quiz page. The remembered URL is kept for his next pass.

## UC5 - When the remembered URL is forgotten

- When the proxy allows a request for exactly that URL from the same computer, the URL is forgotten. That happens whether he got there through the forward or typed it himself, so an old URL does not send him back again after the next task.
- When the household day ends, the URL is forgotten. A page he was sent away from last night does not open after this morning's revision.

# Acceptance Criteria

Use a test policy in which an `entertainment` site group covering `www.youtube.com` is redirected to `revision_task` until `tasks_required` reaches 1, and then allowed. Give his client group one short arithmetic task, such as one with `correct_answers_required: 3`. Configure Firefox to use the proxy as described in `docs/child-computer.md`. Run the `curl` checks on the same computer as Firefox, with `--cacert` pointing at `mitmproxy-ca-cert.pem` for `https` URLs.

- [ ] He opens `https://www.youtube.com/watch?v=<id>`, is sent to the arithmetic task, and passes it. "Well done" says "Going back to www.youtube.com", and about 5 seconds later the same video page opens in that tab.
- [ ] On the same "Well done" screen, "Go now" and Enter open the video straight away.
- [ ] With `tasks_required` set to 2 and two tasks assigned, passing the first task shows "Well done" and "Next task" with no countdown. Passing the second forwards him to the video.
- [ ] After he opens one YouTube video and then a different one, both redirected to the task, passing the task forwards him to the second video.
- [ ] A plain `http` page works too. `curl -x http://<proxy>:<port> -H 'Accept: text/html' http://<blocked host>/some/path?x=1` is redirected to the task. After he passes it in Firefox on that computer, "Well done" goes back to `http://<blocked host>/some/path?x=1`.
- [ ] A `POST` that is redirected to the task is not remembered. After an earlier blocked page load, `curl -x ... -X POST -d a=1 https://www.youtube.com/post-target` is redirected, and the pass still forwards to the earlier page.
- [ ] A background fetch is not remembered. After a blocked page load, `curl -x ... -H 'Sec-Fetch-Dest: image' https://www.youtube.com/thumb.jpg` and `curl -x ... https://www.youtube.com/api` (with curl's default `Accept: */*`) are redirected, and the pass still forwards to the page.
- [ ] A redirect to an absolute URL in the policy file, and a deny, are not remembered. The pass forwards to the earlier `revision_task` page, or shows the normal "Well done" when there was none.
- [ ] Opening `https://<policy host>:<port>/tasks/next` directly is not remembered, and neither is a redirect from one task page to another.
- [ ] When the entertainment quota is used up, the rules deny YouTube after a pass, and "Well done" is unchanged, with no countdown.
- [ ] Choosing "Next task" during the countdown stops it and opens the next task. Passing that task forwards him to the remembered page.
- [ ] After he has been forwarded to the page once, or has opened it himself while it is allowed, passing another task shows the normal "Well done" with no countdown.
- [ ] A URL remembered before the household day ends is not used after it. Passing a task the next day shows the normal "Well done".
- [ ] Two computers in the same client group each get their own page back. Computer A is sent away from one URL, then computer B from another. Passing the task on A forwards A to its own URL, not B's. B's URL is still remembered, and passing a task on B forwards B to it.
- [ ] Computers in different client groups each get their own page back too. A page blocked on one is never opened on the other.
- [ ] After `docker compose restart decisions`, a page remembered before the restart is still opened after the next pass.
- [ ] The countdown and "Go now" work on the "Well done" screen of every quiz type: arithmetic, skip counting, spelling (including after "Continue" from the missed-words screen), and parts of speech.
- [ ] A failure, a give-up, and a `parent_check` recorded from `/attempts` forward nothing.
- [ ] `README.md` and `docs/hierarchical-policy.md` describe which requests are remembered, when he is sent back, and when the URL is forgotten.

# Notes

## Decisions in this draft

- "Last URL requested" means the last page load that was redirected to `revision_task`. Remembering every request would usually pick up a background fetch from the blocked page, or an allowed school site he opened while waiting. Forwarding him to either of those would be no reward. Change this during refinement if the intent was any allowed or redirected page load.
- The URL is remembered per computer, by IP address, not per client group. Otherwise a page blocked on one computer would replace, or be opened on, another computer in the same group. Client groups are already classified from IP addresses, so the address is the finest identity the household has.
- "Completion of the day's revision tasks" means the remembered URL would now be allowed. Each site group can need a different `tasks_required` count, so there is no single "done for the day" moment. Deciding the URL itself gives the right answer for that page, including a time window or quota that now denies it.
- The 5-second countdown gives the last answer's sound time to play and lets him see "Well done". It is not configurable in this draft.

## Implementation pointers

- `proxy/addon.py` `_ask` sends `method` and `url` but no headers. Add the request's `Sec-Fetch-Dest` and `Accept` values to the decision request, and accept them, as optional fields, in `parse_request` in `policy/decisions.py`. The decision log already records the request the addon sent.
- The decision that the proxy enforces comes from `policy/engine.py` `judge`, after `apply_task_selection` in `policy/selection.py`. The URL is remembered when the rule's decision was a `revision_task` redirect, and forgotten when the final decision allows that exact URL. `same_task_site` says whether a URL is on the policy server.
- Every quiz type returns `next` from `next_task_url` in `policy/quiz_page.py` when an attempt passes: `arithmetic_page.py`, `skip_counting_page.py`, `spelling_page.py`, and `parts_of_speech_page.py`. Return the remembered URL alongside it when `judge` allows it for that computer's address, and extend `finish` in the shared script to run the countdown.
- A task page knows the child's address from `_client_address` in `policy/app.py`. That is the connection's address, or the `X-Daywarden-Client` header the proxy adds when it forwards the request. The decision request carries the same address as `client_ip`. Store the remembered URL keyed by the normalized address from `normalize_ip`.
- The household day comes from `household_day` in `policy/tasks.py`. If S009 is done first, the day boundary it adds applies here too.
- An automated test that sends real requests through the proxy belongs with `tests/test_enforce_decisions.py`, which starts Docker Compose.
