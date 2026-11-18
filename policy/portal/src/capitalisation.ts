import { LEVEL_RANGE, NO_SENTENCES, levelProblem, newId, type PoolData } from "./sentences";

/**
 * A capitalisation pool's sentences as the editor holds them (S040.2), and what the page says about them.
 * A sentence is a line of text and its own level of difficulty, which is empty for the pool's.
 */

export type CapSentence = { text: string; level_of_difficulty: string };
/** A capitalisation pool's page, as the service sends it. */
export type CapPoolData = Omit<PoolData, "sentences"> & { sentences: CapSentence[] };
/** One sentence on the page. ``origin`` is its place in the file, or null for a new sentence. */
export type CapBlock = { id: string; origin: number | null; text: string; level: string };

export const NO_TEXT = "The sentence is empty.";
export const NO_CAPITAL = "The sentence has no capital letter, so there is nothing to click.";
export const TWICE = "This sentence is already in the pool.";
export { LEVEL_RANGE, NO_SENTENCES };

const CAPITAL = /\p{Lu}/u;

export function loaded(data: Pick<CapPoolData, "sentences">): CapBlock[] {
  return data.sentences.map((sentence, index) => ({ id: `s${index}`, origin: index, text: sentence.text, level: sentence.level_of_difficulty }));
}

export function newBlock(text = ""): CapBlock {
  return { id: newId("c"), origin: null, text, level: "" };
}

/** A sentence as the pool compares it: its words, which are the runs between spaces, without regard to case. */
function same(text: string): string {
  return text.trim().split(/\s+/).join(" ").toLowerCase();
}

/** What stops a save, for the sentence at ``index``. Each is shown under its row. */
export function problems(blocks: CapBlock[], index: number): string[] {
  const block = blocks[index];
  const found: string[] = [];
  const text = block.text.trim();
  if (text === "") found.push(NO_TEXT);
  else {
    if (!CAPITAL.test(text)) found.push(NO_CAPITAL);
    if (blocks.slice(0, index).some((other) => same(other.text) === same(text))) found.push(TWICE);
  }
  const level = levelProblem(block.level);
  if (level) found.push(level);
  return found;
}

export function blocked(blocks: CapBlock[]): boolean {
  return blocks.length === 0 || blocks.some((_block, index) => problems(blocks, index).length > 0);
}

export function countsText(blocks: CapBlock[]): string {
  const troubled = blocks.filter((_block, index) => problems(blocks, index).length > 0).length;
  const sentences = `${blocks.length} sentence${blocks.length === 1 ? "" : "s"}.`;
  return `${sentences} ${troubled === 0 ? "None" : troubled} with problems.`;
}

export function blockChanged(original: CapSentence | undefined, block: CapBlock): boolean {
  return original === undefined || block.text !== original.text || block.level.trim() !== original.level_of_difficulty.trim();
}

export function blocksChanged(data: Pick<CapPoolData, "sentences">, blocks: CapBlock[]): boolean {
  if (blocks.length !== data.sentences.length || blocks.some((block, index) => block.origin !== index)) return true;
  return blocks.some((block) => blockChanged(data.sentences[block.origin ?? -1], block));
}

/** The sentences as a save sends them. */
export function toRequest(blocks: CapBlock[]) {
  return blocks.map((block) => ({ origin: block.origin, text: block.text, level_of_difficulty: block.level }));
}

/**
 * What pasting ``pasted`` into the box of ``block`` does, with the box's text selected from ``start`` to ``end``:
 * the first line goes into that row, and each other non-empty line is a new row below it. Null when the text is one line.
 */
export function pasteInto(block: CapBlock, start: number, end: number, pasted: string): { first: string; more: string[] } | null {
  const lines = pasted.split(/\r\n|\r|\n/);
  if (lines.length < 2) return null;
  const first = block.text.slice(0, start) + lines[0].trim() + block.text.slice(end);
  return { first, more: lines.slice(1).map((line) => line.trim()).filter((line) => line !== "") };
}
