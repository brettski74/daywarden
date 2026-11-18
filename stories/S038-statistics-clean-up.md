Ticket: S038
Title: Statistics clean-up
Status: Draft
Story Points: 3
Last Updated: 2026-11-18 03:20:00
---

# User Voice

As a parent, I want to remove the spelling word and arithmetic fact figures that weight his questions, for one client
group, one word, or one fact, so that test runs and bad data stop affecting what he is asked.

# Behaviour

## Removing figures

The figures are the spelling word figures from S033 and the arithmetic fact figures from S037. Each is built from rows
kept for every attempt that asked the word or fact, so removing them can be narrowed by the age of the attempt.

- [ ] `bin/rm-stats` removes figures. `--client GROUP` narrows it to a client group, and `--type spelling` or
      `--type arithmetic` to one kind. `--word WORD` narrows spelling to one entry key, such as `rope` or `read.1`.
      `--operation OPERATION` narrows arithmetic to one operation, and `--fact M,N` to one fact, such as
      `--operation multiplication --fact 7,8`. Each may be given more than once. Several values for one filter match
      any of them, and different filters must all match, as in `rm-attempts`.
- [ ] `--older-than` and `--newer-than` take an age such as `30m`, `2h`, or `7d`, as in `rm-attempts`, measured from
      the start of the attempt that asked the word or fact. Only the figures from those attempts are removed, and the
      rest are counted again from what is left. A run and a smoothed time are worked out from the remaining answers
      in order.
- [ ] Without `--yes` it lists what matches, one line for each client group and word or fact, with how many asks
      would be removed, and changes nothing. With no filter it refuses unless given `--all`.
- [ ] After removal, `bin/word-stats` and the facts page show the remaining figures, a word or fact with nothing left
      is shown as never asked, and the next questions are weighted from what is left.
- [ ] `--rebuild` counts the figures again from the attempts still stored, for the client groups and kinds the filters
      choose, as the first start after S033 and S037 did. After `rm-attempts --all --yes`, `rm-stats --all --rebuild
      --yes` leaves no figures.
- [ ] It says `daywarden is not running. Start it with dw up.` when the stack is down, and is installed, linked, and
      documented beside `rm-attempts` in the README.

# Notes

Depends on S033 and S037.

Open questions for refinement:
- Is narrowing by age wanted, or is removing whole words and facts enough? Age is cheap because both ledgers keep one
  row per attempt, and it lets a parent forget a bad week without losing the rest.
- Is `--rebuild` wanted? It is the quickest way to put figures back in step with the stored attempts after testing.
- Should the facts page or `bin/word-stats` gain a way to do this, or is the command line enough?

Sized at 3: one maintenance command over two existing ledgers, with filters copied from `rm-attempts`.
