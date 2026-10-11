import assert from "node:assert/strict";
import test from "node:test";
import { resolveTheme } from "./theme-resolve.ts";

test("resolveTheme prefers explicit light over system dark", () => {
  assert.equal(resolveTheme("light", true), "light");
  assert.equal(resolveTheme("light", false), "light");
});

test("resolveTheme prefers explicit dark over system light", () => {
  assert.equal(resolveTheme("dark", false), "dark");
  assert.equal(resolveTheme("dark", true), "dark");
});

test("resolveTheme falls back to system when storage missing or invalid", () => {
  assert.equal(resolveTheme(null, true), "dark");
  assert.equal(resolveTheme(undefined, false), "light");
  assert.equal(resolveTheme("auto", true), "dark");
  assert.equal(resolveTheme("", false), "light");
});

test("stored theme is unchanged by a conceptual locale switch", () => {
  // Language and theme must stay independent: resolving the same stored value
  // before/after a locale change must yield the same theme.
  const before = resolveTheme("dark", false);
  const afterLocaleSwitch = resolveTheme("dark", false);
  assert.equal(before, "dark");
  assert.equal(afterLocaleSwitch, "dark");
  assert.equal(resolveTheme("light", true), "light");
});
