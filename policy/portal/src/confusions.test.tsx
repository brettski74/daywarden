import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import {
  confusionWordLink,
  filterPairs,
  pairPlacements,
  shareLevel,
  sortWords,
  sortedBy,
  taskConfusionsAddress,
  withChoice,
  type ConfusionWord,
  type ConfusionsData,
  type ConfusionsReport,
} from "./confusions";
import type { View } from "./attempts";
import { ATTEMPT, TREND, fakeService, renderPortal, shown, type Call } from "./test/portal";

const VIEW: View = {
  client: "younger",
  range: "past-month",
  from: "",
  to: "",
  set: ["required", "potential", "practice"],
  outcome: ["pass", "failure", "abandoned", "unfinished", "in_progress"],
};

const QUICKLY = [{ text: "The", word: 0 }, { text: " " }, { text: "dog", word: 1 }, { text: " " }, { text: "ran", word: 2 }, { text: " " }, { text: "quickly", word: 3 }, { text: "." }];

/** Monday: "The dog ran quickly." with quickly put in adjective, then left out. Tuesday: the same, quickly in adjective once. */
const DATA: ConfusionsData = {
  columns: [
    { part: "adjective", label: "adjective" },
    { part: "noun", label: "noun" },
    { part: "verb", label: "verb" },
    { part: "left_out", label: "left out" },
  ],
  rows: [
    { part: "adverb", label: "adverb", placements: 3, right: null, cells: [2, 0, 0, 1] },
    { part: "noun", label: "noun", placements: 3, right: 100, cells: [0, 3, 0, 0] },
    { part: "verb", label: "verb", placements: 3, right: 67, cells: [0, 0, 2, 1] },
    { part: "no_part", label: "no part", placements: 3, right: 100, cells: [0, 0, 0, 3] },
  ],
  words: [
    {
      id: "quickly|adverb", word: "quickly", part: "adverb", part_label: "adverb", sentences: 2, placements: 3, right: null,
      instead: { part: "adjective", label: "adjective", count: 2 }, last_misplaced: "Tuesday 17 November 2026", last_misplaced_day: "2026-11-17",
      asks: [[1, 3], [0, 3]],
    },
    {
      id: "ran|verb", word: "ran", part: "verb", part_label: "verb", sentences: 2, placements: 3, right: 67,
      instead: { part: "left_out", label: "left out", count: 1 }, last_misplaced: "Tuesday 17 November 2026", last_misplaced_day: "2026-11-17",
      asks: [[1, 2], [0, 2]],
    },
    {
      id: "dog|noun", word: "dog", part: "noun", part_label: "noun", sentences: 2, placements: 3, right: 100,
      instead: null, last_misplaced: null, last_misplaced_day: null, asks: [[1, 1], [0, 1]],
    },
  ],
  asks: {
    "0": {
      attempt: 61, started: "Monday 16 November 2026, 16:00", day: "2026-11-16", task: "pos-younger", pieces: QUICKLY,
      belongs: ["no_part", "noun", "verb", "adverb"],
      tries: [["left_out", "noun", "verb", "adjective"], ["left_out", "noun", "verb", "left_out"]],
      kept: [1, 2], labels: { noun: "noun", verb: "verb", adverb: "adverb", adjective: "adjective" },
    },
    "1": {
      attempt: 62, started: "Tuesday 17 November 2026, 16:00", day: "2026-11-17", task: "pos-younger", pieces: QUICKLY,
      belongs: ["no_part", "noun", "verb", "adverb"],
      tries: [["left_out", "noun", "left_out", "adjective"]],
      kept: [1], labels: { noun: "noun", verb: "verb", adverb: "adverb", adjective: "adjective" },
    },
  },
};

const REPORT: ConfusionsReport = {
  clients: ["younger", "older"],
  client: "younger",
  view: VIEW,
  notes: [],
  times: "Times are Europe/London.",
  today: "2026-11-18",
  range: "Thursday 19 October to Wednesday 18 November 2026",
  days: { from: "2026-10-19", to: "2026-11-18" },
  tasks_offered: [
    { name: "pos-younger", in_policy: true },
    { name: "pos-old", in_policy: false },
  ],
  pools_offered: [
    { id: "basic", name: "Basic" },
    { id: "no_pool", name: "None" },
  ],
  choices: { task: ["pos-younger", "pos-old"], pool: ["basic", "no_pool"], try: [1, 2, 3] },
  message: null,
  confusions: DATA,
};

const POS_ATTEMPT = {
  ...ATTEMPT,
  id: 61,
  task: "pos-younger",
  type: "parts_of_speech",
  client: "younger",
  record: { settings: {} },
  answers: null,
  parts_of_speech: {
    last: {
      run: 2,
      expired: null,
      figures: { points: 6.25, pass_mark: 7, questions: 8, maximum: 10, wrong: 1, timeouts: 1, time_ms: 300_000, average_ms: 35_000 },
      right_on_try: [5, 2, 1],
      sentences: [
        {
          text: "The dog ran quickly.", pieces: QUICKLY, words: ["the", "dog", "ran", "quickly"], outcome: "correct", outcome_label: "Correct",
          points: 0.5, taken_ms: 9000, allowed_ms: 90_000, no_try: false,
          tries: [
            {
              timer: false, taken_ms: 4000,
              words: [
                { label: null, right: true, belongs: "no part", link: "determiner" },
                { label: "noun", right: true, belongs: "noun", link: "noun" },
                { label: "left out", right: false, belongs: "verb", link: "verb" },
                { label: "adjective", right: false, belongs: "no part", link: "adverb" },
              ],
            },
          ],
        },
        { text: "A cat sat.", pieces: [{ text: "A cat sat." }], words: ["a", "cat", "sat"], outcome: "timeout", outcome_label: "Timed out", points: 0, taken_ms: 60_000, allowed_ms: 60_000, no_try: true, tries: [] },
      ],
    },
    expired: [
      {
        run: 1, expired: "Wednesday 18 November 2026, 15:00", figures: null, right_on_try: [0, 0, 0],
        sentences: [
          {
            text: "The dog ran quickly.", pieces: QUICKLY, words: ["the", "dog", "ran", "quickly"], outcome: "timeout", outcome_label: "Timed out",
            points: 0, taken_ms: 90_000, allowed_ms: 90_000, no_try: false,
            tries: [{ timer: true, taken_ms: 90_000, words: [
              { label: null, right: true, belongs: "no part", link: "determiner" },
              { label: "noun", right: true, belongs: "noun", link: "noun" },
              { label: "left out", right: false, belongs: "verb", link: "verb" },
              { label: null, right: true, belongs: "no part", link: "adverb" },
            ] }],
          },
        ],
      },
    ],
  },
};

function service() {
  return fakeService((call) => {
    if (call.path === "/parent/api/attempts/parts-of-speech") return { body: REPORT };
    if (call.path === "/parent/api/attempts/61") return { body: POS_ATTEMPT };
    if (call.path === "/parent/api/attempts/tasks/parts_of_speech/pos-younger") return { body: { ...TREND, task: { type: "parts_of_speech", name: "pos-younger", label: "parts_of_speech/pos-younger", in_policy: true }, facts: null } };
    return undefined;
  });
}

function asked(calls: Call[]): string[] {
  return calls.filter((call) => call.path === "/parent/api/attempts/parts-of-speech").map((call) => call.search);
}

const rowsOf = (table: HTMLElement, skip: number) =>
  within(table)
    .getAllByRole("row")
    .slice(skip)
    .map((row) => [...row.querySelectorAll("td")].map((cell) => cell.textContent));

describe("the confusions address and list", () => {
  it("leaves filters out while everything is chosen, and names a pair, a word, and the sort in the address", () => {
    expect(filterPairs({ task: ["pos-younger", "pos-old"], pool: ["basic", "no_pool"], try: ["1", "2", "3"] }, REPORT)).toEqual([]);
    expect(filterPairs({ task: ["pos-old"], pool: [], try: ["1"] }, REPORT)).toEqual([
      ["task", "pos-old"],
      ["pool", "none"],
      ["try", "1"],
    ]);
    expect(taskConfusionsAddress("pos-younger", { ...VIEW, range: "past-week" })).toBe("/attempts/parts-of-speech?client=younger&range=past-week&task=pos-younger");
    expect(confusionWordLink("younger", "quickly", "adverb")).toBe("/attempts/parts-of-speech?client=younger&word=quickly&part=adverb");
    expect(withChoice("?client=younger&try=1", { pair: { from: "adverb", to: "adjective" } })).toBe("?client=younger&try=1&from_part=adverb&to_part=adjective");
    expect(sortedBy("?client=younger", "placements")).toBe("?client=younger&sort=placements&dir=desc");
    expect(sortedBy("?client=younger&sort=right&dir=desc", "right")).toBe("?client=younger");
  });

  it("sorts by Right, smallest first with not asked last, then Placements, and finds a pair's placements newest first", () => {
    const words = DATA.words as ConfusionWord[];
    expect(sortWords(words, "right", "asc").map(({ id }) => id)).toEqual(["ran|verb", "dog|noun", "quickly|adverb"]);
    expect(sortWords(words, "word", "asc").map(({ id }) => id)).toEqual(["dog|noun", "quickly|adverb", "ran|verb"]);
    expect(pairPlacements(DATA, "adverb", "adjective").map(({ ask, try: number }) => [ask.attempt, number])).toEqual([
      [62, 1],
      [61, 1],
    ]);
    expect([0, 1, 3, 5, 10].map((count) => shareLevel(count, 20))).toEqual([0, 1, 2, 3, 4]);
  });
});

describe("the confusions page", () => {
  it("asks for the view and filters alone, and draws the grid with each row's Right and a readout", async () => {
    const calls = service();
    renderPortal("/parent/attempts/parts-of-speech?client=younger&try=1&from_part=adverb&to_part=adjective&sort=word&dir=asc");
    const grid = await screen.findByRole("table", { name: "Confusions" });
    expect(asked(calls)).toEqual(["?client=younger&try=1"]);
    expect(within(grid).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual(["adjective", "noun", "verb", "left out"]);
    expect(within(grid).getAllByRole("rowheader").map((cell) => cell.textContent)).toEqual(["adverbnot asked", "nounRight 100%", "verbRight 67%", "no partRight 100%"]);
    const cell = within(grid).getByRole("link", { name: "adverb put in adjective: 2 of 3" });
    expect(cell.closest("td")).toHaveAttribute("data-level", "4");
    expect(cell).toHaveAttribute("tabindex", "0");
    fireEvent.pointerEnter(cell);
    const readout = document.querySelector(".facts-readout") as HTMLElement;
    await waitFor(() => expect(readout).toHaveTextContent("adverb put in adjective: 2 of 3 adverb placements"));
    cell.focus();
    fireEvent.keyDown(cell, { key: "ArrowDown" });
    expect(document.activeElement).toHaveAccessibleName("noun put in adjective: 0 of 3");
    fireEvent.keyDown(document.activeElement!, { key: "End" });
    expect(document.activeElement).toHaveAccessibleName("noun left out: 0 of 3");
    expect(screen.getByLabelText("Key")).toHaveTextContent("Right: the part, or no part left out");
  });

  it("chooses a pair without asking again and lists its placements newest first, each opening its attempt", async () => {
    const calls = service();
    const { router } = renderPortal("/parent/attempts/parts-of-speech?client=younger");
    const grid = await screen.findByRole("table", { name: "Confusions" });
    await userEvent.click(within(grid).getByRole("link", { name: "adverb put in adjective: 2 of 3" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/attempts/parts-of-speech?client=younger&from_part=adverb&to_part=adjective"));
    const list = await screen.findByRole("table", { name: "Placements of adverb put in adjective" });
    expect(rowsOf(list, 1)).toEqual([
      ["The dog ran quickly.", "Tuesday 17 November 2026, 16:00", "pos-younger", "1st"],
      ["The dog ran quickly.", "Monday 16 November 2026, 16:00", "pos-younger", "1st"],
    ]);
    expect(within(list).getAllByRole("link")[0]).toHaveAttribute("href", "/parent/attempts/62");
    expect(list.querySelector("mark")).toHaveTextContent("quickly");
    expect(asked(calls)).toHaveLength(1);
  });

  it("lists the words by Right, and a chosen word shows where he put it on each try", async () => {
    service();
    const { router } = renderPortal("/parent/attempts/parts-of-speech?client=younger");
    const list = await screen.findByRole("table", { name: "Words" });
    expect(rowsOf(list, 1)).toEqual([
      ["ran", "verb", "2", "3", "67%", "left out ×1", "Tuesday 17 November 2026"],
      ["dog", "noun", "2", "3", "100%", "", ""],
      ["quickly", "adverb", "2", "3", "not asked", "adjective ×2", "Tuesday 17 November 2026"],
    ]);
    await userEvent.click(within(list).getByRole("link", { name: "quickly" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/attempts/parts-of-speech?client=younger&word=quickly&part=adverb"));
    const chosen = await screen.findByRole("table", { name: "Sentences that asked quickly (adverb)" });
    expect(rowsOf(chosen, 1).map((row) => row[3])).toEqual(["adjective", "adjective, left out"]);
    await userEvent.click(within(list).getByRole("button", { name: "Placements" }));
    await waitFor(() => expect(shown(router)).toContain("sort=placements&dir=desc"));
  });

  it("sends a Try choice to the service and keeps the page's own choices", async () => {
    const calls = service();
    const { router } = renderPortal("/parent/attempts/parts-of-speech?client=younger&word=dog");
    await screen.findByRole("table", { name: "Confusions" });
    await userEvent.click(screen.getByRole("button", { name: /^Try 1st/ }));
    await userEvent.click(screen.getByRole("option", { name: "1st" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/attempts/parts-of-speech?client=younger&try=2&try=3&word=dog"));
    await waitFor(() => expect(asked(calls)).toEqual(["?client=younger", "?client=younger&try=2&try=3"]));
  });

  it("says why it has nothing to show", async () => {
    fakeService((call) =>
      call.path === "/parent/api/attempts/parts-of-speech"
        ? { body: { ...REPORT, confusions: null, message: "No parts of speech sentences for younger in this period." } }
        : undefined,
    );
    renderPortal("/parent/attempts/parts-of-speech?client=younger");
    expect(await screen.findByText("No parts of speech sentences for younger in this period.")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Confusions" })).toBeNull();
  });

  it("is linked from a parts of speech task's trend with only that task chosen", async () => {
    service();
    renderPortal("/parent/attempts/tasks/parts_of_speech/pos-younger?client=younger&range=past-week");
    expect(await screen.findByRole("link", { name: "Parts of speech confusions" })).toHaveAttribute(
      "href",
      expect.stringMatching(/^\/parent\/attempts\/parts-of-speech\?client=younger.*&task=pos-younger$/),
    );
  });
});

describe("a parts of speech attempt's page", () => {
  it("shows the last run's summary, each try with every word labelled and judged, and each expired run", async () => {
    service();
    renderPortal("/parent/attempts/61");
    const sentences = await screen.findByRole("list", { name: "Last run's sentences" });
    const summary = document.querySelector(".run-summary")!;
    expect(summary).toHaveTextContent("Points6.25 / 7 points");
    expect(summary).toHaveTextContent("Questions8 / 10");
    expect(summary).toHaveTextContent("Right on 1st try5Right on 2nd try2Right on 3rd try1");
    expect(summary).toHaveTextContent("Average per right answer35.0 s");
    const first = within(sentences).getByRole("listitem", { name: "Try 1" });
    expect(first).toHaveTextContent("The dog noun ran left out (verb) quickly adjective (no part).");
    expect(within(first).getAllByRole("img", { name: "wrong" })).toHaveLength(2);
    expect(within(first).getByRole("link", { name: "quickly" })).toHaveAttribute("href", "/parent/attempts/parts-of-speech?client=younger&word=quickly&part=adverb");
    expect(within(sentences).getByText("Timed out with no try: A cat sat.")).toBeInTheDocument();
    const expired = screen.getByRole("region", { name: "Run 1, expired Wednesday 18 November 2026, 15:00" });
    expect(within(expired).getByText("Timer ran out")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stored record" })).toBeInTheDocument();
  });
});
