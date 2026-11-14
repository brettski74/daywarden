import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TASKS_KEY } from "./sidebar";
import { SPELLING, fakeService, renderPortal, shown, type Call, type Reply } from "./test/portal";

function saves(calls: Call[]) {
  return calls.filter((call) => call.method === "POST" && call.path.startsWith("/parent/api/tasks/"));
}

async function openTask(address: string, handler?: (call: Call) => Reply | undefined) {
  const calls = fakeService(handler);
  const view = renderPortal(address);
  await screen.findByRole("heading", { name: decodeURIComponent(address.split("/")[4].split("?")[0]) });
  return { calls, ...view };
}

describe("Task Administration in the sidebar", () => {
  it("is a button that lists every task as a link, and hides them again, remembering the choice", async () => {
    fakeService();
    renderPortal("/parent/usage/minutes");
    const nav = await screen.findByRole("navigation", { name: "Portal pages" });
    const toggle = within(nav).getByRole("button", { name: "Task Administration" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(within(nav).queryByRole("link", { name: "spelling" })).not.toBeInTheDocument();

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const links = within(nav.querySelector("#task-list") as HTMLElement).getAllByRole("link");
    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["Create New Task", "/parent/new-task"],
      ["check", "/parent/tasks/parent_check/check"],
      ["spelling", "/parent/tasks/spelling/spelling"],
      ["sums", "/parent/tasks/worksheet/sums"],
    ]);
    expect(localStorage.getItem(TASKS_KEY)).toBe("true");

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await waitFor(() => expect(within(nav).queryByRole("link", { name: "spelling" })).not.toBeInTheDocument());
    expect(localStorage.getItem(TASKS_KEY)).toBe("false");
  });

  it("names each task by its type and name, adding the type where two tasks share a name", async () => {
    localStorage.setItem(TASKS_KEY, "true");
    const listed = [
      { type: "arithmetic", name: "week-1" },
      { type: "spelling", name: "week-1" },
      { type: "worksheet", name: "sums" },
    ];
    fakeService((call) => (call.path === "/parent/api/tasks" ? { body: { tasks: listed } } : undefined));
    renderPortal("/parent/attempts");
    const links = within((await screen.findByRole("navigation", { name: "Portal pages" })).querySelector("#task-list") as HTMLElement);
    expect((await links.findAllByRole("link")).map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["Create New Task", "/parent/new-task"],
      ["week-1 (arithmetic)", "/parent/tasks/arithmetic/week-1"],
      ["week-1 (spelling)", "/parent/tasks/spelling/week-1"],
      ["sums", "/parent/tasks/worksheet/sums"],
    ]);
  });

  it("stays expanded across a reload", async () => {
    localStorage.setItem(TASKS_KEY, "true");
    fakeService();
    renderPortal("/parent/attempts");
    expect(await screen.findByRole("link", { name: "sums" })).toHaveAttribute("href", "/parent/tasks/worksheet/sums");
  });

  it("is expanded with the open task marked when a task page is opened directly", async () => {
    await openTask("/parent/tasks/spelling/spelling");
    const nav = screen.getByRole("navigation", { name: "Portal pages" });
    expect(within(nav).getByRole("button", { name: "Task Administration" })).toHaveAttribute("aria-expanded", "true");
    expect(within(nav).getByRole("link", { name: "spelling" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "sums" })).not.toHaveAttribute("aria-current");
    expect(localStorage.getItem(TASKS_KEY)).toBe("true");
  });
});

describe("a task page", () => {
  it("shows the task in the context bar and its settings in groups", async () => {
    await openTask("/parent/tasks/spelling/spelling");
    const crumbs = screen.getByRole("navigation", { name: "Where you are" });
    expect(crumbs).toHaveTextContent("Tasks");
    expect(within(crumbs).getByRole("heading", { name: "spelling" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Task" })).toHaveTextContent("spelling");
    expect(screen.getByRole("button", { name: "Client Groups younger" })).toHaveAttribute("aria-expanded", "false");
    const limits = screen.getByRole("group", { name: "Cooldowns and limits" });
    expect(within(limits).getByRole("textbox", { name: "Max Skips" })).toHaveValue("3");
    expect(within(limits).getByRole("textbox", { name: "Max Passes" })).toHaveValue("");
    expect(within(screen.getByRole("group", { name: "Dates" })).getByRole("textbox", { name: "Due Date" })).toBeInTheDocument();
    expect(document.title).toBe("spelling · Daywarden");
  });

  it("offers a parent check no date, skip, or pass fields", async () => {
    await openTask("/parent/tasks/parent_check/check");
    expect(screen.getByRole("textbox", { name: "Pass Cooldown" })).toHaveValue("0");
    for (const name of ["Available From", "Due Date", "Max Skips", "Max Passes"]) {
      expect(screen.queryByRole("textbox", { name })).not.toBeInTheDocument();
    }
    expect(screen.queryByRole("group", { name: "Dates" })).not.toBeInTheDocument();
  });

  it("says a type with no administration page is not built yet", async () => {
    await openTask("/parent/tasks/worksheet/sums");
    expect(screen.getByText("Task-specific administration for worksheet tasks is not built yet.")).toBeInTheDocument();
  });

  it("says an unknown task is not there, with the frame around it", async () => {
    fakeService((call) => (call.path === "/parent/api/tasks/worksheet/nope" ? { status: 404, body: { error: "There is no task named nope." } } : undefined));
    renderPortal("/parent/tasks/worksheet/nope");
    expect(await screen.findByText("There is no task named nope.")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Portal pages" })).toBeInTheDocument();
  });
});

describe("the client groups pull-down", () => {
  it("lists the chosen groups when closed, highlights them when open, and toggles one per click", async () => {
    await openTask("/parent/tasks/spelling/spelling");
    const button = screen.getByRole("button", { name: "Client Groups younger" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();

    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    const list = screen.getByRole("listbox", { name: "Client Groups" });
    expect(list).toHaveAttribute("aria-multiselectable", "true");
    expect(list).toHaveFocus();
    const selected = () => within(list).getAllByRole("option").filter((option) => option.getAttribute("aria-selected") === "true").map((option) => option.textContent);
    expect(selected()).toEqual(["younger"]);

    await userEvent.click(within(list).getByRole("option", { name: "default" }));
    await userEvent.click(within(list).getByRole("option", { name: "older" }));
    expect(selected()).toEqual(["younger", "older", "default"]);
    await userEvent.click(within(list).getByRole("option", { name: "younger" }));
    expect(selected()).toEqual(["older", "default"]);
    expect(button).toHaveTextContent("older, default");
    expect(screen.getByRole("banner")).toHaveTextContent("Unsaved changes");

    await userEvent.keyboard("{Home} ");
    expect(selected()).toEqual(["younger", "older", "default"]);
    await userEvent.keyboard("{Escape}");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveFocus();
    expect(button).toHaveTextContent("younger, older, default");
  });

  it("closes on a click elsewhere", async () => {
    await openTask("/parent/tasks/spelling/spelling");
    await userEvent.click(screen.getByRole("button", { name: "Client Groups younger" }));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("textbox", { name: "Max Skips" }));
    await waitFor(() => expect(screen.queryByRole("listbox")).not.toBeInTheDocument());
  });
});

describe("saving", () => {
  it("offers Save, and shows that there are unsaved changes, only once something has changed", async () => {
    const { calls } = await openTask("/parent/tasks/spelling/spelling");
    const save = screen.getByRole("button", { name: "Save" });
    const bar = screen.getByRole("banner");
    expect(save).toBeDisabled();
    expect(bar).not.toHaveTextContent("Unsaved changes");
    await userEvent.keyboard("{Control>}s{/Control}");
    expect(saves(calls)).toHaveLength(0);

    await userEvent.type(screen.getByRole("textbox", { name: "Max Passes" }), "2");
    expect(save).toBeEnabled();
    expect(bar).toHaveTextContent("Unsaved changes");
    await userEvent.clear(screen.getByRole("textbox", { name: "Max Passes" }));
    expect(save).toBeDisabled();
    expect(bar).not.toHaveTextContent("Unsaved changes");
  });

  it("saves every change with Ctrl+S and confirms it in the status bar", async () => {
    let saved = false;
    const { calls } = await openTask("/parent/tasks/spelling/spelling", (call) => {
      if (call.method === "POST") {
        saved = true;
        return { body: { message: "Saved spelling. The decisions, observations, and autoconfig services are using it.", warnings: [] } };
      }
      return undefined;
    });
    const cooldown = screen.getByRole("textbox", { name: "Pass Cooldown" });
    await userEvent.clear(cooldown);
    await userEvent.type(cooldown, "4");
    await userEvent.click(screen.getByRole("button", { name: "Client Groups younger" }));
    await userEvent.click(screen.getByRole("option", { name: "older" }));
    await userEvent.clear(screen.getByRole("textbox", { name: "Timeout" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Timeout" }), "20s");
    expect(screen.getByRole("banner")).toHaveTextContent("Unsaved changes");

    await userEvent.keyboard("{Control>}s{/Control}");
    expect(await screen.findByText(/^Saved spelling\./)).toBeInTheDocument();
    expect(saved).toBe(true);
    const [post] = saves(calls);
    expect(post.path).toBe("/parent/api/tasks/spelling/spelling");
    expect(post.body).toMatchObject({
      version: "v1",
      fields: { pass_cooldown: "4", max_skips: "3" },
      groups: ["younger", "older"],
      settings: { timeout: "20s", revision_required: "1" },
      moves: {},
      confirmed: false,
    });
    await waitFor(() => expect(screen.getByRole("banner")).not.toHaveTextContent("Unsaved changes"));
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("lists each reason a save was refused and keeps the change on screen", async () => {
    await openTask("/parent/tasks/spelling/spelling", (call) =>
      call.method === "POST"
        ? {
            status: 400,
            body: {
              error: "This save would leave the policy unable to load, so nothing was saved.",
              errors: ["/etc/daywarden/policy.yaml:17:17: max_passes must be a whole number, zero or more"],
            },
          }
        : undefined,
    );
    await userEvent.type(screen.getByRole("textbox", { name: "Max Passes" }), "-1");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    const status = screen.getByRole("status");
    expect(await within(status).findByText(/max_passes must be a whole number/)).toBeInTheDocument();
    expect(status).toHaveTextContent("This save would leave the policy unable to load");
    expect(screen.getByRole("textbox", { name: "Max Passes" })).toHaveValue("-1");
  });

  it("keeps refusing a page opened before a hand edit until it is reloaded", async () => {
    let version = "v1";
    const { calls } = await openTask("/parent/tasks/spelling/spelling", (call) => {
      if (call.method === "POST") {
        const sent = (call.body as { version: string }).version;
        return sent === version
          ? { body: { message: "Saved spelling.", warnings: [] } }
          : { status: 409, body: { error: "The policy file has changed on the server since this page was opened. Reload the page and make the change again.", stale: true } };
      }
      if (call.path === "/parent/api/tasks/spelling/spelling") return { body: { ...SPELLING, version } };
      return undefined;
    });
    version = "v2";
    await userEvent.type(screen.getByRole("textbox", { name: "Max Passes" }), "2");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Reload the page and make the change again\./)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(saves(calls)).toHaveLength(2));
    expect(saves(calls).map((call) => (call.body as { version: string }).version)).toEqual(["v1", "v1"]);
  });

  it("asks before saving a due-dated task a group has passed, and Cancel writes nothing", async () => {
    const { calls } = await openTask("/parent/tasks/spelling/spelling", (call) => {
      if (call.method !== "POST") return undefined;
      if ((call.body as { confirmed: boolean }).confirmed) return { body: { message: "Saved spelling.", warnings: [] } };
      return { status: 409, body: { confirm: "younger already has a pass for spelling. Saving does not ask it to do the task again.", groups: ["younger"] } };
    });
    await userEvent.type(screen.getByRole("textbox", { name: "Due Date" }), "2026-11-30");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Save anyway?" });
    expect(dialog).toHaveTextContent("younger already has a pass for spelling.");
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(saves(calls)).toHaveLength(1);

    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved spelling.")).toBeInTheDocument();
    expect(saves(calls).map((call) => (call.body as { confirmed: boolean }).confirmed)).toEqual([false, false, true]);
  });

  it("asks before leaving with unsaved changes, with Stay as the default", async () => {
    localStorage.setItem(TASKS_KEY, "true");
    fakeService();
    const { router } = renderPortal("/parent/usage/minutes");
    await userEvent.click(await screen.findByRole("link", { name: "spelling" }));
    await userEvent.type(await screen.findByRole("textbox", { name: "Max Passes" }), "2");
    await userEvent.click(screen.getByRole("link", { name: "Attempts" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Leave this page?" });
    expect(within(dialog).getByRole("button", { name: "Stay" })).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(shown(router)).toBe("/parent/tasks/spelling/spelling");
    expect(screen.getByRole("textbox", { name: "Max Passes" })).toHaveValue("2");

    await router.navigate(-1);
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Leave" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/usage/minutes"));
  });
});

describe("the spelling words", () => {
  it("lists current and revision words by default and keeps the pool filter in the address", async () => {
    const { calls, router } = await openTask("/parent/tasks/spelling/spelling");
    const table = screen.getByRole("table");
    const keys = () => within(table).getAllByRole("row").slice(1).map((row) => within(row).getAllByRole("button")[0].textContent);
    expect(keys()).toEqual(["rope", "cat", "fish"]);
    expect(screen.getByRole("status")).toHaveTextContent("Words listed: 2 current, 1 revision.");
    const fetched = calls.filter((call) => call.path === "/parent/api/tasks/spelling/spelling").length;

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Pool" }), "attic");
    await waitFor(() => expect(shown(router)).toBe("/parent/tasks/spelling/spelling?pool=attic"));
    await waitFor(() => expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(2));
    expect(screen.getByRole("button", { name: "owl" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retire" })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Words listed: 1 attic.");
    expect(calls.filter((call) => call.path === "/parent/api/tasks/spelling/spelling")).toHaveLength(fetched);
  });

  it("marks a word whose pool changed and moves it on save", async () => {
    const { calls } = await openTask("/parent/tasks/spelling/spelling", (call) =>
      call.method === "POST" ? { body: { message: "Moved rope to revision.", warnings: [] } } : undefined,
    );
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Pool for rope" }), "revision");
    expect(screen.getByRole("combobox", { name: "Pool for rope" }).closest("tr")).toHaveAttribute("data-changed");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Moved rope to revision.")).toBeInTheDocument();
    expect(saves(calls)[0].body).toMatchObject({ moves: { rope: "revision" } });
  });

  it("offers Attic in a word's pool pull-down only for a word already there", async () => {
    await openTask("/parent/tasks/spelling/spelling?pool=attic");
    const options = (name: string) => within(screen.getByRole("combobox", { name })).getAllByRole("option").map((option) => option.textContent);
    expect(options("Pool for owl")).toEqual(["Current", "Revision", "Attic"]);
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Pool" }), "");
    await screen.findByRole("combobox", { name: "Pool for rope" });
    expect(options("Pool for rope")).toEqual(["Current", "Revision"]);
    expect(options("Pool for fish")).toEqual(["Current", "Revision"]);
  });

  it("retires a word at once once Retire is confirmed", async () => {
    const { calls } = await openTask("/parent/tasks/spelling/spelling", (call) =>
      call.path === "/parent/api/tasks/spelling/spelling/retire" ? { body: { message: "Retired rope. Its recordings are in the attic.", warnings: [] } } : undefined,
    );
    const row = screen.getByRole("combobox", { name: "Pool for rope" }).closest("tr") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Retire" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Retire rope? Its recordings move to the attic.");
    await userEvent.click(within(dialog).getByRole("button", { name: "Retire" }));
    expect(await screen.findByText("Retired rope. Its recordings are in the attic.")).toBeInTheDocument();
    expect(saves(calls)).toEqual([{ path: "/parent/api/tasks/spelling/spelling/retire", search: "", method: "POST", body: { word: "rope" } }]);
  });

  it("plays the word and its sentence from the parent data address", async () => {
    const played: string[] = [];
    vi.spyOn(window.HTMLMediaElement.prototype, "play").mockImplementation(function (this: HTMLMediaElement) {
      played.push(this.src);
      return Promise.resolve();
    });
    await openTask("/parent/tasks/spelling/spelling");
    await userEvent.click(screen.getByRole("button", { name: "rope" }));
    await userEvent.click(screen.getByRole("button", { name: "Play the sentence for rope" }));
    expect(played.map((src) => new URL(src).pathname)).toEqual([
      "/parent/api/tasks/spelling/spelling/audio/current/rope.wav",
      "/parent/api/tasks/spelling/spelling/audio/current/rope.sentence.wav",
    ]);
    expect(screen.getByRole("combobox", { name: "Pool for cat" }).closest("tr")).toHaveTextContent("No");
  });
});
