import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { normalizeClock, sameFields } from "./policy";
import { fakeService, renderPortal, shown, type Call, type Reply } from "./test/portal";

const SITES = {
  version: "v1",
  file: "/etc/daywarden/policy.yaml",
  items: [
    { name: "school", file: null, priority: "10", patterns: ["classroom.google.com", "docs.google.com"] },
    { name: "games", file: "extra.yaml", priority: "20", patterns: ["*.minecraft.net"] },
  ],
};
const WINDOWS = {
  version: "v1",
  file: "/etc/daywarden/policy.yaml",
  items: [
    {
      name: "bedtime",
      file: null,
      periods: [{ origin: 0, start: "21:00", end: "07:00", extra: "1", weekdays: [4, 5, 6] }],
    },
  ],
};
const QUOTAS = {
  version: "v1",
  file: "/etc/daywarden/policy.yaml",
  rule_sets: ["gate", "meter"],
  defaults: { time_grace: "5m", volume_grace: "1M" },
  items: [{ name: "entertainment", file: null, time: "45m", bytes: "", time_grace: "", volume_grace: "", ruleset: "meter" }],
};
const HOUSEHOLD = {
  version: "v1",
  file: "/etc/daywarden/policy.yaml",
  fields: { entry: "gate", timezone: "America/Toronto", bucket_length: "", time_grace: "", volume_grace: "", host_retention: "", request_retention: "" },
  proxy: { localhost: true, plain_host_names: true, policy_server: true, local_subnets: true, local_domains: true, extra: [] },
  rule_sets: ["gate", "meter"],
  defaults: { timezone: "UTC", bucket_length: "5m", time_grace: "5m", volume_grace: "1M", host_retention: "30d", request_retention: "30d" },
};
const DONE = { message: "Saved the site groups.", warnings: [] };

async function open(page: string, data: unknown, handler?: (call: Call) => Reply | undefined) {
  const calls = fakeService((call) => {
    const answered = handler?.(call);
    if (answered) return answered;
    return call.path === `/parent/api/policy/${page}` && call.method === "GET" ? { body: data } : undefined;
  });
  const view = renderPortal(`/parent/policy/${page}`);
  await screen.findByRole("heading", { level: 1 });
  return { calls, router: view.router };
}

const save = () => screen.getByRole("button", { name: "Save" });
const item = (name: string) => screen.getByRole("region", { name });
const posts = (calls: Call[]) => calls.filter((call) => call.method === "POST" && call.path.startsWith("/parent/api/policy/"));

describe("the clock and field rules", () => {
  it("rewrites a readable clock as HH:MM and leaves anything else as typed", () => {
    expect(normalizeClock("7:05")).toBe("07:05");
    expect(normalizeClock("0705")).toBe("07:05");
    expect(normalizeClock("07:05")).toBe("07:05");
    for (const text of ["25:00", "705", "7pm", "12:60", ""]) expect(normalizeClock(text)).toBe(text);
  });

  it("does not count a period's origin, or the clock's form, as a change", () => {
    const period = { origin: 0, start: "07:05", end: "08:00", extra: "0", weekdays: [1] };
    expect(sameFields({ periods: [period] }, { periods: [{ ...period, origin: 3, start: "7:05" }] })).toBe(true);
    expect(sameFields({ periods: [period] }, { periods: [{ ...period, weekdays: [1, 2] }] })).toBe(false);
  });
});

describe("the site groups page", () => {
  it("lists the groups as the files write them, names a file other than policy.yaml, and ends with the read-only default", async () => {
    await open("site-groups", SITES);
    expect(within(item("school")).getByRole("textbox", { name: "Pattern 2" })).toHaveValue("docs.google.com");
    expect(within(item("games")).getByText("extra.yaml")).toBeInTheDocument();
    expect(within(item("school")).queryByText("extra.yaml")).toBeNull();
    const regions = screen.getAllByRole("region");
    const last = regions[regions.length - 1];
    expect(last).toHaveAccessibleName("default");
    expect(within(last).getByText(/holds every site that no other group holds/)).toBeInTheDocument();
    expect(within(last).queryByRole("button", { name: "Delete" })).toBeNull();
    expect(within(last).getByRole("textbox", { name: "Name" })).toHaveAttribute("readonly");
    expect(save()).toBeDisabled();
  });

  it("leaves Save disabled after a field is changed and changed back", async () => {
    const user = userEvent.setup();
    const { calls } = await open("site-groups", SITES);
    const priority = within(item("school")).getByRole("textbox", { name: "Priority" });
    await user.type(priority, "5");
    expect(priority).toHaveAttribute("data-changed");
    expect(save()).toBeEnabled();
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    await user.type(priority, "{Backspace}");
    expect(priority).not.toHaveAttribute("data-changed");
    expect(save()).toBeDisabled();
    expect(screen.queryByText("Unsaved changes")).toBeNull();
    expect(posts(calls)).toEqual([]);
  });

  it("sends one request for every change on the page: changed items, new items, and deletes", async () => {
    const user = userEvent.setup();
    const { calls } = await open("site-groups", SITES, (call) => (call.method === "POST" ? { body: DONE } : undefined));
    await user.click(within(item("school")).getByRole("button", { name: "Add pattern" }));
    await user.type(within(item("school")).getByRole("textbox", { name: "Pattern 3" }), "*.gstatic.com");
    await user.click(within(item("games")).getByRole("button", { name: "Delete" }));
    await user.keyboard("{Alt>}n{/Alt}");
    const fresh = screen.getByRole("region", { name: "New site group 3" });
    const box = within(fresh).getByRole("textbox", { name: "Name" });
    expect(box).toHaveFocus();
    await user.type(box, "hobby");
    await user.type(within(fresh).getByRole("textbox", { name: "Priority" }), "40");
    await user.click(within(fresh).getByRole("button", { name: "Add pattern" }));
    await user.type(within(fresh).getByRole("textbox", { name: "Pattern 1" }), "*.lego.com");
    await user.click(save());
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(posts(calls)[0].body).toEqual({
      version: "v1",
      items: [
        { name: "school", new: false, fields: { priority: "10", patterns: ["classroom.google.com", "docs.google.com", "*.gstatic.com"] } },
        { name: "hobby", new: true, fields: { priority: "40", patterns: ["*.lego.com"] } },
      ],
      deleted: ["games"],
    });
    expect(await screen.findByText("Saved the site groups.")).toBeInTheDocument();
  });

  it("marks an item to be deleted, and Undo takes the mark away", async () => {
    const user = userEvent.setup();
    await open("site-groups", SITES);
    await user.click(within(item("games")).getByRole("button", { name: "Delete" }));
    expect(item("games")).toHaveAttribute("data-marked");
    expect(save()).toBeEnabled();
    await user.click(within(item("games")).getByRole("button", { name: "Undo" }));
    expect(item("games")).not.toHaveAttribute("data-marked");
    expect(save()).toBeDisabled();
  });

  it("lets a new item's name be edited until it is saved, then shows it read-only", async () => {
    const user = userEvent.setup();
    const saved = { ...SITES, version: "v2", items: [...SITES.items, { name: "hobby", file: null, priority: "40", patterns: [] }] };
    let version = "v1";
    await open("site-groups", SITES, (call) => {
      if (call.method === "POST") {
        version = "v2";
        return { body: DONE };
      }
      return call.path.endsWith("/site-groups") ? { body: version === "v1" ? SITES : saved } : undefined;
    });
    await user.click(screen.getByRole("button", { name: "Add" }));
    const fresh = screen.getByRole("region", { name: "New site group 3" });
    const box = within(fresh).getByRole("textbox", { name: "Name" });
    expect(box).not.toHaveAttribute("readonly");
    await user.type(box, "hobby");
    await user.type(within(fresh).getByRole("textbox", { name: "Priority" }), "40");
    await user.click(save());
    await waitFor(() => expect(within(item("hobby")).getByRole("textbox", { name: "Name" })).toHaveAttribute("readonly"));
    expect(save()).toBeDisabled();
  });

  it("holds Save for a nameless item and a blank pattern, saying why", async () => {
    const user = userEvent.setup();
    const { calls } = await open("site-groups", SITES);
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(save()).toBeDisabled();
    expect(save()).toHaveAttribute("title", "Give the site group a name.");
    expect(posts(calls)).toEqual([]);
  });

  it("saves with Ctrl+S and lists a refusal's reasons in the status bar", async () => {
    const user = userEvent.setup();
    const { calls } = await open("site-groups", SITES, (call) =>
      call.method === "POST"
        ? { status: 400, body: { error: "This save would leave the policy unable to load, so nothing was saved.", errors: ["site groups 'school' and 'games' both have priority 20"] } }
        : undefined,
    );
    await user.type(within(item("school")).getByRole("textbox", { name: "Priority" }), "0");
    await user.keyboard("{Control>}s{/Control}");
    expect(await screen.findByText("site groups 'school' and 'games' both have priority 20")).toBeInTheDocument();
    expect(posts(calls)).toHaveLength(1);
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
  });

  it("asks before leaving with unsaved changes, with Stay as the default", async () => {
    const user = userEvent.setup();
    const { router } = await open("site-groups", SITES);
    await user.type(within(item("school")).getByRole("textbox", { name: "Priority" }), "5");
    await user.click(screen.getByRole("link", { name: "Quotas" }));
    const stay = await screen.findByRole("button", { name: "Stay" });
    expect(stay).toHaveFocus();
    await user.click(stay);
    expect(shown(router)).toBe("/parent/policy/site-groups");
  });

  it("goes to sign-in and comes back to the same page without a session", async () => {
    const calls = fakeService(() => ({ status: 401, body: {} }));
    const view = renderPortal("/parent/policy/site-groups");
    await waitFor(() => expect(shown(view.router)).toBe("/parent/login?next=%2Fparent%2Fpolicy%2Fsite-groups"));
    // An admin page asks for nothing of its own until the session says the parent is an admin.
    expect(calls.some((call) => call.path === "/parent/api/policy/site-groups")).toBe(false);
  });
});

describe("Rename on a policy page", () => {
  const renameButton = (name: string) => within(item(name)).getByRole("button", { name: "Rename" });
  const renames = (calls: Call[]) => calls.filter((call) => call.method === "POST" && call.path.endsWith("/rename"));

  it("is on each saved item, is disabled with its reason while the page has unsaved changes, and not on the default or a new item", async () => {
    const user = userEvent.setup();
    await open("site-groups", SITES);
    expect(renameButton("school")).toBeEnabled();
    expect(within(screen.getByRole("region", { name: "default" })).queryByRole("button", { name: "Rename" })).toBeNull();
    await user.keyboard("{Alt>}n{/Alt}");
    const fresh = screen.getByRole("region", { name: "New site group 3" });
    expect(within(fresh).queryByRole("button", { name: "Rename" })).toBeNull();
    expect(renameButton("school")).toBeDisabled();
    expect(renameButton("school")).toHaveAttribute("title", expect.stringMatching(/Save or undo the changes.*not part of the next save/));
  });

  it("renames at once from a dialog that starts with the old name, sends nothing with the next save, and shows the item under its new name", async () => {
    const user = userEvent.setup();
    let renamed = false;
    const after = { ...SITES, version: "v2", items: [{ ...SITES.items[0], name: "classes" }, SITES.items[1]] };
    const { calls } = await open("site-groups", SITES, (call) => {
      if (call.method === "POST") {
        renamed = true;
        return { body: { message: "Renamed the site group school to classes.", warnings: [], name: "classes" } };
      }
      return renamed && call.path === "/parent/api/policy/site-groups" ? { body: after } : undefined;
    });
    await user.click(renameButton("school"));
    const box = screen.getByRole("textbox", { name: "New name" });
    expect(box).toHaveValue("school");
    await user.clear(box);
    await user.type(box, "classes{Enter}");
    expect(await screen.findByRole("region", { name: "classes" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "school" })).toBeNull();
    expect(renames(calls)).toHaveLength(1);
    expect(renames(calls)[0]).toMatchObject({ path: "/parent/api/policy/site-groups/rename", body: { version: "v1", name: "school", to: "classes" } });
    expect(screen.getByText("Renamed the site group school to classes.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(save()).toBeDisabled();
  });

  it("keeps the dialog open with the reason when the name is refused, and Escape cancels without a request", async () => {
    const user = userEvent.setup();
    const { calls } = await open("site-groups", SITES, (call) =>
      call.method === "POST" ? { status: 400, body: { error: "A site group named games already exists, in extra.yaml." } } : undefined,
    );
    await user.click(renameButton("school"));
    await user.clear(screen.getByRole("textbox", { name: "New name" }));
    await user.type(screen.getByRole("textbox", { name: "New name" }), "games{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("A site group named games already exists");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(renames(calls)).toHaveLength(1);
  });

  it("closes the dialog and gives the reason in the status bar when a step failed and everything was put back", async () => {
    const user = userEvent.setup();
    await open("quotas", QUOTAS, (call) =>
      call.method === "POST" ? { status: 500, body: { error: "The stored history could not be moved, so nothing was renamed: database is locked" } } : undefined,
    );
    await user.click(renameButton("entertainment"));
    await user.clear(screen.getByRole("textbox", { name: "New name" }));
    await user.type(screen.getByRole("textbox", { name: "New name" }), "fun{Enter}");
    expect(await screen.findByText(/nothing was renamed: database is locked/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("region", { name: "entertainment" })).toBeInTheDocument();
  });
});

describe("the client groups page", () => {
  it("adds and removes addresses and says that default holds every address no other group holds", async () => {
    const user = userEvent.setup();
    const { calls } = await open(
      "client-groups",
      { version: "v1", file: "p", items: [{ name: "younger", file: null, addresses: ["192.0.2.40"] }] },
      (call) => (call.method === "POST" ? { body: DONE } : undefined),
    );
    expect(screen.getByText(/holds every address that no other group holds/)).toBeInTheDocument();
    await user.click(within(item("younger")).getByRole("button", { name: "Add address" }));
    await user.type(within(item("younger")).getByRole("textbox", { name: "Address 2" }), "192.0.2.41");
    await user.click(within(item("younger")).getByRole("button", { name: "Remove address 1" }));
    await user.click(save());
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(posts(calls)[0].body).toMatchObject({ items: [{ name: "younger", new: false, fields: { addresses: ["192.0.2.41"] } }] });
  });
});

describe("the time windows page", () => {
  it("shows the clocks, extra days, and weekday toggles of each period", async () => {
    await open("time-windows", WINDOWS);
    const period = within(item("bedtime")).getByRole("group", { name: "Period 1" });
    expect(within(period).getByRole("textbox", { name: "Start" })).toHaveValue("21:00");
    expect(within(period).getByRole("textbox", { name: "Extra Days" })).toHaveValue("1");
    const pressed = within(period).getAllByRole("button", { pressed: true }).map((button) => button.getAttribute("aria-label"));
    expect(pressed).toEqual(["Friday", "Saturday", "Sunday"]);
  });

  it("selects a clock's text on focus and rewrites it as HH:MM on blur, leaving text that is not a clock as typed", async () => {
    const user = userEvent.setup();
    await open("time-windows", WINDOWS);
    const start = within(item("bedtime")).getByRole("textbox", { name: "Start" }) as HTMLInputElement;
    await user.click(start);
    expect(start.selectionStart).toBe(0);
    expect(start.selectionEnd).toBe(5);
    await user.keyboard("7:05");
    await user.tab();
    expect(start).toHaveValue("07:05");
    await user.clear(start);
    await user.type(start, "25:00");
    await user.tab();
    expect(start).toHaveValue("25:00");
    await user.clear(start);
    await user.type(start, "2100");
    await user.tab();
    expect(start).toHaveValue("21:00");
    expect(save()).toBeDisabled();
  });

  it("sends the period as typed, with its extra days and the weekdays that are on, and refuses a bad extra days box", async () => {
    const user = userEvent.setup();
    const { calls } = await open("time-windows", WINDOWS, (call) => (call.method === "POST" ? { body: DONE } : undefined));
    const bedtime = item("bedtime");
    await user.click(within(bedtime).getByRole("button", { name: "Add period" }));
    const period = within(bedtime).getByRole("group", { name: "Period 2" });
    await user.type(within(period).getByRole("textbox", { name: "Start" }), "1200");
    await user.type(within(period).getByRole("textbox", { name: "End" }), "21:00");
    await user.clear(within(period).getByRole("textbox", { name: "Extra Days" }));
    await user.type(within(period).getByRole("textbox", { name: "Extra Days" }), "x");
    expect(save()).toBeDisabled();
    expect(save()).toHaveAttribute("title", "Extra days is a whole number, 0 or more.");
    await user.clear(within(period).getByRole("textbox", { name: "Extra Days" }));
    await user.type(within(period).getByRole("textbox", { name: "Extra Days" }), "2");
    await user.click(within(period).getByRole("button", { name: "Friday" }));
    await user.click(save());
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    const sent = posts(calls)[0].body as { items: { fields: { periods: unknown[] } }[] };
    expect(sent.items[0].fields.periods).toEqual([
      { origin: 0, start: "21:00", end: "07:00", extra: "1", weekdays: [4, 5, 6] },
      { origin: null, start: "12:00", end: "21:00", extra: "2", weekdays: [4] },
    ]);
  });
});

describe("the quotas page", () => {
  it("greys in the household's grace, says Not set for a blank limit, and chooses the rule set from every rule set", async () => {
    await open("quotas", QUOTAS);
    const quota = item("entertainment");
    expect(within(quota).getByRole("textbox", { name: "Time Grace" })).toHaveAttribute("placeholder", "5m");
    expect(within(quota).getByRole("textbox", { name: "Volume Grace" })).toHaveAttribute("placeholder", "1M");
    const bytes = within(quota).getByRole("textbox", { name: "Byte Limit" });
    expect(bytes).toHaveAttribute("placeholder", "Not set");
    expect(bytes.getAttribute("title")).toContain("always takes its false branch");
    const rules = within(quota).getByRole("combobox", { name: "Rule Set" });
    expect(within(rules).getAllByRole("option").map((option) => option.textContent)).toEqual(["gate", "meter"]);
    expect(rules).toHaveValue("meter");
  });

  it("sends the changed quota with blank limits as empty text", async () => {
    const user = userEvent.setup();
    const { calls } = await open("quotas", QUOTAS, (call) => (call.method === "POST" ? { body: DONE } : undefined));
    const time = within(item("entertainment")).getByRole("textbox", { name: "Time Limit" });
    await user.clear(time);
    await user.type(time, "60m");
    await user.click(save());
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(posts(calls)[0].body).toEqual({
      version: "v1",
      items: [{ name: "entertainment", new: false, fields: { time: "60m", bytes: "", time_grace: "", volume_grace: "", ruleset: "meter" } }],
      deleted: [],
    });
  });
});

describe("the household page", () => {
  it("shows each default greyed in a blank box, and the proxy switches on when not written", async () => {
    await open("household", HOUSEHOLD);
    expect(screen.getByRole("textbox", { name: "Bucket Length" })).toHaveAttribute("placeholder", "5m");
    expect(screen.getByRole("textbox", { name: "Host Retention" })).toHaveAttribute("placeholder", "30d");
    expect(screen.getByRole("combobox", { name: "Entry Rule Set" })).toHaveValue("gate");
    for (const name of ["Localhost", "Plain host names", "Policy server", "Local subnets", "Local domains"]) expect(screen.getByRole("checkbox", { name })).toBeChecked();
    expect(screen.queryByRole("button", { name: "Add" })).toBeNull();
  });

  it("sends only the settings that changed, with the proxy configuration as the switches and extra", async () => {
    const user = userEvent.setup();
    const { calls } = await open("household", HOUSEHOLD, (call) => (call.method === "POST" ? { body: { message: "Saved the household.", warnings: [] } } : undefined));
    await user.type(screen.getByRole("textbox", { name: "Time Grace" }), "10m");
    await user.click(screen.getByRole("checkbox", { name: "Local subnets" }));
    await user.click(screen.getByRole("button", { name: "Add extra" }));
    await user.type(screen.getByRole("textbox", { name: "Extra 1" }), "*.home.arpa");
    await user.click(save());
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(posts(calls)[0].body).toEqual({
      version: "v1",
      fields: {
        time_grace: "10m",
        proxy_configuration: { direct: { localhost: true, plain_host_names: true, policy_server: true, local_subnets: false, local_domains: true, extra: ["*.home.arpa"] } },
      },
    });
  });

  it("takes a setting out when its box is cleared", async () => {
    const user = userEvent.setup();
    const { calls } = await open("household", HOUSEHOLD, (call) => (call.method === "POST" ? { body: { message: "ok", warnings: [] } } : undefined));
    await user.clear(screen.getByRole("textbox", { name: "Timezone" }));
    fireEvent.keyDown(window, { key: "s", ctrlKey: true });
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(posts(calls)[0].body).toEqual({ version: "v1", fields: { timezone: "" } });
  });
});
