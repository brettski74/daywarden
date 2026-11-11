import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DEFAULT_NOTE, FIX_ON_PAGE, NO_DIFFERENCES } from "./skipCounting";
import { SUMS, fakeService, renderPortal, type Call, type Reply } from "./test/portal";

const blank = { minimum_value: "", maximum_value: "", multiples_only: null };
const SETTINGS = {
  sequence_length: "6",
  completed: "",
  minimum_value: "",
  maximum_value: "",
  consecutive: "",
  multiples_only: "",
  timeout: "",
  correct_answers_required: "",
  minimum_questions: "",
  maximum_questions: "",
};
const DEFAULT = [2, 5, 10, 25, 100, -2, -5, -10, -25, -100].map((value) => {
  const cap = { 2: "99", 5: "199", 10: "499" }[Math.abs(value)] ?? "";
  return { from: String(value), to: "", weight: "1", minimum_value: "", maximum_value: cap, multiples_only: Math.abs(value) === 25 ? true : null };
});
const OWN = {
  ...SUMS,
  name: "counting",
  type: "skip_counting",
  skip_counting: {
    settings: SETTINGS,
    flags: { consecutive: true, multiples_only: false },
    difference: [
      { from: "2", to: "", weight: "3", ...blank, maximum_value: "99" },
      { from: "3", to: "9", weight: "1", ...blank },
    ],
    default: DEFAULT,
    problems: [],
  },
};
const DEFAULTED = { ...OWN, skip_counting: { ...OWN.skip_counting, difference: null } };
const SAVED = { body: { message: "Saved counting. The decisions, observations, and autoconfig services are using it.", warnings: [] } };

async function openCounting(data: unknown = OWN, handler?: (call: Call) => Reply | undefined) {
  const calls = fakeService((call) => {
    const answered = handler?.(call);
    if (answered) return answered;
    if (call.method === "POST") return SAVED;
    return call.path === "/parent/api/tasks/skip_counting/counting" ? { body: data } : undefined;
  });
  renderPortal("/parent/tasks/skip_counting/counting");
  await screen.findByRole("heading", { name: "counting" });
  return calls;
}

const table = () => screen.getByRole("table", { name: "Differences" });
const rows = () => within(table()).getAllByRole("row").filter((row) => /^Row \d+$/.test(row.getAttribute("aria-label") ?? ""));
const box = (row: number, name: string) => within(rows()[row - 1]).getByRole(name === "Multiples Only" ? "combobox" : "textbox", { name });
const values = () => rows().map((row) => within(row).getAllByRole("textbox").map((input) => (input as HTMLInputElement).value));
const status = () => screen.getByRole("status");
const save = () => screen.getByRole("button", { name: "Save" });
const setting = (name: string) => screen.getByRole("textbox", { name });
const posted = (calls: Call[]) => calls.filter((call) => call.method === "POST").map((call) => call.body as Record<string, unknown>);

describe("the skip counting area of a task page", () => {
  it("shows the settings in two groups with their defaults, then the differences as rows", async () => {
    await openCounting();
    const questions = screen.getByRole("group", { name: "Questions" });
    expect(within(questions).getByRole("textbox", { name: "Sequence Length" })).toHaveValue("6");
    expect(within(questions).getByText("Sequence Length")).toHaveAttribute("title", "sequence_length");
    expect(within(questions).getByRole("checkbox", { name: "Consecutive" })).toBeChecked();
    expect(within(questions).getByRole("checkbox", { name: "Multiples Only" })).not.toBeChecked();
    const placeholders = ["Completed", "Minimum Value", "Maximum Value", "Timeout", "Maximum Questions", "Correct Answers Required", "Minimum Questions"].map((name) =>
      setting(name).getAttribute("placeholder"),
    );
    expect(placeholders).toEqual(["3", "1", "999", "3m", "None", "8", "8"]);
    expect(within(screen.getByRole("group", { name: "Session" })).getByRole("textbox", { name: "Timeout" })).toBeInTheDocument();
    expect(within(table()).getAllByRole("columnheader").map((header) => [header.textContent, header.getAttribute("title")])).toEqual([
      ["From", "from"],
      ["To", "to"],
      ["Weight", "weight"],
      ["Min", "minimum_value"],
      ["Max", "maximum_value"],
      ["Multiples Only", "multiples_only"],
      ["", null],
    ]);
    expect(values()).toEqual([
      ["2", "", "3", "", "99"],
      ["3", "9", "1", "", ""],
    ]);
    expect(box(1, "Weight")).toHaveAttribute("placeholder", "1");
    expect(box(2, "Min")).toHaveAttribute("placeholder", "1");
    expect(box(2, "Max")).toHaveAttribute("placeholder", "999");
    expect(within(rows()[0]).getByRole("button", { name: "Remove row" })).toHaveAttribute("title", "Remove row");
    expect(status()).toHaveTextContent("2 differences. None with problems.");
    expect(screen.queryByText(DEFAULT_NOTE)).not.toBeInTheDocument();
  });

  it("works out Correct Answers Required from the questions on the page, and Minimum Questions from it", async () => {
    await openCounting();
    await userEvent.type(setting("Maximum Questions"), "5");
    expect(setting("Correct Answers Required")).toHaveAttribute("placeholder", "5");
    expect(setting("Minimum Questions")).toHaveAttribute("placeholder", "5");
    await userEvent.clear(setting("Maximum Questions"));
    await userEvent.type(setting("Minimum Questions"), "12");
    expect(setting("Correct Answers Required")).toHaveAttribute("placeholder", "10");
    await userEvent.clear(setting("Minimum Questions"));
    await userEvent.type(setting("Correct Answers Required"), "4");
    expect(setting("Minimum Questions")).toHaveAttribute("placeholder", "4");
  });

  it("follows the task's Minimum Value, Maximum Value, and Multiples Only in each row's placeholders", async () => {
    await openCounting();
    await userEvent.type(setting("Minimum Value"), "-20");
    await userEvent.type(setting("Maximum Value"), "300");
    await userEvent.click(screen.getByRole("checkbox", { name: "Multiples Only" }));
    expect(box(2, "Min")).toHaveAttribute("placeholder", "-20");
    expect(box(2, "Max")).toHaveAttribute("placeholder", "300");
    expect(within(box(2, "Multiples Only")).getAllByRole("option").map((option) => option.textContent)).toEqual(["Task's (Yes)", "Yes", "No"]);
  });

  it("writes a checkbox only when it differs from the value in force", async () => {
    const calls = await openCounting();
    const consecutive = screen.getByRole("checkbox", { name: "Consecutive" });
    await userEvent.click(consecutive);
    expect(screen.getByRole("banner")).toHaveTextContent("Unsaved changes");
    await userEvent.click(consecutive);
    expect(screen.getByRole("banner")).not.toHaveTextContent("Unsaved changes");
    expect(save()).toBeDisabled();
    await userEvent.click(consecutive);
    await userEvent.keyboard("{Control>}s{/Control}");
    expect(await screen.findByText(/^Saved counting\./)).toBeInTheDocument();
    expect(posted(calls)[0]).toMatchObject({ settings: { ...SETTINGS, consecutive: "false" }, lists: {} });
  });
});

describe("the keyboard in the table", () => {
  it("adds rows with Enter and Tab past the end, and removes an empty last row with Enter", async () => {
    const calls = await openCounting();
    await userEvent.click(box(2, "Weight"));
    await userEvent.keyboard("{Enter}");
    expect(rows()).toHaveLength(3);
    expect(box(3, "From")).toHaveFocus();
    expect(rows()[2]).toHaveAttribute("data-changed");
    await userEvent.keyboard("-2{Enter}-5{Tab}{Tab}2{Enter}");
    expect(values()).toEqual([
      ["2", "", "3", "", "99"],
      ["3", "9", "1", "", ""],
      ["-2", "", "", "", ""],
      ["-5", "", "2", "", ""],
      ["", "", "", "", ""],
    ]);
    expect(box(5, "From")).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(rows()).toHaveLength(4);
    expect(screen.getByRole("button", { name: "Add row" })).toHaveFocus();

    within(rows()[3]).getByRole("button", { name: "Remove row" }).focus();
    await userEvent.tab();
    expect(rows()).toHaveLength(5);
    expect(box(5, "From")).toHaveFocus();
    for (let control = 0; control < 6; control += 1) await userEvent.tab();
    expect(within(rows()[4]).getByRole("button", { name: "Remove row" })).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Add row" })).toHaveFocus();
    expect(rows()).toHaveLength(4);

    await userEvent.keyboard("{Control>}s{/Control}");
    await screen.findByText(/^Saved counting\./);
    expect(posted(calls)[0].lists).toEqual({
      difference: [
        { from: "2", to: "", weight: "3", ...blank, maximum_value: "99" },
        { from: "3", to: "9", weight: "1", ...blank },
        { from: "-2", to: "", weight: "", ...blank },
        { from: "-5", to: "", weight: "2", ...blank },
      ],
    });
  });

  it("moves Enter to the next row's From with its contents selected", async () => {
    await openCounting();
    await userEvent.click(box(1, "Max"));
    await userEvent.keyboard("{Enter}");
    const next = box(2, "From") as HTMLInputElement;
    expect(next).toHaveFocus();
    expect([next.selectionStart, next.selectionEnd]).toEqual([0, 1]);
    await userEvent.keyboard("4");
    expect(next).toHaveValue("4");
  });

  it("removes a row cleared in the middle of the table once the focus leaves it, and Shift+Tab goes on", async () => {
    await openCounting();
    await userEvent.clear(box(2, "From"));
    await userEvent.clear(box(2, "To"));
    await userEvent.clear(box(2, "Weight"));
    expect(rows()).toHaveLength(2);
    box(2, "From").focus();
    await userEvent.tab({ shift: true });
    expect(rows()).toHaveLength(1);
    expect(within(rows()[0]).getByRole("button", { name: "Remove row" })).toHaveFocus();
  });

  it("adds an empty row with Add row, focused in From, and removes a row at once with its button", async () => {
    await openCounting();
    await userEvent.click(screen.getByRole("button", { name: "Add row" }));
    expect(rows()).toHaveLength(3);
    expect(box(3, "From")).toHaveFocus();
    await userEvent.keyboard("12");
    await userEvent.click(within(rows()[0]).getByRole("button", { name: "Remove row" }));
    expect(values()).toEqual([
      ["3", "9", "1", "", ""],
      ["12", "", "", "", ""],
    ]);
    expect(box(1, "From")).toHaveFocus();
    expect(status()).toHaveTextContent("2 differences. None with problems.");
    await userEvent.click(within(rows()[0]).getByRole("button", { name: "Remove row" }));
    await userEvent.click(within(rows()[0]).getByRole("button", { name: "Remove row" }));
    expect(screen.getByRole("button", { name: "Add row" })).toHaveFocus();
  });
});

describe("problems in the table", () => {
  it("marks each problem under its row, blocks Save, and Ctrl+S says why", async () => {
    const calls = await openCounting();
    await userEvent.type(box(1, "To"), "5");
    await userEvent.clear(box(2, "From"));
    await userEvent.type(box(2, "From"), "-1");
    expect(within(table()).getByText("2 is also in row 2.")).toBeInTheDocument();
    expect(within(table()).getByText("2 is also in row 1.")).toBeInTheDocument();
    expect(within(table()).getByText("0 is not a difference. Write one range below zero and another above it.")).toBeInTheDocument();
    expect(status()).toHaveTextContent("2 differences. 2 with problems.");
    expect(save()).toBeDisabled();
    expect(save()).toHaveAttribute("title", FIX_ON_PAGE);
    await userEvent.keyboard("{Control>}s{/Control}");
    expect(status()).toHaveTextContent(FIX_ON_PAGE);
    expect(posted(calls)).toHaveLength(0);
  });

  it("calls a table with no rows a problem", async () => {
    await openCounting();
    for (let left = 2; left > 0; left -= 1) await userEvent.click(within(rows()[0]).getByRole("button", { name: "Remove row" }));
    expect(screen.getByText(NO_DIFFERENCES)).toBeInTheDocument();
    expect(save()).toBeDisabled();
  });
});

describe("the default list", () => {
  it("shows the default rows with their caps under a note, following Maximum Value", async () => {
    await openCounting(DEFAULTED);
    expect(screen.getByText(DEFAULT_NOTE)).toBeInTheDocument();
    expect(values().slice(0, 5).map((row) => [row[0], row[4]])).toEqual([
      ["2", "99"],
      ["5", "199"],
      ["10", "499"],
      ["25", ""],
      ["100", ""],
    ]);
    expect(box(4, "Multiples Only")).toHaveValue("yes");
    expect(status()).toHaveTextContent("Default list of 10 differences. None with problems.");
    expect(screen.queryByRole("button", { name: "Use the default list" })).not.toBeInTheDocument();
    await userEvent.type(setting("Maximum Value"), "150");
    expect(values().slice(0, 3).map((row) => row[4])).toEqual(["99", "150", "150"]);
    expect(screen.getByText(DEFAULT_NOTE)).toBeInTheDocument();
  });

  it("becomes the task's own list once a row changes, and saving writes it whole", async () => {
    const calls = await openCounting(DEFAULTED);
    for (let left = 10; left > 2; left -= 1) await userEvent.click(within(rows()[2]).getByRole("button", { name: "Remove row" }));
    expect(screen.queryByText(DEFAULT_NOTE)).not.toBeInTheDocument();
    expect(status()).toHaveTextContent("2 differences.");
    await userEvent.click(save());
    await screen.findByText(/^Saved counting\./);
    expect(posted(calls)[0].lists).toEqual({
      difference: [
        { from: "2", to: "", weight: "1", ...blank, maximum_value: "99" },
        { from: "5", to: "", weight: "1", ...blank, maximum_value: "199" },
      ],
    });
  });

  it("is not written while its rows are unchanged, even after a box is changed back", async () => {
    const calls = await openCounting(DEFAULTED);
    await userEvent.type(box(1, "Weight"), "2");
    expect(screen.queryByText(DEFAULT_NOTE)).not.toBeInTheDocument();
    expect(box(1, "Weight")).toHaveAttribute("data-changed");
    await userEvent.type(box(1, "Weight"), "{Backspace}");
    expect(screen.getByText(DEFAULT_NOTE)).toBeInTheDocument();
    await userEvent.type(setting("Timeout"), "2m");
    await userEvent.click(save());
    await screen.findByText(/^Saved counting\./);
    expect(posted(calls)[0].lists).toEqual({});
  });

  it("can take the place of the task's own list, and saving removes the list", async () => {
    const calls = await openCounting();
    await userEvent.click(screen.getByRole("button", { name: "Use the default list" }));
    expect(screen.getByText(DEFAULT_NOTE)).toBeInTheDocument();
    expect(rows()).toHaveLength(10);
    expect(rows()[0]).toHaveAttribute("data-changed");
    expect(screen.queryByRole("button", { name: "Use the default list" })).not.toBeInTheDocument();
    await userEvent.click(save());
    await screen.findByText(/^Saved counting\./);
    expect(posted(calls)[0].lists).toEqual({ difference: "default" });
  });
});
