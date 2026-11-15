import { useEffect, useState } from "react";
import { useLoaderData, useLocation, useNavigate, type LoaderFunctionArgs } from "react-router";
import { ApiError, BASE, api, pageOf } from "../api";
import { DateField } from "../components/DateField";
import { Dialog } from "../components/Dialog";
import { MultiSelect } from "../components/MultiSelect";
import { NameDialog } from "../components/NameDialog";
import { RequestTable } from "../components/RequestTable";
import { NOT_A_DATE, parseDay } from "../dates";
import { useExpander } from "../motion";
import { ContextBar, StatusBar, useTitle } from "../slots";
import {
  DEFAULT_PRESET,
  OUTCOMES,
  RANGES,
  presetQuery,
  quotasBlocked,
  requestsQuery,
  sitesBlocked,
  toggled,
  withTable,
  type RangeName,
  type RequestsData,
  type Settings,
} from "../usage";

type Asking = { kind: "name" } | { kind: "replace"; name: string } | { kind: "delete"; name: string } | null;
type Outcome = { ok: boolean; message: string };

function dateProblems(from: string, to: string): { from: string | null; to: string | null } {
  const first = parseDay(from);
  const last = parseDay(to);
  return {
    from: from.trim() === "" ? NOT_A_DATE : null,
    to: to.trim() === "" ? NOT_A_DATE : first !== null && last !== null && to.trim() < from.trim() ? "To is before From." : null,
  };
}

/** The loader for the Requests page. */
export function requestsLoader({ request }: LoaderFunctionArgs): Promise<RequestsData> {
  return api<RequestsData>(`/usage/requests${new URL(request.url).search}`, { page: pageOf(request), signal: request.signal });
}

/** Every request within the filters, with a Host box and Outcome pull-down. */
export function Requests() {
  const data = useLoaderData() as RequestsData;
  const location = useLocation();
  const navigate = useNavigate();
  useTitle("Usage requests");

  const [held, setHeld] = useState(data);
  const [draft, setDraft] = useState<Settings>(data.settings);
  const [dates, setDates] = useState({ from: data.settings.from, to: data.settings.to });
  const [host, setHost] = useState(data.host);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [asking, setAsking] = useState<Asking>(null);
  if (held !== data) {
    setHeld(data);
    setDraft(data.settings);
    setDates({ from: data.settings.from, to: data.settings.to });
    setHost(data.host);
    setRefusal(null);
  }

  const custom = draft.range === "custom";
  const [open, setOpen] = useState(custom);
  const { shown, moving, toggle } = useExpander(open, setOpen);
  useEffect(() => {
    if (custom !== open) toggle();
  }, [custom, open, toggle]);

  const here = BASE + location.pathname + location.search;
  const reported = location.state as Outcome | null;
  const outcome: Outcome | null = refusal !== null ? { ok: false, message: refusal } : reported;

  function go(next: Settings, extras: { host?: string; outcome?: string[] } = {}) {
    setDraft(next);
    navigate({
      search: requestsQuery(next, {
        host: extras.host ?? host,
        outcome: extras.outcome ?? data.outcome,
      }),
    });
  }

  function change(patch: Partial<Settings>) {
    go({ ...draft, ...patch });
  }

  function chooseRange(range: RangeName) {
    if (range === "custom") change({ range, from: data.days?.from ?? data.today, to: data.days?.to ?? data.today });
    else change({ range, from: "", to: "" });
  }

  function typeDate(which: "from" | "to", text: string) {
    const next = { ...dates, [which]: text };
    setDates(next);
    const problems = dateProblems(next.from, next.to);
    const fine = parseDay(next.from) !== null && parseDay(next.to) !== null && problems.from === null && problems.to === null;
    if (fine && (next.from.trim() !== draft.from || next.to.trim() !== draft.to)) change({ from: next.from.trim(), to: next.to.trim() });
  }

  function typeHost(text: string) {
    setHost(text);
  }

  function applyHost() {
    if (host === data.host) return;
    go(draft, { host });
  }

  async function send(path: string, body: unknown): Promise<{ name: string; message: string } | string> {
    try {
      return await api<{ name: string; message: string }>(path, { page: here, method: "POST", body });
    } catch (error) {
      if (error instanceof ApiError) return error.message;
      if (error instanceof Response && error.headers.get("Location")) {
        navigate(error.headers.get("Location") as string);
        return "Sign in to save presets.";
      }
      throw error;
    }
  }

  async function save(name: string, replace: boolean): Promise<string | null> {
    const done = await send("/usage/presets", { name, settings: data.settings, replace });
    if (typeof done === "string") return done;
    setAsking(null);
    navigate({ search: presetQuery(done.name) }, { state: { ok: true, message: done.message } satisfies Outcome });
    return null;
  }

  async function named(name: string): Promise<string | null> {
    const existing = data.presets.find((preset) => preset.toLowerCase() === name.trim().toLowerCase());
    if (existing !== undefined) {
      setAsking({ kind: "replace", name: existing });
      return null;
    }
    return save(name, false);
  }

  async function replace(name: string) {
    const problem = await save(name, true);
    if (problem !== null) {
      setAsking(null);
      setRefusal(problem);
    }
  }

  async function remove(name: string) {
    setAsking(null);
    const done = await send("/usage/presets/delete", { name });
    if (typeof done === "string") setRefusal(done);
    else navigate({ search: requestsQuery(data.settings, { host: data.host, outcome: data.outcome }) }, { state: { ok: true, message: done.message } satisfies Outcome });
  }

  // Group by is ignored here, so only a chosen site or quota list blocks the other.
  const sitesWhy = draft.quota.length > 0 ? sitesBlocked({ ...draft, by: "client" }) : null;
  const quotasWhy = draft.site.length > 0 ? quotasBlocked({ ...draft, by: "client" }) : null;
  const problems = dateProblems(dates.from, dates.to);
  const deleteWhy =
    data.preset === "" ? "Choose a preset to delete it." : data.preset === DEFAULT_PRESET ? `${DEFAULT_PRESET} can be replaced but not deleted.` : null;

  return (
    <>
      <ContextBar>
        <nav className="crumbs" aria-label="Where you are">
          <ol>
            <li>Usage</li>
            <li>
              <h1 className="bar-title">Requests</h1>
            </li>
          </ol>
        </nav>
        <div className="bar-actions bar-end">
          <label className="bar-field bar-preset">
            Preset
            <select value={data.preset} onChange={(event) => event.target.value && navigate({ search: presetQuery(event.target.value) })}>
              {data.preset === "" && <option value="" />}
              {data.presets.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="button" onClick={() => setAsking({ kind: "name" })}>
            Save preset
          </button>
          <button
            type="button"
            className="button button-quiet"
            disabled={deleteWhy !== null}
            title={deleteWhy ?? undefined}
            onClick={() => setAsking({ kind: "delete", name: data.preset })}
          >
            Delete preset
          </button>
        </div>
        <div className="bar-filters">
          <MultiSelect label="Client groups" options={data.choices.clients} selected={draft.client} empty="All" onToggle={(name) => change({ client: toggled(draft.client, name) })} />
          <MultiSelect
            label="Site groups"
            options={data.choices.sites}
            selected={draft.site}
            empty="All"
            disabled={sitesWhy !== null}
            disabledTitle={sitesWhy ?? undefined}
            onToggle={(name) => change({ site: toggled(draft.site, name) })}
          />
          <MultiSelect
            label="Quotas"
            options={data.choices.quotas}
            selected={draft.quota}
            empty="All"
            disabled={quotasWhy !== null}
            disabledTitle={quotasWhy ?? undefined}
            onToggle={(name) => change({ quota: toggled(draft.quota, name) })}
          />
          <label className="bar-field">
            Date range
            <select value={draft.range} onChange={(event) => chooseRange(event.target.value as RangeName)}>
              {RANGES.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          {shown && (
            <div className="bar-dates" data-open={open || undefined} data-moving={moving || undefined} inert={!open}>
              <div className="bar-dates-inner">
                <div className="bar-date">
                  <DateField name="from" label="From" value={dates.from} today={data.today} changed={false} problem={problems.from} onChange={(text) => typeDate("from", text)} />
                </div>
                <div className="bar-date">
                  <DateField name="to" label="To" value={dates.to} today={data.today} changed={false} problem={problems.to} onChange={(text) => typeDate("to", text)} />
                </div>
              </div>
            </div>
          )}
          <label className="bar-field">
            Host
            <input
              type="text"
              value={host}
              onChange={(event) => typeHost(event.target.value)}
              onBlur={applyHost}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  applyHost();
                }
              }}
              placeholder="Any"
            />
          </label>
          <MultiSelect
            label="Outcome"
            options={[...OUTCOMES]}
            selected={data.outcome}
            empty="All"
            onToggle={(name) => go(draft, { outcome: toggled(data.outcome, name) })}
          />
        </div>
      </ContextBar>

      <div className="requests-page">
        {data.kept && <p className="usage-hosts-kept">{data.kept}</p>}
        <RequestTable
          rows={data.rows}
          sort={data.sort}
          dir={data.dir}
          page={data.page}
          pages={data.pages}
          href={(patch) => withTable(location.search || requestsQuery(data.settings, { host: data.host, outcome: data.outcome }), { ...patch })}
          empty={
            data.kept
              ? "No request rows in the part of the range that is still kept. Earlier usage still appears on Minutes and Bytes."
              : "No requests in this range."
          }
        />
      </div>

      {asking?.kind === "name" && <NameDialog title="Save preset" label="Name" onSubmit={named} onCancel={() => setAsking(null)} />}
      {asking?.kind === "replace" && (
        <Dialog
          title="Replace preset?"
          message={`There is already a preset called ${asking.name}. Replace it with the settings on show?`}
          confirm="Replace"
          cancel="Cancel"
          onConfirm={() => replace(asking.name)}
          onCancel={() => setAsking(null)}
        />
      )}
      {asking?.kind === "delete" && (
        <Dialog
          title="Delete preset?"
          message={`Delete the preset ${asking.name}? This cannot be undone.`}
          confirm="Delete"
          cancel="Cancel"
          onConfirm={() => remove(asking.name)}
          onCancel={() => setAsking(null)}
        />
      )}

      <StatusBar>
        {outcome && <span className={outcome.ok ? "status-done" : "status-refused"}>{outcome.message}</span>}
        {data.notes.map((note) => (
          <span key={note}>{note}</span>
        ))}
        {data.status && <span>{data.status}</span>}
        <span>{data.range ? `${data.range}. ${data.times}` : data.times}</span>
      </StatusBar>
    </>
  );
}
