/** Asset Administration's parts of speech pool pages: their addresses, and where their data lives. */

/** The pool list page, under the router's /parent base. */
export const POOLS = "/assets/parts-of-speech-pools";
/** The pools' data, under /parent/api. */
export const POOLS_DATA = "/parts-of-speech-pools";

/** One pool in the list. ``level_of_difficulty`` is empty when the pool sets none. */
export type PoolEntry = { id: string; name: string; level_of_difficulty: string; sentences: number; problem?: string };

export function poolPath(id: string): string {
  return `${POOLS}/${encodeURIComponent(id)}`;
}

export function poolData(id: string): string {
  return `${POOLS_DATA}/${encodeURIComponent(id)}`;
}

/** What a pool page reports on the page it opens, such as the list after a delete. */
export type PoolReport = { message: string; warnings: string[] };
