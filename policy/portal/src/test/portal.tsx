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

/** Stand in for the decisions service: a signed-in parent unless handler answers otherwise. */
export function fakeService(handler: Handler = () => undefined) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), "https://garden:8084");
    const call: Call = {
      path: url.pathname,
      search: url.search,
      method: init.method ?? "GET",
      body: typeof init.body === "string" ? JSON.parse(init.body) : undefined,
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
