import { useState } from "react";
import { Link, useLoaderData, useLocation, useNavigate, type LoaderFunctionArgs, type ShouldRevalidateFunctionArgs } from "react-router";
import { api, pageOf } from "../api";
import { labelsOf, toggledIn, valueOf, viewQuery, type View } from "../attempts";
import { MultiSelect } from "../components/MultiSelect";
import { ViewFilters } from "../components/ViewFilters";
import { RESULT_ICONS, WordGrid, type WordCell } from "../components/WordGrid";
import { ContextBar, StatusBar, useTitle } from "../slots";
import {
  COLUMNS,
  PAGE_KEYS,
  POOLS,
  RESULTS,
  dataSearch,
  filtersIn,
  medianText,
  misspellingText,
  pageChoice,
  poolText,
  resultLabel,
  sortWords,
  sortedBy,
  thisWeekAddress,
  withChoice,
  wordsAddress,
  type Word,
  type WordsData,
  type WordsReport,
} from "../spellingWords";

/** The data endpoint takes the view and the Task and Pool filters. The chosen word and the sort are the page's alone. */
export async function wordsLoader({ request }: LoaderFunctionArgs): Promise<WordsReport> {
  return api<WordsReport>(`/attempts/words${dataSearch(new URL(request.url).search)}`, { page: pageOf(request), signal: request.signal });
}

/** Choosing a word or the sort changes only the address, so the data is not asked for again. */
export function wordsShouldRevalidate({ currentUrl, nextUrl, defaultShouldRevalidate }: ShouldRevalidateFunctionArgs) {
  if (currentUrl.pathname === nextUrl.pathname && dataSearch(currentUrl.search) === dataSearch(nextUrl.search)) return false;
  return defaultShouldRevalidate;
}

function Tiles({ data }: { data: WordsData }) {
  const tiles = data.tiles;
  const rows: [string, string][] = [
    ["Words asked", String(tiles.words_asked)],
    ["Right first time", tiles.right_first_time === null ? "none" : `${tiles.right_first_time}%`],
    ["Words missed", String(tiles.words_missed)],
    ["Settled", String(tiles.settled)],
  ];
  return (
    <dl className="summary words-tiles" aria-label="Tiles">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** The grid's key: each result's icon and words, so nothing relies on colour alone. */
function ResultKey() {
  return (
    <ul className="facts-key words-key" aria-label="Key">
      {RESULTS.map(({ key, label }) => {
        const Icon = RESULT_ICONS[key];
        return (
          <li key={key}>
            <span className="words-swatch" data-result={key} aria-hidden="true">
              <Icon />
            </span>
            {label}
          </li>
        );
      })}
    </ul>
  );
}

function readoutLines(cell: WordCell, data: WordsData): string[] {
  const attempt = data.attempts[String(cell.id)];
  const lines = [cell.word.key, `${attempt?.started ?? ""}, ${attempt?.task ?? ""}`];
  lines.push(cell.asked ? `${resultLabel(cell.asked.result)}: ${cell.asked.answers.join(", ")}` : "Not asked");
  return lines;
}

/** The chosen word's misspellings and timeouts, then the attempts that asked it, newest first. */
function ChosenWord({ word, data }: { word: Word; data: WordsData }) {
  return (
    <section className="facts-chosen" aria-labelledby="words-chosen-heading">
      <h2 id="words-chosen-heading">{word.key}</h2>
      <dl className="summary">
        <div>
          <dt>Misspellings</dt>
          <dd>{misspellingText(word)}</dd>
        </div>
        <div>
          <dt>Timeouts</dt>
          <dd>{word.timeouts}</dd>
        </div>
      </dl>
      <table className="records" aria-label={`Attempts that asked ${word.key}`}>
        <thead>
          <tr>
            <th scope="col">Started</th>
            <th scope="col">Task</th>
            <th scope="col">Asked from</th>
            <th scope="col">Answers</th>
          </tr>
        </thead>
        <tbody>
          {word.attempts.map(({ id, pools, answers }) => {
            const attempt = data.attempts[String(id)];
            return (
              <tr key={id}>
                <td>
                  <Link to={`/attempts/${id}`}>{attempt?.started ?? `Attempt ${id}`}</Link>
                </td>
                <td>{attempt?.task}</td>
                <td>{pools.map((pool) => POOLS.find(([value]) => value === pool)?.[1] ?? pool).join(", ")}</td>
                <td>{answers.join(", ")}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

/** One client group's spelling words across its spelling attempts in the period: the tiles, the grid, the list, and the chosen word. */
export function Words() {
  const report = useLoaderData() as WordsReport;
  const location = useLocation();
  const navigate = useNavigate();
  useTitle("Spelling words · Attempts");

  const [held, setHeld] = useState(report);
  const [draft, setDraft] = useState<View>(report.view);
  const [pointed, setPointed] = useState<WordCell | null>(null);
  if (held !== report) {
    setHeld(report);
    setDraft(report.view);
    setPointed(null);
  }

  const own = () => [...new URLSearchParams(location.search)].filter(([key]) => PAGE_KEYS.includes(key));
  function change(patch: Partial<View>) {
    const next = { ...draft, ...patch };
    setDraft(next);
    // A new view keeps the Task and Pool filters and the page's own choices.
    navigate({ search: viewQuery(next, [...filtersIn(location.search), ...own()]) });
  }
  const offered = report.tasks_offered.map(({ name }) => name);
  const taskLabels: [string, string][] = report.tasks_offered.map(({ name, in_policy }) => [name, in_policy ? name : `${name} (not in the policy)`]);
  function filter(task: string[], pool: string[]) {
    navigate(wordsAddress(report.view, { task, pool }, offered, own()));
  }

  const choice = pageChoice(location.search);
  const data = report.words;
  const words = sortWords(data?.words ?? [], choice.sort, choice.dir);
  const chosen = words.find((word) => word.word === choice.word) ?? null;
  const choose = (word: Word) => withChoice(location.search, { word: word.word });
  const thisWeek = thisWeekAddress(report);

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
              <h1 className="bar-title">Spelling words</h1>
            </li>
          </ol>
        </nav>
        <ViewFilters view={draft} period={report} onChange={change} />
        <div className="bar-filters">
          <MultiSelect
            label="Task"
            options={taskLabels.map(([, label]) => label)}
            selected={labelsOf(report.choices.task, taskLabels)}
            onToggle={(label) => filter(toggledIn(report.choices.task, valueOf(label, taskLabels), taskLabels), report.choices.pool)}
          />
          <MultiSelect
            label="Pool"
            options={POOLS.map(([, label]) => label)}
            selected={labelsOf(report.choices.pool, POOLS)}
            onToggle={(label) => filter(report.choices.task, toggledIn(report.choices.pool, valueOf(label, POOLS), POOLS))}
          />
          {thisWeek !== null && (
            <Link className="words-this-week" to={thisWeek}>
              This week's words
            </Link>
          )}
        </div>
      </ContextBar>

      {report.message !== null && <p>{report.message}</p>}
      {data !== null && (
        <>
          <Tiles data={data} />
          <ResultKey />
          <div className="facts-top">
            <WordGrid data={data} words={words} chosen={chosen?.word ?? null} choose={choose} onPoint={setPointed} />
            <div className="facts-readout" aria-live="polite">
              {pointed === null ? (
                <p>Point at a cell to see his answers.</p>
              ) : (
                readoutLines(pointed, data).map((line, index) => (index === 0 ? <strong key={index}>{line}</strong> : <span key={index}>{line}</span>))
              )}
            </div>
          </div>

          <h2>Words</h2>
          <div className="facts-list-box">
            <table className="records facts-list words-list" aria-label="Words">
              <thead>
                <tr>
                  <th scope="colgroup" colSpan={COLUMNS.filter((column) => !column.now).length}>
                    In this period
                  </th>
                  <th scope="colgroup" colSpan={COLUMNS.filter((column) => column.now).length}>
                    For now
                  </th>
                </tr>
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
                  const to = { search: choose(word) };
                  const isChosen = word.word === chosen?.word;
                  return (
                    <tr
                      key={word.word}
                      data-chosen={isChosen || undefined}
                      onClick={(event) => {
                        if (!(event.target instanceof Element) || !event.target.closest("a")) navigate(to, { preventScrollReset: true });
                      }}
                    >
                      <td className="facts-list-text">
                        <Link to={to} preventScrollReset aria-current={isChosen ? "true" : undefined}>
                          {word.key}
                        </Link>
                      </td>
                      <td className="facts-list-text">{poolText(word)}</td>
                      <td>{word.asked}</td>
                      <td>{word.first_time}</td>
                      <td>{word.after_miss}</td>
                      <td>{word.missed}</td>
                      <td>{word.missed_percent}%</td>
                      <td>{word.timeouts}</td>
                      <td>{medianText(word)}</td>
                      <td>{word.replays_per_ask.toFixed(1)}</td>
                      <td className="facts-list-text">{word.last_missed ?? ""}</td>
                      <td>{word.all_time.run}</td>
                      <td>{word.all_time.weight.toFixed(3)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {chosen !== null && <ChosenWord word={chosen} data={data} />}
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
