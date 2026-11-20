import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { filterPairs, sortWords, sortedBy, taskWordsAddress, thisWeekAddress, withChoice, wordLink, type Word, type WordsReport } from "./spellingWords";
import { TREND, WORDS, fakeService, renderPortal, shown, type Call } from "./test/portal";

const words = WORDS.words.words as Word[];
const names = (list: Word[]) => list.map((word) => word.word);
const OFFERED = ["spelling-younger", "old-list"];
const ALL_POOLS = ["current", "revision", "attic", "no_pool"];

function asked(calls: Call[], path: string): string[] {
  return calls.filter((call) => call.path === path).map((call) => call.search);
}

const rowsOf = (table: HTMLElement, skip: number) =>
  within(table)
    .getAllByRole("row")
    .slice(skip)
    .map((row) => [...row.querySelectorAll("td")].map((cell) => cell.textContent));

describe("the words address and list", () => {
  it("leaves the filters out while everything is chosen, and This week's words chooses Current and the period the list began", () => {
    expect(filterPairs({ task: OFFERED, pool: ALL_POOLS }, OFFERED)).toEqual([]);
    expect(filterPairs({ task: ["old-list"], pool: ["current"] }, OFFERED)).toEqual([
      ["task", "old-list"],
      ["pool", "current"],
    ]);
    expect(filterPairs({ task: [], pool: [] }, OFFERED)).toEqual([
      ["task", "none"],
      ["pool", "none"],
    ]);
    expect(thisWeekAddress(WORDS as WordsReport)).toBe("/attempts/words?client=younger&range=custom&from=2026-11-16&to=2026-11-18&pool=current");
    const oneTask = { ...WORDS, choices: { ...WORDS.choices, task: ["spelling-younger"] } } as WordsReport;
    expect(thisWeekAddress(oneTask)).toContain("&task=spelling-younger&pool=current");
    expect(taskWordsAddress("spelling-younger", { ...WORDS.view, range: "past-week" })).toBe("/attempts/words?client=younger&range=past-week&task=spelling-younger");
    expect(wordLink("younger", "Read.1")).toBe("/attempts/words?client=younger&word=read.1");
  });

  it("sorts by Missed %, then Asked, largest first, and a header sorts by its column and turns it round", () => {
    expect(names(sortWords(words, "missed_percent", "desc"))).toEqual(["necessary", "rope", "cat"]);
    expect(names(sortWords(words, "weight", "desc"))).toEqual(["necessary", "rope", "cat"]);
    expect(names(sortWords(words, "word", "asc"))).toEqual(["cat", "necessary", "rope"]);
    // A word never missed goes last whichever way Last missed is sorted.
    expect(names(sortWords(words, "last", "asc"))).toEqual(["necessary", "rope", "cat"]);
    expect(sortedBy("?client=younger", "word")).toBe("?client=younger&sort=word&dir=asc");
    expect(sortedBy("?client=younger&sort=missed_percent&dir=asc", "missed_percent")).toBe("?client=younger");
    expect(withChoice("?client=younger&pool=current", { word: "Necessary" })).toBe("?client=younger&pool=current&word=necessary");
  });
});

describe("the words page", () => {
  it("asks for the view and filters alone, and shows the tiles, the filters, and This week's words", async () => {
    const calls = fakeService();
    renderPortal("/parent/attempts/words?client=younger&pool=current&word=necessary&sort=word&dir=asc");
    expect(await screen.findByRole("heading", { level: 1, name: "Spelling words" })).toBeInTheDocument();
    expect(asked(calls, "/parent/api/attempts/words")).toEqual(["?client=younger&pool=current"]);
    const tiles = screen.getByLabelText("Tiles");
    expect([...tiles.querySelectorAll("div")].map((tile) => tile.textContent)).toEqual(["Words asked3", "Right first time71%", "Words missed1", "Settled1"]);
    expect(screen.getByRole("link", { name: "This week's words" })).toHaveAttribute(
      "href",
      "/parent/attempts/words?client=younger&range=custom&from=2026-11-16&to=2026-11-18&pool=current",
    );
    await userEvent.click(screen.getByRole("button", { name: /^Task spelling-younger/ }));
    expect(screen.getByRole("option", { name: "old-list (not in the policy)" })).toBeInTheDocument();
  });

  it("turns a Pool choice off in the address and keeps the page's own choices", async () => {
    const calls = fakeService();
    const { router } = renderPortal("/parent/attempts/words?client=younger&word=rope");
    await screen.findByRole("heading", { level: 1, name: "Spelling words" });
    await userEvent.click(screen.getByRole("button", { name: /^Pool Current/ }));
    await userEvent.click(screen.getByRole("option", { name: "Attic" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/attempts/words?client=younger&pool=current&pool=revision&pool=no_pool&word=rope"));
    await waitFor(() => expect(asked(calls, "/parent/api/attempts/words")).toHaveLength(2));
  });

  it("lists every word sorted by Missed %, with its figures for now, and a header sorts in the address", async () => {
    fakeService();
    const { router } = renderPortal("/parent/attempts/words?client=younger");
    const list = await screen.findByRole("table", { name: "Words" });
    expect(rowsOf(list, 2)).toEqual([
      ["necessary", "Current", "3", "0", "1", "2", "100%", "1", "5.0 s", "0.7", "Wednesday 18 November 2026", "0", "4.250"],
      ["rope", "Current", "3", "3", "0", "0", "0%", "0", "2.0 s", "0.0", "", "3", "0.250"],
      ["cat", "Revision", "1", "1", "0", "0", "0%", "0", "3.0 s", "0.0", "", "6", "0.125"],
    ]);
    const groups = within(list).getAllByRole("row")[0];
    expect([...groups.querySelectorAll("th")].map((cell) => cell.textContent)).toEqual(["In this period", "For now"]);
    await userEvent.click(within(list).getByRole("button", { name: "Word" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/attempts/words?client=younger&sort=word&dir=asc"));
    await waitFor(() => expect(rowsOf(list, 2)[0][0]).toBe("cat"));
  });

  it("draws a cell for each word and attempt, with a readout of his answers, the arrow keys between cells, and a link to the attempt", async () => {
    fakeService();
    renderPortal("/parent/attempts/words?client=younger");
    const grid = await screen.findByRole("table", { name: "Words by attempt" });
    const header = within(grid).getAllByRole("row")[0];
    expect([...header.querySelectorAll("th")].map((cell) => cell.textContent)).toEqual(["16 Nov", "17 Nov", "18 Nov"]);
    expect(within(grid).getAllByRole("rowheader").map((cell) => cell.textContent)).toEqual(["necessary", "rope", "cat"]);
    const wednesday = within(grid).getByRole("link", { name: "necessary, Wednesday 18 November 2026, 16:00, Right after a miss" });
    expect(wednesday).toHaveAttribute("href", "/parent/attempts/53");
    expect(wednesday).toHaveAttribute("tabindex", "0");

    fireEvent.pointerEnter(within(grid).getByRole("link", { name: /^necessary, Tuesday/ }));
    expect(await screen.findByText("Missed: timeout, necesary")).toBeInTheDocument();

    wednesday.focus();
    fireEvent.keyDown(wednesday, { key: "ArrowDown" });
    expect(document.activeElement).toHaveAccessibleName("rope, Wednesday 18 November 2026, 16:00, Right first time");
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    // cat was not asked on Wednesday. Its cell can still be focused and says so.
    expect(document.activeElement).toHaveAccessibleName("cat, Wednesday 18 November 2026, 16:00, Not asked");
    expect(within(document.querySelector(".facts-readout") as HTMLElement).getByText("Not asked")).toBeInTheDocument();
    fireEvent.keyDown(document.activeElement!, { key: "Home" });
    expect(document.activeElement).toHaveAccessibleName("cat, Monday 16 November 2026, 16:00, Not asked");
  });

  it("chooses a word from the grid or the list without asking again, and shows its misspellings and the attempts that asked it", async () => {
    const calls = fakeService();
    const { router } = renderPortal("/parent/attempts/words?client=younger");
    const grid = await screen.findByRole("table", { name: "Words by attempt" });
    await userEvent.click(within(grid).getByRole("link", { name: "necessary" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/attempts/words?client=younger&word=necessary"));
    expect(await screen.findByText("necesary ×3, neccessary ×1")).toBeInTheDocument();
    const chosen = screen.getByRole("table", { name: "Attempts that asked necessary" });
    expect(rowsOf(chosen, 1)).toEqual([
      ["Wednesday 18 November 2026, 16:00", "spelling-younger", "Current", "necesary, necessary"],
      ["Tuesday 17 November 2026, 16:00", "spelling-younger", "Current", "timeout, necesary"],
      ["Monday 16 November 2026, 16:00", "spelling-younger", "Revision", "necesary, neccessary"],
    ]);
    expect(within(chosen).getAllByRole("link")[0]).toHaveAttribute("href", "/parent/attempts/53");

    const list = screen.getByRole("table", { name: "Words" });
    await userEvent.click(within(list).getByRole("link", { name: "rope" }).closest("tr")!.querySelector("td:nth-child(3)")!);
    await waitFor(() => expect(shown(router)).toBe("/parent/attempts/words?client=younger&word=rope"));
    expect(await screen.findByRole("table", { name: "Attempts that asked rope" })).toBeInTheDocument();
    expect(asked(calls, "/parent/api/attempts/words")).toHaveLength(1);
  });

  it("says why it has nothing to show", async () => {
    fakeService((call) =>
      call.path === "/parent/api/attempts/words" ? { body: { ...WORDS, words: null, message: "No spelling words for younger in this period." } } : undefined,
    );
    renderPortal("/parent/attempts/words?client=younger");
    expect(await screen.findByText("No spelling words for younger in this period.")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Words" })).not.toBeInTheDocument();
  });

  it("is linked from a spelling task's trend with only that task chosen", async () => {
    const spelling = { ...TREND, task: { type: "spelling", name: "spelling-younger", label: "spelling/spelling-younger", in_policy: true }, facts: null };
    fakeService((call) => (call.path === "/parent/api/attempts/tasks/spelling/spelling-younger" ? { body: spelling } : undefined));
    renderPortal("/parent/attempts/tasks/spelling/spelling-younger?client=younger");
    expect(await screen.findByRole("link", { name: "Spelling words" })).toHaveAttribute(
      "href",
      "/parent/attempts/words?client=younger&task=spelling-younger",
    );
  });
});

describe("a spelling attempt's page", () => {
  it("shows the last run's summary and questions, then each earlier run and how it ended", async () => {
    fakeService();
    renderPortal("/parent/attempts/44");
    const table = await screen.findByRole("table", { name: "Last run's questions" });
    expect(screen.getByText("2 / 2 current, 1 / 1 revision")).toBeInTheDocument();
    expect(screen.getByText("Practised before this run: rope, cat")).toBeInTheDocument();
    expect(rowsOf(table, 1)).toEqual([
      ["1", "necessary", "Current", "necesary", "Wrong", "Yes", "2", "1", "4.0 s", "12.0 s"],
      ["2", "necessary", "Current", "necessary", "Right", "No", "0", "0", "4.5 s", "12.0 s"],
      ["3", "read.1", "Current", "read", "Right", "No", "0", "0", "3.0 s", "12.0 s"],
      ["4", "cat", "Revision", "", "Timeout", "No", "0", "0", "", "12.0 s"],
    ]);
    expect(within(table).getByRole("link", { name: "read.1" })).toHaveAttribute("href", "/parent/attempts/words?client=younger&word=read.1");
    expect(screen.getByRole("heading", { name: "Run 1, expired Wednesday 18 November 2026, 15:00" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Run 2, left for practice mode Wednesday 18 November 2026, 16:20" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stored record" })).toHaveAttribute("aria-expanded", "false");
  });
});
