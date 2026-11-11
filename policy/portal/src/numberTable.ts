import { newId } from "./sentences";

/** A row's Multiples Only: the task's setting, Yes, or No. */
export type Multiples = "" | "yes" | "no";

/** One entry of a weighted list as its table shows it. Every box holds its text as typed. */
export type NumberRow = {
  id: string;
  /** Its place in the list it was loaded from, or null for a new row. */
  origin: number | null;
  from: string;
  to: string;
  weight: string;
  min: string;
  max: string;
  multiples: Multiples;
};

/** A row as the service sends and takes it. */
export type ServiceRow = {
  from: string;
  to: string;
  weight: string;
  minimum_value?: string;
  maximum_value?: string;
  multiples_only?: boolean | null;
};

export type Box = "from" | "to" | "weight" | "min" | "max";

export const BOX_LABELS: Record<Box, string> = { from: "From", to: "To", weight: "Weight", min: "Min", max: "Max" };
export const BOX_FIELDS: Record<Box | "multiples", string> = {
  from: "from",
  to: "to",
  weight: "weight",
  min: "minimum_value",
  max: "maximum_value",
  multiples: "multiples_only",
};

/** What a table's numbers may be. */
export type TableRules = {
  /** Whether rows have their own Min, Max, and Multiples Only. */
  bounds: boolean;
  negatives: boolean;
  /** Whether 0 is a problem, as it is for a difference. */
  noZero: boolean;
  /** A check of the page's own, given each row whose From and To are good. */
  check?: (range: Range) => string[];
};

/** The task's Minimum Value and Maximum Value as now on the page, standing in for an empty Min or Max. */
export type Bounds = { minimum: number | null; maximum: number | null };

export type Range = { low: number; high: number };

export const ZERO_DIFFERENCE = "0 is not a difference. Write one range below zero and another above it.";

const WHOLE = /^-?[0-9]+$/;

export function whole(text: string): number | null {
  const trimmed = text.trim();
  return WHOLE.test(trimmed) ? Number(trimmed) : null;
}

export function newRow(): NumberRow {
  return { id: newId("n"), origin: null, from: "", to: "", weight: "", min: "", max: "", multiples: "" };
}

export function fromService(rows: ServiceRow[], prefix: string): NumberRow[] {
  return rows.map((row, index) => ({
    id: `${prefix}${index}`,
    origin: index,
    from: row.from,
    to: row.to,
    weight: row.weight,
    min: row.minimum_value ?? "",
    max: row.maximum_value ?? "",
    multiples: row.multiples_only === true ? "yes" : row.multiples_only === false ? "no" : "",
  }));
}

/** The rows a save sends: every row that is not empty. */
export function toService(rows: NumberRow[], bounds: boolean): ServiceRow[] {
  return rows
    .filter((row) => !isEmpty(row))
    .map((row) => ({
      from: row.from.trim(),
      to: row.to.trim(),
      weight: row.weight.trim(),
      ...(bounds
        ? {
            minimum_value: row.min.trim(),
            maximum_value: row.max.trim(),
            multiples_only: row.multiples === "yes" ? true : row.multiples === "no" ? false : null,
          }
        : {}),
    }));
}

/** A row is empty when every box in it is empty and Multiples Only is on the task's setting. */
export function isEmpty(row: NumberRow): boolean {
  return [row.from, row.to, row.weight, row.min, row.max].every((text) => text.trim() === "") && row.multiples === "";
}

/** The numbers a row holds, when its From and To are whole numbers in order. */
export function rangeOf(row: NumberRow): Range | null {
  const low = whole(row.from);
  if (low === null) return null;
  const high = row.to.trim() === "" ? low : whole(row.to);
  return high === null || high < low ? null : { low, high };
}

/** Each row's problems, in table order. An empty row has none. */
export function tableProblems(rows: NumberRow[], rules: TableRules, bounds: Bounds): string[][] {
  const ranges = rows.map((row) => (isEmpty(row) ? null : rangeOf(row)));
  return rows.map((row, index) => {
    if (isEmpty(row)) return [];
    const found = boxProblems(row, rules, bounds);
    const range = ranges[index];
    if (range === null) return found;
    if (rules.noZero && range.low <= 0 && range.high >= 0) found.push(ZERO_DIFFERENCE);
    found.push(...(rules.check?.(range) ?? []));
    ranges.forEach((other, place) => {
      if (place === index || other === null) return;
      if (other.low <= range.high && range.low <= other.high) found.push(`${Math.max(other.low, range.low)} is also in row ${place + 1}.`);
    });
    return found;
  });
}

function boxProblems(row: NumberRow, rules: TableRules, bounds: Bounds): string[] {
  const found: string[] = [];
  const boxes: Box[] = rules.bounds ? ["from", "to", "weight", "min", "max"] : ["from", "to", "weight"];
  const good: Partial<Record<Box, number>> = {};
  if (row.from.trim() === "") found.push("From is needed.");
  for (const box of boxes) {
    if (row[box].trim() === "") continue;
    const value = whole(row[box]);
    const anySign = box === "weight" || box === "min" || box === "max";
    if (value === null || (!rules.negatives && !anySign && value < 0)) {
      found.push(rules.negatives || anySign ? `${BOX_LABELS[box]} must be a whole number.` : `${BOX_LABELS[box]} must be a whole number, 0 or more.`);
    } else {
      good[box] = value;
    }
  }
  if (good.from !== undefined && good.to !== undefined && good.to < good.from) found.push("To is below From.");
  if (good.weight !== undefined && good.weight < 1) found.push("Weight must be 1 or more.");
  if (rules.bounds && (good.min !== undefined || good.max !== undefined)) {
    const low = row.min.trim() === "" ? bounds.minimum : (good.min ?? null);
    const high = row.max.trim() === "" ? bounds.maximum : (good.max ?? null);
    if (low !== null && high !== null && high <= low) found.push(`Max ${high} is not above Min ${low}.`);
  }
  return found;
}

/** The row as a save would write it, to compare two lists by what they hold. */
function written(row: NumberRow): string {
  const from = row.from.trim();
  const to = row.to.trim() === from ? "" : row.to.trim();
  return [from, to, row.weight.trim() || "1", row.min.trim(), row.max.trim(), row.multiples].join("\u0001");
}

/** Whether two lists hold the same entries in the same order, leaving out empty rows. */
export function sameRows(left: NumberRow[], right: NumberRow[]): boolean {
  const a = left.filter((row) => !isEmpty(row)).map(written);
  const b = right.filter((row) => !isEmpty(row)).map(written);
  return a.length === b.length && a.every((row, index) => row === b[index]);
}

/** Whether a box differs from the row it was loaded as. */
export function boxChanged(row: NumberRow, original: NumberRow | undefined, box: Box | "multiples"): boolean {
  if (original === undefined) return false;
  return box === "multiples" ? row.multiples !== original.multiples : row[box].trim() !== original[box].trim();
}
