import { describe, expect, it } from "vitest";
import { NOT_A_DATE, addDays, addMonths, dateProblem, formatDay, longDay, monthWeeks, parseDay } from "./dates";

describe("reading a date box", () => {
  it.each(["2026-10-31", " 2026-10-31 ", "2028-02-29", "0001-01-01"])("reads %j as a day", (text) => {
    expect(parseDay(text)).not.toBeNull();
    expect(dateProblem(text)).toBeNull();
  });

  it.each(["2026-11-31", "2026-02-29", "2026-13-01", "2026-00-10", "0000-01-01", "10/11/2026", "2026-1-5", "2026-10-31x", "２０２６-10-31"])(
    "calls %j not a date",
    (text) => {
      expect(parseDay(text)).toBeNull();
      expect(dateProblem(text)).toBe(NOT_A_DATE);
    },
  );

  it("finds no problem in an empty box", () => {
    expect(dateProblem("  ")).toBeNull();
  });

  it("writes a day back as yyyy-mm-dd, and in full with its weekday", () => {
    expect(formatDay({ year: 26, month: 3, day: 7 })).toBe("0026-03-07");
    expect(longDay({ year: 2026, month: 11, day: 10 })).toBe("Tuesday 10 November 2026");
  });
});

describe("moving between days", () => {
  it("crosses month and year edges a day or a week at a time", () => {
    expect(addDays({ year: 2026, month: 12, day: 31 }, 1)).toEqual({ year: 2027, month: 1, day: 1 });
    expect(addDays({ year: 2026, month: 3, day: 3 }, -7)).toEqual({ year: 2026, month: 2, day: 24 });
  });

  it("keeps the day of the month, or the month's last day where it has no such day", () => {
    expect(addMonths({ year: 2026, month: 1, day: 31 }, 1)).toEqual({ year: 2026, month: 2, day: 28 });
    expect(addMonths({ year: 2028, month: 2, day: 29 }, 12)).toEqual({ year: 2029, month: 2, day: 28 });
    expect(addMonths({ year: 2026, month: 1, day: 15 }, -1)).toEqual({ year: 2025, month: 12, day: 15 });
  });

  it("lays a month out in weeks from Sunday, with blanks for the months either side", () => {
    const weeks = monthWeeks({ year: 2026, month: 11, day: 10 });
    expect(weeks.map((week) => week.map((day) => day?.day ?? null))).toEqual([
      [1, 2, 3, 4, 5, 6, 7],
      [8, 9, 10, 11, 12, 13, 14],
      [15, 16, 17, 18, 19, 20, 21],
      [22, 23, 24, 25, 26, 27, 28],
      [29, 30, null, null, null, null, null],
    ]);
    expect(monthWeeks({ year: 2026, month: 10, day: 1 })[0].map((day) => day?.day ?? null)).toEqual([null, null, null, null, 1, 2, 3]);
  });
});
