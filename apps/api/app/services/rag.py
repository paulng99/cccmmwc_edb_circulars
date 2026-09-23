from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Document, DocumentChunk
from app.services.dify import get_dify_sync
from app.services.embeddings import get_embedding_backend
from app.services.ingest import chunk_text, extract_text_from_pdf
from app.services.storage import get_object_bytes

logger = logging.getLogger(__name__)

_VALID_PROGRAMMES = frozenset({"circular", "sister_school", "lwlssg", "other"})
_VALID_TOPICS = frozenset(
    {
        "grant_funding",
        "curriculum",
        "admin",
        "student_activity",
        "parent_home",
        "other",
    }
)


async def index_document(session: AsyncSession, document_id: uuid.UUID) -> dict[str, Any]:
    doc = await session.get(Document, document_id)
    if not doc or not doc.storage_key:
        return {"ok": False, "error": "document not found or no file"}

    doc.status = "indexing"
    await session.commit()

    try:
        raw = get_object_bytes(doc.storage_key)
        if doc.mime_type == "application/pdf" or (doc.storage_key or "").lower().endswith(".pdf"):
            text = extract_text_from_pdf(raw)
        else:
            text = raw.decode("utf-8", errors="ignore")
        chunks = chunk_text(text)
        if not chunks:
            doc.status = "ready"
            doc.extra = {**(doc.extra or {}), "warning": "no text extracted"}
            try:
                from app.services.classify import apply_classification

                await apply_classification(doc, use_llm=True, force_topics=False)
            except Exception:
                logger.exception("Classification failed for %s", document_id)
            await session.commit()
            return {"ok": True, "chunks": 0}

        await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
        embedder = get_embedding_backend()
        batch_size = 16
        all_vectors: list[list[float]] = []
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            all_vectors.extend(await embedder.embed(batch))

        for idx, (content, vec) in enumerate(zip(chunks, all_vectors)):
            session.add(
                DocumentChunk(
                    document_id=doc.id,
                    chunk_index=idx,
                    content=content,
                    embedding=vec,
                    token_count=len(content.split()),
                )
            )
        doc.status = "ready"
        try:
            from app.services.classify import apply_classification

            await apply_classification(doc, use_llm=True, force_topics=False)
        except Exception:
            logger.exception("Classification failed for %s", document_id)
        await session.commit()

        sync = get_dify_sync()
        await sync.sync_document(session, doc)

        return {"ok": True, "chunks": len(chunks)}
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        doc = await session.get(Document, document_id)
        if doc:
            doc.status = "failed"
            doc.extra = {**(doc.extra or {}), "index_error": str(exc)[:2000]}
            await session.commit()
        return {"ok": False, "error": str(exc)}


def _row_to_hit(r: Any, *, score: float, match: str) -> dict[str, Any]:
    return {
        "chunk_id": str(r["id"]),
        "document_id": str(r["document_id"]),
        "content": r["content"],
        "chunk_index": r["chunk_index"],
        "title": r["title"],
        "circular_no": r["circular_no"],
        "issued_at": r["issued_at"].isoformat() if r["issued_at"] else None,
        "source_url": r["source_url"],
        "language": r["language"],
        "score": score,
        "match": match,
    }


def _query_terms(query: str) -> list[str]:
    """Extract searchable terms for ILIKE hybrid retrieval."""
    q = (query or "").strip()
    if not q:
        return []
    terms: list[str] = []
    # Full query (truncated) for phrase match
    if len(q) >= 2:
        terms.append(q[:80])
    # Chinese 2–4 char grams + alphanumerics / EDBC numbers
    for m in re.finditer(r"[\u4e00-\u9fff]{2,8}|[A-Za-z]{3,}|EDBC(?:M)?\s*\d+/\d{4}|\d{4}", q, re.I):
        t = m.group(0).replace(" ", "")
        if t not in terms:
            terms.append(t)
    return terms[:12]


def _filter_sql(
    *,
    programme: str | None,
    topic: str | None,
    params: dict[str, Any],
) -> str:
    parts: list[str] = []
    if programme:
        params["programme"] = programme
        parts.append("AND d.programme = :programme")
    if topic:
        params["topic_json"] = json.dumps([topic])
        parts.append("AND d.topics @> CAST(:topic_json AS jsonb)")
    return " ".join(parts)


async def _vector_retrieve(
    session: AsyncSession,
    query: str,
    top_k: int,
    *,
    programme: str | None = None,
    topic: str | None = None,
) -> list[dict[str, Any]]:
    try:
        embedder = get_embedding_backend()
        vectors = await embedder.embed([query])
    except Exception:
        logger.exception("Query embedding failed; falling back to keyword search")
        return []
    if not vectors:
        return []
    qvec = vectors[0]
    emb_literal = "[" + ",".join(str(float(x)) for x in qvec) + "]"
    params: dict[str, Any] = {"embedding": emb_literal, "top_k": top_k}
    filt = _filter_sql(programme=programme, topic=topic, params=params)
    sql = text(
        f"""
        SELECT c.id, c.document_id, c.content, c.chunk_index,
               d.title, d.circular_no, d.issued_at, d.source_url, d.language,
               1 - (c.embedding <=> CAST(:embedding AS vector)) AS score
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.status = 'ready' AND c.embedding IS NOT NULL
        {filt}
        ORDER BY c.embedding <=> CAST(:embedding AS vector)
        LIMIT :top_k
        """
    )
    result = await session.execute(sql, params)
    return [
        _row_to_hit(r, score=float(r["score"]) if r["score"] is not None else 0.0, match="vector")
        for r in result.mappings().all()
    ]


async def _keyword_retrieve(
    session: AsyncSession,
    query: str,
    top_k: int,
    *,
    programme: str | None = None,
    topic: str | None = None,
) -> list[dict[str, Any]]:
    terms = _query_terms(query)
    if not terms:
        return []

    params: dict[str, Any] = {"limit": max(top_k * 3, 24)}
    clauses: list[str] = []
    for i, term in enumerate(terms):
        key = f"p{i}"
        params[key] = f"%{term}%"
        clauses.append(
            f"(d.title ILIKE :{key} OR COALESCE(d.circular_no, '') ILIKE :{key} OR c.content ILIKE :{key})"
        )
    where_sql = " OR ".join(clauses)
    filt = _filter_sql(programme=programme, topic=topic, params=params)
    sql = text(
        f"""
        SELECT c.id, c.document_id, c.content, c.chunk_index,
               d.title, d.circular_no, d.issued_at, d.source_url, d.language
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.status = 'ready'
          AND ({where_sql})
          {filt}
        ORDER BY d.issued_at DESC NULLS LAST
        LIMIT :limit
        """
    )
    result = await session.execute(sql, params)
    hits: list[dict[str, Any]] = []
    for r in result.mappings().all():
        blob = f"{r['title'] or ''} {r['circular_no'] or ''} {r['content'] or ''}"
        hits_count = sum(1 for t in terms if t.lower() in blob.lower() or t in blob)
        title_blob = f"{r['title'] or ''} {r['circular_no'] or ''}"
        title_hits = sum(1 for t in terms if t in title_blob or t.lower() in title_blob.lower())
        score = 0.45 + 0.08 * hits_count + 0.12 * title_hits
        hits.append(_row_to_hit(r, score=min(score, 0.99), match="keyword"))
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:top_k]


def _merge_hits(
    vector_hits: list[dict[str, Any]],
    keyword_hits: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for h in vector_hits:
        key = f"{h['document_id']}:{h['chunk_index']}"
        by_key[key] = dict(h)
    for h in keyword_hits:
        key = f"{h['document_id']}:{h['chunk_index']}"
        if key in by_key:
            # Boost when both vector and keyword agree
            existing = by_key[key]
            existing["score"] = min(1.0, float(existing["score"]) + 0.15)
            existing["match"] = "hybrid"
        else:
            by_key[key] = dict(h)
    merged = sorted(by_key.values(), key=lambda x: float(x["score"]), reverse=True)
    return merged[:top_k]


async def retrieve_chunks(
    session: AsyncSession,
    query: str,
    top_k: int = 8,
    *,
    programme: str | None = None,
    topic: str | None = None,
) -> list[dict[str, Any]]:
    """Hybrid retrieval: pgvector + keyword ILIKE, merged by score."""
    prog = programme if programme in _VALID_PROGRAMMES else None
    top = topic if topic in _VALID_TOPICS else None
    fetch_k = max(top_k * 2, 12)
    vector_hits = await _vector_retrieve(
        session, query, fetch_k, programme=prog, topic=top
    )
    keyword_hits = await _keyword_retrieve(
        session, query, fetch_k, programme=prog, topic=top
    )
    if not vector_hits and not keyword_hits:
        return []
    if not vector_hits:
        return keyword_hits[:top_k]
    if not keyword_hits:
        return vector_hits[:top_k]
    return _merge_hits(vector_hits, keyword_hits, top_k)
