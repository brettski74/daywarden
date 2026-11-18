import { Check, Hourglass, TimerOff, X } from "lucide-react";
import { Link, useLoaderData, type LoaderFunctionArgs } from "react-router";
import { ApiError, api, pageOf } from "../api";
import { formatClock, formatPoints, formatSeconds, type Figures } from "../attempts";
import { Fold } from "../components/Fold";
import { Fields, StoredValue, type Stored } from "../components/StoredValue";
import { factLink } from "../facts";
import { ContextBar, StatusBar, useTitle } from "../slots";

type Question = {
  text: string;
  m: number | null;
  n: number | null;
  operation: string | null;
  answer: string;
  outcome: "correct" | "incorrect" | "timeout" | null;
  outcome_label: string;
  taken_ms: number | null;
  allowed_ms: number | null;
};
type Run = {
  run: number;
  expired: string | null;
  operation: string | null;
  operation_label: string;
  figures: Figures | null;
  questions: Question[];
};

type AttemptReport = {
  id: number;
  task: string;
  type: string;
  client: string;
  times: string;
  summary: { label: string; value: string }[];
  reopened: { gave_up: string; came_back: string }[];
  arithmetic: { last: Run; expired: Run[] } | null;
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

function seconds(ms: number | null): string {
  return ms === null ? "" : formatSeconds(ms / 1000);
}

/** A run's figures, as S035.1 works them out. */
function RunSummary({ run }: { run: Run }) {
  const f = run.figures;
  const rows: [string, string][] = [["Operation", run.operation_label]];
  if (f !== null) {
    rows.push(
      ["Points", `${formatPoints(f.points)} / ${f.pass_mark ?? "?"} right`],
      ["Questions", String(f.questions)],
      ["Wrong", String(f.wrong)],
      ["Timeouts", String(f.timeouts)],
      ["Time answering", formatClock(f.time_ms / 1000)],
      ["Average per right answer", f.average_ms === null ? "none" : formatSeconds(f.average_ms / 1000)],
    );
  }
  return (
    <dl className="summary run-summary">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

const OUTCOME_ICONS = { correct: Check, incorrect: X, timeout: TimerOff };

/** The run's questions in order, each linking to its fact over the past month. */
function RunQuestions({ run, client, label }: { run: Run; client: string; label: string }) {
  if (run.questions.length === 0) return <p>No questions yet.</p>;
  return (
    <table className="records run-questions" aria-label={label}>
      <thead>
        <tr>
          <th scope="col">#</th>
          <th scope="col">Question</th>
          <th scope="col">Answer given</th>
          <th scope="col">Outcome</th>
          <th scope="col">Time taken</th>
          <th scope="col">Time allowed</th>
        </tr>
      </thead>
      <tbody>
        {run.questions.map((question, index) => {
          const Icon = question.outcome === null ? Hourglass : OUTCOME_ICONS[question.outcome];
          const operation = question.operation ?? run.operation;
          return (
            <tr key={index}>
              <td>{index + 1}</td>
              <td>
                {operation !== null && question.m !== null && question.n !== null ? (
                  <Link to={factLink(operation, client, question.m, question.n)}>{question.text}</Link>
                ) : (
                  question.text
                )}
              </td>
              <td>{question.answer}</td>
              <td className="run-outcome" data-outcome={question.outcome ?? "waiting"}>
                <Icon aria-hidden="true" />
                {question.outcome_label}
              </td>
              <td>{question.outcome === null ? "" : seconds(question.taken_ms)}</td>
              <td>{seconds(question.allowed_ms)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** An arithmetic attempt's last run, then each run that expired before it. */
function ArithmeticRuns({ runs, client }: { runs: { last: Run; expired: Run[] }; client: string }) {
  return (
    <>
      <h2>Last run</h2>
      <RunSummary run={runs.last} />
      <RunQuestions run={runs.last} client={client} label="Last run's questions" />
      {runs.expired.map((run) => {
        const heading = run.expired ? `Run ${run.run}, expired ${run.expired}` : `Run ${run.run}`;
        return (
          <section key={run.run} aria-label={heading}>
            <h2>{heading}</h2>
            <RunSummary run={run} />
            <RunQuestions run={run} client={client} label={`Run ${run.run}'s questions`} />
          </section>
        );
      })}
    </>
  );
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
          {attempt.arithmetic && <ArithmeticRuns runs={attempt.arithmetic} client={attempt.client} />}
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
          {attempt.record !== null &&
            (attempt.arithmetic ? (
              <Fold title="Stored record">
                <Fields value={attempt.record} />
              </Fold>
            ) : (
              <>
                <h2>Record</h2>
                <Fields value={attempt.record} />
              </>
            ))}
        </>
      )}

      <StatusBar>{attempt && <span>{attempt.times}</span>}</StatusBar>
    </>
  );
}
