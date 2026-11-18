/** A parts of speech task page's pools, filter, and defaults (S031.3), apart from how the page draws them. */
import { LONGEST_NAME, recognized } from "./sentences";

/** One pool a task could name. ``sentences`` is how many it adds to the runnable size. */
export type AvailablePool = { id: string; name: string; sentences: number };

/** A parts of speech task's page data: its own settings, the pools and filter the file writes, and every pool available. */
export type PosData = { settings: Record<string, string>; pools: string[]; filter: string[]; available: AvailablePool[] };

export const SETTINGS = ["timeout", "correct_answers_required", "minimum_questions", "maximum_questions"];
export const DEFAULT_TIMEOUT = "90s";
/** What a capitalisation task's empty Timeout shows (S040.2). */
export const CAPITALISATION_TIMEOUT = "60s";
export const NO_POOLS = "Choose at least one pool.";
export const FILTER_LABEL = "Parts of speech filter";

/** The pool names to show as options: every available pool, then any the task names that no pool file has. */
export function poolOptions(data: Pick<PosData, "available">, chosen: string[]): string[] {
  const names = data.available.map((pool) => pool.name);
  return [...names, ...chosen.filter((name) => !names.includes(name))];
}

/** The runnable size: the sentences across the chosen pools. */
export function runnableSize(data: Pick<PosData, "available">, chosen: string[]): number {
  return data.available.filter((pool) => chosen.includes(pool.name)).reduce((total, pool) => total + pool.sentences, 0);
}

/** The default number of correct answers for a runnable size, as the loader works it out: min(7, 70% rounded up). */
export function defaultRequired(size: number): number {
  return size < 1 ? 0 : Math.min(7, Math.ceil((7 * size) / 10));
}

/** The placeholders of the three question fields, which follow the chosen pools. Empty when no sentences are runnable. */
export function questionPlaceholders(size: number, settings: Record<string, string>): Record<string, string> {
  if (size < 1) return {};
  const typed = (settings.correct_answers_required ?? "").trim();
  const required = /^\d+$/.test(typed) && Number(typed) >= 1 ? Number(typed) : defaultRequired(size);
  return {
    correct_answers_required: String(defaultRequired(size)),
    minimum_questions: String(required),
    maximum_questions: String(size),
  };
}

/** The status bar's count, such as "2 pools. 24 sentences." */
export function poolCounts(chosen: string[], size: number): string {
  const pools = `${chosen.length} ${chosen.length === 1 ? "pool" : "pools"}`;
  return `${pools}. ${size} ${size === 1 ? "sentence" : "sentences"}.`;
}

/** Why one filter name stops a save, or null. ``names`` is the whole filter, for the same-apart-from-case rule. */
export function filterProblem(names: string[], index: number): string | null {
  const name = names[index].trim();
  if (name === "") return "A part name must not be empty.";
  if (name.length > LONGEST_NAME) return `A part name is at most ${LONGEST_NAME} characters.`;
  const folded = name.toLowerCase();
  if (names.some((other, at) => at !== index && other.trim().toLowerCase() === folded)) {
    return `"${name}" is listed more than once. Names must differ by more than case.`;
  }
  return null;
}

/** What is worth knowing about a filter name but does not stop a save. */
export function filterWarning(name: string): string | null {
  const typed = name.trim();
  return typed !== "" && !recognized(typed) ? `"${typed}" is not a recognized part of speech.` : null;
}

/** The first thing on the page that stops a save, or null. */
export function posBlock(chosen: string[], filter: string[]): string | null {
  if (chosen.length === 0) return NO_POOLS;
  const at = filter.findIndex((_name, index) => filterProblem(filter, index) !== null);
  return at < 0 ? null : filterProblem(filter, at);
}

export const sameList = (a: string[], b: string[]) => a.length === b.length && a.every((item, index) => item === b[index]);
