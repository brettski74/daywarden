/** The arithmetic facts page: its data, the address of its choices, the list's sort, and the grid's shading. */

import { formatSeconds, viewQuery, type PeriodData, type View } from "./attempts";

export type FactAttempt = { id: number; answers: string[] };

/** A fact's figures from his whole record, whatever the period and filters, and the weight that chooses his questions (S037). */
export type AllTime = {
  asked: number;
  run: number;
  smoothed_ms: number | null;
  miss_boost: number;
  slow_boost: number;
  weight: number;
};

/** The operation's median smoothed time and where the slow boost starts and is full, or that too few facts are timed yet. */
export type Slow = {
  median_ms: number | null;
  start_ms: number | null;
  full_ms: number | null;
  timed_facts: number;
  facts_needed: number;
  answers_needed: number;
  text: string;
};

export type Fact = {
  m: number;
  n: number;
  /** The question as asked, such as ``6 × 7``. */
  cell: string;
  /** The question with its answer, such as ``6 × 7 = 42``. */
  text: string;
  asked: number;
  right: number;
  wrong: number;
  timeouts: number;
  missed: number;
  missed_percent: number;
  median_ms: number | null;
  last_missed: string | null;
  last_missed_day: string | null;
  attempts: FactAttempt[];
  all_time: AllTime;
};

export type FactsData = {
  rows: number[];
  columns: number[];
  facts: Fact[];
  attempts: Record<string, { started: string; task: string }>;
};

export type FactsReport = PeriodData & {
  clients: string[];
  client: string;
  view: View;
  notes: string[];
  times: string;
  operation: { name: string; label: string };
  operations: { name: string; label: string }[];
  message: string | null;
  slow: Slow | null;
  facts: FactsData | null;
};

/** Choices that are the page's alone. The data does not change with them. */
export const PAGE_KEYS = ["m", "n", "shade", "sort", "dir"];

export type Shade = "misses" | "time" | "weight";
export const SHADES: { key: Shade; label: string }[] = [
  { key: "misses", label: "Misses" },
  { key: "time", label: "Time" },
  { key: "weight", label: "Weight" },
];
export type SortKey =
  | "fact"
  | "asked"
  | "right"
  | "wrong"
  | "timeouts"
  | "missed"
  | "median"
  | "last"
  | "all_asked"
  | "run"
  | "smoothed"
  | "miss_boost"
  | "slow_boost"
  | "weight";
export type Dir = "asc" | "desc";

/** The list's columns. The all-time ones come from his whole record, whatever the period and filters. */
export const COLUMNS: { key: SortKey; label: string; allTime?: true }[] = [
  { key: "fact", label: "Fact" },
  { key: "asked", label: "Asked" },
  { key: "right", label: "Right" },
  { key: "wrong", label: "Wrong" },
  { key: "timeouts", label: "Timeouts" },
  { key: "missed", label: "Missed" },
  { key: "median", label: "Median time" },
  { key: "last", label: "Last missed" },
  { key: "all_asked", label: "All-time asked", allTime: true },
  { key: "run", label: "Run", allTime: true },
  { key: "smoothed", label: "Smoothed time", allTime: true },
  { key: "miss_boost", label: "Miss boost", allTime: true },
  { key: "slow_boost", label: "Slow boost", allTime: true },
  { key: "weight", label: "Weight", allTime: true },
];

const DEFAULT_SORT: SortKey = "missed";

/** What the address chooses on the page itself: the chosen fact, the shading, and the list's sort. */
export type PageChoice = { m: number | null; n: number | null; shade: Shade; sort: SortKey; dir: Dir };

function whole(value: string | null): number | null {
  return value !== null && /^\d+$/.test(value) ? Number(value) : null;
}

export function pageChoice(search: string): PageChoice {
  const params = new URLSearchParams(search);
  const sort = COLUMNS.some(({ key }) => key === params.get("sort")) ? (params.get("sort") as SortKey) : DEFAULT_SORT;
  const dir: Dir = params.get("dir") === "asc" || params.get("dir") === "desc" ? (params.get("dir") as Dir) : naturalDir(sort);
  const shade = SHADES.find(({ key }) => key === params.get("shade"))?.key ?? "misses";
  return { m: whole(params.get("m")), n: whole(params.get("n")), shade, sort, dir };
}

/** A column's first direction: the Fact column smallest first, the counts largest first. */
export function naturalDir(sort: SortKey): Dir {
  return sort === "fact" ? "asc" : "desc";
}

/** The page's query string for a view and its own choices, with its ?. A choice at its default is left out. */
export function factsQuery(view: View, choice: Partial<PageChoice> = {}): string {
  const extra: [string, string][] = [];
  if (choice.m !== undefined && choice.m !== null && choice.n !== undefined && choice.n !== null) extra.push(["m", String(choice.m)], ["n", String(choice.n)]);
  if (choice.shade !== undefined && choice.shade !== "misses") extra.push(["shade", choice.shade]);
  const sort = choice.sort ?? DEFAULT_SORT;
  const dir = choice.dir ?? naturalDir(sort);
  if (sort !== DEFAULT_SORT || dir !== naturalDir(DEFAULT_SORT)) extra.push(["sort", sort], ["dir", dir]);
  return viewQuery(view, extra);
}

/** The facts page for an operation, with the view and the page's own choices in its address. */
export function factsAddress(operation: string, view: View, choice: Partial<PageChoice> = {}): string {
  return `/attempts/facts/${encodeURIComponent(operation)}${factsQuery(view, choice)}`;
}

/** The facts page for one client group over the past month with one fact chosen, as an attempt's questions link to it. */
export function factLink(operation: string, client: string, m: number, n: number): string {
  return `/attempts/facts/${encodeURIComponent(operation)}?client=${encodeURIComponent(client)}&m=${m}&n=${n}`;
}

/** The address with one choice changed on the page and the rest kept. */
export function withChoice(search: string, patch: Partial<PageChoice>): string {
  const params = new URLSearchParams(search);
  const choice = { ...pageChoice(search), ...patch };
  for (const key of PAGE_KEYS) params.delete(key);
  if (choice.m !== null && choice.n !== null) {
    params.append("m", String(choice.m));
    params.append("n", String(choice.n));
  }
  if (choice.shade !== "misses") params.append("shade", choice.shade);
  if (choice.sort !== DEFAULT_SORT || choice.dir !== naturalDir(DEFAULT_SORT)) {
    params.append("sort", choice.sort);
    params.append("dir", choice.dir);
  }
  const text = [...params].map(([key, value]) => `${key}=${encodeURIComponent(value)}`).join("&");
  return text ? `?${text}` : "";
}

/** The address for a click on a column header: that column in its first direction, or the other direction when it is already the sort. */
export function sortedBy(search: string, key: SortKey): string {
  const now = pageChoice(search);
  const dir = now.sort === key ? (now.dir === "asc" ? "desc" : "asc") : naturalDir(key);
  return withChoice(search, { sort: key, dir });
}

// The list's order.

function compareFact(a: Fact, b: Fact): number {
  return a.m - b.m || a.n - b.n;
}

/** A column's value to sort by. A fact with nothing in that column, such as no right answers for Median time, has none. */
function sortValue(fact: Fact, key: SortKey): number | string | null {
  switch (key) {
    case "fact":
      return null;
    case "missed":
      return fact.missed / fact.asked;
    case "median":
      return fact.median_ms;
    case "last":
      return fact.last_missed_day;
    case "all_asked":
      return fact.all_time.asked;
    case "run":
    case "miss_boost":
    case "slow_boost":
    case "weight":
      return fact.all_time[key];
    case "smoothed":
      return fact.all_time.smoothed_ms;
    default:
      return fact[key];
  }
}

/** The facts in the list's order: by the chosen column, then Missed, then Asked, largest first, then by fact. A fact with no value goes last. */
export function sortFacts(facts: Fact[], sort: SortKey, dir: Dir): Fact[] {
  const sign = dir === "asc" ? 1 : -1;
  return [...facts].sort((a, b) => {
    if (sort === "fact") return sign * compareFact(a, b);
    const left = sortValue(a, sort);
    const right = sortValue(b, sort);
    if (left !== right) {
      if (left === null) return 1;
      if (right === null) return -1;
      return sign * (left < right ? -1 : 1);
    }
    return b.missed / b.asked - a.missed / a.asked || b.asked - a.asked || compareFact(a, b);
  });
}

// The grid's shading.

export type Band = { level: number; label: string };

const MISS_BANDS: Band[] = [
  { level: 0, label: "None missed" },
  { level: 1, label: "Under 25% missed" },
  { level: 2, label: "25% to 49% missed" },
  { level: 3, label: "50% to 74% missed" },
  { level: 4, label: "75% or more missed" },
];

const WEIGHT_BANDS: Band[] = [
  { level: 0, label: "Weight under 0.5" },
  { level: 1, label: "0.5 to 1" },
  { level: 2, label: "1 to 2" },
  { level: 3, label: "2 to 4" },
  { level: 4, label: "4 or more" },
];

/** How a cell is shaded: by what, a level from 0, lightest, to 4, and the key's bands. A fact with no right answers has no level by Time. */
export type Shading = { kind: Shade; bands: Band[]; level: (fact: Fact) => number | null; none: string | null };

function missLevel(fact: Fact): number {
  const share = fact.missed / fact.asked;
  if (share === 0) return 0;
  return Math.min(4, 1 + Math.floor(share * 4));
}

/** A weight's level: under 0.5, 0.5 to 1, 1 to 2, 2 to 4, and 4 or more. */
function weightLevel(fact: Fact): number {
  const weight = fact.all_time.weight;
  return weight < 0.5 ? 0 : weight < 1 ? 1 : weight < 2 ? 2 : weight < 4 ? 3 : 4;
}

export function shading(shade: Shade, facts: Fact[]): Shading {
  if (shade === "misses") return { kind: shade, bands: MISS_BANDS, level: missLevel, none: null };
  if (shade === "weight") return { kind: shade, bands: WEIGHT_BANDS, level: weightLevel, none: null };
  const medians = facts.map((fact) => fact.median_ms).filter((value): value is number => value !== null);
  const none = "No right answers";
  if (medians.length === 0) return { kind: shade, bands: [], level: () => null, none };
  const low = Math.min(...medians);
  const high = Math.max(...medians);
  if (low === high) return { kind: shade, bands: [{ level: 1, label: formatSeconds(low / 1000) }], level: (fact) => (fact.median_ms === null ? null : 1), none };
  const step = (high - low) / 4;
  const bands = [1, 2, 3, 4].map((level) => {
    const from = low + step * (level - 1);
    const to = level === 4 ? high : low + step * level;
    return { level, label: `${formatSeconds(from / 1000)} to ${formatSeconds(to / 1000)}` };
  });
  const level = (fact: Fact) => (fact.median_ms === null ? null : Math.min(4, 1 + Math.floor((fact.median_ms - low) / step)));
  return { kind: shade, bands, level, none };
}

// How a fact reads.

export function medianText(fact: Fact): string {
  return fact.median_ms === null ? "none" : formatSeconds(fact.median_ms / 1000);
}

export function smoothedText(fact: Fact): string {
  return fact.all_time.smoothed_ms === null ? "none" : formatSeconds(fact.all_time.smoothed_ms / 1000);
}

/** A boost or weight to three places, as in S037's table, such as ``4.091``. */
export function weightText(value: number): string {
  return value.toFixed(3);
}

/** The readout's lines for a fact: the period's figures, then the all-time ones. */
export function factLines(fact: Fact): string[] {
  const all = fact.all_time;
  return [
    fact.text,
    `Asked ${fact.asked}, right ${fact.right}, wrong ${fact.wrong}, timeouts ${fact.timeouts}`,
    `Median time of right answers ${medianText(fact)}`,
    `Last missed ${fact.last_missed ?? "never"}`,
    `All time: asked ${all.asked}, run ${all.run}, smoothed time ${smoothedText(fact)}`,
    `All time: miss boost ${weightText(all.miss_boost)}, slow boost ${weightText(all.slow_boost)}, weight ${weightText(all.weight)}`,
  ];
}
