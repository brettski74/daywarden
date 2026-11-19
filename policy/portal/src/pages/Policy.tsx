import { PencilLine, Plus, Save, TextCursorInput, Trash2, Undo2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  Link,
  useBlocker,
  useFetcher,
  useLoaderData,
  useRevalidator,
  type ActionFunctionArgs,
  type LoaderFunctionArgs,
  type ShouldRevalidateFunctionArgs,
} from "react-router";
import { ApiError, api, pageOf } from "../api";
import { Dialog } from "../components/Dialog";
import { NameDialog } from "../components/NameDialog";
import { label } from "../labels";
import {
  HOUSEHOLD_TEXT,
  SWITCHES,
  WEEKDAYS,
  anyChanged,
  blankFields,
  extraProblem,
  householdChanged,
  householdProblem,
  householdRequest,
  infoOf,
  normalizeClock,
  pageProblem,
  policyPath,
  rowChanged,
  rowProblem,
  rowsFrom,
  sameFields,
  saveRequest,
  type Fields,
  type HouseholdData,
  type HouseholdEdits,
  type ItemPage,
  type ItemsData,
  type PageKey,
  type Period,
  type Row,
} from "../policy";
import { ContextBar, StatusBar, useTitle } from "../slots";
import { Outcome } from "./Task";

type Result = { ok: boolean; message?: string; warnings?: string[]; error?: string; errors?: string[] };

export function policyLoader(key: PageKey) {
  return ({ request }: LoaderFunctionArgs) => api<ItemsData | HouseholdData>(`/policy/${key}`, { page: pageOf(request), signal: request.signal });
}

/** Save the page. Sent from the page on show, so a refusal returns to it. */
export function policyAction(key: PageKey) {
  return async ({ request }: ActionFunctionArgs): Promise<Result> => {
    const body = await request.json();
    try {
      const done = await api<Omit<Result, "ok">>(`/policy/${key}`, { page: pageOf(request), method: "POST", body });
      return { ok: true, ...done };
    } catch (error) {
      if (error instanceof ApiError) return { ok: false, ...(error.data as Partial<Result>), error: error.message };
      throw error;
    }
  };
}

/** A refused save keeps the page as it was, so files changed on the server stay refused until the page is reloaded. */
export function policyShouldRevalidate({ actionResult, defaultShouldRevalidate }: ShouldRevalidateFunctionArgs) {
  if ((actionResult as Result | undefined)?.ok === false) return false;
  return defaultShouldRevalidate;
}

/** The context bar, status bar, Save, Ctrl+S, and the leave prompt that every policy page has. */
export function PolicyFrame({ page, dirty, held, request, onSaved, onAdd, addLabel, title, parent, actions, children }: {
  page: PageKey;
  /** The page's own heading, such as a rule set's name, when it is not the section's. */
  title?: string;
  /** The section's list page, shown before the heading. */
  parent?: { to: string; label: string };
  /** More buttons for the context bar, before Save. */
  actions?: ReactNode;
  dirty: boolean;
  /** Why Save cannot be pressed yet, or null. */
  held: string | null;
  request: () => unknown;
  onSaved: () => void;
  onAdd?: () => void;
  addLabel?: string;
  children: ReactNode;
}) {
  const info = infoOf(page);
  useTitle(title ?? info.title);
  const fetcher = useFetcher<Result>();
  const handled = useRef<Result | undefined>(undefined);
  const [result, setResult] = useState<Result | null>(null);
  const busy = fetcher.state !== "idle";
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname);

  const save = useCallback(() => {
    if (busy || !dirty) return;
    if (held !== null) {
      setResult({ ok: false, error: held });
      return;
    }
    fetcher.submit(request() as never, { method: "post", encType: "application/json" });
  }, [busy, dirty, held, fetcher, request]);

  useEffect(() => {
    const done = fetcher.data;
    if (fetcher.state !== "idle" || done === undefined || handled.current === done) return;
    handled.current = done;
    setResult(done);
    if (done.ok) onSaved();
  }, [fetcher.state, fetcher.data, onSaved]);

  const latest = useRef({ save, onAdd });
  latest.current = { save, onAdd };
  useEffect(() => {
    function key(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "s") {
        event.preventDefault();
        latest.current.save();
      } else if (event.altKey && !event.ctrlKey && !event.metaKey && event.key.toLowerCase() === "n" && latest.current.onAdd) {
        event.preventDefault();
        latest.current.onAdd();
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

  return (
    <>
      <ContextBar>
        <nav className="crumbs" aria-label="Where you are">
          <ol>
            <li>Policy</li>
            {parent && (
              <li>
                <Link to={parent.to}>{parent.label}</Link>
              </li>
            )}
            <li>
              <h1 className="bar-title">{title ?? info.title}</h1>
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
          {actions}
          {onAdd && (
            <button type="button" className="button button-quiet" onClick={onAdd} disabled={busy} title={`${addLabel} (Alt+N)`}>
              <Plus aria-hidden="true" />
              Add
            </button>
          )}
          <button type="button" className="button" onClick={save} disabled={busy || !dirty || held !== null} title={held ?? (dirty ? "Save (Ctrl+S)" : "Nothing to save")}>
            <Save aria-hidden="true" />
            Save
          </button>
        </div>
      </ContextBar>
      {children}
      <StatusBar>{result && <Outcome result={result} />}</StatusBar>
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

// Renaming

/** Why Rename is not available while the page has changes that are not saved. */
export const RENAME_WHILE_DIRTY = "Save or undo the changes on this page first. A rename is made at once, and is not part of the next save.";

type Renamed = { name: string; message: string; warnings?: string[] };

/**
 * Rename one saved item at once. Asks for the new name in a `NameDialog`, which stays open with the reason when the
 * name is refused. A failure that left the policy as it was, after the checks passed, goes to `onFailed` for the
 * status bar instead.
 */
export function RenameButton({ page, name, version, from, disabled, onRenamed, onFailed }: {
  page: PageKey;
  name: string;
  version: string;
  /** The address of the page the button is on, for signing in again. */
  from: string;
  /** True while the page has changes that are not saved. */
  disabled: boolean;
  onRenamed: (done: Renamed) => void;
  onFailed: (result: Result) => void;
}) {
  const [asking, setAsking] = useState(false);
  const info = infoOf(page);

  async function submit(typed: string): Promise<string | null> {
    try {
      const done = await api<{ message: string; warnings?: string[]; name?: string }>(`/policy/${page}/rename`, {
        page: from,
        method: "POST",
        body: { version, name, to: typed.trim() },
        signedOut: "refuse",
      });
      setAsking(false);
      onRenamed({ name: done.name ?? typed.trim(), message: done.message, warnings: done.warnings });
      return null;
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      const errors = (error.data.errors as string[] | undefined) ?? [];
      if (error.status >= 500) {
        setAsking(false);
        onFailed({ ok: false, error: error.message, errors });
        return null;
      }
      return [error.message, ...errors].join(" ");
    }
  }

  return (
    <>
      <button type="button" className="button button-quiet" disabled={disabled} title={disabled ? RENAME_WHILE_DIRTY : `Rename this ${info.item}`} onClick={() => setAsking(true)}>
        <TextCursorInput aria-hidden="true" />
        Rename
      </button>
      {asking && <NameDialog title={`Rename ${info.item}`} label="New name" initial={name} onSubmit={submit} onCancel={() => setAsking(false)} />}
    </>
  );
}

// Lists of text, such as a group's addresses

function TextList({ field, singular, add, items, orig, onChange, disabled }: {
  field: string;
  singular: string;
  add: string;
  items: string[];
  orig: string[] | null;
  onChange: (items: string[]) => void;
  disabled?: boolean;
}) {
  return (
    <div className="policy-list">
      <span className="policy-list-label" title={field}>
        {label(field)}
      </span>
      <ul>
        {items.map((text, index) => (
          <li key={index}>
            <input
              type="text"
              aria-label={`${singular} ${index + 1}`}
              value={text}
              disabled={disabled}
              data-changed={orig === null || orig[index]?.trim() !== text.trim() || undefined}
              onChange={(event) => onChange(items.map((each, at) => (at === index ? event.target.value : each)))}
            />
            <button type="button" className="icon-button" aria-label={`Remove ${singular.toLowerCase()} ${index + 1}`} title="Remove" disabled={disabled} onClick={() => onChange(items.filter((_each, at) => at !== index))}>
              <X aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>
      <button type="button" className="button button-quiet policy-add" disabled={disabled} onClick={() => onChange([...items, ""])}>
        <Plus aria-hidden="true" />
        {add}
      </button>
    </div>
  );
}

// Time windows

function ClockBox({ name, value, changed, onChange }: { name: string; value: string; changed: boolean; onChange: (text: string) => void }) {
  return (
    <label className="policy-period-field">
      <span>{name}</span>
      <input
        type="text"
        inputMode="numeric"
        value={value}
        data-changed={changed || undefined}
        onFocus={(event) => event.currentTarget.select()}
        onChange={(event) => onChange(event.target.value)}
        onBlur={() => onChange(normalizeClock(value))}
      />
    </label>
  );
}

function PeriodEditor({ period, was, number, disabled, onChange, onRemove }: {
  period: Period;
  was: Period | null;
  number: number;
  disabled: boolean;
  onChange: (period: Period) => void;
  onRemove: () => void;
}) {
  const trouble = extraProblem(period.extra);
  const weekdays = was ? [...was.weekdays].sort().join() : null;
  return (
    <fieldset className="policy-period" aria-label={`Period ${number}`} disabled={disabled} data-changed={(was === null || !samePeriod(period, was)) || undefined}>
      <div className="policy-period-row">
        <ClockBox name="Start" value={period.start} changed={was === null || normalizeClock(period.start) !== normalizeClock(was.start)} onChange={(start) => onChange({ ...period, start })} />
        <ClockBox name="End" value={period.end} changed={was === null || normalizeClock(period.end) !== normalizeClock(was.end)} onChange={(end) => onChange({ ...period, end })} />
        <label className="policy-period-field">
          <span>Extra Days</span>
          <input
            type="text"
            inputMode="numeric"
            value={period.extra}
            aria-invalid={trouble !== null || undefined}
            data-changed={(was === null || period.extra.trim() !== was.extra.trim()) || undefined}
            onFocus={(event) => event.currentTarget.select()}
            onChange={(event) => onChange({ ...period, extra: event.target.value })}
          />
        </label>
        <div className="policy-weekdays" role="group" aria-label="May start on">
          {WEEKDAYS.map((day, index) => {
            const on = period.weekdays.includes(index);
            return (
              <button
                key={day}
                type="button"
                className="policy-weekday"
                aria-pressed={on}
                aria-label={day}
                title={day}
                data-changed={(was === null ? true : weekdays !== [...period.weekdays].sort().join()) || undefined}
                onClick={() => onChange({ ...period, weekdays: on ? period.weekdays.filter((each) => each !== index) : [...period.weekdays, index].sort() })}
              >
                {day.slice(0, 2)}
              </button>
            );
          })}
        </div>
        <button type="button" className="icon-button" aria-label={`Remove period ${number}`} title="Remove" onClick={onRemove}>
          <X aria-hidden="true" />
        </button>
      </div>
      {trouble && <p className="note note-problem">{trouble}</p>}
    </fieldset>
  );
}

function samePeriod(a: Period, b: Period): boolean {
  return sameFields({ periods: [a] }, { periods: [b] });
}

function PeriodList({ periods, orig, onChange, disabled }: { periods: Period[]; orig: Period[] | null; onChange: (periods: Period[]) => void; disabled: boolean }) {
  const was = (period: Period) => (orig && period.origin !== null ? (orig[period.origin] ?? null) : null);
  return (
    <div className="policy-list">
      <span className="policy-list-label" title="periods">
        Periods
      </span>
      {periods.map((period, index) => (
        <PeriodEditor
          key={index}
          period={period}
          was={was(period)}
          number={index + 1}
          disabled={disabled}
          onChange={(next) => onChange(periods.map((each, at) => (at === index ? next : each)))}
          onRemove={() => onChange(periods.filter((_each, at) => at !== index))}
        />
      ))}
      <button type="button" className="button button-quiet policy-add" disabled={disabled} onClick={() => onChange([...periods, { origin: null, start: "", end: "", extra: "0", weekdays: [] }])}>
        <Plus aria-hidden="true" />
        Add period
      </button>
    </div>
  );
}

// Items

const NOT_SET_TITLE: Record<string, string> = {
  time: "Not set: no time limit applies, so a rule checking time remaining always takes its false branch.",
  bytes: "Not set: no byte limit applies, so a rule checking volume remaining always takes its false branch.",
};

function Setting({ field, title, children }: { field: string; title?: string; children: ReactNode }) {
  return (
    <label className="setting">
      <span title={title ?? field}>{label(field)}</span>
      {children}
    </label>
  );
}

function ItemBody({ page, row, data, disabled, onFields }: { page: ItemPage; row: Row; data: ItemsData; disabled: boolean; onFields: (fields: Fields) => void }) {
  const { fields, orig } = row;
  const set = (change: Fields) => onFields({ ...fields, ...change });
  if (page === "client-groups") {
    return <TextList field="addresses" singular="Address" add="Add address" items={fields.addresses ?? []} orig={orig?.addresses ?? null} disabled={disabled} onChange={(addresses) => set({ addresses })} />;
  }
  if (page === "site-groups") {
    return (
      <>
        <div className="settings">
          <Setting field="priority">
            <input type="text" inputMode="numeric" value={fields.priority ?? ""} disabled={disabled} data-changed={orig === null || (fields.priority ?? "").trim() !== (orig.priority ?? "").trim() || undefined} onChange={(event) => set({ priority: event.target.value })} />
          </Setting>
        </div>
        <TextList field="patterns" singular="Pattern" add="Add pattern" items={fields.patterns ?? []} orig={orig?.patterns ?? null} disabled={disabled} onChange={(patterns) => set({ patterns })} />
      </>
    );
  }
  if (page === "time-windows") {
    return <PeriodList periods={fields.periods ?? []} orig={orig?.periods ?? null} disabled={disabled} onChange={(periods) => set({ periods })} />;
  }
  const text = (field: "time" | "bytes" | "time_grace" | "volume_grace") => {
    const grace = field === "time_grace" || field === "volume_grace";
    const blank = (fields[field] ?? "").trim() === "";
    return (
      <Setting field={field}>
        <input
          type="text"
          value={fields[field] ?? ""}
          disabled={disabled}
          placeholder={grace ? (data.defaults?.[field] ?? "") : "Not set"}
          title={!grace && blank ? NOT_SET_TITLE[field] : undefined}
          data-changed={orig === null || (fields[field] ?? "").trim() !== (orig[field] ?? "").trim() || undefined}
          onChange={(event) => set({ [field]: event.target.value })}
        />
      </Setting>
    );
  };
  return (
    <div className="settings">
      {text("time")}
      {text("bytes")}
      {text("time_grace")}
      {text("volume_grace")}
      <Setting field="ruleset">
        <select value={fields.ruleset ?? ""} disabled={disabled} data-changed={orig === null || (fields.ruleset ?? "") !== (orig.ruleset ?? "") || undefined} onChange={(event) => set({ ruleset: event.target.value })}>
          {(fields.ruleset ?? "") === "" && <option value="">Choose…</option>}
          {(data.rule_sets ?? []).map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </Setting>
    </div>
  );
}

const IMPLICIT: Partial<Record<ItemPage, string>> = {
  "client-groups": "holds every address that no other group holds.",
  "site-groups": "holds every site that no other group holds.",
};

export function ItemsPage({ page }: { page: ItemPage }) {
  const data = useLoaderData() as ItemsData;
  const ids = useRef(0);
  const nextId = useCallback(() => ++ids.current, []);
  const [rows, setRows] = useState<Row[]>(() => rowsFrom(page, data, nextId));
  const [pending, setPending] = useState(false);
  const [focus, setFocus] = useState<number | null>(null);
  const [notice, setNotice] = useState<Result | null>(null);
  const revalidator = useRevalidator();
  const shown = useRef(data);
  const info = infoOf(page);

  useEffect(() => {
    if (shown.current === data) return;
    shown.current = data;
    setRows(rowsFrom(page, data, nextId));
    setPending(false);
  }, [data, page, nextId]);

  useEffect(() => {
    if (focus === null) return;
    document.querySelector<HTMLInputElement>(`[data-name-box="${focus}"]`)?.focus();
    setFocus(null);
  }, [focus]);

  const change = (id: number, update: (row: Row) => Row) => setRows((current) => current.map((row) => (row.id === id ? update(row) : row)));
  const add = useCallback(() => {
    const id = nextId();
    setRows((current) => [...current, { id, name: "", isNew: true, marked: false, file: null, fields: blankFields(page), orig: null }]);
    setFocus(id);
  }, [nextId, page]);
  const dirty = !pending && anyChanged(rows);
  const held = pageProblem(page, rows);
  const request = useCallback(() => saveRequest(rows, data.version), [rows, data.version]);
  const onSaved = useCallback(() => setPending(true), []);
  const implicit = IMPLICIT[page];

  return (
    <PolicyFrame page={page} dirty={dirty} held={held} request={request} onSaved={onSaved} onAdd={add} addLabel={`Add a ${info.item}`}>
      <div className="policy-items">
        {rows.map((row, index) => {
          const trouble = rowProblem(page, row);
          return (
            <section key={row.id} className="policy-item" role="region" aria-label={row.name || `New ${info.item} ${index + 1}`} data-changed={(!row.marked && rowChanged(row)) || undefined} data-marked={row.marked || undefined} data-new={row.isNew || undefined}>
              <div className="policy-item-head">
                <label className="policy-name">
                  <span title="name">{label("name")}</span>
                  <input
                    type="text"
                    data-name-box={row.id}
                    value={row.name}
                    readOnly={!row.isNew}
                    disabled={row.marked}
                    aria-invalid={(row.name.trim() === "" && row.isNew && trouble !== null) || undefined}
                    data-changed={row.isNew || undefined}
                    onChange={(event) => change(row.id, (each) => ({ ...each, name: event.target.value }))}
                  />
                </label>
                {row.file && (
                  <span className="policy-file" title="The file that holds this item">
                    {row.file}
                  </span>
                )}
                {row.marked && <span className="policy-marked">Will be deleted when saved</span>}
                {!row.isNew && !row.marked && (
                  <RenameButton
                    page={page}
                    name={row.name}
                    version={data.version}
                    from={`/parent${policyPath(page)}`}
                    disabled={dirty || pending}
                    onRenamed={(done) => {
                      setNotice({ ok: true, message: done.message, warnings: done.warnings });
                      revalidator.revalidate();
                    }}
                    onFailed={setNotice}
                  />
                )}
                {row.marked ? (
                  <button type="button" className="button button-quiet" onClick={() => change(row.id, (each) => ({ ...each, marked: false }))}>
                    <Undo2 aria-hidden="true" />
                    Undo
                  </button>
                ) : (
                  <button
                    type="button"
                    className="button button-quiet"
                    onClick={() => (row.isNew ? setRows((current) => current.filter((each) => each.id !== row.id)) : change(row.id, (each) => ({ ...each, marked: true })))}
                  >
                    <Trash2 aria-hidden="true" />
                    Delete
                  </button>
                )}
              </div>
              <ItemBody page={page} row={row} data={data} disabled={row.marked} onFields={(fields) => change(row.id, (each) => ({ ...each, fields }))} />
              {trouble && <p className="note note-problem">{trouble}</p>}
            </section>
          );
        })}
        {implicit && (
          <section className="policy-item policy-implicit" role="region" aria-label="default">
            <div className="policy-item-head">
              <label className="policy-name">
                <span title="name">{label("name")}</span>
                <input type="text" value="default" readOnly />
              </label>
            </div>
            <p>
              <code>default</code> {implicit}
            </p>
          </section>
        )}
      </div>
      <StatusBar>{notice && <Outcome result={notice} />}</StatusBar>
    </PolicyFrame>
  );
}

// Household

const SWITCH_TEXT: Record<(typeof SWITCHES)[number], string> = {
  localhost: "Localhost",
  plain_host_names: "Plain host names",
  policy_server: "Policy server",
  local_subnets: "Local subnets",
  local_domains: "Local domains",
};

export function HouseholdPage() {
  const data = useLoaderData() as HouseholdData;
  const [edits, setEdits] = useState<HouseholdEdits>({ fields: data.fields, proxy: data.proxy });
  const [pending, setPending] = useState(false);
  const shown = useRef(data);

  useEffect(() => {
    if (shown.current === data) return;
    shown.current = data;
    setEdits({ fields: data.fields, proxy: data.proxy });
    setPending(false);
  }, [data]);

  const dirty = !pending && householdChanged(data, edits);
  const held = householdProblem(edits);
  const request = useCallback(() => householdRequest(data, edits, data.version), [data, edits]);
  const onSaved = useCallback(() => setPending(true), []);
  const field = (key: string) => edits.fields[key] ?? "";
  const set = (key: string, text: string) => setEdits((current) => ({ ...current, fields: { ...current.fields, [key]: text } }));
  const proxy = edits.proxy;

  return (
    <PolicyFrame page="household" dirty={dirty} held={held} request={request} onSaved={onSaved}>
      <div className="policy-items">
        <section className="policy-item" role="region" aria-label="Household settings">
          <div className="settings">
            <Setting field="entry">
              <select value={field("entry")} data-changed={field("entry") !== (data.fields.entry ?? "") || undefined} onChange={(event) => set("entry", event.target.value)}>
                {field("entry") === "" && <option value="">Choose…</option>}
                {data.rule_sets.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </Setting>
            {HOUSEHOLD_TEXT.map((key) => (
              <Setting key={key} field={key}>
                <input type="text" value={field(key)} placeholder={data.defaults[key] ?? ""} data-changed={field(key).trim() !== (data.fields[key] ?? "").trim() || undefined} onChange={(event) => set(key, event.target.value)} />
              </Setting>
            ))}
          </div>
        </section>
        <section className="policy-item" role="region" aria-label="Proxy Configuration">
          <h2 className="policy-heading" title="proxy_configuration">
            Proxy Configuration
          </h2>
          <p className="policy-hint">Hosts the proxy auto-configuration file sends direct, not to the proxy. A switch that is on is not written.</p>
          <div className="policy-switches">
            {SWITCHES.map((name) => (
              <label key={name} className="setting-flag" data-changed={proxy[name] !== data.proxy[name] || undefined}>
                <input type="checkbox" checked={proxy[name]} onChange={(event) => setEdits((current) => ({ ...current, proxy: { ...current.proxy, [name]: event.target.checked } }))} />
                <span title={`direct.${name}`}>{SWITCH_TEXT[name]}</span>
              </label>
            ))}
          </div>
          <TextList
            field="extra"
            singular="Extra"
            add="Add extra"
            items={proxy.extra}
            orig={data.proxy.extra}
            onChange={(extra) => setEdits((current) => ({ ...current, proxy: { ...current.proxy, extra } }))}
          />
        </section>
      </div>
    </PolicyFrame>
  );
}
