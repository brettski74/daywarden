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
};

export const DEFAULT_PRESET = "Default";
export const QUOTA_SITE = "Usage by quota is not kept per site group.";

function query(pairs: [string, string][]): string {
  return pairs.length ? `?${pairs.map(([key, value]) => `${key}=${encodeURIComponent(value)}`).join("&")}` : "";
}

/** The address's query string for settings, with its ?. */
export function settingsQuery(settings: Settings): string {
  const pairs: [string, string][] = [
    ...settings.client.map((name): [string, string] => ["client", name]),
    ...settings.site.map((name): [string, string] => ["site", name]),
    ...settings.quota.map((name): [string, string] => ["quota", name]),
    ["by", settings.by],
    ["range", settings.range],
  ];
  if (settings.range === "custom") pairs.push(["from", settings.from], ["to", settings.to]);
  return query(pairs);
}

/** The address's query string for a preset, such as ?preset=School%20week. */
export function presetQuery(name: string): string {
  return query([["preset", name]]);
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
