import { label } from "./labels";
import type { Choice } from "./components/SelectOne";

/** The spelling directory in the data directory. Every directory a pull-down lists is under it. */
export const SPELLING_DIR = "spelling";
export const DIRECTORY_FIELDS = ["current_dir", "revision_dir", "attic_dir", "alphabet_dir"];

const PREFIX = `${SPELLING_DIR}/`;

/** Whether a path from the data directory is under the spelling directory. */
export function inSpelling(path: string): boolean {
  return path.startsWith(PREFIX) && path.length > PREFIX.length;
}

/** A directory as a pull-down shows it: relative to the spelling directory, or its path from the data directory when outside it. */
export function shownDirectory(path: string): string {
  return inSpelling(path) ? path.slice(PREFIX.length) : path;
}

/** Order directory paths by name, part by part, as the service lists them. */
export function byName(a: string, b: string): number {
  const left = a.split("/");
  const right = b.split("/");
  for (let index = 0; index < Math.min(left.length, right.length); index += 1) {
    const [x, y] = [left[index].toLowerCase(), right[index].toLowerCase()];
    if (x !== y) return x < y ? -1 : 1;
    if (left[index] !== right[index]) return left[index] < right[index] ? -1 : 1;
  }
  return left.length - right.length;
}

/**
 * The options of a directory pull-down: every directory under the spelling
 * directory, and each of ``shown``, such as the field's saved and chosen
 * directories, that is not one of them. A missing one under the spelling
 * directory is marked missing, in its place by name. One outside it is
 * marked outside spelling, after the rest.
 */
export function directoryChoices(folders: string[], shown: string[]): Choice[] {
  const listed = new Set(folders);
  const missing = shown.filter((path) => inSpelling(path) && !listed.has(shownDirectory(path))).map(shownDirectory);
  const outside = [...new Set(shown.filter((path) => !inSpelling(path)))];
  const inside = [...new Set([...folders, ...missing])].sort(byName);
  return [
    ...inside.map((folder) => ({ value: PREFIX + folder, label: folder, ...(listed.has(folder) ? {} : { note: "missing" }) })),
    ...outside.map((path) => ({ value: path, label: path, note: "outside spelling" })),
  ];
}

/** The problem under each field that names the same directory as an earlier field. */
export function sameDirectoryProblems(chosen: Record<string, string>): Record<string, string> {
  const problems: Record<string, string> = {};
  const seen = new Map<string, string>();
  for (const field of DIRECTORY_FIELDS) {
    const path = chosen[field];
    if (path === undefined) continue;
    const first = seen.get(path);
    if (first !== undefined) problems[field] = `${label(first)} and ${label(field)} are the same directory.`;
    else seen.set(path, field);
  }
  return problems;
}

/** The fields whose chosen directory differs from the saved one. */
export function changedDirectories(saved: Record<string, string>, chosen: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(chosen).filter(([field, path]) => path !== saved[field]));
}

/** A query string, with its ?, that names each directory given, or "" when there are none. */
export function directoryQuery(directories: Record<string, string>): string {
  const query = new URLSearchParams(DIRECTORY_FIELDS.filter((field) => field in directories).map((field) => [field, directories[field]]));
  const text = query.toString();
  return text ? `?${text}` : "";
}
