/** Asset Administration's pool pages: their addresses, and where their data lives. There is one set for each kind of pool. */

/** One kind of pool: parts of speech sentences, or capitalisation sentences (S040.2). */
export type PoolKind = {
  /** The pool list page, under the router's /parent base. */
  list: string;
  /** The pools' data, under /parent/api. */
  data: string;
  /** The list page's title, and what its crumb is called. */
  title: string;
  /** What a pool is called in sentences, such as "parts of speech pool". */
  noun: string;
};

export const PARTS_POOLS: PoolKind = {
  list: "/assets/parts-of-speech-pools",
  data: "/parts-of-speech-pools",
  title: "Parts of Speech Pools",
  noun: "parts of speech pool",
};
export const CAPITALISATION_POOLS: PoolKind = {
  list: "/assets/capitalisation-pools",
  data: "/capitalisation-pools",
  title: "Capitalisation Pools",
  noun: "capitalisation pool",
};

/** The pool list page of parts of speech pools, under the router's /parent base. */
export const POOLS = PARTS_POOLS.list;
/** The parts of speech pools' data, under /parent/api. */
export const POOLS_DATA = PARTS_POOLS.data;

/** The kind of pool a page address belongs to. */
export function kindOf(pathname: string): PoolKind {
  return pathname.includes("/capitalisation-pools") ? CAPITALISATION_POOLS : PARTS_POOLS;
}

/** One pool in the list. ``level_of_difficulty`` is empty when the pool sets none. */
export type PoolEntry = { id: string; name: string; level_of_difficulty: string; sentences: number; problem?: string };

export function poolPath(id: string, kind: PoolKind = PARTS_POOLS): string {
  return `${kind.list}/${encodeURIComponent(id)}`;
}

export function poolData(id: string, kind: PoolKind = PARTS_POOLS): string {
  return `${kind.data}/${encodeURIComponent(id)}`;
}

/** What a pool page reports on the page it opens, such as the list after a delete. */
export type PoolReport = { message: string; warnings: string[] };
