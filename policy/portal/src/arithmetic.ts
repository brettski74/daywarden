import { fromService, isEmpty, sameRows, tableProblems, toService, type NumberRow, type Range, type ServiceRow, type TableRules } from "./numberTable";
import { label } from "./labels";
import type { ListEdits } from "./skipCounting";

export type ArithmeticData = {
  settings: Record<string, string>;
  operations: { name: string; label: string }[];
  first: ServiceRow[];
  operands: ServiceRow[];
  problems: string[];
};

export const SETTINGS = ["max_timeout", "min_timeout", "correct_answers_required"];
export const NO_OPERANDS = "Add a number.";
export const NO_FIRST = "With no first numbers, both numbers are drawn from Operands.";
export const NO_ZERO_DIVISOR = "Division cannot divide by 0.";
/** How each operation uses the two tables. */
export const USES: Record<string, string> = {
  addition: "first + operand",
  subtraction: "(first + operand) \u2212 first, and the answer is the operand",
  multiplication: "first \u00d7 operand",
  division: "(first \u00d7 operand) \u00f7 first, and the answer is the operand",
};
const RULES: TableRules = { bounds: false, negatives: false, noZero: false };
const DIVISOR: TableRules = { ...RULES, check: (range: Range) => (range.low <= 0 ? [NO_ZERO_DIVISOR] : []) };

export type ShownTable = { rows: NumberRow[]; originals: NumberRow[]; changed: boolean };
export type ShownArithmetic = {
  operation: string;
  first: ShownTable;
  operands: ShownTable;
  settingProblems: Record<string, string>;
  firstProblems: string[][];
  operandProblems: string[][];
  /** Every problem on the page. */
  count: number;
};

function table(rows: ServiceRow[], prefix: string, edit: ListEdits[string] | undefined): ShownTable {
  const originals = fromService(rows, prefix);
  const now = Array.isArray(edit) ? edit : originals;
  return { rows: now, originals, changed: !sameRows(now, originals) };
}

export function hasNumbers(rows: NumberRow[]): boolean {
  return rows.some((row) => !isEmpty(row));
}

/** What the page shows: both tables, and each problem where it is shown. */
export function shownArithmetic(data: ArithmeticData, settings: Record<string, string>, lists: ListEdits): ShownArithmetic {
  const value = (key: string) => settings[key] ?? data.settings[key] ?? "";
  const operation = value("operation").trim();
  const first = table(data.first, "f", lists.first);
  const operands = table(data.operands, "o", lists.operands);
  const settingProblems = Object.fromEntries(
    ["operation", ...SETTINGS].filter((key) => value(key).trim() === "").map((key) => [key, `${label(key)} is required.`]),
  );
  // Division draws the number it divides by from First, or from Operands when First is empty.
  const divides = operation === "division";
  const firstDrawn = hasNumbers(first.rows);
  const firstProblems = tableProblems(first.rows, divides && firstDrawn ? DIVISOR : RULES, { minimum: null, maximum: null });
  const operandProblems = tableProblems(operands.rows, divides && !firstDrawn ? DIVISOR : RULES, { minimum: null, maximum: null });
  const count =
    Object.keys(settingProblems).length +
    [...firstProblems, ...operandProblems].reduce((total, found) => total + found.length, 0) +
    (hasNumbers(operands.rows) ? 0 : 1);
  return { operation, first, operands, settingProblems, firstProblems, operandProblems, count };
}

export function problemsText(shown: ShownArithmetic): string {
  return shown.count === 0 ? "No problems." : `${shown.count} problem${shown.count === 1 ? "" : "s"}.`;
}

/** The lists a save sends: each one changed. An empty First is sent empty, which leaves it out of the file. */
export function arithmeticLists(shown: ShownArithmetic): Record<string, ServiceRow[]> {
  const lists: Record<string, ServiceRow[]> = {};
  if (shown.first.changed) lists.first = toService(shown.first.rows, false);
  if (shown.operands.changed) lists.operands = toService(shown.operands.rows, false);
  return lists;
}
