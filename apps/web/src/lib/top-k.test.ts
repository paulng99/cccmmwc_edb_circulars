import assert from "node:assert/strict";
import test from "node:test";
import { isValidTopK } from "./top-k.ts";

test("accepts integers from 1 to 20", () => {
  assert.equal(isValidTopK(1), true);
  assert.equal(isValidTopK(12), true);
  assert.equal(isValidTopK(20), true);
});

test("rejects out of range and non-integers", () => {
  assert.equal(isValidTopK(0), false);
  assert.equal(isValidTopK(-1), false);
  assert.equal(isValidTopK(21), false);
  assert.equal(isValidTopK(120), false);
  assert.equal(isValidTopK(1.5), false);
  assert.equal(isValidTopK("12"), false);
  assert.equal(isValidTopK(""), false);
  assert.equal(isValidTopK(null), false);
  assert.equal(isValidTopK(undefined), false);
  assert.equal(isValidTopK(NaN), false);
});
