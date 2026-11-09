import { describe, expect, it } from "vitest";
import { decide, leftOver, outcomes, reviewOver, startReview, undo, type Decision } from "./review";

function run(decisions: Decision[], items: number, clips: number) {
  return decisions.reduce((review, decision) => decide(review, decision, items, clips), startReview(items));
}

describe("reviewing clips against items", () => {
  it("keeps a clip for each item in turn", () => {
    const review = run(["keep", "keep"], 2, 2);
    expect(reviewOver(review, 2, 2)).toBe(true);
    expect(outcomes(review)).toEqual([
      { kind: "kept", clip: 0 },
      { kind: "kept", clip: 1 },
    ]);
  });

  it("junk moves to the next clip for the same item", () => {
    const review = run(["junk", "keep"], 1, 2);
    expect(outcomes(review)).toEqual([{ kind: "kept", clip: 1 }]);
  });

  it("discard moves to the next item and the next clip", () => {
    const review = run(["discard", "keep"], 2, 2);
    expect(outcomes(review)).toEqual([{ kind: "discarded" }, { kind: "kept", clip: 1 }]);
  });

  it("missing moves to the next item and stays on the same clip", () => {
    const review = run(["missing"], 2, 1);
    expect(review.item).toBe(1);
    expect(review.clip).toBe(0);
    expect(outcomes(decide(review, "keep", 2, 1))).toEqual([{ kind: "missing" }, { kind: "kept", clip: 0 }]);
  });

  it("back undoes the last decision, one at a time", () => {
    const review = run(["junk", "keep"], 2, 3);
    const once = undo(review);
    expect([once.item, once.clip, once.outcomes[0]]).toEqual([0, 1, undefined]);
    const twice = undo(once);
    expect([twice.item, twice.clip]).toEqual([0, 0]);
    expect(undo(twice)).toBe(twice);
  });

  it("counts the clips left over when the items run out, and marks unreached items missing when the clips do", () => {
    expect(leftOver(run(["keep"], 1, 4), 1, 4)).toBe(3);
    const short = run(["keep"], 3, 1);
    expect(reviewOver(short, 3, 1)).toBe(true);
    expect(leftOver(short, 3, 1)).toBe(0);
    expect(outcomes(short)).toEqual([{ kind: "kept", clip: 0 }, { kind: "missing" }, { kind: "missing" }]);
  });

  it("ignores decisions once the review is over", () => {
    const over = run(["keep"], 1, 1);
    expect(decide(over, "keep", 1, 1)).toBe(over);
  });
});
