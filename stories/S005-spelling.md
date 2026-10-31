Ticket: S005
Title: Spelling quiz
Status: Refined
Story Points: 21
Last Updated: 2026-10-31 12:31:02
---

# User Voice

As a parent, I want him to spell this week's words, plus a few older ones, from audio only, so that he is revising spelling rather than copying the word off the screen.

# Use Cases

- Two pools: this week's words, and a revision pool. Either pool may be any length.
- He hears the word, types it, and can replay the word or hear it in a sentence. The timer pauses during replay and the box will not accept typing while the audio plays.
- The task is done when this week's words have all been asked and both pools have enough correct spellings.
- Practice mode shows and spells this week's words, then returns him to a fresh quiz.
- The parent records the audio. Each word has a clip of the word alone and a clip of a sentence containing it. Generated speech is a later option, not the way the first lists are made.

# Acceptance Criteria

- [ ] S005.1, S005.2, and S005.3 are done before spelling is finished for the initial build.
- [ ] Spelling works from audio files the parent recorded. It does not require S005.4.
- [ ] The quiz is not complete until every this-week word has been asked at least once and both correct-counts are met. A pass mark of 7 when this week's pool has 10 words still asks the other 3.

# Child stories

| Ticket | Title | Points |
| --- | --- | --- |
| S005.1 | Word pools, targets, and audio | 3 |
| S005.2 | Spelling quiz flow | 8 |
| S005.3 | Spelling practice mode | 5 |
| S005.4 | Generate spelling audio (later) | 5 |

# Notes

Depends on S003. He is asked every word from this week's pool even after the pass mark for that pool is reached. Wrong this-week words go back on the queue only while the correct count for that pool is still short. S005.4 is not part of the initial build.

A spelling task can carry `available_from`, `due_date`, `max_skips`, and `max_passes` from S003.1. A due date is a fit for "he attempts this week's words at least once." The next week's words are a new spelling task when the previous task should stay passed. There is no failure outcome, so a required spelling task stays required until he passes it or a parent changes the assignment. Give-up and practice follow S003.2.
