import { Calendar, ChevronLeft, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import {
  MONTHS,
  WEEKDAYS,
  addDays,
  addMonths,
  dateProblem,
  formatDay,
  longDay,
  monthWeeks,
  parseDay,
  sameDay,
  weekday,
  type Day,
} from "../dates";
import { useExpander } from "../motion";

type Props = {
  /** The policy file's name for the field, which is its label's title. */
  name: string;
  label: string;
  value: string;
  /** The household's today, `yyyy-mm-dd`. */
  today: string;
  changed: boolean;
  onChange: (text: string) => void;
  /** A problem the page finds with a real day, such as one before another field's, shown under the box. */
  problem?: string | null;
};

/** Sent when a calendar opens, so any other that is open closes. */
const OPENING = "date-field-opening";

const MOVES: Record<string, (day: Day, shift: boolean) => Day> = {
  ArrowLeft: (day) => addDays(day, -1),
  ArrowRight: (day) => addDays(day, 1),
  ArrowUp: (day) => addDays(day, -7),
  ArrowDown: (day) => addDays(day, 7),
  Home: (day) => addDays(day, -weekday(day)),
  End: (day) => addDays(day, 6 - weekday(day)),
  PageUp: (day, shift) => addMonths(day, shift ? -12 : -1),
  PageDown: (day, shift) => addMonths(day, shift ? 12 : 1),
};

/**
 * A `yyyy-mm-dd` text box with a calendar to pick the day from.
 *
 * The calendar button, or Alt+Down in the box, opens the calendar under the
 * box, or above it when the content pane has no room below. It opens on the
 * box's day, or on the household's today when the box holds no date.
 */
export function DateField({ name, label, value, today, changed, onChange, problem: outside = null }: Props) {
  const [open, setOpen] = useState(false);
  const { shown, moving, toggle } = useExpander(open, setOpen);
  const selected = parseDay(value);
  const todayDay = parseDay(today) ?? browserToday();
  const [active, setActive] = useState<Day>(todayDay);
  const [above, setAbove] = useState(false);
  const [end, setEnd] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const box = useRef<HTMLInputElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const calendar = useRef<HTMLDivElement>(null);
  const focusDay = useRef(false);
  const id = useId();
  const monthId = `${id}-month`;
  const problemId = `${id}-problem`;
  const problem = dateProblem(value) ?? outside;

  const close = useCallback(
    (then?: "box" | "button") => {
      if (!open) return;
      toggle();
      if (then === "box") box.current?.focus();
      if (then === "button") button.current?.focus();
    },
    [open, toggle],
  );

  const start = () => {
    if (open) return;
    setActive(selected ?? todayDay);
    focusDay.current = true;
    document.dispatchEvent(new CustomEvent(OPENING, { detail: id }));
    toggle();
  };

  const pick = (text: string) => {
    onChange(text);
    close("box");
  };

  useEffect(() => {
    if (!open) return;
    function away(event: PointerEvent) {
      const target = event.target as Node;
      if (!panel.current?.contains(target) && !button.current?.contains(target)) close();
    }
    function other(event: Event) {
      if ((event as CustomEvent<string>).detail !== id) close();
    }
    document.addEventListener("pointerdown", away);
    document.addEventListener(OPENING, other);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener(OPENING, other);
    };
  }, [open, close, id]);

  useEffect(() => {
    if (!open || !focusDay.current) return;
    focusDay.current = false;
    // Scrolling would move the calendar inside its clipped panel while it expands.
    panel.current?.querySelector<HTMLButtonElement>("button[data-active]")?.focus({ preventScroll: true });
  }, [open, active]);

  useLayoutEffect(() => {
    if (!open || !root.current || !calendar.current) return;
    const field = root.current.getBoundingClientRect();
    const pane = (root.current.closest(".content") ?? document.documentElement).getBoundingClientRect();
    const below = pane.bottom - field.bottom;
    setAbove(below < calendar.current.scrollHeight && field.top - pane.top > below);
    setEnd(field.left + calendar.current.scrollWidth > pane.right);
  }, [open]);

  function boxKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.altKey && event.key === "ArrowDown") {
      event.preventDefault();
      start();
    }
  }

  function panelKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      close("button");
    } else if (event.key === "Tab") {
      event.preventDefault();
      const stops = [...(panel.current?.querySelectorAll<HTMLElement>("[data-stop]") ?? [])];
      const at = stops.indexOf(document.activeElement as HTMLElement);
      const next = at === -1 ? 0 : (at + (event.shiftKey ? -1 : 1) + stops.length) % stops.length;
      stops[next]?.focus();
    }
  }

  function gridKey(event: KeyboardEvent<HTMLTableElement>) {
    const move = MOVES[event.key];
    if (!move || event.altKey || event.ctrlKey || event.metaKey) return;
    event.preventDefault();
    focusDay.current = true;
    setActive(move(active, event.shiftKey));
  }

  const turn = (count: number) => setActive(addMonths(active, count));

  return (
    <>
      <label htmlFor={id}>
        <span title={name}>{label}</span>
      </label>
      <div
        className="date-field"
        ref={root}
        data-open={open || undefined}
        data-moving={moving || undefined}
        data-above={above || undefined}
        data-end={end || undefined}
      >
        <input
          id={id}
          ref={box}
          type="text"
          value={value}
          placeholder="yyyy-mm-dd"
          aria-invalid={problem !== null || undefined}
          aria-describedby={problem ? problemId : undefined}
          data-changed={changed || undefined}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={boxKey}
        />
        <button
          type="button"
          ref={button}
          className="icon-button icon-button-quiet"
          aria-label={`Choose ${label}`}
          title={`Choose ${label}`}
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={() => (open ? close() : start())}
        >
          <Calendar aria-hidden="true" />
        </button>
        {shown && (
          <div className="date-panel" ref={panel} inert={!open} role="dialog" aria-label={`Choose ${label}`} onKeyDown={panelKey}>
            <div className="date-calendar" ref={calendar}>
              <div className="date-head">
                <button type="button" className="icon-button icon-button-quiet" aria-label="Previous month" title="Previous month" data-stop onClick={() => turn(-1)}>
                  <ChevronLeft aria-hidden="true" />
                </button>
                <span id={monthId} className="date-month" aria-live="polite">
                  {MONTHS[active.month - 1]} {active.year}
                </span>
                <button type="button" className="icon-button icon-button-quiet" aria-label="Next month" title="Next month" data-stop onClick={() => turn(1)}>
                  <ChevronRight aria-hidden="true" />
                </button>
              </div>
              <table className="date-grid" role="grid" aria-labelledby={monthId} onKeyDown={gridKey}>
                <thead>
                  <tr>
                    {WEEKDAYS.map((weekdayName) => (
                      <th key={weekdayName} scope="col" abbr={weekdayName}>
                        {weekdayName.slice(0, 3)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {monthWeeks(active).map((week, row) => (
                    <tr key={row}>
                      {week.map((day, column) =>
                        day === null ? (
                          <td key={column} />
                        ) : (
                          <td key={column} role="gridcell" aria-selected={sameDay(day, selected)}>
                            <button
                              type="button"
                              tabIndex={sameDay(day, active) ? 0 : -1}
                              aria-label={longDay(day)}
                              title={longDay(day)}
                              aria-current={sameDay(day, todayDay) ? "date" : undefined}
                              data-active={sameDay(day, active) || undefined}
                              data-stop={sameDay(day, active) || undefined}
                              onClick={() => pick(formatDay(day))}
                            >
                              {day.day}
                            </button>
                          </td>
                        ),
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="date-foot">
                <button type="button" className="button button-quiet" data-stop onClick={() => pick(formatDay(todayDay))}>
                  Today
                </button>
                <button type="button" className="button button-quiet" data-stop onClick={() => pick("")}>
                  Clear
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
      {problem && (
        <p id={problemId} className="note note-problem setting-problem">
          {problem}
        </p>
      )}
    </>
  );
}

/** Only for a page whose data has no today, which the service always sends. */
function browserToday(): Day {
  const now = new Date();
  return { year: now.getFullYear(), month: now.getMonth() + 1, day: now.getDate() };
}
