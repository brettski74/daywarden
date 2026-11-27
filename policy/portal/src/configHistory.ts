/** Config History (S047): its page addresses, its data, and what the pages build from it. */

/** The pages, under the router's /parent base. */
export const HISTORY = "/settings/history";
export const HISTORY_COMPARE = "/settings/history/compare";
/** The data, under /parent/api. */
export const HISTORY_DATA = "/settings/history";

export function revisionPath(revision: string): string {
  return `${HISTORY}/${encodeURIComponent(revision)}`;
}

export function revisionData(revision: string): string {
  return `${HISTORY_DATA}/revisions/${encodeURIComponent(revision)}`;
}

export function comparePath(from: string, to: string): string {
  return `${HISTORY_COMPARE}?${new URLSearchParams({ from, to })}`;
}

/** The list, filtered to one file or not, on one page. Page 1 is left out of the address. */
export function listPath(file: string | null, page = 1): string {
  const search = new URLSearchParams();
  if (file) search.set("file", file);
  if (page > 1) search.set("page", String(page));
  const query = search.toString();
  return query ? `${HISTORY}?${query}` : HISTORY;
}

export type Revision = {
  id: string;
  short: string;
  /** Household-local, as yyyy-mm-dd HH:MM. */
  time: string;
  author: string;
  /** The commit message without its leading time and the author's name. */
  what: string;
  message: string;
  files: string[];
};

export type DiffLine = { kind: " " | "+" | "-"; text: string; old: number | null; new: number | null };
export type FileDiff = {
  path: string;
  status: "added" | "changed" | "removed";
  binary: boolean;
  hunks: { header: string; lines: DiffLine[] }[];
  unified: string;
};

export type HistoryList =
  | { kept: false }
  | {
      kept: true;
      revisions: Revision[];
      page: number;
      pages: number;
      total: number;
      file: string | null;
      hand_edits: string[];
      times: string;
    };

export type RevisionPage = { revision: Revision; newest: boolean; head: string; before: string | null; diff: FileDiff[] };
export type ComparePage = { from: Revision; to: Revision; diff: FileDiff[] };
export type RevertPreview = {
  revision: Revision;
  head: string;
  newest: boolean;
  diff: FileDiff[];
  nothing: boolean;
  renames: string[];
  mcp: string;
};

export const STATUS_LABELS: Record<FileDiff["status"], string> = { added: "Added", changed: "Changed", removed: "Removed" };

/** Return the rows the From and To radio buttons start on: the newest for To, and the one before it for From. */
export function defaultPair(revisions: Revision[]): { from: string; to: string } {
  const to = revisions[0]?.id ?? "";
  return { from: revisions[1]?.id ?? to, to };
}
