import { fromService, isEmpty, sameRows, tableProblems, toService, whole, type Bounds, type NumberRow, type ServiceRow, type TableRules } from "./numberTable";

/** A changed list: its rows, or the default list a skip counting task falls back on. */
export type ListEdit = NumberRow[] | "default";
export type ListEdits = Record<string, ListEdit>;

export type SkipData = {
  settings: Record<string, string>;
  /** The checkboxes' values in force, which are their defaults when the file leaves them out. */
  flags: Record<string, boolean>;
  /** The task's own list, or null when it uses the default list. */
  difference: ServiceRow[] | null;
  /** The default list, each difference with its own cap. */
  default: ServiceRow[];
  problems: string[];
};

export const FIX_ON_PAGE = "Fix the problems marked on the page first.";
export const NO_DIFFERENCES = "Add a difference, or use the default list.";
export const DEFAULT_NOTE = "This task uses the default list of differences.";
export const DIFFERENCE_RULES: TableRules = { bounds: true, negatives: true, noZero: true };

export const QUESTION_SETTINGS = ["sequence_length", "completed", "minimum_value", "maximum_value", "consecutive", "multiples_only"];
export const SESSION_SETTINGS = ["timeout", "correct_answers_required", "minimum_questions", "maximum_questions"];
export const FLAGS = ["consecutive", "multiples_only"];
const PLACEHOLDERS: Record<string, string> = {
  sequence_length: "8",
  completed: "3",
  minimum_value: "1",
  maximum_value: "999",
  timeout: "3m",
  maximum_questions: "None",
};
const DEFAULT_REQUIRED = 8;

function shownSetting(data: SkipData, settings: Record<string, string>, key: string): string {
  return settings[key] ?? data.settings[key] ?? "";
}

function positive(text: string): number | null {
  const value = whole(text);
  return value !== null && value >= 1 ? value : null;
}

/** The Correct Answers Required in force when the box is empty, worked out as the loader does from the questions on the page. */
export function defaultRequired(minimumQuestions: string, maximumQuestions: string): number {
  const least = positive(minimumQuestions);
  const most = positive(maximumQuestions);
  const required = least === null ? DEFAULT_REQUIRED : Math.max(DEFAULT_REQUIRED, Math.ceil((4 * least) / 5));
  return most === null ? required : Math.min(required, most);
}

/** Each setting's placeholder, following the settings now on the page. */
export function placeholderOf(data: SkipData, settings: Record<string, string>, key: string): string | undefined {
  const value = (name: string) => shownSetting(data, settings, name);
  const required = () => String(defaultRequired(value("minimum_questions"), value("maximum_questions")));
  if (key === "correct_answers_required") return required();
  if (key === "minimum_questions") return value("correct_answers_required").trim() || required();
  return PLACEHOLDERS[key];
}

/** Whether a checkbox is ticked: as changed on the page, or the value in force. */
export function flagOf(data: SkipData, settings: Record<string, string>, key: string): boolean {
  const edited = settings[key];
  if (edited === undefined || edited.trim() === (data.settings[key] ?? "").trim()) return data.flags[key];
  return edited === "true";
}

/** The settings edit a checkbox makes. Changing it back puts back the text as written. */
export function flagEdit(data: SkipData, key: string, ticked: boolean): string {
  return ticked === data.flags[key] ? (data.settings[key] ?? "") : String(ticked);
}

/** The task's own Minimum Value, Maximum Value, and Multiples Only as now on the page. */
export function taskBounds(data: SkipData, settings: Record<string, string>): { min: string; max: string; multiples: boolean } {
  return {
    min: shownSetting(data, settings, "minimum_value").trim() || PLACEHOLDERS.minimum_value,
    max: shownSetting(data, settings, "maximum_value").trim() || PLACEHOLDERS.maximum_value,
    multiples: flagOf(data, settings, "multiples_only"),
  };
}

/** The default list as rows, each cap lowered to the Maximum Value now on the page. */
export function defaultRows(data: SkipData, settings: Record<string, string>): NumberRow[] {
  const maximum = whole(taskBounds(data, settings).max);
  return fromService(data.default, "d").map((row) => {
    const cap = whole(row.max);
    return cap === null || maximum === null ? row : { ...row, max: String(Math.min(cap, maximum)) };
  });
}

export type ShownDifference = {
  rows: NumberRow[];
  /** Whether the rows are the default list, unchanged. */
  isDefault: boolean;
  /** What the change marks compare with, or null when every row is new. */
  originals: NumberRow[] | null;
  changed: boolean;
};

export function shownDifference(data: SkipData, settings: Record<string, string>, edit: ListEdit | undefined): ShownDifference {
  const defaults = defaultRows(data, settings);
  const own = data.difference === null ? null : fromService(data.difference, "r");
  if (edit === undefined) return { rows: own ?? defaults, isDefault: own === null, originals: own ?? defaults, changed: false };
  if (edit === "default") return { rows: defaults, isDefault: true, originals: own === null ? defaults : null, changed: own !== null };
  if (own === null) {
    const same = sameRows(edit, defaults);
    return { rows: edit, isDefault: same, originals: defaults, changed: !same };
  }
  return { rows: edit, isDefault: false, originals: own, changed: !sameRows(edit, own) };
}

export function differenceProblems(rows: NumberRow[], data: SkipData, settings: Record<string, string>): string[][] {
  const shown = taskBounds(data, settings);
  const bounds: Bounds = { minimum: whole(shown.min), maximum: whole(shown.max) };
  return tableProblems(rows, DIFFERENCE_RULES, bounds);
}

/** Whether anything on the page stops a save. */
export function skipBlocked(shown: ShownDifference, problems: string[][]): boolean {
  return shown.rows.every(isEmpty) || problems.some((found) => found.length > 0);
}

export function skipCounts(shown: ShownDifference, problems: string[][]): string {
  const count = shown.rows.filter((row) => !isEmpty(row)).length;
  const troubled = problems.filter((found) => found.length > 0).length;
  const listed = shown.isDefault ? `Default list of ${count} differences.` : `${count} difference${count === 1 ? "" : "s"}.`;
  return `${listed} ${troubled === 0 ? "None" : troubled} with problems.`;
}

/** The difference list as a save sends it, or undefined when it is unchanged. */
export function differenceRequest(shown: ShownDifference): ServiceRow[] | "default" | undefined {
  if (!shown.changed) return undefined;
  return shown.isDefault ? "default" : toService(shown.rows, true);
}
