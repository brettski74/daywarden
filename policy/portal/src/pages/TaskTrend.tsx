import { useState } from "react";
import { Link, useLoaderData, useLocation, useNavigate, type LoaderFunctionArgs, type ShouldRevalidateFunctionArgs } from "react-router";
import { api, pageOf } from "../api";
import {
  OUTCOMES,
  TIME_SERIES,
  clockAxis,
  countAxis,
  countSeries,
  readoutLines,
  secondsAxis,
  shownOf,
  viewQuery,
  withShown,
  type AttemptRow,
  type Kind,
  type PeriodData,
  type SeriesDef,
  type SeriesKey,
  type TrendPoint,
  type View,
} from "../attempts";
import { AttemptTable } from "../components/AttemptTable";
import { ViewFilters } from "../components/ViewFilters";
import { factsAddress } from "../facts";
import { taskWordsAddress } from "../spellingWords";
import { Shape, TrendChart, type Marked, type TrendSeries } from "../components/charts/TrendChart";
import type { Tick } from "../components/charts/ChartFrame";
import { ContextBar, StatusBar, useTitle } from "../slots";

type Trend = {
  kind: Kind | null;
  has_maximum: boolean;
  length: number;
  ticks: Tick[];
  points: TrendPoint[];
  attempts: AttemptRow[];
};
type TrendReport = PeriodData & {
  clients: string[];
  client: string;
  view: View;
  notes: string[];
  times: string;
  task: { type: string; name: string; label: string; in_policy: boolean };
  /** An arithmetic task's operation, whose facts page it links to. */
  facts: string | null;
  message: string | null;
  trend: Trend | null;
};

/** The data endpoint takes the page's own query string. The lines shown are the page's alone. */
export async function trendLoader({ request, params }: LoaderFunctionArgs): Promise<TrendReport> {
  const search = new URL(request.url).search;
  const path = `/attempts/tasks/${encodeURIComponent(params.type ?? "")}/${encodeURIComponent(params.name ?? "")}${search}`;
  return api<TrendReport>(path, { page: pageOf(request), signal: request.signal });
}

/** Showing or hiding a line changes only the address, so the data is not asked for again. */
export function trendShouldRevalidate({ currentUrl, nextUrl, defaultShouldRevalidate }: ShouldRevalidateFunctionArgs) {
  const strip = (url: URL) => {
    const params = new URLSearchParams(url.search);
    params.delete("show");
    return url.pathname + "?" + params.toString();
  };
  if (currentUrl.pathname === nextUrl.pathname && strip(currentUrl) === strip(nextUrl)) return false;
  return defaultShouldRevalidate;
}

function seriesOf(defs: SeriesDef[], points: TrendPoint[], shown: SeriesKey[], right: SeriesKey[] = []): TrendSeries[] {
  return defs.map((def) => ({
    key: def.key,
    name: def.name,
    colour: def.colour,
    shown: shown.includes(def.key),
    right: right.includes(def.key),
    values: points.map((point) => (point.figures === null ? null : def.value(point.figures))),
  }));
}

/** The marker shapes, so the outcome never relies on colour alone. */
function ShapeKey() {
  return (
    <ul className="trend-shapes" aria-label="Markers">
      {OUTCOMES.map(([value, label]) => (
        <li key={value}>
          <svg viewBox="-8 -8 16 16" className="trend-shape" aria-hidden="true">
            <g className="trend-marker" data-outcome={value}>
              <Shape outcome={value} />
            </g>
          </svg>
          {label}
        </li>
      ))}
      <li>
        <svg viewBox="-8 -8 16 16" className="trend-shape" aria-hidden="true">
          <g className="trend-marker" data-hollow>
            <Shape outcome="pass" />
          </g>
        </svg>
        Hollow: practice
      </li>
    </ul>
  );
}

/** A task's points, pass mark, and questions over the period, its times, and its attempts. */
export function TaskTrend() {
  const report = useLoaderData() as TrendReport;
  const location = useLocation();
  const navigate = useNavigate();
  const task = report.task;
  useTitle(`${task.label} · Attempts`);

  const [held, setHeld] = useState(report);
  const [draft, setDraft] = useState<View>(report.view);
  if (held !== report) {
    setHeld(report);
    setDraft(report.view);
  }

  const shownParams = new URLSearchParams(location.search).getAll("show");
  function change(patch: Partial<View>) {
    const next = { ...draft, ...patch };
    setDraft(next);
    navigate({ search: viewQuery(next, shownParams.map((value): [string, string] => ["show", value])) });
  }

  const trend = report.trend;
  const kind = trend?.kind ?? null;
  const shown = kind === null ? [] : shownOf(location.search, kind);
  const toggle = (key: string) => kind !== null && navigate({ search: withShown(location.search, kind, key as SeriesKey) }, { replace: false });
  const marked: Marked[] =
    trend?.points.map((point) => {
      const readout = readoutLines(point);
      return { id: point.id, at: point.at, outcome: point.outcome, hollow: point.practice, label: readout.join(". "), readout, to: `/attempts/${point.id}` };
    }) ?? [];
  const back = { pathname: "/attempts", search: viewQuery(report.view) };

  return (
    <>
      <ContextBar>
        <nav aria-label="Where you are" className="crumbs">
          <ol>
            <li>
              <Link to={back}>Attempts</Link>
            </li>
            {report.client && <li>{report.client}</li>}
            <li aria-current="page">
              <h1 className="bar-title">{task.label}</h1>
            </li>
          </ol>
        </nav>
        <ViewFilters view={draft} period={report} onChange={change} />
      </ContextBar>

      {report.facts && (
        <p className="trend-facts">
          <Link to={factsAddress(report.facts, report.view)}>{report.facts.charAt(0).toUpperCase() + report.facts.slice(1)} facts</Link>
        </p>
      )}
      {task.type === "spelling" && (
        <p className="trend-facts">
          <Link to={taskWordsAddress(task.name, report.view)}>Spelling words</Link>
        </p>
      )}
      {!task.in_policy && trend !== null && <p className="task-gone">{task.label} is not in the policy.</p>}
      {report.message !== null && <p>{report.message}</p>}
      {trend !== null && kind === null && <p>This type has no figures yet, so its attempts are only listed.</p>}
      {trend !== null && kind !== null && (
        <div className="trend">
          <ShapeKey />
          <div className="trend-counts">
            <TrendChart
              label={`${task.label}: counts`}
              length={trend.length}
              ticks={trend.ticks}
              marked={marked}
              series={seriesOf(countSeries(kind, trend.has_maximum), trend.points, shown)}
              axis={countAxis}
              onToggle={toggle}
              empty="Choose a line in the legend to show it."
            />
          </div>
          <div className="trend-times">
            <TrendChart
              label={`${task.label}: times`}
              length={trend.length}
              ticks={trend.ticks}
              marked={marked}
              series={seriesOf(TIME_SERIES, trend.points, shown, ["average"])}
              axis={clockAxis}
              rightAxis={secondsAxis}
              onToggle={toggle}
              empty="Choose a line in the legend to show it."
            />
          </div>
        </div>
      )}
      {trend !== null && (
        <>
          <h2>Attempts</h2>
          <AttemptTable rows={trend.attempts} label="Attempts" />
        </>
      )}

      <StatusBar>
        {report.notes.map((note) => (
          <span key={note}>{note}</span>
        ))}
        {trend !== null && <span>{trend.attempts.length === 1 ? "1 attempt." : `${trend.attempts.length} attempts.`}</span>}
        <span>{report.range ? `${report.range}. ${report.times}` : report.times}</span>
      </StatusBar>
    </>
  );
}
