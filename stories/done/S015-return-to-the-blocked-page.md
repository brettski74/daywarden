Ticket: S015
Title: Return to the page he was sent away from
Status: Done
Story Points: 8
Last Updated: 2026-11-05 23:10:00
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

# Implementation

## Files Added/Changed/Removed

- Added `policy/returns.py`: `is_page_load`, the `ReturnPages` store (table `return_pages` in the policy database, one row per normalized address), its `note` hook for each proxy decision, and `way_back`, which decides the remembered URL again for a pass.
- Added `tests/test_return_to_page.py` (38 tests): which requests are page loads, the decision request fields, the household day and per-address storage, the way back under a window and a used-up quota, and the whole service from proxy decisions to a passing answer.
- Changed `proxy/addon.py` to send `sec_fetch_dest` and `accept` with each decision request when the browser sent those headers.
- Changed `policy/decisions.py` so `parse_request` accepts both as optional strings.
- Changed `policy/engine.py`: `Trace` has a `revision` flag, set when the deciding rule redirected to `revision_task`, before task selection turns that into a task URL.
- Changed `policy/app.py` to note each YAML decision in `ReturnPages`, and to give the task pages a `back` for the computer asking.
- Changed `policy/task_page.py` to pass `back` to every quiz, including the refused give-up that can close a pass.
- Changed `policy/quiz_page.py`: `ending` returns `next` and, after a pass only, `back`. The "Well done" screen has "Going back to <host>", "Go now", and the countdown, Enter, and "Next task" handling in the shared script.
- Changed `policy/arithmetic_page.py`, `policy/skip_counting_page.py`, `policy/spelling_page.py`, and `policy/parts_of_speech_page.py` to return `back` with a pass and hand it to `finish`. Spelling keeps it until "Continue" on the missed-words screen.
- Changed `tests/page_harness.js` to record `window.location.assign` as a navigation, and `tests/conftest.py` to add `run_page` and `needs_node`.
- Changed `tests/test_arithmetic.py`, `tests/test_skip_counting.py`, `tests/test_spelling.py`, and `tests/test_parts_of_speech_quiz.py`: each `Quiz` helper can pass `back`, with tests that a pass carries it, a failure does not, and the page counts down, goes at "Go now" or Enter, and stops at "Next task".
- Changed `tests/test_enforce_decisions.py`: through the real proxy, the decision request carries `Sec-Fetch-Dest` and `Accept`. curl's default `Accept: */*` is now part of the logged request.
- Changed `README.md` and `docs/hierarchical-policy.md` to describe which requests are remembered, when he is sent back, and when the URL is forgotten.

## Change Summary

The proxy passes the two headers through. After each YAML decision, the decisions service remembers the URL for the client address when the deciding rule said `revision_task`, the final answer is a redirect, the method is `GET`, the request is a page load, and the URL is not on the policy server. A later such request from that address replaces it. When the final answer is an allow for exactly the remembered URL from that address, the row is deleted. The row records the household day, and a row from an earlier day is never used. It is not deleted until it is replaced or forgotten.

When a quiz attempt passes, the pass is stored first. Then the service looks up the URL for the task page's client address and runs `judge` on it at the current time, against the usage ledger, without task selection. Task selection never turns an off-site URL into an allow, and without it a hypothetical redirect cannot move the task rotation. An allow puts the URL in the reply as `back`. A failure or abandonment never asks for it, and a `parent_check` pass does not go through a quiz page, so nothing is sent back after any of those.

On "Well done" the shared script shows "Going back to" with `new URL(back).host`, shows and focuses "Go now", hides "All done for now", and opens the URL with `location.assign` after 5000 ms. "Go now" and Enter open it at once, unless focus is on "Next task". "Next task" clears the countdown before it opens the picker. The skip counting and parts of speech failure screens never count down.

Checked in a real browser against a local service on plain HTTP. With a YouTube page load and a later `Sec-Fetch-Dest: image` request both redirected, passing the arithmetic task showed "Well done", "Going back to www.youtube.com", "Go now", and "Next task". About 5 seconds later the tab was at `https://www.youtube.com/watch?v=abc123`.

The full suite has 1260 passing tests, including the Docker proxy tests. 55 of them are new.

## Suggested Acceptance Testing

### Acceptance test cases for S015

Use the policy, task, and proxy setup at the top of the Acceptance Criteria.

1. In Firefox, open `https://www.youtube.com/watch?v=<id>`. You are sent to the arithmetic task. Pass it. "Well done" says "Going back to www.youtube.com", and about 5 seconds later the same video opens in that tab.
2. Block the video again, pass again, and press "Go now" on "Well done". The video opens straight away. Repeat with Enter instead of "Go now".
3. Set `tasks_required` to 2, assign two tasks, and restart `decisions`. Open a video. Passing the first task shows "Well done" and "Next task" with no countdown. Passing the second sends you to the video.
4. Open one video, then a different one, both redirected. Passing the task sends you to the second video.
5. With a second eligible task, choose "Next task" during the countdown. The countdown stops and the next task opens. Passing it sends you to the remembered video.
6. After you have been forwarded to the video once, pass another task. "Well done" is the normal screen with no countdown. Then block a new video, pass a task, and choose "Next task" during the countdown. In another tab, type the new video's URL. It opens, because it is allowed now. Pass the next task. "Well done" is the normal screen again.
7. Use up the entertainment quota, or set a time window that has closed, so YouTube is denied after a pass. "Well done" is unchanged, with no countdown.
8. Two computers in one client group: on A open video 1, then on B open video 2. Pass on A, and A goes to video 1. Pass on B, and B goes to video 2.
9. Two computers in different client groups: a page blocked on one is never opened after a pass on the other.
10. Block a video, run `docker compose restart decisions`, and pass a task. The video opens.
11. Plain `http`: `curl -x http://<proxy>:<port> -H 'Accept: text/html' 'http://<blocked host>/some/path?x=1'` is redirected to the task. Pass the task in Firefox on that computer. "Well done" goes back to `http://<blocked host>/some/path?x=1`.
12. After a blocked page load in Firefox, run `curl -x ... --cacert mitmproxy-ca-cert.pem -X POST -d a=1 https://www.youtube.com/post-target`. It is redirected. Pass the task. You go back to the Firefox page, not the POST target.
13. After a blocked page load, run `curl -x ... --cacert ... -H 'Sec-Fetch-Dest: image' https://www.youtube.com/thumb.jpg` and `curl -x ... --cacert ... https://www.youtube.com/api`. Both are redirected, and the pass still goes back to the page.
14. A site group redirected to an absolute URL in the policy file, and a denied site, are not remembered. The pass goes back to the earlier `revision_task` page, or shows the normal "Well done" when there was none.
15. Open `https://<policy host>:<port>/tasks/next` directly, and open a task page that redirects to another task, with nothing else blocked. The pass shows the normal "Well done".
16. Block a video, then pass a task on the next household day. "Well done" is normal.
17. Repeat test 1 with skip counting, parts of speech, and spelling tasks. For spelling, finish with a missed word: there is no countdown on "Words to practise". "Continue" brings up "Well done", and the countdown starts.
18. A failure, a give-up, and a `parent_check` recorded from `/attempts` send you nowhere. After them, a pass still goes back to the remembered page.
19. In `/tmp/decisions.jsonl` inside `decisions`, a Firefox page load's request shows `sec_fetch_dest` and `accept`.
20. Read the new "Back to the page he was sent away from" sections in `README.md` and `docs/hierarchical-policy.md`.
