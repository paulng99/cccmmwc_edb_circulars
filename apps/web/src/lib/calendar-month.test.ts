import assert from "node:assert/strict";
import test from "node:test";
import {
  INITIAL_FUTURE_MONTHS,
  INITIAL_PAST_MONTHS,
  canExtend,
  extendMonths,
  isoInMonth,
  monthKey,
  monthWindow,
  scrollEdge,
  scrollTopAfterPrepend,
  shiftMonth,
  weekdayIndex,
  weeksForMonth,
  yearMonthFromIso,
  initialScrollTop,
} from "./calendar-month.ts";

test("default window opens on this month with earlier months above and later months below", () => {
  const today = yearMonthFromIso("2026-10-28");
  assert.ok(today);
  const months = monthWindow(today, INITIAL_PAST_MONTHS, INITIAL_FUTURE_MONTHS);
  assert.equal(months.length, INITIAL_PAST_MONTHS + 1 + INITIAL_FUTURE_MONTHS);
  assert.equal(monthKey(months[INITIAL_PAST_MONTHS]), "2026-10");
  assert.ok(monthKey(months[0]) < "2026-10");
  assert.ok(monthKey(months[months.length - 1]) > "2026-10");
  assert.equal(monthKey(months[0]), "2026-02");
  assert.equal(monthKey(months.at(-1)!), "2027-06");
});

test("shiftMonth crosses year boundaries", () => {
  assert.deepEqual(shiftMonth({ year: 2026, month: 1 }, -1), { year: 2025, month: 12 });
  assert.deepEqual(shiftMonth({ year: 2026, month: 12 }, 1), { year: 2027, month: 1 });
  assert.deepEqual(shiftMonth({ year: 2026, month: 10 }, 14), { year: 2027, month: 12 });
});

test("weeksForMonth is Sunday-first and includes neighbour days", () => {
  const october = weeksForMonth({ year: 2026, month: 10 });
  assert.equal(october[0][0], "2026-09-27");
  assert.equal(october[0][4], "2026-10-01");
  assert.equal(october[4][6], "2026-10-31");
  assert.equal(isoInMonth("2026-10-28", { year: 2026, month: 10 }), true);
  assert.equal(isoInMonth("2026-09-27", { year: 2026, month: 10 }), false);

  const february = weeksForMonth({ year: 2026, month: 2 });
  assert.equal(february.length, 4);
  assert.equal(february[0][0], "2026-02-01");
  assert.equal(february[3][6], "2026-02-28");
  assert.equal(weekdayIndex("2026-10-28"), 3);
});

test("extendMonths prepends and appends without dropping the current month", () => {
  const start = monthWindow({ year: 2026, month: 10 }, 1, 1);
  const older = extendMonths(start, "prepend", 2);
  assert.deepEqual(older.map(monthKey), ["2026-07", "2026-08", "2026-09", "2026-10", "2026-11"]);
  const newer = extendMonths(start, "append", 2);
  assert.deepEqual(newer.map(monthKey), ["2026-09", "2026-10", "2026-11", "2026-12", "2027-01"]);
});

test("canExtend stops at the month limit", () => {
  const today = { year: 2026, month: 10 };
  const atPastLimit = [{ year: 2016, month: 10 }];
  const atFutureLimit = [{ year: 2036, month: 10 }];
  assert.equal(canExtend(atPastLimit, "prepend", today, 120), false);
  assert.equal(canExtend(atFutureLimit, "append", today, 120), false);
  assert.equal(canExtend([{ year: 2026, month: 9 }], "prepend", today, 120), true);
});

test("scrollEdge asks for older months near the top and later months near the bottom", () => {
  assert.equal(scrollEdge(0, 400, 400), "none");
  assert.equal(scrollEdge(40, 2000, 500, 160), "prepend");
  assert.equal(scrollEdge(1400, 2000, 500, 160), "append");
  assert.equal(scrollEdge(800, 2000, 500, 160), "none");
});

test("scrollTopAfterPrepend keeps the visible month in place", () => {
  assert.equal(scrollTopAfterPrepend(320, 4000, 4600), 920);
});

test("initial scroll keeps this month at the top when today already fits", () => {
  assert.equal(initialScrollTop(1000, 1200, 40, 500), 1000);
});

test("initial scroll reveals today when the month is taller than the view", () => {
  assert.equal(initialScrollTop(1000, 1400, 48, 300), 1156);
});
