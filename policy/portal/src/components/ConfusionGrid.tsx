import { useRef, useState, type KeyboardEvent } from "react";
import { Link } from "react-router";
import { LEFT_OUT, NO_PART, rightText, shareLevel, type ConfusionsData, type GridColumn, type GridRow } from "../confusions";

export type PointedCell = { row: GridRow; column: GridColumn; count: number };

type Props = {
  data: ConfusionsData;
  /** The chosen pair, if any. */
  chosen: { from: string; to: string } | null;
  /** The address that chooses a pair. */
  href: (row: GridRow, column: GridColumn) => string;
  onPoint: (cell: PointedCell | null) => void;
};

const MOVES: Record<string, [number, number]> = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };

/** A cell is right when its row's part is its column's, or no part is left out. */
function isRight(row: GridRow, column: GridColumn): boolean {
  return row.part === column.part || (row.part === NO_PART && column.part === LEFT_OUT);
}

/**
 * A row for each part the placements belong in, then no part, and a column for each row they were put in, then left out.
 *
 * Each cell is a link that chooses its pair, shaded by its share of its row. Only one cell is in the Tab order: the
 * chosen pair, or else the first. The arrow keys move between cells, Home and End to the ends of the row.
 */
export function ConfusionGrid({ data, chosen, href, onPoint }: Props) {
  const [focus, setFocus] = useState<[number, number] | null>(null);
  const links = useRef(new Map<string, HTMLAnchorElement>());
  const chosenAt = chosen === null ? null : ([data.rows.findIndex(({ part }) => part === chosen.from), data.columns.findIndex(({ part }) => part === chosen.to)] as [number, number]);
  const valid = (at: [number, number] | null) => at !== null && at[0] >= 0 && at[1] >= 0 && at[0] < data.rows.length && at[1] < data.columns.length;
  const current = valid(focus) ? focus! : valid(chosenAt) ? chosenAt! : [0, 0];

  function moveTo(r: number, c: number) {
    setFocus([r, c]);
    links.current.get(`${r},${c}`)?.focus();
  }

  function keyDown(event: KeyboardEvent<HTMLAnchorElement>, r: number, c: number) {
    if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      moveTo(r, event.key === "Home" ? 0 : data.columns.length - 1);
      return;
    }
    const move = MOVES[event.key];
    if (!move) return;
    event.preventDefault();
    const [nr, nc] = [r + move[0], c + move[1]];
    if (nr >= 0 && nr < data.rows.length && nc >= 0 && nc < data.columns.length) moveTo(nr, nc);
  }

  return (
    <div className="facts-grid-box">
      <table className="facts-grid confusion-grid" aria-label="Confusions" data-shade="share">
        <thead>
          <tr>
            <td>
              <span className="confusion-corner">Belongs in ↓ · Put in →</span>
            </td>
            {data.columns.map((column) => (
              <th key={column.part} scope="col">
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row, r) => (
            <tr key={row.part}>
              <th scope="row">
                <span className="confusion-part">{row.label}</span>
                <span className="confusion-right">{row.right === null ? "not asked" : `Right ${rightText(row.right)}`}</span>
              </th>
              {data.columns.map((column, c) => {
                const count = row.cells[c];
                const isChosen = chosen !== null && chosen.from === row.part && chosen.to === column.part;
                const cell = { row, column, count };
                return (
                  <td key={column.part} data-level={shareLevel(count, row.placements)} data-right={isRight(row, column) || undefined} data-chosen={isChosen || undefined}>
                    <Link
                      ref={(element) => {
                        if (element) links.current.set(`${r},${c}`, element);
                        else links.current.delete(`${r},${c}`);
                      }}
                      to={href(row, column)}
                      preventScrollReset
                      tabIndex={current[0] === r && current[1] === c ? 0 : -1}
                      aria-label={`${row.label} ${column.part === LEFT_OUT ? "left out" : `put in ${column.label}`}: ${count} of ${row.placements}`}
                      aria-current={isChosen ? "true" : undefined}
                      onKeyDown={(event) => keyDown(event, r, c)}
                      onFocus={() => {
                        setFocus([r, c]);
                        onPoint(cell);
                      }}
                      onBlur={() => onPoint(null)}
                      onPointerEnter={() => onPoint(cell)}
                      onPointerLeave={() => onPoint(null)}
                    >
                      {count}
                    </Link>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
