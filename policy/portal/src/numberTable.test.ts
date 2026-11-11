import { describe, expect, it } from "vitest";
import { ZERO_DIFFERENCE, newRow, sameRows, tableProblems, toService, type NumberRow, type TableRules } from "./numberTable";
import { defaultRequired } from "./skipCounting";

const DIFFERENCES: TableRules = { bounds: true, negatives: true, noZero: true };
const OPERANDS: TableRules = { bounds: false, negatives: false, noZero: false };
const TASK = { minimum: 1, maximum: 999 };

function row(from: string, to = "", more: Partial<NumberRow> = {}): NumberRow {
  return { ...newRow(), from, to, ...more };
}

function problemsOf(rows: NumberRow[], rules = DIFFERENCES, bounds = TASK) {
  return tableProblems(rows, rules, bounds);
}

describe("a row's problems", () => {
  it("needs From once anything else in the row is filled in, and an empty row has none", () => {
    expect(problemsOf([row("", "", { weight: "2" }), newRow()])).toEqual([["From is needed."], []]);
  });

  it("marks a box that is not a whole number, To below From, and a Weight below 1", () => {
    expect(problemsOf([row("2.5")])[0]).toEqual(["From must be a whole number."]);
    expect(problemsOf([row("9", "3")])[0]).toEqual(["To is below From."]);
    expect(problemsOf([row("2", "", { weight: "0" })])[0]).toEqual(["Weight must be 1 or more."]);
    expect(problemsOf([row("2", "", { weight: "x" })])[0]).toEqual(["Weight must be a whole number."]);
  });

  it("marks a Max not above Min, an empty one standing for the task's value", () => {
    expect(problemsOf([row("2", "", { max: "0" })])[0]).toEqual(["Max 0 is not above Min 1."]);
    expect(problemsOf([row("2", "", { min: "1000" })])[0]).toEqual(["Max 999 is not above Min 1000."]);
    expect(problemsOf([row("2", "", { min: "50" })], DIFFERENCES, { minimum: 1, maximum: 40 })[0]).toEqual(["Max 40 is not above Min 50."]);
    expect(problemsOf([row("-2", "", { min: "-50", max: "-10" })])[0]).toEqual([]);
  });

  it("names the first number two rows share, counting every number in a range", () => {
    expect(problemsOf([row("5"), row("2"), row("5")])).toEqual([["5 is also in row 3."], [], ["5 is also in row 1."]]);
    expect(problemsOf([row("3", "9"), row("7", "12")])).toEqual([["7 is also in row 2."], ["7 is also in row 1."]]);
  });

  it("refuses 0 as a difference, alone or inside a range, and accepts negatives", () => {
    expect(problemsOf([row("0")])[0]).toEqual([ZERO_DIFFERENCE]);
    expect(problemsOf([row("-5", "5")])[0]).toEqual([ZERO_DIFFERENCE]);
    expect(problemsOf([row("-5", "-1"), row("1", "5")])).toEqual([[], []]);
  });

  it("accepts 0 and refuses a negative number in a table of operands, and runs the page's own check", () => {
    expect(problemsOf([row("0", "3")], OPERANDS)[0]).toEqual([]);
    expect(problemsOf([row("-1")], OPERANDS)[0]).toEqual(["From must be a whole number, 0 or more."]);
    expect(problemsOf([row("1", "-3")], OPERANDS)[0]).toEqual(["To must be a whole number, 0 or more."]);
    const division = { ...OPERANDS, check: (range: { low: number }) => (range.low <= 0 ? ["Division cannot divide by 0."] : []) };
    expect(problemsOf([row("0", "4"), row("5")], division)).toEqual([["Division cannot divide by 0."], []]);
  });
});

describe("comparing and sending rows", () => {
  it("treats an empty Weight as 1 and a To equal to From as empty, and leaves out empty rows", () => {
    expect(sameRows([row("3", "3", { weight: "" }), newRow()], [row("3", "", { weight: "1" })])).toBe(true);
    expect(sameRows([row("3", "", { multiples: "yes" })], [row("3")])).toBe(false);
  });

  it("sends each row that is not empty, with Min, Max, and Multiples Only only where the table has them", () => {
    const rows = [row(" 3 ", "9", { weight: "10", max: "99" }), newRow(), row("5", "", { multiples: "no" })];
    expect(toService(rows, true)).toEqual([
      { from: "3", to: "9", weight: "10", minimum_value: "", maximum_value: "99", multiples_only: null },
      { from: "5", to: "", weight: "", minimum_value: "", maximum_value: "", multiples_only: false },
    ]);
    expect(toService(rows, false)[0]).toEqual({ from: "3", to: "9", weight: "10" });
  });
});

describe("the default Correct Answers Required", () => {
  it("is 8, or four fifths of the minimum questions, and never more than the maximum", () => {
    expect(defaultRequired("", "")).toBe(8);
    expect(defaultRequired("", "5")).toBe(5);
    expect(defaultRequired("12", "")).toBe(10);
    expect(defaultRequired("12", "9")).toBe(9);
    expect(defaultRequired("abc", "0")).toBe(8);
  });
});
