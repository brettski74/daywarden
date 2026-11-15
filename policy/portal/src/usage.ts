/** The usage graph's settings, the address that holds them, and how its values read. */

import { scaleLinear } from "d3-scale";

export const UNITS = ["minutes", "bytes"] as const;
export type Unit = (typeof UNITS)[number];

export type GroupBy = "client" | "site" | "quota" | "none";
export type RangeName =
  | "today"
  | "yesterday"
  | "this-week"
  | "this-month"
  | "past-week"
  | "past-month"
  | "previous-week"
  | "previous-month"
  | "custom";

export const GROUP_BY: [GroupBy, string][] = [
  ["client", "Client group"],
  ["site", "Site group"],
  ["quota", "Quota"],
  ["none", "None"],
];

export const RANGES: [RangeName, string][] = [
  ["today", "Today"],
  ["yesterday", "Yesterday"],
  ["this-week", "This week"],
  ["this-month", "This month"],
  ["past-week", "Past week"],
  ["past-month", "Past month"],
  ["previous-week", "Previous week"],
  ["previous-month", "Previous month"],
  ["custom", "Custom"],
];

/** What a graph shows. ``from`` and ``to`` are the Custom range's days, `yyyy-mm-dd`, and empty otherwise. */
export type Settings = {
  client: string[];
  site: string[];
  quota: string[];
  by: GroupBy;
  range: RangeName;
  from: string;
  to: string;
};

export type Graph = {
  /** Seconds from the start of the range to its end. Every `at` is seconds from the start. */
  length: number;
  interval: "hour" | "day" | "week";
  ticks: { at: number; label: string }[];
  points: { at: number; label: string }[];
  /** Seconds on the Minutes page and bytes on the Bytes page, one value per point. */
  lines: { name: string; values: number[] }[];
};

/** One host's bar. ``value`` is seconds on the Minutes page, and bytes down and up added on the Bytes page. */
export type HostBar = { host: string; value: number; down?: number; up?: number };

/** The top hosts on the line the address drills into, highest first. */
export type Hosts = {
  line: string;
  /** From when hosts are kept, when the range starts before that. */
  kept: string | null;
  bars: HostBar[];
};

export type RequestRow = {
  id: string;
  start: string;
  end: string;
  duration: string;
  address: string;
  client_group: string;
  site_group: string;
  quotas: string;
  method: string;
  host: string;
  path: string;
  query: string;
  url: string;
  status: string;
  type: string;
  down: string;
  up: string;
  outcome: string;
};

export type RequestsData = {
  today: string;
  choices: { clients: string[]; sites: string[]; quotas: string[]; outcomes: string[] };
  settings: Settings;
  preset: string;
  presets: string[];
  host: string;
  exact: boolean;
  outcome: string[];
  sort: string;
  dir: "asc" | "desc";
  page: number;
  pages: number;
  notes: string[];
  times: string;
  range: string | null;
  days: { from: string; to: string } | null;
  kept: string | null;
  total: number;
  from: number;
  to: number;
  rows: RequestRow[];
  status: string | null;
};

export type UsageData = {
  unit: Unit;
  today: string;
  choices: { clients: string[]; sites: string[]; quotas: string[] };
  settings: Settings;
  /** The preset whose settings are on show, or "". */
  preset: string;
  presets: string[];
  notes: string[];
  times: string;
  range: string | null;
  days: { from: string; to: string } | null;
  graph: Graph | null;
  hosts: Hosts | null;
  /** The requests for the host drilled into, or null when none is. */
  requests: RequestsData | null;
};

export const OUTCOMES = ["allowed", "denied", "redirected", "cut"] as const;
export type OutcomeName = (typeof OUTCOMES)[number];


export const DEFAULT_PRESET = "Default";
export const QUOTA_SITE = "Usage by quota is not kept per site group.";

function query(pairs: [string, string][]): string {
  return pairs.length ? `?${pairs.map(([key, value]) => `${key}=${encodeURIComponent(value)}`).join("&")}` : "";
}

/** The address's query string for settings, with its ?, and the line drilled into last when there is one. */
export function settingsQuery(settings: Settings, line: string | null = null): string {
  const pairs: [string, string][] = [
    ...settings.client.map((name): [string, string] => ["client", name]),
    ...settings.site.map((name): [string, string] => ["site", name]),
    ...settings.quota.map((name): [string, string] => ["quota", name]),
    ["by", settings.by],
    ["range", settings.range],
  ];
  if (settings.range === "custom") pairs.push(["from", settings.from], ["to", settings.to]);
  if (line) pairs.push(["line", line]);
  return query(pairs);
}

/** The address's query string for a preset, such as ?preset=School%20week, and the line drilled into. */
export function presetQuery(name: string, line: string | null = null): string {
  return query(line ? [["preset", name], ["line", line]] : [["preset", name]]);
}

/** The line an address drills into, or null. */
export function lineOf(search: string): string | null {
  return new URLSearchParams(search).get("line") || null;
}

/** An address's query string with its line replaced, or taken away when line is null. Everything else stays in order. */
export function withLine(search: string, line: string | null): string {
  const pairs = [...new URLSearchParams(search)].filter(([key]) => key !== "line" && key !== "host" && key !== "exact" && key !== "sort" && key !== "dir" && key !== "page");
  if (line) pairs.push(["line", line]);
  return query(pairs);
}

/** The host an address drills into, or null. */
export function hostOf(search: string): string | null {
  return new URLSearchParams(search).get("host") || null;
}

/** An address's query string with its host drill replaced. Opening a host is exact; closing drops sort and page too. */
export function withHost(search: string, host: string | null): string {
  const pairs = [...new URLSearchParams(search)].filter(([key]) => key !== "host" && key !== "exact" && key !== "sort" && key !== "dir" && key !== "page");
  if (host) pairs.push(["host", host], ["exact", "1"]);
  return query(pairs);
}

/** Replace sort, direction, and page on an address, keeping everything else. Changing a filter should call this with page 1. */
export function withTable(search: string, patch: { sort?: string; dir?: "asc" | "desc"; page?: number; host?: string; outcome?: string[] }): string {
  const params = new URLSearchParams(search);
  if (patch.sort !== undefined) params.set("sort", patch.sort);
  if (patch.dir !== undefined) params.set("dir", patch.dir);
  if (patch.page !== undefined) {
    if (patch.page <= 1) params.delete("page");
    else params.set("page", String(patch.page));
  }
  if (patch.host !== undefined) {
    if (patch.host) params.set("host", patch.host);
    else params.delete("host");
  }
  if (patch.outcome !== undefined) {
    params.delete("outcome");
    for (const name of patch.outcome) params.append("outcome", name);
  }
  const pairs = [...params];
  return query(pairs);
}

/** Settings for the Requests page: filters and range, without Group by, plus host fragment and outcomes. */
export function requestsQuery(
  settings: Settings,
  extras: { host?: string; outcome?: string[]; sort?: string; dir?: "asc" | "desc"; page?: number } = {},
): string {
  const pairs: [string, string][] = [
    ...settings.client.map((name): [string, string] => ["client", name]),
    ...settings.site.map((name): [string, string] => ["site", name]),
    ...settings.quota.map((name): [string, string] => ["quota", name]),
    ["range", settings.range],
  ];
  if (settings.range === "custom") pairs.push(["from", settings.from], ["to", settings.to]);
  if (extras.host) pairs.push(["host", extras.host]);
  for (const name of extras.outcome ?? []) pairs.push(["outcome", name]);
  if (extras.sort && extras.sort !== "start") pairs.push(["sort", extras.sort]);
  if (extras.dir && extras.dir !== "desc") pairs.push(["dir", extras.dir]);
  if (extras.page && extras.page > 1) pairs.push(["page", String(extras.page)]);
  return query(pairs);
}

/** The date range as the bar chart's heading names it, such as Past week, or 2026-11-01 to 2026-11-07. */
export function rangeLabel(settings: Settings): string {
  if (settings.range === "custom") return `${settings.from} to ${settings.to}`;
  return RANGES.find(([value]) => value === settings.range)?.[1] ?? settings.range;
}

/** Why Site groups cannot be chosen, or null when they can. */
export function sitesBlocked(settings: Settings): string | null {
  return settings.quota.length > 0 || settings.by === "quota" ? `${QUOTA_SITE} Clear Quotas and group by something other than Quota to choose site groups.` : null;
}

/** Why Quotas cannot be chosen, or null when they can. */
export function quotasBlocked(settings: Settings): string | null {
  return settings.site.length > 0 || settings.by === "site" ? `${QUOTA_SITE} Clear Site groups and group by something other than Site group to choose quotas.` : null;
}

/** The Group by choices the other filters allow. */
export function groupByChoices(settings: Settings): [GroupBy, string][] {
  return GROUP_BY.filter(([value]) => (value === "site" ? settings.quota.length === 0 : value === "quota" ? settings.site.length === 0 : true));
}

/** Turn one name on or off in a list, keeping the others in order. */
export function toggled(names: string[], name: string): string[] {
  return names.includes(name) ? names.filter((each) => each !== name) : [...names, name];
}

/** A duration such as 6h 20m, 45m, 2m 30s, or 0m. */
export function formatDuration(seconds: number): string {
  const whole = Math.round(seconds);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const rest = whole % 60;
  const parts = [hours ? `${hours}h` : "", minutes ? `${minutes}m` : "", rest ? `${rest}s` : ""].filter(Boolean);
  return parts.length ? parts.join(" ") : "0m";
}

/** KB, MB, GB, and TB are the powers of 1,024 the policy file uses. */
export const BYTE_UNITS: [string, number][] = [
  ["TB", 1024 ** 4],
  ["GB", 1024 ** 3],
  ["MB", 1024 ** 2],
  ["KB", 1024],
];

/** The largest unit that count reaches, and KB below that. */
export function byteUnit(count: number): [string, number] {
  return BYTE_UNITS.find(([, size]) => count >= size) ?? BYTE_UNITS[BYTE_UNITS.length - 1];
}

/** A number of units with at most one decimal place below ten, such as 1.4 or 512. */
export function units(value: number): string {
  return String(value < 10 ? Math.round(value * 10) / 10 : Math.round(value));
}

/** A byte count such as 1.4 GB, 512 MB, or 900 bytes. */
export function formatBytes(count: number): string {
  if (count < 1024) return count === 1 ? "1 byte" : `${Math.round(count)} bytes`;
  const [name, size] = byteUnit(count);
  return `${units(count / size)} ${name}`;
}

const MINUTE_STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 180, 240, 360, 720, 1440, 2880, 4320, 7200, 10080, 20160, 43200];
const MOST_STEPS = 6;

export type AxisTick = { value: number; label: string };

/** A minutes axis to at least the largest value, in steps that read well as durations, from 0 to at least an hour. Values are seconds. */
export function durationAxis(largest: number): { max: number; ticks: AxisTick[] } {
  const minutes = Math.max(largest / 60, 60);
  const step = MINUTE_STEPS.find((each) => Math.ceil(minutes / each) <= MOST_STEPS) ?? Math.ceil(minutes / MOST_STEPS);
  const count = Math.ceil(minutes / step);
  const ticks = Array.from({ length: count + 1 }, (_, index) => ({ value: index * step * 60, label: formatDuration(index * step * 60) }));
  return { max: count * step * 60, ticks };
}

/** A bytes axis to at least the largest value, from 0 to at least 1 KB, labelled in the unit the top of the axis reaches. */
export function bytesAxis(largest: number): { max: number; ticks: AxisTick[] } {
  const top = Math.max(largest, 1024);
  const [name, size] = byteUnit(top);
  const scale = scaleLinear().domain([0, top / size]).nice(MOST_STEPS);
  return {
    max: scale.domain()[1] * size,
    ticks: scale.ticks(MOST_STEPS).map((value) => ({ value: value * size, label: value === 0 ? "0" : `${Number(value.toPrecision(6))} ${name}` })),
  };
}
