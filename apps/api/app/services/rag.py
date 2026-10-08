from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Any

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.doc_dates import apply_document_dates
from app.models.entities import Document, DocumentChunk
from app.services.dify import get_dify_sync
from app.services.embeddings import get_embedding_backend
from app.services.ingest import chunk_text, extract_text_from_pdf
from app.services.storage import get_object_bytes
from app.services.usage import usage_scope

logger = logging.getLogger(__name__)
_PDF_EXTRACT_TIMEOUT_SECONDS = 90

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
            # pypdf can block forever on a bad file. Run it off the event loop
            # so one document cannot freeze the crawl progress bar.
            text = await asyncio.wait_for(
                asyncio.to_thread(extract_text_from_pdf, raw),
                timeout=_PDF_EXTRACT_TIMEOUT_SECONDS,
            )
        else:
            text = raw.decode("utf-8", errors="ignore")
        if text and text.strip():
            apply_document_dates(doc, text)
            doc.extra = {**(doc.extra or {}), "dates_parsed": "1"}
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
            with usage_scope("embed_index"):
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


_ACADEMIC_YEAR_RE = re.compile(r"\d{4}\s*[/\-]\s*\d{2,4}")
_ACADEMIC_YEAR_TERM_RE = re.compile(r"^\d{4}/\d{2,4}$")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")


def _normalize_academic_year(raw: str) -> str:
    """Normalize academic-year spans to slash form (e.g. 2026-27 → 2026/27)."""
    return re.sub(r"\s+", "", raw or "").replace("-", "/")


def _query_terms(query: str) -> list[str]:
    """Extract searchable terms for ILIKE hybrid retrieval.

    Prefer academic years (2026/27) over bare years (2026). Bare 4-digit years
    match too many chunks via ILIKE and drown out title hits with NULL issued_at.
    """
    q = (query or "").strip()
    if not q:
        return []
    terms: list[str] = []

    def _add(term: str) -> None:
        t = (term or "").replace(" ", "").strip()
        if len(t) >= 2 and t not in terms:
            terms.append(t)

    # Full query (truncated) for phrase match
    if len(q) >= 2:
        _add(q[:80])

    # Academic year before other tokens (e.g. 2026/27, 2026-27, 2025/2026)
    for m in _ACADEMIC_YEAR_RE.finditer(q):
        _add(_normalize_academic_year(m.group(0)))

    # Chinese 2–8 char grams + Latin words / EDBC numbers (no bare \\d{4})
    for m in re.finditer(r"[\u4e00-\u9fff]{2,8}|[A-Za-z]{3,}|EDBC(?:M)?\s*\d+/\d{4}", q, re.I):
        _add(m.group(0))
    return terms[:12]


def _cjk_bigram_overlap(query: str, title: str) -> float:
    """Share of query CJK bigrams that also appear in the title (0–1)."""
    q_cjk = "".join(_CJK_RUN_RE.findall(query or ""))
    t_cjk = "".join(_CJK_RUN_RE.findall(title or ""))
    if len(q_cjk) < 2 or not t_cjk:
        return 0.0
    bigrams = {q_cjk[i : i + 2] for i in range(len(q_cjk) - 1)}
    if not bigrams:
        return 0.0
    return sum(1 for b in bigrams if b in t_cjk) / len(bigrams)


def _keyword_score(
    terms: list[str],
    title: str,
    circular_no: str | None,
    content: str,
    query: str | None = None,
) -> float:
    """Score a keyword hit; title/circular matches outrank weak content-only hits."""
    title_blob = f"{title or ''} {circular_no or ''}"
    blob = f"{title_blob} {content or ''}"
    hits_count = sum(1 for t in terms if t.lower() in blob.lower() or t in blob)
    title_hits = sum(1 for t in terms if t in title_blob or t.lower() in title_blob.lower())
    # Skip the full-query phrase when counting "strong" title hits (often has spaces).
    strong_title = sum(
        1
        for t in terms[1:]
        if len(t) >= 4 and (t in title_blob or t.lower() in title_blob.lower())
    )
    score = 0.40 + 0.06 * hits_count + 0.20 * title_hits
    if strong_title:
        score += 0.16

    # Academic-year in title is a strong intent signal for EDB circulars.
    if any(_ACADEMIC_YEAR_TERM_RE.match(t) and t in title_blob for t in terms):
        score += 0.22

    # Near-title: query CJK bigrams overlapping the title (handles inserted words
    # like 「全方位學習及姊妹學校津貼」 vs query 「全方位學習津貼」).
    overlap_query = query if query is not None else (terms[0] if terms else "")
    overlap = _cjk_bigram_overlap(overlap_query, title or "")
    score += 0.30 * overlap
    if title_hits >= 1 and overlap >= 0.4:
        score += 0.08

    return min(score, 0.99)


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
        with usage_scope("embed_query"):
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
    """Keyword ILIKE retrieval with title-first pass so undated docs are not dropped."""
    terms = _query_terms(query)
    if not terms:
        return []

    filt_params: dict[str, Any] = {}
    filt = _filter_sql(programme=programme, topic=topic, params=filt_params)

    def _term_clauses(prefix: str, fields: list[str]) -> tuple[str, dict[str, Any]]:
        params: dict[str, Any] = {}
        clauses: list[str] = []
        for i, term in enumerate(terms):
            key = f"{prefix}{i}"
            params[key] = f"%{term}%"
            field_or = " OR ".join(f"{f} ILIKE :{key}" for f in fields)
            clauses.append(f"({field_or})")
        return " OR ".join(clauses), params

    title_where, title_params = _term_clauses(
        "t", ["d.title", "COALESCE(d.circular_no, '')"]
    )
    content_where, content_params = _term_clauses(
        "c", ["d.title", "COALESCE(d.circular_no, '')", "c.content"]
    )

    # Pass 1: title / circular only — keeps NULL issued_at docs that match the name.
    title_limit = max(top_k * 2, 24)
    title_sql = text(
        f"""
        SELECT c.id, c.document_id, c.content, c.chunk_index,
               d.title, d.circular_no, d.issued_at, d.source_url, d.language
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.status = 'ready'
          AND ({title_where})
          {filt}
        LIMIT :limit
        """
    )
    title_bind = {**filt_params, **title_params, "limit": title_limit}
    title_rows = (await session.execute(title_sql, title_bind)).mappings().all()

    # Pass 2: content (and title) — still useful, but must not crowd out pass 1.
    content_limit = max(top_k * 3, 24)
    content_sql = text(
        f"""
        SELECT c.id, c.document_id, c.content, c.chunk_index,
               d.title, d.circular_no, d.issued_at, d.source_url, d.language
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.status = 'ready'
          AND ({content_where})
          {filt}
        ORDER BY d.issued_at DESC NULLS LAST
        LIMIT :limit
        """
    )
    content_bind = {**filt_params, **content_params, "limit": content_limit}
    content_rows = (await session.execute(content_sql, content_bind)).mappings().all()

    by_key: dict[str, dict[str, Any]] = {}
    for r in list(title_rows) + list(content_rows):
        key = f"{r['document_id']}:{r['chunk_index']}"
        if key in by_key:
            continue
        score = _keyword_score(
            terms,
            r["title"] or "",
            r["circular_no"],
            r["content"] or "",
            query=query,
        )
        by_key[key] = _row_to_hit(r, score=score, match="keyword")

    hits = sorted(by_key.values(), key=lambda h: float(h["score"]), reverse=True)
    return hits[:top_k]


# Cap how many chunks from one document fill the final context window.
MAX_CHUNKS_PER_DOCUMENT = 2


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


def diversify_hits_by_document(
    hits: list[dict[str, Any]],
    top_k: int,
    *,
    max_per_doc: int = MAX_CHUNKS_PER_DOCUMENT,
) -> list[dict[str, Any]]:
    """Keep score order but cap chunks per document_id; backfill if under-filled."""
    if top_k <= 0:
        return []
    if max_per_doc <= 0:
        return list(hits[:top_k])

    selected: list[dict[str, Any]] = []
    per_doc: dict[str, int] = {}
    deferred: list[dict[str, Any]] = []
    for hit in hits:
        doc_id = str(hit.get("document_id") or "")
        count = per_doc.get(doc_id, 0)
        if count < max_per_doc:
            selected.append(hit)
            per_doc[doc_id] = count + 1
            if len(selected) >= top_k:
                return selected
        else:
            deferred.append(hit)
    for hit in deferred:
        if len(selected) >= top_k:
            break
        selected.append(hit)
    return selected


async def retrieve_vector_only(
    session: AsyncSession,
    query: str,
    top_k: int = 8,
    *,
    programme: str | None = None,
    topic: str | None = None,
    match: str = "vector",
) -> list[dict[str, Any]]:
    """pgvector-only retrieve (used by HyDE: embed a hypothetical passage as the query)."""
    prog = programme if programme in _VALID_PROGRAMMES else None
    top = topic if topic in _VALID_TOPICS else None
    hits = await _vector_retrieve(session, query, top_k, programme=prog, topic=top)
    if match != "vector":
        for hit in hits:
            hit["match"] = match
    return hits


async def retrieve_document_chunks(
    session: AsyncSession,
    document_id: uuid.UUID,
    *,
    query: str = "",
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """Fetch top chunks from one document (vector-ranked when query embeds, else by index)."""
    limit = max(1, min(int(top_k), 20))
    q = (query or "").strip()
    if q:
        try:
            embedder = get_embedding_backend()
            with usage_scope("embed_query"):
                vectors = await embedder.embed([q])
            if vectors:
                emb_literal = "[" + ",".join(str(float(x)) for x in vectors[0]) + "]"
                sql = text(
                    """
                    SELECT c.id, c.document_id, c.content, c.chunk_index,
                           d.title, d.circular_no, d.issued_at, d.source_url, d.language,
                           1 - (c.embedding <=> CAST(:embedding AS vector)) AS score
                    FROM document_chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE c.document_id = :document_id
                      AND d.status = 'ready'
                      AND c.embedding IS NOT NULL
                    ORDER BY c.embedding <=> CAST(:embedding AS vector)
                    LIMIT :top_k
                    """
                )
                result = await session.execute(
                    sql,
                    {
                        "document_id": document_id,
                        "embedding": emb_literal,
                        "top_k": limit,
                    },
                )
                rows = result.mappings().all()
                if rows:
                    return [
                        _row_to_hit(
                            r,
                            score=float(r["score"]) if r["score"] is not None else 0.0,
                            match="focus",
                        )
                        for r in rows
                    ]
        except Exception:
            logger.exception("Focus-document vector retrieve failed; falling back to index order")

    sql = text(
        """
        SELECT c.id, c.document_id, c.content, c.chunk_index,
               d.title, d.circular_no, d.issued_at, d.source_url, d.language
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.document_id = :document_id
          AND d.status = 'ready'
        ORDER BY c.chunk_index ASC
        LIMIT :top_k
        """
    )
    result = await session.execute(sql, {"document_id": document_id, "top_k": limit})
    return [
        _row_to_hit(r, score=1.0 - (i * 0.01), match="focus")
        for i, r in enumerate(result.mappings().all())
    ]


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
    # Fetch extra candidates so per-document diversity still fills top_k.
    fetch_k = max(top_k * 3, 12)
    vector_hits = await _vector_retrieve(
        session, query, fetch_k, programme=prog, topic=top
    )
    keyword_hits = await _keyword_retrieve(
        session, query, fetch_k, programme=prog, topic=top
    )
    if not vector_hits and not keyword_hits:
        return []
    if not vector_hits:
        return diversify_hits_by_document(keyword_hits, top_k)
    if not keyword_hits:
        return diversify_hits_by_document(vector_hits, top_k)
    merged = _merge_hits(vector_hits, keyword_hits, fetch_k)
    return diversify_hits_by_document(merged, top_k)
