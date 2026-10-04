"""Per-document diversity when assembling retrieval hits."""

from __future__ import annotations

import uuid

from app.services.rag import diversify_hits_by_document


def _hit(doc_id: str, idx: int, score: float) -> dict:
    return {
        "document_id": doc_id,
        "chunk_index": idx,
        "score": score,
        "title": f"t-{idx}",
        "content": f"c-{idx}",
    }


def test_diversify_caps_chunks_per_document():
    doc_a = str(uuid.uuid4())
    doc_b = str(uuid.uuid4())
    doc_c = str(uuid.uuid4())
    hits = [
        _hit(doc_a, 0, 1.0),
        _hit(doc_a, 1, 0.99),
        _hit(doc_a, 2, 0.98),
        _hit(doc_a, 3, 0.97),
        _hit(doc_b, 0, 0.5),
        _hit(doc_c, 0, 0.4),
    ]
    out = diversify_hits_by_document(hits, top_k=4, max_per_doc=2)
    assert len(out) == 4
    assert sum(1 for h in out if h["document_id"] == doc_a) == 2
    assert {h["document_id"] for h in out} == {doc_a, doc_b, doc_c}


def test_diversify_backfills_when_not_enough_docs():
    doc_a = str(uuid.uuid4())
    hits = [_hit(doc_a, i, 1.0 - i * 0.01) for i in range(6)]
    out = diversify_hits_by_document(hits, top_k=4, max_per_doc=2)
    assert len(out) == 4
    assert all(h["document_id"] == doc_a for h in out)


def test_diversify_preserves_score_order_within_cap():
    doc_a = str(uuid.uuid4())
    doc_b = str(uuid.uuid4())
    hits = [
        _hit(doc_a, 0, 0.9),
        _hit(doc_b, 0, 0.8),
        _hit(doc_a, 1, 0.7),
        _hit(doc_b, 1, 0.6),
    ]
    out = diversify_hits_by_document(hits, top_k=3, max_per_doc=1)
    assert [h["document_id"] for h in out] == [doc_a, doc_b, doc_a]
    assert out[2]["chunk_index"] == 1
