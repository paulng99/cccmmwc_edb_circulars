"""Repair document title / circular_no / language from stored file_url and row_text."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.circular_meta import (
    extract_subject,
    is_language_label,
    resolve_circular_no,
    resolve_language,
    resolve_title,
)
from app.models.entities import Document


async def fix_document_metadata(session: AsyncSession) -> dict:
    rows = list((await session.scalars(select(Document))).all())
    updated = 0
    for doc in rows:
        extra = dict(doc.extra or {})
        row_text = extra.get("row_text") or ""
        link_label = extra.get("link_label") or ""
        subject = extract_subject(row_text) if row_text else None

        new_circ = resolve_circular_no(row_text=row_text, file_url=doc.file_url) or doc.circular_no
        new_lang = resolve_language(
            link_text=link_label or (doc.title if is_language_label(doc.title) else None),
            file_url=doc.file_url,
            fallback=doc.language or "zh-HK",
        )
        new_title = resolve_title(
            subject=subject,
            row_text=row_text,
            link_text=None if is_language_label(doc.title) else doc.title,
            file_url=doc.file_url,
        )
        # Prefer existing good title over filename fallback
        if not is_language_label(doc.title) and (not subject or is_language_label(new_title)):
            new_title = doc.title

        changed = False
        if new_circ and new_circ != doc.circular_no:
            doc.circular_no = new_circ
            changed = True
        if new_lang and new_lang != doc.language:
            doc.language = new_lang
            changed = True
        if new_title and new_title != doc.title:
            doc.title = new_title[:1000]
            changed = True
        if changed:
            updated += 1

    if updated:
        await session.commit()
    return {"total": len(rows), "updated": updated}
