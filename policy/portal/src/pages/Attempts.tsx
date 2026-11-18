import { useState } from "react";
import {
  Form,
  Link,
  useActionData,
  useLoaderData,
  useNavigate,
  useNavigation,
  type ActionFunctionArgs,
  type LoaderFunctionArgs,
} from "react-router";
import { ApiError, api, pageOf } from "../api";
import { trendAddress, viewQuery, type AttemptRow, type PeriodData, type View } from "../attempts";
import { AttemptTable } from "../components/AttemptTable";
import { ViewFilters } from "../components/ViewFilters";
import { Sparkline } from "../components/charts/Sparkline";
import { ContextBar, StatusBar, useTitle } from "../slots";

type Labelled = { label: string; value: string };
export type OverviewRow = {
  type: string;
  name: string;
  label: string;
  in_policy: boolean;
  attempts: number;
  passes: number;
  failures: number;
  abandoned: number;
  unfinished: number;
  accuracy: number | null;
  spark: { points: number; pass_mark: number | null }[];
  spark_label: string;
};
type AttemptsReport = PeriodData & {
  clients: string[];
  client: string;
  view: View;
  notes: string[];
  times: string;
  message: string | null;
  summary: Labelled[] | null;
  overview: OverviewRow[] | null;
  attempts: AttemptRow[] | null;
};
type CheckResult = { ok: boolean; message: string };

/** The data endpoint takes the page's own query string. */
export async function attemptsLoader({ request }: LoaderFunctionArgs): Promise<AttemptsReport> {
  const search = new URL(request.url).search;
  return api<AttemptsReport>(`/attempts${search}`, { page: pageOf(request), signal: request.signal });
}

/** Record a parent check for the group on show. Sent from the page on show, so a refusal returns to it. */
export async function attemptsAction({ request }: ActionFunctionArgs): Promise<CheckResult> {
  const form = await request.formData();
  try {
    const done = await api<{ message: string }>("/parent-check", {
      page: pageOf(request),
      method: "POST",
      body: { client: form.get("client") },
    });
    return { ok: true, message: done.message };
  } catch (error) {
    if (error instanceof ApiError) return { ok: false, message: error.message };
    throw error;
  }
}

/** How each task went over the period, one row per task. */
function Overview({ rows, view }: { rows: OverviewRow[]; view: View }) {
  return (
    <table className="records overview" aria-label="Overview">
      <thead>
        <tr>
          <th scope="col">Task</th>
          <th scope="col">Attempts</th>
          <th scope="col">Passes</th>
          <th scope="col">Failures</th>
          <th scope="col">Abandoned</th>
          <th scope="col">Unfinished</th>
          <th scope="col">Accuracy</th>
          <th scope="col">Trend</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.label}>
            <th scope="row">
              <Link to={trendAddress(row.type, row.name, view)}>{row.label}</Link>
              {!row.in_policy && <span className="task-gone">not in the policy</span>}
            </th>
            <td>{row.attempts}</td>
            <td>{row.passes}</td>
            <td>{row.failures}</td>
            <td>{row.abandoned}</td>
            <td>{row.unfinished}</td>
            <td>{row.accuracy === null ? "" : `${row.accuracy}%`}</td>
            <td>{row.spark.length > 0 ? <Sparkline values={row.spark} label={row.spark_label} /> : <span>{row.spark_label}</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function Attempts() {
  const report = useLoaderData() as AttemptsReport;
  const result = useActionData() as CheckResult | undefined;
  const navigate = useNavigate();
  const navigation = useNavigation();
  useTitle("Attempts");

  // The controls show a change at once, before the page for it has loaded.
  const [held, setHeld] = useState(report);
  const [draft, setDraft] = useState<View>(report.view);
  if (held !== report) {
    setHeld(report);
    setDraft(report.view);
  }

  function change(patch: Partial<View>) {
    const next = { ...draft, ...patch };
    setDraft(next);
    navigate({ search: viewQuery(next) });
  }

  const chosen = report.client;
  const options = chosen && !report.clients.includes(chosen) ? [...report.clients, chosen] : report.clients;
  const listed = report.attempts;
  const overview = report.overview;

  return (
    <>
      <ContextBar>
        <h1 className="bar-title">Attempts</h1>
        <label className="bar-field">
          Client group
          <select value={draft.client} onChange={(event) => change({ client: event.target.value })}>
            <option value="">Choose</option>
            {options.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <Form method="post" className="bar-form">
          <input type="hidden" name="client" value={chosen} />
          <button type="submit" className="button" disabled={report.summary === null || navigation.state === "submitting"}>
            Record parent check
          </button>
        </Form>
        <ViewFilters view={draft} period={report} onChange={change} />
      </ContextBar>

      {report.message !== null && <p>{report.message}</p>}
      {report.summary !== null && (
        <>
          <h2>{chosen}</h2>
          <dl className="summary" id="today">
            {report.summary.map(({ label, value }) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
      {report.summary !== null && overview === null && <p>Fix the period to show the attempts.</p>}
      {overview !== null && (
        <>
          <h2>Overview</h2>
          {overview.length === 0 ? <p>No attempts in this period.</p> : <Overview rows={overview} view={report.view} />}
        </>
      )}
      {listed !== null && listed.length > 0 && (
        <>
          <h2>Attempts</h2>
          <AttemptTable rows={listed} label="Attempts" />
        </>
      )}

      <StatusBar>
        {result && <span className={result.ok ? "status-done" : "status-refused"}>{result.message}</span>}
        {report.notes.map((note) => (
          <span key={note}>{note}</span>
        ))}
        {listed !== null && <span>{listed.length === 1 ? "1 attempt listed." : `${listed.length} attempts listed.`}</span>}
        <span>{report.range ? `${report.range}. ${report.times}` : report.times}</span>
      </StatusBar>
    </>
  );
}
