Ticket: S013
Title: Giving up is always an abandonment
Status: Refined
Story Points: 1
Last Updated: 2026-11-05 01:20:00
---

# User Voice

As a parent, I want a quiz he gives up on to be recorded as abandoned, whatever his score was when he gave up, so that only a task he actually completes counts as a pass or a failure.

# Use Cases

## UC1 - Bug: a give-up can be recorded as a pass or a failure

- Today, a give-up that S003.2 allows closes the question showing as a timeout. If closing it decides the attempt, the attempt is recorded as that pass or failure instead of `abandoned`.
- Skip counting (S011) does this. For example, with `maximum_questions: 8`, giving up while the eighth question is showing records a `failure`. With `minimum_questions: 10` and enough points after nine questions, giving up on the tenth records a `pass`.
- Spelling (S005.1) does the same when closing the word showing completes the run. That is when it was the last current word not yet asked and both targets were already met. The give-up then records a `pass`.
- Arithmetic (S004.1) is already correct. A give-up there is always `abandoned`.

## UC2 - Fixed behaviour

- A give-up that S003.2 allows always finishes the attempt as `abandoned`, in every quiz type, whatever his points or progress. The question showing is still closed as a timeout and kept in the attempt record. The abandon follows S003.1 as any abandon does: it counts as a skip day, starts no cooldown, and does not count toward today's revision.
- A give-up that S003.2 refuses is unchanged.
- Finishing through a timeout that is not a give-up is unchanged. A reload, or coming back after a question's time, closes the question showing as a timeout. If that completes the run, the attempt passes or fails as usual, because he stayed in the attempt.

# Acceptance Criteria

- [ ] Skip counting with `maximum_questions: 8`: after seven questions with too few points to pass, giving up while the eighth is showing records `abandoned`, not `failure`. The task stays eligible, with no failure cooldown.
- [ ] Skip counting with `minimum_questions: 10` and 8 points required: with 8 points after nine questions, giving up while the tenth is showing records `abandoned`, not `pass`. Today's revision count does not go up.
- [ ] Spelling: with both targets met and one current word still to be asked, giving up while that word is showing records `abandoned`, not `pass`. The missed-words screen after a give-up still works as S005.1 describes.
- [ ] In each case, the attempt review shows the question that was showing as a timeout.
- [ ] Skip counting with `minimum_questions: 10` and 8 points after nine questions: reloading while the tenth question is showing, then coming back, still passes the attempt, as before.
- [ ] Arithmetic give-ups are still recorded as `abandoned`.
- [ ] `docs/hierarchical-policy.md` no longer says a give-up can record a pass or a failure.

# Notes

Found while refining S006, which states the same rule for parts of speech in S006.2 UC10.

The cause is the `settle` functions in `policy/skip_counting_page.py` and `policy/spelling_page.py`. Each returns the quiz's verdict after closing the question showing, falling back to `ABANDONED` only when there is no verdict. `policy/arithmetic_page.py` always returns `ABANDONED`. `tests/test_skip_counting.py::test_giving_up_on_the_last_question_records_the_failure_it_decides` asserts the wrong behaviour and changes with the fix.

The S011 story and its Implementation section describe the old behaviour. They are a record of what was built, and are left as they are.
