import assert from "node:assert/strict";
import test from "node:test";
import { agendaDetailLines, agendaTitleLines } from "./agenda-title.ts";

// Fixtures are synthetic (not live circular titles).

test("agendaTitleLines: item then notice as two lines", () => {
  assert.deepEqual(agendaTitleLines("交回問卷", "小學數學科評估安排"), [
    "交回問卷",
    "小學數學科評估安排",
  ]);
});

test("agendaTitleLines: missing item name shows notice title only", () => {
  assert.deepEqual(agendaTitleLines(null, "小學數學科評估安排"), ["小學數學科評估安排"]);
  assert.deepEqual(agendaTitleLines("", "小學數學科評估安排"), ["小學數學科評估安排"]);
  assert.deepEqual(agendaTitleLines("   ", "小學數學科評估安排"), ["小學數學科評估安排"]);
});

test("agendaTitleLines: same text shown once", () => {
  assert.deepEqual(
    agendaTitleLines("校本教師專業發展工作坊", "校本教師專業發展工作坊"),
    ["校本教師專業發展工作坊"],
  );
});

test("agendaTitleLines keeps a long public notice title intact (no truncation helper)", () => {
  const longTitle =
    "優化高中經濟科及公布《經濟課程及評估指引（中四至中六）》（2025年更新）及《補充文件》（2025年更新）";
  assert.deepEqual(agendaTitleLines("交回問卷", longTitle), ["交回問卷", longTitle]);
  assert.equal(agendaTitleLines("交回問卷", longTitle)[1], longTitle);
});

test("agendaDetailLines omits missing summary and location", () => {
  assert.deepEqual(agendaDetailLines(null, null), []);
  assert.deepEqual(agendaDetailLines("", "  "), []);
  assert.deepEqual(agendaDetailLines("一句內容", null), ["一句內容"]);
  assert.deepEqual(agendaDetailLines(null, "學校禮堂"), ["學校禮堂"]);
  assert.deepEqual(agendaDetailLines("一句內容", "學校禮堂"), ["一句內容", "學校禮堂"]);
});
