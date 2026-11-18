import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ATTEMPT, CHECK, TASKS, TODAY, fakeService, renderPortal, type Call, type Reply } from "./test/portal";

const PAGE = {
  ...CHECK,
  name: "caps",
  type: "capitalisation",
  version: "v1",
  fields: { pass_cooldown: "1", failure_cooldown: "", max_skips: "", max_passes: "", available_from: "", due_date: "" },
  capitalisation: {
    settings: { timeout: "", correct_answers_required: "", minimum_questions: "", maximum_questions: "" },
    pools: ["Places"],
    available: [
      { id: "places", name: "Places", sentences: 12 },
      { id: "people", name: "People", sentences: 3 },
    ],
  },
  today: TODAY,
};
const DONE = { message: "Saved caps.", warnings: [] };

async function openCaps(handler?: (call: Call) => Reply | undefined) {
  const calls = fakeService((call) => {
    const answered = handler?.(call);
    if (answered) return answered;
    if (call.path === "/parent/api/tasks") return { body: { tasks: [...TASKS.tasks, { type: "capitalisation", name: "caps" }] } };
    return call.path === "/parent/api/tasks/capitalisation/caps" && call.method === "GET" ? { body: PAGE } : undefined;
  });
  renderPortal("/parent/tasks/capitalisation/caps");
  await screen.findByRole("heading", { name: "caps" });
  return calls;
}

describe("a capitalisation task page", () => {
  it("shows the settings and pools with a 60s timeout placeholder, and no parts of speech filter", async () => {
    await openCaps();
    expect(screen.getByRole("textbox", { name: "Timeout" })).toHaveAttribute("placeholder", "60s");
    expect(screen.getByRole("textbox", { name: "Maximum Questions" })).toHaveAttribute("placeholder", "12");
    expect(screen.getByRole("button", { name: "Pools Places" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Parts of speech filter" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Edit Places" })).toHaveAttribute("href", "/parent/assets/capitalisation-pools/places");
    expect(screen.getByRole("status")).toHaveTextContent("1 pool. 12 sentences.");
  });

  it("saves the settings and pools without a parts of speech filter", async () => {
    const calls = await openCaps((call) => (call.method === "POST" ? { body: DONE } : undefined));
    await userEvent.type(screen.getByRole("textbox", { name: "Timeout" }), "45s");
    await userEvent.click(screen.getByRole("button", { name: /^Pools/ }));
    await userEvent.click(within(screen.getByRole("listbox", { name: "Pools" })).getByRole("option", { name: "People" }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
    const sent = calls.find((call) => call.method === "POST")!.body as Record<string, unknown>;
    expect(sent).toMatchObject({ version: "v1", pools: ["Places", "People"], settings: { timeout: "45s" } });
    expect(sent).not.toHaveProperty("parts_of_speech");
  });
});

describe("a capitalisation attempt page", () => {
  it("shows the last run's figures, then each try of each sentence with its marked words, points, and time", async () => {
    const word = (text: string, colour: string) => ({ word: text, colour });
    fakeService((call) =>
      call.path === "/parent/api/attempts/42"
        ? {
            body: {
              ...ATTEMPT,
              type: "capitalisation",
              capitalisation: {
                last: {
                  run: 1,
                  expired: null,
                  figures: { points: 1.5, pass_mark: 2, questions: 2, maximum: 5, wrong: 1, timeouts: 0, time_ms: 12000, average_ms: 6000 },
                  sentences: [
                    {
                      text: "Anna flew to Paris.",
                      outcome: "correct",
                      outcome_label: "Correct",
                      points: 0.5,
                      tries: [
                        { words: [word("Anna", "blue"), word("flew", "black"), word("to", "black"), word("Paris.", "red")], points: 0, timeout: false, taken_ms: 4000 },
                        { words: [word("Anna", "blue"), word("flew", "black"), word("to", "black"), word("Paris.", "blue")], points: 0.5, timeout: false, taken_ms: 8000 },
                      ],
                    },
                    {
                      text: "We saw NASA.",
                      outcome: "timeout",
                      outcome_label: "Timed out",
                      points: 0,
                      tries: [{ words: [word("We", "black"), word("saw", "black"), word("NASA.", "red")], points: 0, timeout: true, taken_ms: 60000 }],
                    },
                  ],
                },
                expired: [],
              },
            },
          }
        : undefined,
    );
    renderPortal("/parent/attempts/42");
    await screen.findByRole("heading", { name: "Last run" });
    expect(screen.getByText("1.5 / 2 right")).toBeInTheDocument();
    const first = within(screen.getByRole("listitem", { name: "Sentence 1" }));
    const tries = first.getAllByRole("listitem");
    expect(tries).toHaveLength(2);
    expect(tries[0].querySelector('[data-colour="red"]')).toHaveTextContent("Paris.");
    expect(tries[1].querySelector('[data-colour="red"]')).toBeNull();
    expect(tries[1].querySelectorAll('[data-colour="blue"]')).toHaveLength(2);
    expect(tries[1]).toHaveTextContent("0.5 points");
    expect(within(screen.getByRole("listitem", { name: "Sentence 2" })).getByText("Timeout")).toBeInTheDocument();
  });
});
