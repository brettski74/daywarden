import { ChevronLeft, ChevronRight, GitCompareArrows, Undo2 } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import {
  Link,
  useFetcher,
  useLoaderData,
  useLocation,
  useNavigate,
  useSearchParams,
  type ActionFunctionArgs,
  type LoaderFunctionArgs,
  type ShouldRevalidateFunctionArgs,
} from "react-router";
import { ApiError, BASE, api, pageOf } from "../api";
import { DiffView } from "../components/DiffView";
import {
  HISTORY,
  HISTORY_DATA,
  comparePath,
  defaultPair,
  listPath,
  revisionData,
  revisionPath,
  type ComparePage,
  type HistoryList,
  type RevertPreview,
  type Revision,
  type RevisionPage,
} from "../configHistory";
import { ContextBar, StatusBar, useTitle } from "../slots";
import { NotFound } from "./Problems";
import { Outcome } from "./Task";

export const TITLE = "Config History";
const NO_HISTORY =
  "The config directory has no history of its own, as in a clone of the daywarden repository, so there are no versions to list, compare, or revert to.";

type Missing = { missing: true };
type Report = { message: string; warnings: string[] };
type Result = { ok: boolean; message?: string; warnings?: string[]; error?: string; errors?: string[]; nothing?: boolean; stale?: boolean };

/** An unknown revision shows the portal's not-found page, as an unknown address does. */
async function orMissing<T>(load: () => Promise<T>): Promise<T | Missing> {
  try {
    return await load();
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return { missing: true };
    throw error;
  }
}

function isMissing(data: unknown): data is Missing {
  return typeof data === "object" && data !== null && "missing" in data;
}

function Crumbs({ last }: { last?: string }) {
  return (
    <nav className="crumbs" aria-label="Where you are">
      <ol>
        <li>Settings</li>
        <li>{last === undefined ? <h1 className="bar-title">{TITLE}</h1> : <Link to={HISTORY}>{TITLE}</Link>}</li>
        {last !== undefined && (
          <li>
            <h1 className="bar-title">{last}</h1>
          </li>
        )}
      </ol>
    </nav>
  );
}

// The list

export async function historyLoader({ request }: LoaderFunctionArgs): Promise<HistoryList> {
  const asked = new URL(request.url).searchParams;
  const search = new URLSearchParams();
  for (const key of ["page", "file"]) {
    const value = asked.get(key);
    if (value) search.set(key, value);
  }
  const query = search.toString();
  return api<HistoryList>(query ? `${HISTORY_DATA}?${query}` : HISTORY_DATA, { page: pageOf(request), signal: request.signal });
}

/** Choosing From and To changes only the address, so the list is not fetched again. */
export function historyShouldRevalidate({ currentUrl, nextUrl, defaultShouldRevalidate }: ShouldRevalidateFunctionArgs) {
  const kept = (url: URL) => ["page", "file"].map((key) => url.searchParams.get(key) ?? "").join("\n");
  if (currentUrl.pathname === nextUrl.pathname && kept(currentUrl) === kept(nextUrl)) return false;
  return defaultShouldRevalidate;
}

/** Every saved version of the configuration, newest first, 50 to a page. */
export function ConfigHistory() {
  const data = useLoaderData() as HistoryList;
  const report = useLocation().state as Report | null;
  useTitle(TITLE);
  if (!data.kept) {
    return (
      <>
        <ContextBar>
          <Crumbs />
        </ContextBar>
        <p className="note">{NO_HISTORY}</p>
      </>
    );
  }
  return <HistoryTable data={data} report={report} />;
}

function HistoryTable({ data, report }: { data: Extract<HistoryList, { kept: true }>; report: Report | null }) {
  const [search, setSearch] = useSearchParams();
  const fallback = defaultPair(data.revisions);
  const from = search.get("from") || fallback.from;
  const to = search.get("to") || fallback.to;

  function choose(key: "from" | "to", id: string) {
    setSearch(
      (current) => {
        const next = new URLSearchParams(current);
        next.set("from", from);
        next.set("to", to);
        next.set(key, id);
        return next;
      },
      { replace: true, preventScrollReset: true },
    );
  }

  const first = (data.page - 1) * 50 + 1;
  const last = first + data.revisions.length - 1;
  return (
    <>
      <ContextBar>
        <Crumbs last={data.file ?? undefined} />
        <div className="bar-end bar-actions">
          {data.page > 1 ? (
            <Link className="button button-quiet" to={listPath(data.file, data.page - 1)}>
              <ChevronLeft aria-hidden="true" />
              Newer
            </Link>
          ) : null}
          {data.page < data.pages ? (
            <Link className="button button-quiet" to={listPath(data.file, data.page + 1)}>
              Older
              <ChevronRight aria-hidden="true" />
            </Link>
          ) : null}
          {from && to ? (
            <Link className="button" to={comparePath(from, to)}>
              <GitCompareArrows aria-hidden="true" />
              Compare
            </Link>
          ) : null}
        </div>
      </ContextBar>

      {data.hand_edits.length > 0 && (
        <div className="notes">
          <p className="note">
            The config directory has hand edits that are not in the history yet: {data.hand_edits.map((name, index) => (
              <span key={name}>
                {index > 0 && ", "}
                <code>{name}</code>
              </span>
            ))}
            . The next dw reload or portal save commits them.
          </p>
        </div>
      )}
      {data.file && (
        <p className="note">
          Only the versions that changed <code>{data.file}</code>. <Link to={HISTORY}>Show every version</Link>
        </p>
      )}

      {data.revisions.length === 0 ? (
        <p>{data.file ? "No version changed this file." : "The history has no versions yet."}</p>
      ) : (
        <table className="records history-list">
          <thead>
            <tr>
              <th scope="col" className="history-pick">From</th>
              <th scope="col" className="history-pick">To</th>
              <th scope="col">Time</th>
              <th scope="col">Who</th>
              <th scope="col">What</th>
              <th scope="col">Files</th>
            </tr>
          </thead>
          <tbody>
            {data.revisions.map((row) => (
              <tr key={row.id} data-chosen={row.id === from || row.id === to || undefined}>
                <td className="history-pick">
                  <input type="radio" name="from" aria-label={`From ${row.time}`} checked={row.id === from} onChange={() => choose("from", row.id)} />
                </td>
                <td className="history-pick">
                  <input type="radio" name="to" aria-label={`To ${row.time}`} checked={row.id === to} onChange={() => choose("to", row.id)} />
                </td>
                <td>
                  <Link to={revisionPath(row.short)} title={row.id}>
                    {row.time}
                  </Link>
                </td>
                <td>{row.author}</td>
                <td>{row.what}</td>
                <td>
                  <ul className="history-files">
                    {row.files.map((file) => (
                      <li key={file}>
                        <Link to={listPath(file)}>{file}</Link>
                      </li>
                    ))}
                  </ul>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <StatusBar>
        {report && <Outcome result={{ ok: true, message: report.message, warnings: report.warnings }} />}
        <span>{data.total === 0 ? "No versions." : `Versions ${first} to ${last} of ${data.total}.`}</span>
        <span>{data.times}</span>
      </StatusBar>
    </>
  );
}

function Details({ revision, label = "" }: { revision: Revision; label?: string }) {
  return (
    <dl className="summary history-details" aria-label={label || undefined}>
      {label && (
        <div>
          <dt>{label}</dt>
          <dd>
            <Link to={revisionPath(revision.short)}>{revision.time}</Link>
          </dd>
        </div>
      )}
      {!label && (
        <div>
          <dt>Time</dt>
          <dd>{revision.time}</dd>
        </div>
      )}
      <div>
        <dt>Who</dt>
        <dd>{revision.author}</dd>
      </div>
      {!label && (
        <>
          <div>
            <dt>What</dt>
            <dd>{revision.what}</dd>
          </div>
          <div>
            <dt>Revision</dt>
            <dd>
              <code>{revision.id}</code>
            </dd>
          </div>
        </>
      )}
    </dl>
  );
}

// One revision

export async function revisionLoader({ request, params }: LoaderFunctionArgs): Promise<RevisionPage | Missing> {
  return orMissing(() => api<RevisionPage>(revisionData(params.revision ?? ""), { page: pageOf(request), signal: request.signal }));
}

/** Revert: sent from the revision's page with the newest revision the dialog was opened on. */
export async function revisionAction({ request, params }: ActionFunctionArgs): Promise<Result> {
  const body = await request.json();
  try {
    const done = await api<Omit<Result, "ok">>(`${revisionData(params.revision ?? "")}/revert`, { page: pageOf(request), method: "POST", body });
    return { ok: true, ...done };
  } catch (error) {
    if (error instanceof ApiError) return { ok: false, ...(error.data as Partial<Result>), error: error.message };
    throw error;
  }
}

/** A refused revert keeps the page as it was, with the dialog open on the reasons. */
export function revisionShouldRevalidate({ actionResult, defaultShouldRevalidate }: ShouldRevalidateFunctionArgs) {
  if ((actionResult as Result | undefined)?.ok === false) return false;
  return defaultShouldRevalidate;
}

/** A revision's details and what it changed against the revision before it, with Revert to this version. */
export function RevisionView() {
  const data = useLoaderData() as RevisionPage | Missing;
  if (isMissing(data)) return <NotFound />;
  return <RevisionDetails key={data.revision.id} data={data} />;
}

function RevisionDetails({ data }: { data: RevisionPage }) {
  const { revision } = data;
  const [reverting, setReverting] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  useTitle(`${TITLE} ${revision.time}`);
  return (
    <>
      <ContextBar>
        <Crumbs last={revision.time} />
        <div className="bar-end bar-actions">
          {!data.newest && (
            <Link className="button button-quiet" to={comparePath(revision.short, "current")}>
              <GitCompareArrows aria-hidden="true" />
              Compare with current
            </Link>
          )}
          {!data.newest && (
            <button type="button" className="button" onClick={() => setReverting(true)}>
              <Undo2 aria-hidden="true" />
              Revert to this version
            </button>
          )}
        </div>
      </ContextBar>

      <Details revision={revision} />
      <h2>{data.before === null ? "Every file, as this first version added it" : "What this version changed"}</h2>
      <DiffView files={data.diff} empty="This version changed no files." />

      <StatusBar>
        {result && <Outcome result={result} />}
        <span>
          {data.diff.length} file{data.diff.length === 1 ? "" : "s"} changed.
        </span>
        {data.newest && <span>This is the newest version.</span>}
      </StatusBar>

      {reverting && (
        <RevertDialog
          revision={revision}
          onClose={(done) => {
            setReverting(false);
            if (done) setResult(done);
          }}
        />
      )}
    </>
  );
}

/**
 * The portal's own dialog for Revert, with Cancel the default. It shows the diff from the newest revision that the
 * revert would make, the renames it crosses, and that mcp.yaml is kept. A refusal keeps it open with the reasons.
 */
function RevertDialog({ revision, onClose }: { revision: Revision; onClose: (done: Result | null) => void }) {
  const heading = useId();
  const location = useLocation();
  const navigate = useNavigate();
  const fetcher = useFetcher<Result>();
  const handled = useRef<Result | undefined>(undefined);
  const [preview, setPreview] = useState<RevertPreview | null>(null);
  const [refused, setRefused] = useState<Result | null>(null);
  const busy = fetcher.state !== "idle";
  const page = BASE + location.pathname + location.search;

  useEffect(() => {
    const control = new AbortController();
    api<RevertPreview>(`${revisionData(revision.short)}/revert`, { page, signal: control.signal })
      .then(setPreview)
      .catch((error: unknown) => {
        if (error instanceof ApiError) setRefused({ ok: false, error: error.message });
        else if (!control.signal.aborted) setRefused({ ok: false, error: "The service did not answer." });
      });
    return () => control.abort();
  }, [revision.short, page]);

  useEffect(() => {
    const done = fetcher.data;
    if (fetcher.state !== "idle" || done === undefined || handled.current === done) return;
    handled.current = done;
    if (!done.ok) {
      setRefused(done);
      return;
    }
    if (done.nothing) {
      onClose(done);
      return;
    }
    navigate(HISTORY, { state: { message: done.message ?? "", warnings: done.warnings ?? [] } satisfies Report });
  }, [fetcher.state, fetcher.data, navigate, onClose]);

  function key(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && !busy) {
      event.preventDefault();
      onClose(null);
    }
  }

  const stale = refused?.stale === true;
  return (
    <div className="dialog-backdrop">
      <div className="dialog dialog-wide" role="alertdialog" aria-modal="true" aria-labelledby={heading} onKeyDown={key}>
        <h2 id={heading}>Revert to {revision.time}?</h2>
        <div className="dialog-body">
          {preview === null && refused === null && <p aria-busy="true">Working out what the revert would change…</p>}
          {preview && (
            <>
              <p>
                Every file in the config directory goes back as it was in this version, as one new version. Every version
                from before is kept in the history.
              </p>
              <p className="note">{preview.mcp}</p>
              {preview.renames.length > 0 && (
                <ul className="history-renames" aria-label="Renames since this version">
                  {preview.renames.map((sentence) => (
                    <li key={sentence}>{sentence}</li>
                  ))}
                </ul>
              )}
              {preview.nothing ? (
                <p>This version is the same as the newest one, apart from the MCP settings, so reverting changes nothing.</p>
              ) : (
                <DiffView files={preview.diff} />
              )}
            </>
          )}
          {refused && (
            <div className="notes" role="alert">
              <p className="note note-problem">{refused.error}</p>
              {refused.errors && refused.errors.length > 0 && (
                <ul className="status-errors">
                  {refused.errors.map((problem) => (
                    <li key={problem}>{problem}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
        <div className="dialog-buttons">
          <button
            type="button"
            className="button button-quiet"
            disabled={preview === null || busy || stale}
            onClick={() => {
              if (preview === null) return;
              setRefused(null);
              fetcher.submit({ head: preview.head }, { method: "post", encType: "application/json" });
            }}
          >
            Revert
          </button>
          <button type="button" className="button" autoFocus disabled={busy} onClick={() => onClose(null)}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

// Comparing

export async function compareLoader({ request }: LoaderFunctionArgs): Promise<ComparePage | Missing> {
  const asked = new URL(request.url).searchParams;
  const search = new URLSearchParams({ from: asked.get("from") ?? "", to: asked.get("to") ?? "" });
  return orMissing(() => api<ComparePage>(`${HISTORY_DATA}/compare?${search}`, { page: pageOf(request), signal: request.signal }));
}

/** The diff from one revision to another, in that direction. */
export function CompareView() {
  const data = useLoaderData() as ComparePage | Missing;
  useTitle(`${TITLE} compare`);
  if (isMissing(data)) return <NotFound />;
  return (
    <>
      <ContextBar>
        <Crumbs last="Compare" />
      </ContextBar>
      <div className="history-pair">
        <Details revision={data.from} label="From" />
        <Details revision={data.to} label="To" />
      </div>
      <DiffView files={data.diff} empty="Nothing differs: these two versions have the same files." />
      <StatusBar>
        <span>
          {data.diff.length} file{data.diff.length === 1 ? "" : "s"} differ{data.diff.length === 1 ? "s" : ""}.
        </span>
      </StatusBar>
    </>
  );
}
