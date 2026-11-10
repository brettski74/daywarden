// Types for word_sort.js, which the portal imports and the child's parts of speech page inlines.

/** The words in each row of a table, by their number in the sentence, in the order they were dropped. */
export type Cells = Record<string, number[]>;

/** What dropping a word does: put it in a row, leave it where it was, take it out of its row, or fly it back to the sentence. */
export type Drop = "place" | "stay" | "unsort" | "back";

export declare const sortModel: {
  empty(parts: string[]): Cells;
  partOf(cells: Cells, id: number): string | null;
  place(cells: Cells, id: number, part: string): Cells;
  remove(cells: Cells, id: number): Cells;
  count(cells: Cells): number;
  drop(origin: string | null, target: string | null): Drop;
};

export declare const PRESS_THRESHOLD: number;

export type DropTarget = { key: string; element: HTMLElement };

export interface WordSortOptions {
  sources: HTMLElement[];
  flightMs: number;
  canPress?(event: PointerEvent): boolean;
  pickable(target: EventTarget | null): HTMLElement | null;
  originOf(id: number): string | null;
  sentenceWord(id: number): HTMLElement;
  cellWord(id: number): HTMLElement | null;
  targetAt(found: Element, id: number): DropTarget | null;
  hoverable?(target: EventTarget | null): HTMLElement | null;
  hoverOn?(): boolean;
  ghost?(copy: HTMLElement, source: HTMLElement): void;
  onPlace(id: number, key: string): void;
  onUnsort(id: number): void;
  onBusy?(): void;
  onArrive?(id: number): void;
  noSelect?(target: EventTarget | null): boolean;
  noDragImage?(target: EventTarget | null): boolean;
}

export interface WordSort {
  dragging(): boolean;
  flying(): boolean;
  /** Drop a drag in progress where it started, with no flight. */
  cancel(): void;
  /** End a flight at once. */
  arrive(): void;
  destroy(): void;
}

export declare function wordSort(options: WordSortOptions): WordSort;
