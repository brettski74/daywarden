import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { factsAddress, shading, sortFacts, sortedBy, withChoice, type Fact } from "./facts";
import { ARITHMETIC_ATTEMPT, FACTS, TREND, fakeService, renderPortal, shown, type Call } from "./test/portal";

const VIEW = FACTS.view;
const facts = FACTS.facts.facts as Fact[];
const names = (list: Fact[]) => list.map((fact) => fact.cell);

function asked(calls: Call[], path: string): string[] {
  return calls.filter((call) => call.path === path).map((call) => call.search);
}

describe("the facts address and list", () => {
  it("keeps the view and leaves the page's choices out while they are their defaults", () => {
    expect(factsAddress("addition", { ...VIEW, range: "past-week", set: ["required"] })).toBe("/attempts/facts/addition?client=younger&range=past-week&set=required");
    expect(withChoice("?client=younger", { m: 7, n: 8, shade: "time" })).toBe("?client=younger&m=7&n=8&shade=time");
    expect(withChoice("?client=younger&m=7&n=8&shade=time", { shade: "misses" })).toBe("?client=younger&m=7&n=8");
  });

  it("sorts by Missed, then Asked, largest first, and a header sorts by its column and turns it round", () => {
    expect(names(sortFacts(facts, "missed", "desc"))).toEqual(["7 × 8", "6 × 8", "7 × 6"]);
    expect(names(sortFacts(facts, "asked", "desc"))).toEqual(["7 × 8", "6 × 8", "7 × 6"]);
    expect(names(sortFacts(facts, "median", "asc"))).toEqual(["7 × 6", "7 × 8", "6 × 8"]);
    // A fact never missed goes last whichever way Last missed is sorted.
    expect(names(sortFacts(facts, "last", "asc"))).toEqual(["6 × 8", "7 × 8", "7 × 6"]);
    expect(sortedBy("?client=younger", "fact")).toBe("?client=younger&sort=fact&dir=asc");
    expect(sortedBy("?client=younger&sort=fact&dir=asc", "fact")).toBe("?client=younger&sort=fact&dir=desc");
    expect(sortedBy("?client=younger", "missed")).toBe("?client=younger&sort=missed&dir=asc");
    expect(sortedBy("?client=younger&sort=missed&dir=asc", "missed")).toBe("?client=younger");
  });

  it("shades by the share missed, or by the median time of right answers with a band for none", () => {
    const misses = shading("misses", facts);
    expect(facts.map(misses.level)).toEqual([2, 0, 2]);
    const time = shading("time", [...facts, { ...facts[0], m: 9, median_ms: null }]);
    expect(time.bands.map((band) => band.label)).toEqual(["2.0 s to 2.5 s", "2.5 s to 3.0 s", "3.0 s to 3.5 s", "3.5 s to 4.0 s"]);
    expect([...facts, { ...facts[0], median_ms: null }].map(time.level)).toEqual([4, 1, 3, null]);
    expect(time.none).toBe("No right answers");
  });
});

describe("the facts page", () => {
  it("asks for the view alone, links to the other operations and back with it, and draws only the facts asked", async () => {
    const calls = fakeService();
    renderPortal("/parent/attempts/facts/multiplication?client=younger&m=7&n=8&shade=time");
    expect(await screen.findByRole("heading", { level: 1, name: "Multiplication facts" })).toBeInTheDocument();
    expect(asked(calls, "/parent/api/attempts/facts/multiplication")).toEqual(["?client=younger"]);
    const operations = screen.getByRole("navigation", { name: "Operations" });
    expect(within(operations).getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual([
      "/parent/attempts/facts/addition?client=younger",
      "/parent/attempts/facts/subtraction?client=younger",
      "/parent/attempts/facts/division?client=younger",
    ]);
    const crumbs = screen.getByRole("navigation", { name: "Where you are" });
    expect(within(crumbs).getByRole("link", { name: "Attempts" })).toHaveAttribute("href", "/parent/attempts?client=younger");

    const grid = screen.getByRole("table", { name: "Multiplication facts" });
    const rows = within(grid).getAllByRole("row");
    // The header row, then 6 and 7. 6 × 6 was never asked, so its cell is empty.
    expect(rows.map((row) => row.textContent)).toEqual(["68", "66 × 83/4", "77 × 62/27 × 83/5"]);
    expect(within(grid).getByRole("link", { name: "7 × 8 = 56, right 3 of 5" })).toHaveAttribute("aria-current", "true");
    expect(screen.getByText(/^Under each question: times right \/ times asked/)).toBeInTheDocument();
  });

  it("shows a fact's readout when it is pointed at or focused, and the arrow keys move between the facts asked", async () => {
    fakeService();
    renderPortal("/parent/attempts/facts/multiplication?client=younger");
    const grid = await screen.findByRole("table", { name: "Multiplication facts" });
    const sixEight = within(grid).getByRole("link", { name: /^6 × 8/ });
    const sevenSix = within(grid).getByRole("link", { name: /^7 × 6/ });
    const sevenEight = within(grid).getByRole("link", { name: /^7 × 8/ });
    expect([sixEight, sevenSix, sevenEight].map((link) => link.getAttribute("tabindex"))).toEqual(["0", "-1", "-1"]);

    fireEvent.pointerEnter(sevenEight);
    expect(await screen.findByText("Asked 5, right 3, wrong 1, timeouts 1")).toBeInTheDocument();
    expect(screen.getByText("Median time of right answers 3.0 s")).toBeInTheDocument();
    expect(screen.getByText("Last missed Friday 13 November 2026")).toBeInTheDocument();
    fireEvent.pointerLeave(sevenEight);

    sixEight.focus();
    fireEvent.keyDown(sixEight, { key: "ArrowDown" });
    expect(document.activeElement).toBe(sevenEight);
    fireEvent.keyDown(sevenEight, { key: "ArrowLeft" });
    expect(document.activeElement).toBe(sevenSix);
    // Up from 7 × 6 is 6 × 6, never asked, and nothing above it, so the focus stays.
    fireEvent.keyDown(sevenSix, { key: "ArrowUp" });
    expect(document.activeElement).toBe(sevenSix);
    expect(await screen.findByText("Last missed never")).toBeInTheDocument();
  });

  it("chooses a fact from the grid or the list without asking for the data again, and lists the attempts that asked it", async () => {
    const calls = fakeService();
    const { router } = renderPortal("/parent/attempts/facts/multiplication?client=younger");
    const grid = await screen.findByRole("table", { name: "Multiplication facts" });
    await userEvent.click(within(grid).getByRole("link", { name: /^7 × 8/ }));
    await waitFor(() => expect(shown(router)).toBe("/parent/attempts/facts/multiplication?client=younger&m=7&n=8"));
    const chosen = await screen.findByRole("table", { name: "Attempts that asked 7 × 8 = 56" });
    const rows = within(chosen).getAllByRole("row").slice(1);
    expect(rows.map((row) => [...row.querySelectorAll("td")].map((cell) => cell.textContent))).toEqual([
      ["Friday 13 November 2026, 16:00", "tables", "timeout, 56"],
      ["Tuesday 27 October 2026, 16:00", "times", "54, 54, 56"],
    ]);
    expect(within(rows[0]).getByRole("link")).toHaveAttribute("href", "/parent/attempts/9");

    const list = screen.getByRole("table", { name: "Facts" });
    // A click anywhere in the row chooses its fact.
    await userEvent.click(within(list).getByRole("link", { name: "7 × 6 = 42" }).closest("tr")!.querySelector("td:nth-child(2)")!);
    await waitFor(() => expect(shown(router)).toBe("/parent/attempts/facts/multiplication?client=younger&m=7&n=6"));
    expect(await screen.findByRole("table", { name: "Attempts that asked 7 × 6 = 42" })).toBeInTheDocument();
    expect(asked(calls, "/parent/api/attempts/facts/multiplication")).toHaveLength(1);
  });

  it("lists every fact, sorted by Missed then Asked, with a header that sorts by its column in the address", async () => {
    fakeService();
    const { router } = renderPortal("/parent/attempts/facts/multiplication?client=younger");
    const list = await screen.findByRole("table", { name: "Facts" });
    const body = () => within(list).getAllByRole("row").slice(2);
    expect(body().map((row) => [...row.querySelectorAll("td")].map((cell) => cell.textContent))).toEqual([
      ["7 × 8 = 56", "5", "3", "1", "1", "40%", "3.0 s", "Friday 13 November 2026", "6", "1", "3.1 s", "2.000", "0.000", "2.143"],
      ["6 × 8 = 48", "4", "3", "1", "0", "25%", "4.0 s", "Monday 9 November 2026", "9", "2", "6.0 s", "1.000", "2.000", "3.100"],
      ["7 × 6 = 42", "2", "2", "0", "0", "0%", "2.0 s", "", "12", "12", "1.9 s", "0.000", "0.000", "0.077"],
    ]);
    expect(within(list).getByRole("columnheader", { name: /Missed/ })).toHaveAttribute("aria-sort", "descending");
    await userEvent.click(within(list).getByRole("button", { name: "Median time" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/attempts/facts/multiplication?client=younger&sort=median&dir=desc"));
    await waitFor(() => expect(body()[0].querySelector("td")?.textContent).toBe("6 × 8 = 48"));
  });

  it("heads the all-time columns apart from the period's, and each sorts like the others", async () => {
    fakeService();
    const { router } = renderPortal("/parent/attempts/facts/multiplication?client=younger");
    const list = await screen.findByRole("table", { name: "Facts" });
    const groups = within(list).getAllByRole("row")[0];
    expect([...groups.querySelectorAll("th")].map((cell) => [cell.textContent, cell.getAttribute("colspan")])).toEqual([
      ["In this period", "8"],
      ["All time", "6"],
    ]);
    const first = () => within(list).getAllByRole("row")[2].querySelector("td")?.textContent;
    await userEvent.click(within(list).getByRole("button", { name: "Weight" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/attempts/facts/multiplication?client=younger&sort=weight&dir=desc"));
    await waitFor(() => expect(first()).toBe("6 × 8 = 48"));
    for (const [column, top] of [["All-time asked", "7 × 6 = 42"], ["Run", "7 × 6 = 42"], ["Smoothed time", "6 × 8 = 48"], ["Miss boost", "7 × 8 = 56"], ["Slow boost", "6 × 8 = 48"]]) {
      await userEvent.click(within(list).getByRole("button", { name: column }));
      await waitFor(() => expect(first()).toBe(top));
    }
  });

  it("shows the all-time figures in the readout and the operation's median line above the grid", async () => {
    fakeService();
    renderPortal("/parent/attempts/facts/multiplication?client=younger");
    const grid = await screen.findByRole("table", { name: "Multiplication facts" });
    expect(screen.getByText("Median 2.0 s. Slow from 4.0 s, full at 8.0 s.", { exact: false })).toHaveTextContent(
      "All time: Median 2.0 s. Slow from 4.0 s, full at 8.0 s.",
    );
    fireEvent.pointerEnter(within(grid).getByRole("link", { name: /^6 × 8/ }));
    expect(await screen.findByText("All time: asked 9, run 2, smoothed time 6.0 s")).toBeInTheDocument();
    expect(screen.getByText("All time: miss boost 1.000, slow boost 2.000, weight 3.100")).toBeInTheDocument();
  });

  it("shades by Weight with its own key and levels, kept in the address", async () => {
    expect(facts.map(shading("weight", facts).level)).toEqual([3, 0, 3]);
    const levels = [0.49, 0.5, 0.99, 1, 1.99, 2, 3.99, 4, 9].map((weight) => shading("weight", facts).level({ ...facts[0], all_time: { ...facts[0].all_time, weight } }));
    expect(levels).toEqual([0, 1, 1, 2, 2, 3, 3, 4, 4]);
    fakeService();
    const { router } = renderPortal("/parent/attempts/facts/multiplication?client=younger");
    await screen.findByRole("list", { name: "Shading" });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Shade by" }), "weight");
    await waitFor(() => expect(shown(router)).toBe("/parent/attempts/facts/multiplication?client=younger&shade=weight"));
    const key = screen.getByRole("list", { name: "Shading" });
    expect(within(key).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["Weight under 0.5", "0.5 to 1", "1 to 2", "2 to 4", "4 or more"]);
    expect(key).toHaveAttribute("data-shade", "weight");
    const grid = screen.getByRole("table", { name: "Multiplication facts" });
    expect(grid).toHaveAttribute("data-shade", "weight");
    expect(within(grid).getByRole("link", { name: /^7 × 6/ }).closest("td")).toHaveAttribute("data-level", "0");
    expect(withChoice("?client=younger&shade=weight", { m: 7, n: 8 })).toBe("?client=younger&m=7&n=8&shade=weight");
  });

  it("shades by Time when chosen, with a key, and keeps the choice in the address", async () => {
    fakeService();
    const { router } = renderPortal("/parent/attempts/facts/multiplication?client=younger");
    const key = await screen.findByRole("list", { name: "Shading" });
    expect(within(key).getAllByRole("listitem")[0]).toHaveTextContent("None missed");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Shade by" }), "time");
    await waitFor(() => expect(shown(router)).toBe("/parent/attempts/facts/multiplication?client=younger&shade=time"));
    await waitFor(() => expect(within(screen.getByRole("list", { name: "Shading" })).getByText("No right answers")).toBeInTheDocument());
  });

  it("says when there are no questions to show", async () => {
    const empty = { ...FACTS, operation: { name: "division", label: "Division" }, facts: null, message: "No division questions for younger in this period." };
    fakeService((call) => (call.path === "/parent/api/attempts/facts/division" ? { body: empty } : undefined));
    renderPortal("/parent/attempts/facts/division?client=younger");
    expect(await screen.findByText("No division questions for younger in this period.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByText(/^Under each question/)).toBeNull();
    // The median comes from his whole record, so it is shown whatever the period.
    expect(screen.getByText("All time:")).toBeInTheDocument();
  });

  it("is linked from an arithmetic task's trend with the same view", async () => {
    const week = { ...TREND, view: { ...TREND.view, range: "past-week", set: ["required"] } };
    fakeService((call) => (call.path === "/parent/api/attempts/tasks/arithmetic/sums" ? { body: week } : undefined));
    renderPortal("/parent/attempts/tasks/arithmetic/sums?client=younger&range=past-week&set=required");
    expect(await screen.findByRole("link", { name: "Addition facts" })).toHaveAttribute(
      "href",
      "/parent/attempts/facts/addition?client=younger&range=past-week&set=required",
    );
  });
});

describe("an arithmetic attempt's page", () => {
  it("sums up the last run and lists its questions, each linking to its fact over the past month", async () => {
    fakeService();
    renderPortal("/parent/attempts/43");
    expect(await screen.findByRole("heading", { name: "Last run" })).toBeInTheDocument();
    const summary = screen.getAllByRole("definition").map((each) => each.previousElementSibling?.textContent + ": " + each.textContent);
    expect(summary).toEqual(
      expect.arrayContaining([
        "Operation: Addition",
        "Points: 2 / 2 right",
        "Questions: 4",
        "Wrong: 1",
        "Timeouts: 1",
        "Time answering: 0:18",
        "Average per right answer: 2.3 s",
      ]),
    );
    const table = screen.getByRole("table", { name: "Last run's questions" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((row) => [...row.querySelectorAll("td")].map((cell) => cell.textContent))).toEqual([
      ["1", "6 + 7 = 13", "13", "Right", "2.0 s", "10.0 s"],
      ["2", "6 + 7 = 13", "12", "Wrong", "3.0 s", "10.0 s"],
      ["3", "7 + 8 = 15", "", "Timeout", "10.0 s", "10.0 s"],
      ["4", "2 + 0 = 2", "2", "Right", "2.5 s", "10.0 s"],
    ]);
    // A wrong answer and a timeout carry an icon and a word.
    expect(rows[1].querySelector("[data-outcome='incorrect'] svg")).not.toBeNull();
    expect(rows[2].querySelector("[data-outcome='timeout'] svg")).not.toBeNull();
    expect(within(rows[2]).getByRole("link", { name: "7 + 8 = 15" })).toHaveAttribute("href", "/parent/attempts/facts/addition?client=younger&m=7&n=8");
    expect(ARITHMETIC_ATTEMPT.arithmetic.expired).toHaveLength(1);
  });

  it("lists each practice walk under a Practice heading with its m, and each question with its step", async () => {
    fakeService();
    renderPortal("/parent/attempts/43");
    const practice = await screen.findByRole("region", { name: "Practice" });
    expect(within(practice).getByRole("heading", { name: "Practice" })).toBeInTheDocument();
    const walk = within(practice).getByRole("region", { name: "Practice walk 1" });
    expect(within(walk).getByRole("heading", { name: "Walk 1: m = 7, Addition, left early" })).toBeInTheDocument();
    const table = within(walk).getByRole("table", { name: "Practice walk 1's questions" });
    expect(within(table).getAllByRole("columnheader").map((head) => head.textContent)).toEqual([
      "#", "Step", "Question", "Answer given", "Outcome", "Time taken", "Time allowed",
    ]);
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((row) => [...row.querySelectorAll("td")].map((cell) => cell.textContent))).toEqual([
      ["1", "1 of 28", "7 + 1 = 8", "8", "Right", "1.5 s", "10.0 s"],
      ["2", "2 of 28", "7 + 2 = 9", "10", "Wrong", "2.5 s", "10.0 s"],
      ["3", "1 of 28", "7 + 1 = 8", "", "Timeout", "10.0 s", "10.0 s"],
    ]);
    // Practice is in no fact's figures, so its questions do not link to the facts page.
    expect(within(table).queryByRole("link")).toBeNull();
  });

  it("lists each expired run after the last under the time it expired", async () => {
    fakeService();
    renderPortal("/parent/attempts/43");
    const expired = await screen.findByRole("region", { name: "Run 1, expired Saturday 31 October 2026, 17:00" });
    expect(within(expired).getByText("0 / 2 right")).toBeInTheDocument();
    expect(within(expired).getByRole("table", { name: "Run 1's questions" })).toHaveTextContent("Wrong");
  });

  it("keeps the stored record in a section that starts closed and opens from its heading", async () => {
    fakeService();
    renderPortal("/parent/attempts/43");
    const toggle = await screen.findByRole("button", { name: "Stored record" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("last_activity")).toBeNull();
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByText("last_activity")).toBeInTheDocument();
    await userEvent.click(toggle);
    await waitFor(() => expect(screen.queryByText("last_activity")).toBeNull());
  });
});
