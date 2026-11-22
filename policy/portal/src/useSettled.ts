import { useEffect, useState } from "react";

/** How long typing must pause before the password advice is worked out again (S046). */
export const SETTLE_MS = 1000;

/**
 * The value as it was when it last stayed unchanged for `ms`. Until then it
 * keeps the earlier settled value, so what depends on it does not change with
 * every keystroke.
 */
export function useSettled<T>(value: T, ms = SETTLE_MS): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return settled;
}
