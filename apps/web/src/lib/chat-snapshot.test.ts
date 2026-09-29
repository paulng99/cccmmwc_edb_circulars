import assert from "node:assert/strict";
import test from "node:test";
import { mergeTranscript, parseSnapshot, serializeSnapshot, type ChatSnapshot } from "./chat-snapshot.ts";

test("mergeTranscript keeps an optimistic local turn the server has not stored", () => {
  const local = ["q1", "a1", "q2"];
  const server = ["q1", "a1"];
  assert.deepEqual(mergeTranscript(local, server), local);
});

test("mergeTranscript prefers the server once it has caught up", () => {
  const local = ["q1", "a1", "q2"];
  const server = ["q1", "a1", "q2", "a2"];
  assert.deepEqual(mergeTranscript(local, server), server);
});

test("parseSnapshot restores a draft and transcript", () => {
  const snapshot: ChatSnapshot = {
    v: 1,
    sessionId: "abc",
    question: "未送出的問題",
    knowledge: "local",
    programme: "all",
    topic: "all",
    msgs: [{ id: "1", role: "user", content: "你好" }],
  };
  const parsed = parseSnapshot(serializeSnapshot(snapshot));
  assert.deepEqual(parsed, snapshot);
});

test("parseSnapshot rejects corrupt payloads", () => {
  assert.equal(parseSnapshot("not-json"), null);
  assert.equal(parseSnapshot(JSON.stringify({ v: 2 })), null);
});
