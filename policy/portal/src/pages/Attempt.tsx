import { Link, useLoaderData, type LoaderFunctionArgs } from "react-router";
import { ApiError, api, pageOf } from "../api";
import { Fields, StoredValue, type Stored } from "../components/StoredValue";
import { ContextBar, StatusBar, useTitle } from "../slots";

type AttemptReport = {
  id: number;
  task: string;
  type: string;
  client: string;
  times: string;
  summary: { label: string; value: string }[];
  reopened: { gave_up: string; came_back: string }[];
  answers: Stored[] | null;
  record: { [key: string]: Stored } | null;
};
type Loaded = { attempt: AttemptReport } | { missing: string };

export async function attemptLoader({ request, params }: LoaderFunctionArgs): Promise<Loaded> {
  try {
    const attempt = await api<AttemptReport>(`/attempts/${encodeURIComponent(params.id ?? "")}`, {
      page: pageOf(request),
      signal: request.signal,
    });
    return { attempt };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return { missing: error.message };
    throw error;
  }
}

export function Attempt() {
  const loaded = useLoaderData() as Loaded;
  const attempt = "attempt" in loaded ? loaded.attempt : null;
  useTitle(attempt ? `${attempt.task} · Attempts` : "Attempts");

  return (
    <>
      <ContextBar>
        <nav aria-label="Where you are" className="crumbs">
          <ol>
            <li>
              <Link to="/attempts">Attempts</Link>
            </li>
            {attempt && (
              <>
                <li>
                  <Link to={{ pathname: "/attempts", search: `?client=${encodeURIComponent(attempt.client)}` }}>{attempt.client}</Link>
                </li>
                <li aria-current="page">
                  <h1 className="bar-title">{attempt.task}</h1>
                </li>
              </>
            )}
          </ol>
        </nav>
      </ContextBar>

      {"missing" in loaded && <p>{loaded.missing}</p>}
      {attempt && (
        <>
          <dl className="summary">
            {attempt.summary.map(({ label, value }) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          {attempt.reopened.length > 0 && (
            <>
              <h2>Given up and carried on</h2>
              <table className="records">
                <thead>
                  <tr>
                    <th scope="col">Gave up</th>
                    <th scope="col">Came back</th>
                  </tr>
                </thead>
                <tbody>
                  {attempt.reopened.map((event, index) => (
                    <tr key={index}>
                      <td>{event.gave_up}</td>
                      <td>{event.came_back}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          {attempt.answers !== null && (
            <>
              <h2>Answers</h2>
              {attempt.answers.length === 0 ? <p>No answers were stored.</p> : <StoredValue value={attempt.answers} />}
            </>
          )}
          {attempt.record !== null && (
            <>
              <h2>Record</h2>
              <Fields value={attempt.record} />
            </>
          )}
        </>
      )}

      <StatusBar>{attempt && <span>{attempt.times}</span>}</StatusBar>
    </>
  );
}
