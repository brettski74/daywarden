import { useEffect, useRef, useState } from "react";
import { Outlet, useLoaderData, useLocation, type LoaderFunctionArgs } from "react-router";
import { api, pageOf } from "../api";
import { SlotsContext } from "../slots";
import type { TaskRef } from "../taskRef";
import { Sidebar } from "./Sidebar";

type Frame = { username: string; tasks: TaskRef[] };

export async function layoutLoader({ request }: LoaderFunctionArgs): Promise<Frame> {
  const page = pageOf(request);
  const [session, listed] = await Promise.all([
    api<{ username: string }>("/session", { page, signal: request.signal }),
    api<{ tasks: TaskRef[] }>("/tasks", { page, signal: request.signal }),
  ]);
  return { username: session.username, tasks: listed.tasks };
}

/** Every signed-in page: the sidebar, then the context bar, content pane, and status bar. */
export function Layout() {
  const { username, tasks } = useLoaderData() as Frame;
  const [context, setContext] = useState<HTMLElement | null>(null);
  const [status, setStatus] = useState<HTMLElement | null>(null);
  const content = useRef<HTMLElement>(null);
  const { pathname } = useLocation();
  useEffect(() => {
    content.current?.scrollTo?.(0, 0);
  }, [pathname]);
  return (
    <div className="portal">
      <Sidebar username={username} tasks={tasks} />
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
  );
}
