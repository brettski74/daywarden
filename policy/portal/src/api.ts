import { redirect } from "react-router";

export const BASE = "/parent";
export const HOME = "/parent/";
// Router paths. A redirect from a loader or an action is relative to the /parent base.
export const LOGIN = "/login";
export const HOME_ROUTE = "/";

const NOT_PAGES = new Set(["api", "assets", "login"]);

/** An answer from a data endpoint that the page shows instead of its data. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/**
 * Return the address when it is a portal page, otherwise the portal home.
 *
 * The service makes the same check on sign-in. A page address is a path under
 * /parent/ with its query string. It is not under /parent/api/ or
 * /parent/assets/, it is not the sign-in screen, and its last segment is not
 * a file name.
 */
export function safeNext(value: string | null | undefined): string {
  if (!value || /[\u0000-\u001f\u007f\\]/.test(value)) return HOME;
  if (!value.startsWith(HOME) || value.startsWith("//")) return HOME;
  const [path, ...rest] = value.split("?");
  let segments: string[];
  try {
    segments = decodeURIComponent(path).split("/").slice(2);
  } catch {
    return HOME;
  }
  if (segments.some((segment) => segment === "." || segment === "..")) return HOME;
  if (segments.slice(0, -1).includes("")) return HOME;
  if (NOT_PAGES.has(segments[0]) || segments[segments.length - 1].includes(".")) return HOME;
  return rest.length ? `${path}?${rest.join("?")}` : path;
}

/** Return a portal address relative to the router's /parent base. */
export function withinPortal(address: string): string {
  return address.slice(BASE.length) || "/";
}

/** Return the page a loader is opening, or the page an action was sent from, with its query string. */
export function pageOf(request: Request): string {
  const url = new URL(request.url);
  return url.pathname + url.search;
}

/**
 * Return the sign-in route that comes back to page.
 *
 * page is a full portal page address, never the address of a data request.
 * With no page, sign-in opens the portal home.
 */
export function signInAddress(page: string | null): string {
  if (page === null) return LOGIN;
  return `${LOGIN}?next=${encodeURIComponent(safeNext(page))}`;
}

type DataRequest = {
  /** The portal page this request belongs to, or null when there is none. */
  page: string | null;
  method?: "GET" | "POST";
  body?: unknown;
  signal?: AbortSignal;
};

/**
 * Fetch JSON from /parent/api. Every data request goes through here.
 *
 * A 401 throws a redirect to the sign-in screen that comes back to the page
 * the request belongs to, never to the data address. With no parent account
 * it throws a redirect to the closed sign-in screen. The request is not
 * repeated after sign-in.
 */
export async function api<T>(path: string, { page, method = "GET", body, signal }: DataRequest): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const init: RequestInit = { method, headers, signal, credentials: "same-origin" };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const response = await fetch(`${BASE}/api${path}`, init);
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) throw redirect(signInAddress(page));
  if (response.status === 403 && data.closed) throw redirect(LOGIN);
  if (!response.ok) throw new ApiError(response.status, data.error ?? `The service answered ${response.status}.`);
  return data as T;
}

/** Return the signed-in username, or why there is none: "signed-out" or "closed". */
export async function currentSession(signal?: AbortSignal): Promise<{ username: string } | "signed-out" | "closed"> {
  const response = await fetch(`${BASE}/api/session`, { headers: { Accept: "application/json" }, signal });
  if (response.ok) return response.json();
  const data = await response.json().catch(() => ({}));
  return response.status === 403 && data.closed ? "closed" : "signed-out";
}

/** Sign in. Return the checked page to open, or the refusal to show. */
export async function signIn(
  username: string,
  password: string,
  next: string | null,
): Promise<{ next: string } | { error: string; closed?: boolean }> {
  const response = await fetch(`${BASE}/api/login`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, next }),
  });
  const data = await response.json().catch(() => ({}));
  if (response.ok) return { next: safeNext(data.next) };
  return { error: data.error ?? "Sign-in did not work.", closed: data.closed };
}

/** End this browser's session on the service. */
export async function signOut(): Promise<void> {
  await fetch(`${BASE}/api/logout`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: "{}",
  }).catch(() => undefined);
}
