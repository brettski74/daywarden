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
  /** A practice question's place in its walk, such as "5 of 28". */
  step?: string | null;
};
type Run = {
  run: number;
  expired: string | null;
  operation: string | null;
  operation_label: string;
  figures: Figures | null;
  questions: Question[];
};

/** One practice walk (S039): its `m` and each question asked. Practice is in no run's figures. */
type Walk = {
  walk: number;
  run: number | null;
  m: number | null;
  operation: string | null;
  operation_label: string;
  length: number | null;
  ended: "finished" | "left" | null;
  questions: Question[];
};

/** A capitalisation attempt's try (S040.2): the sentence with the words he clicked marked, and what the try earned. */
type CapTry = { words: { word: string; colour: "blue" | "red" | "black" }[]; points: number; timeout: boolean; taken_ms: number };
type CapSentence = {
  text: string;
  outcome: "correct" | "incorrect" | "timeout" | null;
  outcome_label: string;
  points: number;
  tries: CapTry[];
};
type CapRun = { run: number; expired: string | null; figures: Figures | null; sentences: CapSentence[] };

type AttemptReport = {
  id: number;
  task: string;
  type: string;
  client: string;
  times: string;
  summary: { label: string; value: string }[];
  reopened: { gave_up: string; came_back: string }[];
  arithmetic: { last: Run; expired: Run[]; practice: Walk[] } | null;
  capitalisation: { last: CapRun; expired: CapRun[] } | null;
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

type QuestionsProps = { questions: Question[]; operation: string | null; client: string; label: string; walk?: boolean };

/** The questions in order, each of a run linking to its fact over the past month. A walk's have a Step and no link. */
function RunQuestions({ questions, operation: asked, client, label, walk = false }: QuestionsProps) {
  if (questions.length === 0) return <p>No questions yet.</p>;
  return (
    <table className="records run-questions" aria-label={label}>
      <thead>
        <tr>
          <th scope="col">#</th>
          {walk && <th scope="col">Step</th>}
          <th scope="col">Question</th>
          <th scope="col">Answer given</th>
          <th scope="col">Outcome</th>
          <th scope="col">Time taken</th>
          <th scope="col">Time allowed</th>
        </tr>
      </thead>
      <tbody>
        {questions.map((question, index) => {
          const Icon = question.outcome === null ? Hourglass : OUTCOME_ICONS[question.outcome];
          const operation = question.operation ?? asked;
          return (
            <tr key={index}>
              <td>{index + 1}</td>
              {walk && <td>{question.step ?? ""}</td>}
              <td>
                {!walk && operation !== null && question.m !== null && question.n !== null ? (
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

const ENDINGS = { finished: "finished", left: "left early" };

function walkHeading(walk: Walk): string {
  const ended = walk.ended === null ? "in progress" : ENDINGS[walk.ended];
  return `Walk ${walk.walk}: m = ${walk.m ?? "?"}, ${walk.operation_label}, ${ended}`;
}

/** An arithmetic attempt's last run, then each earlier run, then each practice walk. */
function ArithmeticRuns({ runs, client }: { runs: { last: Run; expired: Run[]; practice: Walk[] }; client: string }) {
  return (
    <>
      <h2>Last run</h2>
      <RunSummary run={runs.last} />
      <RunQuestions questions={runs.last.questions} operation={runs.last.operation} client={client} label="Last run's questions" />
      {runs.expired.map((run) => {
        const heading = run.expired ? `Run ${run.run}, expired ${run.expired}` : `Run ${run.run}`;
        return (
          <section key={run.run} aria-label={heading}>
            <h2>{heading}</h2>
            <RunSummary run={run} />
            <RunQuestions questions={run.questions} operation={run.operation} client={client} label={`Run ${run.run}'s questions`} />
          </section>
        );
      })}
      {runs.practice.length > 0 && (
        <section aria-label="Practice">
          <h2>Practice</h2>
          {runs.practice.map((walk) => (
            <section key={walk.walk} aria-label={`Practice walk ${walk.walk}`}>
              <h3>{walkHeading(walk)}</h3>
              <RunQuestions questions={walk.questions} operation={walk.operation} client={client} label={`Practice walk ${walk.walk}'s questions`} walk />
            </section>
          ))}
        </section>
      )}
    </>
  );
}

/** A capitalisation run's figures, as S035.1 works them out. */
function CapSummary({ run }: { run: CapRun }) {
  const f = run.figures;
  if (f === null) return null;
  const rows: [string, string][] = [
    ["Points", `${formatPoints(f.points)} / ${f.pass_mark ?? "?"} right`],
    ["Questions", `${f.questions}${f.maximum === null ? "" : ` / ${f.maximum}`}`],
    ["Wrong", String(f.wrong)],
    ["Timeouts", String(f.timeouts)],
    ["Time answering", formatClock(f.time_ms / 1000)],
  ];
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

/** The sentences of a run in order, each with every try: its words marked, the points it earned or timeout, and the time taken. */
function CapSentences({ run, label }: { run: CapRun; label: string }) {
  if (run.sentences.length === 0) return <p>No sentences yet.</p>;
  return (
    <ol className="cap-sentences" aria-label={label}>
      {run.sentences.map((sentence, index) => (
        <li key={index} aria-label={`Sentence ${index + 1}`}>
          <ul className="cap-tries">
            {sentence.tries.map((one, number) => (
              <li key={number} className="cap-try" aria-label={`Try ${number + 1}`}>
                <span className="cap-words">
                  {one.words.map((word, at) => (
                    <span key={at} data-colour={word.colour}>
                      {at > 0 && " "}
                      {word.word}
                    </span>
                  ))}
                </span>
                <span className="run-outcome" data-outcome={one.timeout ? "timeout" : one.points > 0 ? "correct" : "incorrect"}>
                  {one.timeout ? <TimerOff aria-hidden="true" /> : one.points > 0 ? <Check aria-hidden="true" /> : <X aria-hidden="true" />}
                  {one.timeout ? "Timeout" : `${formatPoints(one.points)} ${one.points === 1 ? "point" : "points"}`}
                </span>
                <span>{seconds(one.taken_ms)}</span>
              </li>
            ))}
            {sentence.outcome === null && <li>Not answered yet</li>}
          </ul>
        </li>
      ))}
    </ol>
  );
}

/** A capitalisation attempt's last run, then each expired run. */
function CapitalisationRuns({ runs }: { runs: { last: CapRun; expired: CapRun[] } }) {
  return (
    <>
      <h2>Last run</h2>
      <CapSummary run={runs.last} />
      <CapSentences run={runs.last} label="Last run's sentences" />
      {runs.expired.map((run) => {
        const heading = run.expired ? `Run ${run.run}, expired ${run.expired}` : `Run ${run.run}`;
        return (
          <section key={run.run} aria-label={heading}>
            <h2>{heading}</h2>
            <CapSummary run={run} />
            <CapSentences run={run} label={`Run ${run.run}'s sentences`} />
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
          {attempt.capitalisation && <CapitalisationRuns runs={attempt.capitalisation} />}
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
            (attempt.arithmetic || attempt.capitalisation ? (
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
