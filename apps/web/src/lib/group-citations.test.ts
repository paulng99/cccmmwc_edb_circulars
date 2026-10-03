import assert from "node:assert/strict";
import test from "node:test";
import { groupCitationsByDocument } from "./group-citations.ts";
import type { Citation } from "./chat-snapshot.ts";

const citations: Citation[] = [
  { ref: "L1", document_id: "doc-a", title: "通告甲", circular_no: "A/1", issued_at: "2026-01-01", chunk_index: 0 },
  { ref: "L2", document_id: "doc-a", title: "通告甲", circular_no: "A/1", issued_at: "2026-01-01", chunk_index: 1 },
  { ref: "L3", document_id: "doc-b", title: "通告乙", circular_no: "B/1", issued_at: "2026-02-01", chunk_index: 0 },
  { ref: "D1", title: "Dify 來源", backend: "dify" },
];

test("groups same document_id and keeps dify separate", () => {
  const groups = groupCitationsByDocument(citations, "先提 [L3]，再提 [L1]");
  assert.equal(groups.length, 3);
  assert.equal(groups[0].documentId, "doc-b");
  assert.equal(groups[0].chunks.length, 1);
  assert.equal(groups[1].documentId, "doc-a");
  assert.equal(groups[1].chunks.map((c) => c.ref).join(","), "L1,L2");
  assert.equal(groups[2].chunks[0].ref, "D1");
  assert.equal(groups[2].documentId, undefined);
});

test("uncited documents keep original order after cited ones", () => {
  const groups = groupCitationsByDocument(citations, "只引用 [L1]");
  assert.equal(groups[0].documentId, "doc-a");
  assert.equal(groups[1].documentId, "doc-b");
  assert.equal(groups[2].chunks[0].ref, "D1");
});
