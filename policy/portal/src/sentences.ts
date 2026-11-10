import { sortModel, type Cells } from "./wordSort";

/**
 * A parts of speech task's sentences as the editor holds them, and what the page says about them.
 *
 * Words are split as the loader splits them in policy/parts_of_speech.py: a run of letters and digits,
 * with an apostrophe or a hyphen between two of them joining the runs. Words compare without regard to
 * case, with ’ the same as ', and each has its occurrence number among the words that compare the same.
 */

export type Word = { text: string; start: number; end: number; key: string; occurrence: number };
export type Segment = { text: string; word?: number };

export type PosPart = { name: string; words: number[] };
export type PosSentence = { text: string; timeout: string; parts: PosPart[] };
export type PosData = { settings: Record<string, string>; sentences: PosSentence[]; problems: string[] };

/** One row of a sentence's table. ``origin`` is its place in the sentence as loaded, or null for a new row. */
export type Row = { id: string; origin: number | null; name: string; words: number[] };
/**
 * One sentence on the page. ``origin`` is its place in the file, or null for a new sentence.
 * ``removed`` names the sorted words an edit of the text took out of the table.
 */
export type Block = { id: string; origin: number | null; text: string; timeout: string; rows: Row[]; removed: string[] };

export const DEFAULT_TIMEOUT = "90s";
export const LONGEST_NAME = 20;
export const RECOGNIZED = [
  "noun",
  "proper noun",
  "pronoun",
  "verb",
  "participle",
  "gerund",
  "infinitive",
  "adjective",
  "adverb",
  "article",
  "determiner",
  "preposition",
  "conjunction",
  "interjection",
];
export const NO_WORDS = "The sentence has no words.";
export const NO_NAME = "Every row needs a name.";
export const NONE_SORTED = "No word is sorted into the table.";
export const NO_SENTENCES = "There are no sentences. Add at least one.";
export const FIX_FIRST = "Fix the problems marked under the sentences first.";

const LETTER = /^[\p{L}\p{N}\p{M}]$/u;
const JOINERS = new Set(["'", "\u2019", "-"]);

export function wordKey(text: string): string {
  return text.normalize("NFC").replace(/\u2019/g, "'").toLowerCase();
}

export function splitWords(text: string): Word[] {
  const chars = Array.from(text);
  const offsets: number[] = [];
  let at = 0;
  for (const char of chars) {
    offsets.push(at);
    at += char.length;
  }
  offsets.push(at);
  const found: Word[] = [];
  const counts = new Map<string, number>();
  let position = 0;
  while (position < chars.length) {
    if (!LETTER.test(chars[position])) {
      position += 1;
      continue;
    }
    const start = position;
    position += 1;
    while (position < chars.length) {
      if (LETTER.test(chars[position])) position += 1;
      else if (JOINERS.has(chars[position]) && position + 1 < chars.length && LETTER.test(chars[position + 1])) position += 2;
      else break;
    }
    const piece = text.slice(offsets[start], offsets[position]);
    const key = wordKey(piece);
    const occurrence = (counts.get(key) ?? 0) + 1;
    counts.set(key, occurrence);
    found.push({ text: piece, start: offsets[start], end: offsets[position], key, occurrence });
  }
  return found;
}

/** The sentence as pieces: each word with its number, and the text between words. */
export function segments(text: string): Segment[] {
  const pieces: Segment[] = [];
  let at = 0;
  splitWords(text).forEach((word, number) => {
    if (word.start > at) pieces.push({ text: text.slice(at, word.start) });
    pieces.push({ text: word.text, word: number });
    at = word.end;
  });
  if (at < text.length) pieces.push({ text: text.slice(at) });
  return pieces;
}

export function ordinal(number: number): string {
  const tens = number % 100;
  const suffix = tens >= 11 && tens <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[number % 10] ?? "th";
  return `${number}${suffix}`;
}

/** 70% of the sentences, rounded up, as the loader's default for correct_answers_required. */
export function defaultRequired(count: number): number {
  return Math.floor((7 * count + 9) / 10);
}

/** Whether a row name is a part of speech the page knows: ignoring case and spaces at the ends, one listed, or one with s added. */
export function recognized(name: string): boolean {
  const folded = name.trim().toLowerCase();
  return RECOGNIZED.some((listed) => folded === listed || folded === `${listed}s`);
}

let made = 0;
export function newId(prefix: string): string {
  made += 1;
  return `${prefix}${made}`;
}

export function newRow(name = ""): Row {
  return { id: newId("r"), origin: null, name, words: [] };
}

export function loaded(data: PosData): Block[] {
  return data.sentences.map((sentence, index) => ({
    id: `s${index}`,
    origin: index,
    text: sentence.text,
    timeout: sentence.timeout,
    rows: sentence.parts.map((part, row) => ({ id: `s${index}r${row}`, origin: row, name: part.name, words: [...part.words] })),
    removed: [],
  }));
}

export function cellsOf(block: Block): Cells {
  return Object.fromEntries(block.rows.map((row) => [row.id, row.words]));
}

export function withCells(block: Block, cells: Cells): Block {
  return { ...block, rows: block.rows.map((row) => ({ ...row, words: cells[row.id] ?? row.words })) };
}

/** The row a word of the sentence is sorted into, or null. */
export function rowOf(block: Block, id: number): Row | null {
  const found = sortModel.partOf(cellsOf(block), id);
  return block.rows.find((row) => row.id === found) ?? null;
}

export function place(block: Block, id: number, rowId: string): Block {
  return withCells(block, sortModel.place(cellsOf(block), id, rowId));
}

export function unsort(block: Block, id: number): Block {
  return withCells(block, sortModel.remove(cellsOf(block), id));
}

function identity(word: Word): string {
  return `${word.key}\u0000${word.occurrence}`;
}

function shown(word: Word): string {
  return word.occurrence === 1 ? word.text : `${word.text} (${ordinal(word.occurrence)})`;
}

/**
 * The block with new text. Each sorted word still in the sentence, matched ignoring case and by which
 * occurrence it is, stays in its row. The rest leave their rows and are named in ``removed``.
 */
export function retext(block: Block, text: string): Block {
  if (text === block.text) return block;
  const before = splitWords(block.text);
  const after = new Map(splitWords(text).map((word, position) => [identity(word), position]));
  const removed = [...block.removed];
  const rows = block.rows.map((row) => ({
    ...row,
    words: row.words.flatMap((position) => {
      const word = before[position];
      const moved = word === undefined ? undefined : after.get(identity(word));
      if (moved !== undefined) return [moved];
      if (word !== undefined && !removed.includes(shown(word))) removed.push(shown(word));
      return [];
    }),
  }));
  return { ...block, text, rows, removed };
}

/** What stops a save: each is shown under its sentence. */
export function problems(block: Block): string[] {
  const words = splitWords(block.text).length;
  const found: string[] = [];
  if (words === 0) found.push(NO_WORDS);
  if (block.rows.some((row) => row.name.trim() === "")) found.push(NO_NAME);
  if (words > 0 && !block.rows.some((row) => row.words.length > 0)) found.push(NONE_SORTED);
  return found;
}

/** What is worth knowing but does not stop a save. */
export function warnings(block: Block): string[] {
  const names = [...new Set(block.rows.map((row) => row.name.trim()).filter((name) => name && !recognized(name)))];
  const found = names.map((name) => `"${name}" is not a recognized part of speech.`);
  if (block.removed.length) found.push(`No longer in the sentence, so taken out of the table: ${block.removed.join(", ")}.`);
  return found;
}

/** Whether anything on the page stops a save. */
export function blocked(blocks: Block[]): boolean {
  return blocks.length === 0 || blocks.some((block) => problems(block).length > 0);
}

export function countsText(blocks: Block[]): string {
  const troubled = blocks.filter((block) => problems(block).length > 0).length;
  const sentences = `${blocks.length} sentence${blocks.length === 1 ? "" : "s"}.`;
  return `${sentences} ${troubled === 0 ? "None" : troubled} with problems.`;
}

/** Whether a row holds the same words as it did when loaded, comparing each word by its text and occurrence. */
export function sameWords(original: PosSentence, part: PosPart, block: Block, row: Row): boolean {
  const before = splitWords(original.text);
  const now = splitWords(block.text);
  const of = (words: Word[], positions: number[]) =>
    positions
      .map((position) => (words[position] ? identity(words[position]) : `?${position}`))
      .sort()
      .join("\u0001");
  return of(before, part.words) === of(now, row.words);
}

export function rowChanged(original: PosSentence | undefined, block: Block, row: Row): { name: boolean; words: boolean } {
  const part = row.origin === null || original === undefined ? undefined : original.parts[row.origin];
  if (part === undefined || original === undefined) return { name: true, words: true };
  return { name: row.name !== part.name, words: !sameWords(original, part, block, row) };
}

export function blockChanged(original: PosSentence | undefined, block: Block): boolean {
  if (original === undefined) return true;
  if (block.text !== original.text || block.timeout.trim() !== original.timeout.trim()) return true;
  if (block.rows.length !== original.parts.length || block.rows.some((row, index) => row.origin !== index)) return true;
  return block.rows.some((row) => {
    const changed = rowChanged(original, block, row);
    return changed.name || changed.words;
  });
}

export function blocksChanged(data: PosData, blocks: Block[]): boolean {
  if (blocks.length !== data.sentences.length || blocks.some((block, index) => block.origin !== index)) return true;
  return blocks.some((block) => blockChanged(data.sentences[block.origin ?? -1], block));
}

/** The sentences as a save sends them. */
export function toRequest(blocks: Block[]) {
  return blocks.map((block) => ({
    origin: block.origin,
    text: block.text,
    timeout: block.timeout,
    parts: block.rows.map((row) => ({ name: row.name, words: row.words })),
  }));
}
