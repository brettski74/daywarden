# Stories

Stories are markdown files in the `stories` directory, one per story, named `Snnn-short-title.md`. Write every story
from `stories/Sxxx-story-template.md`. Story numbers are `Snnn`, three digits, counting up from 000. An epic's child
stories are `Snnn.m`. Lower values of m usually come first and may be dependencies of later children, but this is not
a strict rule.

Each file starts with the template's data block, which ends with a `---` line: Ticket, Title, Status (Draft, Refined,
In Progress, or Done), Story Points, and Last Updated (`yyyy-mm-dd HH:MM:SS`). Every story has User Voice and Behaviour
sections. Scenarios, Child stories, and Notes are added only when they have something to say.

## Writing stories

The reviewer reads every story, and reading the same thing twice is the slowest part of that review. These rules
apply to every story, epic, and implementation summary:

1. **Say each thing once.** A fact appears in one place. Refer to it rather than restating it, and refer to another
   story, as in "Saving works as in S023.2", rather than repeating its behaviour.
2. **Behaviour is the one list of what the story delivers.** It is grouped under level 2 headings by area. Each item a
   reviewer can check through the external interfaces below is a checkbox, `- [ ]`, ticked `- [x]` once accepted.
   Detail that is not a check of its own, such as an icon name, a list of accepted values, a file layout, or the
   wording of a message, is a plain bullet or sits inside the check it belongs to.
3. **An example goes inside the check it illustrates,** not in an item of its own.
4. **Behaviour inherited from another story is one check,** such as "Save, Ctrl+S, and the unsaved-changes prompt work
   as in S023.2."
5. **Scenarios are optional.** A scenario is a short narrative of a user reaching a goal across several features. It
   states no rule of its own. Write one only when it shows how the features fit together in a way the Behaviour list
   does not.
6. **Notes do not repeat Behaviour.** They hold dependencies, design and implementation hints, what is out of scope,
   and why the story is sized as it is.
7. **A change during review edits the item in place.** Do not add a second item that amends an earlier one.
8. **An epic's Behaviour holds only the checks that span its children,** such as "S004.1 to S004.6 are done". Each
   child's checks are in the child.

## Acceptance through external interfaces

Code review is rare. The reviewer accepts a story through the interfaces a user can see: the policy file and other
configuration, files in the data directory, the web pages (the child's quiz pages, the parent pages, and what the proxy
allows, blocks, or redirects), and the command-line tools such as `bin/daywarden` and `bin/cut-clips`. Write each check
through those interfaces: what to put in the configuration, what to do in the browser or on the command line, and what
should be seen. Do not write checks as SQL queries, scripts, or calls to internal APIs. Database changes and internal
behaviour are accepted through the features that use them. The automated tests cover the internals.

## Story points

- Use Fibonacci numbers: 1, 2, 3, 5, 8, 13, 21.
- An epic's points are the sum of its children's.
- Size a story against stories already implemented that took a similar effort to build and test. A story of m + n
  points is about the effort of one of m points plus one of n points.
- Consistent relative sizes are the goal, not precision.

### Reference size for one story

S006.1, S006.2, and S006.3 were implemented one after another in a single session, and together they used about 40% of
the context window. Together they were 14 points (3 + 8 + 3) and 39 checks. They covered a new task type and its
policy-file checks, a drag-and-drop quiz page with a timer, scoring, and resume, and the red marks and answer table
after a wrong try. That work should have been one story, and one story can hold somewhat more than that. S007.4 used
about 475k tokens, which is still less than 50% of the context window, and was a 21-point story. Size single stories
against these references. 13 and 21 are normal sizes for one story. 1 to 5 points is a small change.

## When to make a story an epic

Keep work in one story by default. Parts that could be accepted separately are not, on their own, a reason to split. One
story with a longer Behaviour list is cheaper to implement and review than several small ones. Measure size against
the reference in "Reference size for one story" above.

Split a story into an epic with child stories only when any of these is true:

1. It is larger than 21 points. A 34-point estimate is always an epic.
2. One implementation session would struggle to hold it. As a guide, finish a story within about 60% of the model's
   context window. The reference work used about 40%. Tool output, test runs, browser snapshots, and re-reading edited
   files use far more context than reading the code once. Split when the code, tests, and browser checking clearly go
   beyond about one and a half times the reference work.
3. Its Behaviour would hold more than about 50 checks.
4. One part carries a risk the rest does not, and that risk is worth seeing working and accepted before the rest is
   built. Examples are a change to what the proxy allows or redirects, or an upgrade of stored household data.
5. Some of the work is not wanted yet, such as a feature planned for a later release. Put it in a later child instead of
   leaving it out.

When an epic is needed, make each child as large as these rules allow. Do not split it into many small children.

Do not split, even when the story is large, when:

- Most of a child's deliverables would have no consequence that can be seen through the external interfaces. A database change, an internal refactor, or a server API with no page to use it is accepted through the feature that uses it, so it belongs in the same story as that feature.
- The children would rewrite the same code or tests in turn, such as each updating the same test fixtures.
- A child could not be accepted until the next child is done.

Prefer to split along features a user can see, such as a working quiz first and its extra feedback screens second, rather than along layers such as configuration, server, and page.

## Implementation summary

After implementing a story, append an `# Implementation` section to the end of the story, with these level 2
headings. The house rules above apply here too.

- **Files Added, Files Changed, Files Removed.** Each file with a short note of what it holds or what changed.
- **Change Summary.** What was built, in a few paragraphs, and the internal choices a reviewer should know about, such
  as a library not used and why. A choice that changes what the reviewer sees is not described here. Instead, edit
  its Behaviour item in place, starting it with *Changed in implementation:*, or add a new check starting with *Added
  in implementation:*.
- **Suggested Acceptance Testing.** Under a heading such as `### Acceptance test cases for Snnn`, a numbered list of
  test sessions, most important first. Each gives what the reviewer needs to set up, such as configuration, commands,
  or data, and names the Behaviour area or checks it covers, without restating them. Together the sessions cover
  every check. Give the same list in the chat response.

# Python Environment

Run all Python in this repository, including the tests, with the workspace virtual environment at `.venv`. Never use
the system `python3`, `pytest`, or `pip` directly. The system Python is missing packages the code imports, such as
`argon2`, which shows up as `ModuleNotFoundError: No module named 'argon2'` when tests are collected, and Arch refuses
`pip install` into the system Python.

- `make venv` creates `.venv` and installs `requirements-dev.txt`, which includes `policy/requirements.txt` and
  `pytest`. It does nothing when `.venv` is already up to date, and reinstalls by itself when either requirements file
  changes, so it is always safe to run first. The first run needs network access to PyPI.
- `make test` runs the whole suite, building the venv first if needed. Pass pytest arguments with `ARGS`, such as
  `make test ARGS="tests/test_clips.py -q"`. `.venv/bin/python -m pytest tests/test_clips.py` works too.
- Run one-off scripts and modules from the repository root with `.venv/bin/python`, such as
  `.venv/bin/python -m policy.clips --help`. `bin/cut-clips` uses `.venv` automatically when it exists.
- A package the policy service needs at runtime goes in `policy/requirements.txt`, which the container image also
  installs. A package only the tests or host tools need goes in `requirements-dev.txt`. Pin exact versions in both.
- If `.venv` stops working, for example after a system Python upgrade, rebuild it with `rm -rf .venv && make venv`.
- Do not create throwaway venvs elsewhere, such as in `/tmp`, and do not use `--system-site-packages`.

Many tests start Docker Compose, so the full suite needs access to Docker. Agents running in a sandbox should run the
full suite outside it. It takes several minutes, so run it in the background. Tests that need `ffmpeg` or `node` are
skipped when those tools are not installed.

# Parent Portal

The parent pages are one React Router app under `/parent/`, with its source in `policy/portal/`. Read
`docs/parent-portal.md` before changing or adding a parent page. The rules there are binding. In short:

- Every navigation is a real `<a href>`, every page and choice has its own URL, and every action is a `<button>`.
- Signing in always returns to a portal page, never to a data address under `/parent/api/`. Data endpoints answer 401
  or 403 and never redirect.
- The portal makes no background requests that keep a session alive.
- Colours come only from role properties in the theme stylesheet. Components name no colour values.
- Icons come from Lucide. The portal loads nothing from outside the parent port.
- Every expand and collapse animates with `--expand-duration` and `--expand-easing`, 500ms of swing easing.
- An editing page saves only on Save or Ctrl+S, and asks before leaving with unsaved changes, with Stay as the default.
- Anything that can be dragged has a keyboard way to do the same. A page's own keys use Alt with a letter, such as Alt+N.
- The child's task pages are not part of the portal. Do not change their layout or design as part of portal work. The one
 shared piece of code is `policy/static/word_sort.js`, the word drag-and-drop.

# Testing

Any new feature or bugfix must implement or update at least one automated test. Implement as many tests are are required
to cover the reasonable set of use cases that the new feature or bugfix covers.

For bugfixes and wherever else is practical, prefer to implement tests first, then build the code to make those tests
pass, but this is not a hard rule and if new test cases don't become apparent until after the code is written, this
preference should not be an excuse to avoid writing those tests. The goal is good test coverage, not adherence to some
general guidelines.

Avoid writing pointless tests, such as tests that do nothing but mirror a set of constants, configuration or data and
verify that the other copy is still the same. Similarly, don't write tests whose only purpose is to verify that static
UI elements are still the same static UI elements we just put into the UI layer. Tests that verify file contents rather
than functionality should also be avoided, especially files which are likely to change over time like .env, Makefile,
policy.yaml and the like. Tests should primarily be about testing functional code and verifying that the code behaves
the way it should, not a duplicate of static content elsewhere.

Tests need to pass. All tests should be passing for work on a story to be considered done. If there are failing tests,
then you need to work to figure out why they're failing, what needs to be done to fix them and fix them. Tests that are
failing and no longer relevant or that meet the definition of pointless tests above should be removed.
