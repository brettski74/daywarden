import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { defaultRequired, poolCounts, questionPlaceholders } from "./partsOfSpeech";
import { CHECK, TASKS, TODAY, fakeService, renderPortal, shown, type Call, type Reply } from "./test/portal";

const PAGE = {
  ...CHECK,
  name: "nouns",
  type: "parts_of_speech",
  version: "v1",
  fields: { pass_cooldown: "1", failure_cooldown: "", max_skips: "", max_passes: "", available_from: "", due_date: "" },
  parts_of_speech: {
    settings: { timeout: "", correct_answers_required: "", minimum_questions: "", maximum_questions: "" },
    pools: ["Basics"],
    filter: [],
    available: [
      { id: "basics", name: "Basics", sentences: 12 },
      { id: "extra", name: "Extra", sentences: 12 },
      { id: "spare", name: "Spare", sentences: 2 },
    ],
  },
  today: TODAY,
};
const DONE = { message: "Saved nouns. The decisions, observations, and autoconfig services are using it.", warnings: [] };

async function openNouns(handler?: (call: Call) => Reply | undefined, page: unknown = PAGE) {
  const calls = fakeService((call) => {
    const answered = handler?.(call);
    if (answered) return answered;
    if (call.path === "/parent/api/tasks") return { body: { tasks: [...TASKS.tasks, { type: "parts_of_speech", name: "nouns" }] } };
    return call.path === "/parent/api/tasks/parts_of_speech/nouns" && call.method === "GET" ? { body: page } : undefined;
  });
  const view = renderPortal("/parent/tasks/parts_of_speech/nouns");
  await screen.findByRole("heading", { name: "nouns" });
  return { calls, ...view };
}

const box = (name: string) => screen.getByRole("textbox", { name });
const save = () => screen.getByRole("button", { name: "Save" });
const posts = (calls: Call[]) => calls.filter((call) => call.method === "POST");

async function choose(name: string) {
  const button = screen.getByRole("button", { name: /^Pools/ });
  await userEvent.click(button);
  await userEvent.click(within(screen.getByRole("listbox", { name: "Pools" })).getByRole("option", { name }));
  await userEvent.keyboard("{Escape}");
}

describe("the defaults a parts of speech task page shows", () => {
  it("works the pass mark as min(7, 70% rounded up)", () => {
    expect([1, 2, 10, 12, 24].map(defaultRequired)).toEqual([1, 2, 7, 7, 7]);
    expect([3, 5, 9].map(defaultRequired)).toEqual([3, 4, 7]);
    expect(defaultRequired(0)).toBe(0);
  });

  it("makes the minimum follow a typed pass mark, and says nothing for an empty pool", () => {
    expect(questionPlaceholders(10, {})).toEqual({ correct_answers_required: "7", minimum_questions: "7", maximum_questions: "10" });
    expect(questionPlaceholders(10, { correct_answers_required: "4" }).minimum_questions).toBe("4");
    expect(questionPlaceholders(0, {})).toEqual({});
  });

  it("counts pools and sentences", () => {
    expect(poolCounts(["a", "b"], 24)).toBe("2 pools. 24 sentences.");
    expect(poolCounts(["a"], 1)).toBe("1 pool. 1 sentence.");
  });
});

describe("a parts of speech task page", () => {
  it("shows the settings, the filter, and the pools, with the sentences edited elsewhere", async () => {
    await openNouns();
    expect(box("Timeout")).toHaveAttribute("placeholder", "90s");
    expect(box("Correct Answers Required")).toHaveAttribute("placeholder", "7");
    expect(box("Minimum Questions")).toHaveAttribute("placeholder", "7");
    expect(box("Maximum Questions")).toHaveAttribute("placeholder", "12");
    expect(screen.getByRole("button", { name: "Pools Basics" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Parts of speech filter" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("1 pool. 12 sentences.");
    expect(screen.queryByRole("region", { name: "Sentence 1" })).not.toBeInTheDocument();
  });

  it("follows the chosen pools in its placeholders and the status bar, and choosing a pool is an edit", async () => {
    await openNouns();
    await choose("Spare");
    expect(screen.getByRole("status")).toHaveTextContent("2 pools. 14 sentences.");
    expect(box("Maximum Questions")).toHaveAttribute("placeholder", "14");
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    await choose("Spare");
    expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument();
  });

  it("links each chosen pool to its page, and asks before the link leaves with unsaved edits", async () => {
    const { router } = await openNouns();
    expect(screen.getByRole("link", { name: "Edit Basics" })).toHaveAttribute("href", "/parent/assets/parts-of-speech-pools/basics");
    await userEvent.type(box("Timeout"), "30s");
    await userEvent.click(screen.getByRole("link", { name: "Edit Basics" }));
    expect(await screen.findByRole("alertdialog", { name: "Leave this page?" })).toBeInTheDocument();
    expect(shown(router)).toBe("/parent/tasks/parts_of_speech/nouns");
  });

  it("blocks Save with no pool, saying why under the control and in Save's title", async () => {
    await openNouns();
    await choose("Basics");
    expect(screen.getByText("Choose at least one pool.")).toBeInTheDocument();
    expect(save()).toBeDisabled();
    expect(save()).toHaveAttribute("title", "Choose at least one pool.");
  });

  it("saves the pools, the filter in order, and the counts", async () => {
    const { calls } = await openNouns((call) => (call.method === "POST" ? { body: DONE } : undefined));
    await choose("Extra");
    await userEvent.type(box("Correct Answers Required"), "5");
    await userEvent.click(screen.getByRole("button", { name: "Add part" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Part 1" }), "verb");
    await userEvent.click(screen.getByRole("button", { name: "Add part" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Part 2" }), "Noun");
    await userEvent.click(screen.getByRole("button", { name: "Move part 2 up" }));
    expect(screen.getByRole("textbox", { name: "Part 1" })).toHaveValue("Noun");
    await userEvent.click(save());
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(posts(calls)[0].body).toMatchObject({
      version: "v1",
      pools: ["Basics", "Extra"],
      parts_of_speech: ["Noun", "verb"],
      settings: { correct_answers_required: "5" },
    });
  });

  it("blocks Save for an empty part, a long one, or two that differ only in case, and only warns for an unknown one", async () => {
    await openNouns();
    await userEvent.click(screen.getByRole("button", { name: "Add part" }));
    expect(screen.getByText("A part name must not be empty.")).toBeInTheDocument();
    expect(save()).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox", { name: "Part 1" }), "x".repeat(21));
    expect(screen.getByText("A part name is at most 20 characters.")).toBeInTheDocument();
    await userEvent.clear(screen.getByRole("textbox", { name: "Part 1" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Part 1" }), "colour");
    expect(screen.getByText('"colour" is not a recognized part of speech.')).toBeInTheDocument();
    expect(save()).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Add part" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Part 2" }), "COLOUR");
    expect(screen.getAllByText(/more than once/)).toHaveLength(2);
    expect(save()).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Remove part 2" }));
    expect(save()).toBeEnabled();
  });

  it("shows the reason a refused save gives in the status bar", async () => {
    await openNouns((call) =>
      call.method === "POST" ? { status: 400, body: { error: "This save would leave the policy unable to load, so nothing was saved.", errors: ["maximum_questions: must be a whole number from 7 to 12"] } } : undefined,
    );
    await userEvent.type(box("Maximum Questions"), "99");
    await userEvent.click(save());
    expect(await screen.findByText(/maximum_questions: must be a whole number/)).toBeInTheDocument();
  });
});
