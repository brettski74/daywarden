import { Copy, PencilLine, Save, ScrollText, Unplug } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Link,
  useBlocker,
  useFetcher,
  useLoaderData,
  useLocation,
  useRevalidator,
  type ActionFunctionArgs,
  type LoaderFunctionArgs,
  type ShouldRevalidateFunctionArgs,
} from "react-router";
import { ApiError, api, pageOf } from "../api";
import { Dialog } from "../components/Dialog";
import {
  DURATIONS,
  DURATION_LABELS,
  MCP_ACTIVITY,
  MCP_DATA,
  PERMISSIONS,
  classLabel,
  daysProblem,
  durationProblem,
  granted,
  settingsChanged,
  withPermission,
  type McpConnection,
  type McpPage,
  type McpSettings,
} from "../mcp";
import { ContextBar, StatusBar, useTitle } from "../slots";
import { Outcome } from "./Task";

export const TITLE = "MCP Server";

type Result = { ok: boolean; message?: string; warnings?: string[]; error?: string; errors?: string[] };

export async function mcpLoader({ request }: LoaderFunctionArgs): Promise<McpPage> {
  return api<McpPage>(MCP_DATA, { page: pageOf(request), signal: request.signal });
}

/** Save the settings. Sent from the page on show, so a refusal returns to it. */
export async function mcpAction({ request }: ActionFunctionArgs): Promise<Result> {
  const body = await request.json();
  try {
    const done = await api<Result>(MCP_DATA, { page: pageOf(request), method: "POST", body });
    return { ...done, ok: true };
  } catch (error) {
    if (error instanceof ApiError) return { ok: false, ...(error.data as Partial<Result>), error: error.message };
    throw error;
  }
}

/** A refused save keeps the page as it was, so a file changed on the server stays refused until the page is reloaded. */
export function mcpShouldRevalidate({ actionResult, defaultShouldRevalidate }: ShouldRevalidateFunctionArgs) {
  if ((actionResult as Result | undefined)?.ok === false) return false;
  return defaultShouldRevalidate;
}

export function Mcp() {
  const data = useLoaderData() as McpPage;
  return <McpEditor data={data} />;
}

function McpEditor({ data }: { data: McpPage }) {
  const fetcher = useFetcher<Result>();
  const revalidator = useRevalidator();
  const location = useLocation();
  const handled = useRef<Result | undefined>(undefined);
  const [edited, setEdited] = useState<McpSettings | null>(null);
  const [days, setDays] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [revoking, setRevoking] = useState<McpConnection | null>(null);
  useTitle(TITLE);

  const settings = edited ?? data.settings;
  const dayText = days ?? String(data.settings.activity_days);
  const troubles = [
    ...DURATIONS.map((name) => durationProblem(settings[name]) && `${DURATION_LABELS[name]}: ${durationProblem(settings[name])}`),
    daysProblem(dayText) && `${DURATION_LABELS.activity_days}: ${daysProblem(dayText)}`,
  ].filter((problem): problem is string => Boolean(problem));
  const current: McpSettings = { ...settings, activity_days: Number(dayText) };
  const dirty = settingsChanged(data.settings, current) || dayText.trim() !== String(data.settings.activity_days);
  const busy = fetcher.state !== "idle";

  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname);

  const save = useCallback(() => {
    if (busy || !dirty) return;
    if (troubles.length) {
      setResult({ ok: false, error: "Fix the settings first.", errors: troubles });
      return;
    }
    fetcher.submit({ version: data.version, settings: current } as never, { method: "post", encType: "application/json" });
  }, [busy, dirty, troubles, fetcher, data.version, current]);

  useEffect(() => {
    const done = fetcher.data;
    if (fetcher.state !== "idle" || done === undefined || handled.current === done) return;
    handled.current = done;
    setResult(done);
    if (done.ok) {
      setEdited(null);
      setDays(null);
    }
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
    function unload(event: BeforeUnloadEvent) {
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", unload);
    return () => window.removeEventListener("beforeunload", unload);
  }, [dirty]);

  const change = (next: Partial<McpSettings>) => setEdited({ ...settings, ...next });

  async function copy() {
    try {
      await navigator.clipboard.writeText(data.endpoint);
      setResult({ ok: true, message: `Copied ${data.endpoint}.` });
    } catch {
      setResult({ ok: false, error: "The browser did not let the page copy. Select the address and copy it." });
    }
  }

  async function revoke(connection: McpConnection) {
    setRevoking(null);
    try {
      const done = await api<Result>(`${MCP_DATA}/connections/${connection.id}/revoke`, {
        page: `/parent${location.pathname}${location.search}`,
        method: "POST",
        body: {},
        signedOut: "refuse",
      });
      setResult({ ...done, ok: true });
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      setResult({ ok: false, error: error.message });
    }
    revalidator.revalidate();
  }

  return (
    <>
      <ContextBar>
        <nav className="crumbs" aria-label="Where you are">
          <ol>
            <li>Settings</li>
            <li>
              <h1 className="bar-title">{TITLE}</h1>
            </li>
          </ol>
        </nav>
        <div className="bar-end bar-actions">
          {dirty && (
            <span className="unsaved">
              <PencilLine aria-hidden="true" />
              Unsaved changes
            </span>
          )}
          <Link className="button button-quiet" to={MCP_ACTIVITY}>
            <ScrollText aria-hidden="true" />
            Activity
          </Link>
          <button type="button" className="button" onClick={save} disabled={busy || !dirty} title={dirty ? "Save (Ctrl+S)" : "Nothing to save"}>
            <Save aria-hidden="true" />
            Save
          </button>
        </div>
      </ContextBar>

      {data.problems.length > 0 && (
        <div className="notes">
          <p className="note note-problem">
            The MCP server is off, because <code>{data.file}</code> has {data.problems.length === 1 ? "a problem" : "problems"}. Fix the file and run
            dw reload, or save this page to write these settings over it.
          </p>
          <ul className="mcp-problems">
            {data.problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="task-common mcp-common">
        <fieldset>
          <legend>Server</legend>
          <div className="settings">
            <label className="setting">
              <span title="enabled">On</span>
              <span className="setting-flag" data-changed={settings.enabled !== data.settings.enabled || undefined}>
                <input type="checkbox" role="switch" checked={settings.enabled} onChange={(event) => change({ enabled: event.target.checked })} />
              </span>
            </label>
            <label className="setting">
              <span>Endpoint</span>
              <input type="text" readOnly value={data.endpoint} onFocus={(event) => event.target.select()} />
            </label>
          </div>
          <button type="button" className="button button-quiet" onClick={copy}>
            <Copy aria-hidden="true" />
            Copy endpoint
          </button>
          <p className="note">
            In Claude Code: <code>claude mcp add --transport http daywarden {data.endpoint}</code>
          </p>
        </fieldset>

        <fieldset>
          <legend>Durations</legend>
          <div className="settings">
            {DURATIONS.map((name) => (
              <label className="setting" key={name}>
                <span title={name}>{DURATION_LABELS[name]}</span>
                <input
                  type="text"
                  value={settings[name]}
                  aria-invalid={durationProblem(settings[name]) !== null || undefined}
                  data-changed={settings[name].trim() !== data.settings[name] || undefined}
                  onChange={(event) => change({ [name]: event.target.value })}
                />
              </label>
            ))}
            <label className="setting">
              <span title="activity_days">{DURATION_LABELS.activity_days}</span>
              <input
                type="text"
                inputMode="numeric"
                value={dayText}
                aria-invalid={daysProblem(dayText) !== null || undefined}
                data-changed={dayText.trim() !== String(data.settings.activity_days) || undefined}
                onChange={(event) => setDays(event.target.value)}
              />
            </label>
          </div>
        </fieldset>
      </div>

      <h2>Permissions</h2>
      <p className="note">What every connected agent may read and change. A change applies from each agent's next call.</p>
      <table className="records mcp-matrix">
        <thead>
          <tr>
            <th scope="col">Class</th>
            {PERMISSIONS.map((name) => (
              <th scope="col" key={name} className="mcp-matrix-cell">
                {name[0].toUpperCase() + name.slice(1)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.classes.map(({ name: kind, permissions }) => (
            <tr key={kind}>
              <th scope="row" title={kind}>
                {classLabel(kind)}
              </th>
              {PERMISSIONS.map((name) => {
                const ticked = granted(settings, kind, name);
                return (
                  <td key={name} className="mcp-matrix-cell">
                    {permissions.includes(name) && (
                      <span className="setting-flag" data-changed={ticked !== granted(data.settings, kind, name) || undefined}>
                        <input
                          type="checkbox"
                          aria-label={`${classLabel(kind)}: ${name}`}
                          checked={ticked}
                          onChange={(event) => change(withPermission(settings, kind, name, event.target.checked))}
                        />
                      </span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Connections</h2>
      {data.connections.length === 0 ? (
        <p>No agent is connected.</p>
      ) : (
        <table className="records">
          <thead>
            <tr>
              <th scope="col">Agent</th>
              <th scope="col">Approved By</th>
              <th scope="col">Approved</th>
              <th scope="col">Last Used</th>
              <th scope="col">Lapses</th>
              <th scope="col" aria-label="Revoke" />
            </tr>
          </thead>
          <tbody>
            {data.connections.map((connection) => (
              <tr key={connection.id}>
                <td>{connection.agent}</td>
                <td>{connection.parent}</td>
                <td>{connection.approved}</td>
                <td>{connection.last_used}</td>
                <td>{connection.lapses}</td>
                <td>
                  <button type="button" className="button button-quiet" onClick={() => setRevoking(connection)}>
                    <Unplug aria-hidden="true" />
                    Revoke
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <StatusBar>
        {result && <Outcome result={result} />}
        <span>{data.on ? "The MCP server is on." : "The MCP server is off."}</span>
        <span>
          {data.connections.length} connection{data.connections.length === 1 ? "" : "s"}.
        </span>
      </StatusBar>

      {revoking && (
        <Dialog
          title="Revoke this connection?"
          message={`${revoking.agent}, approved by ${revoking.parent}, is refused from its next call, and must be approved again in the browser.`}
          confirm="Revoke"
          cancel="Cancel"
          onConfirm={() => revoke(revoking)}
          onCancel={() => setRevoking(null)}
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
