import { useRef, useState, type KeyboardEvent } from "react";
import { Link } from "react-router";
import type { Fact, FactsData, Shading } from "../facts";

type Props = {
  data: FactsData;
  label: string;
  shading: Shading;
  /** The chosen fact's key, ``m,n``, if any. */
  chosen: string | null;
  /** The address that chooses a fact. */
  href: (fact: Fact) => string;
  /** The fact pointed at or focused, or null when the pointer and focus leave it. */
  onPoint: (fact: Fact | null) => void;
};

const keyOf = (m: number, n: number) => `${m},${n}`;

const MOVES: Record<string, [number, number]> = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };

/**
 * A row for each left number and a column for each right number asked, each asked fact a link that chooses it.
 *
 * Only one cell is in the Tab order: the chosen fact, or else the first. The arrow keys move to the next
 * asked fact that way, Home and End to the first and last in the row.
 */
export function FactGrid({ data, label, shading, chosen, href, onPoint }: Props) {
  const byKey = new Map(data.facts.map((fact) => [keyOf(fact.m, fact.n), fact]));
  const first = data.facts[0] ? keyOf(data.facts[0].m, data.facts[0].n) : null;
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const current = focusKey !== null && byKey.has(focusKey) ? focusKey : chosen !== null && byKey.has(chosen) ? chosen : first;
  const links = useRef(new Map<string, HTMLAnchorElement>());

  function moveTo(key: string) {
    setFocusKey(key);
    links.current.get(key)?.focus();
  }

  function keyDown(event: KeyboardEvent<HTMLAnchorElement>, fact: Fact) {
    const row = data.rows.indexOf(fact.m);
    const column = data.columns.indexOf(fact.n);
    if (event.key === "Home" || event.key === "End") {
      const asked = data.columns.filter((n) => byKey.has(keyOf(fact.m, n)));
      const n = event.key === "Home" ? asked[0] : asked[asked.length - 1];
      event.preventDefault();
      moveTo(keyOf(fact.m, n));
      return;
    }
    const move = MOVES[event.key];
    if (!move) return;
    event.preventDefault();
    let [r, c] = [row + move[0], column + move[1]];
    while (r >= 0 && r < data.rows.length && c >= 0 && c < data.columns.length) {
      const key = keyOf(data.rows[r], data.columns[c]);
      if (byKey.has(key)) {
        moveTo(key);
        return;
      }
      r += move[0];
      c += move[1];
    }
  }

  return (
    <div className="facts-grid-box">
      <table className="facts-grid" aria-label={label} data-shade={shading.kind}>
        <thead>
          <tr>
            <td />
            {data.columns.map((n) => (
              <th key={n} scope="col">
                {n}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((m) => (
            <tr key={m}>
              <th scope="row">{m}</th>
              {data.columns.map((n) => {
                const key = keyOf(m, n);
                const fact = byKey.get(key);
                if (!fact) return <td key={n} />;
                const level = shading.level(fact);
                return (
                  <td key={n} data-level={level ?? "none"} data-chosen={key === chosen || undefined}>
                    <Link
                      ref={(element) => {
                        if (element) links.current.set(key, element);
                        else links.current.delete(key);
                      }}
                      to={href(fact)}
                      preventScrollReset
                      tabIndex={key === current ? 0 : -1}
                      aria-label={`${fact.text}, right ${fact.right} of ${fact.asked}`}
                      aria-current={key === chosen ? "true" : undefined}
                      onKeyDown={(event) => keyDown(event, fact)}
                      onFocus={() => {
                        setFocusKey(key);
                        onPoint(fact);
                      }}
                      onBlur={() => onPoint(null)}
                      onPointerEnter={() => onPoint(fact)}
                      onPointerLeave={() => onPoint(null)}
                    >
                      <span className="facts-cell-question">{fact.cell}</span>
                      <span className="facts-cell-count">
                        {fact.right}/{fact.asked}
                      </span>
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
