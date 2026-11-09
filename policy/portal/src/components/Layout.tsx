import { useEffect, useRef, useState } from "react";
import { Outlet, useLoaderData, useLocation, type LoaderFunctionArgs } from "react-router";
import { api, pageOf } from "../api";
import { SlotsContext } from "../slots";
import { Sidebar } from "./Sidebar";

type Session = { username: string };

export async function layoutLoader({ request }: LoaderFunctionArgs): Promise<Session> {
  return api<Session>("/session", { page: pageOf(request), signal: request.signal });
}

/** Every signed-in page: the sidebar, then the context bar, content pane, and status bar. */
export function Layout() {
  const { username } = useLoaderData() as Session;
  const [context, setContext] = useState<HTMLElement | null>(null);
  const [status, setStatus] = useState<HTMLElement | null>(null);
  const content = useRef<HTMLElement>(null);
  const { pathname } = useLocation();
  useEffect(() => content.current?.scrollTo?.(0, 0), [pathname]);
  return (
    <div className="portal">
      <Sidebar username={username} />
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
