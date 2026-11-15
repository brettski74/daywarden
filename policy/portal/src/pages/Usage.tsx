import { X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLoaderData, useLocation, useNavigate, type LoaderFunctionArgs } from "react-router";
import { ApiError, BASE, api, pageOf } from "../api";
import { DateField } from "../components/DateField";
import { Dialog } from "../components/Dialog";
import { MultiSelect } from "../components/MultiSelect";
import { NameDialog } from "../components/NameDialog";
import { BarChart, type Bar } from "../components/charts/BarChart";
import { LineChart } from "../components/charts/LineChart";
import { NOT_A_DATE, parseDay } from "../dates";
import { useExpander } from "../motion";
import { ContextBar, StatusBar, useTitle } from "../slots";
import {
  DEFAULT_PRESET,
  GROUP_BY,
  RANGES,
  bytesAxis,
  durationAxis,
  formatBytes,
  formatDuration,
  groupByChoices,
  lineOf,
  presetQuery,
  quotasBlocked,
  rangeLabel,
  settingsQuery,
  sitesBlocked,
  toggled,
  withLine,
  type GroupBy,
  type Hosts,
  type RangeName,
  type Settings,
  type Unit,
  type UsageData,
} from "../usage";

const TITLES: Record<Unit, string> = { minutes: "Minutes", bytes: "Bytes" };
const SEGMENTS: Record<Unit, string[]> = { minutes: ["Minutes"], bytes: ["Downloaded", "Uploaded"] };

function hostBars(hosts: Hosts, unit: Unit): Bar[] {
  return hosts.bars.map((bar) => ({ name: bar.host, values: unit === "minutes" ? [bar.value] : [bar.down ?? bar.value, bar.up ?? 0] }));
}

const BAR_TEXT: Record<Unit, (bar: Bar) => string> = {
  minutes: (bar) => formatDuration(bar.values[0]),
  bytes: (bar) => `${formatBytes(bar.values[0])} down, ${formatBytes(bar.values[1])} up`,
};

/** The top hosts on the line drilled into, beneath the graph. It opens and closes with the shared animation. */
function HostPanel({ hosts, settings, unit, open, moving, onClose }: { hosts: Hosts; settings: Settings; unit: Unit; open: boolean; moving: boolean; onClose: () => void }) {
  const heading = `${hosts.line}, ${rangeLabel(settings)}: top hosts`;
  const bars = useMemo(() => hostBars(hosts, unit), [hosts, unit]);
  return (
    <section className="usage-hosts" aria-label={heading} data-open={open || undefined} data-moving={moving || undefined} inert={!open}>
      <div className="usage-hosts-inner">
        <div className="usage-hosts-head">
          <h2>{heading}</h2>
          <button type="button" className="icon-button icon-button-quiet" aria-label="Close top hosts" title="Close top hosts" onClick={onClose}>
            <X aria-hidden="true" />
          </button>
        </div>
        {hosts.kept && <p className="usage-hosts-kept">{hosts.kept}</p>}
        <BarChart label={heading} bars={bars} segments={SEGMENTS[unit]} format={BAR_TEXT[unit]} empty="No hosts in this range." />
      </div>
    </section>
  );
}

/** The loader for one unit's page. The data endpoint takes the page's own query string. */
export function usageLoader(unit: Unit) {
  return ({ request }: LoaderFunctionArgs): Promise<UsageData> =>
    api<UsageData>(`/usage/${unit}${new URL(request.url).search}`, { page: pageOf(request), signal: request.signal });
}

type Asking = { kind: "name" } | { kind: "replace"; name: string } | { kind: "delete"; name: string } | null;
type Outcome = { ok: boolean; message: string };

/** The problems under the Custom range's From and To boxes. A box whose own text is not a date says so itself. */
function dateProblems(from: string, to: string): { from: string | null; to: string | null } {
  const first = parseDay(from);
  const last = parseDay(to);
  return {
    from: from.trim() === "" ? NOT_A_DATE : null,
    to: to.trim() === "" ? NOT_A_DATE : first !== null && last !== null && to.trim() < from.trim() ? "To is before From." : null,
  };
}

/** The Minutes or Bytes page: a line graph of usage, with its filters, date range, and presets in the context bar. */
export function Usage({ unit }: { unit: Unit }) {
  const data = useLoaderData() as UsageData;
  const location = useLocation();
  const navigate = useNavigate();
  useTitle(`Usage ${TITLES[unit].toLowerCase()}`);

  // The controls show a change at once, before the graph for it has loaded.
  const [held, setHeld] = useState(data);
  const [draft, setDraft] = useState<Settings>(data.settings);
  const [dates, setDates] = useState({ from: data.settings.from, to: data.settings.to });
  const [refusal, setRefusal] = useState<string | null>(null);
  const [asking, setAsking] = useState<Asking>(null);
  if (held !== data) {
    setHeld(data);
    setDraft(data.settings);
    setDates({ from: data.settings.from, to: data.settings.to });
    setRefusal(null);
  }

  const custom = draft.range === "custom";
  const [open, setOpen] = useState(custom);
  const { shown, moving, toggle } = useExpander(open, setOpen);
  useEffect(() => {
    if (custom !== open) toggle();
  }, [custom, open, toggle]);

  // The bars stay on screen while the panel collapses, after the address has dropped the line.
  const drilled = data.hosts !== null;
  const [lastHosts, setLastHosts] = useState(data.hosts);
  if (data.hosts !== null && data.hosts !== lastHosts) setLastHosts(data.hosts);
  const [hostsOpen, setHostsOpen] = useState(drilled);
  const hostsMotion = useExpander(hostsOpen, setHostsOpen);
  const toggleHosts = hostsMotion.toggle;
  useEffect(() => {
    if (drilled !== hostsOpen) toggleHosts();
  }, [drilled, hostsOpen, toggleHosts]);

  const here = BASE + location.pathname + location.search;
  const reported = location.state as Outcome | null;
  const outcome: Outcome | null = refusal !== null ? { ok: false, message: refusal } : reported;
  const line = lineOf(location.search);

  /** Change the settings. The line drilled into stays, unless Group by changes what the lines are. */
  function change(patch: Partial<Settings>) {
    const next = { ...draft, ...patch };
    setDraft(next);
    navigate({ search: settingsQuery(next, next.by === draft.by ? line : null) });
  }

  function drill(name: string) {
    navigate({ search: withLine(location.search, name) });
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

  /** Send a preset change. Return why it was refused, or null. A signed-out parent goes to sign-in and comes back here. */
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
    navigate({ search: presetQuery(done.name, line) }, { state: { ok: true, message: done.message } satisfies Outcome });
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
    else navigate({ search: settingsQuery(data.settings, line) }, { state: { ok: true, message: done.message } satisfies Outcome });
  }

  const sitesWhy = sitesBlocked(draft);
  const quotasWhy = quotasBlocked(draft);
  const problems = dateProblems(dates.from, dates.to);
  const deleteWhy =
    data.preset === "" ? "Choose a preset to delete it." : data.preset === DEFAULT_PRESET ? `${DEFAULT_PRESET} can be replaced but not deleted.` : null;
  const graph = data.graph;
  const byName = GROUP_BY.find(([value]) => value === data.settings.by)?.[1] ?? "";

  return (
    <>
      <ContextBar>
        <nav className="crumbs" aria-label="Where you are">
          <ol>
            <li>Usage</li>
            <li>
              <h1 className="bar-title">{TITLES[unit]}</h1>
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
            Group by
            <select value={draft.by} onChange={(event) => change({ by: event.target.value as GroupBy })}>
              {groupByChoices(draft).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
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
        </div>
      </ContextBar>

      <div className="usage-page" data-hosts={hostsOpen || undefined}>
        <div className="usage-graph">
          {graph === null ? (
            <p>Fix the date range to draw the graph.</p>
          ) : (
            <LineChart
              label={`${TITLES[unit]} ${data.settings.by === "none" ? "in total" : `by ${byName.toLowerCase()}`}`}
              length={graph.length}
              ticks={graph.ticks}
              points={graph.points}
              series={graph.lines}
              axis={unit === "minutes" ? durationAxis : bytesAxis}
              format={unit === "minutes" ? formatDuration : formatBytes}
              empty="No usage in this range."
              onOpen={drill}
              openTitle={(name) => `Show the top hosts for ${name}`}
            />
          )}
        </div>
        {hostsMotion.shown && lastHosts !== null && (
          <HostPanel
            hosts={data.hosts ?? lastHosts}
            settings={data.settings}
            unit={unit}
            open={hostsOpen}
            moving={hostsMotion.moving}
            onClose={() => navigate({ search: withLine(location.search, null) })}
          />
        )}
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
        <span>{data.range ? `${data.range}. ${data.times}` : data.times}</span>
      </StatusBar>
    </>
  );
}
