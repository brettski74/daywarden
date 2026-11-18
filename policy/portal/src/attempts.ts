/** The attempts page and the task trend: their choices, the address that holds them, and how figures read. */

import { scaleLinear } from "d3-scale";
import type { AxisTick } from "./components/charts/ChartFrame";
import type { RangeName } from "./usage";

export const SETS: [string, string][] = [
  ["required", "Required"],
  ["potential", "Potential"],
  ["practice", "Practice"],
];

export const OUTCOMES: [string, string][] = [
  ["pass", "Pass"],
  ["failure", "Failure"],
  ["abandoned", "Abandoned"],
  ["unfinished", "Unfinished"],
  ["in_progress", "In progress"],
];

export const DEFAULT_RANGE: RangeName = "past-month";
/** The address's value for a filter with nothing chosen. */
const NONE = "none";

/** What the page shows. ``set`` and ``outcome`` are the chosen values, every one at first. */
export type View = {
  client: string;
  range: RangeName;
  from: string;
  to: string;
  set: string[];
  outcome: string[];
};

/** What the service says of the period. */
export type PeriodData = {
  today: string;
  range: string | null;
  days: { from: string; to: string } | null;
};

export type AttemptRow = {
  id: number;
  task: string;
  type: string;
  set: string;
  started: string;
  finished: string;
  outcome: string;
  duration: string;
};

export type Figures = {
  points: number;
  pass_mark: number | null;
  questions: number;
  maximum: number | null;
  wrong: number;
  timeouts: number;
  time_ms: number;
  average_ms: number | null;
  current_points?: number;
  current_required?: number | null;
  revision_points?: number;
  revision_required?: number | null;
};

export type TrendPoint = {
  id: number;
  at: number;
  started: string;
  set: string;
  practice: boolean;
  outcome: string;
  outcome_label: string;
  figures: Figures | null;
};

function query(pairs: [string, string][]): string {
  return pairs.length ? `?${pairs.map(([key, value]) => `${key}=${encodeURIComponent(value)}`).join("&")}` : "";
}

function filterPairs(key: string, chosen: string[], all: [string, string][]): [string, string][] {
  const picked = all.map(([value]) => value).filter((value) => chosen.includes(value));
  if (picked.length === all.length) return [];
  if (picked.length === 0) return [[key, NONE]];
  return picked.map((value): [string, string] => [key, value]);
}

/** The address's query string for a view, with its ?. A choice left at its default is left out. ``extra`` goes on the end. */
export function viewQuery(view: View, extra: [string, string][] = []): string {
  const pairs: [string, string][] = [];
  if (view.client) pairs.push(["client", view.client]);
  if (view.range !== DEFAULT_RANGE) pairs.push(["range", view.range]);
  if (view.range === "custom") pairs.push(["from", view.from], ["to", view.to]);
  pairs.push(...filterPairs("set", view.set, SETS), ...filterPairs("outcome", view.outcome, OUTCOMES), ...extra);
  return query(pairs);
}

/** A task's trend page, with the view in its address. */
export function trendAddress(type: string, name: string, view: View): string {
  return `/attempts/tasks/${encodeURIComponent(type)}/${encodeURIComponent(name)}${viewQuery(view)}`;
}

/** Turn one value on or off, keeping the others in their list's order. */
export function toggledIn(chosen: string[], value: string, all: [string, string][]): string[] {
  const next = chosen.includes(value) ? chosen.filter((each) => each !== value) : [...chosen, value];
  return all.map(([each]) => each).filter((each) => next.includes(each));
}

export function labelsOf(values: string[], all: [string, string][]): string[] {
  return all.filter(([value]) => values.includes(value)).map(([, label]) => label);
}

export function valueOf(label: string, all: [string, string][]): string {
  return all.find(([, each]) => each === label)?.[0] ?? label;
}

// Trend lines.

export type Kind = "points" | "spelling";
export type SeriesKey =
  | "points"
  | "pass_mark"
  | "current_points"
  | "current_required"
  | "revision_points"
  | "revision_required"
  | "questions"
  | "maximum"
  | "wrong"
  | "timeouts"
  | "time"
  | "average";

/** A line a chart offers. ``colour`` keeps a line's colour whichever others are offered. */
export type SeriesDef = { key: SeriesKey; name: string; colour: number; value: (figures: Figures) => number | null };

const SERIES: Record<SeriesKey, SeriesDef> = {
  points: { key: "points", name: "Points", colour: 0, value: (f) => f.points },
  pass_mark: { key: "pass_mark", name: "Pass mark", colour: 1, value: (f) => f.pass_mark },
  current_points: { key: "current_points", name: "Current points", colour: 0, value: (f) => f.current_points ?? null },
  current_required: { key: "current_required", name: "Current required", colour: 1, value: (f) => f.current_required ?? null },
  revision_points: { key: "revision_points", name: "Revision points", colour: 6, value: (f) => f.revision_points ?? null },
  revision_required: { key: "revision_required", name: "Revision required", colour: 7, value: (f) => f.revision_required ?? null },
  questions: { key: "questions", name: "Questions", colour: 2, value: (f) => f.questions },
  maximum: { key: "maximum", name: "Maximum", colour: 3, value: (f) => f.maximum },
  wrong: { key: "wrong", name: "Wrong", colour: 4, value: (f) => f.wrong },
  timeouts: { key: "timeouts", name: "Timeouts", colour: 5, value: (f) => f.timeouts },
  time: { key: "time", name: "Time answering", colour: 0, value: (f) => f.time_ms / 1000 },
  average: { key: "average", name: "Average per right answer", colour: 1, value: (f) => (f.average_ms === null ? null : f.average_ms / 1000) },
};

/** The counts chart's lines. Spelling's four take the place of Points and Pass mark, and Maximum is there only when an attempt had one. */
export function countSeries(kind: Kind, hasMaximum: boolean): SeriesDef[] {
  const marks: SeriesKey[] = kind === "spelling" ? ["current_points", "current_required", "revision_points", "revision_required"] : ["points", "pass_mark"];
  const rest: SeriesKey[] = hasMaximum ? ["questions", "maximum", "wrong", "timeouts"] : ["questions", "wrong", "timeouts"];
  return [...marks, ...rest].map((key) => SERIES[key]);
}

export const TIME_SERIES: SeriesDef[] = [SERIES.time, SERIES.average];

/** The lines shown before the parent chooses: Points, Pass mark, and Questions, or spelling's four and Questions, and both times. */
export function defaultShown(kind: Kind): SeriesKey[] {
  const marks: SeriesKey[] = kind === "spelling" ? ["current_points", "current_required", "revision_points", "revision_required"] : ["points", "pass_mark"];
  return [...marks, "questions", "time", "average"];
}

/** The lines an address shows: its ``show`` values, or the defaults when it has none. */
export function shownOf(search: string, kind: Kind): SeriesKey[] {
  const values = new URLSearchParams(search).getAll("show");
  if (values.length === 0) return defaultShown(kind);
  return values.filter((value): value is SeriesKey => value in SERIES);
}

/** An address's query string with one line shown or hidden. The defaults leave ``show`` out. */
export function withShown(search: string, kind: Kind, key: SeriesKey): string {
  const shown = shownOf(search, kind);
  const next = shown.includes(key) ? shown.filter((each) => each !== key) : [...shown, key];
  const params = [...new URLSearchParams(search)].filter(([name]) => name !== "show");
  const fallback = defaultShown(kind);
  const same = next.length === fallback.length && fallback.every((each) => next.includes(each));
  if (!same) params.push(...(next.length ? next.map((each): [string, string] => ["show", each]) : [["show", NONE] as [string, string]]));
  return query(params);
}

// How figures read.

/** Points such as 20 or 6.25. */
export function formatPoints(value: number): string {
  return String(Math.round(value * 100) / 100);
}

/** Time answering, `m:ss`. */
export function formatClock(seconds: number): string {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

/** An average per right answer, in seconds to one decimal place, such as 3.0 s. */
export function formatSeconds(seconds: number): string {
  return `${seconds.toFixed(1)} s`;
}

function against(points: number | undefined, mark: number | null | undefined): string {
  return `${formatPoints(points ?? 0)} / ${mark ?? "?"}`;
}

/** Every line of an attempt's readout: when, set and outcome, then each figure. */
export function readoutLines(point: TrendPoint): string[] {
  const lines = [point.started, `${point.set}, ${point.outcome_label}`];
  const f = point.figures;
  if (f === null) return lines;
  if (f.current_points !== undefined) {
    lines.push(`Current points ${against(f.current_points, f.current_required)}`, `Revision points ${against(f.revision_points, f.revision_required)}`);
  } else {
    lines.push(`Points ${against(f.points, f.pass_mark)}`);
  }
  lines.push(f.maximum === null ? `Questions ${f.questions}` : `Questions ${f.questions}, maximum ${f.maximum}`);
  lines.push(`Wrong ${f.wrong}, timeouts ${f.timeouts}`);
  lines.push(`Time answering ${formatClock(f.time_ms / 1000)}`);
  lines.push(`Average per right answer ${f.average_ms === null ? "none" : formatSeconds(f.average_ms / 1000)}`);
  return lines;
}

// Axes.

const MOST_TICKS = 6;

function niceAxis(largest: number, label: (value: number) => string, whole: boolean): { max: number; ticks: AxisTick[] } {
  const scale = scaleLinear().domain([0, Math.max(largest, 1)]).nice(MOST_TICKS);
  const ticks = scale.ticks(MOST_TICKS).filter((value) => !whole || Number.isInteger(value));
  return { max: scale.domain()[1], ticks: ticks.map((value) => ({ value, label: label(value) })) };
}

export const countAxis = (largest: number) => niceAxis(largest, String, true);
export const clockAxis = (largest: number) => niceAxis(largest, formatClock, true);
export const secondsAxis = (largest: number) => niceAxis(largest, (value) => `${Number(value.toPrecision(4))} s`, false);
