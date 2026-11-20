/** The spelling words page: its data, the address of its choices, the list's sort, and how a word reads. */

import { formatSeconds, viewQuery, type PeriodData, type View } from "./attempts";

export type Result = "first_time" | "after_miss" | "missed";

/** One attempt that asked a word: how it went, the pools it was asked from, and his answers each time. */
export type WordAttempt = { id: number; result: Result; pools: string[]; answers: string[] };

export type Word = {
  /** The folded entry key, which identifies the word. */
  word: string;
  /** The entry key as last stored, such as ``read.1``. */
  key: string;
  /** Its pool now in the chosen tasks' directories, empty for None. */
  pools: string[];
  asked: number;
  first_time: number;
  after_miss: number;
  missed: number;
  missed_percent: number;
  timeouts: number;
  median_ms: number | null;
  replays_per_ask: number;
  last_missed: string | null;
  last_missed_day: string | null;
  misspellings: { text: string; count: number }[];
  attempts: WordAttempt[];
  /** Figures for now, from his whole record whatever the period and filters, as bin/word-stats gives them. */
  all_time: { run: number; weight: number };
};

export type Tiles = { words_asked: number; right_first_time: number | null; words_missed: number; settled: number };

export type WordsData = {
  tiles: Tiles;
  words: Word[];
  /** Every attempt that asked any of the words, oldest first. */
  columns: number[];
  attempts: Record<string, { started: string; day: string; task: string }>;
};

export type OfferedTask = { name: string; in_policy: boolean };

export type WordsReport = PeriodData & {
  clients: string[];
  client: string;
  view: View;
  notes: string[];
  times: string;
  tasks_offered: OfferedTask[];
  choices: { task: string[]; pool: string[] };
  this_week: { from: string; to: string } | null;
  message: string | null;
  words: WordsData | null;
};

export const POOLS: [string, string][] = [
  ["current", "Current"],
  ["revision", "Revision"],
  ["attic", "Attic"],
  ["no_pool", "None"],
];

export const RESULTS: { key: Result | "not_asked"; label: string }[] = [
  { key: "first_time", label: "Right first time" },
  { key: "after_miss", label: "Right after a miss" },
  { key: "missed", label: "Missed" },
  { key: "not_asked", label: "Not asked" },
];

export function resultLabel(result: Result | null): string {
  return RESULTS.find(({ key }) => key === (result ?? "not_asked"))!.label;
}

/** Choices that are the page's alone. The data does not change with them. */
export const PAGE_KEYS = ["word", "sort", "dir"];
/** The words page's own filters, which the data does change with. */
const FILTER_KEYS = ["task", "pool"];
const NONE = "none";

export type Filters = { task: string[]; pool: string[] };

/** The address's pairs for the Task and Pool filters. Everything chosen is left out, and nothing chosen is ``none``. */
export function filterPairs(filters: Filters, offered: string[]): [string, string][] {
  const pairs: [string, string][] = [];
  const tasks = offered.filter((name) => filters.task.includes(name));
  if (tasks.length !== offered.length || filters.task.some((name) => !offered.includes(name))) {
    const named = filters.task.length ? filters.task : [NONE];
    pairs.push(...named.map((name): [string, string] => ["task", name]));
  }
  const pools = POOLS.map(([value]) => value).filter((value) => filters.pool.includes(value));
  if (pools.length !== POOLS.length) pairs.push(...(pools.length ? pools : [NONE]).map((value): [string, string] => ["pool", value]));
  return pairs;
}

/** The words page for a view and its filters, with the page's own choices on the end. */
export function wordsAddress(view: View, filters: Filters, offered: string[], extra: [string, string][] = []): string {
  return `/attempts/words${viewQuery(view, [...filterPairs(filters, offered), ...extra])}`;
}

/** The words page with only one spelling task chosen, as a trend page links to it. */
export function taskWordsAddress(name: string, view: View): string {
  return `/attempts/words${viewQuery(view, [["task", name]])}`;
}

/** The words page for one client group over the past month with one word chosen, as an attempt's questions link to it. */
export function wordLink(client: string, word: string): string {
  return `/attempts/words?client=${encodeURIComponent(client)}&word=${encodeURIComponent(word.toLowerCase())}`;
}

/** This week's words: only Current, the Task filter kept, and the period from the day the list began to today. */
export function thisWeekAddress(report: WordsReport): string | null {
  if (report.this_week === null) return null;
  const view: View = { ...report.view, range: "custom", from: report.this_week.from, to: report.this_week.to };
  return wordsAddress(view, { task: report.choices.task, pool: ["current"] }, report.tasks_offered.map(({ name }) => name));
}

/** The query string the data endpoint takes: the address without the page's own choices. */
export function dataSearch(search: string): string {
  const params = new URLSearchParams(search);
  for (const key of PAGE_KEYS) params.delete(key);
  const text = params.toString();
  return text ? `?${text}` : "";
}

/** The address's filter pairs as they stand, kept when the view changes. */
export function filtersIn(search: string): [string, string][] {
  return [...new URLSearchParams(search)].filter(([key]) => FILTER_KEYS.includes(key));
}

export type SortKey =
  | "word"
  | "pool"
  | "asked"
  | "first_time"
  | "after_miss"
  | "missed"
  | "missed_percent"
  | "timeouts"
  | "median"
  | "replays"
  | "last"
  | "run"
  | "weight";
export type Dir = "asc" | "desc";

export const COLUMNS: { key: SortKey; label: string; text?: true; now?: true }[] = [
  { key: "word", label: "Word", text: true },
  { key: "pool", label: "Pool now", text: true },
  { key: "asked", label: "Asked" },
  { key: "first_time", label: "Right first time" },
  { key: "after_miss", label: "Right after a miss" },
  { key: "missed", label: "Missed" },
  { key: "missed_percent", label: "Missed %" },
  { key: "timeouts", label: "Timeouts" },
  { key: "median", label: "Median time" },
  { key: "replays", label: "Replays per ask" },
  { key: "last", label: "Last missed", text: true },
  { key: "run", label: "Run", now: true },
  { key: "weight", label: "Weight", now: true },
];

const DEFAULT_SORT: SortKey = "missed_percent";

export type PageChoice = { word: string | null; sort: SortKey; dir: Dir };

export function naturalDir(sort: SortKey): Dir {
  return sort === "word" || sort === "pool" ? "asc" : "desc";
}

export function pageChoice(search: string): PageChoice {
  const params = new URLSearchParams(search);
  const sort = COLUMNS.some(({ key }) => key === params.get("sort")) ? (params.get("sort") as SortKey) : DEFAULT_SORT;
  const dir: Dir = params.get("dir") === "asc" || params.get("dir") === "desc" ? (params.get("dir") as Dir) : naturalDir(sort);
  const word = params.get("word");
  return { word: word ? word.toLowerCase() : null, sort, dir };
}

/** The address with one of the page's choices changed and the rest kept. A choice at its default is left out. */
export function withChoice(search: string, patch: Partial<PageChoice>): string {
  const params = new URLSearchParams(search);
  const choice = { ...pageChoice(search), ...patch };
  for (const key of PAGE_KEYS) params.delete(key);
  if (choice.word !== null) params.append("word", choice.word.toLowerCase());
  if (choice.sort !== DEFAULT_SORT || choice.dir !== naturalDir(DEFAULT_SORT)) {
    params.append("sort", choice.sort);
    params.append("dir", choice.dir);
  }
  const text = [...params].map(([key, value]) => `${key}=${encodeURIComponent(value)}`).join("&");
  return text ? `?${text}` : "";
}

/** The address for a click on a column header: that column in its first direction, or the other way when it is already the sort. */
export function sortedBy(search: string, key: SortKey): string {
  const now = pageChoice(search);
  const dir = now.sort === key ? (now.dir === "asc" ? "desc" : "asc") : naturalDir(key);
  return withChoice(search, { sort: key, dir });
}

export function poolText(word: Word): string {
  return word.pools.length ? word.pools.map((pool) => POOLS.find(([value]) => value === pool)?.[1] ?? pool).join(", ") : "None";
}

function sortValue(word: Word, key: SortKey): number | string | null {
  switch (key) {
    case "word":
      return word.word;
    case "pool":
      return poolText(word);
    case "median":
      return word.median_ms;
    case "replays":
      return word.replays_per_ask;
    case "last":
      return word.last_missed_day;
    case "run":
    case "weight":
      return word.all_time[key];
    default:
      return word[key];
  }
}

/** The words in the list's order: by the chosen column, then Missed %, then Asked, largest first, then by word. A word with no value goes last. */
export function sortWords(words: Word[], sort: SortKey, dir: Dir): Word[] {
  const sign = dir === "asc" ? 1 : -1;
  return [...words].sort((a, b) => {
    const left = sortValue(a, sort);
    const right = sortValue(b, sort);
    if (left !== right) {
      if (left === null) return 1;
      if (right === null) return -1;
      return sign * (left < right ? -1 : 1);
    }
    return b.missed_percent - a.missed_percent || b.asked - a.asked || (a.word < b.word ? -1 : a.word > b.word ? 1 : 0);
  });
}

export function medianText(word: Word): string {
  return word.median_ms === null ? "none" : formatSeconds(word.median_ms / 1000);
}

/** A word's misspellings, most first, such as ``necesary ×3, neccessary ×1``, or none. */
export function misspellingText(word: Word): string {
  return word.misspellings.length ? word.misspellings.map(({ text, count }) => `${text} ×${count}`).join(", ") : "none";
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** A grid column's heading from a ``yyyy-mm-dd`` day, such as ``16 Nov``. */
export function shortDay(day: string): string {
  const [, month, date] = day.split("-").map(Number);
  return `${date} ${MONTHS[month - 1] ?? ""}`;
}
