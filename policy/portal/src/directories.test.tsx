import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DIRECTORIES, SPELLING, WEEK, fakeService, renderPortal, shown, type Call, type Reply } from "./test/portal";

const TASK_API = "/parent/api/tasks/spelling/spelling";
const WEEK_API = `${TASK_API}/week`;
const MADE = { message: "Made spelling/year-4. It is empty until words are added.", directory: "year-4", folders: [...SPELLING.spelling.folders, "year-4"] };
const BROKEN = "This save would leave the policy unable to load, so nothing was saved.";
const NEW_WORDS = [
  { key: "lion", word: "lion", pool: "current", clip: "lion.wav", sentence: null },
  { key: "newt", word: "newt", pool: "revision", clip: "newt.wav", sentence: null },
];

type Spelling = typeof SPELLING.spelling;

function withSpelling(change: Partial<Spelling>) {
  return { ...SPELLING, spelling: { ...SPELLING.spelling, ...change } };
}

async function openTask(handler?: (call: Call) => Reply | undefined, page: unknown = SPELLING) {
  const calls = fakeService((call) => handler?.(call) ?? (call.path === TASK_API && call.method === "GET" ? { body: page } : undefined));
  const view = renderPortal("/parent/tasks/spelling/spelling");
  await screen.findByRole("heading", { name: "spelling" });
  return { calls, ...view };
}

function pullDown(label: string): HTMLElement {
  return screen.getByRole("button", { name: new RegExp(`^${label} `) });
}

async function choose(label: string, option: string) {
  await userEvent.click(pullDown(label));
  await userEvent.click(within(screen.getByRole("listbox", { name: label })).getByRole("option", { name: option }));
}

function posts(calls: Call[], path: string) {
  return calls.filter((call) => call.method === "POST" && call.path === path);
}

describe("the directory pull-downs", () => {
  it("show each directory relative to the spelling directory and list every one in name order, then New directory…", async () => {
    await openTask();
    expect(pullDown("Current Pool Directory")).toHaveTextContent("current");
    expect(pullDown("Attic Directory")).toHaveTextContent("attic");
    await userEvent.click(pullDown("Revision Pool Directory"));
    const list = screen.getByRole("listbox", { name: "Revision Pool Directory" });
    expect(list).toHaveFocus();
    expect(within(list).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "alphabet",
      "attic",
      "current",
      "revision",
      "year-3",
      "year-3/current",
      "New directory…",
    ]);
    expect(within(list).getByRole("option", { name: "revision" })).toHaveAttribute("aria-selected", "true");
  });

  it("mark a directory that is missing, and one outside the spelling directory set by hand", async () => {
    const folders = SPELLING.spelling.folders.filter((folder) => folder !== "attic");
    await openTask(undefined, withSpelling({ folders, directories: { ...DIRECTORIES, current_dir: "words/year-3" } }));
    expect(pullDown("Attic Directory")).toHaveTextContent("attic (missing)");
    expect(pullDown("Current Pool Directory")).toHaveTextContent("words/year-3 (outside spelling)");
    await userEvent.click(pullDown("Current Pool Directory"));
    const options = within(screen.getByRole("listbox")).getAllByRole("option").map((option) => option.textContent);
    expect(options.slice(-2)).toEqual(["words/year-3 (outside spelling)", "New directory…"]);
  });

  it("choose with a click or the keys, closing each time, and mark the change until the saved directory is chosen again", async () => {
    await openTask();
    await choose("Revision Pool Directory", "year-3");
    await waitFor(() => expect(screen.queryByRole("listbox")).not.toBeInTheDocument());
    const button = pullDown("Revision Pool Directory");
    expect(button).toHaveTextContent("year-3");
    expect(button).toHaveAttribute("data-changed");
    expect(button).toHaveFocus();
    expect(screen.getByRole("banner")).toHaveTextContent("Unsaved changes");

    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard("{ArrowUp}{Enter}");
    await waitFor(() => expect(screen.queryByRole("listbox")).not.toBeInTheDocument());
    expect(button).toHaveTextContent("revision");
    expect(button).not.toHaveAttribute("data-changed");
    expect(screen.getByRole("banner")).not.toHaveTextContent("Unsaved changes");

    await userEvent.click(button);
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("listbox")).not.toBeInTheDocument());
    expect(button).toHaveFocus();
  });

  it("block Save when two fields name the same directory, saying so under the second", async () => {
    await openTask();
    await choose("Attic Directory", "current");
    expect(screen.getByText("Current Pool Directory and Attic Directory are the same directory.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("are disabled while a word's pool change is unsaved", async () => {
    await openTask();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Pool for rope" }), "revision");
    expect(pullDown("Current Pool Directory")).toBeDisabled();
    expect(pullDown("Current Pool Directory")).toHaveAttribute("title", "Save the word moves first.");
  });
});

describe("a new directory", () => {
  it("opens a dialog with the name box focused, and Cancel or Escape makes nothing and returns to the pull-down", async () => {
    const { calls } = await openTask();
    await choose("Current Pool Directory", "New directory…");
    const dialog = await screen.findByRole("dialog", { name: "New directory" });
    expect(within(dialog).getByRole("textbox", { name: "Name, under spelling/" })).toHaveFocus();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    await userEvent.keyboard("year-4{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(pullDown("Current Pool Directory")).toHaveFocus();
    expect(pullDown("Current Pool Directory")).toHaveTextContent("current");
    expect(posts(calls, `${TASK_API}/directories`)).toEqual([]);
  });

  it("keeps the dialog open with the name and the reason when the service refuses it", async () => {
    await openTask((call) =>
      call.path === `${TASK_API}/directories` ? { status: 400, body: { error: "`year-3` already exists." } } : undefined,
    );
    await choose("Current Pool Directory", "New directory…");
    await userEvent.keyboard(" Year-3 {Enter}");
    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("`year-3` already exists.");
    expect(within(dialog).getByRole("textbox")).toHaveValue(" Year-3 ");
  });

  it("asks for a sign-in in another tab when the session has ended, and keeps the name", async () => {
    await openTask((call) => (call.path === `${TASK_API}/directories` ? { status: 401, body: { error: "Sign in to see this." } } : undefined));
    await choose("Current Pool Directory", "New directory…");
    await userEvent.keyboard("year-4");
    await userEvent.click(screen.getByRole("button", { name: "OK" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Your session has ended. Sign in again in another tab, then press OK.");
    expect(screen.getByRole("textbox", { name: "Name, under spelling/" })).toHaveValue("year-4");
  });

  it("chooses the new directory as an unsaved edit, and every pull-down lists it", async () => {
    const { calls } = await openTask((call) => (call.path === `${TASK_API}/directories` ? { body: MADE } : undefined));
    await choose("Revision Pool Directory", "New directory…");
    await userEvent.keyboard("year-4");
    await userEvent.click(screen.getByRole("button", { name: "OK" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(posts(calls, `${TASK_API}/directories`)[0].body).toEqual({ name: "year-4" });
    expect(pullDown("Revision Pool Directory")).toHaveTextContent("year-4");
    expect(screen.getByRole("banner")).toHaveTextContent("Unsaved changes");
    expect(screen.getByRole("status")).toHaveTextContent("Made spelling/year-4.");
    await userEvent.click(pullDown("Attic Directory"));
    expect(within(screen.getByRole("listbox")).getByRole("option", { name: "year-4" })).toBeInTheDocument();
  });
});

describe("saving the directories", () => {
  it("replaces the word list until the change is saved, and sends only the changed fields", async () => {
    const { calls } = await openTask((call) => (call.method === "POST" ? { body: { message: "Saved spelling.", warnings: [] } } : undefined));
    await choose("Current Pool Directory", "year-3/current");
    expect(screen.getByText("Save to see the words in the new directories.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    await userEvent.keyboard("{Control>}s{/Control}");
    await waitFor(() => expect(posts(calls, TASK_API)).toHaveLength(1));
    expect(posts(calls, TASK_API)[0].body).toMatchObject({ directories: { current_dir: "spelling/year-3/current" }, moves: {} });
  });

  it("lists the words in refused directories, says to add words from the Words menu, and saves a pool change with them", async () => {
    let refusals = 0;
    const { calls } = await openTask((call) => {
      if (call.path !== TASK_API || call.method !== "POST") return undefined;
      refusals += 1;
      if (refusals > 1) return { body: { message: "Saved spelling.", warnings: [] } };
      return { status: 400, body: { error: BROKEN, errors: ["revision_required: is 1, but revision_dir has only 0 words"], spelling: { words: NEW_WORDS, problems: [] } } };
    });
    await choose("Current Pool Directory", "year-3/current");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    const status = screen.getByRole("status");
    expect(await within(status).findByText("revision_required: is 1, but revision_dir has only 0 words")).toBeInTheDocument();
    expect(status).toHaveTextContent("Add words to the new directories from the Words menu. Its Apply saves the directories with the words.");
    expect(pullDown("Current Pool Directory")).toHaveTextContent("year-3/current");
    const row = screen.getByRole("combobox", { name: "Pool for lion" }).closest("tr") as HTMLElement;
    expect(within(row).getByRole("button", { name: "Retire" })).toBeDisabled();
    expect(within(row).getByRole("button", { name: "Re-record word for lion" })).toHaveAttribute("title", "Save the directory change first.");

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Pool for lion" }), "revision");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(posts(calls, TASK_API)).toHaveLength(2));
    expect(posts(calls, TASK_API)[1].body).toMatchObject({ directories: { current_dir: "spelling/year-3/current" }, moves: { lion: "revision" } });
  });
});

describe("the Words menu", () => {
  it("opens a menu of three links, carrying unsaved directories, that the arrow keys move between", async () => {
    await openTask();
    await choose("Revision Pool Directory", "year-3");
    await userEvent.click(screen.getByRole("button", { name: "Words" }));
    const links = within(screen.getByRole("menu", { name: "Words" })).getAllByRole("menuitem");
    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["Add to Current", "/parent/tasks/spelling/spelling/words/add-current?revision_dir=spelling%2Fyear-3"],
      ["Add to Revision", "/parent/tasks/spelling/spelling/words/add-revision?revision_dir=spelling%2Fyear-3"],
      ["Replace Current", "/parent/tasks/spelling/spelling/words/replace-current?revision_dir=spelling%2Fyear-3"],
    ]);
    expect(links[0]).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(links[1]).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Words" })).toHaveFocus();
  });

  it("takes unsaved directories to the setup without asking, but asks when other changes are unsaved too", async () => {
    const { router } = await openTask();
    await choose("Revision Pool Directory", "year-3");
    await userEvent.type(screen.getByRole("textbox", { name: "Max Passes" }), "2");
    await userEvent.click(screen.getByRole("button", { name: "Words" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Replace Current" }));
    await userEvent.click(within(await screen.findByRole("alertdialog", { name: "Leave this page?" })).getByRole("button", { name: "Stay" }));
    await userEvent.clear(screen.getByRole("textbox", { name: "Max Passes" }));
    await userEvent.click(screen.getByRole("button", { name: "Words" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Replace Current" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/tasks/spelling/spelling/words/replace-current?revision_dir=spelling%2Fyear-3"));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("asks before throwing away a setup in another mode, and Keep it leaves the page as it was", async () => {
    const page = withSpelling({ setup: { mode: "replace-current", count: 6 } });
    const { calls, router } = await openTask(
      (call) => (call.path === `${WEEK_API}/cancel` ? { body: { message: "Threw away the new week's setup. The pools have not changed.", warnings: [] } } : undefined),
      page,
    );
    await userEvent.type(screen.getByRole("textbox", { name: "Max Passes" }), "2");
    await userEvent.click(screen.getByRole("button", { name: "Words" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Add to Revision" }));
    let dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Throw away the Replace Current setup in progress, with 6 words, and start Add to Revision?");
    expect(within(dialog).getByRole("button", { name: "Keep it" })).toHaveFocus();
    await userEvent.click(within(dialog).getByRole("button", { name: "Keep it" }));
    expect(shown(router)).toBe("/parent/tasks/spelling/spelling");
    expect(screen.getByRole("textbox", { name: "Max Passes" })).toHaveValue("2");
    expect(posts(calls, `${WEEK_API}/cancel`)).toEqual([]);

    await userEvent.clear(screen.getByRole("textbox", { name: "Max Passes" }));
    await userEvent.click(screen.getByRole("button", { name: "Words" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Add to Revision" }));
    dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Throw away" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/tasks/spelling/spelling/words/add-revision"));
    expect(posts(calls, `${WEEK_API}/cancel`)).toHaveLength(1);
  });

  it("opens the setup in progress in its own mode without asking", async () => {
    const { router } = await openTask(undefined, withSpelling({ setup: { mode: "replace-current", count: 6 } }));
    await userEvent.click(screen.getByRole("button", { name: "Words" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Replace Current" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/tasks/spelling/spelling/words/replace-current"));
  });
});

describe("the setup page", () => {
  const ADD = { ...WEEK, mode: "add-current", setup: null, words: [], needs: [] };

  it("names its mode, asks for its directories, and marks those that differ from the task's", async () => {
    const directories = { ...DIRECTORIES, current_dir: "spelling/year-4/current" };
    const calls = fakeService((call) => {
      if (call.path === WEEK_API && call.method === "GET") return { body: { ...ADD, directories } };
      if (call.path === WEEK_API) return { body: { message: "Saved the week's list of 1 word.", warnings: [] } };
      return undefined;
    });
    renderPortal("/parent/tasks/spelling/spelling/words/add-current?current_dir=spelling%2Fyear-4%2Fcurrent");
    expect(await screen.findByRole("heading", { name: "Add to Current" })).toBeInTheDocument();
    expect(document.title).toBe("spelling: Add to Current · Daywarden");
    expect(calls.find((call) => call.path === WEEK_API)?.search).toBe("?current_dir=spelling%2Fyear-4%2Fcurrent&mode=add-current");
    const box = screen.getByRole("group", { name: "Directories" });
    expect(within(box).getByText("year-4/current")).toHaveAttribute("data-changed");
    expect(within(box).getByText("revision")).not.toHaveAttribute("data-changed");
    expect(box).toHaveTextContent("Apply also makes the task use these directories.");
    await userEvent.type(screen.getByRole("textbox", { name: /^Words, separated by commas/ }), "lion");
    await userEvent.click(screen.getByRole("button", { name: "Check" }));
    await waitFor(() => expect(posts(calls, WEEK_API)).toHaveLength(1));
    expect(posts(calls, WEEK_API)[0].body).toMatchObject({ mode: "add-current", directories: { current_dir: "spelling/year-4/current" }, add: "lion" });
  });

  it("for a task not written yet, has no Targets and goes back to the New task page with its name, type, and directories", async () => {
    const directories = { ...DIRECTORIES, current_dir: "spelling/more/current" };
    const unwritten = { ...ADD, name: "More Spelling", version: "", file: "", written: false, directories, words: [{ ...WEEK.words[2] }] };
    const NEW_API = "/parent/api/tasks/spelling/More%20Spelling/week";
    const back = "/parent/new-task?name=More+Spelling&type=spelling&current_dir=spelling%2Fmore%2Fcurrent";
    fakeService((call) => {
      if (call.path === NEW_API && call.method === "GET") return { body: unwritten };
      if (call.path === `${NEW_API}/apply`) return { body: { message: "Added 1 word to current. Save the new task to use them.", warnings: [] } };
      if (call.path === "/parent/api/new-task/check") return { body: { ...SPELLING, name: "More Spelling", version: "", groups: [] } };
      if (call.path === "/parent/api/new-task") return { body: { types: ["spelling"], clients: SPELLING.clients, fields: SPELLING.fields, today: SPELLING.today } };
      return undefined;
    });
    const { router } = renderPortal("/parent/tasks/spelling/More%20Spelling/words/add-current?current_dir=spelling%2Fmore%2Fcurrent");
    expect(await screen.findByRole("heading", { name: "Add to Current" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Targets" })).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Directories" })).toHaveTextContent("The task is not written yet.");
    expect(within(screen.getByRole("navigation", { name: "Where you are" })).getByRole("link", { name: "More Spelling" })).toHaveAttribute("href", back);
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(shown(router)).toBe(back));
    expect(await screen.findByText("Added 1 word to current. Save the new task to use them.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Current Pool Directory / })).toHaveTextContent("more/current");
  });

  it("asks before throwing away a setup in another mode, and Keep it goes to the spelling page", async () => {
    fakeService((call) => (call.path === WEEK_API && call.method === "GET" ? { body: { ...ADD, setup: { mode: "replace-current", count: 6 } } } : undefined));
    const { router } = renderPortal("/parent/tasks/spelling/spelling/words/add-current");
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Throw away the Replace Current setup in progress, with 6 words, and start Add to Current?");
    expect(screen.queryByRole("button", { name: "Apply" })).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Keep it" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/tasks/spelling/spelling"));
  });

  it("throws the other setup away and opens its own mode with an empty list", async () => {
    let thrown = false;
    const calls = fakeService((call) => {
      if (call.path === `${WEEK_API}/cancel`) {
        thrown = true;
        return { body: { message: "Threw away the new week's setup. The pools have not changed.", warnings: [] } };
      }
      if (call.path === WEEK_API && call.method === "GET") return { body: { ...ADD, setup: thrown ? null : { mode: "replace-current", count: 6 } } };
      return undefined;
    });
    const { router } = renderPortal("/parent/tasks/spelling/spelling/words/add-current");
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Throw away" }));
    expect(await screen.findByRole("button", { name: "Apply" })).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(shown(router)).toBe("/parent/tasks/spelling/spelling/words/add-current");
    expect(screen.getByText("No words on the week's list yet. Type them under Add words and press Check.")).toBeInTheDocument();
    expect(posts(calls, `${WEEK_API}/cancel`)).toHaveLength(1);
  });
});
