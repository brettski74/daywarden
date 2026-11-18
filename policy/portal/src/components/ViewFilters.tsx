import { useEffect, useState } from "react";
import { OUTCOMES, SETS, labelsOf, toggledIn, valueOf, type PeriodData, type View } from "../attempts";
import { NOT_A_DATE, parseDay } from "../dates";
import { useExpander } from "../motion";
import { RANGES, type RangeName } from "../usage";
import { DateField } from "./DateField";
import { MultiSelect } from "./MultiSelect";

/** The problems under the Custom period's From and To boxes. A box whose own text is not a date says so itself. */
function dateProblems(from: string, to: string): { from: string | null; to: string | null } {
  const first = parseDay(from);
  const last = parseDay(to);
  return {
    from: from.trim() === "" ? NOT_A_DATE : null,
    to: to.trim() === "" ? NOT_A_DATE : first !== null && last !== null && to.trim() < from.trim() ? "To is before From." : null,
  };
}

/**
 * The Period, Set, and Outcome controls of the attempts page and a task's trend, on the context bar's second line.
 *
 * The Period offers the usage graph's ranges. Custom slides open its From and To boxes, and a change
 * is sent once both are real days in order.
 */
export function ViewFilters({ view, period, onChange }: { view: View; period: PeriodData; onChange: (patch: Partial<View>) => void }) {
  const [dates, setDates] = useState({ from: view.from, to: view.to });
  const [held, setHeld] = useState(view);
  // The boxes keep what is typed until the view's own days change, such as on Back.
  if (held !== view) {
    setHeld(view);
    if (held.from !== view.from || held.to !== view.to) setDates({ from: view.from, to: view.to });
  }
  const custom = view.range === "custom";
  const [open, setOpen] = useState(custom);
  const { shown, moving, toggle } = useExpander(open, setOpen);
  useEffect(() => {
    if (custom !== open) toggle();
  }, [custom, open, toggle]);

  function chooseRange(range: RangeName) {
    if (range === "custom") {
      const from = period.days?.from ?? period.today;
      const to = period.days?.to ?? period.today;
      setDates({ from, to });
      onChange({ range, from, to });
    } else onChange({ range, from: "", to: "" });
  }

  function typeDate(which: "from" | "to", text: string) {
    const next = { ...dates, [which]: text };
    setDates(next);
    const problems = dateProblems(next.from, next.to);
    const fine = parseDay(next.from) !== null && parseDay(next.to) !== null && problems.from === null && problems.to === null;
    if (fine && (next.from.trim() !== view.from || next.to.trim() !== view.to)) onChange({ from: next.from.trim(), to: next.to.trim() });
  }

  const problems = dateProblems(dates.from, dates.to);
  return (
    <div className="bar-filters">
      <label className="bar-field">
        Period
        <select value={view.range} onChange={(event) => chooseRange(event.target.value as RangeName)}>
          {RANGES.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {shown && (
        <div className="bar-dates" data-open={open || undefined} data-moving={moving || undefined} inert={!open}>
          <div className="bar-dates-inner">
            <div className="bar-date">
              <DateField name="from" label="From" value={dates.from} today={period.today} changed={false} problem={problems.from} onChange={(text) => typeDate("from", text)} />
            </div>
            <div className="bar-date">
              <DateField name="to" label="To" value={dates.to} today={period.today} changed={false} problem={problems.to} onChange={(text) => typeDate("to", text)} />
            </div>
          </div>
        </div>
      )}
      <MultiSelect
        label="Set"
        options={SETS.map(([, label]) => label)}
        selected={labelsOf(view.set, SETS)}
        onToggle={(label) => onChange({ set: toggledIn(view.set, valueOf(label, SETS), SETS) })}
      />
      <MultiSelect
        label="Outcome"
        options={OUTCOMES.map(([, label]) => label)}
        selected={labelsOf(view.outcome, OUTCOMES)}
        onToggle={(label) => onChange({ outcome: toggledIn(view.outcome, valueOf(label, OUTCOMES), OUTCOMES) })}
      />
    </div>
  );
}
