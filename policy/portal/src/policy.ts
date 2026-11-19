/** The policy pages: Client Groups, Site Groups, Time Windows, Quotas, and Household. */

export type ItemPage = "client-groups" | "site-groups" | "time-windows" | "quotas";
export type PageKey = ItemPage | "rule-sets" | "household";

export type PageInfo = {
  key: PageKey;
  title: string;
  /** What one item is called, in the singular and lower case. */
  item: string;
};

export const POLICY_PAGES: PageInfo[] = [
  { key: "client-groups", title: "Client Groups", item: "client group" },
  { key: "site-groups", title: "Site Groups", item: "site group" },
  { key: "time-windows", title: "Time Windows", item: "time window" },
  { key: "quotas", title: "Quotas", item: "quota" },
  { key: "rule-sets", title: "Rule Sets", item: "rule set" },
  { key: "household", title: "Household", item: "household" },
];

export const POLICY = "/policy";

export function policyPath(key: PageKey): string {
  return `${POLICY}/${key}`;
}

export function infoOf(key: PageKey): PageInfo {
  return POLICY_PAGES.find((page) => page.key === key) as PageInfo;
}

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/** One period of a time window. ``origin`` is its place in the file, or null for one just added. */
export type Period = { origin: number | null; start: string; end: string; extra: string; weekdays: number[] };

export type Fields = {
  addresses?: string[];
  priority?: string;
  patterns?: string[];
  periods?: Period[];
  time?: string;
  bytes?: string;
  time_grace?: string;
  volume_grace?: string;
  ruleset?: string;
};

/** An item as the service sends it. */
export type ItemData = { name: string; file: string | null } & Fields;

export type ItemsData = {
  version: string;
  file: string;
  items: ItemData[];
  rule_sets?: string[];
  defaults?: { time_grace: string; volume_grace: string };
};

export type Row = {
  id: number;
  name: string;
  isNew: boolean;
  /** Marked to be removed at the next save. */
  marked: boolean;
  file: string | null;
  fields: Fields;
  /** The fields as the file has them, or null for a new item. */
  orig: Fields | null;
};

const FIELDS: Record<ItemPage, (keyof Fields)[]> = {
  "client-groups": ["addresses"],
  "site-groups": ["priority", "patterns"],
  "time-windows": ["periods"],
  quotas: ["time", "bytes", "time_grace", "volume_grace", "ruleset"],
};

export function blankFields(page: ItemPage): Fields {
  if (page === "client-groups") return { addresses: [] };
  if (page === "site-groups") return { priority: "", patterns: [] };
  if (page === "time-windows") return { periods: [] };
  return { time: "", bytes: "", time_grace: "", volume_grace: "", ruleset: "" };
}

function fieldsOf(page: ItemPage, item: ItemData): Fields {
  const found: Fields = {};
  for (const key of FIELDS[page]) (found as Record<string, unknown>)[key] = structuredClone(item[key]);
  return found;
}

export function rowsFrom(page: ItemPage, data: ItemsData, nextId: () => number): Row[] {
  return data.items.map((item) => ({
    id: nextId(),
    name: item.name,
    isNew: false,
    marked: false,
    file: item.file,
    fields: fieldsOf(page, item),
    orig: fieldsOf(page, item),
  }));
}

/** Read a clock the way the box takes one: HH:MM, H:MM, or HHMM. Return HH:MM, or the text as typed when it is not a clock. */
export function normalizeClock(text: string): string {
  const typed = text.trim();
  const found = /^(\d{1,2}):(\d{2})$/.exec(typed) ?? (/^(\d{2})(\d{2})$/.exec(typed) as RegExpExecArray | null);
  if (!found) return text;
  const [hours, minutes] = [Number(found[1]), Number(found[2])];
  if (hours > 23 || minutes > 59) return text;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

/** What is wrong with an extra days box, or null. The service checks the rest. */
export function extraProblem(text: string): string | null {
  return text.trim() === "" || /^\d+$/.test(text.trim()) ? null : "Extra days is a whole number, 0 or more.";
}

function normalized(fields: Fields): Fields {
  if (!fields.periods) return fields;
  return {
    ...fields,
    periods: fields.periods.map((period) => ({
      ...period,
      start: normalizeClock(period.start),
      end: normalizeClock(period.end),
      extra: period.extra.trim() === "" ? "0" : period.extra.trim(),
      weekdays: [...period.weekdays].sort((a, b) => a - b),
    })),
  };
}

function trimmed(fields: Fields): Fields {
  const found: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(normalized(fields))) {
    found[key] = typeof value === "string" ? value.trim() : Array.isArray(value) && typeof value[0] === "string" ? (value as string[]).map((text) => text.trim()) : value;
  }
  return found as Fields;
}

function periodsLike(fields: Fields): unknown {
  // The origin only says where a period was read from, so it is not a change by itself.
  return fields.periods?.map(({ origin: _origin, ...rest }) => rest);
}

export function sameFields(a: Fields, b: Fields): boolean {
  const [left, right] = [trimmed(a), trimmed(b)];
  return JSON.stringify({ ...left, periods: periodsLike(left) }) === JSON.stringify({ ...right, periods: periodsLike(right) });
}

/** Whether a row is changed, new, or marked, so that a save has to send it or delete it. */
export function rowChanged(row: Row): boolean {
  if (row.isNew || row.marked) return true;
  return row.orig !== null && !sameFields(row.fields, row.orig);
}

export function anyChanged(rows: Row[]): boolean {
  return rows.some(rowChanged);
}

/** The first reason a row cannot be saved, or null. The service's checks decide the rest, and say why. */
export function rowProblem(page: ItemPage, row: Row): string | null {
  if (row.marked) return null;
  const item = infoOf(page).item;
  if (row.name.trim() === "") return `Give the ${item} a name.`;
  for (const key of ["addresses", "patterns"] as const) {
    if ((row.fields[key] ?? []).some((text) => text.trim() === "")) return `Give each ${key === "addresses" ? "address" : "pattern"} a value, or remove it.`;
  }
  for (const period of row.fields.periods ?? []) {
    const trouble = extraProblem(period.extra);
    if (trouble) return trouble;
  }
  return null;
}

export function pageProblem(page: ItemPage, rows: Row[]): string | null {
  for (const row of rows) {
    const trouble = rowProblem(page, row);
    if (trouble) return trouble;
  }
  return null;
}

/** What a save sends: each changed or new item with its fields, and the names to delete. */
export function saveRequest(rows: Row[], version: string): { version: string; items: unknown[]; deleted: string[] } {
  const items = rows
    .filter((row) => !row.marked && rowChanged(row))
    .map((row) => ({ name: row.name.trim(), new: row.isNew, fields: trimmed(row.fields) }));
  const deleted = rows.filter((row) => row.marked && !row.isNew).map((row) => row.name);
  return { version, items, deleted };
}

// Household

export type Proxy = {
  localhost: boolean;
  plain_host_names: boolean;
  policy_server: boolean;
  local_subnets: boolean;
  local_domains: boolean;
  extra: string[];
};

export const SWITCHES = ["localhost", "plain_host_names", "policy_server", "local_subnets", "local_domains"] as const;

export const HOUSEHOLD_TEXT = ["timezone", "bucket_length", "time_grace", "volume_grace", "host_retention", "request_retention"] as const;

export type HouseholdData = {
  version: string;
  file: string;
  fields: Record<string, string>;
  proxy: Proxy;
  rule_sets: string[];
  defaults: Record<string, string>;
};

export type HouseholdEdits = { fields: Record<string, string>; proxy: Proxy };

export function householdChanged(data: HouseholdData, edits: HouseholdEdits): boolean {
  return Object.keys(householdRequest(data, edits, data.version).fields).length > 0;
}

export function proxyChanged(was: Proxy, now: Proxy): boolean {
  return SWITCHES.some((name) => was[name] !== now[name]) || JSON.stringify(was.extra.map((text) => text.trim())) !== JSON.stringify(now.extra.map((text) => text.trim()));
}

/** What a save sends: only the settings that differ from the file, each blank one as "" to take it out. */
export function householdRequest(data: HouseholdData, edits: HouseholdEdits, version: string): { version: string; fields: Record<string, unknown> } {
  const fields: Record<string, unknown> = {};
  for (const key of ["entry", ...HOUSEHOLD_TEXT]) {
    if ((edits.fields[key] ?? "").trim() !== (data.fields[key] ?? "").trim()) fields[key] = (edits.fields[key] ?? "").trim();
  }
  if (proxyChanged(data.proxy, edits.proxy)) {
    const { extra, ...switches } = edits.proxy;
    fields.proxy_configuration = { direct: { ...switches, extra: extra.map((text) => text.trim()) } };
  }
  return { version, fields };
}

export function householdProblem(edits: HouseholdEdits): string | null {
  if (edits.proxy.extra.some((text) => text.trim() === "")) return "Give each extra entry a value, or remove it.";
  if ((edits.fields.entry ?? "").trim() === "") return "Choose the entry rule set.";
  return null;
}
