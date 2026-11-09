import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Return how long an expand or collapse takes, in milliseconds.
 *
 * The time is --expand-duration in the layout stylesheet, so CSS
 * transitions and the code that waits for them use the same value. It is
 * 0 when the browser asks for reduced motion, or when no stylesheet sets it.
 */
export function expandDuration(): number {
  const value = getComputedStyle(document.documentElement).getPropertyValue("--expand-duration").trim();
  const match = /^([\d.]+)(ms|s)$/.exec(value);
  if (!match) return 0;
  return Number(match[1]) * (match[2] === "s" ? 1000 : 1);
}

/**
 * Track something that expands and collapses with the shared animation.
 *
 * ``expanded`` is where it is heading, and it changes at once so the CSS
 * transition can start. ``shown`` says whether the expanded content is
 * rendered. It turns on at once when expanding and turns off only when a
 * collapse has finished, so the content can fade and slide out first.
 * ``moving`` is true while the animation runs.
 */
export function useExpander(expanded: boolean, setExpanded: (value: boolean) => void) {
  const [shown, setShown] = useState(expanded);
  const [moving, setMoving] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const toggle = useCallback(() => {
    const next = !expanded;
    const duration = expandDuration();
    window.clearTimeout(timer.current);
    if (next) setShown(true);
    setExpanded(next);
    if (duration === 0) {
      setShown(next);
      setMoving(false);
      return;
    }
    setMoving(true);
    timer.current = window.setTimeout(() => {
      setMoving(false);
      setShown(next);
    }, duration);
  }, [expanded, setExpanded]);

  return { shown, moving, toggle };
}
