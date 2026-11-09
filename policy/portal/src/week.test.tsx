import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { WEEK, fakeService, renderPortal, shown, type Call, type Reply } from "./test/portal";
import { media, useFakeMedia } from "./test/recorder";

const TAKE = "TakeTakeTakeTake";
const WEEK_API = "/parent/api/tasks/spelling/week";
type Week = typeof WEEK;

useFakeMedia();

function clips(count: number) {
  return Array.from({ length: count }, (_, index) => ({ id: `aaaaaa-${index + 1}`, start: index * 1000, ms: 600 }));
}

/** The week page over a fake service. ``answer`` answers the page's POSTs; the list is ``week`` until it is changed. */
async function openWeek({ week = WEEK as Week, answer, found = 5 }: { week?: Week; answer?: (call: Call) => Reply | undefined; found?: number } = {}) {
  let shownWeek = week;
  let fetched = 0;
  const calls = fakeService((call) => {
    if (call.method === "POST") {
      const answered = answer?.(call);
      if (answered) return answered;
    }
    if (call.path === WEEK_API && call.method === "GET") {
      fetched += 1;
      return { body: shownWeek };
    }
    if (call.path === "/parent/api/recordings") return { body: { take: TAKE } };
    if (call.path === `/parent/api/recordings/${TAKE}/cut`) return { body: { take: TAKE, clips: clips(found), ignored: 0, loudness: "" } };
    if (call.path === `${WEEK_API}/recordings`) return { body: { message: "Kept 2 clips for the new week. They go into the pools on Apply.", warnings: [] } };
    return undefined;
  });
  const view = renderPortal("/parent/tasks/spelling/week");
  await screen.findByRole("heading", { name: "New week's words" });
  return { calls, fetches: () => fetched, change: (next: Week) => (shownWeek = next), ...view };
}

function posts(calls: Call[], path: string) {
  return calls.filter((call) => call.method === "POST" && call.path === path);
}

function crumb(): HTMLElement {
  return within(screen.getByRole("navigation", { name: "Where you are" })).getByRole("link", { name: "spelling" });
}

function row(key: string): HTMLElement {
  return screen.getByRole("textbox", { name: `Sentence for ${key}` }).closest("tr") as HTMLElement;
}

async function startRecording(button: string) {
  await userEvent.click(screen.getByRole("button", { name: button }));
  const dialog = await screen.findByRole("dialog");
  await within(dialog).findByText("Press any key to start recording.");
  return dialog;
}

async function recordTake(dialog: HTMLElement) {
  await userEvent.keyboard("a");
  await within(dialog).findByText(/^Recording 0:00\./);
  await userEvent.keyboard("{Enter}");
  await within(dialog).findByText(/^Playing: /);
}

describe("opening the new week's words", () => {
  it("is a link in the spelling page's context bar to its own address", async () => {
    fakeService();
    const { router } = renderPortal("/parent/tasks/spelling");
    const link = await screen.findByRole("link", { name: "New week's words" });
    expect(link).toHaveAttribute("href", "/parent/tasks/spelling/week");
    await userEvent.click(link);
    expect(await screen.findByRole("heading", { name: "New week's words" })).toBeInTheDocument();
    expect(shown(router)).toBe("/parent/tasks/spelling/week");
    expect(crumb()).toHaveAttribute("href", "/parent/tasks/spelling");
  });

  it("lists each word with where it is now, its word and sentence clips, and its sentence text", async () => {
    await openWeek();
    const shownRows = screen.getAllByRole("row").slice(1).map((each) => within(each).getAllByRole("cell").slice(1, 4).map((cell) => cell.textContent));
    expect(shownRows).toEqual([
      ["New", "No", "No"],
      ["New", "No", "Play new"],
      ["Current", "Yes", "No"],
      ["Revision", "Yes", "Play"],
      ["Attic", "Yes", "No"],
    ]);
    expect(screen.getByRole("textbox", { name: "Sentence for frog" })).toHaveValue("The frog jumped.");
    expect(screen.getByRole("status")).toHaveTextContent("Week's list: 5 words, 2 new, 1 current, 1 revision, 1 attic.");
  });

  it("plays a kept clip from the setup and an existing clip from its pool", async () => {
    await openWeek();
    await userEvent.click(screen.getByRole("button", { name: "Play the sentence for toad" }));
    await userEvent.click(screen.getByRole("button", { name: "Play the sentence for fish" }));
    await userEvent.click(screen.getByRole("button", { name: "rope" }));
    expect(media.played).toEqual([
      `${WEEK_API}/clips/00c0ffee.opus`,
      "/parent/api/tasks/spelling/audio/revision/fish.sentence.wav",
      "/parent/api/tasks/spelling/audio/current/rope.wav",
    ]);
  });
});

describe("entering and editing the list", () => {
  it("sends the typed words and the list with Check, and shows each refused line", async () => {
    const errors = ['Line 1, "rope2": use only the letters a to z, - and \', with an optional .<n> such as read.1.', 'Line 2, "Frog": frog is already on the list.'];
    const { calls } = await openWeek({
      answer: (call) => (call.path === WEEK_API ? { status: 400, body: { error: "Some of the words are not allowed, so the list was not saved.", errors } } : undefined),
    });
    expect(screen.getByRole("button", { name: "Check" })).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox", { name: /^Words, separated by commas/ }), "rope2{Enter}Frog");
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Check" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Some of the words are not allowed"));
    for (const error of errors) expect(within(screen.getByRole("status")).getByText(error)).toBeInTheDocument();
    const [sent] = posts(calls, WEEK_API);
    expect(sent.body).toMatchObject({ add: "rope2\nFrog" });
    expect((sent.body as { rows: unknown[] }).rows).toHaveLength(5);
  });

  it("saves an edited word and sentence with Ctrl+S, naming the key each row was saved as", async () => {
    const { calls } = await openWeek({ answer: (call) => (call.path === WEEK_API ? { body: { message: "Saved the week's list of 4 words.", warnings: [] } } : undefined) });
    await userEvent.click(screen.getByRole("button", { name: "Change rope" }));
    const key = screen.getByRole("textbox", { name: "Word in place of rope" });
    await userEvent.clear(key);
    await userEvent.type(key, "rope.1");
    expect(within(row("rope")).getAllByRole("cell")[1]).toHaveTextContent("Save to check");
    await userEvent.type(screen.getByRole("textbox", { name: "Sentence for owl" }), "An owl hooted.");
    await userEvent.click(screen.getByRole("button", { name: "Remove fish from the week" }));
    expect(screen.queryByRole("textbox", { name: "Sentence for fish" })).not.toBeInTheDocument();
    await userEvent.keyboard("{Control>}s{/Control}");
    await waitFor(() => expect(posts(calls, WEEK_API)).toHaveLength(1));
    expect(posts(calls, WEEK_API)[0].body).toEqual({
      rows: [
        { from: "frog", key: "frog", sentence: "The frog jumped." },
        { from: "toad", key: "toad", sentence: "A toad sat." },
        { from: "rope", key: "rope.1", sentence: "Pull the rope." },
        { from: "owl", key: "owl", sentence: "An owl hooted." },
      ],
      add: "",
    });
    expect(await screen.findByText("Saved the week's list of 4 words.")).toBeInTheDocument();
  });

  it("disables recording and Apply while the list has unsaved changes", async () => {
    await openWeek({ week: { ...WEEK, needs: [] } });
    expect(screen.getByRole("button", { name: "Apply" })).toBeEnabled();
    await userEvent.type(screen.getByRole("textbox", { name: "Sentence for owl" }), "An owl hooted.");
    for (const name of ["Record all", "Record missing", "Re-record word for owl", "Apply"]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
    expect(screen.getByRole("button", { name: "Record all" })).toHaveAttribute("title", "Save the list before recording.");
  });

  it("asks which meaning a plain word is when the pools have numbered ones, and uses the ticked ones", async () => {
    const read = {
      ...WEEK.words[0],
      key: "read",
      word: "read",
      sentence: "",
      choices: [
        { key: "read.1", pool: "revision" },
        { key: "read.2", pool: "attic" },
      ],
      new_key: "read.3",
    };
    const { calls } = await openWeek({ week: { ...WEEK, words: [read], needs: ["read"], ambiguous: ["read"] } as unknown as Week });
    expect(screen.getByText("Apply is not ready. Choose which meaning of read belongs to the week.")).toBeInTheDocument();
    const choices = screen.getByRole("group", { name: "The pools have more than one read. Which belong to this week?" });
    expect(within(choices).getAllByRole("checkbox").map((box) => box.parentElement?.textContent)).toEqual([
      "read.1 (Revision)",
      "read.2 (Attic)",
      "read.3 (a new meaning)",
    ]);
    await userEvent.click(within(choices).getByRole("checkbox", { name: "read.3 (a new meaning)" }));
    await userEvent.click(within(choices).getByRole("checkbox", { name: "read.1 (Revision)" }));
    await userEvent.click(within(choices).getByRole("button", { name: "Use these" }));
    expect(screen.getByRole("textbox", { name: "Word in place of read" })).toHaveValue("read.1");
    expect(screen.getByRole("textbox", { name: /^Words, separated by commas/ })).toHaveValue("read.3");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(posts(calls, WEEK_API)).toHaveLength(1));
    expect(posts(calls, WEEK_API)[0].body).toMatchObject({ rows: [{ from: "read", key: "read.1", sentence: "" }], add: "read.3" });
  });

  it("asks before leaving with unsaved changes, with Stay as the default", async () => {
    const { router } = await openWeek();
    await userEvent.type(screen.getByRole("textbox", { name: /^Words, separated by commas/ }), "newt");
    await userEvent.click(crumb());
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByRole("button", { name: "Stay" })).toHaveFocus();
    await userEvent.click(within(dialog).getByRole("button", { name: "Stay" }));
    expect(shown(router)).toBe("/parent/tasks/spelling/week");
    expect(screen.getByRole("textbox", { name: /^Words, separated by commas/ })).toHaveValue("newt");
  });
});

describe("recording the week", () => {
  it("prompts every word, each followed by its typed sentence, with Record all", async () => {
    await openWeek();
    const dialog = await startRecording("Record all");
    expect(within(dialog).getByRole("heading")).toHaveTextContent("Record the week's words");
    expect(within(dialog).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "frog",
      "The frog jumped.",
      "toad",
      "A toad sat.",
      "rope",
      "Pull the rope.",
      "fish",
      "A fish swims.",
      "owl",
    ]);
  });

  it("prompts only the pieces with no clip with Record missing", async () => {
    await openWeek();
    const dialog = await startRecording("Record missing");
    expect(within(dialog).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["frog", "The frog jumped.", "toad", "Pull the rope."]);
  });

  it("ignores every key but Enter while recording", async () => {
    await openWeek();
    const dialog = await startRecording("Record missing");
    await userEvent.keyboard("a");
    await within(dialog).findByText(/^Recording 0:00\./);
    await userEvent.keyboard("kjdmrb{Escape} ");
    expect(within(dialog).getByText(/^Recording 0:00\./)).toBeInTheDocument();
    await userEvent.keyboard("{Enter}");
    expect(await within(dialog).findByText("Playing: frog (word)")).toBeInTheDocument();
  });

  it("steps through the lines and clips with Junk, Keep, Discard, and Missing, and keeps the clips with the setup", async () => {
    const { calls, fetches } = await openWeek();
    const dialog = await startRecording("Record missing");
    await recordTake(dialog);
    expect(within(dialog).getByText("1 of 4: frog (word). Clip 1 of 5.")).toBeInTheDocument();
    await userEvent.keyboard("j");
    expect(within(dialog).getByText("1 of 4: frog (word). Clip 2 of 5.")).toBeInTheDocument();
    await userEvent.keyboard("k");
    expect(within(dialog).getByText("2 of 4: frog (sentence). Clip 3 of 5.")).toBeInTheDocument();
    expect(within(dialog).getByText("The frog jumped.", { selector: ".record-expected" })).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Discard" }));
    expect(within(dialog).getByText("3 of 4: toad (word). Clip 4 of 5.")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Missing" }));
    expect(within(dialog).getByText("4 of 4: rope (sentence). Clip 4 of 5.")).toBeInTheDocument();
    await userEvent.keyboard("k");
    expect(within(dialog).getByText("1 clip was left over and will be ignored.")).toBeInTheDocument();
    expect(within(dialog).getByRole("row", { name: "frog (sentence) Discarded" })).toBeInTheDocument();
    expect(within(dialog).getByRole("row", { name: "toad (word) Missing" })).toBeInTheDocument();
    expect(media.played).toEqual([1, 2, 3, 4, 4].map((number) => `/parent/api/recordings/${TAKE}/aaaaaa-${number}.opus`));

    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(posts(calls, `${WEEK_API}/recordings`)[0].body).toEqual({
      take: TAKE,
      clips: [
        { word: "frog", kind: "word", clip: "aaaaaa-2" },
        { word: "rope", kind: "sentence", clip: "aaaaaa-4" },
      ],
    });
    expect(screen.getByRole("status")).toHaveTextContent("Kept 2 clips for the new week. They go into the pools on Apply.");
    await waitFor(() => expect(fetches()).toBe(2));
  });

  it("re-records one row's word, keeping the clip with the setup", async () => {
    const { calls } = await openWeek({ found: 1 });
    const dialog = await startRecording("Re-record word for frog");
    expect(within(dialog).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["frog"]);
    await recordTake(dialog);
    await userEvent.keyboard("k");
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(posts(calls, `${WEEK_API}/recordings`)).toHaveLength(1));
    expect(posts(calls, `${WEEK_API}/recordings`)[0].body).toEqual({ take: TAKE, clips: [{ word: "frog", kind: "word", clip: "aaaaaa-1" }] });
    expect(posts(calls, "/parent/api/tasks/spelling/recordings")).toEqual([]);
  });

  it("shows Back undoing the last decision during the week's review", async () => {
    await openWeek();
    const dialog = await startRecording("Record missing");
    await recordTake(dialog);
    await userEvent.keyboard("k");
    await userEvent.keyboard("b");
    expect(within(dialog).getByText("1 of 4: frog (word). Clip 1 of 5.")).toBeInTheDocument();
  });
});

describe("applying or cancelling", () => {
  it("keeps Apply disabled and says which words still need a word clip", async () => {
    await openWeek();
    const apply = screen.getByRole("button", { name: "Apply" });
    expect(apply).toBeDisabled();
    expect(apply).toHaveAttribute("title", "These words still need a word clip: frog, toad.");
    expect(screen.getByText("Apply is not ready. These words still need a word clip: frog, toad.")).toBeInTheDocument();
  });

  it("applies when every word has a word clip, then goes to the spelling page and reports what changed", async () => {
    const message = "Applied the new week: 5 words are current, and 1 went to revision.";
    const { calls, router } = await openWeek({
      week: { ...WEEK, needs: [] },
      answer: (call) => (call.path === `${WEEK_API}/apply` ? { body: { message, warnings: [] } } : undefined),
    });
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/tasks/spelling"));
    expect(posts(calls, `${WEEK_API}/apply`)[0].body).toEqual({ version: "v1" });
    expect(await screen.findByRole("heading", { name: "spelling" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(message);
  });

  it("offers to lower a target when Apply is refused for it, and sends the new target with Apply", async () => {
    let refused = true;
    const { calls, router } = await openWeek({
      week: { ...WEEK, needs: [] },
      answer: (call) => {
        if (call.path !== `${WEEK_API}/apply`) return undefined;
        if (refused) {
          refused = false;
          return {
            status: 400,
            body: { error: "This save would leave the policy unable to load, so nothing was saved.", errors: ["spelling: current_required: is 8, but current_dir has only 5 words"] },
          };
        }
        return { body: { message: "Saved spelling. Applied the new week.", warnings: [] } };
      },
    });
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByText("spelling: current_required: is 8, but current_dir has only 5 words")).toBeInTheDocument();
    expect(screen.getByText(/^Change a target here, then press Apply again\./)).toBeInTheDocument();
    const target = screen.getByRole("textbox", { name: "Required Correct (Current Pool)" });
    await userEvent.type(target, "5");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/tasks/spelling"));
    expect(posts(calls, `${WEEK_API}/apply`)[1].body).toEqual({ version: "v1", settings: { current_required: "5", revision_required: "1" } });
  });

  it("asks before cancelling, with keeping it as the default, then throws the setup away", async () => {
    const { calls, router } = await openWeek({
      answer: (call) => (call.path === `${WEEK_API}/cancel` ? { body: { message: "Threw away the new week's setup. The pools have not changed.", warnings: [] } } : undefined),
    });
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    let dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByRole("button", { name: "Keep it" })).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(posts(calls, `${WEEK_API}/cancel`)).toEqual([]);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Throw away" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/tasks/spelling"));
    expect(posts(calls, `${WEEK_API}/cancel`)).toHaveLength(1);
    expect(await screen.findByText("Threw away the new week's setup. The pools have not changed.")).toBeInTheDocument();
  });
});
