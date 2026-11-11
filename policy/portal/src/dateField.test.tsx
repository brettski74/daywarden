import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { NOT_A_DATE } from "./dates";
import { FIX_ON_PAGE } from "./skipCounting";
import { SUMS, fakeService, renderPortal, type Call } from "./test/portal";

const SUMS_API = "/parent/api/tasks/worksheet/sums";

/** Open the sums task page, with its fields changed as given. */
async function openSums(fields: Record<string, string> = {}) {
  const calls = fakeService((call) => {
    if (call.path !== SUMS_API) return undefined;
    if (call.method === "POST") return { body: { message: "Saved sums.", warnings: [] } };
    return { body: { ...SUMS, fields: { ...SUMS.fields, ...fields } } };
  });
  renderPortal("/parent/tasks/worksheet/sums");
  await screen.findByRole("heading", { name: "sums" });
  return calls;
}

const box = (name: string) => screen.getByRole("textbox", { name });
const calendarButton = (name: string) => screen.getByRole("button", { name: `Choose ${name}` });
const calendar = (name = "Due Date") => screen.getByRole("dialog", { name: `Choose ${name}` });
const day = (label: string) => within(calendar()).getByRole("button", { name: label });
const save = () => screen.getByRole("button", { name: "Save" });
const posts = (calls: Call[]) => calls.filter((call) => call.method === "POST");

describe("a date field", () => {
  it("keeps its yyyy-mm-dd box beside a calendar button, and saves a typed date", async () => {
    const calls = await openSums();
    expect(box("Available From")).toHaveAttribute("placeholder", "yyyy-mm-dd");
    expect(calendarButton("Available From")).toHaveAttribute("title", "Choose Available From");
    expect(calendarButton("Due Date")).toHaveAttribute("title", "Choose Due Date");

    await userEvent.type(box("Due Date"), " 2026-11-30 ");
    expect(screen.queryByText(NOT_A_DATE)).not.toBeInTheDocument();
    await userEvent.keyboard("{Control>}s{/Control}");
    expect(await screen.findByText("Saved sums.")).toBeInTheDocument();
    expect(posts(calls)[0].body).toMatchObject({ fields: { due_date: " 2026-11-30 " } });
  });

  it.each(["2026-11-31", "10/11/2026", "2026-1-5"])("calls %j not a date and holds Save until it is fixed or emptied", async (text) => {
    const calls = await openSums();
    await userEvent.type(box("Available From"), text);
    expect(screen.getByText(NOT_A_DATE)).toBeInTheDocument();
    expect(box("Available From")).toHaveAttribute("aria-invalid", "true");
    expect(save()).toBeDisabled();
    expect(save()).toHaveAttribute("title", FIX_ON_PAGE);
    await userEvent.keyboard("{Control>}s{/Control}");
    expect(screen.getByRole("status")).toHaveTextContent(FIX_ON_PAGE);
    expect(posts(calls)).toHaveLength(0);

    await userEvent.clear(box("Available From"));
    expect(screen.queryByText(NOT_A_DATE)).not.toBeInTheDocument();
    expect(save()).toBeDisabled();
    expect(save()).toHaveAttribute("title", "Nothing to save");
  });
});

describe("the calendar", () => {
  it("opens on the household's today with none selected, and a click puts the day in the box as a change", async () => {
    await openSums();
    await userEvent.click(calendarButton("Due Date"));
    expect(calendarButton("Due Date")).toHaveAttribute("aria-expanded", "true");
    expect(calendar()).toHaveTextContent("November 2026");
    expect(within(calendar()).getAllByRole("columnheader").map((head) => head.textContent)).toEqual(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]);
    const today = day("Tuesday 10 November 2026");
    expect(today).toHaveAttribute("aria-current", "date");
    expect(today).toHaveAttribute("title", "Tuesday 10 November 2026");
    expect(today).toHaveFocus();
    expect(within(calendar()).queryByRole("gridcell", { selected: true })).not.toBeInTheDocument();
    expect(within(calendar()).getAllByRole("gridcell")).toHaveLength(30);

    await userEvent.click(day("Monday 30 November 2026"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(box("Due Date")).toHaveValue("2026-11-30");
    expect(box("Due Date")).toHaveFocus();
    expect(box("Due Date")).toHaveAttribute("data-changed");
    expect(screen.getByRole("banner")).toHaveTextContent("Unsaved changes");
    expect(save()).toBeEnabled();
  });

  it("opens with Alt+Down on the box's own day, selected and focused, and on today's month when the box is not a date", async () => {
    await openSums({ available_from: "2027-02-14" });
    await userEvent.click(box("Available From"));
    await userEvent.keyboard("{Alt>}{ArrowDown}{/Alt}");
    expect(calendar("Available From")).toHaveTextContent("February 2027");
    const selected = within(calendar("Available From")).getByRole("gridcell", { selected: true });
    expect(within(selected).getByRole("button")).toHaveAccessibleName("Sunday 14 February 2027");
    expect(within(selected).getByRole("button")).toHaveFocus();
    await userEvent.keyboard("{Escape}");

    await userEvent.type(box("Available From"), "x");
    await userEvent.click(calendarButton("Available From"));
    expect(calendar("Available From")).toHaveTextContent("November 2026");
    expect(within(calendar("Available From")).queryByRole("gridcell", { selected: true })).not.toBeInTheDocument();
  });

  it("closes with the button again, Escape, or a click outside, leaving the field as it was", async () => {
    await openSums({ due_date: "2026-11-30" });
    await userEvent.click(calendarButton("Due Date"));
    await userEvent.click(calendarButton("Due Date"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.click(calendarButton("Due Date"));
    await userEvent.keyboard("{ArrowRight}{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(calendarButton("Due Date")).toHaveFocus();

    await userEvent.click(calendarButton("Due Date"));
    await userEvent.click(box("Max Skips"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(box("Due Date")).toHaveValue("2026-11-30");
    expect(save()).toBeDisabled();
  });

  it("closes one date field's calendar when the other's opens", async () => {
    await openSums();
    await userEvent.click(calendarButton("Available From"));
    await userEvent.click(calendarButton("Due Date"));
    expect(screen.getAllByRole("dialog")).toEqual([calendar("Due Date")]);
  });

  it("does not count picking the saved date as a change", async () => {
    await openSums({ due_date: "2026-11-30" });
    await userEvent.click(calendarButton("Due Date"));
    await userEvent.click(day("Monday 30 November 2026"));
    expect(box("Due Date")).not.toHaveAttribute("data-changed");
    expect(save()).toBeDisabled();
    expect(screen.getByRole("banner")).not.toHaveTextContent("Unsaved changes");
  });

  it("turns the month with its month buttons", async () => {
    await openSums();
    await userEvent.click(calendarButton("Due Date"));
    await userEvent.click(within(calendar()).getByRole("button", { name: "Next month" }));
    expect(calendar()).toHaveTextContent("December 2026");
    await userEvent.click(within(calendar()).getByRole("button", { name: "Previous month" }));
    await userEvent.click(within(calendar()).getByRole("button", { name: "Previous month" }));
    expect(calendar()).toHaveTextContent("October 2026");
    expect(within(calendar()).getAllByRole("gridcell")).toHaveLength(31);
  });

  it("puts today in the box with Today, and empties it with Clear", async () => {
    await openSums({ due_date: "2026-12-25" });
    await userEvent.click(calendarButton("Due Date"));
    await userEvent.click(within(calendar()).getByRole("button", { name: "Today" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(box("Due Date")).toHaveValue("2026-11-10");

    await userEvent.click(calendarButton("Due Date"));
    await userEvent.click(within(calendar()).getByRole("button", { name: "Clear" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(box("Due Date")).toHaveValue("");
    expect(box("Due Date")).toHaveAttribute("data-changed");
  });

  it("moves by day, week, week's end, month, and year with the keys, and picks with Enter", async () => {
    await openSums({ due_date: "2026-01-31" });
    await userEvent.click(box("Due Date"));
    await userEvent.keyboard("{Alt>}{ArrowDown}{/Alt}");
    const focused = () => (document.activeElement as HTMLElement).getAttribute("aria-label");
    expect(focused()).toBe("Saturday 31 January 2026");
    const steps: [string, string][] = [
      ["{PageDown}", "Saturday 28 February 2026"],
      ["{Shift>}{PageDown}{/Shift}", "Sunday 28 February 2027"],
      ["{ArrowRight}", "Monday 1 March 2027"],
      ["{ArrowUp}", "Monday 22 February 2027"],
      ["{Home}", "Sunday 21 February 2027"],
      ["{End}", "Saturday 27 February 2027"],
      ["{ArrowDown}", "Saturday 6 March 2027"],
      ["{ArrowLeft}", "Friday 5 March 2027"],
      ["{PageUp}", "Friday 5 February 2027"],
      ["{Shift>}{PageUp}{/Shift}", "Thursday 5 February 2026"],
    ];
    for (const [keys, expected] of steps) {
      await userEvent.keyboard(keys);
      expect(focused()).toBe(expected);
    }
    expect(calendar()).toHaveTextContent("February 2026");
    await userEvent.keyboard("{Enter}");
    expect(box("Due Date")).toHaveValue("2026-02-05");
    expect(box("Due Date")).toHaveFocus();
  });

  it("picks the focused day with Space too", async () => {
    await openSums();
    await userEvent.click(calendarButton("Available From"));
    await userEvent.keyboard("{ArrowLeft} ");
    expect(box("Available From")).toHaveValue("2026-11-09");
  });

  it("keeps Tab and Shift+Tab inside the calendar, among the month buttons, the focused day, Today, and Clear", async () => {
    await openSums();
    await userEvent.click(calendarButton("Due Date"));
    const order = [
      within(calendar()).getByRole("button", { name: "Today" }),
      within(calendar()).getByRole("button", { name: "Clear" }),
      within(calendar()).getByRole("button", { name: "Previous month" }),
      within(calendar()).getByRole("button", { name: "Next month" }),
      day("Tuesday 10 November 2026"),
    ];
    for (const stop of order) {
      await userEvent.tab();
      expect(stop).toHaveFocus();
    }
    await userEvent.tab({ shift: true });
    expect(within(calendar()).getByRole("button", { name: "Next month" })).toHaveFocus();
  });
});
