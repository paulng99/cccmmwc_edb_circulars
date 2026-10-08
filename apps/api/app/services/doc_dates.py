"""Fill issue and update dates on documents already stored in the library."""

from __future__ import annotations

import logging

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.doc_dates import apply_document_dates
from app.models.entities import Document, DocumentChunk

logger = logging.getLogger(__name__)

_PARSED_FLAG = "1"
_CHUNK_LIMIT = 8


async def backfill_document_dates(session: AsyncSession) -> dict[str, int]:
    """Read stored text once and record an issue date plus any later update date."""
    parsed = Document.extra["dates_parsed"].astext
    docs = list(
        (
            await session.scalars(
                select(Document).where(or_(parsed.is_(None), parsed != _PARSED_FLAG))
            )
        ).all()
    )
    if not docs:
        return {"checked": 0, "updated": 0}

    chunks = (
        await session.execute(
            select(
                DocumentChunk.document_id,
                DocumentChunk.chunk_index,
                DocumentChunk.content,
            )
            .where(
                DocumentChunk.document_id.in_([doc.id for doc in docs]),
                DocumentChunk.chunk_index < _CHUNK_LIMIT,
            )
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
        )
    ).all()
    by_doc: dict = {}
    for document_id, _index, content in chunks:
        by_doc.setdefault(document_id, []).append(content or "")

    updated = 0
    for doc in docs:
        parts = by_doc.get(doc.id) or []
        text = "\n".join(parts)
        if not text.strip():
            continue
        if apply_document_dates(doc, text):
            updated += 1
        doc.extra = {**(doc.extra or {}), "dates_parsed": _PARSED_FLAG}
    await session.commit()
    logger.info("document date backfill checked=%s updated=%s", len(docs), updated)
    return {"checked": len(docs), "updated": updated}
