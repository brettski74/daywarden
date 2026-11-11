import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { NO_FIRST, NO_OPERANDS, NO_ZERO_DIVISOR } from "./arithmetic";
import { FIX_ON_PAGE } from "./skipCounting";
import { SUMS, fakeService, renderPortal, type Call } from "./test/portal";

const TIMES = {
  ...SUMS,
  name: "times",
  type: "arithmetic",
  arithmetic: {
    settings: { operation: "addition", max_timeout: "10s", min_timeout: "4s", correct_answers_required: "20" },
    operations: [
      { name: "addition", label: "Addition" },
      { name: "subtraction", label: "Subtraction" },
      { name: "multiplication", label: "Multiplication" },
      { name: "division", label: "Division" },
    ],
    first: [{ from: "0", to: "", weight: "1" }],
    operands: [
      { from: "0", to: "", weight: "1" },
      { from: "2", to: "12", weight: "10" },
    ],
    problems: [],
  },
};

async function openTimes() {
  const calls = fakeService((call) => {
    if (call.method === "POST") return { body: { message: "Saved times.", warnings: [] } };
    return call.path === "/parent/api/tasks/arithmetic/times" ? { body: TIMES } : undefined;
  });
  renderPortal("/parent/tasks/arithmetic/times");
  await screen.findByRole("heading", { name: "times" });
  return calls;
}

const table = (name: string) => screen.getByRole("table", { name });
const rows = (name: string) => within(table(name)).getAllByRole("row").filter((row) => /^Row \d+$/.test(row.getAttribute("aria-label") ?? ""));
const box = (name: string, row: number, column: string) => within(rows(name)[row - 1]).getByRole("textbox", { name: column });
const operation = () => screen.getByRole("combobox", { name: "Operation" });
const status = () => screen.getByRole("status");
const save = () => screen.getByRole("button", { name: "Save" });
const posted = (calls: Call[]) => calls.filter((call) => call.method === "POST").map((call) => call.body as Record<string, unknown>);

describe("the arithmetic area of a task page", () => {
  it("shows the operation, the timer and target, and the First and Operands tables with three columns", async () => {
    await openTimes();
    expect(operation()).toHaveValue("addition");
    expect(within(operation()).getAllByRole("option").map((option) => option.textContent)).toEqual(["Addition", "Subtraction", "Multiplication", "Division"]);
    expect(screen.getByText("Operation")).toHaveAttribute("title", "operation");
    expect(screen.getByRole("textbox", { name: "Max Timeout" })).toHaveValue("10s");
    expect(screen.getByText("Min Timeout")).toHaveAttribute("title", "min_timeout");
    expect(within(table("Operands")).getAllByRole("columnheader").map((header) => header.textContent)).toEqual(["From", "To", "Weight", ""]);
    expect(box("Operands", 2, "To")).toHaveValue("12");
    expect(box("First", 1, "From")).toHaveValue("0");
    expect(status()).toHaveTextContent("No problems.");
    expect(screen.getByText("Each question is first + operand.")).toBeInTheDocument();
  });

  it("says how the chosen operation uses the tables, following the pull-down, and saves the choice", async () => {
    const calls = await openTimes();
    await userEvent.selectOptions(operation(), "subtraction");
    expect(screen.getByText("Each question is (first + operand) \u2212 first, and the answer is the operand.")).toBeInTheDocument();
    await userEvent.selectOptions(operation(), "multiplication");
    expect(screen.getByText("Each question is first \u00d7 operand.")).toBeInTheDocument();
    expect(operation()).toHaveAttribute("data-changed");
    await userEvent.click(save());
    await screen.findByText("Saved times.");
    expect(posted(calls)[0]).toMatchObject({ settings: { ...TIMES.arithmetic.settings, operation: "multiplication" }, lists: {} });
  });

  it("calls an empty timeout or target a problem under its box, and blocks Save", async () => {
    await openTimes();
    await userEvent.clear(screen.getByRole("textbox", { name: "Min Timeout" }));
    await userEvent.clear(screen.getByRole("textbox", { name: "Correct Answers Required" }));
    expect(screen.getByText("Min Timeout is required.")).toBeInTheDocument();
    expect(screen.getByText("Correct Answers Required is required.")).toBeInTheDocument();
    expect(status()).toHaveTextContent("2 problems.");
    expect(save()).toBeDisabled();
    expect(save()).toHaveAttribute("title", FIX_ON_PAGE);
  });

  it("accepts 0 and calls a negative number a problem", async () => {
    await openTimes();
    await userEvent.type(box("Operands", 1, "To"), "1");
    expect(status()).toHaveTextContent("No problems.");
    await userEvent.clear(box("Operands", 1, "From"));
    await userEvent.type(box("Operands", 1, "From"), "-1");
    expect(within(table("Operands")).getByText("From must be a whole number, 0 or more.")).toBeInTheDocument();
    expect(status()).toHaveTextContent("1 problem.");
  });

  it("calls Operands with no rows a problem, and leaves First out when it has none", async () => {
    const calls = await openTimes();
    await userEvent.click(within(rows("First")[0]).getByRole("button", { name: "Remove row" }));
    expect(screen.getByText(NO_FIRST)).toBeInTheDocument();
    expect(status()).toHaveTextContent("No problems.");
    await userEvent.click(save());
    await screen.findByText("Saved times.");
    expect(posted(calls)[0].lists).toEqual({ first: [] });
  });

  it("keeps Save from an operands table with no rows", async () => {
    await openTimes();
    for (let left = 2; left > 0; left -= 1) await userEvent.click(within(rows("Operands")[0]).getByRole("button", { name: "Remove row" }));
    expect(screen.getByText(NO_OPERANDS)).toBeInTheDocument();
    expect(status()).toHaveTextContent("1 problem.");
    expect(save()).toBeDisabled();
  });

  it("marks a 0 in the list division divides by, following the pull-down and the First table", async () => {
    await openTimes();
    expect(screen.queryByText(NO_ZERO_DIVISOR)).not.toBeInTheDocument();
    await userEvent.selectOptions(operation(), "division");
    expect(within(table("First")).getByText(NO_ZERO_DIVISOR)).toBeInTheDocument();
    expect(within(table("Operands")).queryByText(NO_ZERO_DIVISOR)).not.toBeInTheDocument();
    await userEvent.clear(box("First", 1, "From"));
    await userEvent.type(box("First", 1, "From"), "7");
    expect(screen.queryByText(NO_ZERO_DIVISOR)).not.toBeInTheDocument();
    await userEvent.click(within(rows("First")[0]).getByRole("button", { name: "Remove row" }));
    expect(within(table("Operands")).getByText(NO_ZERO_DIVISOR)).toBeInTheDocument();
    expect(save()).toBeDisabled();
    await userEvent.selectOptions(operation(), "addition");
    expect(screen.queryByText(NO_ZERO_DIVISOR)).not.toBeInTheDocument();
  });

  it("writes a changed table's rows from the keyboard, as in the skip counting table", async () => {
    const calls = await openTimes();
    await userEvent.click(box("Operands", 2, "Weight"));
    await userEvent.keyboard("{Enter}13{Tab}15{Enter}{Enter}");
    expect(screen.getAllByRole("button", { name: "Add row" })[1]).toHaveFocus();
    await userEvent.keyboard("{Control>}s{/Control}");
    await screen.findByText("Saved times.");
    expect(posted(calls)[0].lists).toEqual({
      operands: [
        { from: "0", to: "", weight: "1" },
        { from: "2", to: "12", weight: "10" },
        { from: "13", to: "15", weight: "" },
      ],
    });
  });
});
