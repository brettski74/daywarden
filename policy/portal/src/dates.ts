/** Calendar days as the policy file writes them, `yyyy-mm-dd`, and the moves a calendar makes between them. */

/** A calendar day. Month is 1 to 12. */
export type Day = { year: number; month: number; day: number };

export const NOT_A_DATE = "Not a date. Use yyyy-mm-dd, such as 2026-10-31.";
export const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
export const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

const DAY_TEXT = /^([0-9]{4})-([0-9]{2})-([0-9]{2})$/;

export function daysInMonth(year: number, month: number): number {
  return toDate({ year, month: month + 1, day: 0 }).getUTCDate();
}

/** Read `yyyy-mm-dd`, ignoring a space at either end. Anything that is not a real day, as the policy check reads it, is null. */
export function parseDay(text: string): Day | null {
  const match = DAY_TEXT.exec(text.trim());
  if (!match) return null;
  const [year, month, day] = match.slice(1).map(Number);
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month)) return null;
  return { year, month, day };
}

/** The problem with a date box's text, or null. An empty box is no problem. */
export function dateProblem(text: string): string | null {
  return text.trim() === "" || parseDay(text) !== null ? null : NOT_A_DATE;
}

export function formatDay({ year, month, day }: Day): string {
  return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** The full date, such as Tuesday 10 November 2026. */
export function longDay(day: Day): string {
  return `${WEEKDAYS[weekday(day)]} ${day.day} ${MONTHS[day.month - 1]} ${day.year}`;
}

/** 0 for Sunday to 6 for Saturday. */
export function weekday(day: Day): number {
  return toDate(day).getUTCDay();
}

export function sameDay(a: Day | null, b: Day | null): boolean {
  return a !== null && b !== null && a.year === b.year && a.month === b.month && a.day === b.day;
}

export function addDays(day: Day, count: number): Day {
  return fromDate(toDate({ ...day, day: day.day + count }));
}

/** Move by whole months, keeping the day of the month where that month has it, and its last day where not. */
export function addMonths({ year, month, day }: Day, count: number): Day {
  const index = year * 12 + (month - 1) + count;
  const to = { year: Math.floor(index / 12), month: (index % 12) + 1 };
  return { ...to, day: Math.min(day, daysInMonth(to.year, to.month)) };
}

/** The weeks of a day's month, Sunday first, with null for the days of the months either side. */
export function monthWeeks({ year, month }: Day): (Day | null)[][] {
  const cells: (Day | null)[] = Array(weekday({ year, month, day: 1 })).fill(null);
  for (let day = 1; day <= daysInMonth(year, month); day += 1) cells.push({ year, month, day });
  while (cells.length % 7 !== 0) cells.push(null);
  const weeks: (Day | null)[][] = [];
  for (let start = 0; start < cells.length; start += 7) weeks.push(cells.slice(start, start + 7));
  return weeks;
}

/** Dates in UTC, with the full year set, so no timezone shift or two-digit year can move them. */
function toDate({ year, month, day }: Day): Date {
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  return date;
}

function fromDate(date: Date): Day {
  return { year: date.getUTCFullYear(), month: date.getUTCMonth() + 1, day: date.getUTCDate() };
}
