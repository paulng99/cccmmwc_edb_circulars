from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Document, DocumentChunk
from app.services.embeddings import get_embedding_backend
from app.services.ingest import chunk_text, extract_text_from_pdf
from app.services.storage import get_object_bytes
from app.services.dify import get_dify_sync


async def index_document(session: AsyncSession, document_id: uuid.UUID) -> dict[str, Any]:
    doc = await session.get(Document, document_id)
    if not doc or not doc.storage_key:
        return {"ok": False, "error": "document not found or no file"}

    doc.status = "indexing"
    await session.commit()

    try:
        raw = get_object_bytes(doc.storage_key)
        text = extract_text_from_pdf(raw) if doc.mime_type == "application/pdf" else raw.decode("utf-8", errors="ignore")
        chunks = chunk_text(text)
        if not chunks:
            doc.status = "ready"
            doc.extra = {**(doc.extra or {}), "warning": "no text extracted"}
            await session.commit()
            return {"ok": True, "chunks": 0}

        await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
        embedder = get_embedding_backend()
        # batch embeddings
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
        await session.commit()

        sync = get_dify_sync()
        await sync.sync_document(session, doc)

        return {"ok": True, "chunks": len(chunks)}
    except Exception as exc:  # noqa: BLE001
        doc.status = "failed"
        doc.extra = {**(doc.extra or {}), "index_error": str(exc)}
        await session.commit()
        return {"ok": False, "error": str(exc)}


async def retrieve_chunks(
    session: AsyncSession,
    query: str,
    top_k: int = 8,
) -> list[dict[str, Any]]:
    embedder = get_embedding_backend()
    vectors = await embedder.embed([query])
    if not vectors:
        return []
    qvec = vectors[0]
    # pgvector cosine distance
    sql = text(
        """
        SELECT c.id, c.document_id, c.content, c.chunk_index,
               d.title, d.circular_no, d.issued_at, d.source_url, d.language,
               1 - (c.embedding <=> CAST(:embedding AS vector)) AS score
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.status = 'ready' AND c.embedding IS NOT NULL
        ORDER BY c.embedding <=> CAST(:embedding AS vector)
        LIMIT :top_k
        """
    )
    # format embedding as pgvector literal
    emb_literal = "[" + ",".join(str(float(x)) for x in qvec) + "]"
    result = await session.execute(sql, {"embedding": emb_literal, "top_k": top_k})
    rows = result.mappings().all()
    return [
        {
            "chunk_id": str(r["id"]),
            "document_id": str(r["document_id"]),
            "content": r["content"],
            "chunk_index": r["chunk_index"],
            "title": r["title"],
            "circular_no": r["circular_no"],
            "issued_at": r["issued_at"].isoformat() if r["issued_at"] else None,
            "source_url": r["source_url"],
            "language": r["language"],
            "score": float(r["score"]) if r["score"] is not None else 0.0,
        }
        for r in rows
    ]
