import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { browser } from "./pages/McpConnect";
import { fakeService, renderPortal, shown, type Call, type Reply } from "./test/portal";

const DATA = "/parent/api/settings/mcp";
const CLASSES = [
  { name: "household", permissions: ["read", "update"] },
  { name: "tasks", permissions: ["create", "read", "update", "delete"] },
  { name: "attempts", permissions: ["read"] },
];
const PAGE = {
  exists: true,
  on: true,
  problems: [],
  version: "v1",
  file: "/etc/daywarden/mcp.yaml",
  endpoint: "https://garden:8084/mcp",
  settings: {
    enabled: true,
    access_token: "1h",
    refresh_idle: "30d",
    refresh_lifetime: "90d",
    activity_days: 90,
    permissions: { household: [], tasks: ["create", "read", "update"], attempts: ["read"] },
  },
  classes: CLASSES,
  connections: [{ id: 7, agent: "Claude Code", parent: "ada", role: "admin", approved: "2026-11-17 09:00", last_used: "2026-11-17 09:50", lapses: "2026-12-17 09:50" }],
};

async function openMcp(handler?: (call: Call) => Reply | undefined) {
  const calls = fakeService((call) => {
    const answered = handler?.(call);
    if (answered) return answered;
    return call.path === DATA && call.method === "GET" ? { body: PAGE } : undefined;
  });
  const view = renderPortal("/parent/settings/mcp");
  await screen.findByRole("heading", { name: "MCP Server" });
  return { calls, router: view.router };
}

afterEach(() => vi.restoreAllMocks());

describe("the MCP Server page", () => {
  it("is in the Settings group of the sidebar", async () => {
    await openMcp();
    const sidebar = screen.getByRole("complementary", { name: "Portal" });
    expect(within(sidebar).getByRole("button", { name: "Settings" })).toHaveAttribute("aria-expanded", "true");
    expect(within(sidebar).getByRole("link", { name: "MCP Server" })).toHaveAttribute("href", "/parent/settings/mcp");
  });

  it("has a checkbox only where a class has that permission", async () => {
    await openMcp();
    const attempts = screen.getByRole("rowheader", { name: "Attempts" }).closest("tr")!;
    expect(within(attempts).getAllByRole("checkbox").map((box) => box.getAttribute("aria-label"))).toEqual(["Attempts: read"]);
    expect(screen.getAllByRole("checkbox", { name: /^Household:/ })).toHaveLength(2);
    expect(screen.getAllByRole("checkbox", { name: /^Tasks:/ })).toHaveLength(4);
    expect(screen.getByRole("checkbox", { name: "Tasks: delete" })).not.toBeChecked();
    expect(screen.getByDisplayValue("https://garden:8084/mcp")).toBeInTheDocument();
  });

  it("marks a change and saves every change with Ctrl+S", async () => {
    const { calls } = await openMcp((call) =>
      call.path === DATA && call.method === "POST" ? { body: { message: "Saved the MCP settings.", warnings: [] } } : undefined,
    );
    const user = userEvent.setup();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: "Household: read" }));
    expect(screen.getByRole("checkbox", { name: "Household: read" }).parentElement).toHaveAttribute("data-changed", "true");
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    await user.keyboard("{Control>}s{/Control}");
    await screen.findByText("Saved the MCP settings.");
    const saved = calls.find((call) => call.path === DATA && call.method === "POST")!;
    expect(saved.body).toEqual({
      version: "v1",
      settings: { ...PAGE.settings, permissions: { ...PAGE.settings.permissions, household: ["read"] } },
    });
  });

  it("lists each reason a save is refused in the status bar", async () => {
    await openMcp((call) =>
      call.path === DATA && call.method === "POST"
        ? { status: 400, body: { error: "The MCP settings were not saved.", errors: ["access_token: 0h is not a duration."] } }
        : undefined,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("switch"));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("The MCP settings were not saved.")).toBeInTheDocument();
    expect(screen.getByText("access_token: 0h is not a duration.")).toBeInTheDocument();
  });

  it("asks before revoking, with Cancel as the default, and revokes at once", async () => {
    const { calls } = await openMcp((call) =>
      call.path === `${DATA}/connections/7/revoke` ? { body: { message: "Revoked Claude Code." } } : undefined,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Revoke" }));
    const dialog = screen.getByRole("alertdialog", { name: "Revoke this connection?" });
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.click(within(dialog).getByRole("button", { name: "Revoke" }));
    await screen.findByText("Revoked Claude Code.");
    expect(calls.some((call) => call.path === `${DATA}/connections/7/revoke` && call.method === "POST")).toBe(true);
  });

  it("asks before leaving with unsaved changes", async () => {
    const { router } = await openMcp();
    const user = userEvent.setup();
    await user.click(screen.getByRole("checkbox", { name: "Tasks: delete" }));
    await user.click(screen.getByRole("link", { name: "Activity" }));
    const dialog = screen.getByRole("alertdialog", { name: "Leave this page?" });
    expect(within(dialog).getByRole("button", { name: "Stay" })).toHaveFocus();
    await user.click(within(dialog).getByRole("button", { name: "Stay" }));
    expect(shown(router)).toBe("/parent/settings/mcp");
  });
});

describe("the consent page", () => {
  const REQUEST = {
    request: "abc",
    agent: "Claude Code",
    client_id: "c0ffee",
    redirect_uri: "http://localhost:43123/callback",
    permissions: [{ name: "tasks", permissions: ["read"] }],
    problem: null,
  };

  async function openConsent(body: unknown, handler?: (call: Call) => Reply | undefined) {
    const calls = fakeService((call) => {
      const answered = handler?.(call);
      if (answered) return answered;
      return call.path === "/parent/api/settings/mcp/connect" && call.method === "GET" ? { body } : undefined;
    });
    renderPortal("/parent/settings/mcp/connect?request=abc");
    await screen.findByRole("heading", { name: "Connect an Agent" });
    return calls;
  }

  it("shows the agent and approves only when Approve is pressed", async () => {
    const leave = vi.spyOn(browser, "leave").mockImplementation(() => undefined);
    const calls = await openConsent(REQUEST, (call) =>
      call.method === "POST" ? { body: { location: "http://localhost:43123/callback?code=x&state=s" } } : undefined,
    );
    expect(screen.getByText("Claude Code")).toBeInTheDocument();
    expect(screen.getByText("http://localhost:43123/callback")).toBeInTheDocument();
    expect(screen.getByText("Tasks")).toBeInTheDocument();
    expect(calls.some((call) => call.method === "POST")).toBe(false);
    await userEvent.setup().click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(leave).toHaveBeenCalledWith("http://localhost:43123/callback?code=x&state=s"));
    expect(calls.find((call) => call.method === "POST")!.body).toEqual({ request: "abc", decision: "approve" });
  });

  it("shows a problem and offers nothing to press", async () => {
    await openConsent({ ...REQUEST, problem: "The agent did not use PKCE with S256, so it cannot be approved." });
    expect(screen.getByRole("alert")).toHaveTextContent("PKCE with S256");
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Deny" })).toBeNull();
  });
});

describe("the activity log", () => {
  it("lists entries newest first with their outcome and reasons", async () => {
    fakeService((call) =>
      call.path === "/parent/api/settings/mcp/activity"
        ? {
            body: {
              entries: [
                { at: "2026-11-17 10:00:00", agent: "Claude Code", parent: "ada", tool: "get_task", target: "arithmetic/times-7", outcome: "refused", reasons: ["This needs tasks: read."] },
                { at: "2026-11-17 09:00:00", agent: "Claude Code", parent: "ada", tool: "", target: "", outcome: "approved", reasons: [] },
              ],
              keep_days: 90,
              times: "Times are Australia/Sydney.",
            },
          }
        : undefined,
    );
    renderPortal("/parent/settings/mcp/activity");
    await screen.findByRole("heading", { name: "Activity" });
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("arithmetic/times-7");
    expect(rows[0]).toHaveTextContent("Refused: This needs tasks: read.");
    expect(rows[1]).toHaveTextContent("Approved");
  });
});
