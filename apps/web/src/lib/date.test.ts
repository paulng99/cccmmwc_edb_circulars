import assert from "node:assert/strict";
import test from "node:test";
import { formatHkTimeHm } from "./date.ts";

test("formatHkTimeHm formats Asia/Hong_Kong HH:mm", () => {
  // 2026-10-14 00:05:00 UTC = 08:05 HKT
  assert.equal(formatHkTimeHm("2026-10-14T00:05:00+00:00"), "08:05");
});

test("formatHkTimeHm returns em dash for empty", () => {
  assert.equal(formatHkTimeHm(null), "—");
  assert.equal(formatHkTimeHm(undefined), "—");
});
