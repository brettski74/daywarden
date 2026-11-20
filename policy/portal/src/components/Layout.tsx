import { useEffect, useRef, useState } from "react";
import { Outlet, useLoaderData, useLocation, type LoaderFunctionArgs } from "react-router";
import { api, pageOf } from "../api";
import { SessionContext, loadSession, type Session } from "../session";
import { SlotsContext } from "../slots";
import type { TaskRef } from "../taskRef";
import { Sidebar } from "./Sidebar";

type Frame = { session: Session; tasks: TaskRef[] };

/** The signed-in account and, for an admin, the task list for Task Administration. A reviewer's sidebar has no tasks. */
export async function layoutLoader({ request }: LoaderFunctionArgs): Promise<Frame> {
  const page = pageOf(request);
  const session = await loadSession(page, request.signal);
  if (session.role !== "admin") return { session, tasks: [] };
  const listed = await api<{ tasks: TaskRef[] }>("/tasks", { page, signal: request.signal });
  return { session, tasks: listed.tasks };
}

/** Every signed-in page: the sidebar, then the context bar, content pane, and status bar. */
export function Layout() {
  const { session, tasks } = useLoaderData() as Frame;
  const [context, setContext] = useState<HTMLElement | null>(null);
  const [status, setStatus] = useState<HTMLElement | null>(null);
  const content = useRef<HTMLElement>(null);
  const { pathname } = useLocation();
  useEffect(() => {
    content.current?.scrollTo?.(0, 0);
  }, [pathname]);
  return (
    <SessionContext.Provider value={session}>
      <div className="portal">
        <Sidebar session={session} tasks={tasks} />
        <div className="main">
          <header className="context-bar" ref={setContext} />
          <main className="content" ref={content}>
            <SlotsContext.Provider value={{ context, status }}>
              <Outlet />
            </SlotsContext.Provider>
          </main>
          <footer className="status-bar" ref={setStatus} role="status" />
        </div>
      </div>
    </SessionContext.Provider>
  );
}
