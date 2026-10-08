"""Backfill activity dates/details on documents already in the library."""

from __future__ import annotations

import logging

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.activity_dates import apply_document_activities
from app.models.entities import Document, DocumentChunk

logger = logging.getLogger(__name__)

# Bump when stored activity shape changes so existing rows are re-extracted on boot.
_PARSED_FLAG = "2"
_CHUNK_LIMIT = 12


async def backfill_document_activities(session: AsyncSession) -> dict[str, int]:
    """Read stored chunk text and fill Document.activities (local regex only)."""
    parsed = Document.extra["activities_parsed"].astext
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
        if text.strip() and apply_document_activities(doc, text):
            updated += 1
        elif not text.strip() and not (doc.activities or []):
            # No text — leave empty activities, still mark parsed.
            doc.activities = []
        doc.extra = {**(doc.extra or {}), "activities_parsed": _PARSED_FLAG}
    await session.commit()
    logger.info("document activity backfill checked=%s updated=%s", len(docs), updated)
    return {"checked": len(docs), "updated": updated}
