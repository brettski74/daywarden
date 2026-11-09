import {
  Form,
  Link,
  useActionData,
  useLoaderData,
  useNavigation,
  useSearchParams,
  type ActionFunctionArgs,
  type LoaderFunctionArgs,
} from "react-router";
import { ApiError, api, pageOf } from "../api";
import { ContextBar, StatusBar, useTitle } from "../slots";

type Labelled = { label: string; value: string };
type AttemptRow = {
  id: number;
  task: string;
  set: string;
  started: string;
  finished: string;
  outcome: string;
  duration: string;
};
type AttemptsReport = {
  clients: string[];
  client: string;
  times: string;
  message: string | null;
  summary: Labelled[] | null;
  attempts: AttemptRow[] | null;
};
type CheckResult = { ok: boolean; message: string };

export async function attemptsLoader({ request }: LoaderFunctionArgs): Promise<AttemptsReport> {
  const client = new URL(request.url).searchParams.get("client") ?? "";
  const query = client ? `?client=${encodeURIComponent(client)}` : "";
  return api<AttemptsReport>(`/attempts${query}`, { page: pageOf(request), signal: request.signal });
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

export function Attempts() {
  const report = useLoaderData() as AttemptsReport;
  const result = useActionData() as CheckResult | undefined;
  const [, setSearchParams] = useSearchParams();
  const navigation = useNavigation();
  useTitle("Attempts");
  const chosen = report.client;
  const options = chosen && !report.clients.includes(chosen) ? [...report.clients, chosen] : report.clients;
  const listed = report.attempts;

  return (
    <>
      <ContextBar>
        <h1 className="bar-title">Attempts</h1>
        <label className="bar-field">
          Client group
          <select value={chosen} onChange={(event) => setSearchParams(event.target.value ? { client: event.target.value } : {})}>
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
          <button type="submit" className="button" disabled={listed === null || navigation.state === "submitting"}>
            Record parent check
          </button>
        </Form>
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
      {listed !== null && listed.length === 0 && <p>No attempts yet.</p>}
      {listed !== null && listed.length > 0 && (
        <table className="records">
          <thead>
            <tr>
              <th scope="col">Task</th>
              <th scope="col">Set</th>
              <th scope="col">Started</th>
              <th scope="col">Finished</th>
              <th scope="col">Outcome</th>
              <th scope="col">Duration</th>
            </tr>
          </thead>
          <tbody>
            {listed.map((row) => (
              <tr key={row.id}>
                <td>
                  <Link to={`/attempts/${row.id}`}>{row.task}</Link>
                </td>
                <td>{row.set}</td>
                <td>{row.started}</td>
                <td>{row.finished}</td>
                <td>{row.outcome}</td>
                <td>{row.duration}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <StatusBar>
        {result && <span className={result.ok ? "status-done" : "status-refused"}>{result.message}</span>}
        {listed !== null && <span>{listed.length === 1 ? "1 attempt listed." : `${listed.length} attempts listed.`}</span>}
        <span>{report.times}</span>
      </StatusBar>
    </>
  );
}
