import { useState } from "react";
import { Link, useLoaderData, useLocation, useNavigate, type LoaderFunctionArgs, type ShouldRevalidateFunctionArgs } from "react-router";
import { api, pageOf } from "../api";
import { viewQuery, type View } from "../attempts";
import { FactGrid } from "../components/FactGrid";
import { ViewFilters } from "../components/ViewFilters";
import {
  COLUMNS,
  PAGE_KEYS,
  factLines,
  factsAddress,
  medianText,
  pageChoice,
  shading,
  sortFacts,
  sortedBy,
  withChoice,
  type Fact,
  type FactsData,
  type FactsReport,
  type Shade,
} from "../facts";
import { ContextBar, StatusBar, useTitle } from "../slots";

function dataSearch(url: URL): string {
  const params = new URLSearchParams(url.search);
  for (const key of PAGE_KEYS) params.delete(key);
  const text = params.toString();
  return text ? `?${text}` : "";
}

/** The data endpoint takes the page's view. The chosen fact, the shading, and the sort are the page's alone. */
export async function factsLoader({ request, params }: LoaderFunctionArgs): Promise<FactsReport> {
  const path = `/attempts/facts/${encodeURIComponent(params.operation ?? "")}${dataSearch(new URL(request.url))}`;
  return api<FactsReport>(path, { page: pageOf(request), signal: request.signal });
}

/** Choosing a fact, the shading, or the sort changes only the address, so the data is not asked for again. */
export function factsShouldRevalidate({ currentUrl, nextUrl, defaultShouldRevalidate }: ShouldRevalidateFunctionArgs) {
  if (currentUrl.pathname === nextUrl.pathname && dataSearch(currentUrl) === dataSearch(nextUrl)) return false;
  return defaultShouldRevalidate;
}

const keyOf = (fact: Fact) => `${fact.m},${fact.n}`;

/** The shading key, so nothing relies on colour alone. */
function ShadeKey({ bands, none }: { bands: { level: number; label: string }[]; none: string | null }) {
  return (
    <ul className="facts-key" aria-label="Shading">
      {bands.map((band) => (
        <li key={band.level}>
          <span className="facts-swatch" data-level={band.level} aria-hidden="true" />
          {band.label}
        </li>
      ))}
      {none && (
        <li>
          <span className="facts-swatch" data-level="none" aria-hidden="true" />
          {none}
        </li>
      )}
    </ul>
  );
}

/** The attempts that asked the chosen fact, newest first, each with his answers. */
function FactAttempts({ fact, data }: { fact: Fact; data: FactsData }) {
  return (
    <section className="facts-chosen" aria-labelledby="facts-chosen-heading">
      <h2 id="facts-chosen-heading">{fact.text}</h2>
      <table className="records" aria-label={`Attempts that asked ${fact.text}`}>
        <thead>
          <tr>
            <th scope="col">Started</th>
            <th scope="col">Task</th>
            <th scope="col">Answers</th>
          </tr>
        </thead>
        <tbody>
          {fact.attempts.map(({ id, answers }) => {
            const attempt = data.attempts[String(id)];
            return (
              <tr key={id}>
                <td>
                  <Link to={`/attempts/${id}`}>{attempt?.started ?? `Attempt ${id}`}</Link>
                </td>
                <td>{attempt?.task}</td>
                <td>{answers.join(", ")}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

/** One operation's facts across every arithmetic attempt in the period: the grid, the list, and the chosen fact's attempts. */
export function Facts() {
  const report = useLoaderData() as FactsReport;
  const location = useLocation();
  const navigate = useNavigate();
  const operation = report.operation;
  useTitle(`${operation.label} facts · Attempts`);

  const [held, setHeld] = useState(report);
  const [draft, setDraft] = useState<View>(report.view);
  const [pointed, setPointed] = useState<Fact | null>(null);
  if (held !== report) {
    setHeld(report);
    setDraft(report.view);
    setPointed(null);
  }

  const choice = pageChoice(location.search);
  function change(patch: Partial<View>) {
    const next = { ...draft, ...patch };
    setDraft(next);
    // A new view keeps the page's own choices.
    const own = [...new URLSearchParams(location.search)].filter(([key]) => PAGE_KEYS.includes(key));
    navigate({ search: viewQuery(next, own) });
  }

  const data = report.facts;
  const facts = data?.facts ?? [];
  const chosenKey = choice.m !== null && choice.n !== null ? `${choice.m},${choice.n}` : null;
  const chosen = facts.find((fact) => keyOf(fact) === chosenKey) ?? null;
  const shade = shading(choice.shade, facts);
  const href = (fact: Fact) => ({ search: withChoice(location.search, { m: fact.m, n: fact.n }) });
  const shown = pointed ?? chosen;
  const sorted = sortFacts(facts, choice.sort, choice.dir);

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
              <h1 className="bar-title">{operation.label} facts</h1>
            </li>
          </ol>
        </nav>
        <ViewFilters view={draft} period={report} onChange={change} />
      </ContextBar>

      <nav aria-label="Operations" className="facts-operations">
        <ul>
          {report.operations.map((each) => (
            <li key={each.name}>
              {each.name === operation.name ? (
                <span aria-current="page">{each.label}</span>
              ) : (
                <Link to={factsAddress(each.name, report.view)}>{each.label}</Link>
              )}
            </li>
          ))}
        </ul>
      </nav>

      {report.message !== null && <p>{report.message}</p>}
      {data !== null && (
        <>
          <div className="facts-controls">
            <label className="bar-field">
              Shade by
              <select value={choice.shade} onChange={(event) => navigate({ search: withChoice(location.search, { shade: event.target.value as Shade }) }, { preventScrollReset: true })}>
                <option value="misses">Misses</option>
                <option value="time">Time</option>
              </select>
            </label>
            <ShadeKey bands={shade.bands} none={shade.none} />
          </div>
          <div className="facts-top">
            <FactGrid data={data} label={`${operation.label} facts`} shading={shade} chosen={chosenKey} href={(fact) => href(fact).search} onPoint={setPointed} />
            <div className="facts-readout" aria-live="polite">
              {shown === null ? (
                <p>Point at a fact to see it.</p>
              ) : (
                factLines(shown).map((line, index) => (index === 0 ? <strong key={line}>{line}</strong> : <span key={line}>{line}</span>))
              )}
            </div>
          </div>

          <h2>Facts</h2>
          <table className="records facts-list" aria-label="Facts">
            <thead>
              <tr>
                {COLUMNS.map(({ key, label }) => {
                  const active = choice.sort === key;
                  const arrow = active ? (choice.dir === "asc" ? " ↑" : " ↓") : "";
                  return (
                    <th key={key} scope="col" aria-sort={active ? (choice.dir === "asc" ? "ascending" : "descending") : "none"}>
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
              {sorted.map((fact) => {
                const to = href(fact);
                return (
                  <tr
                    key={keyOf(fact)}
                    data-chosen={keyOf(fact) === chosenKey || undefined}
                    onClick={(event) => {
                      if (!(event.target instanceof Element) || !event.target.closest("a")) navigate(to, { preventScrollReset: true });
                    }}
                  >
                    <td>
                      <Link to={to} preventScrollReset aria-current={keyOf(fact) === chosenKey ? "true" : undefined}>
                        {fact.text}
                      </Link>
                    </td>
                    <td>{fact.asked}</td>
                    <td>{fact.right}</td>
                    <td>{fact.wrong}</td>
                    <td>{fact.timeouts}</td>
                    <td>{fact.missed_percent}%</td>
                    <td>{medianText(fact)}</td>
                    <td>{fact.last_missed ?? ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {chosen !== null && <FactAttempts fact={chosen} data={data} />}
        </>
      )}

      <StatusBar>
        {report.notes.map((note) => (
          <span key={note}>{note}</span>
        ))}
        {data !== null && <span>{facts.length === 1 ? "1 fact." : `${facts.length} facts.`}</span>}
        <span>{report.range ? `${report.range}. ${report.times}` : report.times}</span>
      </StatusBar>
    </>
  );
}
