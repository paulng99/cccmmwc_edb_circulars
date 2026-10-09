import assert from "node:assert/strict";
import test from "node:test";
import {
  applyReanalyzeResults,
  canSubmitReanalyze,
  expandSelectedDocumentIds,
  reanalyzeButtonLabel,
  toggleIdInSet,
} from "./reanalyze-ui.ts";

test("cannot submit when nothing selected", () => {
  assert.equal(canSubmitReanalyze(0, false), false);
  assert.equal(canSubmitReanalyze(0, true), false);
});

test("can submit when selection present and not analyzing", () => {
  assert.equal(canSubmitReanalyze(1, false), true);
  assert.equal(canSubmitReanalyze(3, false), true);
  assert.equal(canSubmitReanalyze(2, true), false);
});

test("button label shows count or analyzing", () => {
  const labels = {
    idle: "重新分析",
    withCount: (n: number) => `重新分析（${n}）`,
    analyzing: "正在分析",
  };
  assert.equal(reanalyzeButtonLabel(0, false, labels), "重新分析");
  assert.equal(reanalyzeButtonLabel(2, false, labels), "重新分析（2）");
  assert.equal(reanalyzeButtonLabel(2, true, labels), "正在分析");
});

test("toggle selection set", () => {
  const a = toggleIdInSet(new Set(), "d1");
  assert.deepEqual([...a], ["d1"]);
  const b = toggleIdInSet(a, "d1");
  assert.deepEqual([...b], []);
});

test("apply results: success updates; failure keeps old", () => {
  const items = [
    { id: "a", school_action: "未核對\n舊 A" },
    { id: "b", school_action: "未核對\n舊 B" },
  ];
  const next = applyReanalyzeResults(items, [
    { document_id: "a", ok: true, school_action: "未核對\n新 A" },
    { document_id: "b", ok: false, school_action: null },
  ]);
  assert.equal(next[0].school_action, "未核對\n新 A");
  assert.equal(next[1].school_action, "未核對\n舊 B");
});

test("apply results updates activities even when LLM fails", () => {
  const items = [
    {
      primary_id: "a",
      variants: [{ id: "a" }, { id: "a-en" }],
      school_action: "舊",
      activities: [],
    },
  ];
  const next = applyReanalyzeResults(items, [
    {
      document_id: "a",
      ok: false,
      school_action: null,
      activities: [{ starts_at: "2026-10-07", deadline_at: "2026-12-02" }],
    },
  ]);
  assert.equal(next[0].school_action, "舊");
  assert.deepEqual(next[0].activities, [{ starts_at: "2026-10-07", deadline_at: "2026-12-02" }]);
});

test("expand selected groups to all variant ids", () => {
  const groups = [
    {
      primary_id: "zh",
      variants: [{ id: "zh" }, { id: "en" }, { id: "sc" }],
    },
    {
      primary_id: "other",
      variants: [{ id: "other" }],
    },
  ];
  assert.deepEqual(expandSelectedDocumentIds(groups, new Set(["zh"])), ["zh", "en", "sc"]);
  assert.deepEqual(expandSelectedDocumentIds(groups, new Set(["other", "zh"])), [
    "zh",
    "en",
    "sc",
    "other",
  ]);
});
