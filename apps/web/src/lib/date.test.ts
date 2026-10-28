import assert from "node:assert/strict";
import test from "node:test";
import { formatHkTimeHm, hkTodayIso } from "./date.ts";

test("formatHkTimeHm formats Asia/Hong_Kong HH:mm", () => {
  // 2026-10-14 00:05:00 UTC = 08:05 HKT
  assert.equal(formatHkTimeHm("2026-10-14T00:05:00+00:00"), "08:05");
});

test("formatHkTimeHm returns em dash for empty", () => {
  assert.equal(formatHkTimeHm(null), "—");
  assert.equal(formatHkTimeHm(undefined), "—");
});

test("hkTodayIso uses the Hong Kong calendar day across the UTC boundary", () => {
  assert.equal(hkTodayIso(new Date("2026-10-27T16:30:00Z")), "2026-10-28");
  assert.equal(hkTodayIso(new Date("2026-10-28T15:59:00Z")), "2026-10-28");
  assert.equal(hkTodayIso(new Date("2026-10-28T16:00:00Z")), "2026-10-29");
});
