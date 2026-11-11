import { CircleX, SquareMinus, SquarePlus } from "lucide-react";
import { Fragment, useCallback, useLayoutEffect, useRef, useState, type FocusEvent, type KeyboardEvent, type ReactNode } from "react";
import { BOX_FIELDS, BOX_LABELS, boxChanged, isEmpty, newRow, type Box, type NumberRow } from "../numberTable";

type Props = {
  /** The table's name, such as Differences, and the field it writes, such as difference. */
  label: string;
  field: string;
  rows: NumberRow[];
  /** The rows each row's origin refers to, for the change marks, or null when every row is new. */
  originals: NumberRow[] | null;
  /** Each row's problems, in table order. */
  problems: string[][];
  /** Whether rows have their own Min, Max, and Multiples Only. */
  bounds?: boolean;
  /** What an empty Min and Max stand for, and the task's own Multiples Only. */
  placeholders?: { min: string; max: string; multiples: boolean };
  onRows: (change: (rows: NumberRow[]) => NumberRow[]) => void;
  /** Shown above the table, such as a note that the default list is in use. */
  above?: ReactNode;
  /** Shown beside Add row. */
  beside?: ReactNode;
  /** Shown under the table, such as the problem of a table with no rows. */
  below?: ReactNode;
};

type Focus = { key: string; select?: boolean };

/**
 * A weighted list of numbers, one row per entry, filled in from the keyboard.
 *
 * Enter moves to the next row's From, and adds a row after the last one that
 * is not empty. A row left empty is removed as soon as the focus leaves it.
 */
export function WeightedTable(props: Props) {
  const { label, field, rows, originals, problems, bounds = false, placeholders } = props;
  const root = useRef<HTMLDivElement>(null);
  const focusing = useRef<Focus | null>(null);
  const [, setTick] = useState(0);
  const latest = useRef(props);
  latest.current = props;
  const boxes: Box[] = bounds ? ["from", "to", "weight", "min", "max"] : ["from", "to", "weight"];
  const columns = boxes.length + (bounds ? 2 : 1);

  const focusOn = useCallback((key: string, select = false) => {
    focusing.current = { key, select };
    setTick((tick) => tick + 1);
  }, []);

  useLayoutEffect(() => {
    const want = focusing.current;
    const element = want && root.current?.querySelector<HTMLElement>(`[data-focus="${want.key}"]`);
    if (!want || !element) return;
    focusing.current = null;
    element.focus();
    if (want.select && element instanceof HTMLInputElement) element.select();
  });

  const addRow = () => {
    const row = newRow();
    props.onRows((current) => [...current, row]);
    focusOn(`from:${row.id}`);
  };

  const removeRow = (id: string) => {
    const now = latest.current.rows;
    const next = now[now.findIndex((row) => row.id === id) + 1];
    props.onRows((current) => current.filter((row) => row.id !== id));
    focusOn(next ? `from:${next.id}` : "addrow", Boolean(next));
  };

  const enter = (row: NumberRow, event: KeyboardEvent) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const index = rows.findIndex((found) => found.id === row.id);
    const next = rows[index + 1];
    if (next) focusOn(`from:${next.id}`, true);
    else if (!isEmpty(row)) addRow();
    else focusOn("addrow");
  };

  const tabPastEnd = (row: NumberRow, event: KeyboardEvent) => {
    if (event.key !== "Tab" || event.shiftKey || row.id !== rows[rows.length - 1]?.id || isEmpty(row)) return;
    event.preventDefault();
    addRow();
  };

  const left = (id: string, event: FocusEvent<HTMLTableRowElement>) => {
    const going = event.relatedTarget;
    if (going instanceof Node && event.currentTarget.contains(going)) return;
    if (going === null && !document.hasFocus()) return;
    const row = latest.current.rows.find((found) => found.id === id);
    if (row && isEmpty(row)) latest.current.onRows((current) => current.filter((found) => found.id !== id));
  };

  const setBox = (id: string, box: Box | "multiples", text: string) =>
    props.onRows((current) => current.map((row) => (row.id === id ? { ...row, [box]: text } : row)));

  const placeholder = (box: Box) => (box === "weight" ? "1" : box === "min" ? placeholders?.min : box === "max" ? placeholders?.max : undefined);

  return (
    <div className="number-list" ref={root}>
      <h2 className="number-title" title={field}>
        {label}
      </h2>
      {props.above}
      <table className="number-table" aria-label={label}>
        <thead>
          <tr>
            {boxes.map((box) => (
              <th key={box} scope="col" title={BOX_FIELDS[box]}>
                {BOX_LABELS[box]}
              </th>
            ))}
            {bounds && (
              <th scope="col" title={BOX_FIELDS.multiples}>
                Multiples Only
              </th>
            )}
            <th scope="col" aria-label="Remove" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const original = row.origin === null || originals === null ? undefined : originals[row.origin];
            const found = problems[index] ?? [];
            return (
              <Fragment key={row.id}>
                <tr aria-label={`Row ${index + 1}`} data-changed={original === undefined || undefined} onBlur={(event) => left(row.id, event)}>
                  {boxes.map((box) => (
                    <td key={box}>
                      <input
                        type="text"
                        inputMode="numeric"
                        aria-label={BOX_LABELS[box]}
                        value={row[box]}
                        placeholder={placeholder(box)}
                        data-focus={box === "from" ? `from:${row.id}` : undefined}
                        data-changed={boxChanged(row, original, box) || undefined}
                        onChange={(event) => setBox(row.id, box, event.target.value)}
                        onKeyDown={(event) => enter(row, event)}
                      />
                    </td>
                  ))}
                  {bounds && (
                    <td>
                      <select
                        aria-label="Multiples Only"
                        value={row.multiples}
                        data-changed={boxChanged(row, original, "multiples") || undefined}
                        onChange={(event) => setBox(row.id, "multiples", event.target.value)}
                        onKeyDown={(event) => enter(row, event)}
                      >
                        <option value="">Task's ({placeholders?.multiples ? "Yes" : "No"})</option>
                        <option value="yes">Yes</option>
                        <option value="no">No</option>
                      </select>
                    </td>
                  )}
                  <td>
                    <button
                      type="button"
                      className="icon-button icon-button-quiet"
                      aria-label="Remove row"
                      title="Remove row"
                      onClick={() => removeRow(row.id)}
                      onKeyDown={(event) => tabPastEnd(row, event)}
                    >
                      <SquareMinus aria-hidden="true" />
                    </button>
                  </td>
                </tr>
                {found.length > 0 && (
                  <tr className="number-problems">
                    <td colSpan={columns}>
                      <ul className="notes">
                        {found.map((problem) => (
                          <li key={problem} className="note note-problem">
                            <CircleX aria-hidden="true" />
                            {problem}
                          </li>
                        ))}
                      </ul>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
      <div className="number-under">
        <button type="button" className="button button-quiet" data-focus="addrow" onClick={addRow}>
          <SquarePlus aria-hidden="true" />
          Add row
        </button>
        {props.beside}
      </div>
      {props.below}
    </div>
  );
}

/** A problem or note shown under a table or a setting. */
export function Note({ problem = false, children }: { problem?: boolean; children: ReactNode }) {
  return (
    <p className={problem ? "note note-problem" : "note"}>
      {problem && <CircleX aria-hidden="true" />}
      {children}
    </p>
  );
}
