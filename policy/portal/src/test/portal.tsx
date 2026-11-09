import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { vi } from "vitest";
import { BASENAME, routes } from "../routes";

export type Reply = { status?: number; body?: unknown };
export type Call = { path: string; search: string; method: string; body: unknown };
type Handler = (call: Call) => Reply | undefined;

export const ATTEMPTS = {
  clients: ["younger", "older", "default"],
  client: "younger",
  times: "Times are Australia/Sydney.",
  message: null,
  summary: [
    { label: "Today's score", value: "1" },
    { label: "Required tasks outstanding", value: "none" },
    { label: "Potential tasks available", value: "spelling" },
    { label: "Potential passes waiting on required tasks", value: "none" },
  ],
  attempts: [
    {
      id: 42,
      task: "spelling-week-3",
      set: "Required",
      started: "Saturday 31 October 2026, 16:00",
      finished: "Saturday 31 October 2026, 16:12:30",
      outcome: "pass",
      duration: "12m 30s",
    },
  ],
};

export const NO_GROUP = { ...ATTEMPTS, client: "", message: "Choose a client group.", summary: null, attempts: null };

export const ATTEMPT = {
  id: 42,
  task: "spelling-week-3",
  client: "younger",
  times: "Times are Australia/Sydney.",
  summary: [
    { label: "Client group", value: "younger" },
    { label: "Outcome", value: "pass" },
  ],
  reopened: [{ gave_up: "Saturday 31 October 2026, 16:05", came_back: "Saturday 31 October 2026, 16:10" }],
  answers: ["wombat", { prompt: "2 + 2", answer: "5", correct: false }],
  record: { result: "pass", settings: { words: 10 } },
};

export const USAGE = {
  times: "Times are Australia/Sydney.",
  choices: { clients: ["younger", "default"], sites: ["school", "default"], quotas: ["youtube"] },
  chosen: { view: "", client: "", site: "", quota: "" },
  report: null,
  message: "Choose a site group, a client group, or a quota.",
};

export const TASKS = { tasks: ["check", "spelling", "sums"] };

const COMMON = {
  pass_cooldown: "1",
  failure_cooldown: "",
  max_skips: "3",
  max_passes: "",
  available_from: "",
  due_date: "",
};

export const SPELLING = {
  name: "spelling",
  type: "spelling",
  file: "/etc/daywarden/policy.yaml",
  version: "v1",
  groups: ["younger"],
  clients: ["younger", "older", "default"],
  fields: COMMON,
  spelling: {
    settings: {
      timeout: "30s",
      maximum_replays: "",
      maximum_sentence_plays: "",
      current_required: "",
      revision_required: "1",
      letter_pause: "",
      word_pause: "",
    },
    directories: {
      current_dir: "spelling/current",
      revision_dir: "spelling/revision",
      attic_dir: "spelling/attic",
      alphabet_dir: "spelling/alphabet",
    },
    words: [
      { key: "rope", word: "rope", pool: "current", clip: "rope.wav", sentence: "rope.sentence.wav" },
      { key: "cat", word: "cat", pool: "current", clip: "cat.wav", sentence: null },
      { key: "fish", word: "fish", pool: "revision", clip: "fish.wav", sentence: null },
      { key: "owl", word: "owl", pool: "attic", clip: "owl.wav", sentence: null },
    ],
    problems: [],
  },
};

const NO_CLIPS = { word: null, sentence: null };
const WEEK_WORD = { becomes: null, renames: null, sentence_clip: null, kept: NO_CLIPS, choices: [], new_key: null };

/** A week's list with a word of each kind: new, new with a sentence kept, current, revision, and attic. */
export const WEEK = {
  name: "spelling",
  version: "v1",
  file: "/etc/daywarden/policy.yaml",
  targets: { current_required: "", revision_required: "1" },
  current: 2,
  needs: ["frog", "toad"],
  ambiguous: [],
  problems: [],
  words: [
    { ...WEEK_WORD, key: "frog", word: "frog", pool: null, clip: null, sentence: "The frog jumped." },
    { ...WEEK_WORD, key: "toad", word: "toad", pool: null, clip: null, kept: { word: null, sentence: "00c0ffee.opus" }, sentence: "A toad sat." },
    { ...WEEK_WORD, key: "rope", word: "rope", pool: "current", clip: "rope.wav", sentence: "Pull the rope." },
    { ...WEEK_WORD, key: "fish", word: "fish", pool: "revision", clip: "fish.wav", sentence_clip: "fish.sentence.wav", sentence: "A fish swims." },
    { ...WEEK_WORD, key: "owl", word: "owl", pool: "attic", clip: "owl.wav", sentence: "" },
  ],
};

export const CHECK = {
  name: "check",
  type: "parent_check",
  file: "/etc/daywarden/policy.yaml",
  version: "v1",
  groups: ["younger"],
  clients: ["younger", "older", "default"],
  fields: { pass_cooldown: "0", failure_cooldown: "" },
};

export const SUMS = { ...CHECK, name: "sums", type: "worksheet", fields: COMMON };

/** Stand in for the decisions service: a signed-in parent unless handler answers otherwise. */
export function fakeService(handler: Handler = () => undefined) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), "https://garden:8084");
    const call: Call = {
      path: url.pathname,
      search: url.search,
      method: init.method ?? "GET",
      body: typeof init.body === "string" ? JSON.parse(init.body) : (init.body ?? undefined),
    };
    calls.push(call);
    const reply = handler(call) ?? standard(call);
    return new Response(JSON.stringify(reply.body ?? {}), {
      status: reply.status ?? 200,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

function standard(call: Call): Reply {
  switch (call.path) {
    case "/parent/api/session":
      return { body: { username: "ada" } };
    case "/parent/api/attempts":
      return { body: call.search ? ATTEMPTS : NO_GROUP };
    case "/parent/api/attempts/42":
      return { body: ATTEMPT };
    case "/parent/api/usage":
      return { body: USAGE };
    case "/parent/api/tasks":
      return { body: TASKS };
    case "/parent/api/tasks/spelling":
      return { body: SPELLING };
    case "/parent/api/tasks/spelling/week":
      return { body: WEEK };
    case "/parent/api/tasks/check":
      return { body: CHECK };
    case "/parent/api/tasks/sums":
      return { body: SUMS };
    case "/parent/api/logout":
      return { body: { signed_out: true } };
    default:
      return { status: 404, body: { error: "Not found." } };
  }
}

/** Render the portal at a full address such as /parent/attempts?client=younger. */
export function renderPortal(address: string) {
  const router = createMemoryRouter(routes, { basename: BASENAME, initialEntries: [address] });
  const view = render(<RouterProvider router={router} />);
  return { router, ...view };
}

/** The address the router is showing, with its query string. */
export function shown(router: ReturnType<typeof createMemoryRouter>): string {
  return router.state.location.pathname + router.state.location.search;
}
