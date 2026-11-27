import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeService, renderPortal, shown, type Call, type Reply } from "./test/portal";

const DATA = "/parent/api/settings/history";
const NEWEST = {
  id: "9b1c0de9b1c0de9b1c0de9b1c0de9b1c0de9b1c0",
  short: "9b1c0de",
  time: "2026-11-20 18:30",
  author: "brett",
  what: "saved task spelling",
  message: "2026-11-20 18:30 -0500 brett: saved task spelling",
  files: ["tasks.d/spelling.yaml"],
};
const OLDER = {
  id: "3f2a9c13f2a9c13f2a9c13f2a9c13f2a9c13f2a9",
  short: "3f2a9c1",
  time: "2026-11-17 20:15",
  author: "ada",
  what: "via Claude Code: saved task arithmetic/times-7",
  message: "2026-11-17 20:15 -0500 ada via Claude Code: saved task arithmetic/times-7",
  files: ["tasks.d/times-7.yaml", "policy.yaml"],
};
const LIST = {
  kept: true,
  revisions: [NEWEST, OLDER],
  page: 1,
  pages: 2,
  total: 52,
  file: null,
  hand_edits: [] as string[],
  times: "Times are in America/New_York.",
};
const CHANGED = {
  path: "tasks.d/times-7.yaml",
  status: "changed",
  binary: false,
  hunks: [
    {
      header: "@@ -1,3 +1,3 @@",
      lines: [
        { kind: " ", text: "tasks:", old: 1, new: 1 },
        { kind: "-", text: "  pass_cooldown: 1", old: 2, new: null },
        { kind: "+", text: "  pass_cooldown: 2", old: null, new: 2 },
      ],
    },
  ],
  unified: "",
};
const REVISION = { revision: OLDER, newest: false, head: NEWEST.id, before: "0000aaa", diff: [CHANGED] };
const PREVIEW = {
  revision: OLDER,
  head: NEWEST.id,
  newest: false,
  diff: [{ ...CHANGED, path: "tasks.d/spelling.yaml" }],
  nothing: false,
  renames: ["Client group kids was renamed to younger after this version. Attempts and usage recorded under younger stay under younger."],
  mcp: "The MCP settings in mcp.yaml are kept as they are now. They are changed on the MCP Server page.",
};

function service(handler?: (call: Call) => Reply | undefined) {
  return fakeService((call) => {
    const answered = handler?.(call);
    if (answered) return answered;
    if (call.path === DATA) return { body: LIST };
    if (call.path === `${DATA}/revisions/3f2a9c1` && call.method === "GET") return { body: REVISION };
    if (call.path === `${DATA}/revisions/3f2a9c1/revert` && call.method === "GET") return { body: PREVIEW };
    return undefined;
  });
}

afterEach(() => vi.restoreAllMocks());

describe("the Config History list", () => {
  it("is in the Settings group and lists each revision with links to its page and its files", async () => {
    service();
    renderPortal("/parent/settings/history");
    await screen.findByRole("heading", { name: "Config History" });
    const sidebar = screen.getByRole("complementary", { name: "Portal" });
    expect(within(sidebar).getByRole("link", { name: "Config History" })).toHaveAttribute("href", "/parent/settings/history");
    const row = screen.getByRole("link", { name: "2026-11-20 18:30" }).closest("tr")!;
    expect(screen.getByRole("link", { name: "2026-11-20 18:30" })).toHaveAttribute("href", "/parent/settings/history/9b1c0de");
    expect(within(row).getByText("brett")).toBeInTheDocument();
    expect(within(row).getByText("saved task spelling")).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "tasks.d/spelling.yaml" })).toHaveAttribute(
      "href",
      "/parent/settings/history?file=tasks.d%2Fspelling.yaml",
    );
    expect(screen.getByRole("link", { name: "Older" })).toHaveAttribute("href", "/parent/settings/history?page=2");
    expect(screen.queryByRole("link", { name: "Newer" })).toBeNull();
    expect(screen.getByText("Versions 1 to 2 of 52.")).toBeInTheDocument();
  });

  it("asks for the page and file in the address", async () => {
    const calls = service((call) => (call.path === DATA ? { body: { ...LIST, page: 2, file: "policy.yaml" } } : undefined));
    renderPortal("/parent/settings/history?file=policy.yaml&page=2");
    await screen.findByRole("heading", { name: "policy.yaml" });
    expect(calls.find((call) => call.path === DATA)?.search).toBe("?page=2&file=policy.yaml");
    expect(screen.getByRole("link", { name: "Newer" })).toHaveAttribute("href", "/parent/settings/history?file=policy.yaml");
    expect(screen.getByRole("link", { name: "Show every version" })).toHaveAttribute("href", "/parent/settings/history");
  });

  it("names the hand edits waiting to be committed", async () => {
    service((call) => (call.path === DATA ? { body: { ...LIST, hand_edits: ["policy.yaml", "tasks.d/new.yaml"] } } : undefined));
    renderPortal("/parent/settings/history");
    const note = await screen.findByText(/hand edits that are not in the history yet/);
    expect(note).toHaveTextContent("policy.yaml, tasks.d/new.yaml. The next dw reload or portal save commits them.");
  });

  it("says there is no history where the config directory has none", async () => {
    service((call) => (call.path === DATA ? { body: { kept: false } } : undefined));
    renderPortal("/parent/settings/history");
    expect(await screen.findByText(/has no history of its own/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("link", { name: "Compare" })).toBeNull();
  });

  it("puts the From and To choices in the address and the Compare link, without loading the list again", async () => {
    const calls = service();
    const user = userEvent.setup();
    const { router } = renderPortal("/parent/settings/history");
    await screen.findByRole("heading", { name: "Config History" });
    expect(screen.getByRole("radio", { name: "From 2026-11-17 20:15" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "To 2026-11-20 18:30" })).toBeChecked();
    expect(screen.getByRole("link", { name: "Compare" })).toHaveAttribute(
      "href",
      `/parent/settings/history/compare?from=${OLDER.id}&to=${NEWEST.id}`,
    );
    await user.click(screen.getByRole("radio", { name: "From 2026-11-20 18:30" }));
    await user.click(screen.getByRole("radio", { name: "To 2026-11-17 20:15" }));
    expect(shown(router)).toBe(`/parent/settings/history?from=${NEWEST.id}&to=${OLDER.id}`);
    await waitFor(() =>
      expect(screen.getByRole("link", { name: "Compare" })).toHaveAttribute(
        "href",
        `/parent/settings/history/compare?from=${NEWEST.id}&to=${OLDER.id}`,
      ),
    );
    expect(calls.filter((call) => call.path === DATA)).toHaveLength(1);
  });
});

describe("a revision's page", () => {
  it("shows its details and its diff with + and - marks", async () => {
    service();
    renderPortal("/parent/settings/history/3f2a9c1");
    await screen.findByRole("heading", { name: "2026-11-17 20:15" });
    expect(screen.getByText(OLDER.id)).toBeInTheDocument();
    const file = screen.getByRole("region", { name: "tasks.d/times-7.yaml, changed" });
    expect(within(file).getByLabelText("removed")).toHaveTextContent("-");
    expect(within(file).getByLabelText("added")).toHaveTextContent("+");
    const added = within(file).getByLabelText("added").closest("tr")!;
    expect(added).toHaveAttribute("data-kind", "added");
    expect(added).toHaveTextContent("pass_cooldown: 2");
    expect(screen.getByRole("link", { name: "Compare with current" })).toHaveAttribute(
      "href",
      "/parent/settings/history/compare?from=3f2a9c1&to=current",
    );
  });

  it("offers no Revert on the newest revision", async () => {
    service((call) =>
      call.path === `${DATA}/revisions/9b1c0de` ? { body: { ...REVISION, revision: NEWEST, newest: true } } : undefined,
    );
    renderPortal("/parent/settings/history/9b1c0de");
    await screen.findByRole("heading", { name: "2026-11-20 18:30" });
    expect(screen.queryByRole("button", { name: "Revert to this version" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Compare with current" })).toBeNull();
  });

  it("shows the not-found page for an unknown revision", async () => {
    service((call) => (call.path === `${DATA}/revisions/0000000` ? { status: 404, body: { error: "There is no revision 0000000." } } : undefined));
    renderPortal("/parent/settings/history/0000000");
    expect(await screen.findByRole("heading", { name: "Not found" })).toBeInTheDocument();
  });
});

describe("Revert", () => {
  async function openDialog(handler?: (call: Call) => Reply | undefined) {
    const calls = service(handler);
    const user = userEvent.setup();
    const view = renderPortal("/parent/settings/history/3f2a9c1");
    await user.click(await screen.findByRole("button", { name: "Revert to this version" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Revert to 2026-11-17 20:15?" });
    await within(dialog).findByRole("region", { name: "tasks.d/spelling.yaml, changed" });
    return { calls, user, dialog, ...view };
  }

  it("shows the diff it would make, the renames, and that mcp.yaml is kept, with Cancel the default", async () => {
    const { calls, user, dialog } = await openDialog();
    expect(within(dialog).getByText(PREVIEW.renames[0])).toBeInTheDocument();
    expect(within(dialog).getByText(PREVIEW.mcp)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(calls.filter((call) => call.method === "POST")).toEqual([]);
  });

  it("posts the newest revision it was opened on and opens the list with the outcome", async () => {
    const { calls, user, dialog, router } = await openDialog((call) =>
      call.method === "POST" ? { body: { message: "Reverted to 3f2a9c1 (2026-11-17 20:15).", warnings: [], renames: [] } } : undefined,
    );
    await user.click(within(dialog).getByRole("button", { name: "Revert" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/settings/history"));
    const posted = calls.find((call) => call.method === "POST")!;
    expect(posted.path).toBe(`${DATA}/revisions/3f2a9c1/revert`);
    expect(posted.body).toEqual({ head: NEWEST.id });
    expect(await screen.findByText("Reverted to 3f2a9c1 (2026-11-17 20:15).")).toBeInTheDocument();
  });

  it("keeps the dialog open with each error when the check fails", async () => {
    const { user, dialog } = await openDialog((call) =>
      call.method === "POST"
        ? {
            status: 400,
            body: {
              error: "The files of this version do not pass dw check, so nothing was reverted.",
              errors: ["/etc/daywarden/tasks.d/spelling.yaml: spelling/week-1 is not in the data directory"],
            },
          }
        : undefined,
    );
    await user.click(within(dialog).getByRole("button", { name: "Revert" }));
    expect(await within(dialog).findByText(/do not pass dw check/)).toBeInTheDocument();
    expect(within(dialog).getByText(/spelling\/week-1 is not in the data directory/)).toBeInTheDocument();
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });

  it("refuses to go on once the configuration has changed meanwhile", async () => {
    const { user, dialog } = await openDialog((call) =>
      call.method === "POST" ? { status: 409, body: { error: "The configuration changed after this dialog was opened.", stale: true } } : undefined,
    );
    await user.click(within(dialog).getByRole("button", { name: "Revert" }));
    expect(await within(dialog).findByText("The configuration changed after this dialog was opened.")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Revert" })).toBeDisabled();
  });
});

describe("comparing two revisions", () => {
  it("shows each revision's time and author, and says when nothing differs", async () => {
    const calls = service((call) =>
      call.path === `${DATA}/compare` ? { body: { from: OLDER, to: NEWEST, diff: [] } } : undefined,
    );
    renderPortal(`/parent/settings/history/compare?from=${OLDER.short}&to=current`);
    expect(await screen.findByText("Nothing differs: these two versions have the same files.")).toBeInTheDocument();
    expect(calls.find((call) => call.path === `${DATA}/compare`)?.search).toBe(`?from=${OLDER.short}&to=current`);
    expect(screen.getByRole("link", { name: "2026-11-17 20:15" })).toHaveAttribute("href", "/parent/settings/history/3f2a9c1");
    expect(within(screen.getByLabelText("From")).getByText("ada")).toBeInTheDocument();
    expect(within(screen.getByLabelText("To")).getByText("brett")).toBeInTheDocument();
  });
});
