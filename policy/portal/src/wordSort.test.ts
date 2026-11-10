import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { sortModel, wordSort, type WordSort, type WordSortOptions } from "./wordSort";

type Calls = { onPlace: Mock<(id: number, key: string) => void>; onUnsort: Mock<(id: number) => void>; onArrive: Mock<(id: number) => void> };

describe("the sorting model", () => {
  it("places, moves, and removes words, and says what a drop does", () => {
    const empty = sortModel.empty(["noun", "verb"]);
    expect(empty).toEqual({ noun: [], verb: [] });
    const placed = sortModel.place(sortModel.place(empty, 3, "noun"), 8, "noun");
    expect(placed).toEqual({ noun: [3, 8], verb: [] });
    expect(sortModel.place(placed, 3, "noun")).toBe(placed);
    expect(sortModel.place(placed, 3, "verb")).toEqual({ noun: [8], verb: [3] });
    expect(sortModel.remove(placed, 8)).toEqual({ noun: [3], verb: [] });
    expect([sortModel.partOf(placed, 8), sortModel.partOf(placed, 4)]).toEqual(["noun", null]);
    expect(sortModel.count(placed)).toBe(2);
    expect([
      sortModel.drop(null, "noun"),
      sortModel.drop(null, null),
      sortModel.drop("noun", "verb"),
      sortModel.drop("noun", "noun"),
      sortModel.drop("noun", null),
    ]).toEqual(["place", "back", "place", "stay", "unsort"]);
  });
});

/** A sentence of two words, the first sorted into the noun row, as a page would draw it. */
function page() {
  document.body.innerHTML = `
    <div id="root">
      <p id="sentence"><span data-word="0" data-sorted>cat</span> <span data-word="1" data-pick>sat</span></p>
      <table><tbody>
        <tr><th>noun</th><td data-row="noun"><span data-word="0" data-pick>cat</span></td></tr>
        <tr><th>verb</th><td data-row="verb"></td></tr>
      </tbody></table>
      <h1 id="elsewhere">Elsewhere</h1>
    </div>`;
  const $ = (selector: string) => document.querySelector(selector) as HTMLElement;
  return {
    $,
    sentence: (id: number) => $(`#sentence [data-word="${id}"]`),
    cell: (id: number) => document.querySelector<HTMLElement>(`td [data-word="${id}"]`),
    row: (key: string) => $(`td[data-row="${key}"]`),
  };
}

function pointer(target: EventTarget, type: string, x: number, y: number) {
  act(() => {
    target.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, clientX: x, clientY: y }));
  });
}

describe("dragging a word", () => {
  let view: ReturnType<typeof page>;
  let under: Element | null;
  let sorter: WordSort;
  let options: WordSortOptions & Calls;

  beforeEach(() => {
    vi.useFakeTimers();
    view = page();
    under = null;
    document.elementFromPoint = () => under;
    const root = view.$("#root");
    options = {
      sources: [root],
      flightMs: 600,
      pickable: (target) => (target as Element).closest<HTMLElement>("[data-pick]"),
      originOf: (id) => (id === 0 ? "noun" : null),
      sentenceWord: view.sentence,
      cellWord: view.cell,
      targetAt: (found) => {
        const cell = found.closest<HTMLElement>("td[data-row]");
        return cell ? { key: cell.dataset.row as string, element: cell } : null;
      },
      hoverable: (target) => (target as Element).closest<HTMLElement>("#sentence [data-sorted], td [data-word]"),
      onPlace: vi.fn<(id: number, key: string) => void>(),
      onUnsort: vi.fn<(id: number) => void>(),
      onArrive: vi.fn<(id: number) => void>(),
      noSelect: (target) => (target as Node).nodeName !== "INPUT",
    };
    sorter = wordSort(options);
  });

  afterEach(() => {
    sorter.destroy();
    vi.useRealTimers();
  });

  it("starts only once the pointer moves past the threshold, then follows the pointer with a copy", () => {
    const sat = view.sentence(1);
    pointer(sat, "pointerdown", 10, 10);
    pointer(document, "pointermove", 12, 11);
    expect(sorter.dragging()).toBe(false);
    expect(document.querySelector("[data-ghost]")).toBeNull();
    pointer(document, "pointermove", 14, 10);
    expect(sorter.dragging()).toBe(true);
    const ghost = document.querySelector<HTMLElement>("[data-ghost]");
    expect(ghost?.textContent).toBe("sat");
    expect(sat).toHaveAttribute("data-held");
    expect(document.body).toHaveAttribute("data-dragging");
    pointer(document, "pointermove", 50, 40);
    expect([ghost?.style.left, ghost?.style.top]).toEqual(["40px", "30px"]);
  });

  it("drops a word from the sentence on a row, marking the row under the pointer on the way", () => {
    pointer(view.sentence(1), "pointerdown", 10, 10);
    under = view.row("verb");
    pointer(document, "pointermove", 30, 30);
    expect(view.row("verb")).toHaveAttribute("data-over");
    pointer(document, "pointerup", 30, 30);
    expect(options.onPlace).toHaveBeenCalledWith(1, "verb");
    expect(view.row("verb")).not.toHaveAttribute("data-over");
    expect(view.sentence(1)).not.toHaveAttribute("data-held");
    expect(document.body).not.toHaveAttribute("data-dragging");
    expect(document.querySelector("[data-ghost]")).toBeNull();
  });

  it("flies a word dropped elsewhere back to the sentence, changing nothing", () => {
    pointer(view.sentence(1), "pointerdown", 10, 10);
    under = view.$("#elsewhere");
    pointer(document, "pointermove", 30, 30);
    pointer(document, "pointerup", 30, 30);
    expect(sorter.flying()).toBe(true);
    expect(document.querySelector("[data-ghost]")).toHaveAttribute("data-flying");
    expect(view.sentence(1)).toHaveAttribute("data-held");
    act(() => vi.advanceTimersByTime(600));
    expect(sorter.flying()).toBe(false);
    expect(document.querySelector("[data-ghost]")).toBeNull();
    expect(view.sentence(1)).not.toHaveAttribute("data-held");
    expect(options.onArrive).toHaveBeenCalledWith(1);
    expect(options.onPlace).not.toHaveBeenCalled();
    expect(options.onUnsort).not.toHaveBeenCalled();
  });

  it("takes a word dropped elsewhere out of its row, and leaves one dropped on its own row alone", () => {
    const cat = view.cell(0) as HTMLElement;
    pointer(cat, "pointerdown", 10, 10);
    pointer(document, "pointermove", 30, 30);
    expect(cat).toHaveAttribute("data-held");
    expect(view.sentence(0)).toHaveAttribute("data-held");
    under = view.row("noun");
    pointer(document, "pointerup", 30, 30);
    expect(options.onPlace).not.toHaveBeenCalled();
    expect(options.onUnsort).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(600));

    pointer(cat, "pointerdown", 10, 10);
    pointer(document, "pointermove", 30, 30);
    under = null;
    pointer(document, "pointerup", 30, 30);
    expect(options.onUnsort).toHaveBeenCalledWith(0);
  });

  it("refuses a press while the page says no", () => {
    sorter.destroy();
    sorter = wordSort({ ...options, canPress: () => false });
    pointer(view.sentence(1), "pointerdown", 10, 10);
    pointer(document, "pointermove", 40, 40);
    expect(sorter.dragging()).toBe(false);
  });

  it("lights a sorted word and its twin while the pointer is over either", () => {
    act(() => view.sentence(0).dispatchEvent(new MouseEvent("pointerover", { bubbles: true })));
    expect(view.sentence(0)).toHaveAttribute("data-lit");
    expect(view.cell(0)).toHaveAttribute("data-lit");
    act(() => view.sentence(0).dispatchEvent(new MouseEvent("pointerout", { bubbles: true, relatedTarget: document.body })));
    expect(view.cell(0)).not.toHaveAttribute("data-lit");
  });

  it("cancels a drag where it started, and blocks text selection and the browser's own drag", () => {
    pointer(view.sentence(1), "pointerdown", 10, 10);
    pointer(document, "pointermove", 40, 40);
    act(() => sorter.cancel());
    expect(sorter.dragging()).toBe(false);
    expect(document.querySelector("[data-ghost]")).toBeNull();
    expect(view.sentence(1)).not.toHaveAttribute("data-held");
    const selecting = new Event("selectstart", { bubbles: true, cancelable: true });
    view.sentence(1).dispatchEvent(selecting);
    expect(selecting.defaultPrevented).toBe(true);
    const dragging = new Event("dragstart", { bubbles: true, cancelable: true });
    view.sentence(1).dispatchEvent(dragging);
    expect(dragging.defaultPrevented).toBe(true);
  });
});
