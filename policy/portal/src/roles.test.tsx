import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { fakeService, renderPortal, type Call } from "./test/portal";

// What the service lets a reviewer read (S043). Everything else answers 403, as the service does.
const REVIEWER_DATA = [/^\/parent\/api\/session$/, /^\/parent\/api\/attempts(\/.*)?$/, /^\/parent\/api\/parent-check$/, /^\/parent\/api\/usage\/(minutes|bytes|requests)$/, /^\/parent\/api\/settings\/mcp\/connect$/, /^\/parent\/api\/account(\/password)?$/];

const forAdmins = (call: Call) => !REVIEWER_DATA.some((pattern) => pattern.test(call.path));

/** Stand in for the service with nana, a reviewer, signed in. */
function asReviewer(handler: (call: Call) => { status?: number; body?: unknown } | undefined = () => undefined) {
  return fakeService((call) => {
    if (call.path === "/parent/api/session") return { body: { username: "nana", role: "reviewer" } };
    if (forAdmins(call)) return { status: 403, body: { error: "This address is for admins. You are signed in as nana, a reviewer.", admins_only: true } };
    return handler(call);
  });
}

const sidebar = () => screen.getByRole("complementary", { name: "Portal" });

describe("a reviewer's portal", () => {
  it("has Attempts and Usage in the sidebar, names the role, and loads no task list", async () => {
    const calls = asReviewer();
    renderPortal("/parent/attempts?client=younger");
    await screen.findByRole("link", { name: "spelling-week-3" });
    const nav = within(sidebar()).getByRole("navigation", { name: "Portal pages" });
    expect(within(nav).getByRole("link", { name: "Attempts" })).toBeInTheDocument();
    expect(within(nav).getByRole("button", { name: "Usage" })).toBeInTheDocument();
    for (const group of ["Task Administration", "Asset Administration", "Policy", "Settings"]) {
      expect(within(nav).queryByRole("button", { name: group })).toBeNull();
    }
    expect(within(sidebar()).getByText(/Signed in as/)).toHaveTextContent("Signed in as nana (reviewer)");
    expect(calls.filter(forAdmins)).toEqual([]);
  });

  it.each([
    "/parent/tasks/spelling/spelling",
    "/parent/tasks/spelling/spelling/words/replace-current",
    "/parent/new-task",
    "/parent/assets/parts-of-speech-pools",
    "/parent/assets/capitalisation-pools/year-3",
    "/parent/policy/site-groups",
    "/parent/policy/rule-sets/entry",
    "/parent/settings/mcp",
    "/parent/settings/mcp/activity",
    "/parent/settings/history",
    "/parent/settings/history/3f2a9c1",
    "/parent/settings/history/compare?from=3f2a9c1&to=current",
  ])("shows %s as a page for admins, in the frame, and loads nothing from it", async (address) => {
    const calls = asReviewer();
    renderPortal(address);
    expect(await screen.findByText("This page is for admins. You are signed in as nana, a reviewer.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "For admins" })).toBeInTheDocument();
    expect(sidebar()).toBeInTheDocument();
    expect(calls.filter(forAdmins)).toEqual([]);
  });

  it("opens an attempt, a trend, and the facts grid without asking for admin data", async () => {
    const calls = asReviewer();
    const user = userEvent.setup();
    renderPortal("/parent/attempts/43");
    await screen.findByRole("heading", { level: 1 });
    renderPortal("/parent/attempts/facts/multiplication?client=younger&m=7&n=8");
    await screen.findAllByRole("table", { name: "Multiplication facts" });
    renderPortal("/parent/attempts/tasks/arithmetic/sums?client=younger");
    await user.click((await screen.findAllByRole("link", { name: "Addition facts" }))[0]);
    await waitFor(() => expect(calls.some((call) => call.path === "/parent/api/attempts/facts/addition")).toBe(true));
    expect(calls.filter(forAdmins)).toEqual([]);
  });

  it.each(["/parent/usage/minutes", "/parent/usage/requests"])("chooses presets on %s but has no Save preset or Delete preset", async (address) => {
    asReviewer();
    renderPortal(address);
    expect(await screen.findByRole("combobox", { name: "Preset" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save preset" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete preset" })).toBeNull();
  });

  it("records a parent check", async () => {
    const calls = asReviewer((call) => (call.path === "/parent/api/parent-check" ? { body: { message: "Recorded a parent check for younger." } } : undefined));
    renderPortal("/parent/attempts?client=younger");
    await userEvent.setup().click(await screen.findByRole("button", { name: /parent check/i }));
    await waitFor(() => expect(calls.some((call) => call.path === "/parent/api/parent-check" && call.method === "POST")).toBe(true));
  });
});

describe("a reviewer's Account page", () => {
  it("opens, with Change password, from the signed-in line", async () => {
    const calls = asReviewer((call) => (call.path === "/parent/api/account" ? { body: { username: "nana", role: "reviewer", email: "nana@example.net" } } : undefined));
    renderPortal("/parent/attempts?client=younger");
    await screen.findByRole("link", { name: "spelling-week-3" });
    await userEvent.setup().click(within(sidebar()).getByRole("link", { name: "Signed in as nana (reviewer)" }));
    expect(await screen.findByRole("button", { name: "Change password" })).toBeInTheDocument();
    expect(screen.queryByText(/This page is for admins/)).toBeNull();
    expect(calls.filter(forAdmins)).toEqual([]);
  });
});

describe("an admin's portal", () => {
  it("names the role and keeps every sidebar group and the preset buttons", async () => {
    fakeService();
    renderPortal("/parent/usage/minutes");
    expect(await screen.findByRole("button", { name: "Save preset" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete preset" })).toBeInTheDocument();
    const nav = within(sidebar()).getByRole("navigation", { name: "Portal pages" });
    for (const group of ["Usage", "Task Administration", "Asset Administration", "Policy", "Settings"]) {
      expect(within(nav).getByRole("button", { name: group })).toBeInTheDocument();
    }
    expect(within(sidebar()).getByText(/Signed in as/)).toHaveTextContent("Signed in as ada (admin)");
  });

  it("sees who approved each agent, with their role", async () => {
    fakeService((call) =>
      call.path === "/parent/api/settings/mcp"
        ? {
            body: {
              exists: true,
              on: true,
              problems: [],
              version: "v1",
              file: "/etc/daywarden/mcp.yaml",
              endpoint: "https://garden:8084/mcp",
              settings: { enabled: true, access_token: "1h", refresh_idle: "30d", refresh_lifetime: "90d", activity_days: 90, permissions: { attempts: ["read"] } },
              classes: [{ name: "attempts", permissions: ["read"] }],
              connections: [{ id: 8, agent: "Claude Code", parent: "nana", role: "reviewer", approved: "2026-11-17 09:00", last_used: "2026-11-17 09:50", lapses: "2026-12-17 09:50" }],
            },
          }
        : undefined,
    );
    renderPortal("/parent/settings/mcp");
    expect(await screen.findByRole("cell", { name: "nana (reviewer)" })).toBeInTheDocument();
  });
});

describe("a reviewer's consent page", () => {
  const REQUEST = {
    request: "abc",
    agent: "Claude Code",
    client_id: "c0ffee",
    redirect_uri: "http://localhost:43123/callback",
    permissions: [
      { name: "attempts", permissions: ["read"] },
      { name: "usage", permissions: ["read"] },
    ],
    problem: null,
    reviewer: true,
  };

  async function openConsent(body: unknown) {
    const calls = asReviewer((call) => (call.path === "/parent/api/settings/mcp/connect" && call.method === "GET" ? { body } : undefined));
    renderPortal("/parent/settings/mcp/connect?request=abc");
    await screen.findByRole("heading", { name: "Connect an Agent" });
    return calls;
  }

  it("lists what the agent will have, says a reviewer's agent only reads, and links to no admin page", async () => {
    const calls = await openConsent(REQUEST);
    expect(screen.getByText("You are a reviewer, so an agent you approve can only read attempts and usage.")).toBeInTheDocument();
    expect(screen.getByTitle("attempts")).toBeInTheDocument();
    expect(screen.getByTitle("usage")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
    const crumbs = screen.getByRole("navigation", { name: "Where you are" });
    expect(within(crumbs).getByText("MCP Server")).toBeInTheDocument();
    expect(within(crumbs).queryByRole("link")).toBeNull();
    expect(calls.filter(forAdmins)).toEqual([]);
  });

  it("disables Approve when there is nothing a reviewer's agent could use, and Deny still works", async () => {
    await openConsent({ ...REQUEST, permissions: [] });
    expect(screen.getByText(/nothing a reviewer's agent could use/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Deny" })).toBeEnabled();
  });
});
