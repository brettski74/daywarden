import { PencilLine, Save } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  useBlocker,
  useFetcher,
  useLoaderData,
  useRevalidator,
  useSearchParams,
  type ActionFunctionArgs,
  type LoaderFunctionArgs,
  type ShouldRevalidateFunctionArgs,
} from "react-router";
import { ApiError, api, pageOf } from "../api";
import { Dialog } from "../components/Dialog";
import { MultiSelect } from "../components/MultiSelect";
import { label } from "../labels";
import { ContextBar, StatusBar, useTitle } from "../slots";
import { POOL_FILTERS, SpellingAdmin, listedPools, type Pool, type SpellingData } from "./Spelling";

export type TaskData = {
  name: string;
  type: string;
  file: string;
  version: string;
  groups: string[];
  clients: string[];
  fields: Record<string, string>;
  spelling?: SpellingData;
};

export type Result = {
  intent: "save" | "retire" | "record";
  ok: boolean;
  message?: string;
  warnings?: string[];
  error?: string;
  errors?: string[];
  confirm?: string;
};

type Edits = {
  fields: Record<string, string>;
  groups: string[] | null;
  settings: Record<string, string>;
  moves: Record<string, Pool>;
};

const NO_EDITS: Edits = { fields: {}, groups: null, settings: {}, moves: {} };

const GROUPS: { legend: string; keys: string[] }[] = [
  { legend: "Cooldowns and limits", keys: ["pass_cooldown", "failure_cooldown", "max_skips", "max_passes"] },
  { legend: "Dates", keys: ["available_from", "due_date"] },
];
const PLACEHOLDERS: Record<string, string> = { pass_cooldown: "1", available_from: "yyyy-mm-dd", due_date: "yyyy-mm-dd" };

function taskPath(name: string): string {
  return `/tasks/${encodeURIComponent(name)}`;
}

export async function taskLoader({ request, params }: LoaderFunctionArgs): Promise<TaskData> {
  return api<TaskData>(taskPath(params.name ?? ""), { page: pageOf(request), signal: request.signal });
}

/**
 * Choosing a pool filter changes only the query string, so the task is not fetched again.
 *
 * Nor is it after a refused save. A file changed on the server since the page
 * opened must stay refused until the parent reloads the page and sees it.
 * A kept recording fetches it again on the same address, to list the new clips.
 */
export function taskShouldRevalidate({ currentUrl, nextUrl, formMethod, actionResult, defaultShouldRevalidate }: ShouldRevalidateFunctionArgs) {
  if (!formMethod && currentUrl.pathname === nextUrl.pathname && currentUrl.search !== nextUrl.search) return false;
  if ((actionResult as Result | undefined)?.ok === false) return false;
  return defaultShouldRevalidate;
}

/** Save the page, or retire one word. Sent from the page on show, so a refusal returns to it. */
export async function taskAction({ request, params }: ActionFunctionArgs): Promise<Result> {
  const { intent, ...body } = (await request.json()) as { intent: "save" | "retire" } & Record<string, unknown>;
  const path = taskPath(params.name ?? "") + (intent === "retire" ? "/retire" : "");
  try {
    const done = await api<{ message: string; warnings: string[] }>(path, { page: pageOf(request), method: "POST", body });
    return { intent, ok: true, ...done };
  } catch (error) {
    if (error instanceof ApiError) return { intent, ok: false, ...(error.data as Partial<Result>), error: error.message };
    throw error;
  }
}

export function Task() {
  const data = useLoaderData() as TaskData;
  return <TaskEditor key={data.name} data={data} />;
}

function changed(data: TaskData, edits: Edits): boolean {
  const differs = (shown: Record<string, string>, edited: Record<string, string>) =>
    Object.entries(edited).some(([key, value]) => value.trim() !== (shown[key] ?? "").trim());
  if (differs(data.fields, edits.fields) || differs(data.spelling?.settings ?? {}, edits.settings)) return true;
  if (edits.groups !== null && edits.groups.join("\n") !== data.groups.join("\n")) return true;
  const pools = new Map(data.spelling?.words.map((word) => [word.key, word.pool]) ?? []);
  return Object.entries(edits.moves).some(([key, pool]) => pools.has(key) && pools.get(key) !== pool);
}

function TaskEditor({ data }: { data: TaskData }) {
  const [edits, setEdits] = useState<Edits>(NO_EDITS);
  const [result, setResult] = useState<Result | null>(null);
  const [asking, setAsking] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const fetcher = useFetcher<Result>();
  const revalidator = useRevalidator();
  const handled = useRef<Result | undefined>(undefined);
  useTitle(data.name);
  const dirty = changed(data, edits);
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname);

  const save = useCallback(
    (confirmed = false) => {
      if (fetcher.state !== "idle" || !dirty) return;
      const groups = edits.groups ?? data.groups;
      fetcher.submit(
        {
          intent: "save",
          version: data.version,
          fields: { ...data.fields, ...edits.fields },
          groups,
          ...(data.spelling ? { settings: { ...data.spelling.settings, ...edits.settings }, moves: edits.moves } : {}),
          confirmed,
        },
        { method: "post", encType: "application/json" },
      );
    },
    [fetcher, data, edits, dirty],
  );

  const retire = useCallback(
    (key: string) => fetcher.submit({ intent: "retire", word: key }, { method: "post", encType: "application/json" }),
    [fetcher],
  );

  useEffect(() => {
    const done = fetcher.data;
    if (fetcher.state !== "idle" || done === undefined || handled.current === done) return;
    handled.current = done;
    if (done.intent === "save" && !done.ok && done.confirm) {
      setAsking(done.confirm);
      return;
    }
    setResult(done);
    if (done.intent === "save" && done.ok) setEdits(NO_EDITS);
  }, [fetcher.state, fetcher.data]);

  const latestSave = useRef(save);
  latestSave.current = save;
  useEffect(() => {
    function key(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "s") {
        event.preventDefault();
        latestSave.current();
      }
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  useEffect(() => {
    if (!dirty) return;
    function leaving(event: BeforeUnloadEvent) {
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", leaving);
    return () => window.removeEventListener("beforeunload", leaving);
  }, [dirty]);

  const value = (key: string) => edits.fields[key] ?? data.fields[key] ?? "";
  const setField = (key: string, text: string) => setEdits((current) => ({ ...current, fields: { ...current.fields, [key]: text } }));
  const groups = edits.groups ?? data.groups;
  const toggleGroup = (name: string) =>
    setEdits((current) => {
      const now = current.groups ?? data.groups;
      const next = now.includes(name) ? now.filter((group) => group !== name) : data.clients.filter((client) => client === name || now.includes(client));
      return { ...current, groups: next };
    });
  const asked = searchParams.get("pool") ?? "";
  const pool = POOL_FILTERS.some(([option]) => option === asked) ? asked : "";

  return (
    <>
      <ContextBar>
        <nav className="crumbs" aria-label="Where you are">
          <ol>
            <li>Tasks</li>
            <li>
              <h1 className="bar-title">{data.name}</h1>
            </li>
          </ol>
        </nav>
        {data.spelling && (
          <label className="bar-field">
            Pool
            <select value={pool} onChange={(event) => setSearchParams(event.target.value ? { pool: event.target.value } : {})}>
              {POOL_FILTERS.map(([option, label]) => (
                <option key={option} value={option}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="bar-end bar-actions">
          {dirty && (
            <span className="unsaved">
              <PencilLine aria-hidden="true" />
              Unsaved changes
            </span>
          )}
          <button
            type="button"
            className="button"
            onClick={() => save()}
            disabled={fetcher.state !== "idle" || !dirty}
            title={dirty ? "Save (Ctrl+S)" : "Nothing to save"}
          >
            <Save aria-hidden="true" />
            Save
          </button>
        </div>
      </ContextBar>

      <div className="task-common">
        <fieldset>
          <legend>Task</legend>
          <dl className="fields">
            <div>
              <dt>{label("name")}</dt>
              <dd>{data.name}</dd>
            </div>
            <div>
              <dt>{label("type")}</dt>
              <dd>{data.type}</dd>
            </div>
          </dl>
          <MultiSelect
            label="Client Groups"
            options={data.clients}
            selected={groups}
            onToggle={toggleGroup}
            changed={groups.join("\n") !== data.groups.join("\n")}
          />
        </fieldset>
        {GROUPS.map(({ legend, keys }) => {
          const shown = keys.filter((key) => key in data.fields);
          if (shown.length === 0) return null;
          return (
            <fieldset key={legend}>
              <legend>{legend}</legend>
              <div className="settings">
                {shown.map((key) => (
                  <label key={key} className="setting">
                    <span title={key}>{label(key)}</span>
                    <input
                      type="text"
                      inputMode={key.endsWith("_from") || key.endsWith("_date") ? undefined : "numeric"}
                      value={value(key)}
                      placeholder={PLACEHOLDERS[key]}
                      data-changed={value(key).trim() !== (data.fields[key] ?? "").trim() || undefined}
                      onChange={(event) => setField(key, event.target.value)}
                    />
                  </label>
                ))}
              </div>
            </fieldset>
          );
        })}
      </div>

      <hr className="task-divider" />

      {data.spelling ? (
        <SpellingAdmin
          task={data.name}
          data={data.spelling}
          filter={pool}
          settings={edits.settings}
          moves={edits.moves}
          onSetting={(key, text) => setEdits((current) => ({ ...current, settings: { ...current.settings, [key]: text } }))}
          onMove={(key, to) => setEdits((current) => ({ ...current, moves: { ...current.moves, [key]: to } }))}
          onRetire={retire}
          onPlayFailed={(message) => setResult({ intent: "retire", ok: false, error: message })}
          onRecorded={(message, written) => {
            setResult({ intent: "record", ok: true, message, warnings: [] });
            if (written) void revalidator.revalidate();
          }}
        />
      ) : (
        <p>Task-specific administration for {data.type} tasks is not built yet.</p>
      )}

      <StatusBar>
        {result && <Outcome result={result} />}
        {data.spelling && <span>{counts(data.spelling, pool)}</span>}
      </StatusBar>

      {asking !== null && (
        <Dialog
          title="Save anyway?"
          message={asking}
          confirm="Save"
          cancel="Cancel"
          onConfirm={() => {
            setAsking(null);
            save(true);
          }}
          onCancel={() => setAsking(null)}
        />
      )}
      {blocker.state === "blocked" && (
        <Dialog
          title="Leave this page?"
          message="The changes on this page have not been saved. Leaving loses them."
          confirm="Leave"
          cancel="Stay"
          onConfirm={() => blocker.proceed()}
          onCancel={() => blocker.reset()}
        />
      )}
    </>
  );
}

function Outcome({ result }: { result: Result }) {
  if (result.ok) {
    return (
      <>
        <span className="status-done">{result.message}</span>
        {result.warnings?.map((warning) => (
          <span key={warning} className="status-refused">
            {warning}
          </span>
        ))}
      </>
    );
  }
  return (
    <>
      <span className="status-refused">{result.error}</span>
      {result.errors && result.errors.length > 0 && (
        <ul className="status-errors">
          {result.errors.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      )}
    </>
  );
}

function counts(spelling: SpellingData, filter: string): string {
  const parts = listedPools(filter).map((pool) => {
    const count = spelling.words.filter((word) => word.pool === pool).length;
    return `${count} ${pool}`;
  });
  return `Words listed: ${parts.join(", ")}.`;
}
