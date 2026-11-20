import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { vi } from "vitest";
import { BASENAME, routes } from "../routes";

export type Reply = { status?: number; body?: unknown };
export type Call = { path: string; search: string; method: string; body: unknown };
type Handler = (call: Call) => Reply | undefined;

const ALL_VIEW = {
  range: "past-month",
  from: "",
  to: "",
  set: ["required", "potential", "practice"],
  outcome: ["pass", "failure", "abandoned", "unfinished", "in_progress"],
};

export const ATTEMPTS = {
  clients: ["younger", "older", "default"],
  client: "younger",
  view: { ...ALL_VIEW, client: "younger" },
  notes: [] as string[],
  today: "2026-11-17",
  range: "Saturday 17 October 2026 18:00 to Tuesday 17 November 2026 18:00",
  days: { from: "2026-10-17", to: "2026-11-17" },
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
      type: "spelling",
      set: "Required",
      started: "Saturday 31 October 2026, 16:00",
      finished: "Saturday 31 October 2026, 16:12:30",
      outcome: "pass",
      duration: "12m 30s",
    },
  ],
  overview: [
    {
      type: "spelling",
      name: "spelling-week-3",
      label: "spelling/spelling-week-3",
      in_policy: true,
      attempts: 1,
      passes: 1,
      failures: 0,
      abandoned: 0,
      unfinished: 0,
      accuracy: 92,
      spark: [{ points: 11, pass_mark: 12 }],
      spark_label: "1 attempt, latest 11 of 12",
    },
  ],
};

export const NO_GROUP = {
  ...ATTEMPTS,
  client: "",
  view: { ...ATTEMPTS.view, client: "" },
  message: "Choose a client group.",
  summary: null,
  overview: null,
  attempts: null,
};

const SUM_FIGURES = { points: 20, pass_mark: 20, questions: 25, maximum: null, wrong: 3, timeouts: 2, time_ms: 70_000, average_ms: 2500 };

/** arithmetic/sums for younger over the past month: a pass, then a practice abandonment. */
export const TREND = {
  clients: ["younger", "older", "default"],
  client: "younger",
  view: { ...ALL_VIEW, client: "younger" },
  notes: [] as string[],
  today: "2026-11-17",
  range: "Saturday 17 October 2026 18:00 to Tuesday 17 November 2026 18:00",
  days: { from: "2026-10-17", to: "2026-11-17" },
  times: "Times are Australia/Sydney.",
  task: { type: "arithmetic", name: "sums", label: "arithmetic/sums", in_policy: true },
  facts: "addition" as string | null,
  message: null as string | null,
  trend: {
    kind: "points" as "points" | "spelling" | null,
    has_maximum: false,
    length: 31 * 86400,
    ticks: [{ at: 86400, label: "Sun 18 Oct" }],
    points: [
      {
        id: 7,
        at: 10 * 86400,
        started: "Tuesday 27 October 2026, 16:00",
        set: "Required",
        practice: false,
        outcome: "pass",
        outcome_label: "Pass",
        figures: SUM_FIGURES as Record<string, number | null>,
      },
      {
        id: 9,
        at: 20 * 86400,
        started: "Friday 6 November 2026, 16:00",
        set: "Practice",
        practice: true,
        outcome: "abandoned",
        outcome_label: "Abandoned",
        figures: { ...SUM_FIGURES, points: 4, questions: 6, wrong: 2, timeouts: 0, average_ms: null } as Record<string, number | null>,
      },
    ],
    attempts: [
      { id: 9, task: "sums", type: "arithmetic", set: "Practice", started: "Friday 6 November 2026, 16:00", finished: "Friday 6 November 2026, 16:05", outcome: "abandoned", duration: "5m" },
      { id: 7, task: "sums", type: "arithmetic", set: "Required", started: "Tuesday 27 October 2026, 16:00", finished: "Tuesday 27 October 2026, 16:10", outcome: "pass", duration: "10m" },
    ],
  },
};

export const ATTEMPT = {
  id: 42,
  task: "spelling-week-3",
  type: "spelling",
  client: "younger",
  times: "Times are Australia/Sydney.",
  summary: [
    { label: "Client group", value: "younger" },
    { label: "Outcome", value: "pass" },
  ],
  reopened: [{ gave_up: "Saturday 31 October 2026, 16:05", came_back: "Saturday 31 October 2026, 16:10" }],
  arithmetic: null,
  answers: ["wombat", { prompt: "2 + 2", answer: "5", correct: false }],
  record: { result: "pass", settings: { words: 10 } },
};

const fact = (m: number, n: number, counts: { asked: number; right: number; wrong: number; timeouts: number }, extra: Record<string, unknown> = {}) => ({
  m,
  n,
  cell: `${m} \u00d7 ${n}`,
  text: `${m} \u00d7 ${n} = ${m * n}`,
  ...counts,
  missed: counts.wrong + counts.timeouts,
  missed_percent: Math.round((100 * (counts.wrong + counts.timeouts)) / counts.asked),
  median_ms: null as number | null,
  last_missed: null as string | null,
  last_missed_day: null as string | null,
  attempts: [] as { id: number; answers: string[] }[],
  all_time: { asked: counts.asked, run: 0, smoothed_ms: null as number | null, miss_boost: 0, slow_boost: 0, weight: 1 / (counts.asked + 1) },
  ...extra,
});

/** younger's multiplication over the past month: 7 × 8 missed twice in five, 7 × 6 never missed, 6 × 8 once, and 6 × 6 not asked. */
export const FACTS = {
  clients: ["younger", "older", "default"],
  client: "younger",
  view: { ...ALL_VIEW, client: "younger" },
  notes: [] as string[],
  today: "2026-11-17",
  range: "Saturday 17 October 2026 18:00 to Tuesday 17 November 2026 18:00",
  days: { from: "2026-10-17", to: "2026-11-17" },
  times: "Times are Australia/Sydney.",
  operation: { name: "multiplication", label: "Multiplication" },
  operations: [
    { name: "addition", label: "Addition" },
    { name: "subtraction", label: "Subtraction" },
    { name: "multiplication", label: "Multiplication" },
    { name: "division", label: "Division" },
  ],
  message: null as string | null,
  slow: {
    median_ms: 2000,
    start_ms: 4000,
    full_ms: 8000,
    timed_facts: 12,
    facts_needed: 10,
    answers_needed: 3,
    text: "Median 2.0 s. Slow from 4.0 s, full at 8.0 s.",
  } as Record<string, unknown> | null,
  facts: {
    rows: [6, 7],
    columns: [6, 8],
    facts: [
      fact(6, 8, { asked: 4, right: 3, wrong: 1, timeouts: 0 }, {
        median_ms: 4000,
        last_missed: "Monday 9 November 2026",
        last_missed_day: "2026-11-09",
        attempts: [{ id: 7, answers: ["46"] }],
        all_time: { asked: 9, run: 2, smoothed_ms: 6000, miss_boost: 1, slow_boost: 2, weight: 3.1 },
      }),
      fact(7, 6, { asked: 2, right: 2, wrong: 0, timeouts: 0 }, {
        median_ms: 2000,
        attempts: [{ id: 7, answers: ["42", "42"] }],
        all_time: { asked: 12, run: 12, smoothed_ms: 1900, miss_boost: 0, slow_boost: 0, weight: 0.077 },
      }),
      fact(7, 8, { asked: 5, right: 3, wrong: 1, timeouts: 1 }, {
        all_time: { asked: 6, run: 1, smoothed_ms: 3100, miss_boost: 2, slow_boost: 0, weight: 2.143 },
        median_ms: 3000,
        last_missed: "Friday 13 November 2026",
        last_missed_day: "2026-11-13",
        attempts: [
          { id: 9, answers: ["timeout", "56"] },
          { id: 7, answers: ["54", "54", "56"] },
        ],
      }),
    ],
    attempts: {
      "7": { started: "Tuesday 27 October 2026, 16:00", task: "times" },
      "9": { started: "Friday 13 November 2026, 16:00", task: "tables" },
    },
  },
};

const RUN_QUESTION = { m: 6, n: 7, operation: "addition", allowed_ms: 10_000 };

/** An arithmetic attempt: a run that expired, then a run that passed. */
export const ARITHMETIC_ATTEMPT = {
  ...ATTEMPT,
  id: 43,
  task: "sums",
  type: "arithmetic",
  reopened: [],
  answers: null,
  arithmetic: {
    last: {
      run: 2,
      expired: null,
      operation: "addition",
      operation_label: "Addition",
      figures: { points: 2, pass_mark: 2, questions: 4, maximum: null, wrong: 1, timeouts: 1, time_ms: 17_500, average_ms: 2250 },
      questions: [
        { ...RUN_QUESTION, text: "6 + 7 = 13", answer: "13", outcome: "correct", outcome_label: "Right", taken_ms: 2000 },
        { ...RUN_QUESTION, text: "6 + 7 = 13", answer: "12", outcome: "incorrect", outcome_label: "Wrong", taken_ms: 3000 },
        { ...RUN_QUESTION, m: 7, n: 8, text: "7 + 8 = 15", answer: "", outcome: "timeout", outcome_label: "Timeout", taken_ms: 10_000 },
        { ...RUN_QUESTION, m: 2, n: 0, text: "2 + 0 = 2", answer: "2", outcome: "correct", outcome_label: "Right", taken_ms: 2500 },
      ],
    },
    expired: [
      {
        run: 1,
        expired: "Saturday 31 October 2026, 17:00",
        operation: "addition",
        operation_label: "Addition",
        figures: { points: 0, pass_mark: 2, questions: 1, maximum: null, wrong: 1, timeouts: 0, time_ms: 4000, average_ms: null },
        questions: [{ ...RUN_QUESTION, text: "6 + 7 = 13", answer: "0", outcome: "incorrect", outcome_label: "Wrong", taken_ms: 4000 }],
      },
    ],
    practice: [
      {
        walk: 1,
        run: 2,
        m: 7,
        operation: "addition",
        operation_label: "Addition",
        length: 28,
        ended: "left",
        questions: [
          { ...RUN_QUESTION, m: 7, n: 1, text: "7 + 1 = 8", answer: "8", outcome: "correct", outcome_label: "Right", taken_ms: 1500, step: "1 of 28" },
          { ...RUN_QUESTION, m: 7, n: 2, text: "7 + 2 = 9", answer: "10", outcome: "incorrect", outcome_label: "Wrong", taken_ms: 2500, step: "2 of 28" },
          { ...RUN_QUESTION, m: 7, n: 1, text: "7 + 1 = 8", answer: "", outcome: "timeout", outcome_label: "Timeout", taken_ms: 10_000, step: "1 of 28" },
        ],
      },
    ],
  },
  record: { settings: { operation: "addition" }, last_activity: "2026-10-31T17:30:00" },
};

/** Default settings over the past week at Friday 13 November 2026 21:30: younger used 1h 15m on the Tuesday, older nothing. */
const spelled = (word: string, counts: { first_time: number; after_miss: number; missed: number }, extra: Record<string, unknown> = {}) => {
  const asked = counts.first_time + counts.after_miss + counts.missed;
  return {
    word,
    key: word,
    pools: ["current"],
    asked,
    ...counts,
    missed_percent: Math.round((100 * (counts.after_miss + counts.missed)) / asked),
    timeouts: 0,
    median_ms: 3000 as number | null,
    replays_per_ask: 0,
    last_missed: null as string | null,
    last_missed_day: null as string | null,
    misspellings: [] as { text: string; count: number }[],
    attempts: [] as { id: number; result: string; pools: string[]; answers: string[] }[],
    all_time: { run: 3, weight: 0.25 },
    ...extra,
  };
};

/** younger's spelling words this week: necessary missed Monday and Tuesday and right after a miss Wednesday, rope and cat right first time. */
export const WORDS = {
  clients: ["younger", "older", "default"],
  client: "younger",
  view: { ...ALL_VIEW, client: "younger" },
  notes: [] as string[],
  times: "Times are Australia/Sydney.",
  today: "2026-11-18",
  range: "Past month",
  days: { from: "2026-10-19", to: "2026-11-18" },
  tasks_offered: [
    { name: "spelling-younger", in_policy: true },
    { name: "old-list", in_policy: false },
  ],
  choices: { task: ["spelling-younger", "old-list"], pool: ["current", "revision", "attic", "no_pool"] },
  this_week: { from: "2026-11-16", to: "2026-11-18" } as { from: string; to: string } | null,
  message: null as string | null,
  words: {
    tiles: { words_asked: 3, right_first_time: 71, words_missed: 1, settled: 1 },
    columns: [51, 52, 53],
    attempts: {
      "51": { started: "Monday 16 November 2026, 16:00", day: "2026-11-16", task: "spelling-younger" },
      "52": { started: "Tuesday 17 November 2026, 16:00", day: "2026-11-17", task: "spelling-younger" },
      "53": { started: "Wednesday 18 November 2026, 16:00", day: "2026-11-18", task: "spelling-younger" },
    },
    words: [
      spelled("cat", { first_time: 1, after_miss: 0, missed: 0 }, { pools: ["revision"], all_time: { run: 6, weight: 0.125 }, attempts: [{ id: 52, result: "first_time", pools: ["revision"], answers: ["cat"] }] }),
      spelled(
        "necessary",
        { first_time: 0, after_miss: 1, missed: 2 },
        {
          timeouts: 1,
          median_ms: 5000,
          replays_per_ask: 0.7,
          last_missed: "Wednesday 18 November 2026",
          last_missed_day: "2026-11-18",
          misspellings: [
            { text: "necesary", count: 3 },
            { text: "neccessary", count: 1 },
          ],
          attempts: [
            { id: 53, result: "after_miss", pools: ["current"], answers: ["necesary", "necessary"] },
            { id: 52, result: "missed", pools: ["current"], answers: ["timeout", "necesary"] },
            { id: 51, result: "missed", pools: ["revision"], answers: ["necesary", "neccessary"] },
          ],
          all_time: { run: 0, weight: 4.25 },
        },
      ),
      spelled("rope", { first_time: 3, after_miss: 0, missed: 0 }, {
        median_ms: 2000,
        attempts: [53, 52, 51].map((id) => ({ id, result: "first_time", pools: ["current"], answers: ["rope"] })),
      }),
    ],
  },
};

/** A spelling attempt: a run that expired, a run left for practice mode, then the run practice started. */
export const SPELLING_ATTEMPT = {
  ...ATTEMPT,
  id: 44,
  task: "spelling-younger",
  reopened: [],
  answers: null,
  spelling: {
    last: {
      run: 3,
      ended: null,
      figures: { points: 3, pass_mark: 3, questions: 4, maximum: null, wrong: 1, timeouts: 0, time_ms: 14_000, average_ms: 3500, current_points: 2, current_required: 2, revision_points: 1, revision_required: 1 },
      practised: [
        { key: "rope", word: "rope", pool: "current", pool_label: "Current" },
        { key: "cat", word: "cat", pool: "revision", pool_label: "Revision" },
      ],
      questions: [
        { key: "necessary", word: "necessary", spelling: "necessary", pool: "current", pool_label: "Current", answer: "necesary", outcome: "incorrect", outcome_label: "Wrong", came_back: true, word_replays: 2, sentence_plays: 1, taken_ms: 4000, allowed_ms: 12_000 },
        { key: "necessary", word: "necessary", spelling: "necessary", pool: "current", pool_label: "Current", answer: "necessary", outcome: "correct", outcome_label: "Right", came_back: false, word_replays: 0, sentence_plays: 0, taken_ms: 4500, allowed_ms: 12_000 },
        { key: "read.1", word: "read.1", spelling: "read", pool: "current", pool_label: "Current", answer: "read", outcome: "correct", outcome_label: "Right", came_back: false, word_replays: 0, sentence_plays: 0, taken_ms: 3000, allowed_ms: 12_000 },
        { key: "cat", word: "cat", spelling: "cat", pool: "revision", pool_label: "Revision", answer: "", outcome: "timeout", outcome_label: "Timeout", came_back: false, word_replays: 0, sentence_plays: 0, taken_ms: null, allowed_ms: 12_000 },
      ],
    },
    earlier: [
      { run: 1, ended: { how: "expired", at: "Wednesday 18 November 2026, 15:00" }, figures: null, practised: null, questions: [] },
      { run: 2, ended: { how: "practice", at: "Wednesday 18 November 2026, 16:20" }, figures: null, practised: null, questions: [] },
    ],
  },
  record: { settings: {} },
};

export const USAGE = {
  unit: "minutes",
  today: "2026-11-13",
  choices: { clients: ["younger", "older", "default"], sites: ["school", "youtube", "default"], quotas: ["youtube", "screen-time"] },
  settings: { client: [] as string[], site: [] as string[], quota: [] as string[], by: "client", range: "past-week", from: "", to: "" },
  preset: "Default",
  presets: ["Default", "School week"],
  notes: [] as string[],
  times: "Times are Australia/Sydney.",
  range: "Friday 6 November 2026 21:30 to Friday 13 November 2026 21:30",
  days: { from: "2026-11-06", to: "2026-11-13" },
  graph: {
    length: 7 * 86400,
    interval: "day",
    ticks: [{ at: 9000, label: "Sat 7 Nov" }],
    points: [
      "Friday 6 November 2026 21:30 to 24:00",
      "Saturday 7 November 2026",
      "Sunday 8 November 2026",
      "Monday 9 November 2026",
      "Tuesday 10 November 2026",
      "Wednesday 11 November 2026",
      "Thursday 12 November 2026",
      "Friday 13 November 2026 00:00 to 21:30",
    ].map((label, index) => ({ at: index * 86400, label })),
    lines: [
      { name: "younger", values: [0, 0, 0, 0, 4500, 0, 0, 0] },
      { name: "older", values: [0, 0, 0, 0, 0, 0, 0, 0] },
    ],
  },
  hosts: null as null | { line: string; kept: string | null; bars: { host: string; value: number; down?: number; up?: number }[] },
};

/** One request row for the Requests page and the host drill-down. */
export const REQUESTS = {
  today: "2026-11-13",
  choices: {
    clients: ["younger", "older", "default"],
    sites: ["school", "youtube", "default"],
    quotas: ["youtube", "screen-time"],
    outcomes: ["allowed", "denied", "redirected", "cut"],
  },
  settings: { client: [] as string[], site: [] as string[], quota: [] as string[], by: "none", range: "past-week", from: "", to: "" },
  preset: "Default",
  presets: ["Default", "School week"],
  host: "",
  exact: false,
  outcome: [] as string[],
  fetch: "all" as "all" | "documents" | "user",
  hide_hops: false,
  sort: "start",
  dir: "desc" as const,
  page: 1,
  pages: 1,
  notes: [] as string[],
  times: "Times are Australia/Sydney.",
  range: "Friday 6 November 2026 21:30 to Friday 13 November 2026 21:30",
  days: { from: "2026-11-06", to: "2026-11-13" },
  kept: null as string | null,
  total: 1,
  from: 1,
  to: 1,
  status: "Requests 1 to 1 of 1.",
  rows: [
    {
      id: "flow-1",
      start: "Friday 13 November 2026, 20:00",
      end: "Friday 13 November 2026, 20:00:05",
      duration: "5s",
      address: "192.0.2.40",
      client_group: "younger",
      site_group: "youtube",
      quotas: "youtube, screen-time",
      method: "GET",
      host: "www.youtube.com",
      path: "https://www.youtube.com/watch",
      query: "v=abc123",
      url: "https://www.youtube.com/watch?v=abc123",
      status: "200",
      type: "text/html",
      down: "2 KB",
      up: "40 bytes",
      outcome: "allowed",
      dest: "document",
      mode: "navigate",
      fetch_site: "none",
      user: "?1",
      purpose: "",
    },
  ],
};

export const TASKS = {
  tasks: [
    { type: "parent_check", name: "check" },
    { type: "spelling", name: "spelling" },
    { type: "worksheet", name: "sums" },
  ],
};

/** The household's today, a Tuesday. */
export const TODAY = "2026-11-10";

const COMMON = {
  pass_cooldown: "1",
  failure_cooldown: "",
  max_skips: "3",
  max_passes: "",
  available_from: "",
  due_date: "",
};

export const DIRECTORIES = {
  current_dir: "spelling/current",
  revision_dir: "spelling/revision",
  attic_dir: "spelling/attic",
  alphabet_dir: "spelling/alphabet",
};

export const SPELLING = {
  name: "spelling",
  type: "spelling",
  file: "/etc/daywarden/policy.yaml",
  version: "v1",
  groups: ["younger"],
  clients: ["younger", "older", "default"],
  fields: COMMON,
  today: TODAY,
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
    directories: DIRECTORIES,
    folders: ["alphabet", "attic", "current", "revision", "year-3", "year-3/current"],
    setup: null as { mode: string; count: number } | null,
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
  type: "spelling",
  version: "v1",
  file: "/etc/daywarden/policy.yaml",
  mode: "replace-current",
  setup: { mode: "replace-current", count: 5 },
  directories: DIRECTORIES,
  saved_directories: DIRECTORIES,
  written: true,
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
  today: TODAY,
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
      return { body: { username: "ada", role: "admin" } };
    case "/parent/api/attempts":
      return { body: call.search ? ATTEMPTS : NO_GROUP };
    case "/parent/api/attempts/42":
      return { body: ATTEMPT };
    case "/parent/api/attempts/tasks/arithmetic/sums":
      return { body: TREND };
    case "/parent/api/attempts/43":
      return { body: ARITHMETIC_ATTEMPT };
    case "/parent/api/attempts/facts/multiplication":
      return { body: FACTS };
    case "/parent/api/attempts/words":
      return { body: WORDS };
    case "/parent/api/attempts/44":
      return { body: SPELLING_ATTEMPT };
    case "/parent/api/usage/minutes":
      return { body: USAGE };
    case "/parent/api/usage/bytes":
      return { body: { ...USAGE, unit: "bytes" } };
    case "/parent/api/usage/requests":
      return { body: REQUESTS };
    case "/parent/api/tasks":
      return { body: TASKS };
    case "/parent/api/tasks/spelling/spelling":
      return { body: SPELLING };
    case "/parent/api/tasks/spelling/spelling/week":
      return { body: WEEK };
    case "/parent/api/tasks/parent_check/check":
      return { body: CHECK };
    case "/parent/api/tasks/worksheet/sums":
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
