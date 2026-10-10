import assert from "node:assert/strict";
import { test } from "node:test";
import { activityDateRows } from "./activity-date-rows";

test("activityDateRows keeps start and deadline when both present", () => {
  assert.deepEqual(
    activityDateRows({ starts_at: "2026-10-07", deadline_at: "2026-12-02" }),
    [
      { kind: "start", value: "2026-10-07" },
      { kind: "deadline", value: "2026-12-02" },
    ],
  );
});

test("activityDateRows omits missing start without placeholder", () => {
  assert.deepEqual(activityDateRows({ starts_at: null, deadline_at: "2026-12-02" }), [
    { kind: "deadline", value: "2026-12-02" },
  ]);
});

test("activityDateRows omits missing deadline without placeholder", () => {
  assert.deepEqual(activityDateRows({ starts_at: "2026-11-10", deadline_at: undefined }), [
    { kind: "start", value: "2026-11-10" },
  ]);
});

test("activityDateRows empty when both missing", () => {
  assert.deepEqual(activityDateRows({ starts_at: null, deadline_at: null }), []);
});
