import assert from "node:assert/strict";
import test from "node:test";
import { displaySchoolAction, UNVERIFIED_PREFIX } from "./school-action.ts";

test("strips unverified prefix and newline", () => {
  assert.equal(displaySchoolAction(`${UNVERIFIED_PREFIX}\n學校須交回表格。`), "學校須交回表格。");
});

test("returns empty for blank or prefix-only", () => {
  assert.equal(displaySchoolAction(null), "");
  assert.equal(displaySchoolAction("   "), "");
  assert.equal(displaySchoolAction(UNVERIFIED_PREFIX), "");
});

test("leaves text without prefix unchanged", () => {
  assert.equal(displaySchoolAction("人手核對後的撮要"), "人手核對後的撮要");
});
