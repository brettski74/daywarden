import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { USAGE_KEY } from "./sidebar";
import { USAGE, fakeService, renderPortal, shown, type Call } from "./test/portal";
import { bytesAxis, durationAxis, formatBytes, formatDuration, settingsQuery, type Settings } from "./usage";

const DEFAULT_ADDRESS = "/parent/usage/minutes?by=client&range=past-week";

function usageCalls(calls: Call[]): string[] {
  return calls.filter((call) => call.path.startsWith("/parent/api/usage/")).map((call) => call.path + call.search);
}

function withSettings(settings: Partial<Settings>, extra: Record<string, unknown> = {}) {
  return { ...USAGE, settings: { ...USAGE.settings, ...settings }, ...extra };
}

/** Answer a graph request whose address holds settings with those settings, as the service does. */
function echo(call: Call) {
  const asked = new URLSearchParams(call.search);
  if (!/^\/parent\/api\/usage\/(minutes|bytes)$/.test(call.path) || !asked.has("by")) return undefined;
  const settings = {
    client: asked.getAll("client"),
    site: asked.getAll("site"),
    quota: asked.getAll("quota"),
    by: asked.get("by"),
    range: asked.get("range"),
    from: asked.get("from") ?? "",
    to: asked.get("to") ?? "",
  };
  return { body: { ...USAGE, unit: call.path.endsWith("bytes") ? "bytes" : "minutes", preset: "", settings } };
}

async function openUsage(address = "/parent/usage/minutes", answer?: (call: Call) => { status?: number; body?: unknown } | undefined) {
  const calls = fakeService((call) => answer?.(call) ?? echo(call));
  const view = renderPortal(address);
  await screen.findByRole("group", { name: /^(Minutes|Bytes) / });
  return { calls, ...view };
}

describe("Usage in the sidebar", () => {
  it("is a group that expands into Minutes and Bytes, and remembers whether it is expanded", async () => {
    fakeService();
    renderPortal("/parent/attempts?client=younger");
    const nav = await screen.findByRole("navigation", { name: "Portal pages" });
    const toggle = within(nav).getByRole("button", { name: "Usage" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    const links = within(nav.querySelector("#usage-list") as HTMLElement).getAllByRole("link");
    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["Minutes", "/parent/usage/minutes"],
      ["Bytes", "/parent/usage/bytes"],
    ]);
    expect(localStorage.getItem(USAGE_KEY)).toBe("true");
    await userEvent.click(toggle);
    expect(localStorage.getItem(USAGE_KEY)).toBe("false");
  });

  it("keeps the settings or the preset in the address between Minutes and Bytes", async () => {
    const { calls, router } = await openUsage("/parent/usage/minutes?client=younger&by=client&range=today");
    const nav = screen.getByRole("navigation", { name: "Portal pages" });
    expect(within(nav).getByRole("button", { name: "Usage" })).toHaveAttribute("aria-expanded", "true");
    expect(within(nav).getByRole("link", { name: "Minutes" })).toHaveAttribute("aria-current", "page");
    await userEvent.click(within(nav).getByRole("link", { name: "Bytes" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/usage/bytes?client=younger&by=client&range=today"));
    expect(usageCalls(calls)).toContain("/parent/api/usage/bytes?client=younger&by=client&range=today");
    expect(await screen.findByRole("heading", { name: "Bytes" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Minutes" })).toHaveAttribute("href", "/parent/usage/minutes?client=younger&by=client&range=today");
  });

  it("opens Minutes from /parent/usage", async () => {
    fakeService();
    const { router } = renderPortal("/parent/usage");
    await waitFor(() => expect(shown(router)).toBe("/parent/usage/minutes"));
  });
});

describe("the filters", () => {
  it("say All with nothing chosen and write each choice to the address at once", async () => {
    const { calls, router } = await openUsage();
    const clients = screen.getByRole("button", { name: "Client groups All" });
    await userEvent.click(clients);
    await userEvent.click(screen.getByRole("option", { name: "younger" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/usage/minutes?client=younger&by=client&range=past-week"));
    expect(usageCalls(calls)).toContain("/parent/api/usage/minutes?client=younger&by=client&range=past-week");
    await userEvent.click(screen.getByRole("option", { name: "older" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/usage/minutes?client=younger&client=older&by=client&range=past-week"));
    await userEvent.keyboard("{Escape}");

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Group by" }), "none");
    await waitFor(() => expect(new URLSearchParams(router.state.location.search).get("by")).toBe("none"));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Date range" }), "previous-month");
    await waitFor(() => expect(new URLSearchParams(router.state.location.search).get("range")).toBe("previous-month"));
  });

  it("disable Site groups while a quota is chosen, and offer no Group by that needs site groups", async () => {
    await openUsage("/parent/usage/minutes?quota=youtube&by=client&range=past-week", (call) =>
      call.path === "/parent/api/usage/minutes" ? { body: withSettings({ quota: ["youtube"] }, { preset: "" }) } : undefined,
    );
    const sites = screen.getByRole("button", { name: "Site groups All" });
    expect(sites).toBeDisabled();
    expect(sites.getAttribute("title")).toContain("Usage by quota is not kept per site group.");
    expect(screen.getByRole("button", { name: "Quotas youtube" })).toBeEnabled();
    const groupBy = within(screen.getByRole("combobox", { name: "Group by" }));
    expect(groupBy.getAllByRole("option").map((option) => option.textContent)).toEqual(["Client group", "Quota", "None"]);
  });

  it("disable Quotas while grouping by site group", async () => {
    await openUsage("/parent/usage/minutes?by=site&range=past-week", (call) =>
      call.path === "/parent/api/usage/minutes" ? { body: withSettings({ by: "site" }, { preset: "" }) } : undefined,
    );
    expect(screen.getByRole("button", { name: "Quotas All" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Site groups All" })).toBeEnabled();
  });
});

describe("a custom date range", () => {
  it("opens From and To on the days the range covered, and redraws only for a range that can be drawn", async () => {
    const { router } = await openUsage();
    expect(screen.queryByRole("textbox", { name: "From" })).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Date range" }), "custom");
    await waitFor(() => expect(shown(router)).toBe("/parent/usage/minutes?by=client&range=custom&from=2026-11-06&to=2026-11-13"));
    expect(screen.getByRole("textbox", { name: "From" })).toHaveValue("2026-11-06");
    expect(screen.getByRole("textbox", { name: "To" })).toHaveValue("2026-11-13");
  });

  it("says To before From, or text that is not a date, under the box and leaves the graph alone", async () => {
    const custom = withSettings({ range: "custom", from: "2026-11-01", to: "2026-11-07" }, { preset: "" });
    const address = "/parent/usage/minutes?by=client&range=custom&from=2026-11-01&to=2026-11-07";
    const { router } = await openUsage(address, (call) => (call.path === "/parent/api/usage/minutes" ? { body: custom } : undefined));
    const to = screen.getByRole("textbox", { name: "To" });
    await userEvent.clear(to);
    await userEvent.type(to, "2026-10-30");
    expect(await screen.findByText("To is before From.")).toBeInTheDocument();
    await userEvent.clear(to);
    await userEvent.type(to, "2026-13-01");
    expect(screen.getByText("Not a date. Use yyyy-mm-dd, such as 2026-10-31.")).toBeInTheDocument();
    expect(shown(router)).toBe(address);
    await userEvent.clear(to);
    await userEvent.type(to, "2026-11-03");
    await waitFor(() => expect(shown(router)).toBe("/parent/usage/minutes?by=client&range=custom&from=2026-11-01&to=2026-11-03"));
  });
});

describe("presets", () => {
  it("shows the preset on show, puts a chosen one's name in the address, and is blank when none matches", async () => {
    const { calls, router } = await openUsage();
    const preset = screen.getByRole("combobox", { name: "Preset" });
    expect(preset).toHaveValue("Default");
    expect(within(preset).getAllByRole("option").map((option) => option.textContent)).toEqual(["Default", "School week"]);
    await userEvent.selectOptions(preset, "School week");
    await waitFor(() => expect(shown(router)).toBe("/parent/usage/minutes?preset=School%20week"));
    expect(usageCalls(calls)).toContain("/parent/api/usage/minutes?preset=School%20week");
  });

  it("is blank when no preset matches the settings on show", async () => {
    await openUsage(DEFAULT_ADDRESS, (call) => (call.path === "/parent/api/usage/minutes" ? { body: { ...USAGE, preset: "" } } : undefined));
    expect(screen.getByRole("combobox", { name: "Preset" })).toHaveValue("");
    const remove = screen.getByRole("button", { name: "Delete preset" });
    expect(remove).toBeDisabled();
    expect(remove).toHaveAttribute("title", "Choose a preset to delete it.");
  });

  it("saves the settings on show under a new name and then shows that preset", async () => {
    const { calls, router } = await openUsage(DEFAULT_ADDRESS, (call) =>
      call.path === "/parent/api/usage/presets" ? { body: { name: "Weekdays", message: "Saved preset Weekdays." } } : undefined,
    );
    await userEvent.click(screen.getByRole("button", { name: "Save preset" }));
    const dialog = screen.getByRole("dialog", { name: "Save preset" });
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Name" }), "Weekdays{Enter}");
    await waitFor(() => expect(shown(router)).toBe("/parent/usage/minutes?preset=Weekdays"));
    expect(await screen.findByText("Saved preset Weekdays.")).toBeInTheDocument();
    expect(calls.filter((call) => call.path === "/parent/api/usage/presets").map((call) => call.body)).toEqual([
      { name: "Weekdays", settings: USAGE.settings, replace: false },
    ]);
  });

  it("asks before replacing a preset, with Cancel as the default", async () => {
    const { calls } = await openUsage(DEFAULT_ADDRESS, (call) =>
      call.path === "/parent/api/usage/presets" ? { body: { name: "School week", message: "Replaced preset School week." } } : undefined,
    );
    await userEvent.click(screen.getByRole("button", { name: "Save preset" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "school week{Enter}");
    const ask = await screen.findByRole("alertdialog", { name: "Replace preset?" });
    expect(within(ask).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(calls.some((call) => call.path === "/parent/api/usage/presets")).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Save preset" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "School week{Enter}");
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Replace" }));
    expect(await screen.findByText("Replaced preset School week.")).toBeInTheDocument();
    expect(calls.find((call) => call.path === "/parent/api/usage/presets")?.body).toEqual({ name: "School week", settings: USAGE.settings, replace: true });
  });

  it("keeps the name dialog open with the reason when the service refuses the name", async () => {
    await openUsage(DEFAULT_ADDRESS, (call) =>
      call.path === "/parent/api/usage/presets" ? { status: 400, body: { error: "Give the preset a name." } } : undefined,
    );
    await userEvent.click(screen.getByRole("button", { name: "Save preset" }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "OK" }));
    expect(await within(screen.getByRole("dialog")).findByText("Give the preset a name.")).toBeInTheDocument();
  });

  it("cannot delete Default", async () => {
    await openUsage();
    const blocked = screen.getByRole("button", { name: "Delete preset" });
    expect(blocked).toBeDisabled();
    expect(blocked).toHaveAttribute("title", "Default can be replaced but not deleted.");
  });

  it("deletes the preset on show after asking, then shows its settings in the address", async () => {
    const school = withSettings({ client: ["younger"], range: "this-week" }, { preset: "School week" });
    const { calls, router } = await openUsage("/parent/usage/minutes?preset=School%20week", (call) => {
      if (call.path === "/parent/api/usage/presets/delete") return { body: { name: "School week", message: "Deleted preset School week." } };
      if (call.path === "/parent/api/usage/minutes") return { body: school };
      return undefined;
    });
    await userEvent.click(screen.getByRole("button", { name: "Delete preset" }));
    const ask = await screen.findByRole("alertdialog", { name: "Delete preset?" });
    expect(within(ask).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await userEvent.click(within(ask).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/usage/minutes?client=younger&by=client&range=this-week"));
    expect(await screen.findByText("Deleted preset School week.")).toBeInTheDocument();
    expect(calls.find((call) => call.path === "/parent/api/usage/presets/delete")?.body).toEqual({ name: "School week" });
  });
});

describe("the graph", () => {
  it("names each line with its total and reads out the point the keyboard or pointer is on", async () => {
    await openUsage();
    const legend = screen.getByRole("list", { name: "Legend" });
    expect(within(legend).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["younger1h 15m", "older0m"]);
    const younger = screen.getByRole("img", { name: "younger, 1h 15m" });
    younger.focus();
    expect(await screen.findByText("Tuesday 10 November 2026, younger, 1h 15m")).toBeInTheDocument();
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByText("Wednesday 11 November 2026, younger, 0m")).toBeInTheDocument();
    await userEvent.keyboard("{Home}");
    expect(screen.getByText("Friday 6 November 2026 21:30 to 24:00, younger, 0m")).toBeInTheDocument();
    younger.blur();

    const plot = document.querySelector(".chart-hit") as SVGRectElement;
    // At the fallback size, Tuesday's point is about 430px across and its 1h 15m is the top of the axis.
    fireEvent.pointerMove(plot, { clientX: 431, clientY: 16 });
    expect(screen.getByText("Tuesday 10 November 2026, younger, 1h 15m")).toBeInTheDocument();
    fireEvent.pointerMove(plot, { clientX: 431, clientY: 200 });
    expect(screen.queryByText(/Tuesday 10 November 2026, /)).not.toBeInTheDocument();
  });

  it("shows the range and its timezone, and every note, in the status bar", async () => {
    await openUsage(DEFAULT_ADDRESS, (call) =>
      call.path === "/parent/api/usage/minutes" ? { body: { ...USAGE, notes: ["Left out client group middle, which the policy no longer has."] } } : undefined,
    );
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Friday 6 November 2026 21:30 to Friday 13 November 2026 21:30. Times are Australia/Sydney.");
    expect(status).toHaveTextContent("Left out client group middle, which the policy no longer has.");
  });

  it("says when a range has no usage", async () => {
    const quiet = { ...USAGE, graph: { ...USAGE.graph, lines: [{ name: "younger", values: USAGE.graph.lines[1].values }] } };
    await openUsage(DEFAULT_ADDRESS, (call) => (call.path === "/parent/api/usage/minutes" ? { body: quiet } : undefined));
    expect(screen.getByText("No usage in this range.")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Legend" })).not.toBeInTheDocument();
  });

  it("labels the Bytes page's axis and totals in the units the policy file uses", async () => {
    const gigabytes = { ...USAGE, unit: "bytes", graph: { ...USAGE.graph, lines: [{ name: "older", values: [0, 0, 0, 0, 1.4 * 1024 ** 3, 0, 0, 0] }] } };
    await openUsage("/parent/usage/bytes", (call) => (call.path === "/parent/api/usage/bytes" ? { body: gigabytes } : undefined));
    expect(within(screen.getByRole("list", { name: "Legend" })).getByText("1.4 GB")).toBeInTheDocument();
    expect(screen.getByText("0.2 GB")).toBeInTheDocument();
  });
});

describe("usage values", () => {
  it("read as durations and as the policy file's byte units", () => {
    expect([0, 59, 180, 3600, 22800, 4530].map(formatDuration)).toEqual(["0m", "59s", "3m", "1h", "6h 20m", "1h 15m 30s"]);
    expect([1, 900, 1536, 512 * 1024 ** 2, 1.4 * 1024 ** 3, 3 * 1024 ** 4].map(formatBytes)).toEqual(["1 byte", "900 bytes", "1.5 KB", "512 MB", "1.4 GB", "3 TB"]);
  });

  it("have axes that start at zero and reach past the largest value", () => {
    expect(durationAxis(0).ticks.map((tick) => tick.label)).toEqual(["0m", "10m", "20m", "30m", "40m", "50m", "1h"]);
    expect(durationAxis(4 * 3600).ticks.map((tick) => tick.label)).toEqual(["0m", "1h", "2h", "3h", "4h"]);
    const bytes = bytesAxis(700 * 1024 ** 2);
    expect(bytes.max).toBeGreaterThanOrEqual(700 * 1024 ** 2);
    expect(bytes.ticks[0].label).toBe("0");
    expect(bytes.ticks.slice(1).every((tick) => tick.label.endsWith(" MB"))).toBe(true);
  });

  it("put the settings in the address in a fixed order, with dates only for Custom", () => {
    const settings: Settings = { client: ["younger", "the twins"], site: [], quota: ["youtube"], by: "quota", range: "past-week", from: "2026-11-01", to: "2026-11-02" };
    expect(settingsQuery(settings)).toBe("?client=younger&client=the%20twins&quota=youtube&by=quota&range=past-week");
    expect(settingsQuery({ ...settings, range: "custom" })).toBe("?client=younger&client=the%20twins&quota=youtube&by=quota&range=custom&from=2026-11-01&to=2026-11-02");
  });
});
