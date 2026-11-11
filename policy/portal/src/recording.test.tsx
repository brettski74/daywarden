import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { describe, expect, it, vi } from "vitest";
import { RecordDialog, START_DELAY_MS } from "./components/RecordDialog";
import { SPELLING, fakeService, renderPortal, shown, type Call, type Reply } from "./test/portal";
import { FakeRecorder, media, useFakeMedia } from "./test/recorder";

const TAKE = "TakeTakeTakeTake";

useFakeMedia();

function clips(count: number, mark = "aaaaaa") {
  return Array.from({ length: count }, (_, index) => ({ id: `${mark}-${index + 1}`, start: index * 1000, ms: 600 }));
}

type Answers = {
  upload?: (call: Call) => Reply | undefined;
  cut?: (call: Call) => Reply | undefined;
  keep?: (call: Call) => Reply | undefined;
  found?: number;
};

/** The spelling page with a fake service that takes uploads, cuts them into ``found`` clips, and keeps clips. */
async function openSpelling({ upload, cut, keep, found = 2 }: Answers = {}) {
  let refetched = 0;
  const calls = fakeService((call) => {
    if (call.path === "/parent/api/recordings") return upload?.(call) ?? { body: { take: TAKE } };
    if (call.path === `/parent/api/recordings/${TAKE}/cut`) {
      return cut?.(call) ?? { body: { take: TAKE, clips: clips(found), ignored: 0, loudness: "Loudness -30.0 LUFS, raised 12.0 dB to -18.0 LUFS." } };
    }
    if (call.path === `/parent/api/recordings/${TAKE}/discard`) return { body: { discarded: true } };
    if (call.path === "/parent/api/tasks/spelling/spelling/recordings") return keep?.(call) ?? { body: { message: "Saved the new word recording of rope.", warnings: [] } };
    if (call.path === "/parent/api/tasks/spelling/spelling") {
      refetched += 1;
      return { body: SPELLING };
    }
    return undefined;
  });
  const view = renderPortal("/parent/tasks/spelling/spelling");
  await screen.findByRole("heading", { name: "spelling" });
  return { calls, refetches: () => refetched - 1, ...view };
}

function posts(calls: Call[], path: string) {
  return calls.filter((call) => call.method === "POST" && call.path === path);
}

async function openDialog(label: string) {
  await userEvent.click(screen.getByRole("button", { name: label }));
  const dialog = await screen.findByRole("dialog");
  await within(dialog).findByText("Press any key to start recording.");
  return dialog;
}

/** Start with a key press, wait for the recorder to start after its delay, then stop with Enter. */
async function recordTake(scope: HTMLElement = document.body) {
  await userEvent.keyboard("a");
  await within(scope).findByText(/^Recording 0:00\./);
  await userEvent.keyboard("{Enter}");
}

/** Record a take and wait for the first clip to play. */
async function recordAndReview(dialog: HTMLElement) {
  await recordTake(dialog);
  return within(dialog).findByText(/^Playing: /);
}

async function openAdvanced(dialog: HTMLElement) {
  const toggle = within(dialog).getAllByRole("button", { name: "Advanced" }).find((button) => button.hasAttribute("aria-expanded"))!;
  await userEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
}

describe("the recording buttons on each word", () => {
  it("offers word and sentence, word, and sentence, each naming the word", async () => {
    await openSpelling();
    const row = screen.getByRole("combobox", { name: "Pool for fish" }).closest("tr") as HTMLElement;
    for (const label of ["Re-record word and sentence for fish", "Re-record word for fish", "Re-record sentence for fish"]) {
      expect(within(row).getByRole("button", { name: label })).toHaveAttribute("title", label);
    }
  });

  it("opens a dialog showing a line for each clip to say", async () => {
    await openSpelling();
    const dialog = await openDialog("Re-record word and sentence for rope");
    expect(within(dialog).getByRole("heading")).toHaveTextContent("Re-record word and sentence for rope");
    expect(within(dialog).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["rope", "Sentence for rope"]);
  });
});

describe("recording", () => {
  it("says so when the browser refuses the microphone, and records nothing", async () => {
    media.microphone = () => Promise.reject(new DOMException("denied", "NotAllowedError"));
    const { calls } = await openSpelling();
    await userEvent.click(screen.getByRole("button", { name: "Re-record word for rope" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("The browser was not allowed to use the microphone");
    expect(within(dialog).queryByRole("button", { name: "Start" })).not.toBeInTheDocument();
    await userEvent.keyboard("a");
    expect(FakeRecorder.last).toBeNull();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(posts(calls, "/parent/api/recordings")).toEqual([]);
  });

  it("says so when there is no microphone", async () => {
    media.microphone = () => Promise.reject(new DOMException("none", "NotFoundError"));
    await openSpelling();
    await userEvent.click(screen.getByRole("button", { name: "Re-record word for rope" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No microphone was found, so nothing can be recorded.");
  });

  it("starts half a second after any key, ignores every key but Enter while recording, then uploads the raw take and cuts it", async () => {
    const { calls } = await openSpelling();
    const dialog = await openDialog("Re-record word for rope");
    await userEvent.keyboard("x");
    const pressed = Date.now();
    expect(FakeRecorder.last).toBeNull();
    expect(within(dialog).getByRole("status")).toHaveTextContent("Get ready…");
    await userEvent.keyboard("kj{Enter}{Escape}");
    expect(screen.getByRole("dialog")).toBe(dialog);
    expect(await within(dialog).findByText("Recording 0:00. Press Enter or Stop when you are done.")).toBeInTheDocument();
    expect(Date.now() - pressed).toBeGreaterThanOrEqual(START_DELAY_MS - 20);
    expect(FakeRecorder.last?.state).toBe("recording");
    await userEvent.keyboard("kjd{Escape}{Control>}s{/Control} ");
    expect(FakeRecorder.last?.state).toBe("recording");
    expect(screen.getByRole("dialog")).toBe(dialog);
    expect(calls.filter((call) => call.method === "POST")).toEqual([]);

    await userEvent.keyboard("{Enter}");
    expect(await within(dialog).findByText("Playing: rope (word)")).toBeInTheDocument();
    const [upload] = posts(calls, "/parent/api/recordings");
    expect(upload.body).toBeInstanceOf(Blob);
    const init = vi.mocked(fetch).mock.calls.find(([address]) => String(address) === "/parent/api/recordings")![1] as RequestInit;
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("audio/webm;codecs=opus");
    expect(posts(calls, `/parent/api/recordings/${TAKE}/cut`)[0].body).toEqual({
      settings: { min_silence: 700, threshold: 35, min_speech: 150, guard: 100, loudness: -18 },
    });
    expect(media.played).toEqual([`/parent/api/recordings/${TAKE}/aaaaaa-1.opus`]);
  });

  it("starts and stops with the buttons too", async () => {
    await openSpelling();
    const dialog = await openDialog("Re-record word for rope");
    await userEvent.click(within(dialog).getByRole("button", { name: "Start" }));
    await userEvent.click(await within(dialog).findByRole("button", { name: "Stop" }));
    expect(await within(dialog).findByText("Playing: rope (word)")).toBeInTheDocument();
  });

  it("says so when the recording cannot start, and stays ready", async () => {
    vi.spyOn(FakeRecorder.prototype, "start").mockImplementation(() => {
      throw new DOMException("There was an error starting the MediaRecorder.", "NotSupportedError");
    });
    await openSpelling();
    const dialog = await openDialog("Re-record word for rope");
    await userEvent.keyboard("a");
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("The recording could not start, so nothing was recorded.");
    expect(within(dialog).getByText("Press any key to start recording.")).toBeInTheDocument();
  });

  it("uploads the take when the dialog runs under StrictMode, as the dev server does", async () => {
    const calls = fakeService((call) => {
      if (call.path === "/parent/api/recordings") return { body: { take: TAKE } };
      if (call.path.endsWith("/cut")) return { body: { take: TAKE, clips: clips(1), ignored: 0, loudness: "" } };
      return undefined;
    });
    render(
      <StrictMode>
        <RecordDialog title="Re-record word for rope" items={[{ key: "rope", kind: "word", line: "rope" }]} onKeep={async () => ""} onClose={() => undefined} />
      </StrictMode>,
    );
    await screen.findByText("Press any key to start recording.");
    await recordTake();
    expect(await screen.findByText("Playing: rope (word)")).toBeInTheDocument();
    expect(posts(calls, "/parent/api/recordings")).toHaveLength(1);
  });

  it("closes on Escape or Cancel before recording and changes nothing", async () => {
    const { calls } = await openSpelling();
    await openDialog("Re-record word for rope");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const dialog = await openDialog("Re-record sentence for rope");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(calls.filter((call) => call.method === "POST")).toEqual([]);
  });
});

describe("reviewing the clips", () => {
  it("keeps the word on Keep and Confirm, and lists the new recording", async () => {
    const { calls, refetches } = await openSpelling({ found: 1 });
    const dialog = await openDialog("Re-record word for rope");
    await recordAndReview(dialog);
    await userEvent.click(within(dialog).getByRole("button", { name: "Keep" }));
    expect(within(dialog).getByRole("row", { name: "rope (word) Kept" })).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(posts(calls, "/parent/api/tasks/spelling/spelling/recordings")[0].body).toEqual({ take: TAKE, word: "rope", clips: { word: "aaaaaa-1" } });
    expect(screen.getByRole("status")).toHaveTextContent("Saved the new word recording of rope.");
    await waitFor(() => expect(refetches()).toBe(1));
  });

  it("plays and labels the word clip, then the sentence clip, and keeps both", async () => {
    const { calls } = await openSpelling({ found: 3 });
    const dialog = await openDialog("Re-record word and sentence for rope");
    await recordAndReview(dialog);
    expect(within(dialog).getByText("Playing: rope (word)")).toBeInTheDocument();
    await userEvent.keyboard("j");
    expect(within(dialog).getByText("Playing: rope (word)")).toBeInTheDocument();
    expect(within(dialog).getByText("1 of 2: rope (word). Clip 2 of 3.")).toBeInTheDocument();
    await userEvent.keyboard("k");
    expect(within(dialog).getByText("Playing: rope (sentence)")).toBeInTheDocument();
    await userEvent.keyboard("k");
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(posts(calls, "/parent/api/tasks/spelling/spelling/recordings")).toHaveLength(1));
    expect(posts(calls, "/parent/api/tasks/spelling/spelling/recordings")[0].body).toMatchObject({ clips: { word: "aaaaaa-2", sentence: "aaaaaa-3" } });
    expect(media.played).toEqual(["aaaaaa-1", "aaaaaa-2", "aaaaaa-3"].map((id) => `/parent/api/recordings/${TAKE}/${id}.opus`));
  });

  it("moves straight to the sentence with the same clip on Missing", async () => {
    const { calls } = await openSpelling({ found: 1 });
    const dialog = await openDialog("Re-record word and sentence for rope");
    await recordAndReview(dialog);
    await userEvent.click(within(dialog).getByRole("button", { name: "Missing" }));
    expect(within(dialog).getByText("Playing: rope (sentence)")).toBeInTheDocument();
    expect(within(dialog).getByText("2 of 2: rope (sentence). Clip 1 of 1.")).toBeInTheDocument();
    await userEvent.keyboard("k");
    expect(within(dialog).getByRole("row", { name: "rope (word) Missing" })).toBeInTheDocument();
    expect(within(dialog).getByRole("row", { name: "rope (sentence) Kept" })).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(posts(calls, "/parent/api/tasks/spelling/spelling/recordings")).toHaveLength(1));
    expect(posts(calls, "/parent/api/tasks/spelling/spelling/recordings")[0].body).toMatchObject({ clips: { sentence: "aaaaaa-1" } });
  });

  it("goes back to the last clip and item, undoing the choice, and replays on R", async () => {
    await openSpelling({ found: 2 });
    const dialog = await openDialog("Re-record word and sentence for rope");
    await recordAndReview(dialog);
    expect(within(dialog).getByRole("button", { name: "Back" })).toBeDisabled();
    await userEvent.keyboard("k");
    await userEvent.click(within(dialog).getByRole("button", { name: "Back" }));
    expect(within(dialog).getByText("Playing: rope (word)")).toBeInTheDocument();
    expect(within(dialog).getByText("1 of 2: rope (word). Clip 1 of 2.")).toBeInTheDocument();
    await userEvent.keyboard("r");
    await userEvent.click(within(dialog).getByRole("button", { name: "Replay" }));
    expect(media.played.filter((path) => path.endsWith("aaaaaa-1.opus"))).toHaveLength(4);
    await userEvent.keyboard("dk");
    expect(within(dialog).getByRole("row", { name: "rope (word) Discarded" })).toBeInTheDocument();
    await userEvent.keyboard("b");
    expect(within(dialog).getByText("Playing: rope (sentence)")).toBeInTheDocument();
    await userEvent.keyboard("m");
    expect(within(dialog).getByRole("row", { name: "rope (sentence) Missing" })).toBeInTheDocument();
  });

  it("writes nothing when nothing is kept, or when Cancel is pressed at the end", async () => {
    const { calls } = await openSpelling({ found: 1 });
    let dialog = await openDialog("Re-record word for rope");
    await recordAndReview(dialog);
    await userEvent.keyboard("d");
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Nothing was kept, so nothing changed.");

    dialog = await openDialog("Re-record word for rope");
    await recordAndReview(dialog);
    await userEvent.keyboard("k");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(posts(calls, "/parent/api/tasks/spelling/spelling/recordings")).toEqual([]);
    expect(posts(calls, `/parent/api/recordings/${TAKE}/discard`)).toHaveLength(2);
  });

  it("says how many clips were left over when the items run out", async () => {
    await openSpelling({ found: 4 });
    const dialog = await openDialog("Re-record word for rope");
    await recordAndReview(dialog);
    await userEvent.keyboard("k");
    expect(within(dialog).getByText("3 clips were left over and will be ignored.")).toBeInTheDocument();
  });

  it("says when no clips were found, and offers Record again and Advanced", async () => {
    const { calls } = await openSpelling({ found: 0 });
    const dialog = await openDialog("Re-record word for rope");
    await recordTake(dialog);
    expect(await within(dialog).findByText(/^No clips were found in the recording\./)).toBeInTheDocument();
    const footer = within(dialog).getByRole("button", { name: "Record again" }).parentElement as HTMLElement;
    await userEvent.click(within(footer).getByRole("button", { name: "Advanced" }));
    expect(within(dialog).getByRole("textbox", { name: "Threshold" })).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Record again" }));
    expect(within(dialog).getByText("Press any key to start recording.")).toBeInTheDocument();
    expect(posts(calls, `/parent/api/recordings/${TAKE}/discard`)).toHaveLength(1);
    expect(posts(calls, "/parent/api/tasks/spelling/spelling/recordings")).toEqual([]);
  });
});

describe("a session that ends while recording", () => {
  it("keeps the take and sends it again only when Upload is pressed", async () => {
    let refused = true;
    const { calls, router } = await openSpelling({
      upload: () => (refused ? { status: 401, body: { error: "Sign in to see this." } } : undefined),
    });
    const dialog = await openDialog("Re-record word for rope");
    await recordTake(dialog);
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Your session has ended. Sign in again in another tab, then press Upload.");
    expect(shown(router)).toBe("/parent/tasks/spelling/spelling");
    expect(posts(calls, "/parent/api/recordings")).toHaveLength(1);

    refused = false;
    await userEvent.click(within(dialog).getByRole("button", { name: "Upload" }));
    expect(await within(dialog).findByText("Playing: rope (word)")).toBeInTheDocument();
    const uploads = posts(calls, "/parent/api/recordings");
    expect(uploads).toHaveLength(2);
    expect(uploads[1].body).toBe(uploads[0].body);
  });

  it("says a take that is too long is too long, and offers to record again", async () => {
    await openSpelling({ upload: () => ({ status: 413, body: { error: "The recording is too long to upload. Record a shorter take." } }) });
    const dialog = await openDialog("Re-record word for rope");
    await recordTake(dialog);
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("The recording is too long to upload.");
    expect(within(dialog).queryByRole("button", { name: "Upload" })).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Record again" })).toBeInTheDocument();
  });

  it("asks for a sign-in in another tab when Confirm is refused, and keeps the review", async () => {
    await openSpelling({ found: 1, keep: () => ({ status: 401, body: { error: "Sign in to see this." } }) });
    const dialog = await openDialog("Re-record word for rope");
    await recordAndReview(dialog);
    await userEvent.keyboard("k");
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Your session has ended. Sign in again in another tab, then press Confirm.");
    expect(within(dialog).getByRole("row", { name: "rope (word) Kept" })).toBeInTheDocument();
  });
});

describe("the Advanced settings", () => {
  async function advanced() {
    const view = await openSpelling({ found: 2 });
    const dialog = await openDialog("Re-record word for rope");
    await openAdvanced(dialog);
    return { dialog, ...view };
  }

  it("is collapsed until opened, at the bin/cut-clips defaults", async () => {
    await openSpelling();
    const dialog = await openDialog("Re-record word for rope");
    expect(within(dialog).queryByRole("textbox", { name: "Threshold" })).not.toBeInTheDocument();
    await openAdvanced(dialog);
    const values = ["Minimum silence", "Threshold", "Minimum speech", "Guard", "Loudness"].map(
      (name) => (within(dialog).getByRole("textbox", { name }) as HTMLInputElement).value,
    );
    expect(values).toEqual(["700", "35", "150", "100", "-18"]);
    expect(within(dialog).queryByRole("button", { name: "Reset all" })).not.toBeInTheDocument();
  });

  it("keeps the threshold slider and its number in step, and lets the number go beyond the slider", async () => {
    const { dialog } = await advanced();
    const slider = within(dialog).getByRole("slider", { name: "Threshold" });
    const number = within(dialog).getByRole("textbox", { name: "Threshold" });
    expect(slider).toHaveAttribute("min", "10");
    expect(slider).toHaveAttribute("max", "80");
    fireEvent.change(slider, { target: { value: "50" } });
    expect(number).toHaveValue("50");
    await userEvent.clear(number);
    await userEvent.type(number, "42");
    expect(slider).toHaveValue("42");
    await userEvent.clear(number);
    await userEvent.type(number, "120");
    expect(slider).toHaveValue("80");
    expect(number).not.toHaveAttribute("aria-invalid");
  });

  it("shows an error for a loudness outside −40 to −10 LUFS and disables Cut until it is fixed", async () => {
    const { dialog } = await advanced();
    await recordAndReview(dialog);
    const cut = within(dialog).getByRole("button", { name: "Cut" });
    expect(cut).toBeEnabled();
    const number = within(dialog).getByRole("textbox", { name: "Loudness" });
    fireEvent.change(within(dialog).getByRole("slider", { name: "Loudness" }), { target: { value: "-30" } });
    expect(number).toHaveValue("-30");
    await userEvent.clear(number);
    await userEvent.type(number, "-5");
    expect(number).toHaveAttribute("aria-invalid", "true");
    expect(within(dialog).getByText("From \u221240 to \u221210 LUFS.")).toBeInTheDocument();
    expect(cut).toBeDisabled();
    await userEvent.type(number, "0");
    expect(number).toHaveValue("-50");
    expect(cut).toBeDisabled();
    await userEvent.clear(number);
    await userEvent.type(number, "-12");
    expect(cut).toBeEnabled();
  });

  it("offers a reset beside a changed field that puts back the slider and number, leaving the others", async () => {
    const { dialog } = await advanced();
    expect(within(dialog).queryByRole("button", { name: "Reset threshold to 35 dB" })).not.toBeInTheDocument();
    fireEvent.change(within(dialog).getByRole("slider", { name: "Threshold" }), { target: { value: "50" } });
    fireEvent.change(within(dialog).getByRole("slider", { name: "Loudness" }), { target: { value: "-25" } });
    const reset = within(dialog).getByRole("button", { name: "Reset threshold to 35 dB" });
    expect(reset).toHaveAttribute("title", "Reset threshold to 35 dB");
    await userEvent.click(reset);
    expect(within(dialog).getByRole("textbox", { name: "Threshold" })).toHaveValue("35");
    expect(within(dialog).getByRole("slider", { name: "Threshold" })).toHaveValue("35");
    expect(within(dialog).queryByRole("button", { name: "Reset threshold to 35 dB" })).not.toBeInTheDocument();
    expect(within(dialog).getByRole("textbox", { name: "Loudness" })).toHaveValue("-25");
    expect(within(dialog).getByRole("button", { name: "Reset loudness to \u221218 LUFS" })).toBeInTheDocument();
  });

  it("resets a slider on a double-click", async () => {
    const { dialog } = await advanced();
    const slider = within(dialog).getByRole("slider", { name: "Loudness" });
    fireEvent.change(slider, { target: { value: "-30" } });
    await userEvent.dblClick(slider);
    expect(slider).toHaveValue("-18");
    expect(within(dialog).getByRole("textbox", { name: "Loudness" })).toHaveValue("-18");
  });

  it("resets the focused field on Alt+R, and every field on Alt+Shift+R or Reset all", async () => {
    const { dialog } = await advanced();
    const silence = within(dialog).getByRole("textbox", { name: "Minimum silence" });
    const guard = within(dialog).getByRole("textbox", { name: "Guard" });
    await userEvent.clear(silence);
    await userEvent.type(silence, "900");
    await userEvent.clear(guard);
    await userEvent.type(guard, "50");
    await userEvent.click(silence);
    await userEvent.keyboard("{Alt>}r{/Alt}");
    expect(silence).toHaveValue("700");
    expect(guard).toHaveValue("50");

    fireEvent.change(within(dialog).getByRole("slider", { name: "Threshold" }), { target: { value: "20" } });
    await userEvent.click(guard);
    await userEvent.keyboard("{Alt>}{Shift>}R{/Shift}{/Alt}");
    expect(guard).toHaveValue("100");
    expect(within(dialog).getByRole("textbox", { name: "Threshold" })).toHaveValue("35");
    expect(within(dialog).queryByRole("button", { name: "Reset all" })).not.toBeInTheDocument();

    await userEvent.clear(guard);
    await userEvent.type(guard, "20");
    await userEvent.click(within(dialog).getByRole("button", { name: "Reset all" }));
    expect(guard).toHaveValue("100");
  });

  it("reaches a reset button with Tab and works it with Enter and Space", async () => {
    const { dialog } = await advanced();
    const guard = within(dialog).getByRole("textbox", { name: "Guard" });
    await userEvent.clear(guard);
    await userEvent.type(guard, "20");
    await userEvent.tab();
    expect(within(dialog).getByRole("button", { name: "Reset guard to 100 ms" })).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(guard).toHaveValue("100");
    await userEvent.clear(guard);
    await userEvent.type(guard, "30");
    await userEvent.tab();
    await userEvent.keyboard(" ");
    expect(guard).toHaveValue("100");
  });

  it("treats Escape in the Advanced section as it is treated elsewhere in the dialog", async () => {
    const { dialog } = await advanced();
    await userEvent.click(within(dialog).getByRole("textbox", { name: "Guard" }));
    await userEvent.keyboard("5");
    expect(FakeRecorder.last).toBeNull();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    const again = await openDialog("Re-record word for rope");
    await recordAndReview(again);
    await openAdvanced(again);
    await userEvent.click(within(again).getByRole("textbox", { name: "Guard" }));
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBe(again);
    await userEvent.click(within(again).getByRole("button", { name: "Keep" }));
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBe(again);
  });

  it("ignores the review keys while the focus is in an Advanced field", async () => {
    const { dialog } = await advanced();
    await recordAndReview(dialog);
    const guard = within(dialog).getByRole("textbox", { name: "Guard" });
    await userEvent.click(guard);
    await userEvent.keyboard("kjdmrb");
    expect(within(dialog).getByText("Playing: rope (word)")).toBeInTheDocument();
    expect(within(dialog).getByText("1 of 1: rope (word). Clip 1 of 2.")).toBeInTheDocument();
    expect(media.played).toHaveLength(1);
    expect(guard).toHaveValue("100kjdmrb");
  });

  it("cuts the same take again with the new settings, without uploading it again", async () => {
    let cuts = 0;
    const { calls } = await openSpelling({
      cut: () => {
        cuts += 1;
        return { body: { take: TAKE, clips: cuts === 1 ? clips(2) : clips(3, "bbbbbb"), ignored: 0, loudness: "Loudness -20.0 LUFS." } };
      },
    });
    const dialog = await openDialog("Re-record word for rope");
    await recordAndReview(dialog);
    await userEvent.keyboard("j");
    await openAdvanced(dialog);
    fireEvent.change(within(dialog).getByRole("slider", { name: "Threshold" }), { target: { value: "45" } });
    await userEvent.click(within(dialog).getByRole("button", { name: "Cut" }));
    expect(await within(dialog).findByText("1 of 1: rope (word). Clip 1 of 3.")).toBeInTheDocument();
    expect(posts(calls, "/parent/api/recordings")).toHaveLength(1);
    const sent = posts(calls, `/parent/api/recordings/${TAKE}/cut`).map((call) => (call.body as { settings: { threshold: number } }).settings.threshold);
    expect(sent).toEqual([35, 45]);
    expect(media.played[media.played.length - 1]).toBe(`/parent/api/recordings/${TAKE}/bbbbbb-1.opus`);
  });
});
