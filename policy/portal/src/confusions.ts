/** The parts of speech confusions page: its data, the address of its choices, the word list's sort, and the chosen pair's and word's placements. */

import { viewQuery, type PeriodData, type View } from "./attempts";

/** A part as the address names it: a folded part name, or ``no_part``. A row put in is a part, or ``left_out``. */
export const NO_PART = "no_part";
export const LEFT_OUT = "left_out";
export const NO_POOL = "no_pool";

export type GridColumn = { part: string; label: string };
export type GridRow = { part: string; label: string; placements: number; right: number | null; cells: number[] };

export type ConfusionWord = {
  /** ``word|part``, which identifies the row. */
  id: string;
  word: string;
  part: string;
  part_label: string;
  sentences: number;
  placements: number;
  right: number | null;
  instead: { part: string; label: string; count: number } | null;
  last_misplaced: string | null;
  last_misplaced_day: string | null;
  /** Each sentence that asked it, newest first, as ``[ask, word position]``. */
  asks: [number, number][];
};

export type Piece = { text: string; word?: number };

/** One counted sentence: its attempt, its pieces, each word's part, where each word went on every try, and the tries the Try filter kept. */
export type Ask = {
  attempt: number;
  started: string;
  day: string;
  task: string;
  pieces: Piece[];
  belongs: string[];
  tries: string[][];
  kept: number[];
  labels: Record<string, string>;
};

export type ConfusionsData = { columns: GridColumn[]; rows: GridRow[]; words: ConfusionWord[]; asks: Record<string, Ask> };

export type OfferedTask = { name: string; in_policy: boolean };

export type ConfusionsReport = PeriodData & {
  clients: string[];
  client: string;
  view: View;
  notes: string[];
  times: string;
  tasks_offered: OfferedTask[];
  pools_offered: { id: string; name: string }[];
  choices: { task: string[]; pool: string[]; try: number[] };
  message: string | null;
  confusions: ConfusionsData | null;
};

export const TRIES: [string, string][] = [
  ["1", "1st"],
  ["2", "2nd"],
  ["3", "3rd"],
];

/** Choices that are the page's alone. The data does not change with them. */
export const PAGE_KEYS = ["from_part", "to_part", "word", "part", "sort", "dir"];
const FILTER_KEYS = ["task", "pool", "try"];
const NONE = "none";

export type Filters = { task: string[]; pool: string[]; try: string[] };

function listPairs(key: string, chosen: string[], offered: string[]): [string, string][] {
  const kept = offered.filter((value) => chosen.includes(value));
  if (kept.length === offered.length && !chosen.some((value) => !offered.includes(value))) return [];
  return (chosen.length ? chosen : [NONE]).map((value): [string, string] => [key, value]);
}

/** The address's pairs for the Task, Pool, and Try filters. Everything chosen is left out, and nothing chosen is ``none``. */
export function filterPairs(filters: Filters, report: ConfusionsReport): [string, string][] {
  return [
    ...listPairs("task", filters.task, report.tasks_offered.map(({ name }) => name)),
    ...listPairs("pool", filters.pool, report.pools_offered.map(({ id }) => id)),
    ...listPairs("try", filters.try, TRIES.map(([value]) => value)),
  ];
}

export function confusionsAddress(view: View, filters: Filters, report: ConfusionsReport, extra: [string, string][] = []): string {
  return `/attempts/parts-of-speech${viewQuery(view, [...filterPairs(filters, report), ...extra])}`;
}

/** The confusions page with only one task chosen, as a trend page links to it. */
export function taskConfusionsAddress(name: string, view: View): string {
  return `/attempts/parts-of-speech${viewQuery(view, [["task", name]])}`;
}

/** The confusions page for one client group over the past month with one word chosen, as an attempt's words link to it. */
export function confusionWordLink(client: string, word: string, part: string): string {
  return `/attempts/parts-of-speech?client=${encodeURIComponent(client)}&word=${encodeURIComponent(word)}&part=${encodeURIComponent(part)}`;
}

/** The query string the data endpoint takes: the address without the page's own choices. */
export function dataSearch(search: string): string {
  const params = new URLSearchParams(search);
  for (const key of PAGE_KEYS) params.delete(key);
  const text = params.toString();
  return text ? `?${text}` : "";
}

export function filtersIn(search: string): [string, string][] {
  return [...new URLSearchParams(search)].filter(([key]) => FILTER_KEYS.includes(key));
}

export type SortKey = "word" | "belongs" | "sentences" | "placements" | "right" | "instead" | "last";
export type Dir = "asc" | "desc";

export const COLUMNS: { key: SortKey; label: string; text?: true }[] = [
  { key: "word", label: "Word", text: true },
  { key: "belongs", label: "Belongs in", text: true },
  { key: "sentences", label: "Sentences" },
  { key: "placements", label: "Placements" },
  { key: "right", label: "Right" },
  { key: "instead", label: "Most often instead", text: true },
  { key: "last", label: "Last misplaced", text: true },
];

const DEFAULT_SORT: SortKey = "right";

export function naturalDir(sort: SortKey): Dir {
  return sort === "word" || sort === "belongs" || sort === "instead" || sort === "right" ? "asc" : "desc";
}

export type PageChoice = { pair: { from: string; to: string } | null; word: { word: string; part: string | null } | null; sort: SortKey; dir: Dir };

export function pageChoice(search: string): PageChoice {
  const params = new URLSearchParams(search);
  const sort = COLUMNS.some(({ key }) => key === params.get("sort")) ? (params.get("sort") as SortKey) : DEFAULT_SORT;
  const dir: Dir = params.get("dir") === "asc" || params.get("dir") === "desc" ? (params.get("dir") as Dir) : naturalDir(sort);
  const from = params.get("from_part");
  const to = params.get("to_part");
  const word = params.get("word");
  return {
    pair: from && to ? { from, to } : null,
    word: word ? { word: word.toLowerCase(), part: params.get("part") || null } : null,
    sort,
    dir,
  };
}

/** The address with some of the page's choices changed and the rest kept. A choice at its default is left out. */
export function withChoice(search: string, patch: Partial<PageChoice>): string {
  const params = new URLSearchParams(search);
  const choice = { ...pageChoice(search), ...patch };
  for (const key of PAGE_KEYS) params.delete(key);
  if (choice.pair !== null) params.append("from_part", choice.pair.from), params.append("to_part", choice.pair.to);
  if (choice.word !== null) {
    params.append("word", choice.word.word);
    if (choice.word.part !== null) params.append("part", choice.word.part);
  }
  if (choice.sort !== DEFAULT_SORT || choice.dir !== naturalDir(DEFAULT_SORT)) {
    params.append("sort", choice.sort);
    params.append("dir", choice.dir);
  }
  const text = [...params].map(([key, value]) => `${key}=${encodeURIComponent(value)}`).join("&");
  return text ? `?${text}` : "";
}

export function sortedBy(search: string, key: SortKey): string {
  const now = pageChoice(search);
  const dir = now.sort === key ? (now.dir === "asc" ? "desc" : "asc") : naturalDir(key);
  return withChoice(search, { sort: key, dir });
}

/** The chosen word's row: the one with its part, or, with no part named, the first in the list. */
export function chosenWord(words: ConfusionWord[], choice: PageChoice["word"]): ConfusionWord | null {
  if (choice === null) return null;
  return words.find(({ word, part }) => word === choice.word && (choice.part === null || part === choice.part)) ?? null;
}

function sortValue(word: ConfusionWord, key: SortKey): number | string | null {
  switch (key) {
    case "belongs":
      return word.part_label;
    case "instead":
      return word.instead === null ? null : word.instead.label;
    case "last":
      return word.last_misplaced_day;
    default:
      return word[key];
  }
}

/** The words in the list's order: by the chosen column, then Right, smallest first, then Placements, largest first, then by word. A word with no value goes last. */
export function sortWords(words: ConfusionWord[], sort: SortKey, dir: Dir): ConfusionWord[] {
  const sign = dir === "asc" ? 1 : -1;
  const rightOf = (word: ConfusionWord) => (word.right === null ? Infinity : word.right);
  return [...words].sort((a, b) => {
    const left = sortValue(a, sort);
    const right = sortValue(b, sort);
    if (left !== right) {
      if (left === null) return 1;
      if (right === null) return -1;
      return sign * (left < right ? -1 : 1);
    }
    return rightOf(a) - rightOf(b) || b.placements - a.placements || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
  });
}

export function rightText(right: number | null): string {
  return right === null ? "not asked" : `${right}%`;
}

export function insteadText(word: ConfusionWord): string {
  return word.instead === null ? "" : `${word.instead.label} ×${word.instead.count}`;
}

/** A word and its part as the list names it, such as ``dry (verb)``. */
export function wordText(word: ConfusionWord): string {
  return `${word.word} (${word.part_label})`;
}

/** The share of its row a cell holds, as a shading level from 0 (none) to 4 (half or more). */
export function shareLevel(count: number, total: number): number {
  if (count === 0 || total === 0) return 0;
  const share = count / total;
  return share >= 0.5 ? 4 : share >= 0.25 ? 3 : share >= 0.1 ? 2 : 1;
}

export const SHARE_LEVELS: { level: number; label: string }[] = [
  { level: 0, label: "None" },
  { level: 1, label: "Under 10% of the row" },
  { level: 2, label: "10% to 25%" },
  { level: 3, label: "25% to 50%" },
  { level: 4, label: "Half or more" },
];

/** A cell's readout, such as ``adverb put in adjective: 7 of 31 adverb placements``. */
export function cellText(row: GridRow, column: GridColumn, count: number): string {
  const put = column.part === LEFT_OUT ? "left out" : `put in ${column.label}`;
  return `${row.label} ${put}: ${count} of ${row.placements} ${row.label} placements`;
}

export type Placed = { key: string; ask: Ask; position: number; try: number };

/** The chosen pair's placements, newest first. */
export function pairPlacements(data: ConfusionsData, from: string, to: string): Placed[] {
  const found: Placed[] = [];
  const refs = Object.keys(data.asks).sort((a, b) => Number(b) - Number(a));
  for (const ref of refs) {
    const ask = data.asks[ref];
    for (const number of ask.kept) {
      ask.belongs.forEach((part, position) => {
        if (part === from && ask.tries[number - 1][position] === to) found.push({ key: `${ref}-${number}-${position}`, ask, position, try: number });
      });
    }
  }
  return found;
}

/** Where he put a word on one try, as the page names it. */
export function putLabel(ask: Ask, put: string): string {
  return put === LEFT_OUT ? "left out" : (ask.labels[put] ?? put);
}

export const TRY_LABELS = ["1st", "2nd", "3rd"];
