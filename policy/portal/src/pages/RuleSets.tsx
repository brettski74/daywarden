import { ArrowDownToLine, GripVertical, Plus, SquarePlus, Trash2, Workflow } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent } from "react";
import { Link, useLoaderData, useLocation, useNavigate, useParams } from "react-router";
import { ApiError, api } from "../api";
import { Dialog } from "../components/Dialog";
import { Fold } from "../components/Fold";
import { MultiSelect } from "../components/MultiSelect";
import { NameDialog } from "../components/NameDialog";
import {
  ACTIONS,
  CONDITIONS,
  blankRule,
  liveCreated,
  moved,
  movedTo,
  nameProblem,
  ruleFrom,
  ruleSetChanged,
  ruleSetPath,
  ruleSetRequest,
  rulesFrom,
  sameRule,
  takesNames,
  withCondition,
  withKind,
  withTarget,
  RULE_SETS,
  type Action,
  type Created,
  type Rule,
  type RuleSetData,
  type RuleSetsData,
  type User,
} from "../ruleSets";
import { ContextBar, StatusBar, useTitle } from "../slots";
import { PolicyFrame } from "./Policy";
import { Outcome } from "./Task";

export const NEW_RULE_SET = "New Rule Set";
export const MAKE_NAMED = "Make Named Rule Set";
const INLINE = "\u0001inline";
const NONE = "";

/** Where a user of a rule set is shown: the household, the quota, or the other rule set's page. */
export function userPath(user: User): string {
  if (user.kind === "entry") return "/policy/household";
  if (user.kind === "quota") return "/policy/quotas";
  return ruleSetPath(user.name);
}

function Users({ users }: { users: User[] }) {
  if (users.length === 0) return <span className="note">Nothing uses it.</span>;
  return (
    <ul className="rule-users">
      {users.map((user) => (
        <li key={user.text}>
          <Link to={userPath(user)}>{user.text}</Link>
        </li>
      ))}
    </ul>
  );
}

// The list

/** Every rule set, with how many rules it has and what uses it. */
export function RuleSetsPage() {
  const data = useLoaderData() as RuleSetsData;
  const navigate = useNavigate();
  const [naming, setNaming] = useState(false);
  useTitle("Rule Sets");

  async function make(name: string): Promise<string | null> {
    try {
      await api(`/policy/rule-sets`, {
        page: `/parent${RULE_SETS}`,
        method: "POST",
        body: { version: data.version, items: [{ name, new: true, fields: { rules: [] } }], deleted: [] },
        signedOut: "refuse",
      });
      setNaming(false);
      navigate(ruleSetPath(name));
      return null;
    } catch (error) {
      if (error instanceof ApiError) return [error.message, ...((error.data.errors as string[] | undefined) ?? [])].join(" ");
      throw error;
    }
  }

  return (
    <>
      <ContextBar>
        <nav className="crumbs" aria-label="Where you are">
          <ol>
            <li>Policy</li>
            <li>
              <h1 className="bar-title">Rule Sets</h1>
            </li>
          </ol>
        </nav>
        <div className="bar-end bar-actions">
          <button type="button" className="button" onClick={() => setNaming(true)}>
            <SquarePlus aria-hidden="true" />
            {NEW_RULE_SET}
          </button>
        </div>
      </ContextBar>
      <table className="records rule-sets-table">
        <thead>
          <tr>
            <th scope="col">Name</th>
            <th scope="col">Rules</th>
            <th scope="col">Used by</th>
          </tr>
        </thead>
        <tbody>
          {data.items.map((item) => (
            <tr key={item.name}>
              <td>
                <Link to={ruleSetPath(item.name)}>{item.name}</Link>
              </td>
              <td className="pools-number">{item.rules.length}</td>
              <td>
                <Users users={item.users} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <StatusBar>
        <span>
          {data.items.length} rule set{data.items.length === 1 ? "" : "s"}.
        </span>
      </StatusBar>
      {naming && <NameDialog title={NEW_RULE_SET} label="Name" onSubmit={make} onCancel={() => setNaming(false)} />}
    </>
  );
}

// One rule set

type Editing = {
  data: RuleSetsData;
  /** Names a pull-down offers: every rule set, and each one made on this page. */
  names: string[];
  /** Whether a rule set's page exists, so a link to it opens something. */
  exists: (name: string) => boolean;
  /** Ask for a name for an inline list, then make it a rule set with that name and call apply. */
  askName: (rules: Rule[], apply: (name: string) => void) => void;
};

const Editor = createContext<Editing | null>(null);

export function RuleSetPage() {
  const data = useLoaderData() as RuleSetsData;
  const { name = "" } = useParams();
  const item = data.items.find((each) => each.name === name);
  if (!item) return <Missing name={name} />;
  return <RuleSetEditor key={name} data={data} item={item} />;
}

function Missing({ name }: { name: string }) {
  useTitle("Not found");
  return (
    <>
      <ContextBar>
        <nav className="crumbs" aria-label="Where you are">
          <ol>
            <li>Policy</li>
            <li>
              <Link to={RULE_SETS}>Rule Sets</Link>
            </li>
            <li>
              <h1 className="bar-title">Not found</h1>
            </li>
          </ol>
        </nav>
      </ContextBar>
      <p>There is no rule set named {name}.</p>
    </>
  );
}

type Reply = { ok: boolean; message?: string; error?: string; errors?: string[] };

function RuleSetEditor({ data, item }: { data: RuleSetsData; item: RuleSetData }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [orig, setOrig] = useState(() => rulesFrom(item.rules));
  const [rules, setRules] = useState(orig);
  const [created, setCreated] = useState<Created[]>([]);
  const [pending, setPending] = useState(false);
  const [naming, setNaming] = useState<{ rules: Rule[]; apply: (name: string) => void } | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [gone, setGone] = useState(false);
  const [refusal, setRefusal] = useState<Reply | null>(null);
  const shown = useRef(data);
  const [focus, setFocus] = useState<number | null>(null);

  useEffect(() => {
    if (shown.current === data) return;
    shown.current = data;
    const fresh = rulesFrom(item.rules);
    setOrig(fresh);
    setRules(fresh);
    setCreated([]);
    setPending(false);
  }, [data, item]);

  useEffect(() => {
    if (focus === null) return;
    document.querySelector<HTMLElement>(`[data-rule="${focus}"] .rule-handle`)?.focus();
    setFocus(null);
  }, [focus]);

  useEffect(() => {
    if (gone) navigate(RULE_SETS);
  }, [gone, navigate]);

  const live = liveCreated(rules, created);
  const dirty = !pending && !gone && ruleSetChanged(rules, orig, created);
  const request = useCallback(() => ruleSetRequest(item.name, rules, orig, created, data.version), [item.name, rules, orig, created, data.version]);
  const onSaved = useCallback(() => setPending(true), []);
  const add = useCallback(() => setRules((current) => [...current, blankRule()]), []);

  const context = useMemo<Editing>(() => {
    const existing = data.items.map((each) => each.name);
    return {
      data,
      names: [...existing, ...live.map((made) => made.name)],
      exists: (each) => existing.includes(each),
      askName: (list, apply) => setNaming({ rules: list, apply }),
    };
  }, [data, live]);

  function taken(name: string): string | null {
    return nameProblem(name, [...data.items.map((each) => each.name), ...created.map((made) => made.name)]);
  }

  async function remove() {
    setDeleting(false);
    try {
      const done = await api<{ message: string }>(`/policy/rule-sets`, {
        page: `/parent${location.pathname}`,
        method: "POST",
        body: { version: data.version, items: [], deleted: [item.name] },
      });
      setRefusal({ ok: true, ...done });
      setGone(true);
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      setRefusal({ ok: false, error: error.message, errors: error.data.errors as string[] | undefined });
    }
  }

  return (
    <Editor.Provider value={context}>
      <PolicyFrame
        page="rule-sets"
        title={item.name}
        parent={{ to: RULE_SETS, label: "Rule Sets" }}
        dirty={dirty}
        held={null}
        request={request}
        onSaved={onSaved}
        onAdd={add}
        addLabel="Add a rule"
        actions={
          <button type="button" className="button button-quiet" onClick={() => setDeleting(true)}>
            <Trash2 aria-hidden="true" />
            Delete Rule Set
          </button>
        }
      >
        <div className="policy-items">
          <section className="policy-item" role="region" aria-label="Used by" data-used-by>
            <h2 className="policy-heading">Used by</h2>
            <Users users={item.users} />
            {item.file && (
              <p className="policy-file" title="The file that holds this item">
                {item.file}
              </p>
            )}
          </section>
          <section className="policy-item" role="region" aria-label="Rules">
            <h2 className="policy-heading">Rules</h2>
            <RuleList rules={rules} onChange={setRules} path="" onFocus={setFocus} />
          </section>
        </div>
      </PolicyFrame>
      <StatusBar>{refusal && <Outcome result={refusal} />}</StatusBar>
      {deleting && (
        <Dialog
          title="Delete this rule set?"
          message={`Delete the rule set ${item.name}? It is deleted at once, and cannot be undone.`}
          confirm="Delete"
          cancel="Cancel"
          onConfirm={remove}
          onCancel={() => setDeleting(false)}
        />
      )}
      {naming && (
        <NameDialog
          title={MAKE_NAMED}
          label="Name"
          onSubmit={async (name) => {
            const problem = taken(name);
            if (problem === null) {
              setCreated((current) => [...current, { name, rules: naming.rules }]);
              naming.apply(name);
              setNaming(null);
            }
            return problem;
          }}
          onCancel={() => setNaming(null)}
        />
      )}
    </Editor.Provider>
  );
}

// The rules

function pathOf(path: string, number: number): string {
  return path === "" ? `Rule ${number}` : `${path} rule ${number}`;
}

function RuleList({ rules, onChange, path, onFocus }: { rules: Rule[]; onChange: (rules: Rule[]) => void; path: string; onFocus?: (id: number) => void }) {
  const dragging = useRef<number | null>(null);
  const [over, setOver] = useState<number | null>(null);
  const insert = (index: number) => onChange([...rules.slice(0, index), blankRule(), ...rules.slice(index)]);

  function drop(event: DragEvent, to: number) {
    if (dragging.current === null) return;
    event.preventDefault();
    event.stopPropagation();
    onChange(movedTo(rules, dragging.current, to));
    dragging.current = null;
    setOver(null);
  }

  return (
    <div className="rule-list">
      <ol>
        {rules.map((rule, index) => (
          <li
            key={rule.id}
            data-rule={rule.id}
            data-over={over === index || undefined}
            onDragOver={(event) => {
              if (dragging.current === null) return;
              event.preventDefault();
              event.stopPropagation();
              setOver(index);
            }}
            onDrop={(event) => drop(event, index)}
          >
            <RuleItem
              rule={rule}
              number={index + 1}
              path={pathOf(path, index + 1)}
              onChange={(next) => onChange(rules.map((each, at) => (at === index ? next : each)))}
              onInsertAbove={() => insert(index)}
              onDelete={() => onChange(rules.filter((_each, at) => at !== index))}
              onMove={(by) => {
                onChange(moved(rules, index, by));
                onFocus?.(rule.id);
              }}
              onDragStart={() => {
                dragging.current = index;
              }}
              onDragEnd={() => {
                dragging.current = null;
                setOver(null);
              }}
              onFocus={onFocus}
            />
          </li>
        ))}
      </ol>
      <button type="button" className="button button-quiet policy-add" onClick={() => onChange([...rules, blankRule()])} aria-label={`Add rule${path ? ` to ${path}` : ""}`}>
        <Plus aria-hidden="true" />
        Add rule
      </button>
    </div>
  );
}

function RuleItem({ rule, number, path, onChange, onInsertAbove, onDelete, onMove, onDragStart, onDragEnd, onFocus }: {
  rule: Rule;
  number: number;
  path: string;
  onChange: (rule: Rule) => void;
  onInsertAbove: () => void;
  onDelete: () => void;
  onMove: (by: -1 | 1) => void;
  onDragStart: () => void;
  onDragEnd: () => void;
  onFocus?: (id: number) => void;
}) {
  const editing = useContext(Editor) as Editing;
  const changed = rule.raw === null || !sameRule(rule, ruleFrom(rule.raw));
  const choices = editing.data.choices;

  function key(event: KeyboardEvent) {
    if (!event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    // The innermost rule holding the focus is the one that moves.
    event.preventDefault();
    event.stopPropagation();
    onMove(event.key === "ArrowUp" ? -1 : 1);
  }

  function start(event: DragEvent) {
    event.stopPropagation();
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", path);
    const box = (event.currentTarget as HTMLElement).closest("li");
    if (box && event.dataTransfer.setDragImage) event.dataTransfer.setDragImage(box, 0, 0);
    onDragStart();
  }

  return (
    <fieldset className="rule" aria-label={path} data-changed={changed || undefined} onKeyDown={key}>
      <div className="rule-head">
        <button
          type="button"
          className="icon-button rule-handle"
          draggable
          aria-label={`Move ${path}`}
          title="Drag to move this rule. Alt+Up and Alt+Down move the rule with the focus."
          onDragStart={start}
          onDragEnd={onDragEnd}
        >
          <GripVertical aria-hidden="true" />
        </button>
        <span className="rule-number">Rule {number}</span>
        <label className="setting-inline">
          <span title="condition">Condition</span>
          <select value={rule.condition} onChange={(event) => onChange(withCondition(rule, event.target.value as Rule["condition"]))}>
            {CONDITIONS.map((condition) => (
              <option key={condition} value={condition}>
                {condition}
              </option>
            ))}
          </select>
        </label>
        {takesNames(rule.condition) && (
          <MultiSelect
            label={rule.condition === "time_window" ? "Windows" : rule.condition === "site_group" ? "Site Groups" : "Client Groups"}
            options={choices[rule.condition as "time_window" | "site_group" | "client_group"]}
            selected={rule.names}
            empty="None chosen"
            changed={changed}
            onToggle={(option) => onChange({ ...rule, names: rule.names.includes(option) ? rule.names.filter((each) => each !== option) : [...rule.names, option] })}
          />
        )}
        {rule.condition === "tasks_required" && (
          <label className="setting-inline">
            <span title="required">Required</span>
            <input type="text" inputMode="numeric" value={rule.required} onChange={(event) => onChange({ ...rule, required: event.target.value })} />
          </label>
        )}
        {(rule.condition === "time_remaining" || rule.condition === "volume_remaining") && (
          <label className="setting-inline">
            <span title="quota">Quota</span>
            <select value={rule.quota} onChange={(event) => onChange({ ...rule, quota: event.target.value })}>
              {rule.quota === "" && <option value="">Choose…</option>}
              {choices.quota.map((quota) => (
                <option key={quota} value={quota}>
                  {quota}
                </option>
              ))}
            </select>
          </label>
        )}
        <span className="rule-buttons">
          <button type="button" className="button button-quiet" onClick={onInsertAbove} aria-label={`Insert above ${path}`}>
            <ArrowDownToLine aria-hidden="true" />
            Insert above
          </button>
          <button type="button" className="button button-quiet" onClick={onDelete} aria-label={`Delete ${path}`}>
            <Trash2 aria-hidden="true" />
            Delete
          </button>
        </span>
      </div>
      <ActionEditor label="True action" field="when_true" action={rule.when_true} path={path} onChange={(when_true) => onChange({ ...rule, when_true })} onFocus={onFocus} />
      {rule.condition !== "always" && (
        <ActionEditor label="False action" field="when_false" action={rule.when_false} path={path} onChange={(when_false) => onChange({ ...rule, when_false })} onFocus={onFocus} />
      )}
    </fieldset>
  );
}

function ActionEditor({ label, field, action, path, onChange, onFocus }: {
  label: string;
  field: "when_true" | "when_false";
  action: Action;
  path: string;
  onChange: (action: Action) => void;
  onFocus?: (id: number) => void;
}) {
  const editing = useContext(Editor) as Editing;
  const target = action.inline ? INLINE : action.ruleset;
  const named = action.kind === "evaluate" && !action.inline && action.ruleset !== "";

  return (
    <div className="rule-action" role="group" aria-label={`${path} ${field}`}>
      <div className="rule-action-row">
        <label className="setting-inline">
          <span title={field}>{label}</span>
          <select value={action.kind} onChange={(event) => onChange(withKind(action, event.target.value as Action["kind"]))}>
            {ACTIONS.map((kind) => (
              <option key={kind} value={kind}>
                {kind}
              </option>
            ))}
          </select>
        </label>
        {action.kind === "deny" && (
          <label className="setting-inline">
            <span title="message">Message</span>
            <input type="text" value={action.message} onChange={(event) => onChange({ ...action, message: event.target.value })} />
          </label>
        )}
        {action.kind === "redirect" && (
          <label className="setting-inline">
            <span title="location">Location</span>
            <input type="text" value={action.location} placeholder="revision_task or an http or https address" onChange={(event) => onChange({ ...action, location: event.target.value })} />
          </label>
        )}
        {action.kind === "evaluate" && (
          <>
            <label className="setting-inline">
              <span title="ruleset">Rule Set</span>
              <select value={target} onChange={(event) => onChange(withTarget(action, event.target.value === INLINE ? null : event.target.value))}>
                {target === NONE && <option value="">Choose…</option>}
                <option value={INLINE}>Inline rules</option>
                {editing.names.map((each) => (
                  <option key={each} value={each}>
                    {each}
                  </option>
                ))}
              </select>
            </label>
            {named &&
              (editing.exists(action.ruleset) ? (
                <Link to={ruleSetPath(action.ruleset)} className="rule-link">
                  <Workflow aria-hidden="true" />
                  Open {action.ruleset}
                </Link>
              ) : (
                <span className="note">{action.ruleset} is made when this page is saved.</span>
              ))}
          </>
        )}
      </div>
      {action.kind === "evaluate" && action.inline && (
        <div className="rule-inline">
          <Fold title={`Inline rules (${action.rules.length})`} open level={4}>
            <RuleList rules={action.rules} onChange={(rules) => onChange({ ...action, rules })} path={`${path} ${field}`} onFocus={onFocus} />
          </Fold>
          <button
            type="button"
            className="button button-quiet"
            onClick={() => editing.askName(action.rules, (name) => onChange({ ...withTarget(action, name), rules: [] }))}
            aria-label={`${MAKE_NAMED} from ${path} ${field}`}
          >
            <SquarePlus aria-hidden="true" />
            {MAKE_NAMED}
          </button>
        </div>
      )}
    </div>
  );
}
