Ticket: S032
Title: Spelling under Asset Administration
Status: Draft
Story Points: 21
Last Updated: 2026-11-15 20:54:50
---

# User Voice

As a parent, I want spelling word pools maintained under Asset Administration beside Parts of Speech Pools, so that
shared word lists live with the other reusable assets, while a spelling task still chooses which directories it uses
and can still replace the current week in one Apply.

# Behaviour

## Asset Administration

- [ ] Asset Administration gains a Spelling pools (or equivalent) entry that lists and opens the spelling word
      directories the household already uses under `spelling/` in the data directory.
- [ ] The spelling task page still sets which directories that task uses, and still runs Words › Replace Current, Add
      to Current, and Add to Revision as in S023.4 and S028. Those modes keep their meaning:
  - Replace Current moves current words that are not on the new list into revision, then fills current from the list.
  - Add to Current / Add to Revision add listed words without moving unlisted ones.
- [ ] Recording, Retire, attic, and alphabet behaviour from S023.2, S023.3, and S028 remain available; only their
      place in the navigation changes where this story moves them under Assets.

## Done when

- [ ] A parent can maintain spelling word pools from Asset Administration without losing the weekly Replace Current
      workflow, and the child's spelling quiz is unchanged.

# Notes

Follows S031.2's Asset Administration shell. Deliberately not part of S031: folding Replace Current, directory
pull-downs, and in-browser recording into the same epic as parts-of-speech pools would be scope creep.

Refine before implementation: how much of today's spelling task page moves under Assets versus staying on the task
(directories and Words menu may stay on the task while Assets edits directory contents), whether one directory can be
shared by two tasks without two editors fighting, and whether Assets lists directories or a higher-level "word pool"
concept.

Sizing: 21 as a placeholder against S028's directory and Words work; revisit when refined.
