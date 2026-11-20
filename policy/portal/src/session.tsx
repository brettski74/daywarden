import { createContext, useContext, type ReactNode } from "react";
import type { LoaderFunctionArgs, RouteObject } from "react-router";
import { api, pageOf } from "./api";
import { ContextBar, useTitle } from "./slots";

/**
 * An account's role (S043). An admin uses everything. A reviewer reads
 * attempts and usage, and records parent checks. See Access control in
 * docs/parent-portal.md for which role a new page is open to.
 */
export type Role = "admin" | "reviewer";
export type Session = { username: string; role: Role };

// The session the layout loaded. The layout loads it first on every entry to the signed-in pages, and an admin
// page's loader waits on it, so learning the role costs no request of its own.
let loaded: Promise<Session> | null = null;

/** Load the signed-in account and its role for the page being opened. A signed-out parent goes to sign-in. */
export function loadSession(page: string, signal?: AbortSignal): Promise<Session> {
  const found = api<{ username: string; role: string }>("/session", { page, signal }).then(
    ({ username, role }): Session => ({ username, role: role === "admin" ? "admin" : "reviewer" }),
  );
  loaded = found;
  // A failed load is not kept, so the next page asks again.
  found.catch(() => {
    if (loaded === found) loaded = null;
  });
  return found;
}

/** Forget the session, as signing out does. */
export function forgetSession(): void {
  loaded = null;
}

/** Whether the signed-in account is an admin. A session the layout failed to load is the layout's to answer. */
async function isAdmin(request: Request): Promise<boolean> {
  if (loaded === null) return (await loadSession(pageOf(request), request.signal)).role === "admin";
  try {
    return (await loaded).role === "admin";
  } catch {
    // The layout's loader throws the same refusal, such as the redirect to sign-in. Throwing it twice would follow it twice.
    return false;
  }
}

export const SessionContext = createContext<Session>({ username: "", role: "reviewer" });

export function useSession(): Session {
  return useContext(SessionContext);
}

/** The message in the content pane when a reviewer opens an admin page. Nothing from the page is loaded. */
export function AdminsOnly({ children }: { children?: ReactNode }) {
  const { username, role } = useSession();
  if (role === "admin") return <>{children}</>;
  return <AdminsOnlyMessage username={username} />;
}

function AdminsOnlyMessage({ username }: { username: string }) {
  useTitle("For admins");
  return (
    <>
      <ContextBar>
        <h1 className="bar-title">For admins</h1>
      </ContextBar>
      <p>
        This page is for admins. You are signed in as {username}, a reviewer.
      </p>
    </>
  );
}

type Loader = (args: LoaderFunctionArgs) => unknown;

/**
 * Make a route an admin page. For a reviewer its loader and action are not
 * run, so no request is made to its data addresses, and the page shows the
 * not-available message instead. The service refuses those addresses to a
 * reviewer anyway: this keeps the page tidy, it is not what protects the data.
 */
export function adminOnly(route: RouteObject): RouteObject {
  const wrapped: RouteObject = { ...route, element: <AdminsOnly>{route.element}</AdminsOnly> };
  if (typeof route.loader === "function") {
    const loader = route.loader as Loader;
    wrapped.loader = async (args: LoaderFunctionArgs) => ((await isAdmin(args.request)) ? loader(args) : null);
  }
  if (typeof route.action === "function") {
    const action = route.action as Loader;
    wrapped.action = async (args: LoaderFunctionArgs) => ((await isAdmin(args.request)) ? action(args) : null);
  }
  return wrapped;
}
