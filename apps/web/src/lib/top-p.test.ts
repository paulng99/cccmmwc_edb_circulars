import assert from "node:assert/strict";
import test from "node:test";
import { isValidTopP } from "./top-p.ts";

test("accepts empty as unset", () => {
  assert.equal(isValidTopP(""), true);
  assert.equal(isValidTopP(null), true);
  assert.equal(isValidTopP(undefined), true);
});

test("accepts numbers from 0 to 1 inclusive", () => {
  assert.equal(isValidTopP(0), true);
  assert.equal(isValidTopP(0.0), true);
  assert.equal(isValidTopP(0.9), true);
  assert.equal(isValidTopP(1), true);
  assert.equal(isValidTopP(1.0), true);
});

test("rejects out of range and non-numbers", () => {
  assert.equal(isValidTopP(-0.1), false);
  assert.equal(isValidTopP(1.5), false);
  assert.equal(isValidTopP("abc"), false);
  assert.equal(isValidTopP("0.9"), false);
  assert.equal(isValidTopP(true), false);
  assert.equal(isValidTopP(false), false);
  assert.equal(isValidTopP(NaN), false);
});
