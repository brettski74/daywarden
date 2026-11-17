import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { USAGE_KEY } from "./sidebar";
import { REQUESTS, USAGE, fakeService, renderPortal, shown, type Call } from "./test/portal";
import { bytesAxis, durationAxis, formatBytes, formatDuration, settingsQuery, withFetch, withHost, withLine, type Settings } from "./usage";

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
  it("is a group that expands into Minutes, Bytes, and Requests, and remembers whether it is expanded", async () => {
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
      ["Requests", "/parent/usage/requests"],
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
    // The address changes before the page has drawn the new range, so wait for the boxes as well.
    await waitFor(() => expect(screen.getByRole("textbox", { name: "From" })).toHaveValue("2026-11-06"));
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

const TOP_HOSTS = [
  { host: "rr3---sn-ab5l6nrz.googlevideo.com", value: 3600, down: 1.2 * 1024 ** 3, up: 40 * 1024 ** 2 },
  { host: "www.youtube.com", value: 900, down: 300 * 1024 ** 2, up: 2 * 1024 ** 2 },
];

/** Answer as the service does: the settings asked for, and the top hosts on the line the address names. */
function drillEcho(kept: string | null = null) {
  return (call: Call) => {
    if (call.path === "/parent/api/usage/requests") {
      const asked = new URLSearchParams(call.search);
      const host = asked.get("host") || "";
      return {
        body: {
          ...REQUESTS,
          host,
          exact: asked.get("exact") === "1",
          sort: asked.get("sort") || "start",
          dir: asked.get("dir") === "asc" ? "asc" : "desc",
          page: Number(asked.get("page") || "1"),
          fetch: asked.get("fetch") || "all",
          hide_hops: Boolean(asked.get("fetch")) && asked.get("hops") !== "show",
          rows: host && host !== "www.youtube.com" && !host.includes("youtube") ? [] : REQUESTS.rows,
          total: host && host !== "www.youtube.com" && !host.includes("youtube") ? 0 : 1,
          status: host && host !== "www.youtube.com" && !host.includes("youtube") ? "No requests in this range." : REQUESTS.status,
        },
      };
    }
    if (!/^\/parent\/api\/usage\/(minutes|bytes)$/.test(call.path)) return undefined;
    const asked = new URLSearchParams(call.search);
    const answer = echo(call) ?? { body: { ...USAGE, unit: call.path.endsWith("bytes") ? "bytes" : "minutes" } };
    const line = asked.get("line");
    const bytes = call.path.endsWith("bytes");
    const bars = TOP_HOSTS.map(({ host, value, down, up }) => (bytes ? { host, value: down + up, down, up } : { host, value }));
    return { body: { ...answer.body, hosts: line ? { line, kept, bars } : null } };
  };
}

describe("the top hosts", () => {
  it("open beneath the graph when a line is double-clicked, with the line in the address", async () => {
    const { router } = await openUsage(DEFAULT_ADDRESS, drillEcho());
    expect(screen.queryByRole("region", { name: /top hosts/ })).not.toBeInTheDocument();
    const plot = document.querySelector(".chart-hit") as SVGRectElement;
    fireEvent.doubleClick(plot, { clientX: 431, clientY: 16 });
    await waitFor(() => expect(shown(router)).toBe(`${DEFAULT_ADDRESS}&line=younger`));
    const panel = await screen.findByRole("region", { name: "younger, Past week: top hosts" });
    expect(within(panel).getByRole("heading", { name: "younger, Past week: top hosts" })).toBeInTheDocument();
    const bars = within(panel).getAllByRole("listitem").map((item) => item.getAttribute("aria-label"));
    expect(bars).toEqual(["rr3---sn-ab5l6nrz.googlevideo.com, 1h", "www.youtube.com, 15m"]);
    expect(within(panel).queryByRole("list", { name: "Key" })).not.toBeInTheDocument();
  });

  it("does not open when the double-click is not on a line", async () => {
    const { router } = await openUsage(DEFAULT_ADDRESS, drillEcho());
    fireEvent.doubleClick(document.querySelector(".chart-hit") as SVGRectElement, { clientX: 431, clientY: 200 });
    expect(shown(router)).toBe(DEFAULT_ADDRESS);
  });

  it("open from the keyboard with Enter on a legend entry or on a focused line", async () => {
    const { router } = await openUsage(DEFAULT_ADDRESS, drillEcho());
    const entry = within(screen.getByRole("list", { name: "Legend" })).getByRole("button", { name: "older, 0m" });
    expect(entry).toHaveAttribute("title", "Show the top hosts for older");
    entry.focus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(shown(router)).toBe(`${DEFAULT_ADDRESS}&line=older`));
    expect(await screen.findByRole("region", { name: "older, Past week: top hosts" })).toBeInTheDocument();

    screen.getByRole("img", { name: "younger, 1h 15m" }).focus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(shown(router)).toBe(`${DEFAULT_ADDRESS}&line=younger`));
    expect(await screen.findByRole("region", { name: "younger, Past week: top hosts" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /^older/ })).not.toBeInTheDocument();
  });

  it("split each bar into downloaded and uploaded on the Bytes page, with a key", async () => {
    await openUsage("/parent/usage/bytes?by=client&range=past-week&line=younger", drillEcho());
    const panel = await screen.findByRole("region", { name: "younger, Past week: top hosts" });
    expect(within(within(panel).getByRole("list", { name: "Key" })).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["Downloaded", "Uploaded"]);
    expect(within(panel).getByText("1.2 GB down, 40 MB up")).toBeInTheDocument();
    const first = within(panel).getAllByRole("listitem", { name: /googlevideo/ })[0];
    expect(first.querySelectorAll(".chart-bar")).toHaveLength(2);
  });

  it("close with the close button, which takes the line out of the address", async () => {
    const { router } = await openUsage(`${DEFAULT_ADDRESS}&line=younger`, drillEcho());
    const panel = await screen.findByRole("region", { name: "younger, Past week: top hosts" });
    await userEvent.click(within(panel).getByRole("button", { name: "Close top hosts" }));
    await waitFor(() => expect(shown(router)).toBe(DEFAULT_ADDRESS));
    await waitFor(() => expect(screen.queryByRole("region", { name: /top hosts/ })).not.toBeInTheDocument());
  });

  it("stay open when a filter or the range changes, and close when Group by changes the lines", async () => {
    const { router } = await openUsage(`${DEFAULT_ADDRESS}&line=younger`, drillEcho());
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Date range" }), "previous-month");
    await waitFor(() => expect(shown(router)).toBe("/parent/usage/minutes?by=client&range=previous-month&line=younger"));
    expect(await screen.findByRole("region", { name: "younger, Previous month: top hosts" })).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Group by" }), "none");
    await waitFor(() => expect(shown(router)).toBe("/parent/usage/minutes?by=none&range=previous-month"));
  });

  it("say from when hosts are kept, and that there are none", async () => {
    const kept = "Hosts are kept for 30 days, from Wednesday 14 October 2026.";
    await openUsage("/parent/usage/minutes?by=client&range=past-month&line=younger", (call) => {
      const answer = drillEcho(kept)(call);
      if (!answer || !/^\/parent\/api\/usage\/(minutes|bytes)$/.test(call.path)) return answer;
      const body = answer.body as typeof USAGE;
      return { body: { ...body, hosts: body.hosts ? { ...body.hosts, bars: [] } : null } };
    });
    const panel = await screen.findByRole("region", { name: "younger, Past month: top hosts" });
    expect(within(panel).getByText(kept)).toBeInTheDocument();
    expect(within(panel).getByText("No hosts in this range.")).toBeInTheDocument();
  });

  it("name a custom range by its days in the heading, and keep the line when a preset is saved", async () => {
    const address = "/parent/usage/minutes?by=client&range=custom&from=2026-11-01&to=2026-11-07&line=younger";
    const { router } = await openUsage(address, (call) =>
      call.path === "/parent/api/usage/presets" ? { body: { name: "Week one", message: "Saved preset Week one." } } : drillEcho()(call),
    );
    expect(await screen.findByRole("region", { name: "younger, 2026-11-01 to 2026-11-07: top hosts" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save preset" }));
    await userEvent.type(within(screen.getByRole("dialog")).getByRole("textbox", { name: "Name" }), "Week one{Enter}");
    await waitFor(() => expect(shown(router)).toBe("/parent/usage/minutes?preset=Week%20one&line=younger"));
  });
});

describe("the request table under a host", () => {
  it("opens beneath the bar chart when a host is double-clicked, with the host in the address", async () => {
    const { calls, router } = await openUsage(`${DEFAULT_ADDRESS}&line=younger`, drillEcho());
    const panel = await screen.findByRole("region", { name: "younger, Past week: top hosts" });
    const bar = within(panel).getByRole("listitem", { name: /www\.youtube\.com/ });
    fireEvent.doubleClick(bar);
    await waitFor(() => expect(shown(router)).toBe(`${DEFAULT_ADDRESS}&line=younger&host=www.youtube.com&exact=1`));
    const requests = await screen.findByRole("region", { name: "younger, www.youtube.com, Past week: requests" });
    expect(within(requests).getByRole("columnheader", { name: /Start/ })).toBeInTheDocument();
    expect(within(requests).getByText("www.youtube.com")).toBeInTheDocument();
    await waitFor(() => expect(usageCalls(calls).some((path) => path.includes("/parent/api/usage/requests?") && path.includes("host=www.youtube.com"))).toBe(true));
  });

  it("opens from Enter on a focused host bar", async () => {
    const { router } = await openUsage(`${DEFAULT_ADDRESS}&line=younger`, drillEcho());
    const panel = await screen.findByRole("region", { name: "younger, Past week: top hosts" });
    const bar = within(panel).getByRole("listitem", { name: /www\.youtube\.com/ });
    bar.focus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(shown(router)).toBe(`${DEFAULT_ADDRESS}&line=younger&host=www.youtube.com&exact=1`));
    expect(await screen.findByRole("region", { name: "younger, www.youtube.com, Past week: requests" })).toBeInTheDocument();
  });

  it("closes when the close button is pressed, and when a filter changes", async () => {
    const { router } = await openUsage(`${DEFAULT_ADDRESS}&line=younger&host=www.youtube.com&exact=1`, drillEcho());
    expect(await screen.findByRole("region", { name: "younger, www.youtube.com, Past week: requests" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Close requests" }));
    await waitFor(() => expect(shown(router)).toBe(`${DEFAULT_ADDRESS}&line=younger`));
    const bar = within(screen.getByRole("region", { name: /top hosts/ })).getByRole("listitem", { name: /www\.youtube\.com/ });
    bar.focus();
    await userEvent.keyboard("{Enter}");
    await screen.findByRole("region", { name: "younger, www.youtube.com, Past week: requests" });
    await userEvent.selectOptions(screen.getByLabelText("Date range"), "previous-month");
    await waitFor(() => expect(shown(router)).toBe("/parent/usage/minutes?by=client&range=previous-month&line=younger"));
  });
});

describe("the Fetch filter", () => {
  /** Answer the Requests page with the Fetch level and checkbox its address names, as the service does. */
  function fetchEcho(call: Call) {
    if (call.path !== "/parent/api/usage/requests") return undefined;
    const asked = new URLSearchParams(call.search);
    const fetch = asked.get("fetch") || "all";
    return { body: { ...REQUESTS, host: asked.get("host") || "", outcome: asked.getAll("outcome"), fetch, hide_hops: fetch !== "all" && asked.get("hops") !== "show" } };
  }

  it("shows the five Fetch Metadata columns after Method", async () => {
    fakeService(fetchEcho);
    renderPortal("/parent/usage/requests?range=past-week");
    await screen.findByRole("heading", { name: "Requests" });
    const headings = screen.getAllByRole("columnheader").map((cell) => cell.textContent?.trim());
    const method = headings.indexOf("Method");
    expect(headings.slice(method + 1, method + 6)).toEqual(["Dest", "Mode", "Site", "User", "Purpose"]);
    const cells = screen.getAllByRole("cell").map((cell) => cell.textContent);
    expect(cells).toEqual(expect.arrayContaining(["document", "navigate", "none", "?1"]));
  });

  it("chooses a level on the Requests page, checks Hide redirect hops when first chosen, and keeps the other filters", async () => {
    fakeService(fetchEcho);
    const { router } = renderPortal("/parent/usage/requests?range=past-week&host=example&page=3");
    await screen.findByRole("heading", { name: "Requests" });
    expect(screen.queryByLabelText("Hide redirect hops")).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Fetch"), "documents");
    await waitFor(() => expect(shown(router)).toBe("/parent/usage/requests?range=past-week&host=example&fetch=documents"));
    expect(await screen.findByLabelText("Hide redirect hops")).toBeChecked();
    await userEvent.click(screen.getByLabelText("Hide redirect hops"));
    await waitFor(() => expect(shown(router)).toBe("/parent/usage/requests?range=past-week&host=example&fetch=documents&hops=show"));
    await waitFor(() => expect(screen.getByLabelText("Hide redirect hops")).not.toBeChecked());
    // Moving between the documents levels keeps the checkbox as it is.
    await userEvent.selectOptions(screen.getByLabelText("Fetch"), "user");
    await waitFor(() => expect(shown(router)).toBe("/parent/usage/requests?range=past-week&host=example&fetch=user&hops=show"));
    await userEvent.selectOptions(screen.getByLabelText("Fetch"), "all");
    await waitFor(() => expect(shown(router)).toBe("/parent/usage/requests?range=past-week&host=example"));
    await waitFor(() => expect(screen.queryByLabelText("Hide redirect hops")).not.toBeInTheDocument());
  });

  it("keeps its level when another filter changes on the Requests page, and leaves it out of a preset", async () => {
    fakeService(fetchEcho);
    const { router } = renderPortal("/parent/usage/requests?range=past-week&fetch=user");
    await screen.findByRole("heading", { name: "Requests" });
    await userEvent.selectOptions(screen.getByLabelText("Date range"), "previous-month");
    await waitFor(() => expect(shown(router)).toBe("/parent/usage/requests?range=previous-month&fetch=user"));
    await userEvent.selectOptions(screen.getByLabelText("Preset"), "School week");
    await waitFor(() => expect(shown(router)).toBe("/parent/usage/requests?preset=School%20week"));
  });

  it("narrows the open drill-down table without closing it", async () => {
    const { calls, router } = await openUsage(`${DEFAULT_ADDRESS}&line=younger&host=www.youtube.com&exact=1&page=2`, drillEcho());
    const requests = await screen.findByRole("region", { name: "younger, www.youtube.com, Past week: requests" });
    await userEvent.selectOptions(within(requests).getByLabelText("Fetch"), "documents");
    await waitFor(() => expect(shown(router)).toBe(`${DEFAULT_ADDRESS}&line=younger&host=www.youtube.com&exact=1&fetch=documents`));
    expect(screen.getByRole("region", { name: "younger, www.youtube.com, Past week: requests" })).toBeInTheDocument();
    await waitFor(() => expect(usageCalls(calls).some((path) => path.includes("/parent/api/usage/requests?") && path.includes("fetch=documents"))).toBe(true));
    expect(await within(requests).findByLabelText("Hide redirect hops")).toBeChecked();
    await userEvent.click(within(requests).getByLabelText("Hide redirect hops"));
    await waitFor(() => expect(shown(router)).toBe(`${DEFAULT_ADDRESS}&line=younger&host=www.youtube.com&exact=1&fetch=documents&hops=show`));
    expect(screen.getByRole("region", { name: "younger, www.youtube.com, Past week: requests" })).toBeInTheDocument();
  });

  it("is dropped from the address when the drill-down closes, and kept when another host replaces it", () => {
    const drilled = "?by=client&range=past-week&line=younger&host=a.example&exact=1&fetch=user&hops=show";
    expect(withHost(drilled, "b.example")).toBe("?by=client&range=past-week&line=younger&fetch=user&hops=show&host=b.example&exact=1");
    expect(withHost(drilled, null)).toBe("?by=client&range=past-week&line=younger");
    expect(withLine(drilled, "older")).toBe("?by=client&range=past-week&line=older");
    expect(withFetch("?range=past-week&page=4", "documents", true)).toBe("?range=past-week&fetch=documents");
    expect(withFetch("?range=past-week&fetch=user&hops=show", "all", false)).toBe("?range=past-week");
  });
});

describe("the Requests page", () => {
  it("opens from the sidebar beneath Bytes, with Host and Outcome filters", async () => {
    fakeService();
    const { router } = renderPortal("/parent/usage/requests?range=past-week");
    const heading = await screen.findByRole("heading", { name: "Requests" });
    expect(heading).toBeInTheDocument();
    expect(screen.getByLabelText("Host")).toBeInTheDocument();
    expect(screen.getByLabelText("Outcome")).toBeInTheDocument();
    expect(screen.queryByLabelText("Group by")).not.toBeInTheDocument();
    expect(screen.getByText("Requests 1 to 1 of 1.")).toBeInTheDocument();
    expect(shown(router)).toBe("/parent/usage/requests?range=past-week");
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
