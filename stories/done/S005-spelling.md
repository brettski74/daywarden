Ticket: S005
Title: Spelling quiz
Status: Done
Story Points: 13
Last Updated: 2026-11-04 20:09:00
---

# User Voice

As a parent, I want him to spell this week's words, plus a few older ones, from audio recordings stored in a directory on the host machine, so that he is revising spelling by ear rather than copying words off the screen and I can update word lists without rebuilding the container image.

# Use Cases

- A host data directory (`$HOME/daywarden` by default, configured via `DAYWARDEN_DATA_DIR`) is mounted into the policy container so tasks have a standard place on the host for parent-managed files.
- A spelling task uses two word pool directories (`spelling/current` and `spelling/revision` by default) and an alphabet audio directory (`spelling/alphabet` by default) under that data root.
- Words in each pool are defined by file naming convention: `<word>.<ext>` (or `<word>.<n>.<ext>` for homographs) for the word spoken alone, and an optional `<word>.sentence.<ext>` (or `<word>.<n>.sentence.<ext>`) for the word used in a sentence.
- He hears the word, types it into a large box, and can click large blue buttons to replay the word (up to `maximum_replays` times, default 3) or hear it used in a sentence (up to `maximum_sentence_plays` times, default 2, when a sentence clip exists). While audio plays, the timer pauses and the input box and audio buttons are disabled, preserving anything he has already typed; once a button's limit is reached, that button stays disabled for the rest of the question.
- The task is done when every word in `current` has been asked at least once and both pools have met their required correct counts (`current_required` and `revision_required`).
- When a missed word is placed back on the queue, its spelling is not shown on screen. When a missed word will not be asked again, the correct spelling is shown briefly before moving on.
- When the quiz completes or when he gives up, if he missed any words during the current attempt, the page displays the list of missed words in a three-column layout using a large font and pauses until he clicks a button or presses Enter before proceeding to the end screen or the next task.
- Practice mode walks the `current` words plus any `revision` words he missed in the current attempt in random order, showing each word on screen while playing the word and spelling it out letter by letter three times from the `alphabet` audio files, then starts a fresh quiz from zero.

# Acceptance Criteria

- [x] S005.1 and S005.2 are done.
- [x] Adding, updating, or moving word audio files in the host directories takes effect on the next quiz run without rebuilding the container image or restarting the container.
- [x] The quiz is not complete until every word in `current` has been asked at least once and both correct-count targets are met. A pass mark of 7 when `current` has 10 words still asks the remaining 3 words.
- [x] Completing a spelling quiz attempt increments today's revision pass count from S003.1; practice mode does not.

# Child stories

| Ticket | Title | Points |
| --- | --- | --- |
| S005.1 | Spelling quiz | 8 |
| S005.2 | Spelling practice mode | 5 |
| S005.3 | Spelling audio processor | 5 |
| S005.4 | Spelling feedback pause | 1 |
| S005.5 | Spelling play allowance | 2 |
| S005.6 | Spelling practice pauses | 1 |
| S005.7 | Configurable clip guard | 1 |
| S005.8 | Clip loudness normalization | 2 |
| S005.9 | Cut several recordings in one run | 2 |
| S005.10 | Always or never replace clips | 1 |

# Notes

Depends on S003 and S004.1. He is asked every word from `current` even after the pass mark for that pool is reached. Wrong `current` words go back on the queue only while the correct count for `current` is still below `current_required`. Text-to-speech generation of audio files is out of scope; the parent provides the audio files in the host directories.

A spelling task can carry `available_from`, `due_date`, `max_skips`, and `max_passes` from S003.1. There is no failure outcome, so a required spelling task stays required until he passes it or a parent changes the assignment. Give-up follows S003.2. Practice mode is part of continuing the current attempt (resetting the quiz scores to zero) rather than abandoning the task, so it is always available even when the spelling task is required.
