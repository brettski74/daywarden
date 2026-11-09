import { useCallback, useEffect, useState } from "react";

export const MIN_REM = 12.5;
export const DEFAULT_REM = 15;
export const KEY_STEP = 16;
export const WIDTH_KEY = "daywarden.portal.sidebarWidth";
export const COLLAPSED_KEY = "daywarden.portal.sidebarCollapsed";
export const TASKS_KEY = "daywarden.portal.tasksExpanded";

/** Return the narrowest and widest the sidebar may be in this window, in pixels. */
export function widthLimits(windowWidth: number, remPx: number): { min: number; max: number } {
  const min = MIN_REM * remPx;
  return { min, max: Math.max(min, windowWidth / 3) };
}

/** Return width held between 12.5rem and a third of the window. A third narrower than 12.5rem gives 12.5rem. */
export function clampWidth(width: number, windowWidth: number, remPx: number): number {
  const { min, max } = widthLimits(windowWidth, remPx);
  return Math.round(Math.min(Math.max(width, min), max));
}

export type StoredSidebar = { width: number | null; collapsed: boolean };

export function loadSidebar(storage: Storage): StoredSidebar {
  const raw = Number(storage.getItem(WIDTH_KEY));
  return {
    width: Number.isFinite(raw) && raw > 0 ? raw : null,
    collapsed: storage.getItem(COLLAPSED_KEY) === "true",
  };
}

function rootFontPx(): number {
  const size = parseFloat(getComputedStyle(document.documentElement).fontSize);
  return Number.isFinite(size) && size > 0 ? size : 16;
}

/**
 * Whether the Task Administration list is expanded, kept in localStorage.
 *
 * It is always expanded while a task page is open, and opening one keeps it
 * expanded afterwards.
 */
export function useTaskList(onTaskPage: boolean) {
  const [stored, setStored] = useState(() => localStorage.getItem(TASKS_KEY) === "true");

  useEffect(() => {
    if (onTaskPage && !stored) {
      setStored(true);
      save(TASKS_KEY, "true");
    }
  }, [onTaskPage, stored]);

  const setExpanded = useCallback((value: boolean) => {
    setStored(value);
    save(TASKS_KEY, String(value));
  }, []);

  return { expanded: stored || onTaskPage, setExpanded };
}

function save(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Private windows can refuse storage. The sidebar still works for this visit.
  }
}

/**
 * The sidebar's width and whether it is collapsed, kept in localStorage.
 *
 * ``width`` is the width on screen, held within the limits for the current
 * window. The width the parent chose is kept while collapsed, so expanding
 * brings it back.
 */
export function useSidebar() {
  const [stored] = useState(() => loadSidebar(localStorage));
  const [remPx] = useState(rootFontPx);
  const [chosen, setChosen] = useState(() => stored.width ?? DEFAULT_REM * remPx);
  const [collapsed, setCollapsedState] = useState(stored.collapsed);
  const [windowWidth, setWindowWidth] = useState(() => window.innerWidth);

  useEffect(() => {
    const resized = () => setWindowWidth(window.innerWidth);
    window.addEventListener("resize", resized);
    return () => window.removeEventListener("resize", resized);
  }, []);

  const limits = widthLimits(windowWidth, remPx);
  const width = clampWidth(chosen, windowWidth, remPx);

  const resize = useCallback(
    (next: number, keep = true) => {
      const held = clampWidth(next, window.innerWidth, remPx);
      setChosen(held);
      if (keep) save(WIDTH_KEY, String(held));
    },
    [remPx],
  );

  const setCollapsed = useCallback((value: boolean) => {
    setCollapsedState(value);
    save(COLLAPSED_KEY, String(value));
  }, []);

  return { width, limits, collapsed, resize, setCollapsed };
}
