import assert from "node:assert/strict";
import test from "node:test";
import { resolveApiBase } from "./api.ts";

test("empty config uses same-origin proxy", () => {
  assert.equal(resolveApiBase(""), "");
  assert.equal(resolveApiBase(undefined), "");
  assert.equal(resolveApiBase("   "), "");
});

test("loopback config is ignored so remote browsers do not call the visitor machine", () => {
  assert.equal(resolveApiBase("http://127.0.0.1:8008"), "");
  assert.equal(resolveApiBase("http://localhost:8008"), "");
  assert.equal(resolveApiBase("http://LOCALHOST:8008/"), "");
  assert.equal(resolveApiBase("http://[::1]:8008"), "");
  assert.equal(resolveApiBase("http://0.0.0.0:8008"), "");
});

test("public API URL is used as-is", () => {
  assert.equal(resolveApiBase("https://api.example.com"), "https://api.example.com");
  assert.equal(resolveApiBase("http://165.245.184.200:8008/"), "http://165.245.184.200:8008");
});
