/**
 * Reviewing the clips cut from a take against the items that were meant to be said.
 *
 * The review steps through the items and the clips together. Keep gives the
 * item this clip. Junk throws the clip away and keeps the item. Discard
 * throws the clip away and moves on to the next item. Missing moves on to the
 * next item and keeps the clip. Back undoes the last of these. The review is
 * over when the items or the clips run out.
 */

export type Kind = "word" | "sentence";
/** One thing to say, such as the word rope or its sentence. ``line`` is what the dialog asks for. */
export type Item = { key: string; kind: Kind; line: string };
export type Decision = "keep" | "junk" | "discard" | "missing";
export type Outcome = { kind: "kept"; clip: number } | { kind: "discarded" } | { kind: "missing" };

type Step = { item: number; clip: number; outcomes: (Outcome | undefined)[] };
export type Review = Step & { history: Step[] };

export function startReview(items: number): Review {
  return { item: 0, clip: 0, outcomes: Array(items).fill(undefined), history: [] };
}

export function reviewOver(review: Review, items: number, clips: number): boolean {
  return review.item >= items || review.clip >= clips;
}

export function decide(review: Review, decision: Decision, items: number, clips: number): Review {
  if (reviewOver(review, items, clips)) return review;
  const { history: _history, ...step } = review;
  const history = [...review.history, step];
  const outcomes = [...review.outcomes];
  switch (decision) {
    case "keep":
      outcomes[review.item] = { kind: "kept", clip: review.clip };
      return { item: review.item + 1, clip: review.clip + 1, outcomes, history };
    case "junk":
      return { ...step, clip: review.clip + 1, history };
    case "discard":
      outcomes[review.item] = { kind: "discarded" };
      return { item: review.item + 1, clip: review.clip + 1, outcomes, history };
    case "missing":
      outcomes[review.item] = { kind: "missing" };
      return { item: review.item + 1, clip: review.clip, outcomes, history };
  }
}

export function undo(review: Review): Review {
  const last = review.history[review.history.length - 1];
  if (last === undefined) return review;
  return { ...last, history: review.history.slice(0, -1) };
}

/** Each item's outcome once the review is over. An item the clips never reached is missing. */
export function outcomes(review: Review): Outcome[] {
  return review.outcomes.map((outcome) => outcome ?? { kind: "missing" });
}

/** How many clips were never reviewed because the items ran out first. */
export function leftOver(review: Review, items: number, clips: number): number {
  return review.item >= items ? Math.max(0, clips - review.clip) : 0;
}
