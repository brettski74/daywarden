/** The rule set pages: the rules a page edits, how they read from and write to the policy file, and what a save sends. */

export const RULE_SETS = "/policy/rule-sets";

export function ruleSetPath(name: string): string {
  return `${RULE_SETS}/${encodeURIComponent(name)}`;
}

export const CONDITIONS = ["time_window", "site_group", "client_group", "tasks_required", "time_remaining", "volume_remaining", "always"] as const;
export type Condition = (typeof CONDITIONS)[number];

export const ACTIONS = ["continue", "allow", "deny", "redirect", "evaluate"] as const;
export type Kind = (typeof ACTIONS)[number];

export const REVISION_TASK = "revision_task";

export type Action = {
  kind: Kind;
  message: string;
  location: string;
  /** The rule set an evaluate names, when it is not inline. */
  ruleset: string;
  inline: boolean;
  rules: Rule[];
};

export type Rule = {
  id: number;
  condition: Condition;
  /** The chosen windows, or the chosen site groups or client groups. */
  names: string[];
  required: string;
  quota: string;
  when_true: Action;
  when_false: Action;
  /** The rule as the file writes it, or null for one made on the page. */
  raw: Written | null;
};

/** A rule or action as the policy file writes it. */
export type Written = Record<string, unknown>;

export type User = { kind: "entry" | "quota" | "rule_set"; name: string; text: string };

export type RuleSetData = { name: string; file: string | null; rules: Written[]; users: User[] };

export type RuleSetsData = {
  version: string;
  file: string;
  items: RuleSetData[];
  choices: Record<"time_window" | "site_group" | "client_group" | "quota", string[]>;
};

/** A rule set made on the page from an inline list, which the next save creates with the one that holds it. */
export type Created = { name: string; rules: Rule[] };

let counter = 0;

export function nextRuleId(): number {
  return ++counter;
}

export function blankAction(kind: Kind = "continue"): Action {
  return { kind, message: "", location: kind === "redirect" ? REVISION_TASK : "", ruleset: "", inline: false, rules: [] };
}

export function blankRule(): Rule {
  return { id: nextRuleId(), condition: "always", names: [], required: "", quota: "", when_true: blankAction(), when_false: blankAction(), raw: null };
}

/** What a condition takes besides its actions. */
export function takesNames(condition: Condition): boolean {
  return condition === "time_window" || condition === "site_group" || condition === "client_group";
}

/** Change a rule's condition, clearing the parameters the new condition does not take. */
export function withCondition(rule: Rule, condition: Condition): Rule {
  const sameNames = takesNames(condition) && rule.condition === condition;
  const quota = (condition === "time_remaining" || condition === "volume_remaining") && (rule.condition === "time_remaining" || rule.condition === "volume_remaining");
  return {
    ...rule,
    condition,
    names: sameNames ? rule.names : [],
    required: condition === "tasks_required" ? rule.required : "",
    quota: quota ? rule.quota : "",
    when_false: condition === "always" ? blankAction() : rule.when_false,
  };
}

/** Change an action's kind, clearing what the new kind does not take. */
export function withKind(action: Action, kind: Kind): Action {
  if (kind === action.kind) return action;
  return { ...blankAction(kind), rules: kind === "evaluate" ? action.rules : [] };
}

/** Turn an evaluate's pull-down choice into the action: a rule set's name, or null for inline rules, which starts with one empty rule. */
export function withTarget(action: Action, target: string | null): Action {
  if (target === null) return { ...action, inline: true, ruleset: "", rules: action.rules.length ? action.rules : [blankRule()] };
  return { ...action, inline: false, ruleset: target, rules: [] };
}

// Reading and writing

function text(value: unknown): string {
  return value === undefined || value === null ? "" : String(value);
}

function namesOf(raw: Written, singular: string, plural: string): string[] {
  if (Array.isArray(raw[plural])) return (raw[plural] as unknown[]).map(text);
  return raw[singular] === undefined ? [] : [text(raw[singular])];
}

function actionFrom(raw: unknown): Action {
  if (typeof raw !== "object" || raw === null) return blankAction();
  const written = raw as Written;
  const kind = ACTIONS.includes(written.action as Kind) ? (written.action as Kind) : "continue";
  const inline = kind === "evaluate" && Array.isArray(written.rules);
  return {
    kind,
    message: text(written.message),
    location: text(written.location),
    ruleset: kind === "evaluate" && !inline ? text(written.ruleset) : "",
    inline,
    rules: inline ? (written.rules as Written[]).map(ruleFrom) : [],
  };
}

export function ruleFrom(raw: Written): Rule {
  const condition = CONDITIONS.includes(raw.condition as Condition) ? (raw.condition as Condition) : "always";
  const names = condition === "time_window" ? namesOf(raw, "window", "windows") : condition === "site_group" || condition === "client_group" ? namesOf(raw, "group", "groups") : [];
  return {
    id: nextRuleId(),
    condition,
    names,
    required: text(raw.required),
    quota: text(raw.quota),
    when_true: actionFrom(raw.when_true),
    when_false: actionFrom(raw.when_false),
    raw,
  };
}

export function rulesFrom(raw: Written[]): Rule[] {
  return raw.map(ruleFrom);
}

function actionOut(action: Action): Written | null {
  switch (action.kind) {
    case "continue":
      return null;
    case "allow":
      return { action: "allow" };
    case "deny":
      return { action: "deny", message: action.message.trim() };
    case "redirect":
      return { action: "redirect", location: action.location.trim() };
    default:
      return action.inline ? { action: "evaluate", rules: rulesOut(action.rules) } : { action: "evaluate", ruleset: action.ruleset };
  }
}

/** The rule as it is written: the file's own text when it is not changed, otherwise one window or group as `window` or `group` and several as `windows` or `groups`. */
export function ruleOut(rule: Rule): Written {
  if (rule.raw !== null && sameRule(rule, ruleFrom(rule.raw))) return rule.raw;
  const found: Written = { condition: rule.condition };
  if (takesNames(rule.condition)) {
    const [singular, plural] = rule.condition === "time_window" ? ["window", "windows"] : ["group", "groups"];
    if (rule.names.length === 1) found[singular] = rule.names[0];
    else found[plural] = [...rule.names];
  } else if (rule.condition === "tasks_required") {
    const required = rule.required.trim();
    if (required !== "") found.required = /^\d+$/.test(required) ? Number(required) : required;
  } else if (rule.condition !== "always" && rule.quota !== "") {
    found.quota = rule.quota;
  }
  const whenTrue = actionOut(rule.when_true);
  const whenFalse = rule.condition === "always" ? null : actionOut(rule.when_false);
  if (whenTrue) found.when_true = whenTrue;
  if (whenFalse) found.when_false = whenFalse;
  return found;
}

export function rulesOut(rules: Rule[]): Written[] {
  return rules.map(ruleOut);
}

// Changes

function actionLike(action: Action): unknown {
  if (action.kind === "evaluate") return action.inline ? { kind: "evaluate", rules: action.rules.map(ruleLike) } : { kind: "evaluate", ruleset: action.ruleset };
  if (action.kind === "deny") return { kind: "deny", message: action.message.trim() };
  if (action.kind === "redirect") return { kind: "redirect", location: action.location.trim() };
  return { kind: action.kind };
}

/** A rule with nothing that only says where it came from, so two rules that mean the same thing compare equal. */
function ruleLike(rule: Rule): unknown {
  return {
    condition: rule.condition,
    names: takesNames(rule.condition) ? [...rule.names].sort() : [],
    required: rule.condition === "tasks_required" ? rule.required.trim() : "",
    quota: rule.condition === "time_remaining" || rule.condition === "volume_remaining" ? rule.quota : "",
    when_true: actionLike(rule.when_true),
    when_false: rule.condition === "always" ? { kind: "continue" } : actionLike(rule.when_false),
  };
}

export function sameRule(a: Rule, b: Rule): boolean {
  return JSON.stringify(ruleLike(a)) === JSON.stringify(ruleLike(b));
}

export function sameRules(a: Rule[], b: Rule[]): boolean {
  return JSON.stringify(a.map(ruleLike)) === JSON.stringify(b.map(ruleLike));
}

/** The names of the rule sets that rules evaluate, inside inline lists too. */
export function evaluated(rules: Rule[]): string[] {
  const found: string[] = [];
  for (const rule of rules) {
    for (const action of [rule.when_true, rule.when_false]) {
      if (action.kind !== "evaluate") continue;
      if (action.inline) found.push(...evaluated(action.rules));
      else if (action.ruleset !== "") found.push(action.ruleset);
    }
  }
  return found;
}

/** The rule sets made on the page that something still evaluates. The others were given up when their action changed. */
export function liveCreated(rules: Rule[], created: Created[]): Created[] {
  const live = new Set<string>();
  let queue = evaluated(rules);
  while (queue.length) {
    const next: string[] = [];
    for (const name of queue) {
      if (live.has(name)) continue;
      const made = created.find((each) => each.name === name);
      if (!made) continue;
      live.add(name);
      next.push(...evaluated(made.rules));
    }
    queue = next;
  }
  return created.filter((each) => live.has(each.name));
}

export function ruleSetChanged(rules: Rule[], orig: Rule[], created: Created[]): boolean {
  return !sameRules(rules, orig) || liveCreated(rules, created).length > 0;
}

/** What a save sends: the rule set when its rules changed, then each rule set made on the page. */
export function ruleSetRequest(name: string, rules: Rule[], orig: Rule[], created: Created[], version: string) {
  const items: unknown[] = [];
  if (!sameRules(rules, orig)) items.push({ name, new: false, fields: { rules: rulesOut(rules) } });
  for (const made of liveCreated(rules, created)) items.push({ name: made.name, new: true, fields: { rules: rulesOut(made.rules) } });
  return { version, items, deleted: [] as string[] };
}

/** Why a name cannot be given to a rule set made on the page, or null. The service checks the rest at the save. */
export function nameProblem(name: string, taken: string[]): string | null {
  if (name.trim() === "") return "Give the rule set a name.";
  if (name !== name.trim()) return "A name has no space at its ends.";
  if (taken.includes(name)) return `A rule set named ${name} already exists.`;
  return null;
}

/** Move the rule at index by one place, or return the same list when it cannot move. */
export function moved(rules: Rule[], index: number, by: -1 | 1): Rule[] {
  const to = index + by;
  if (to < 0 || to >= rules.length) return rules;
  const next = [...rules];
  [next[index], next[to]] = [next[to], next[index]];
  return next;
}

/** Move the rule at index to the place of another. */
export function movedTo(rules: Rule[], from: number, to: number): Rule[] {
  if (from === to || from < 0 || to < 0 || from >= rules.length || to >= rules.length) return rules;
  const next = [...rules];
  const [rule] = next.splice(from, 1);
  next.splice(to, 0, rule);
  return next;
}
