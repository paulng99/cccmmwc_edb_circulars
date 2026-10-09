import assert from "node:assert/strict";
import test from "node:test";
import {
  applyReanalyzeResults,
  canSubmitReanalyze,
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
