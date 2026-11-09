import { createContext, useContext, useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";

export type Slots = { context: HTMLElement | null; status: HTMLElement | null };

export const SlotsContext = createContext<Slots>({ context: null, status: null });

/** Put children in the context bar at the top of the main pane. */
export function ContextBar({ children }: { children: ReactNode }) {
  const { context } = useContext(SlotsContext);
  return context ? createPortal(children, context) : null;
}

/** Put children in the status bar at the bottom of the main pane. */
export function StatusBar({ children }: { children: ReactNode }) {
  const { status } = useContext(SlotsContext);
  return status ? createPortal(children, status) : null;
}

/** Name the page in the browser tab, such as "Attempts · Daywarden". */
export function useTitle(page: string): void {
  useEffect(() => {
    document.title = page ? `${page} · Daywarden` : "Daywarden";
  }, [page]);
}
