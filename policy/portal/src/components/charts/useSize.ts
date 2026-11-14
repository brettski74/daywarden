import { useLayoutEffect, useRef, useState, type RefObject } from "react";

export type Size = { width: number; height: number };

/** The size a chart is drawn at before its box has been measured, and in a browser without ResizeObserver. */
export const FALLBACK_SIZE: Size = { width: 720, height: 360 };

/** Measure an element's content box, and measure it again whenever it changes size. */
export function useSize<T extends HTMLElement>(): [RefObject<T | null>, Size] {
  const ref = useRef<T>(null);
  const [size, setSize] = useState<Size>(FALLBACK_SIZE);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const width = Math.floor(entry.contentRect.width);
      const height = Math.floor(entry.contentRect.height);
      if (width > 0 && height > 0) setSize((before) => (before.width === width && before.height === height ? before : { width, height }));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, size];
}
