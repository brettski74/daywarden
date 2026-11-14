import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { SPELLING, TASKS, fakeService, renderPortal, type Call, type Reply } from "./test/portal";

const BLANK = {
  types: ["arithmetic", "parts_of_speech", "skip_counting", "spelling"],
  clients: ["younger", "older", "default"],
  fields: { pass_cooldown: "", failure_cooldown: "", max_skips: "", max_passes: "", available_from: "", due_date: "" },
  today: "2026-11-10",
};

const LOCKED = {
  name: "Café Sums",
  type: "arithmetic",
  file: "/etc/daywarden/tasks.d/cafe_sums.yaml",
  version: "",
  groups: [],
  clients: BLANK.clients,
  fields: BLANK.fields,
  today: BLANK.today,
  arithmetic: {
    settings: { operation: "", max_timeout: "", min_timeout: "", correct_answers_required: "" },
    operations: [{ name: "addition", label: "Addition" }],
    first: [],
    operands: [],
    problems: [],
  },
};

const WRITTEN = { ...LOCKED, version: "v1", groups: ["younger"], fields: { ...BLANK.fields, pass_cooldown: "2" } };

const CREATED = "Created Café Sums in /etc/daywarden/tasks.d/cafe_sums.yaml. The decisions, observations, and autoconfig services are using it.";

/** The service with a new task page, and Café Sums listed and opened once it is written. */
function service(answer?: (call: Call) => Reply | undefined) {
  let written = false;
  const calls = fakeService((call) => {
    const special = answer?.(call);
    if (special) return special;
    if (call.path === "/parent/api/new-task" && call.method === "GET") return { body: BLANK };
    if (call.path === "/parent/api/new-task/check") return { body: LOCKED };
    if (call.path === "/parent/api/new-task") {
      written = true;
      return { body: { message: CREATED, warnings: [], task: { type: "arithmetic", name: "Café Sums" } } };
    }
    if (call.path === "/parent/api/tasks" && written) return { body: { tasks: [{ type: "arithmetic", name: "Café Sums" }, ...TASKS.tasks] } };
    if (call.path === "/parent/api/tasks/arithmetic/Caf%C3%A9%20Sums") return { body: WRITTEN };
    return undefined;
  });
  return calls;
}

async function openNew(answer?: (call: Call) => Reply | undefined) {
  return openNewAt("/parent/new-task", answer);
}

async function openNewAt(address: string, answer?: (call: Call) => Reply | undefined) {
  const calls = service(answer);
  const view = renderPortal(address);
  await screen.findByRole("heading", { name: "New task" });
  return { calls, ...view };
}

async function lockIn() {
  await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "Café Sums");
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Type" }), "arithmetic");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await screen.findByRole("region", { name: "Arithmetic" });
}

const posts = (calls: Call[]) => calls.filter((call) => call.method === "POST");

describe("Create New Task", () => {
  it("heads Task Administration's list, and its page keeps the list open with it marked", async () => {
    await openNew();
    const nav = screen.getByRole("navigation", { name: "Portal pages" });
    expect(within(nav).getByRole("button", { name: "Task Administration" })).toHaveAttribute("aria-expanded", "true");
    const link = within(nav).getByRole("link", { name: "Create New Task" });
    expect(link).toHaveAttribute("href", "/parent/new-task");
    expect(link).toHaveAttribute("aria-current", "page");
    expect(within(nav.querySelector("#task-list") as HTMLElement).getAllByRole("link")[0]).toBe(link);
  });

  it("starts with the name box focused, a type to choose, every other field disabled, and nothing under the divider", async () => {
    await openNew();
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveFocus();
    expect(screen.getByRole("navigation", { name: "Where you are" })).toHaveTextContent("TasksNew task");
    const type = screen.getByRole("combobox", { name: "Type" });
    expect(within(type).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Choose…",
      "arithmetic",
      "parts_of_speech",
      "skip_counting",
      "spelling",
    ]);
    expect(type).toHaveValue("");
    expect(screen.getByRole("textbox", { name: "Pass Cooldown" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Client Groups/ })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Due Date" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Choose Due Date" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Rename" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("says what is wrong with a name under the box once it loses focus, and holds Save until it is valid and a type is chosen", async () => {
    const { calls } = await openNew();
    const name = screen.getByRole("textbox", { name: "Name" });
    const save = screen.getByRole("button", { name: "Save" });
    const type = screen.getByRole("combobox", { name: "Type" });
    expect(screen.queryByText("Give the task a name.")).not.toBeInTheDocument();
    await userEvent.type(name, "x".repeat(41));
    expect(screen.queryByText("A name is at most 40 characters.")).not.toBeInTheDocument();
    expect(name).not.toHaveAttribute("aria-invalid");
    await userEvent.tab();
    expect(screen.getByText("A name is at most 40 characters.")).toBeInTheDocument();
    expect(name).toHaveAttribute("aria-invalid", "true");
    await userEvent.clear(name);
    await userEvent.type(name, "sums ");
    expect(screen.getByText("A name is at most 40 characters.")).toBeInTheDocument();
    await userEvent.click(type);
    expect(screen.getByText("A name has no space at either end.")).toBeInTheDocument();
    await userEvent.type(name, "{Backspace}");
    expect(screen.getByText("A name has no space at either end.")).toBeInTheDocument();
    await userEvent.tab();
    expect(screen.queryByText("A name has no space at either end.")).not.toBeInTheDocument();
    expect(save).toBeDisabled();
    expect(save).toHaveAttribute("title", "Choose the task's type.");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Type" }), "spelling");
    expect(save).toBeEnabled();
    await userEvent.keyboard("{Control>}s{/Control}");
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(posts(calls)[0]).toMatchObject({ path: "/parent/api/new-task/check", body: { name: "sums", type: "spelling" } });
  });

  it("shows why a name is taken and keeps the name and type open", async () => {
    await openNew((call) =>
      call.path === "/parent/api/new-task/check" ? { status: 400, body: { error: "A spelling task named spelling already exists." } } : undefined,
    );
    await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "Spelling");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Type" }), "spelling");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await within(screen.getByRole("status")).findByText("A spelling task named spelling already exists.")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Name" })).not.toHaveAttribute("readonly");
    expect(screen.getByRole("combobox", { name: "Type" })).toBeEnabled();
  });

  it("locks in the name and type, opens the type's section, and has unsaved changes from then on", async () => {
    await openNew();
    await lockIn();
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveAttribute("readonly");
    expect(screen.getByRole("combobox", { name: "Type" })).toBeDisabled();
    const cooldown = screen.getByRole("textbox", { name: "Pass Cooldown" });
    expect(cooldown).toBeEnabled();
    expect(cooldown).toHaveValue("");
    expect(cooldown).toHaveAttribute("placeholder", "1");
    expect(screen.getByText("Add a number.")).toBeInTheDocument();
    expect(screen.getByRole("banner")).toHaveTextContent("Unsaved changes");

    await userEvent.click(screen.getByRole("link", { name: "Attempts" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Leave this page?" });
    expect(within(dialog).getByRole("button", { name: "Stay" })).toHaveFocus();
  });

  it("writes the task with the next save and opens its page, listed in the sidebar", async () => {
    const { calls, router } = await openNew();
    await lockIn();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    const operands = screen.getByRole("table", { name: "Operands" }).closest(".number-list") as HTMLElement;
    await userEvent.click(within(operands).getByRole("button", { name: "Add row" }));
    await userEvent.keyboard("7");
    expect(screen.getByText("Max Timeout is required.")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Operation" }), "addition");
    for (const [name, text] of [["Max Timeout", "10s"], ["Min Timeout", "4s"], ["Correct Answers Required", "3"]]) {
      await userEvent.type(screen.getByRole("textbox", { name }), text);
    }
    await userEvent.type(screen.getByRole("textbox", { name: "Pass Cooldown" }), "2");
    await userEvent.click(screen.getByRole("button", { name: /^Client Groups/ }));
    await userEvent.click(screen.getByRole("option", { name: "younger" }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/parent/tasks/arithmetic/Caf%C3%A9%20Sums"));
    // The task page loads after the sidebar's list is fetched again, which is slow under a full test run.
    expect(await screen.findByRole("heading", { name: "Café Sums" }, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(CREATED);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    const created = posts(calls).find((call) => call.path === "/parent/api/new-task");
    expect(created?.body).toMatchObject({ type: "arithmetic", name: "Café Sums", fields: { pass_cooldown: "2" }, groups: ["younger"] });
    const nav = screen.getByRole("navigation", { name: "Portal pages" });
    expect(within(nav).getByRole("link", { name: "Café Sums" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Rename" })).toBeInTheDocument();
  });

  it("keeps a new spelling task's recordings and Retire for after it is written, and plays from the default pools", async () => {
    await openNew((call) =>
      call.path === "/parent/api/new-task/check" ? { body: { ...SPELLING, name: "words", version: "", groups: [] } } : undefined,
    );
    await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "words");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Type" }), "spelling");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByRole("region", { name: "Spelling" });
    expect(screen.getAllByRole("button", { name: "Retire" })[0]).toBeDisabled();
    expect(screen.getByRole("button", { name: "Re-record word for rope" })).toHaveAttribute("title", "Save the new task first.");
  });

  it("offers the Words menu once the name and type are locked in, carrying the name, type, and new directories", async () => {
    await openNew((call) =>
      call.path === "/parent/api/new-task/check" ? { body: { ...SPELLING, name: "More Spelling", version: "", groups: [] } } : undefined,
    );
    expect(screen.queryByRole("button", { name: "Words" })).not.toBeInTheDocument();
    await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "More Spelling");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Type" }), "spelling");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await userEvent.click(await screen.findByRole("button", { name: /^Current Pool Directory / }));
    await userEvent.click(screen.getByRole("option", { name: "year-3/current" }));
    await userEvent.click(screen.getByRole("button", { name: "Words" }));
    expect(screen.getByRole("menuitem", { name: "Add to Current" })).toHaveAttribute(
      "href",
      "/parent/tasks/spelling/More%20Spelling/words/add-current?current_dir=spelling%2Fyear-3%2Fcurrent",
    );
  });

  it("locks in the name and type again, and chooses the directories again, from its address", async () => {
    const { calls } = await openNewAt("/parent/new-task?name=More+Spelling&type=spelling&current_dir=spelling%2Fyear-3", (call) =>
      call.path === "/parent/api/new-task/check" ? { body: { ...SPELLING, name: "More Spelling", version: "", groups: [] } } : undefined,
    );
    expect(posts(calls)[0]).toMatchObject({ path: "/parent/api/new-task/check", body: { name: "More Spelling", type: "spelling" } });
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue("More Spelling");
    const current = screen.getByRole("button", { name: /^Current Pool Directory / });
    expect(current).toHaveTextContent("year-3");
    expect(current).toHaveAttribute("data-changed");
    expect(screen.getByRole("button", { name: "Words" })).toBeInTheDocument();
  });

  it("makes a new spelling task's new directory at the new task's own address", async () => {
    const { calls } = await openNew((call) => {
      if (call.path === "/parent/api/new-task/check") return { body: { ...SPELLING, name: "words", version: "", groups: [] } };
      if (call.path === "/parent/api/new-task/directories") return { body: { message: "Made spelling/year-4.", directory: "year-4", folders: ["year-4"] } };
      return undefined;
    });
    await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "words");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Type" }), "spelling");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await userEvent.click(await screen.findByRole("button", { name: /^Current Pool Directory / }));
    await userEvent.click(screen.getByRole("option", { name: "New directory…" }));
    await userEvent.keyboard("year-4{Enter}");
    await waitFor(() => expect(screen.getByRole("button", { name: /^Current Pool Directory / })).toHaveTextContent("year-4"));
    expect(posts(calls).map((call) => call.path)).toContain("/parent/api/new-task/directories");
  });
});

async function openSpelling(answer?: (call: Call) => Reply | undefined) {
  const calls = fakeService(answer);
  const view = renderPortal("/parent/tasks/spelling/spelling");
  await screen.findByRole("heading", { name: "spelling" });
  return { calls, ...view };
}

describe("Rename", () => {
  it("sits beside Save and is held while the page has unsaved changes", async () => {
    await openSpelling();
    const rename = screen.getByRole("button", { name: "Rename" });
    expect(rename).toBeEnabled();
    await userEvent.type(screen.getByRole("textbox", { name: "Max Passes" }), "2");
    expect(rename).toBeDisabled();
    expect(rename).toHaveAttribute("title", "Save the changes on this page first.");
  });

  it("opens the name with its text selected and disables everything else until it is cancelled", async () => {
    await openSpelling();
    const name = screen.getByRole("textbox", { name: "Name" });
    expect(name).toHaveAttribute("readonly");
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    expect(name).not.toHaveAttribute("readonly");
    expect(name).toHaveFocus();
    expect([name as HTMLInputElement].map((box) => box.value.slice(box.selectionStart ?? 0, box.selectionEnd ?? 0))).toEqual(["spelling"]);
    expect(screen.getByRole("textbox", { name: "Max Passes" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Timeout" })).toBeDisabled();
    expect(screen.getAllByRole("button", { name: "Retire" })[0]).toBeDisabled();
    expect(screen.getByRole("button", { name: "Re-record word for rope" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Current Pool Directory / })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

    await userEvent.keyboard("words");
    expect(screen.getByRole("banner")).toHaveTextContent("Unsaved changes");
    await userEvent.click(screen.getByRole("button", { name: "Cancel rename" }));
    expect(name).toHaveValue("spelling");
    expect(screen.getByRole("textbox", { name: "Max Passes" })).toBeEnabled();

    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    await userEvent.keyboard("words{Escape}");
    expect(name).toHaveValue("spelling");
    expect(screen.getByRole("button", { name: "Rename" })).toBeInTheDocument();
  });

  it("asks before leaving with a changed name", async () => {
    await openSpelling();
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    await userEvent.keyboard("words");
    await userEvent.click(screen.getByRole("link", { name: "Attempts" }));
    expect(await screen.findByRole("alertdialog", { name: "Leave this page?" })).toBeInTheDocument();
  });

  it("saves the new name and moves to its address with the outcome in the status bar", async () => {
    const message = "Renamed spelling to Week 3. The decisions, observations, and autoconfig services are using it.";
    const { calls, router } = await openSpelling((call) => {
      if (call.path === "/parent/api/tasks/spelling/spelling/rename") return { body: { message, warnings: [], task: { type: "spelling", name: "Week 3" } } };
      if (call.path === "/parent/api/tasks/spelling/Week%203") return { body: { ...SPELLING, name: "Week 3" } };
      return undefined;
    });
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    await userEvent.keyboard("Week 3/");
    const slash = "A name cannot hold a /, because the task's address could not.";
    expect(screen.queryByText(slash)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.keyboard("{Control>}s{/Control}");
    expect(within(screen.getByRole("main")).getByText(slash)).toBeInTheDocument();
    await userEvent.keyboard("{Backspace}{Control>}s{/Control}");

    await waitFor(() => expect(router.state.location.pathname).toBe("/parent/tasks/spelling/Week%203"));
    expect(await screen.findByRole("heading", { name: "Week 3" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(message);
    expect(posts(calls).find((call) => call.path.endsWith("/rename"))?.body).toEqual({ name: "Week 3", version: "v1" });
    expect(calls.filter((call) => call.method === "GET" && call.path === "/parent/api/tasks/spelling/spelling")).toHaveLength(1);
  });

  it("shows why a rename was refused and keeps the name open", async () => {
    await openSpelling((call) =>
      call.path.endsWith("/rename") ? { status: 400, body: { error: "A spelling task named words already exists." } } : undefined,
    );
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    await userEvent.keyboard("words{Enter}");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await within(screen.getByRole("status")).findByText("A spelling task named words already exists.")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue("words");
    expect(screen.getByRole("button", { name: "Cancel rename" })).toBeEnabled();
  });
});
