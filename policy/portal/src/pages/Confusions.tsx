import { useState } from "react";
import { Link, useLoaderData, useLocation, useNavigate, type LoaderFunctionArgs, type ShouldRevalidateFunctionArgs } from "react-router";
import { api, pageOf } from "../api";
import { labelsOf, toggledIn, valueOf, viewQuery, type View } from "../attempts";
import { ConfusionGrid, type PointedCell } from "../components/ConfusionGrid";
import { MultiSelect } from "../components/MultiSelect";
import { ViewFilters } from "../components/ViewFilters";
import {
  COLUMNS,
  PAGE_KEYS,
  SHARE_LEVELS,
  TRIES,
  TRY_LABELS,
  cellText,
  chosenWord,
  confusionsAddress,
  dataSearch,
  filtersIn,
  insteadText,
  pageChoice,
  pairPlacements,
  putLabel,
  rightText,
  sortWords,
  sortedBy,
  withChoice,
  wordText,
  type Ask,
  type ConfusionWord,
  type ConfusionsData,
  type ConfusionsReport,
  type Filters,
} from "../confusions";
import { ContextBar, StatusBar, useTitle } from "../slots";

/** The data endpoint takes the view and the Task, Pool, and Try filters. The chosen pair, the chosen word, and the sort are the page's alone. */
export async function confusionsLoader({ request }: LoaderFunctionArgs): Promise<ConfusionsReport> {
  return api<ConfusionsReport>(`/attempts/parts-of-speech${dataSearch(new URL(request.url).search)}`, { page: pageOf(request), signal: request.signal });
}

/** Choosing a pair, a word, or the sort changes only the address, so the data is not asked for again. */
export function confusionsShouldRevalidate({ currentUrl, nextUrl, defaultShouldRevalidate }: ShouldRevalidateFunctionArgs) {
  if (currentUrl.pathname === nextUrl.pathname && dataSearch(currentUrl.search) === dataSearch(nextUrl.search)) return false;
  return defaultShouldRevalidate;
}

/** The sentence with one word marked. */
function Marked({ ask, position }: { ask: Ask; position: number }) {
  return (
    <span className="confusion-sentence">
      {ask.pieces.map((piece, index) => (piece.word === position ? <mark key={index}>{piece.text}</mark> : <span key={index}>{piece.text}</span>))}
    </span>
  );
}

function ShareKey() {
  return (
    <ul className="facts-key" data-shade="share" aria-label="Key">
      {SHARE_LEVELS.map(({ level, label }) => (
        <li key={level}>
          <span className="facts-swatch" data-level={level} aria-hidden="true" />
          {label}
        </li>
      ))}
      <li>
        <span className="facts-swatch confusion-right-swatch" aria-hidden="true" />
        Right: the part, or no part left out
      </li>
    </ul>
  );
}

/** The chosen pair's placements, newest first, each opening its attempt. */
function ChosenPair({ data, from, to }: { data: ConfusionsData; from: string; to: string }) {
  const row = data.rows.find(({ part }) => part === from);
  const column = data.columns.find(({ part }) => part === to);
  if (!row || !column) return null;
  const found = pairPlacements(data, from, to);
  const heading = cellText(row, column, found.length);
  return (
    <section className="facts-chosen" aria-labelledby="confusion-pair-heading">
      <h2 id="confusion-pair-heading">{heading}</h2>
      {found.length === 0 ? (
        <p>No placements.</p>
      ) : (
        <div className="facts-list-box">
          <table className="records" aria-label={`Placements of ${row.label} ${to === "left_out" ? "left out" : `put in ${column.label}`}`}>
            <thead>
              <tr>
                <th scope="col">Sentence</th>
                <th scope="col">Started</th>
                <th scope="col">Task</th>
                <th scope="col">Try</th>
              </tr>
            </thead>
            <tbody>
              {found.map(({ key, ask, position, try: number }) => (
                <tr key={key}>
                  <td>
                    <Link to={`/attempts/${ask.attempt}`}>
                      <Marked ask={ask} position={position} />
                    </Link>
                  </td>
                  <td>{ask.started}</td>
                  <td>{ask.task}</td>
                  <td>{TRY_LABELS[number - 1] ?? number}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** The sentences that asked the chosen word, newest first, with where he put it on each try. */
function ChosenWord({ data, word }: { data: ConfusionsData; word: ConfusionWord }) {
  return (
    <section className="facts-chosen" aria-labelledby="confusion-word-heading">
      <h2 id="confusion-word-heading">{wordText(word)}</h2>
      <div className="facts-list-box">
        <table className="records" aria-label={`Sentences that asked ${wordText(word)}`}>
          <thead>
            <tr>
              <th scope="col">Sentence</th>
              <th scope="col">Started</th>
              <th scope="col">Task</th>
              <th scope="col">Put in</th>
            </tr>
          </thead>
          <tbody>
            {word.asks.map(([ref, position]) => {
              const ask = data.asks[String(ref)];
              if (!ask) return null;
              return (
                <tr key={`${ref}-${position}`}>
                  <td>
                    <Link to={`/attempts/${ask.attempt}`}>
                      <Marked ask={ask} position={position} />
                    </Link>
                  </td>
                  <td>{ask.started}</td>
                  <td>{ask.task}</td>
                  <td>{ask.tries.map((placed) => putLabel(ask, placed[position])).join(", ")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** One client group's parts of speech placements across its attempts in the period: the grid, the chosen pair, the word list, and the chosen word. */
export function Confusions() {
  const report = useLoaderData() as ConfusionsReport;
  const location = useLocation();
  const navigate = useNavigate();
  useTitle("Parts of speech confusions · Attempts");

  const [held, setHeld] = useState(report);
  const [draft, setDraft] = useState<View>(report.view);
  const [pointed, setPointed] = useState<PointedCell | null>(null);
  if (held !== report) {
    setHeld(report);
    setDraft(report.view);
    setPointed(null);
  }

  const own = () => [...new URLSearchParams(location.search)].filter(([key]) => PAGE_KEYS.includes(key));
  function change(patch: Partial<View>) {
    const next = { ...draft, ...patch };
    setDraft(next);
    navigate({ search: viewQuery(next, [...filtersIn(location.search), ...own()]) });
  }
  const filters: Filters = { task: report.choices.task, pool: report.choices.pool, try: report.choices.try.map(String) };
  const filter = (patch: Partial<Filters>) => navigate(confusionsAddress(report.view, { ...filters, ...patch }, report, own()));
  const taskLabels: [string, string][] = report.tasks_offered.map(({ name, in_policy }) => [name, in_policy ? name : `${name} (not in the policy)`]);
  const poolLabels: [string, string][] = report.pools_offered.map(({ id, name }) => [id, name]);

  const choice = pageChoice(location.search);
  const data = report.confusions;
  const words = sortWords(data?.words ?? [], choice.sort, choice.dir);
  const chosen = chosenWord(words, choice.word);

  return (
    <>
      <ContextBar>
        <nav aria-label="Where you are" className="crumbs">
          <ol>
            <li>
              <Link to={{ pathname: "/attempts", search: viewQuery(report.view) }}>Attempts</Link>
            </li>
            {report.client && <li>{report.client}</li>}
            <li aria-current="page">
              <h1 className="bar-title">Parts of speech confusions</h1>
            </li>
          </ol>
        </nav>
        <ViewFilters view={draft} period={report} onChange={change} />
        <div className="bar-filters">
          <MultiSelect
            label="Task"
            options={taskLabels.map(([, label]) => label)}
            selected={labelsOf(filters.task, taskLabels)}
            onToggle={(label) => filter({ task: toggledIn(filters.task, valueOf(label, taskLabels), taskLabels) })}
          />
          <MultiSelect
            label="Pool"
            options={poolLabels.map(([, label]) => label)}
            selected={labelsOf(filters.pool, poolLabels)}
            onToggle={(label) => filter({ pool: toggledIn(filters.pool, valueOf(label, poolLabels), poolLabels) })}
          />
          <MultiSelect
            label="Try"
            options={TRIES.map(([, label]) => label)}
            selected={labelsOf(filters.try, TRIES)}
            onToggle={(label) => filter({ try: toggledIn(filters.try, valueOf(label, TRIES), TRIES) })}
          />
        </div>
      </ContextBar>

      {report.message !== null && <p>{report.message}</p>}
      {data !== null && (
        <>
          <ShareKey />
          <div className="facts-top">
            <ConfusionGrid
              data={data}
              chosen={choice.pair}
              href={(row, column) => withChoice(location.search, { pair: { from: row.part, to: column.part } })}
              onPoint={setPointed}
            />
            <div className="facts-readout" aria-live="polite">
              {pointed === null ? <p>Point at a cell to see its placements.</p> : <strong>{cellText(pointed.row, pointed.column, pointed.count)}</strong>}
            </div>
          </div>
          {choice.pair !== null && <ChosenPair data={data} from={choice.pair.from} to={choice.pair.to} />}

          <h2>Words</h2>
          <div className="facts-list-box">
            <table className="records facts-list confusion-words" aria-label="Words">
              <thead>
                <tr>
                  {COLUMNS.map(({ key, label, text }) => {
                    const active = choice.sort === key;
                    const arrow = active ? (choice.dir === "asc" ? " ↑" : " ↓") : "";
                    return (
                      <th key={key} scope="col" className={text ? "facts-list-text" : undefined} aria-sort={active ? (choice.dir === "asc" ? "ascending" : "descending") : "none"}>
                        <button type="button" className="records-sort" onClick={() => navigate({ search: sortedBy(location.search, key) }, { preventScrollReset: true })}>
                          <span className="records-sort-label">{label}</span>
                          {arrow && (
                            <span className="records-sort-arrow" aria-hidden="true">
                              {arrow}
                            </span>
                          )}
                        </button>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {words.map((word) => {
                  const to = { search: withChoice(location.search, { word: { word: word.word, part: word.part } }) };
                  const isChosen = word.id === chosen?.id;
                  return (
                    <tr
                      key={word.id}
                      data-chosen={isChosen || undefined}
                      onClick={(event) => {
                        if (!(event.target instanceof Element) || !event.target.closest("a")) navigate(to, { preventScrollReset: true });
                      }}
                    >
                      <td className="facts-list-text">
                        <Link to={to} preventScrollReset aria-current={isChosen ? "true" : undefined}>
                          {word.word}
                        </Link>
                      </td>
                      <td className="facts-list-text">{word.part_label}</td>
                      <td>{word.sentences}</td>
                      <td>{word.placements}</td>
                      <td>{rightText(word.right)}</td>
                      <td className="facts-list-text">{insteadText(word)}</td>
                      <td className="facts-list-text">{word.last_misplaced ?? ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {chosen !== null && <ChosenWord data={data} word={chosen} />}
        </>
      )}

      <StatusBar>
        {report.notes.map((note) => (
          <span key={note}>{note}</span>
        ))}
        {data !== null && <span>{data.words.length === 1 ? "1 word." : `${data.words.length} words.`}</span>}
        <span>{report.range ? `${report.range}. ${report.times}` : report.times}</span>
      </StatusBar>
    </>
  );
}
