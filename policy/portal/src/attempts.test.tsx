import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { countSeries, formatClock, formatSeconds, readoutLines, shownOf, viewQuery, withShown, type View } from "./attempts";
import { ATTEMPTS, TREND, fakeService, renderPortal, shown, type Call } from "./test/portal";

const ALL: View = {
  client: "younger",
  range: "past-month",
  from: "",
  to: "",
  set: ["required", "potential", "practice"],
  outcome: ["pass", "failure", "abandoned", "unfinished", "in_progress"],
};

/** Answer the attempts endpoint with the view its address asks for, as the service does. */
function echo(call: Call) {
  if (call.path !== "/parent/api/attempts") return undefined;
  const asked = new URLSearchParams(call.search);
  const pick = (key: string, all: string[]) => (asked.has(key) ? all.filter((value) => asked.getAll(key).includes(value)) : all);
  const view = {
    client: asked.get("client") ?? "",
    range: asked.get("range") ?? "past-month",
    from: asked.get("from") ?? "",
    to: asked.get("to") ?? "",
    set: pick("set", ALL.set),
    outcome: pick("outcome", ALL.outcome),
  };
  return { body: { ...ATTEMPTS, client: view.client, view } };
}

function asked(calls: Call[], path: string): string[] {
  return calls.filter((call) => call.path === path).map((call) => call.search);
}

describe("the attempts address", () => {
  it("leaves out every choice still at its default", () => {
    expect(viewQuery(ALL)).toBe("?client=younger");
  });

  it("names the period, the chosen sets and outcomes, and none when nothing is chosen", () => {
    expect(viewQuery({ ...ALL, range: "custom", from: "2026-11-01", to: "2026-11-07", set: ["required", "potential"], outcome: [] })).toBe(
      "?client=younger&range=custom&from=2026-11-01&to=2026-11-07&set=required&set=potential&outcome=none",
    );
  });

  it("shows Points, Pass mark, Questions, and both times at first, and keeps a changed choice of lines", () => {
    expect(shownOf("", "points")).toEqual(["points", "pass_mark", "questions", "time", "average"]);
    const hidden = withShown("?client=younger", "points", "questions");
    expect(hidden).toBe("?client=younger&show=points&show=pass_mark&show=time&show=average");
    expect(withShown(hidden, "points", "questions")).toBe("?client=younger");
  });

  it("offers spelling's four in place of Points and Pass mark, and Maximum only when an attempt had one", () => {
    expect(countSeries("spelling", false).map((each) => each.name)).toEqual([
      "Current points",
      "Current required",
      "Revision points",
      "Revision required",
      "Questions",
      "Wrong",
      "Timeouts",
    ]);
    expect(countSeries("points", true).map((each) => each.key)).toContain("maximum");
  });

  it("reads time answering as m:ss and the average to one decimal place", () => {
    expect(formatClock(10)).toBe("0:10");
    expect(formatClock(125.4)).toBe("2:05");
    expect(formatSeconds(3)).toBe("3.0 s");
  });

  it("puts every figure in an attempt's readout", () => {
    expect(readoutLines(TREND.trend.points[0] as never)).toEqual([
      "Tuesday 27 October 2026, 16:00",
      "Required, Pass",
      "Points 20 / 20",
      "Questions 25",
      "Wrong 3, timeouts 2",
      "Time answering 1:10",
      "Average per right answer 2.5 s",
    ]);
  });
});

describe("the attempts page", () => {
  it("shows today, the overview, and the list, and a task opens its trend with the same view", async () => {
    const calls = fakeService(echo);
    renderPortal("/parent/attempts?client=younger&range=past-week&set=required");
    const overview = await screen.findByRole("table", { name: "Overview" });
    expect(screen.getByText("Today's score")).toBeInTheDocument();
    const task = within(overview).getByRole("link", { name: "spelling/spelling-week-3" });
    expect(task).toHaveAttribute("href", "/parent/attempts/tasks/spelling/spelling-week-3?client=younger&range=past-week&set=required");
    expect(within(overview).getByRole("img", { name: "1 attempt, latest 11 of 12" })).toBeInTheDocument();
    expect(within(overview).getByText("92%")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Attempts" })).toBeInTheDocument();
    expect(asked(calls, "/parent/api/attempts")).toContain("?client=younger&range=past-week&set=required");
  });

  it("marks a task gone from the policy and says when there is nothing to show", async () => {
    const gone = { ...ATTEMPTS.overview[0], in_policy: false };
    fakeService((call) => (call.path === "/parent/api/attempts" ? { body: { ...ATTEMPTS, overview: [gone] } } : undefined));
    renderPortal("/parent/attempts?client=younger");
    expect(await screen.findByText("not in the policy")).toBeInTheDocument();

    fakeService((call) => (call.path === "/parent/api/attempts" ? { body: { ...ATTEMPTS, overview: [], attempts: [] } } : undefined));
    renderPortal("/parent/attempts?client=older");
    expect(await screen.findByText("No attempts in this period.")).toBeInTheDocument();
  });

  it("puts the period in the address, and choosing another client group keeps the period and the filters", async () => {
    fakeService(echo);
    const { router } = renderPortal("/parent/attempts?client=younger&outcome=pass");
    const period = await screen.findByRole("combobox", { name: "Period" });
    expect(period).toHaveValue("past-month");
    await userEvent.selectOptions(period, "past-week");
    await waitFor(() => expect(shown(router)).toBe("/parent/attempts?client=younger&range=past-week&outcome=pass"));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Client group" }), "older");
    await waitFor(() => expect(shown(router)).toBe("/parent/attempts?client=older&range=past-week&outcome=pass"));
  });

  it("leaves practice out when Practice is turned off in Set", async () => {
    fakeService(echo);
    const { router } = renderPortal("/parent/attempts?client=younger");
    const set = await screen.findByRole("button", { name: /^Set / });
    await userEvent.click(set);
    await userEvent.click(await screen.findByRole("option", { name: "Practice" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/attempts?client=younger&set=required&set=potential"));
  });

  it("opens the Custom period's dates and sends them once they are real days", async () => {
    fakeService(echo);
    const { router } = renderPortal("/parent/attempts?client=younger");
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Period" }), "custom");
    await waitFor(() => expect(shown(router)).toBe("/parent/attempts?client=younger&range=custom&from=2026-10-17&to=2026-11-17"));
    const from = await screen.findByRole("textbox", { name: "From" });
    fireEvent.change(from, { target: { value: "2026-11-01" } });
    await waitFor(() => expect(shown(router)).toBe("/parent/attempts?client=younger&range=custom&from=2026-11-01&to=2026-11-17"));
  });
});

describe("a task's trend", () => {
  it("is headed by the task, links back with the same view, and lists its attempts", async () => {
    const calls = fakeService();
    renderPortal("/parent/attempts/tasks/arithmetic/sums?client=younger&range=past-week");
    expect(await screen.findByRole("heading", { level: 1, name: "arithmetic/sums" })).toBeInTheDocument();
    const crumbs = screen.getByRole("navigation", { name: "Where you are" });
    expect(within(crumbs).getByRole("link", { name: "Attempts" })).toHaveAttribute("href", "/parent/attempts?client=younger");
    expect(asked(calls, "/parent/api/attempts/tasks/arithmetic/sums")).toEqual(["?client=younger&range=past-week"]);
    const list = screen.getByRole("table", { name: "Attempts" });
    expect(within(list).getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual(["/parent/attempts/9", "/parent/attempts/7"]);
  });

  it("offers each line from the legend, with Points, Pass mark, and Questions shown at first, and keeps the choice in the address", async () => {
    const calls = fakeService();
    const { router } = renderPortal("/parent/attempts/tasks/arithmetic/sums?client=younger");
    const counts = await screen.findByRole("group", { name: "arithmetic/sums: counts" });
    const legend = within(counts.closest(".chart") as HTMLElement).getByRole("list", { name: "Lines" });
    const pressed = within(legend)
      .getAllByRole("button")
      .map((button) => [button.textContent, button.getAttribute("aria-pressed")]);
    expect(pressed).toEqual([
      ["Points", "true"],
      ["Pass mark", "true"],
      ["Questions", "true"],
      ["Wrong", "false"],
      ["Timeouts", "false"],
    ]);
    await userEvent.click(within(legend).getByRole("button", { name: "Wrong" }));
    await waitFor(() => expect(shown(router)).toContain("show=wrong"));
    await waitFor(() => expect(within(legend).getByRole("button", { name: "Wrong" })).toHaveAttribute("aria-pressed", "true"));
    // Showing a line does not ask for the data again.
    expect(asked(calls, "/parent/api/attempts/tasks/arithmetic/sums")).toHaveLength(1);
    expect(screen.getByRole("group", { name: "arithmetic/sums: times" })).toBeInTheDocument();
  });

  it("makes each attempt a link with its figures, moved between with the arrow keys, that Enter opens", async () => {
    fakeService();
    const { router } = renderPortal("/parent/attempts/tasks/arithmetic/sums?client=younger");
    const counts = await screen.findByRole("group", { name: "arithmetic/sums: counts" });
    const links = within(counts).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual(["/parent/attempts/7", "/parent/attempts/9"]);
    expect(links[0]).toHaveAccessibleName(/^Tuesday 27 October 2026, 16:00\. Required, Pass\. Points 20 \/ 20/);
    expect(links.map((link) => link.getAttribute("tabindex"))).toEqual(["-1", "0"]);
    const hollow = links[1].querySelectorAll("[data-hollow]");
    expect(hollow.length).toBeGreaterThan(0);
    expect(links[1].querySelector("[data-outcome='abandoned']")).not.toBeNull();

    links[1].focus();
    expect(await screen.findByText("Practice, Abandoned")).toBeInTheDocument();
    fireEvent.keyDown(links[1], { key: "ArrowLeft" });
    expect(document.activeElement).toBe(links[0]);
    expect(await screen.findByText("Required, Pass")).toBeInTheDocument();
    fireEvent.keyDown(links[0], { key: "Enter" });
    await waitFor(() => expect(shown(router)).toBe("/parent/attempts/7"));
  });

  it("offers spelling's four lines and Maximum only when an attempt had one", async () => {
    const spelling = { ...TREND, task: { ...TREND.task, type: "spelling", name: "week", label: "spelling/week" }, trend: { ...TREND.trend, kind: "spelling", has_maximum: false } };
    fakeService((call) => (call.path === "/parent/api/attempts/tasks/spelling/week" ? { body: spelling } : undefined));
    renderPortal("/parent/attempts/tasks/spelling/week?client=younger");
    const counts = await screen.findByRole("group", { name: "spelling/week: counts" });
    const names = within(within(counts.closest(".chart") as HTMLElement).getByRole("list", { name: "Lines" }))
      .getAllByRole("button")
      .map((button) => button.textContent);
    expect(names).toEqual(["Current points", "Current required", "Revision points", "Revision required", "Questions", "Wrong", "Timeouts"]);
  });

  it("says when there are no attempts to show", async () => {
    const empty = { ...TREND, task: { ...TREND.task, name: "nothing", label: "arithmetic/nothing" }, trend: null, message: "No attempts at arithmetic/nothing for younger in this period." };
    fakeService((call) => (call.path === "/parent/api/attempts/tasks/arithmetic/nothing" ? { body: empty } : undefined));
    renderPortal("/parent/attempts/tasks/arithmetic/nothing?client=younger");
    expect(await screen.findByText("No attempts at arithmetic/nothing for younger in this period.")).toBeInTheDocument();
  });

  it("asks a signed-out parent to sign in and comes back to the trend", async () => {
    fakeService(() => ({ status: 401, body: { error: "Sign in to see this." } }));
    const { router } = renderPortal("/parent/attempts/tasks/arithmetic/sums?client=younger");
    await waitFor(() => expect(shown(router)).toBe("/parent/login?next=%2Fparent%2Fattempts%2Ftasks%2Farithmetic%2Fsums%3Fclient%3Dyounger"));
  });
});
