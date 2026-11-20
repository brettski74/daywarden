Ticket: S045
Title: Capitalisation help
Status: Refined
Story Points: 5
Last Updated: 2026-11-20 18:20:00
---

# User Voice

As a child, I want to open a page that tells me where capital letters go, with an example of each, and then go back to
the sentence I was answering, so that I can check a rule when I am not sure and still finish the sentence.

# Behaviour

## The Help button

- [ ] The capitalisation start screen and question screen show a smaller "Help" button at the bottom right, in the
      place and style of the Practice button on spelling and arithmetic tasks (S005.2). It is not shown on the answer
      screen after a sentence ends, or on the end screen.
- [ ] Help works for every `capitalisation` task with no policy setting, and a task's body has no field for it.

## The help page

- [ ] Clicking "Help" covers the sentence, his clicked words, and Submit with the help page. Nothing of the sentence
      can be seen or clicked while the help page is open, and Submit and Enter do not submit a try.
- [ ] The help page is in moderately large text, larger than the page's small print and smaller than the sentence, with a
      heading such as "Where do capital letters go?" and one point for each of these places, in this order:
      the first word of a sentence, the word "I", names of people, names of pets, names of places (towns, countries,
      streets), days of the week, months of the year, holidays, titles used with a name (such as Dr or Mr), and
      short names made of capitals (such as NASA). Each point is a short sentence a grade 3 reader can follow.
- [ ] Each point comes with an example sentence spelled correctly, with its capitals. The capitalised word that shows
      that point is in blue, in the blue of a clicked word, and every other word in the example is black. An example
      has no capital other than the one it shows, except the first word of the sentence, which is black unless the
      point is the first word, and a name that has to follow a title. The example for a point is never built on its
      first word, except the first-word point. For days of the week, "We are going to the zoo on Tuesday." shows
      `Tuesday` in blue and `We` in black.
- The examples are fixed in the page:
  - first word: "The dog ran home." (`The` blue)
  - "I": "Can I have a snack?" (`I` blue, `Can` black)
  - people: "We saw Mia at the park." (`Mia` blue)
  - pets: "Our dog is called Rex." (`Rex` blue)
  - places: "We drove to Sydney today." (`Sydney` blue)
  - days: "We are going to the zoo on Tuesday." (`Tuesday` blue)
  - months: "My birthday is in May." (`May` blue)
  - holidays: "We eat cake at Christmas." (`Christmas` blue)
  - titles: "We saw Dr Patel today." (`Dr` blue, `Patel` black because it is a name that has to follow the title)
  - short names made of capitals: "My uncle works for NASA." (`NASA` blue)
- [ ] The page scrolls when it does not fit the screen, with the "Back to my sentence" button always visible.

## Returning to the sentence

- [ ] A large "Back to my sentence" button, Escape, or clicking "Help" again closes the help page. The same
      sentence is there with the words he had clicked still blue, his tries unchanged, and the last hint as before.
- [ ] He can open and close help as many times as he likes during a sentence. Opening help is not a try, scores
      nothing, and changes no pass or fail count. Nothing about it is recorded in the attempt.
- [ ] Reloading with help open brings back the same sentence with help closed, as a reload does in S040.1.

## The timer

- [ ] The timer bar keeps running while help is open, and it is shown on the help page so he can see it. The
      parent gives a longer `timeout` (such as `180s`) on a task whose pool needs help time.
- [ ] When the bar empties with help open, the help page closes and the answer shows as a timeout, with his clicks as
      they stood, as in S040.1.

# Notes

Depends on S040.1 for the page. The help text and the examples are fixed in the page. A parent cannot edit them, and
they do not depend on the task's pools.

The timer is not paused. A pause would need the server to know about help, and a parent could not tell from the
attempt how long he really took. A longer `timeout` gives the same time to read with no new rules. If it turns out to
be too little, a pause is the next step, as its own story.

The page needs no keyboard way to click words, as in S040.1. Help has Escape and Enter on the focused "Back to my
sentence" button because it is a plain button.

Sized as a small change to one page. It adds a button, one overlay with fixed text, and a Chromium test that opens and
closes help during a sentence with words clicked, and across a timeout.
