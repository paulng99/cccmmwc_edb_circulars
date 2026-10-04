import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Citation } from "./chat-snapshot.ts";
import type { SourceGroup } from "./group-citations.ts";
import {
  chunkOptionLabel,
  documentLabel,
  singleOptionLabel,
} from "./source-option-labels.ts";

function cite(partial: Partial<Citation> & Pick<Citation, "ref">): Citation {
  return {
    title: partial.title ?? "Doc",
    source_url: partial.source_url,
    document_id: partial.document_id,
    circular_no: partial.circular_no,
    issued_at: partial.issued_at,
    chunk_index: partial.chunk_index,
    backend: partial.backend,
    ref: partial.ref,
  };
}

function group(partial: Partial<SourceGroup> & Pick<SourceGroup, "key" | "chunks">): SourceGroup {
  return {
    key: partial.key,
    documentId: partial.documentId,
    title: partial.title ?? "Untitled",
    circular_no: partial.circular_no,
    issued_at: partial.issued_at,
    chunks: partial.chunks,
  };
}

describe("source option labels", () => {
  it("keeps single-source labels compact without date or passage clutter", () => {
    const g = group({
      key: "doc-1",
      documentId: "1",
      title: "姊妹學校計劃",
      circular_no: "EDBCM001/2026",
      issued_at: "2026-01-15",
      chunks: [cite({ ref: "L1", chunk_index: 0 })],
    });
    assert.equal(singleOptionLabel(g, g.chunks[0]), "L1 · 姊妹學校計劃 · EDBCM001/2026");
  });

  it("puts document identity on the group, not each chunk option", () => {
    const g = group({
      key: "doc-2",
      documentId: "2",
      title: "全方位學習",
      circular_no: "EDBCM002/2026",
      chunks: [
        cite({ ref: "L1", chunk_index: 0 }),
        cite({ ref: "L2", chunk_index: 1 }),
      ],
    });
    assert.equal(documentLabel(g), "全方位學習 · EDBCM002/2026");
    assert.equal(
      chunkOptionLabel(g.chunks[0], (index, ref) => `第 ${index} 段（${ref}）`),
      "第 1 段（L1）",
    );
    assert.equal(
      chunkOptionLabel(g.chunks[1], (index, ref) => `第 ${index} 段（${ref}）`),
      "第 2 段（L2）",
    );
  });

  it("falls back to ref when chunk_index is missing", () => {
    assert.equal(chunkOptionLabel(cite({ ref: "D1" }), () => "unused"), "D1");
  });
});
