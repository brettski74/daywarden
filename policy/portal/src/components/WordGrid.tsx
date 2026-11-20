import { Check, Minus, RotateCcw, X } from "lucide-react";
import { useRef, useState, type KeyboardEvent } from "react";
import { Link } from "react-router";
import { resultLabel, shortDay, type Result, type Word, type WordAttempt, type WordsData } from "../spellingWords";

/** What a cell holds: the word, the attempt's column, and what he did there, or null when it was not asked. */
export type WordCell = { word: Word; id: number; asked: WordAttempt | null };

type Props = {
  data: WordsData;
  /** The words in the list's order. */
  words: Word[];
  chosen: string | null;
  /** The address that chooses a word. */
  choose: (word: Word) => string;
  onPoint: (cell: WordCell | null) => void;
};

export const RESULT_ICONS = { first_time: Check, after_miss: RotateCcw, missed: X, not_asked: Minus };

const MOVES: Record<string, [number, number]> = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };

/**
 * A row for each word and a column for each attempt that asked any of them, oldest on the left.
 *
 * Only one cell is in the Tab order: the last time the chosen word was asked, or else the first row's
 * newest cell. The arrow keys move between cells, Home and End to the ends of the row. An asked cell is
 * a link to its attempt.
 */
export function WordGrid({ data, words, chosen, choose, onPoint }: Props) {
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const cells = useRef(new Map<string, HTMLElement>());
  const keyOf = (row: number, column: number) => `${row},${column}`;
  const columns = data.columns;
  const last = columns.length - 1;
  const chosenRow = words.findIndex((word) => word.word === chosen);
  const fallback = keyOf(Math.max(chosenRow, 0), last);
  const current = focusKey !== null && cells.current.has(focusKey) ? focusKey : fallback;

  function moveTo(row: number, column: number) {
    const key = keyOf(row, column);
    setFocusKey(key);
    cells.current.get(key)?.focus();
  }

  function keyDown(event: KeyboardEvent<HTMLElement>, row: number, column: number) {
    if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      moveTo(row, event.key === "Home" ? 0 : last);
      return;
    }
    const move = MOVES[event.key];
    if (!move) return;
    event.preventDefault();
    const [r, c] = [row + move[0], column + move[1]];
    if (r >= 0 && r < words.length && c >= 0 && c <= last) moveTo(r, c);
  }

  return (
    <div className="words-grid-box">
      <table className="words-grid" aria-label="Words by attempt">
        <thead>
          <tr>
            <td />
            {columns.map((id) => (
              <th key={id} scope="col">
                {shortDay(data.attempts[String(id)]?.day ?? "")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {words.map((word, row) => {
            const byId = new Map(word.attempts.map((each) => [each.id, each]));
            return (
              <tr key={word.word} data-chosen={word.word === chosen || undefined}>
                <th scope="row">
                  <Link to={choose(word)} preventScrollReset aria-current={word.word === chosen ? "true" : undefined}>
                    {word.key}
                  </Link>
                </th>
                {columns.map((id, column) => {
                  const key = keyOf(row, column);
                  const asked = byId.get(id) ?? null;
                  const result: Result | "not_asked" = asked?.result ?? "not_asked";
                  const Icon = RESULT_ICONS[result];
                  const started = data.attempts[String(id)]?.started ?? "";
                  const shared = {
                    ref: (element: HTMLElement | null) => {
                      if (element) cells.current.set(key, element);
                      else cells.current.delete(key);
                    },
                    tabIndex: key === current ? 0 : -1,
                    "aria-label": `${word.key}, ${started}, ${resultLabel(asked?.result ?? null)}`,
                    onKeyDown: (event: KeyboardEvent<HTMLElement>) => keyDown(event, row, column),
                    onFocus: () => {
                      setFocusKey(key);
                      onPoint({ word, id, asked });
                    },
                    onBlur: () => onPoint(null),
                    onPointerEnter: () => onPoint({ word, id, asked }),
                    onPointerLeave: () => onPoint(null),
                  };
                  return (
                    <td key={id} data-result={result}>
                      {asked ? (
                        <Link to={`/attempts/${id}`} {...shared}>
                          <Icon aria-hidden="true" />
                        </Link>
                      ) : (
                        <span role="img" {...shared}>
                          <Icon aria-hidden="true" />
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
